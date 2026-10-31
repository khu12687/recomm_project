from .transformer.web import router as transformer_router

from .mf.web import router as mf_router
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from .auth.web import me as require_login
from starlette.concurrency import run_in_threadpool

from .auth.web import (
    get_auth_service,
    router as auth_router,
)

from .svd.web import (
    get_svd_service,
    router as svd_router,
)


@asynccontextmanager
async def lifespan(app):
    auth_service = get_auth_service()

    try:
        await run_in_threadpool(
            auth_service.initialize
        )

        yield

    finally:
        await run_in_threadpool(
            auth_service.close
        )

        await run_in_threadpool(
            get_svd_service().close
        )

        get_auth_service.cache_clear()
        get_svd_service.cache_clear()


app = FastAPI(
    title="추천 시스템 API",
    lifespan=lifespan,
)

# 회원가입·로그인 API는 기존대로 공개.
app.include_router(auth_router)

# 추천 API는 로그인한 회원만 접근.
app.include_router(
    svd_router,
    dependencies=[Depends(require_login)],
)

app.include_router(
    mf_router,
    dependencies=[Depends(require_login)],
)

app.include_router(
    transformer_router,
    dependencies=[Depends(require_login)],
)