import logging
from threading import Lock

import numpy as np
import torch

from torch import nn
from torch.utils.data import (
    DataLoader,
    TensorDataset,
)
from tqdm import tqdm

from .model import MFModel
from .repository import MFRepository


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


class MFError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)

        self.status_code = status_code
        self.detail = detail


class MFService:
    def __init__(self):
        self.repository = MFRepository()

        self._model = None
        self._checkpoint = None
        self._user_ids = None
        self._movie_ids = None

        self._lock = Lock()

        self.device = self.select_device()

    @staticmethod
    def select_device():
        if torch.cuda.is_available():
            return torch.device("cuda")

        if torch.backends.mps.is_available():
            return torch.device("mps")

        return torch.device("cpu")

    def close(self):
        self.repository.close()

    @staticmethod
    def make_loader(
        users,
        movies,
        ratings,
        batch_size,
        shuffle,
    ):
        dataset = TensorDataset(
            torch.from_numpy(
                users.astype(
                    np.int64,
                    copy=False,
                )
            ),
            torch.from_numpy(
                movies.astype(
                    np.int64,
                    copy=False,
                )
            ),
            torch.from_numpy(
                ratings.astype(
                    np.float32,
                    copy=False,
                )
            ),
        )

        return DataLoader(
            dataset,
            batch_size=batch_size,
            shuffle=shuffle,
            num_workers=0,
            drop_last=False,
        )

    @staticmethod
    @torch.inference_mode()
    def evaluate(
        model,
        loader,
        device,
        rating_min,
        rating_max,
    ):
        model.eval()

        absolute_error_sum = 0.0
        squared_error_sum = 0.0
        count = 0

        for users, movies, ratings in loader:
            users = users.to(device)
            movies = movies.to(device)

            predicted = model(
                users,
                movies,
            ).clamp(
                min=rating_min,
                max=rating_max,
            )

            # 必ず先にCPUへ移動する。
            # float64はCPU側でのみ使用する。
            predicted_cpu = (
                predicted.detach()
                .cpu()
                .to(torch.float64)
            )

            actual_cpu = (
                ratings.cpu()
                .to(torch.float64)
            )

            error = (
                predicted_cpu - actual_cpu
            )

            absolute_error_sum += (
                error.abs().sum().item()
            )

            squared_error_sum += (
                error.square().sum().item()
            )

            count += ratings.numel()

        if count == 0:
            raise ValueError(
                "検証データがありません。"
            )

        mae = absolute_error_sum / count
        mse = squared_error_sum / count

        return {
            "mae": float(mae),
            "mse": float(mse),
            "rmse": float(np.sqrt(mse)),
        }

    def train(
        self,
        factors=30,
        epochs=10,
        batch_size=8192,
        learning_rate=0.003,
    ):
        if (
            factors < 1
            or epochs < 1
            or batch_size < 1
            or learning_rate <= 0
        ):
            raise ValueError(
                "学習パラメーターは正の値を指定してください。"
            )

        with self._lock:
            torch.manual_seed(42)

            print(
                f"MF 학습 장치: {self.device}",
                flush=True,
            )

            print(
                "PostgreSQL 평점 조회 중...",
                flush=True,
            )

            frame = (
                self.repository.read_ratings()
            )

            user_ids, users = np.unique(
                frame["user_id"].to_numpy(
                    dtype=np.int64
                ),
                return_inverse=True,
            )

            movie_ids, movies = np.unique(
                frame["movie_id"].to_numpy(
                    dtype=np.int64
                ),
                return_inverse=True,
            )

            ratings = frame[
                "rating"
            ].to_numpy(
                dtype=np.float32,
                copy=True,
            )

            del frame

            rng = np.random.default_rng(42)

            validation = (
                rng.random(len(ratings)) < 0.2
            )

            # 모든 고객과 영화가 학습에 등장하도록 보호.
            _, first_user_rows = np.unique(
                users,
                return_index=True,
            )

            _, first_movie_rows = np.unique(
                movies,
                return_index=True,
            )

            validation[first_user_rows] = False
            validation[first_movie_rows] = False

            train_mask = ~validation

            train_count = int(
                train_mask.sum()
            )

            validation_count = int(
                validation.sum()
            )

            if validation_count == 0:
                raise ValueError(
                    "검증 평점을 분리할 데이터가 부족합니다."
                )

            train_ratings = ratings[train_mask]

            # 평균과 평점 범위도 학습 데이터로만 계산.
            global_mean = float(
                train_ratings.mean(
                    dtype=np.float64
                )
            )

            rating_min = float(
                train_ratings.min()
            )

            rating_max = float(
                train_ratings.max()
            )

            train_loader = self.make_loader(
                users[train_mask],
                movies[train_mask],
                train_ratings,
                batch_size,
                shuffle=True,
            )

            validation_loader = self.make_loader(
                users[validation],
                movies[validation],
                ratings[validation],
                batch_size,
                shuffle=False,
            )

            model = MFModel(
                n_users=len(user_ids),
                n_movies=len(movie_ids),
                factors=factors,
                global_mean=global_mean,
            ).to(
                device=self.device,
                dtype=torch.float32,
            )

            optimizer = torch.optim.Adam(
                model.parameters(),
                lr=learning_rate,
                weight_decay=1e-5,
            )

            loss_function = nn.MSELoss()

            best_rmse = float("inf")
            best_state = None
            best_metrics = None

            for epoch in range(
                1,
                epochs + 1,
            ):
                model.train()

                train_squared_error = 0.0
                observed_count = 0

                progress = tqdm(
                    train_loader,
                    desc=f"MF Epoch {epoch}/{epochs}",
                    unit="batch",
                )

                for (
                    batch_users,
                    batch_movies,
                    batch_ratings,
                ) in progress:
                    batch_users = (
                        batch_users.to(
                            self.device
                        )
                    )

                    batch_movies = (
                        batch_movies.to(
                            self.device
                        )
                    )

                    # MPS上の平점은float32。
                    batch_ratings = (
                        batch_ratings.to(
                            device=self.device,
                            dtype=torch.float32,
                        )
                    )

                    optimizer.zero_grad(
                        set_to_none=True
                    )

                    predicted = model(
                        batch_users,
                        batch_movies,
                    )

                    loss = loss_function(
                        predicted,
                        batch_ratings,
                    )

                    if not torch.isfinite(
                        loss
                    ).item():
                        raise ValueError(
                            "학습 손실이 유효하지 않습니다. "
                            "학습률과 데이터를 확인하세요."
                        )

                    loss.backward()
                    optimizer.step()

                    # 오차 합산은 CPU float64에서 수행.
                    predicted_cpu = (
                        predicted.detach()
                        .cpu()
                        .to(torch.float64)
                    )

                    ratings_cpu = (
                        batch_ratings.detach()
                        .cpu()
                        .to(torch.float64)
                    )

                    error_cpu = (
                        predicted_cpu
                        - ratings_cpu
                    )

                    train_squared_error += (
                        error_cpu.square()
                        .sum()
                        .item()
                    )

                    observed_count += (
                        ratings_cpu.numel()
                    )

                    progress.set_postfix(
                        train_mse=(
                            train_squared_error
                            / observed_count
                        )
                    )

                metrics = self.evaluate(
                    model,
                    validation_loader,
                    self.device,
                    rating_min,
                    rating_max,
                )

                print(
                    f"Epoch {epoch}: "
                    f"검증 MAE={metrics['mae']:.5f}, "
                    f"MSE={metrics['mse']:.5f}, "
                    f"RMSE={metrics['rmse']:.5f}",
                    flush=True,
                )

                if metrics["rmse"] < best_rmse:
                    best_rmse = metrics["rmse"]

                    best_state = {
                        name: tensor.detach()
                        .cpu()
                        .clone()
                        for name, tensor
                        in model.state_dict().items()
                    }

                    best_metrics = {
                        **metrics,
                        "train_count": train_count,
                        "validation_count": validation_count,
                        "factors": int(factors),
                        "best_epoch": int(epoch),
                        "device": str(self.device),
                    }

            checkpoint = {
                "version": 1,

                "config": {
                    "n_users": int(len(user_ids)),
                    "n_movies": int(len(movie_ids)),
                    "factors": int(factors),
                    "global_mean": global_mean,
                },

                "state_dict": best_state,

                # 원본 ID ↔ 임베딩 행 번호 매핑.
                "user_ids": torch.from_numpy(
                    user_ids.astype(np.int64)
                ),

                "movie_ids": torch.from_numpy(
                    movie_ids.astype(np.int64)
                ),

                "rating_min": rating_min,
                "rating_max": rating_max,
                "metrics": best_metrics,
            }

            self.repository.save_checkpoint(
                checkpoint
            )

            # 같은 객체로 다시 조회해도 저장 모델을 읽도록 초기화.
            self._model = None
            self._checkpoint = None
            self._user_ids = None
            self._movie_ids = None

            print(
                "backend/checkpoint/mf.pt 저장 완료",
                flush=True,
            )

            return best_metrics

    def _ensure_loaded(self):
        if self._model is not None:
            return

        with self._lock:
            if self._model is not None:
                return

            checkpoint = (
                self.repository.load_checkpoint()
            )

            if checkpoint is None:
                raise MFError(
                    503,
                    "MF 모델이 없습니다. "
                    "먼저 MF 학습 명령을 실행하세요.",
                )

            model = MFModel(
                **checkpoint["config"]
            )

            model.load_state_dict(
                checkpoint["state_dict"]
            )

            model = model.to(
                device=self.device,
                dtype=torch.float32,
            )

            model.eval()

            self._user_ids = (
                checkpoint["user_ids"]
                .cpu()
                .numpy()
            )

            self._movie_ids = (
                checkpoint["movie_ids"]
                .cpu()
                .numpy()
            )

            self._checkpoint = checkpoint

            # 다른 스레드가 완성된 상태만 보도록 마지막에 설정.
            self._model = model

    def kpi(self):
        self._ensure_loaded()

        return self._checkpoint[
            "metrics"
        ]

    @staticmethod
    def translate_genres(genres):
        if not genres:
            return "장르 정보 없음"

        return ", ".join(
            GENRES_KO.get(genre, "기타")
            for genre in genres.split("|")
        )

    @torch.inference_mode()
    def recommendations(self, user_id):
        self._ensure_loaded()

        user_position = int(
            np.searchsorted(
                self._user_ids,
                user_id,
            )
        )

        if (
            user_position >= len(self._user_ids)
            or int(
                self._user_ids[user_position]
            ) != user_id
        ):
            raise MFError(
                404,
                "학습 데이터에 없는 고객 ID입니다.",
            )

        seen_ids = (
            self.repository.find_seen_movie_ids(
                user_id
            )
        )

        candidate_positions = np.array(
            [
                position
                for position, movie_id
                in enumerate(self._movie_ids)
                if int(movie_id) not in seen_ids
            ],
            dtype=np.int64,
        )

        if len(candidate_positions) == 0:
            return []

        scores = []

        for start in range(
            0,
            len(candidate_positions),
            8192,
        ):
            positions = candidate_positions[
                start:start + 8192
            ]

            movies = torch.as_tensor(
                positions,
                dtype=torch.long,
                device=self.device,
            )

            users = torch.full(
                (len(positions),),
                user_position,
                dtype=torch.long,
                device=self.device,
            )

            predicted = self._model(
                users,
                movies,
            ).clamp(
                min=self._checkpoint[
                    "rating_min"
                ],
                max=self._checkpoint[
                    "rating_max"
                ],
            )

            scores.append(
                predicted.cpu().numpy()
            )

        scores = np.concatenate(scores)

        candidate_ids = self._movie_ids[
            candidate_positions
        ]

        # 동점일 때 영화 ID 오름차순.
        order = np.lexsort((
            candidate_ids,
            -scores,
        ))[:5]

        top_ids = [
            int(candidate_ids[position])
            for position in order
        ]

        movies = self.repository.find_movies(
            top_ids
        )

        if any(
            movie_id not in movies
            for movie_id in top_ids
        ):
            raise MFError(
                409,
                "MF 모델과 DB의 영화 정보가 "
                "일치하지 않습니다.",
            )

        result = []

        for rank, position in enumerate(
            order,
            start=1,
        ):
            movie_id = int(
                candidate_ids[position]
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

            raise MFError(
                400,
                "지원하지 않는 MF 작업입니다.",
            )

        except MFError:
            raise

        except Exception as error:
            logger.exception(
                "MF 처리 실패: %s",
                operation,
            )

            raise MFError(
                503,
                "MF 처리에 실패했습니다. "
                "서버 로그를 확인하세요.",
            ) from error