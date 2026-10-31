import os
import pickle
import tempfile

from pathlib import Path

import numpy as np
import pandas as pd

from sqlalchemy import URL, create_engine, text


BACKEND_DIR = Path(__file__).resolve().parents[2]

CHECKPOINT_PATH = (
    BACKEND_DIR / "checkpoint" / "svd.pkl"
)


class SVDRepository:
    def __init__(self):
        url = URL.create(
            drivername="postgresql+psycopg",
            username=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            host=os.environ["POSTGRES_HOST"],
            port=int(os.environ["POSTGRES_PORT"]),
            database=os.environ["POSTGRES_DB"],
        )

        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 10},
        )

    def read_ratings(self):
        query = text("""
            SELECT
                user_id,
                movie_id,
                rating
            FROM public.ratings
        """)

        chunks = []

        with self.engine.connect() as connection:
            connection = connection.execution_options(
                stream_results=True
            )

            for chunk in pd.read_sql_query(
                query,
                connection,
                chunksize=100_000,
            ):
                chunk = chunk.astype({
                    "user_id": "int64",
                    "movie_id": "int64",
                    "rating": "float32",
                })

                chunks.append(chunk)

        if not chunks:
            raise ValueError(
                "ratings 테이블에 평점이 없습니다."
            )

        frame = pd.concat(
            chunks,
            ignore_index=True,
        )

        if frame.isna().any().any():
            raise ValueError(
                "평점 데이터에 빈 값이 있습니다."
            )

        if not np.isfinite(
            frame["rating"].to_numpy()
        ).all():
            raise ValueError(
                "평점에 무한대 등 잘못된 값이 있습니다."
            )

        if frame.duplicated(
            ["user_id", "movie_id"]
        ).any():
            raise ValueError(
                "같은 고객·영화의 평점이 중복돼 있습니다."
            )

        return frame

    def find_movies(self, movie_ids):
        if not movie_ids:
            return {}

        query = text("""
            SELECT
                movie_id,
                title,
                genres
            FROM public.movies
            WHERE movie_id = ANY(
                CAST(:movie_ids AS bigint[])
            )
        """)

        with self.engine.connect() as connection:
            rows = connection.execute(
                query,
                {"movie_ids": movie_ids},
            ).mappings().all()

        return {
            int(row["movie_id"]): dict(row)
            for row in rows
        }

    def load_model(self):
        if not CHECKPOINT_PATH.is_file():
            return None

        # 직접 생성한 로컬 체크포인트만 읽는다.
        with CHECKPOINT_PATH.open("rb") as file:
            model = pickle.load(file)

        if getattr(model, "version", None) != 1:
            raise ValueError(
                "체크포인트 버전이 맞지 않습니다. "
                "SVD를 다시 학습하세요."
            )

        return model

    def save_model(self, model):
        CHECKPOINT_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=CHECKPOINT_PATH.parent,
                prefix="svd-",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)

                pickle.dump(
                    model,
                    file,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )

                file.flush()
                os.fsync(file.fileno())

            # 저장 완료 후 최종 파일로 교체한다.
            os.replace(
                temporary_path,
                CHECKPOINT_PATH,
            )

        finally:
            if (
                temporary_path is not None
                and temporary_path.exists()
            ):
                temporary_path.unlink()

    def close(self):
        self.engine.dispose()