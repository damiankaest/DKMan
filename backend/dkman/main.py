import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError

from dkman.access import router as access_router
from dkman.api import router
from dkman.auth import TokenVerifier
from dkman.config import Settings
from dkman.deployment_api import router as deployment_router
from dkman.deployment_health import health_loop
from dkman.deployments.client import HttpDeploymentClient
from dkman.health import readiness
from dkman.job_api import router as job_router
from dkman.job_recovery import recover_once, recovery_loop
from dkman.planning_api import router as planning_router
from dkman.runtime_api import router as runtime_router
from dkman.schemas import HealthView

logger = logging.getLogger("dkman.http")


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings()
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    owns_engine = engine is None
    if engine is None:
        engine = create_engine(
            settings.sqlalchemy_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
            hide_parameters=True,
        )
    active_engine = engine

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(recover_once, active_engine)
        task = asyncio.create_task(recovery_loop(active_engine))
        health_task = asyncio.create_task(
            health_loop(active_engine, settings, app.state.deployment_client)
        )
        try:
            yield
        finally:
            task.cancel()
            health_task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            with suppress(asyncio.CancelledError):
                await health_task
            if owns_engine:
                active_engine.dispose()

    app = FastAPI(title="DKMan Core", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.settings = settings
    app.state.verifier = TokenVerifier(settings)
    app.state.deployment_client = HttpDeploymentClient()

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Never accept an arbitrary user string into logs or echo secrets/query parameters.
        request.state.correlation_id = str(uuid.uuid4())
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        route = request.scope.get("route")
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request.state.correlation_id,
                    "method": request.method,
                    "route": getattr(route, "path", "unmatched"),
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                }
            )
        )
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(request: Request, _: SQLAlchemyError) -> JSONResponse:
        # Do not log exception strings: database URLs and query values may contain secrets.
        return JSONResponse(
            {
                "detail": "Database operation unavailable",
                "request_id": request.state.correlation_id,
            },
            status_code=503,
        )

    @app.get("/health/live", operation_id="getLiveness")
    def live() -> dict[str, str]:
        return {"status": "healthy", "version": "0.1.0"}

    @app.get("/health/ready", response_model=HealthView, operation_id="getReadiness")
    def ready(response: Response) -> HealthView:
        result = readiness(active_engine)
        if result.status != "healthy":
            response.status_code = 503
        return result

    app.include_router(router)
    app.include_router(access_router)
    app.include_router(job_router)
    app.include_router(deployment_router)
    app.include_router(runtime_router)
    app.include_router(planning_router)
    return app
