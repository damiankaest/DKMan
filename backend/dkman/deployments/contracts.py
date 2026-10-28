import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from dkman.forge.attestation import (
    SignedBuildEvidence,
    SignedPreviewEvidence,
    key_id,
    verify_preview_signature,
    verify_signature,
)

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
MAX_FORGE_DEPLOY_ARCHIVE = 256 * 1024 * 1024


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
    user: Literal["10001:10001", "101"] = "10001:10001"
    memory_mb: int = Field(default=128, ge=32, le=1024)
    cpus: float = Field(default=0.5, ge=0.1, le=2, allow_inf_nan=False)
    # Omit only the new empty/default fields, preserving P2-002 wire hashes/replays.
    profile: Literal["web-v1", "notes-postgres-v1", "forge-spa-v1"] = Field(
        default="web-v1", exclude_if=lambda value: value == "web-v1"
    )
    database_image: ImageReference | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    source_hash: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$", exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def profile_contract(self) -> "CuratedImage":
        if self.profile == "notes-postgres-v1":
            if (
                self.definition_id != "demo-notes"
                or self.version != "0.1.0"
                or self.internal_port != 8080
                or self.data_path is not None
                or self.database_image is None
                or self.source_hash is None
            ):
                raise ValueError("Notes requires its exact reviewed database/runtime profile")
        elif self.profile == "forge-spa-v1":
            if (
                not self.definition_id.startswith("forge-")
                or self.internal_port != 8080
                or self.user != "101"
                or self.data_path is not None
                or self.database_image is not None
                or self.source_hash is None
                or not self.image.startswith("sha256:")
                or self.memory_mb != 256
                or self.cpus != 0.5
            ):
                raise ValueError("Forge SPA requires its exact reviewed runtime profile")
        elif self.database_image is not None:
            raise ValueError("Database sidecars require a reviewed profile")
        if self.profile != "forge-spa-v1" and self.user != "10001:10001":
            raise ValueError("The image user is not permitted for this profile")
        return self


class Catalog(StrictModel):
    schema_version: Literal[1] = 1
    images: list[CuratedImage] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_revisions(self) -> "Catalog":
        keys = [(item.definition_id, item.version) for item in self.images]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate curated revision")
        return self


class InstallationContext(StrictModel):
    household_id: UUID
    subject: str = Field(min_length=1, max_length=255)
    manifest_id: UUID
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class PlanRequest(StrictModel):
    installation_id: UUID
    definition_id: Identifier
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    context: InstallationContext | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ForgeReleaseProof(StrictModel):
    build: SignedBuildEvidence
    preview: SignedPreviewEvidence

    @model_validator(mode="after")
    def same_artifact(self) -> "ForgeReleaseProof":
        build = self.build.evidence
        preview = self.preview.evidence
        if (
            build.template != "react-spa"
            or build.archive_size > MAX_FORGE_DEPLOY_ARCHIVE
            or preview.artifact_id != build.build_id
            or preview.workspace_id != build.workspace_id
            or preview.artifact_evidence_hash != canonical_hash(self.build.model_dump(mode="json"))
            or preview.source_hash != build.source_hash
            or preview.plan_hash != build.plan_hash
            or preview.manifest_digest != build.manifest_digest
            or preview.config_digest != build.config_digest
        ):
            raise ValueError("Forge preview and build evidence do not match")
        return self


class DeploymentPlan(CuratedImage):
    schema_version: Literal[1] = 1
    provider: Literal["docker-compose"] = "docker-compose"
    installation_id: UUID
    context: InstallationContext | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    forge: ForgeReleaseProof | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def forge_binding(self) -> "DeploymentPlan":
        if self.profile == "forge-spa-v1":
            if (
                self.forge is None
                or self.context is None
                or self.image != self.forge.build.evidence.config_digest
                or self.source_hash != self.forge.build.evidence.source_hash
            ):
                raise ValueError("Forge runtime must bind its signed build and preview")
        elif self.forge is not None:
            raise ValueError("Forge evidence is only permitted on Forge runtimes")
        return self

    @property
    def plan_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    @property
    def project(self) -> str:
        return f"dkman-app-{self.installation_id}"


def build_plan(catalog: Catalog, request: PlanRequest) -> DeploymentPlan:
    for image in catalog.images:
        if (image.definition_id, image.version) == (request.definition_id, request.version):
            return DeploymentPlan(
                **image.model_dump(),
                installation_id=request.installation_id,
                context=request.context,
            )
    raise ValueError("Image revision is not curated")


def validate_plan(
    catalog: Catalog,
    plan: DeploymentPlan,
    *,
    builder_key: Any = None,
    preview_key: Any = None,
    require_fresh_preview: bool = False,
) -> None:
    if plan.profile == "forge-spa-v1":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        if (
            not isinstance(builder_key, Ed25519PublicKey)
            or not isinstance(preview_key, Ed25519PublicKey)
            or key_id(builder_key) == key_id(preview_key)
            or plan.forge is None
        ):
            raise ValueError("Forge verification keys are required and must differ")
        verify_signature(plan.forge.build, builder_key)
        verify_preview_signature(plan.forge.preview, preview_key)
        if require_fresh_preview:
            now = datetime.now(UTC)
            observation = plan.forge.preview.evidence
            if observation.expires_at <= now or observation.observed_at > now + timedelta(
                seconds=30
            ):
                raise ValueError("Preview evidence is expired or not yet valid")
        return
    expected = build_plan(
        catalog,
        PlanRequest(
            installation_id=plan.installation_id,
            definition_id=plan.definition_id,
            version=plan.version,
            context=plan.context,
        ),
    )
    if expected != plan:
        raise ValueError("Plan does not match the curated image policy")


LifecycleAction = Literal["start", "stop", "restart"]
LIFECYCLE_ACTIONS = {"deployment.start", "deployment.stop", "deployment.restart"}


class LifecyclePlan(StrictModel):
    schema_version: Literal[1] = 1
    action: LifecycleAction
    resource_type: Literal["app_installation"] = "app_installation"
    resource_id: UUID
    subject: str = Field(min_length=1, max_length=255)
    runtime: DeploymentPlan

    @model_validator(mode="after")
    def same_resource(self) -> "LifecyclePlan":
        if self.resource_id != self.runtime.installation_id:
            raise ValueError("Lifecycle resource differs from runtime")
        return self

    @property
    def plan_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class UpgradePlan(StrictModel):
    schema_version: Literal[1] = 1
    action: Literal["deploy"] = "deploy"
    resource_type: Literal["app_installation"] = "app_installation"
    resource_id: UUID
    subject: str = Field(min_length=1, max_length=255)
    previous: DeploymentPlan
    replacement: DeploymentPlan

    @model_validator(mode="after")
    def same_installation(self) -> "UpgradePlan":
        old, new = self.previous, self.replacement
        if (
            old.profile != "forge-spa-v1"
            or new.profile != "forge-spa-v1"
            or old.forge is None
            or new.forge is None
            or old.context is None
            or new.context is None
            or old.installation_id != self.resource_id
            or new.installation_id != self.resource_id
            or old.definition_id != new.definition_id
            or old.context.household_id != new.context.household_id
            or new.context.subject != self.subject
            or old.context.manifest_id == new.context.manifest_id
            or old.version == new.version
            or old.forge.build.evidence.build_id == new.forge.build.evidence.build_id
        ):
            raise ValueError("Forge update must bind one installation and a new revision")
        return self

    @property
    def plan_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class DeploymentCommand(StrictModel):
    action: Action
    plan: DeploymentPlan
    lifecycle: LifecyclePlan | None = Field(default=None, exclude_if=lambda value: value is None)
    upgrade: UpgradePlan | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def bound_lifecycle(self) -> "DeploymentCommand":
        if self.lifecycle and (
            self.lifecycle.action != self.action or self.lifecycle.runtime != self.plan
        ):
            raise ValueError("Lifecycle command mismatch")
        if self.upgrade and (
            self.lifecycle is not None
            or self.action != "deploy"
            or self.upgrade.replacement != self.plan
        ):
            raise ValueError("Update command mismatch")
        if self.action == "deploy" and self.plan.profile == "forge-spa-v1" and self.upgrade is None:
            raise ValueError("Forge deploy requires a bound update plan")
        return self

    @property
    def plan_hash(self) -> str:
        return (
            self.upgrade.plan_hash
            if self.upgrade
            else (self.lifecycle.plan_hash if self.lifecycle else self.plan.plan_hash)
        )


class RuntimeView(StrictModel):
    installation_id: UUID
    state: Literal["absent", "running", "stopped", "starting", "unhealthy", "unknown"]
    observed_at: datetime
    container_id: str | None = None


class ContainerEvidence(StrictModel):
    service: Literal["app", "database"]
    container_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    image_id: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    runtime_plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["created", "running", "paused", "restarting", "removing", "exited", "dead"]
    health: Literal["healthy", "starting", "unhealthy"] | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime
    volumes: list[str] = Field(max_length=1)


class WorkloadEvidence(StrictModel):
    observed_at: AwareDatetime
    containers: list[ContainerEvidence] = Field(max_length=2)


class EngineReceipt(StrictModel):
    schema_version: Literal[1] = 1
    operation_id: UUID
    installation_id: UUID
    action: LifecycleAction | Literal["install", "deploy"]
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    before: WorkloadEvidence
    acknowledged_at: AwareDatetime


class CompletionEvidence(StrictModel):
    kind: Literal["engine_acknowledgement"] = "engine_acknowledgement"
    receipt: EngineReceipt
    after: WorkloadEvidence

    @property
    def evidence_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class RejectionEvidence(StrictModel):
    kind: Literal["preflight_rejected"] = "preflight_rejected"
    operation_id: UUID
    installation_id: UUID
    action: Action
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: Literal[
        "curation_rejected", "resource_preflight_rejected", "engine_preflight_unavailable"
    ]
    observed_at: AwareDatetime

    @property
    def evidence_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


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
    completion: CompletionEvidence | None = Field(default=None, exclude_if=lambda v: v is None)
    rejection: RejectionEvidence | None = Field(default=None, exclude_if=lambda v: v is None)


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
