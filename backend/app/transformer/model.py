import torch
from torch import nn


class RatingTransformer(nn.Module):
    def __init__(
        self,
        n_users,
        n_movies,
        max_history=20,
        dim=32,
        heads=4,
        layers=1,
        mean=3.0,
        scale=1.0,
    ):
        super().__init__()

        self.max_history = max_history

        self.user_embedding = nn.Embedding(
            n_users, dim
        )

        # 0은 패딩, 실제 영화 내부 번호는 1부터 시작.
        self.movie_embedding = nn.Embedding(
            n_movies + 1,
            dim,
            padding_idx=0,
        )

        self.rating_projection = nn.Linear(1, dim)
        self.position_embedding = nn.Embedding(
            max_history + 1, dim
        )
        self.token_type = nn.Embedding(2, dim)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=dim,
            nhead=heads,
            dim_feedforward=dim * 4,
            dropout=0.1,
            batch_first=True,
        )

        self.encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=layers,
            enable_nested_tensor=False,
        )

        self.output = nn.Linear(dim, 1)

        self.register_buffer(
            "mean",
            torch.tensor(mean, dtype=torch.float32),
        )

        self.register_buffer(
            "scale",
            torch.tensor(scale, dtype=torch.float32),
        )

        nn.init.normal_(
            self.user_embedding.weight,
            std=0.05,
        )

        nn.init.normal_(
            self.movie_embedding.weight,
            std=0.05,
        )

        with torch.no_grad():
            self.movie_embedding.weight[0].zero_()

    def forward(
        self,
        users,
        targets,
        history_movies,
        history_ratings,
    ):
        batch_size, length = history_movies.shape

        normalized_ratings = (
            history_ratings - self.mean
        ) / self.scale

        history = (
            self.movie_embedding(history_movies)
            + self.rating_projection(
                normalized_ratings.unsqueeze(-1)
            )
            + self.token_type.weight[0]
        )

        # 예측 대상 영화의 실제 평점은 입력하지 않는다.
        query = (
            self.user_embedding(users)
            + self.movie_embedding(targets)
            + self.token_type.weight[1]
        ).unsqueeze(1)

        tokens = torch.cat(
            [history, query],
            dim=1,
        )

        positions = torch.arange(
            length + 1,
            device=tokens.device,
        )

        tokens = (
            tokens
            + self.position_embedding(positions)
        )

        padding_mask = torch.cat(
            [
                history_movies.eq(0),
                torch.zeros(
                    batch_size,
                    1,
                    dtype=torch.bool,
                    device=tokens.device,
                ),
            ],
            dim=1,
        )

        # 입력 이력 자체가 전부 예측 시점보다 과거이므로
        # 이 블록 안에는 미래 평점이 존재하지 않는다.
        encoded = self.encoder(
            tokens,
            src_key_padding_mask=padding_mask,
        )

        normalized_prediction = self.output(
            encoded[:, -1]
        ).squeeze(-1)

        return (
            self.mean
            + self.scale * normalized_prediction
        )