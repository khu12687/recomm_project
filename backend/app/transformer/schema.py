from pydantic import BaseModel


class KPIResponse(BaseModel):
    mae: float
    mse: float
    rmse: float

    train_count: int
    validation_count: int
    best_epoch: int
    max_history: int
    device: str


class RecommendationResponse(BaseModel):
    rank: int
    movie_id: int
    title: str
    genres: str
    predicted_rating: float