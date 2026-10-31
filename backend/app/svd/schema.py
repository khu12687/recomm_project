from pydantic import BaseModel


class KPIResponse(BaseModel):
    mae: float
    mse: float
    rmse: float

    train_count: int
    validation_count: int
    factors: int


class RecommendationResponse(BaseModel):
    rank: int
    movie_id: int
    title: str
    genres: str
    predicted_rating: float