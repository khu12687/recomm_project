import logging
from threading import Lock

import numpy as np

from scipy.sparse import csr_matrix
from scipy.sparse.linalg import svds

from .model import SVDModel
from .repository import SVDRepository


logger = logging.getLogger(__name__)


GENRES_KO = {
    "Action": "액션",
    "Adventure": "모험",
    "Animation": "애니메이션",
    "Children": "어린이",
    "Children's": "어린이",
    "Comedy": "코미디",
    "Crime": "범죄",
    "Documentary": "다큐멘터리",
    "Drama": "드라마",
    "Fantasy": "판타지",
    "Film-Noir": "필름 누아르",
    "Horror": "공포",
    "IMAX": "아이맥스",
    "Musical": "뮤지컬",
    "Mystery": "미스터리",
    "Romance": "로맨스",
    "Sci-Fi": "SF",
    "Thriller": "스릴러",
    "War": "전쟁",
    "Western": "서부",
    "(no genres listed)": "장르 정보 없음",
}


class SVDError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)

        self.status_code = status_code
        self.detail = detail


class SVDService:
    def __init__(self):
        self.repository = SVDRepository()
        self._model = None
        self._lock = Lock()

    def close(self):
        self.repository.close()

    def train(self, factors=50):
        if factors < 1:
            raise ValueError(
                "factors는 1 이상이어야 합니다."
            )

        with self._lock:
            print(
                "1/5 PostgreSQL 평점 조회",
                flush=True,
            )

            frame = self.repository.read_ratings()

            users = frame[
                "user_id"
            ].to_numpy(dtype=np.int64)

            movies = frame[
                "movie_id"
            ].to_numpy(dtype=np.int64)

            ratings = frame[
                "rating"
            ].to_numpy(dtype=np.float32)

            del frame

            user_ids, user_index = np.unique(
                users,
                return_inverse=True,
            )

            movie_ids, movie_index = np.unique(
                movies,
                return_inverse=True,
            )

            del users, movies

            n_users = len(user_ids)
            n_movies = len(movie_ids)
            n_ratings = len(ratings)

            if min(n_users, n_movies) < 2:
                raise ValueError(
                    "SVD에는 고객과 영화가 "
                    "각각 최소 2개 필요합니다."
                )

            print(
                "2/5 학습·검증 데이터 분리",
                flush=True,
            )

            rng = np.random.default_rng(42)

            validation = (
                rng.random(n_ratings) < 0.2
            )

            # 고객별 최소 한 평점은 학습에 남긴다.
            _, first_user_rows = np.unique(
                user_index,
                return_index=True,
            )

            validation[first_user_rows] = False

            # 영화별 최소 한 평점도 학습에 남긴다.
            _, first_movie_rows = np.unique(
                movie_index,
                return_index=True,
            )

            validation[first_movie_rows] = False

            train = ~validation

            train_count = int(train.sum())
            validation_count = int(
                validation.sum()
            )

            if validation_count == 0:
                raise ValueError(
                    "검증용으로 분리할 평점이 부족합니다."
                )

            train_users = user_index[train]
            train_movies = movie_index[train]
            train_ratings = ratings[train]

            counts = np.bincount(
                train_users,
                minlength=n_users,
            )

            sums = np.bincount(
                train_users,
                weights=train_ratings,
                minlength=n_users,
            )

            user_means = (
                sums / counts
            ).astype(np.float32)

            residuals = (
                train_ratings
                - user_means[train_users]
            ).astype(np.float32)

            print(
                "3/5 희소 행렬 생성",
                flush=True,
            )

            matrix = csr_matrix(
                (
                    residuals,
                    (
                        train_users,
                        train_movies,
                    ),
                ),
                shape=(n_users, n_movies),
                dtype=np.float32,
            )

            matrix.eliminate_zeros()

            # 전체 관측 이력을 보관한다.
            # 검증으로 숨긴 영화도 이미 본 영화이므로 제외.
            seen = csr_matrix(
                (
                    np.ones(
                        n_ratings,
                        dtype=np.uint8,
                    ),
                    (
                        user_index,
                        movie_index,
                    ),
                ),
                shape=(n_users, n_movies),
            )

            seen.sort_indices()

            k = min(
                factors,
                n_users - 1,
                n_movies - 1,
            )

            print(
                f"4/5 SVD 학습: "
                f"{n_users:,}명 × {n_movies:,}편, "
                f"k={k}",
                flush=True,
            )

            if (
                matrix.nnz == 0
                or np.all(matrix.data == 0)
            ):
                # 모든 학습 잔차가 0이면 고객 평균을 예측.
                user_factors = np.zeros(
                    (n_users, k),
                    dtype=np.float32,
                )

                movie_factors = np.zeros(
                    (n_movies, k),
                    dtype=np.float32,
                )

            else:
                u, singular_values, vt = svds(
                    matrix,
                    k=k,
                    which="LM",
                    tol=1e-4,
                    maxiter=5000,
                    random_state=42,
                )

                order = np.argsort(
                    singular_values
                )[::-1]

                singular_values = (
                    singular_values[order]
                )

                u = u[:, order]
                vt = vt[order, :]

                user_factors = (
                    u * singular_values
                ).astype(np.float32)

                movie_factors = (
                    vt.T
                ).astype(np.float32)

            rating_min = float(
                train_ratings.min()
            )

            rating_max = float(
                train_ratings.max()
            )

            print(
                "5/5 검증 및 모델 저장",
                flush=True,
            )

            # 검증 데이터를 배치별로 평가한다.
            # 전체 고객×영화 예측 행렬을 만들지 않는다.
            validation_rows = np.flatnonzero(
                validation
            )

            absolute_error_sum = 0.0
            squared_error_sum = 0.0

            for start in range(
                0,
                validation_count,
                100_000,
            ):
                rows = validation_rows[
                    start:start + 100_000
                ]

                batch_users = user_index[rows]
                batch_movies = movie_index[rows]

                predicted = (
                    user_means[batch_users]
                    + np.einsum(
                        "ij,ij->i",
                        user_factors[batch_users],
                        movie_factors[batch_movies],
                    )
                )

                predicted = np.clip(
                    predicted,
                    rating_min,
                    rating_max,
                )

                error = (
                    predicted.astype(np.float64)
                    - ratings[rows].astype(
                        np.float64
                    )
                )

                absolute_error_sum += float(
                    np.abs(error).sum(
                        dtype=np.float64
                    )
                )

                squared_error_sum += float(
                    np.square(error).sum(
                        dtype=np.float64
                    )
                )

            mae = (
                absolute_error_sum
                / validation_count
            )

            mse = (
                squared_error_sum
                / validation_count
            )

            metrics = {
                "mae": mae,
                "mse": mse,
                "rmse": float(np.sqrt(mse)),
                "train_count": train_count,
                "validation_count": validation_count,
                "factors": k,
            }

            model = SVDModel(
                version=1,
                user_ids=user_ids,
                movie_ids=movie_ids,
                user_means=user_means,
                user_factors=user_factors,
                movie_factors=movie_factors,
                seen=seen,
                rating_min=rating_min,
                rating_max=rating_max,
                metrics=metrics,
            )

            self.repository.save_model(model)
            self._model = model

            print(
                "SVD 모델 저장 완료",
                flush=True,
            )

            return metrics

    def _get_model(self):
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is None:
                self._model = (
                    self.repository.load_model()
                )

        if self._model is None:
            raise SVDError(
                503,
                "SVD 모델이 없습니다. "
                "먼저 학습 명령을 실행하세요.",
            )

        return self._model

    def kpi(self):
        model = self._get_model()
        return model.metrics

    @staticmethod
    def translate_genres(genres):
        if not genres:
            return "장르 정보 없음"

        return ", ".join(
            GENRES_KO.get(
                genre,
                "기타",
            )
            for genre in genres.split("|")
        )

    def recommendations(self, user_id):
        model = self._get_model()

        user_position = int(
            np.searchsorted(
                model.user_ids,
                user_id,
            )
        )

        if (
            user_position >= len(model.user_ids)
            or int(
                model.user_ids[user_position]
            ) != user_id
        ):
            raise SVDError(
                404,
                "평점 데이터에 없는 고객 ID입니다.",
            )

        # 한 고객에 대한 영화 점수만 계산한다.
        scores = (
            model.user_means[user_position]
            + model.movie_factors
            @ model.user_factors[user_position]
        )

        scores = np.clip(
            scores,
            model.rating_min,
            model.rating_max,
        )

        seen_movies = (
            model.seen.getrow(
                user_position
            ).indices
        )

        candidate_mask = np.ones(
            len(model.movie_ids),
            dtype=bool,
        )

        candidate_mask[seen_movies] = False

        candidates = np.flatnonzero(
            candidate_mask
        )

        if len(candidates) == 0:
            return []

        # 동점일 때는 영화 ID가 작은 순서.
        order = np.lexsort((
            model.movie_ids[candidates],
            -scores[candidates],
        ))

        top_positions = candidates[
            order[:5]
        ]

        top_ids = [
            int(model.movie_ids[position])
            for position in top_positions
        ]

        movies = self.repository.find_movies(
            top_ids
        )

        if any(
            movie_id not in movies
            for movie_id in top_ids
        ):
            raise SVDError(
                409,
                "모델의 영화 정보와 DB가 일치하지 않습니다.",
            )

        result = []

        for rank, position in enumerate(
            top_positions,
            start=1,
        ):
            movie_id = int(
                model.movie_ids[position]
            )

            movie = movies[movie_id]

            result.append({
                "rank": rank,
                "movie_id": movie_id,
                "title": movie["title"],
                "genres": self.translate_genres(
                    movie["genres"]
                ),
                "predicted_rating": round(
                    float(scores[position]),
                    4,
                ),
            })

        return result

    def execute(self, operation, *args):
        try:
            if operation == "kpi":
                return self.kpi()

            if operation == "recommendations":
                return self.recommendations(*args)

            raise SVDError(
                400,
                "지원하지 않는 SVD 작업입니다.",
            )

        except SVDError:
            raise

        except Exception as error:
            logger.exception(
                "SVD 처리 실패: %s",
                operation,
            )

            raise SVDError(
                503,
                "SVD 처리에 실패했습니다. "
                "서버 로그를 확인하세요.",
            ) from error