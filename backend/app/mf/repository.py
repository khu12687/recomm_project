import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from sqlalchemy import (
    URL,
    create_engine,
    text,
)


BACKEND_DIR = Path(__file__).resolve().parents[2]

CHECKPOINT_PATH = (
    BACKEND_DIR / "checkpoint" / "mf.pt"
)


class MFRepository:
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
            connect_args={
                "connect_timeout": 10,
            },
        )

    def close(self):
        self.engine.dispose()

    def read_ratings(self):
        query = text("""
            SELECT
                user_id,
                movie_id,
                rating
            FROM public.ratings
            ORDER BY user_id, movie_id
        """)

        chunks = []

        with self.engine.connect() as connection:
            connection = (
                connection.execution_options(
                    stream_results=True
                )
            )

            for chunk in pd.read_sql_query(
                query,
                connection,
                chunksize=100_000,
            ):
                chunks.append(
                    chunk.astype({
                        "user_id": "int64",
                        "movie_id": "int64",
                        "rating": "float32",
                    })
                )

        if not chunks:
            raise ValueError(
                "ratings 테이블이 비어 있습니다."
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
                "평점에 유효하지 않은 값이 있습니다."
            )

        if frame.duplicated(
            ["user_id", "movie_id"]
        ).any():
            raise ValueError(
                "고객·영화 평점이 중복돼 있습니다."
            )

        return frame

    def find_seen_movie_ids(self, user_id):
        query = text("""
            SELECT movie_id
            FROM public.ratings
            WHERE user_id = :user_id
        """)

        with self.engine.connect() as connection:
            rows = connection.execute(
                query,
                {"user_id": user_id},
            ).scalars().all()

        return {
            int(movie_id)
            for movie_id in rows
        }

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

    def save_checkpoint(self, checkpoint):
        CHECKPOINT_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=CHECKPOINT_PATH.parent,
                prefix="mf-",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(
                    file.name
                )

                torch.save(
                    checkpoint,
                    file,
                )

                file.flush()
                os.fsync(file.fileno())

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

    def load_checkpoint(self):
        if not CHECKPOINT_PATH.is_file():
            return None

        checkpoint = torch.load(
            CHECKPOINT_PATH,
            map_location="cpu",
            weights_only=True,
        )

        if checkpoint.get("version") != 1:
            raise ValueError(
                "MF 체크포인트 버전이 맞지 않습니다."
            )

        return checkpoint