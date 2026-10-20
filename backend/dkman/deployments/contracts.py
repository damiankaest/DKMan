import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,62}$")]
ImageReference = Annotated[
    str,
    StringConstraints(
        pattern=r"^(sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64})$"
    ),
]
DataPath = Annotated[str, StringConstraints(pattern=r"^/(data|app/data|var/lib/[a-z][a-z0-9-]*)$")]
Action = Literal[
    "discover",
    "pull",
    "install",
    "deploy",
    "start",
    "stop",
    "restart",
    "status",
    "logs",
    "remove",
    "remove_data",
]
READ_ACTIONS = {"discover", "status", "logs"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


class CuratedImage(StrictModel):
    definition_id: Identifier
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    image: ImageReference
    internal_port: int = Field(ge=1024, le=65535)
    data_path: DataPath | None = None
    user: Literal["10001:10001"] = "10001:10001"
    memory_mb: int = Field(default=128, ge=32, le=1024)
    cpus: float = Field(default=0.5, ge=0.1, le=2, allow_inf_nan=False)


class Catalog(StrictModel):
    schema_version: Literal[1] = 1
    images: list[CuratedImage] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_revisions(self) -> "Catalog":
        keys = [(item.definition_id, item.version) for item in self.images]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate curated revision")
        return self


class PlanRequest(StrictModel):
    installation_id: UUID
    definition_id: Identifier
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class DeploymentPlan(CuratedImage):
    schema_version: Literal[1] = 1
    provider: Literal["docker-compose"] = "docker-compose"
    installation_id: UUID

    @property
    def plan_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    @property
    def project(self) -> str:
        return f"dkman-app-{self.installation_id}"


def build_plan(catalog: Catalog, request: PlanRequest) -> DeploymentPlan:
    for image in catalog.images:
        if (image.definition_id, image.version) == (request.definition_id, request.version):
            return DeploymentPlan(**image.model_dump(), installation_id=request.installation_id)
    raise ValueError("Image revision is not curated")


def validate_plan(catalog: Catalog, plan: DeploymentPlan) -> None:
    expected = build_plan(
        catalog,
        PlanRequest(
            installation_id=plan.installation_id,
            definition_id=plan.definition_id,
            version=plan.version,
        ),
    )
    if expected != plan:
        raise ValueError("Plan does not match the curated image policy")


class DeploymentCommand(StrictModel):
    action: Action
    plan: DeploymentPlan


class RuntimeView(StrictModel):
    installation_id: UUID
    state: Literal["absent", "running", "stopped", "starting", "unhealthy", "unknown"]
    observed_at: datetime
    container_id: str | None = None


class OperationView(StrictModel):
    operation_id: UUID
    installation_id: UUID
    action: Action
    plan_hash: str
    state: Literal["running", "succeeded", "failed", "reconciliation_required"]
    created_at: datetime
    finished_at: datetime | None = None
    failure_code: str | None = None
    runtime: RuntimeView | None = None
    logs: str | None = None


class DeploymentProvider(Protocol):
    def discover(self, plan: DeploymentPlan) -> RuntimeView: ...
    def pull(self, plan: DeploymentPlan) -> None: ...
    def install(self, plan: DeploymentPlan) -> RuntimeView: ...
    def deploy(self, plan: DeploymentPlan) -> RuntimeView: ...
    def start(self, plan: DeploymentPlan) -> RuntimeView: ...
    def stop(self, plan: DeploymentPlan) -> RuntimeView: ...
    def restart(self, plan: DeploymentPlan) -> RuntimeView: ...
    def status(self, plan: DeploymentPlan) -> RuntimeView: ...
    def logs(self, plan: DeploymentPlan) -> str: ...
    def remove(self, plan: DeploymentPlan) -> RuntimeView: ...
    def remove_data(self, plan: DeploymentPlan) -> None: ...
