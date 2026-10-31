from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix


@dataclass
class SVDModel:
    version: int
    user_ids: np.ndarray
    movie_ids: np.ndarray

    user_means: np.ndarray
    user_factors: np.ndarray
    movie_factors: np.ndarray

    seen: csr_matrix

    rating_min: float
    rating_max: float

    metrics: dict