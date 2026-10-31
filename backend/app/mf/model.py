import torch
from torch import nn


class MFModel(nn.Module):
    def __init__(
        self,
        n_users,
        n_movies,
        factors,
        global_mean,
    ):
        super().__init__()

        self.user_embedding = nn.Embedding(
            n_users,
            factors,
        )

        self.movie_embedding = nn.Embedding(
            n_movies,
            factors,
        )

        self.user_bias = nn.Embedding(
            n_users,
            1,
        )

        self.movie_bias = nn.Embedding(
            n_movies,
            1,
        )

        self.register_buffer(
            "global_mean",
            torch.tensor(
                global_mean,
                dtype=torch.float32,
            ),
        )

        nn.init.normal_(
            self.user_embedding.weight,
            mean=0.0,
            std=0.05,
        )

        nn.init.normal_(
            self.movie_embedding.weight,
            mean=0.0,
            std=0.05,
        )

        nn.init.zeros_(
            self.user_bias.weight
        )

        nn.init.zeros_(
            self.movie_bias.weight
        )

    def forward(self, users, movies):
        user_vectors = (
            self.user_embedding(users)
        )

        movie_vectors = (
            self.movie_embedding(movies)
        )

        interaction = (
            user_vectors * movie_vectors
        ).sum(dim=1)

        return (
            self.global_mean
            + self.user_bias(users).squeeze(-1)
            + self.movie_bias(movies).squeeze(-1)
            + interaction
        )