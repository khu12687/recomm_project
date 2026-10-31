import os
import tempfile
from pathlib import Path
from threading import Lock

import numpy as np
import pandas as pd
import torch

from sqlalchemy import URL, create_engine, text


BACKEND_DIR = Path(__file__).resolve().parents[2]

SOURCE_PATH = (
    BACKEND_DIR / "app" / "data" / "ratings.pkl"
)

CHECKPOINT_PATH = (
    BACKEND_DIR / "checkpoint" / "transformer.pt"
)


class TransformerRepository:
    def __init__(self):
        url = URL.create(
            "postgresql+psycopg",
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

        self._timestamps = None
        self._timestamp_lock = Lock()

    def close(self):
        self.engine.dispose()
        self._timestamps = None

    def _get_timestamps(self):
        if self._timestamps is not None:
            return self._timestamps

        with self._timestamp_lock:
            if self._timestamps is not None:
                return self._timestamps

            if not SOURCE_PATH.is_file():
                raise FileNotFoundError(
                    "DB에 timestamp가 없으므로 "
                    "backend/app/data/ratings.pkl이 필요합니다."
                )

            source = pd.read_pickle(SOURCE_PATH)

            required = {
                "userID",
                "movieID",
                "timestamp",
            }

            if not required.issubset(source.columns):
                raise ValueError(
                    "ratings.pkl에 userID, movieID, "
                    "timestamp가 필요합니다."
                )

            timestamps = source[
                ["userID", "movieID", "timestamp"]
            ].copy()

            del source

            timestamps = timestamps.rename(
                columns={
                    "userID": "user_id",
                    "movieID": "movie_id",
                }
            )

            for column in timestamps.columns:
                timestamps[column] = pd.to_numeric(
                    timestamps[column],
                    errors="raise",
                )

            if timestamps.isna().any().any():
                raise ValueError(
                    "원본 ID 또는 timestamp에 빈 값이 있습니다."
                )

            for column in timestamps.columns:
                values = timestamps[column].to_numpy()

                if (
                    not np.isfinite(values).all()
                    or (values % 1 != 0).any()
                ):
                    raise ValueError(
                        f"{column}은 유효한 정수여야 합니다."
                    )

                timestamps[column] = (
                    timestamps[column].astype("int64")
                )

            if timestamps.duplicated(
                ["user_id", "movie_id"]
            ).any():
                raise ValueError(
                    "원본에 고객·영화 중복 기록이 있어 "
                    "DB 행과 시간을 일대일로 연결할 수 없습니다."
                )

            self._timestamps = timestamps.set_index(
                ["user_id", "movie_id"]
            )

        return self._timestamps

    def _attach_time(self, frame):
        result = frame.join(
            self._get_timestamps(),
            on=["user_id", "movie_id"],
            validate="one_to_one",
        )

        if result["timestamp"].isna().any():
            raise ValueError(
                "DB 평점 중 원본 timestamp와 "
                "연결되지 않는 기록이 있습니다."
            )

        # 같은 시각이면 영화 ID로 순서를 고정한다.
        return result.sort_values(
            ["user_id", "timestamp", "movie_id"]
        ).reset_index(drop=True)

    def read_ratings(self):
        query = text("""
            SELECT user_id, movie_id, rating
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
                "DB 평점에 빈 값이 있습니다."
            )

        if not np.isfinite(
            frame["rating"].to_numpy()
        ).all():
            raise ValueError(
                "DB 평점에 유효하지 않은 값이 있습니다."
            )

        if frame.duplicated(
            ["user_id", "movie_id"]
        ).any():
            raise ValueError(
                "DB에 고객·영화 중복 평점이 있습니다."
            )

        return self._attach_time(frame)

    def read_user_history(self, user_id):
        query = text("""
            SELECT user_id, movie_id, rating
            FROM public.ratings
            WHERE user_id = :user_id
        """)

        with self.engine.connect() as connection:
            frame = pd.read_sql_query(
                query,
                connection,
                params={"user_id": user_id},
            )

        if frame.empty:
            return frame

        return self._attach_time(frame)

    def find_movies(self, movie_ids):
        if not movie_ids:
            return {}

        query = text("""
            SELECT movie_id, title, genres
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
                prefix="transformer-",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)

                torch.save(checkpoint, file)

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
                "Transformer 체크포인트 버전이 맞지 않습니다."
            )

        return checkpoint