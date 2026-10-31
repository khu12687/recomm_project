import logging
from threading import Lock

import numpy as np
import torch

from torch import nn
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm

from .model import RatingTransformer
from .repository import TransformerRepository


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


class TransformerError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class SequenceDataset(Dataset):
    def __init__(
        self,
        users,
        movies,
        ratings,
        starts,
        target_rows,
        max_history,
    ):
        self.users = users
        self.movies = movies
        self.ratings = ratings
        self.starts = starts
        self.target_rows = target_rows
        self.max_history = max_history

    def __len__(self):
        return len(self.target_rows)

    def __getitem__(self, index):
        position = int(self.target_rows[index])
        user = int(self.users[position])

        # 현재 target 직전까지만 입력한다.
        start = max(
            int(self.starts[user]),
            position - self.max_history,
        )

        past_movies = self.movies[start:position]
        past_ratings = self.ratings[start:position]

        history_movies = np.zeros(
            self.max_history,
            dtype=np.int64,
        )

        history_ratings = np.zeros(
            self.max_history,
            dtype=np.float32,
        )

        length = len(past_movies)

        history_movies[-length:] = past_movies
        history_ratings[-length:] = past_ratings

        return (
            torch.tensor(user, dtype=torch.long),
            torch.tensor(
                int(self.movies[position]),
                dtype=torch.long,
            ),
            torch.from_numpy(history_movies),
            torch.from_numpy(history_ratings),
            torch.tensor(
                float(self.ratings[position]),
                dtype=torch.float32,
            ),
        )


class TransformerService:
    def __init__(self):
        self.repository = TransformerRepository()

        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            self.device = torch.device("cpu")

        self._model = None
        self._checkpoint = None
        self._lock = Lock()

    def close(self):
        self.repository.close()

    @staticmethod
    def accumulate_error(predicted, actual):
        # 먼저 CPU로 이동하고, 그 다음 float64로 변환.
        predicted_cpu = (
            predicted.detach()
            .cpu()
            .to(torch.float64)
        )

        actual_cpu = (
            actual.detach()
            .cpu()
            .to(torch.float64)
        )

        error = predicted_cpu - actual_cpu

        return (
            error.abs().sum().item(),
            error.square().sum().item(),
            error.numel(),
        )

    @torch.inference_mode()
    def evaluate(
        self,
        model,
        loader,
        rating_min,
        rating_max,
    ):
        model.eval()

        absolute_sum = 0.0
        squared_sum = 0.0
        count = 0

        for batch in loader:
            users, targets, hm, hr, actual = batch

            predicted = model(
                users.to(self.device),
                targets.to(self.device),
                hm.to(self.device),
                hr.to(self.device),
            ).clamp(
                min=rating_min,
                max=rating_max,
            )

            absolute, squared, size = (
                self.accumulate_error(
                    predicted,
                    actual,
                )
            )

            absolute_sum += absolute
            squared_sum += squared
            count += size

        if count == 0:
            raise ValueError(
                "검증 데이터가 없습니다."
            )

        mse = squared_sum / count

        return {
            "mae": float(absolute_sum / count),
            "mse": float(mse),
            "rmse": float(np.sqrt(mse)),
        }

    def train(
        self,
        epochs=2,
        batch_size=512,
        max_history=10,
        dim=32,
        heads=4,
        layers=1,
        learning_rate=0.001,
    ):
        if min(
            epochs,
            batch_size,
            max_history,
            dim,
            heads,
            layers,
        ) < 1:
            raise ValueError(
                "학습 설정은 양수여야 합니다."
            )

        if dim % heads != 0:
            raise ValueError(
                "dim은 heads로 나누어져야 합니다."
            )

        if learning_rate <= 0:
            raise ValueError(
                "학습률은 양수여야 합니다."
            )

        with self._lock:
            torch.manual_seed(42)

            print(
                f"Transformer 학습 장치: {self.device}",
                flush=True,
            )

            print(
                "평점·시간 정보 조회 및 정렬 중...",
                flush=True,
            )

            frame = self.repository.read_ratings()

            user_ids, users = np.unique(
                frame["user_id"].to_numpy(
                    dtype=np.int64
                ),
                return_inverse=True,
            )

            movie_ids, movie_index = np.unique(
                frame["movie_id"].to_numpy(
                    dtype=np.int64
                ),
                return_inverse=True,
            )

            movies = (
                movie_index + 1
            ).astype(np.int64)

            ratings = frame["rating"].to_numpy(
                dtype=np.float32,
                copy=True,
            )

            del frame, movie_index

            counts = np.bincount(
                users,
                minlength=len(user_ids),
            )

            starts = np.concatenate(
                [[0], np.cumsum(counts)[:-1]]
            ).astype(np.int64)

            holdout = np.ceil(
                counts * 0.1
            ).astype(np.int64)

            split = counts - holdout

            # 최소: 과거 1건 + 학습 target 1건 + 검증 1건.
            eligible_users = counts >= 3

            local_position = (
                np.arange(len(ratings))
                - starts[users]
            )

            prefix_mask = (
                eligible_users[users]
                & (local_position < split[users])
            )

            train_mask = (
                prefix_mask
                & (local_position >= 1)
            )

            validation_mask = (
                eligible_users[users]
                & (local_position >= split[users])
            )

            train_rows = np.flatnonzero(
                train_mask
            )

            validation_rows = np.flatnonzero(
                validation_mask
            )

            if (
                len(train_rows) == 0
                or len(validation_rows) == 0
            ):
                raise ValueError(
                    "학습·검증용 고객 이력이 부족합니다."
                )

            # 검증 구간은 평균·범위 계산에도 사용하지 않는다.
            prefix_ratings = ratings[prefix_mask]

            mean = float(
                prefix_ratings.mean(
                    dtype=np.float64
                )
            )

            scale = max(
                float(
                    prefix_ratings.std(
                        dtype=np.float64
                    )
                ),
                1e-6,
            )

            rating_min = float(
                prefix_ratings.min()
            )

            rating_max = float(
                prefix_ratings.max()
            )

            # 학습에 한 번도 등장하지 않은 영화는
            # 추천 후보에서 제외한다.
            trained_movies = np.zeros(
                len(movie_ids),
                dtype=bool,
            )

            trained_movies[
                movies[prefix_mask] - 1
            ] = True

            train_dataset = SequenceDataset(
                users,
                movies,
                ratings,
                starts,
                train_rows,
                max_history,
            )

            validation_dataset = SequenceDataset(
                users,
                movies,
                ratings,
                starts,
                validation_rows,
                max_history,
            )

            train_loader = DataLoader(
                train_dataset,
                batch_size=batch_size,
                shuffle=True,
                num_workers=0,
            )

            validation_loader = DataLoader(
                validation_dataset,
                batch_size=batch_size,
                shuffle=False,
                num_workers=0,
            )

            config = {
                "n_users": int(len(user_ids)),
                "n_movies": int(len(movie_ids)),
                "max_history": int(max_history),
                "dim": int(dim),
                "heads": int(heads),
                "layers": int(layers),
                "mean": mean,
                "scale": scale,
            }

            model = RatingTransformer(
                **config
            ).to(
                device=self.device,
                dtype=torch.float32,
            )

            optimizer = torch.optim.AdamW(
                model.parameters(),
                lr=learning_rate,
                weight_decay=1e-4,
            )

            loss_function = nn.MSELoss()

            best_rmse = float("inf")
            best_state = None
            best_metrics = None

            for epoch in range(1, epochs + 1):
                model.train()

                squared_sum = 0.0
                observed = 0

                progress = tqdm(
                    train_loader,
                    desc=(
                        f"Transformer "
                        f"{epoch}/{epochs}"
                    ),
                )

                for batch in progress:
                    users_b, targets, hm, hr, actual = (
                        item.to(self.device)
                        for item in batch
                    )

                    optimizer.zero_grad(
                        set_to_none=True
                    )

                    predicted = model(
                        users_b,
                        targets,
                        hm,
                        hr,
                    )

                    loss = loss_function(
                        predicted,
                        actual,
                    )

                    if not torch.isfinite(
                        loss
                    ).item():
                        raise ValueError(
                            "학습 손실이 유효하지 않습니다."
                        )

                    loss.backward()

                    nn.utils.clip_grad_norm_(
                        model.parameters(),
                        max_norm=1.0,
                    )

                    optimizer.step()

                    _, squared, size = (
                        self.accumulate_error(
                            predicted,
                            actual,
                        )
                    )

                    squared_sum += squared
                    observed += size

                    progress.set_postfix(
                        train_mse=(
                            squared_sum / observed
                        )
                    )

                metrics = self.evaluate(
                    model,
                    validation_loader,
                    rating_min,
                    rating_max,
                )

                print(
                    f"Epoch {epoch}: "
                    f"MAE={metrics['mae']:.5f}, "
                    f"MSE={metrics['mse']:.5f}, "
                    f"RMSE={metrics['rmse']:.5f}",
                    flush=True,
                )

                if metrics["rmse"] < best_rmse:
                    best_rmse = metrics["rmse"]

                    best_state = {
                        name: value.detach()
                        .cpu()
                        .clone()
                        for name, value
                        in model.state_dict().items()
                    }

                    best_metrics = {
                        **metrics,
                        "train_count": int(
                            len(train_rows)
                        ),
                        "validation_count": int(
                            len(validation_rows)
                        ),
                        "best_epoch": int(epoch),
                        "max_history": int(
                            max_history
                        ),
                        "device": str(self.device),
                    }

            checkpoint = {
                "version": 1,
                "config": config,
                "state_dict": best_state,
                "user_ids": torch.from_numpy(
                    user_ids.astype(np.int64)
                ),
                "movie_ids": torch.from_numpy(
                    movie_ids.astype(np.int64)
                ),
                "eligible_users": torch.from_numpy(
                    eligible_users
                ),
                "trained_movies": torch.from_numpy(
                    trained_movies
                ),
                "rating_min": rating_min,
                "rating_max": rating_max,
                "metrics": best_metrics,
            }

            self.repository.save_checkpoint(
                checkpoint
            )

            self._model = None
            self._checkpoint = None

            print(
                "checkpoint/transformer.pt 저장 완료",
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
                raise TransformerError(
                    503,
                    "Transformer 모델이 없습니다. "
                    "먼저 학습 명령을 실행하세요.",
                )

            model = RatingTransformer(
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

            self._checkpoint = checkpoint
            self._model = model

    def kpi(self):
        self._ensure_loaded()
        return self._checkpoint["metrics"]

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

        checkpoint = self._checkpoint

        user_ids = (
            checkpoint["user_ids"].numpy()
        )

        movie_ids = (
            checkpoint["movie_ids"].numpy()
        )

        user_position = int(
            np.searchsorted(user_ids, user_id)
        )

        if (
            user_position >= len(user_ids)
            or int(user_ids[user_position]) != user_id
            or not bool(
                checkpoint["eligible_users"][
                    user_position
                ]
            )
        ):
            raise TransformerError(
                404,
                "학습 가능한 이력이 없는 고객입니다. "
                "평점이 3개 이상인 학습 고객을 선택하세요.",
            )

        history = (
            self.repository.read_user_history(
                user_id
            )
        )

        if history.empty:
            raise TransformerError(
                404,
                "고객의 평점 이력이 없습니다.",
            )

        seen_ids = set(
            history["movie_id"].astype(int)
        )

        max_history = checkpoint[
            "config"
        ]["max_history"]

        known_history = []

        for row in history.itertuples(
            index=False
        ):
            movie_id = int(row.movie_id)

            position = int(
                np.searchsorted(
                    movie_ids,
                    movie_id,
                )
            )

            if (
                position < len(movie_ids)
                and int(movie_ids[position])
                == movie_id
            ):
                known_history.append(
                    (
                        position + 1,
                        float(row.rating),
                    )
                )

        recent = known_history[-max_history:]

        if not recent:
            raise TransformerError(
                409,
                "현재 이력을 저장된 모델과 "
                "연결할 수 없습니다.",
            )

        hm = np.zeros(
            max_history,
            dtype=np.int64,
        )

        hr = np.zeros(
            max_history,
            dtype=np.float32,
        )

        hm[-len(recent):] = [
            item[0] for item in recent
        ]

        hr[-len(recent):] = [
            item[1] for item in recent
        ]

        trained_movies = checkpoint[
            "trained_movies"
        ].numpy()

        candidates = np.array(
            [
                position
                for position, movie_id
                in enumerate(movie_ids)
                if (
                    trained_movies[position]
                    and int(movie_id) not in seen_ids
                )
            ],
            dtype=np.int64,
        )

        if len(candidates) == 0:
            return []

        scores = []

        for start in range(
            0,
            len(candidates),
            256,
        ):
            positions = candidates[
                start:start + 256
            ]

            size = len(positions)

            users = torch.full(
                (size,),
                user_position,
                dtype=torch.long,
                device=self.device,
            )

            targets = torch.as_tensor(
                positions + 1,
                dtype=torch.long,
                device=self.device,
            )

            history_movies = torch.as_tensor(
                hm,
                dtype=torch.long,
                device=self.device,
            ).unsqueeze(0).expand(size, -1)

            history_ratings = torch.as_tensor(
                hr,
                dtype=torch.float32,
                device=self.device,
            ).unsqueeze(0).expand(size, -1)

            predicted = self._model(
                users,
                targets,
                history_movies,
                history_ratings,
            ).clamp(
                min=checkpoint["rating_min"],
                max=checkpoint["rating_max"],
            )

            scores.append(
                predicted.cpu().numpy()
            )

        scores = np.concatenate(scores)

        candidate_ids = movie_ids[candidates]

        top = np.lexsort(
            (candidate_ids, -scores)
        )[:5]

        top_ids = [
            int(candidate_ids[position])
            for position in top
        ]

        movies = self.repository.find_movies(
            top_ids
        )

        if any(
            movie_id not in movies
            for movie_id in top_ids
        ):
            raise TransformerError(
                409,
                "모델과 DB의 영화 정보가 "
                "일치하지 않습니다.",
            )

        return [
            {
                "rank": rank,
                "movie_id": int(
                    candidate_ids[position]
                ),
                "title": movies[
                    int(candidate_ids[position])
                ]["title"],
                "genres": self.translate_genres(
                    movies[
                        int(candidate_ids[position])
                    ]["genres"]
                ),
                "predicted_rating": round(
                    float(scores[position]),
                    4,
                ),
            }
            for rank, position in enumerate(
                top,
                start=1,
            )
        ]

    def execute(self, operation, *args):
        try:
            if operation == "kpi":
                return self.kpi()

            if operation == "recommendations":
                return self.recommendations(*args)

            raise TransformerError(
                400,
                "지원하지 않는 작업입니다.",
            )

        except TransformerError:
            raise

        except Exception as error:
            logger.exception(
                "Transformer 처리 실패: %s",
                operation,
            )

            raise TransformerError(
                503,
                "Transformer 처리에 실패했습니다. "
                "서버 로그를 확인하세요.",
            ) from error