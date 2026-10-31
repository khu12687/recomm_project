from functools import lru_cache

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from .schema import (
    CodeResponse,
    EmailRequest,
    LoginRequest,
    MessageResponse,
    SignupRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from .service import AuthError, AuthService


router = APIRouter(tags=["auth"])

bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_auth_service():
    return AuthService()


def invoke(service, operation, *args):
    try:
        return service.execute(operation, *args)

    except AuthError as error:
        headers = {}

        if error.status_code == 401:
            headers["WWW-Authenticate"] = "Bearer"

        retry_after = getattr(
            error,
            "retry_after",
            None,
        )

        if retry_after is not None:
            headers["Retry-After"] = str(
                retry_after
            )

        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
            headers=headers or None,
        ) from error


@router.post(
    "/users",
    response_model=CodeResponse,
    status_code=201,
)
def signup(
    body: SignupRequest,
    service: AuthService = Depends(
        get_auth_service
    ),
):
    return invoke(
        service,
        "signup",
        str(body.email),
        body.password,
    )


@router.post(
    "/auth/verify-email",
    response_model=MessageResponse,
)
def verify_email(
    body: VerifyEmailRequest,
    service: AuthService = Depends(
        get_auth_service
    ),
):
    return invoke(
        service,
        "verify_email",
        str(body.email),
        body.code,
    )


@router.post(
    "/auth/resend-code",
    response_model=CodeResponse,
)
def resend_code(
    body: EmailRequest,
    service: AuthService = Depends(
        get_auth_service
    ),
):
    return invoke(
        service,
        "resend_code",
        str(body.email),
    )


@router.post(
    "/auth/login",
    response_model=TokenResponse,
)
def login(
    body: LoginRequest,
    service: AuthService = Depends(
        get_auth_service
    ),
):
    return invoke(
        service,
        "login",
        str(body.email),
        body.password,
    )


@router.get(
    "/users/me",
    response_model=UserResponse,
)
def me(
    credentials: (
        HTTPAuthorizationCredentials | None
    ) = Depends(bearer),
    service: AuthService = Depends(
        get_auth_service
    ),
):
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다.",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )

    return invoke(
        service,
        "me",
        credentials.credentials,
    )


@router.get(
    "/health",
    include_in_schema=False,
)
def health(
    service: AuthService = Depends(
        get_auth_service
    ),
):
    return invoke(service, "health")