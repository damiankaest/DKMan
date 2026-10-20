"""Internal service; exposed on an isolated control network, never through the Hub proxy."""

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from dkman.deployment_adapter.compose import CommandError, ComposeProvider
from dkman.deployment_adapter.journal import AdapterError, Journal
from dkman.deployments.auth import Delegation, verify_delegation
from dkman.deployments.contracts import (
    READ_ACTIONS,
    Catalog,
    DeploymentCommand,
    DeploymentPlan,
    OperationView,
    PlanRequest,
    RuntimeView,
    build_plan,
    canonical_hash,
    validate_plan,
)


class AdapterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DKMAN_ADAPTER_", extra="ignore")
    state_root: Path = Path("/var/lib/dkman-adapter")
    catalog_file: Path = Path("/etc/dkman-adapter/catalog.json")
    secret_file: Path = Path("/run/secrets/adapter-delegation-key")
    docker_binary: str = Field(default="/usr/local/bin/docker", pattern=r"^/[a-zA-Z0-9/_-]+$")


def create_app(
    settings: AdapterSettings | None = None,
    provider_factory: Callable[[UUID], ComposeProvider] | None = None,
) -> FastAPI:
    settings = settings or AdapterSettings()
    factory = provider_factory or (
        lambda operation_id: ComposeProvider(
            settings.state_root, operation_id, settings.docker_binary
        )
    )

    async def recovery_loop(journal: Journal) -> None:
        while True:
            await asyncio.sleep(15)
            await asyncio.to_thread(journal.recover)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.secret_file.is_symlink() or settings.catalog_file.is_symlink():
            raise ValueError("Adapter configuration may not be symlinks")
        key = settings.secret_file.read_bytes().strip()
        if len(key) < 32:
            raise ValueError("Delegation key must contain at least 32 bytes")
        app.state.secret = key
        app.state.catalog = Catalog.model_validate_json(settings.catalog_file.read_text())
        app.state.journal = Journal(settings.state_root)
        app.state.journal.recover()
        task = asyncio.create_task(recovery_loop(app.state.journal))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="DKMan Deployment Adapter", version="0.1.0", lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    def grant(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Delegation:
        if credentials is None:
            raise HTTPException(401, "Delegation required")
        try:
            return verify_delegation(credentials.credentials, request.app.state.secret)
        except PermissionError as error:
            raise HTTPException(403, "Delegated action is not authorized") from error
        except (jwt.PyJWTError, ValidationError, ValueError) as error:
            raise HTTPException(401, "Invalid delegation") from error

    def bind(
        value: Delegation, action: str, operation_id: UUID, resource: UUID, plan_hash: str
    ) -> None:
        if (
            value.action != action
            or value.jti != operation_id
            or value.resource_id != resource
            or value.plan_hash != plan_hash
        ):
            raise HTTPException(403, "Delegation binding mismatch")

    @app.middleware("http")
    async def headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # No access logging; tokens/command bodies never enter request logs.
        if request.method == "POST":
            length = request.headers.get("content-length", "")
            if not length.isdigit() or int(length) > 16384:
                return JSONResponse({"detail": "Body exceeds adapter limit"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(AdapterError)
    async def adapter_error(_: Request, error: AdapterError) -> JSONResponse:
        return JSONResponse({"detail": error.code}, status_code=error.status)

    @app.exception_handler(sqlite3.Error)
    async def journal_error(_: Request, error: sqlite3.Error) -> JSONResponse:
        return JSONResponse({"detail": "Operation journal unavailable"}, status_code=503)

    @app.exception_handler(CommandError)
    async def command_error(_: Request, error: CommandError) -> JSONResponse:
        return JSONResponse({"detail": "Deployment engine unavailable"}, status_code=503)

    @app.get("/health/live", operation_id="getAdapterLiveness")
    def live() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/health/ready", operation_id="getAdapterReadiness")
    def ready() -> dict[str, str]:
        app.state.journal.recover()
        factory(UUID(int=0)).ready()
        return {"status": "healthy", "journal_revision": "2"}

    @app.post("/v1/plans", response_model=DeploymentPlan, operation_id="planDeployment")
    def plan(body: PlanRequest, value: Annotated[Delegation, Depends(grant)]) -> DeploymentPlan:
        bind(
            value,
            "plan",
            value.jti,
            body.installation_id,
            canonical_hash(body.model_dump(mode="json")),
        )
        try:
            return build_plan(app.state.catalog, body)
        except ValueError as error:
            raise HTTPException(409, "Image revision is not curated") from error

    @app.post(
        "/v1/operations/{operation_id}",
        response_model=OperationView,
        operation_id="executeDeploymentOperation",
    )
    def execute(
        operation_id: UUID, body: DeploymentCommand, value: Annotated[Delegation, Depends(grant)]
    ) -> OperationView:
        bind(value, body.action, operation_id, body.plan.installation_id, body.plan.plan_hash)
        try:
            validate_plan(app.state.catalog, body.plan)
        except ValueError as error:
            raise HTTPException(409, "Plan is not permitted by curated policy") from error
        journal: Journal = app.state.journal
        previous = journal.replay(body, value)
        if previous:
            return previous
        mutating = body.action not in READ_ACTIONS
        with journal.lock(body.plan.installation_id):
            previous = journal.replay(body, value)
            if previous:
                return previous
            current = journal.current_plan(body.plan.installation_id)
            if current is not None:
                if (
                    current.definition_id != body.plan.definition_id
                    or current.data_path != body.plan.data_path
                ):
                    raise HTTPException(409, "Installation identity or storage changed")
                if body.action not in {"install", "deploy", "pull"} and current != body.plan:
                    raise HTTPException(409, "Operation must target the current installation plan")
            provider = factory(operation_id)
            provider.preflight(body.plan, known=current is not None)
            observation = provider.status(body.plan)
            if body.action == "install" and observation.state != "absent":
                raise HTTPException(409, "Installation already exists")
            if body.action in {"start", "restart"} and observation.state == "absent":
                raise HTTPException(409, "Installation is absent")
            if body.action == "remove_data" and observation.state != "absent":
                raise HTTPException(409, "Remove workload before deleting data")
            # Repeat time validation after preflight; an expired request cannot begin execution.
            if value.exp <= int(datetime.now(UTC).timestamp()):
                raise HTTPException(401, "Delegation expired before execution")
            result = journal.begin(body, value, mutating)
            try:
                outcome = getattr(provider, body.action)(
                    body.plan
                )  # Action is a closed Literal enum.
                result = result.model_copy(
                    update={
                        "state": "succeeded",
                        "finished_at": datetime.now(UTC),
                        "runtime": outcome if isinstance(outcome, RuntimeView) else None,
                        "logs": outcome if isinstance(outcome, str) else None,
                    }
                )
            except Exception:
                result = result.model_copy(
                    update={
                        "state": "reconciliation_required" if mutating else "failed",
                        "failure_code": "execution_outcome_unknown"
                        if mutating
                        else "engine_read_failed",
                        "finished_at": datetime.now(UTC),
                    }
                )
            journal.finish(result, body, mutating)
            return result

    def read_operation(operation_id: UUID, value: Delegation, action: str) -> OperationView:
        if value.jti != operation_id or value.action != action:
            raise HTTPException(403, "Delegation binding mismatch")
        journal: Journal = app.state.journal
        item = journal.get(operation_id)
        if item is None:
            raise HTTPException(404, "Operation not found")
        bind(value, action, operation_id, item.installation_id, item.plan_hash)
        return item

    @app.get(
        "/v1/operations/{operation_id}",
        response_model=OperationView,
        operation_id="getDeploymentOperation",
    )
    def operation(
        operation_id: UUID, value: Annotated[Delegation, Depends(grant)]
    ) -> OperationView:
        return read_operation(operation_id, value, "operation.read")

    @app.get(
        "/v1/operations/{operation_id}/reconcile",
        response_model=OperationView,
        operation_id="observeUncertainDeploymentOperation",
    )
    def reconcile(
        operation_id: UUID, value: Annotated[Delegation, Depends(grant)]
    ) -> OperationView:
        item = read_operation(operation_id, value, "reconcile")
        journal: Journal = app.state.journal
        journal.recover()
        item = read_operation(operation_id, value, "reconcile")
        command = journal.stored_command(operation_id)
        provider = factory(operation_id)
        provider.preflight(
            command.plan, known=journal.current_plan(item.installation_id) is not None
        )
        return item.model_copy(update={"runtime": provider.status(command.plan)})

    return app
