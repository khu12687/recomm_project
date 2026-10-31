import argparse
import csv
import io
import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from dotenv import load_dotenv
from tqdm import tqdm


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "app" / "data"


def connect_database():
    load_dotenv(
        PROJECT_DIR / ".env",
        override=True,
    )

    # 이 스크립트는 Mac의 터미널에서 실행한다.
    # Docker에 공개한 외부 포트로 접속한다.
    return psycopg.connect(
        host="127.0.0.1",
        port=int(
            os.environ["POSTGRES_EXTERNAL_PORT"]
        ),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
        connect_timeout=10,
        autocommit=True,
    )


def create_tables(connection):
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.movies (
                    movie_id BIGINT PRIMARY KEY,
                    title TEXT NOT NULL,
                    genres TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.ratings (
                    user_id BIGINT NOT NULL,
                    movie_id BIGINT NOT NULL
                        REFERENCES public.movies(movie_id),
                    rating DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (user_id, movie_id)
                )
            """)

            # 임시 테이블은 이 연결에서만 사용한다.
            # 실제 movies, ratings 데이터는 비우지 않는다.
            cursor.execute("""
                CREATE TEMP TABLE stage_movies (
                    movie_id BIGINT NOT NULL,
                    title TEXT NOT NULL,
                    genres TEXT NOT NULL
                ) ON COMMIT DELETE ROWS
            """)

            cursor.execute("""
                CREATE TEMP TABLE stage_ratings (
                    user_id BIGINT NOT NULL,
                    movie_id BIGINT NOT NULL,
                    rating DOUBLE PRECISION NOT NULL
                ) ON COMMIT DELETE ROWS
            """)


def save_movie_batch(connection, rows):
    with connection.transaction():
        with connection.cursor() as cursor:
            with cursor.copy("""
                COPY stage_movies (
                    movie_id,
                    title,
                    genres
                ) FROM STDIN
            """) as copy:
                for row in rows:
                    copy.write_row(row)

            cursor.execute("""
                INSERT INTO public.movies (
                    movie_id,
                    title,
                    genres
                )
                SELECT
                    movie_id,
                    title,
                    genres
                FROM stage_movies
                ON CONFLICT (movie_id) DO NOTHING
            """)

            inserted = cursor.rowcount

    return inserted


def load_movies(
    connection,
    path,
    batch_size,
    encoding,
):
    if not path.is_file():
        raise FileNotFoundError(
            f"영화 파일이 없습니다: {path}"
        )

    # 정확한 진행률 표시를 위해 줄 수를 확인한다.
    with path.open("rb") as file:
        total_lines = sum(1 for _ in file)

    rows = []
    inserted_total = 0

    with (
        path.open(
            "r",
            encoding=encoding,
        ) as file,
        tqdm(
            total=total_lines,
            desc="영화 적재",
            unit="행",
        ) as progress,
    ):
        for line_number, line in enumerate(
            file,
            start=1,
        ):
            line = line.rstrip("\r\n")

            if not line:
                progress.update(1)
                continue

            parts = line.split("::", 2)

            if len(parts) != 3:
                raise ValueError(
                    f"movies.dat {line_number}행: "
                    "영화ID::제목::장르 형식이 아닙니다."
                )

            movie_id_text, title, genres = parts

            try:
                movie_id = int(movie_id_text)
            except ValueError as error:
                raise ValueError(
                    f"movies.dat {line_number}행: "
                    "영화 ID가 정수가 아닙니다."
                ) from error

            if not 0 < movie_id < 2**63:
                raise ValueError(
                    f"movies.dat {line_number}행: "
                    "영화 ID 범위를 확인하세요."
                )

            if not title.strip():
                raise ValueError(
                    f"movies.dat {line_number}행: "
                    "영화 제목이 비어 있습니다."
                )

            rows.append(
                (movie_id, title, genres)
            )

            if len(rows) >= batch_size:
                inserted_total += save_movie_batch(
                    connection,
                    rows,
                )

                progress.update(len(rows))
                progress.set_postfix(
                    신규=f"{inserted_total:,}"
                )

                rows.clear()

        if rows:
            inserted_total += save_movie_batch(
                connection,
                rows,
            )

            progress.update(len(rows))
            progress.set_postfix(
                신규=f"{inserted_total:,}"
            )

    return inserted_total


def prepare_rating_batch(frame, start):
    result = frame[
        ["userID", "movieID", "ratings"]
    ].copy()

    for column in result.columns:
        result[column] = pd.to_numeric(
            result[column],
            errors="raise",
        )

    if result.isna().any().any():
        raise ValueError(
            f"평점 {start:,}행 이후 배치에 "
            "빈 값이 있습니다."
        )

    for column in ("userID", "movieID"):
        values = result[column]

        invalid = (
            ~np.isfinite(values)
            | (values <= 0)
            | (values >= 2**63)
            | (values % 1 != 0)
        )

        if invalid.any():
            raise ValueError(
                f"평점 {start:,}행 이후 배치의 "
                f"{column}에 잘못된 ID가 있습니다."
            )

        result[column] = values.astype("int64")

    result["ratings"] = result[
        "ratings"
    ].astype("float64")

    if not np.isfinite(
        result["ratings"].to_numpy()
    ).all():
        raise ValueError(
            f"평점 {start:,}행 이후 배치에 "
            "유효하지 않은 평점이 있습니다."
        )

    return result


def save_rating_batch(connection, frame):
    # 숫자 데이터만 CSV로 변환한다.
    buffer = io.StringIO()

    frame.to_csv(
        buffer,
        index=False,
        header=False,
        quoting=csv.QUOTE_MINIMAL,
    )

    buffer.seek(0)

    with connection.transaction():
        with connection.cursor() as cursor:
            with cursor.copy("""
                COPY stage_ratings (
                    user_id,
                    movie_id,
                    rating
                )
                FROM STDIN
                WITH (FORMAT CSV)
            """) as copy:
                while block := buffer.read(
                    1024 * 1024
                ):
                    copy.write(block)

            # 영화 정보가 없는 평점을 조용히 버리지 않는다.
            cursor.execute("""
                SELECT s.movie_id
                FROM stage_ratings AS s
                LEFT JOIN public.movies AS m
                    ON m.movie_id = s.movie_id
                WHERE m.movie_id IS NULL
                LIMIT 1
            """)

            missing = cursor.fetchone()

            if missing is not None:
                raise ValueError(
                    "영화 정보에 없는 movieID가 "
                    f"평점에 있습니다: {missing[0]}"
                )

            cursor.execute("""
                INSERT INTO public.ratings (
                    user_id,
                    movie_id,
                    rating
                )
                SELECT
                    user_id,
                    movie_id,
                    rating
                FROM stage_ratings
                ON CONFLICT (
                    user_id,
                    movie_id
                ) DO NOTHING
            """)

            inserted = cursor.rowcount

    return inserted


def load_ratings(
    connection,
    path,
    batch_size,
):
    if not path.is_file():
        raise FileNotFoundError(
            f"평점 파일이 없습니다: {path}"
        )

    print(
        "ratings.pkl 읽는 중 "
        "(pickle 읽기는 진행률 표시 전 수행됩니다)...",
        flush=True,
    )

    # 신뢰하는 수업 데이터 파일만 사용한다.
    frame = pd.read_pickle(path)

    if not isinstance(frame, pd.DataFrame):
        raise TypeError(
            "ratings.pkl은 pandas DataFrame이어야 합니다."
        )

    required = {
        "userID",
        "movieID",
        "ratings",
        "timestamp",
    }

    missing = required - set(frame.columns)

    if missing:
        raise ValueError(
            f"필수 열이 없습니다: {sorted(missing)}"
        )

    total = len(frame)

    print(
        f"원본 평점 수: {total:,}행",
        flush=True,
    )

    inserted_total = 0

    with tqdm(
        total=total,
        desc="평점 적재",
        unit="행",
    ) as progress:
        for start in range(
            0,
            total,
            batch_size,
        ):
            source_batch = frame.iloc[
                start:start + batch_size
            ]

            batch = prepare_rating_batch(
                source_batch,
                start,
            )

            inserted_total += save_rating_batch(
                connection,
                batch,
            )

            # 커밋 완료된 배치만 진행률에 반영한다.
            progress.update(len(source_batch))

            progress.set_postfix(
                신규=f"{inserted_total:,}"
            )

    return inserted_total


def print_counts(
    connection,
    new_movies,
    new_ratings,
):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM public.movies
        """)

        movie_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM public.ratings
        """)

        rating_count = cursor.fetchone()[0]

    print()
    print("===== 적재 완료 =====")
    print(f"이번에 추가한 영화: {new_movies:,}개")
    print(f"이번에 추가한 평점: {new_ratings:,}건")
    print(f"DB 전체 영화 수: {movie_count:,}개")
    print(f"DB 전체 평점 수: {rating_count:,}건")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--batch-size",
        type=int,
        default=100_000,
    )

    parser.add_argument(
        "--movies-encoding",
        default="latin-1",
    )

    args = parser.parse_args()

    if args.batch_size <= 0:
        parser.error(
            "--batch-size는 양수여야 합니다."
        )

    with connect_database() as connection:
        create_tables(connection)

        new_movies = load_movies(
            connection,
            DATA_DIR / "movies.dat",
            args.batch_size,
            args.movies_encoding,
        )

        new_ratings = load_ratings(
            connection,
            DATA_DIR / "ratings.pkl",
            args.batch_size,
        )

        print_counts(
            connection,
            new_movies,
            new_ratings,
        )


if __name__ == "__main__":
    main()