import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import enforce_same_origin
from app.api.routes import (
    account,
    admin_users,
    auth,
    billing,
    dashboard,
    health,
    jobs,
    lessons,
    lessons_admin,
    library,
    movements,
    practice,
    scales_admin,
    theory,
    two_factor,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.monitoring import init_monitoring
from music_theory.errors import TheoryError

logger = logging.getLogger("app")


def create_app() -> FastAPI:
    settings = get_settings()
    init_monitoring(settings)
    if settings.is_production and settings.trusted_proxies < 1:  # get_settings() refuses this too
        logger.warning("PIANO_TRUSTED_PROXIES is 0 in production; rate limits see the proxy's IP")
    # The interactive API docs are for developers; do not publish them in production.
    hide = settings.is_production
    app = FastAPI(
        title="Piano Learning Platform API",
        version="0.1.0",
        dependencies=[Depends(enforce_same_origin)],
        docs_url=None if hide else "/docs",
        redoc_url=None if hide else "/redoc",
        openapi_url=None if hide else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )

    @app.middleware("http")
    async def harden(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # Answers are personal (who you are, what you paid); never let a browser or proxy keep them.
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("Unhandled error (request %s)", request_id, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Something went wrong on our side. Try again in a moment.",
                    "details": {"request_id": request_id},
                }
            },
            # Server errors are answered outside the middleware above, so set these here too.
            headers={
                "X-Request-ID": request_id or "",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            },
        )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            headers=exc.headers,
        )

    @app.exception_handler(TheoryError)
    async def handle_theory_error(_: Request, exc: TheoryError) -> JSONResponse:
        # Invalid musical input is the caller's problem (422); a generator that cannot produce
        # an exercise is ours (500) but still carries a stable code.
        status = 500 if exc.code == "generation_failed" else 422
        return JSONResponse(
            status_code=status,
            content={"error": {"code": exc.code, "message": exc.message, "details": {}}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": jsonable_encoder(exc.errors(), custom_encoder={Exception: str}),
                }
            },
        )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(jobs.router)
    app.include_router(theory.router)
    app.include_router(lessons.router)
    app.include_router(practice.router)
    app.include_router(lessons_admin.router)
    app.include_router(movements.router)
    app.include_router(movements.admin)
    app.include_router(scales_admin.router)
    app.include_router(two_factor.router)
    app.include_router(account.router)
    app.include_router(admin_users.router)
    app.include_router(billing.router)
    app.include_router(billing.institution)
    app.include_router(billing.admin)
    app.include_router(library.router)
    app.include_router(dashboard.router)
    return app


app = create_app()
