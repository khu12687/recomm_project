from functools import lru_cache

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from .schema import (
    KPIResponse,
    RecommendationResponse,
)

from .service import (
    SVDError,
    SVDService,
)


router = APIRouter(
    prefix="/svd",
    tags=["SVD"],
)


@lru_cache
def get_svd_service():
    return SVDService()


def invoke(service, operation, *args):
    try:
        return service.execute(
            operation,
            *args,
        )

    except SVDError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@router.get(
    "/kpi",
    response_model=KPIResponse,
)
def get_kpi(
    service: SVDService = Depends(
        get_svd_service
    ),
):
    return invoke(
        service,
        "kpi",
    )


@router.get(
    "/recommendations",
    response_model=list[
        RecommendationResponse
    ],
)
def get_recommendations(
    user_id: int = Query(..., ge=1),
    service: SVDService = Depends(
        get_svd_service
    ),
):
    return invoke(
        service,
        "recommendations",
        user_id,
    )