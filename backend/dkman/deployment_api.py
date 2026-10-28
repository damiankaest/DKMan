"""Curated installation flow: OIDC -> bound approval -> durable job -> isolated adapter."""

from datetime import timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dkman.access import household
from dkman.auth import Principal, current_principal, require_admin
from dkman.config import Settings
from dkman.database import get_session
from dkman.deployments.auth import sign_delegation
from dkman.deployments.client import AdapterUnavailable
from dkman.deployments.contracts import (
    LIFECYCLE_ACTIONS,
    Catalog,
    CuratedImage,
    DeploymentCommand,
    DeploymentPlan,
    ForgeReleaseProof,
    Identifier,
    InstallationContext,
    OperationView,
    PlanRequest,
    RuntimeView,
    UpgradePlan,
    build_plan,
    validate_plan,
)
from dkman.deployments.evidence import prove_completion
from dkman.forge.attestation import SignedBuildEvidence, SignedPreviewEvidence, read_public_key
from dkman.job_schemas import JobView
from dkman.jobs import (
    approval_for,
    begin_execution,
    claim,
    digest,
    event,
    locked_job,
    owned_lease,
    utc,
)
from dkman.manifest import Manifest
from dkman.models import (
    AppDefinition,
    AppInstallation,
    ApprovalRequest,
    DeploymentTarget,
    ForgeBuildArtifact,
    ForgePreview,
    HealthObservation,
    Job,
    ServiceInstance,
    ServiceManifest,
    utcnow,
)

router = APIRouter(prefix="/api/v1", tags=["deployments"])
Db = Annotated[Session, Depends(get_session)]
Admin = Annotated[Principal, Depends(require_admin)]
Key = Annotated[str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]


def catalog(settings: Settings) -> Catalog:
    if not settings.deployment_enabled:
        return Catalog()
    path = settings.deployment_catalog_file
    try:
        if path.is_symlink():
            raise ValueError()
        return Catalog.model_validate_json(path.read_text())
    except (OSError, ValueError):
        raise HTTPException(503, "Curated deployment catalog unavailable") from None


def validate_runtime_policy(
    settings: Settings, plan: DeploymentPlan, *, fresh: bool = False
) -> None:
    if plan.profile != "forge-spa-v1":
        validate_plan(catalog(settings), plan)
        return
    if (
        not settings.deployment_enabled
        or settings.forge_builder_public_key_file is None
        or settings.forge_preview_public_key_file is None
    ):
        raise ValueError("Forge deployment verification is unavailable")
    try:
        builder = read_public_key(settings.forge_builder_public_key_file)
        preview = read_public_key(settings.forge_preview_public_key_file)
        validate_plan(
            catalog(settings),
            plan,
            builder_key=builder,
            preview_key=preview,
            require_fresh_preview=fresh,
        )
    except (OSError, TypeError) as exc:
        raise ValueError("Forge deployment verification is unavailable") from exc


def credential(
    settings: Settings,
    actor: Principal,
    job: Job,
    action: str,
    *,
    mutate: bool = False,
    db: Session | None = None,
) -> str:
    if not settings.deployment_enabled or settings.deployment_secret_file.is_symlink():
        raise HTTPException(503, "Deployment adapter is not configured")
    try:
        secret = settings.deployment_secret_file.read_bytes().strip()
        if len(secret) < 32:
            raise ValueError()
    except (OSError, ValueError):
        raise HTTPException(503, "Deployment credentials unavailable") from None
    approval = approval_for(db, job) if db is not None else None
    if mutate and (approval is None or approval.state != "consumed"):
        raise HTTPException(409, "Bound approval was not consumed")
    return sign_delegation(
        secret=secret,
        subject=actor.subject,
        roles=sorted(actor.roles),
        operation_id=UUID(job.id),
        action=action,
        resource_id=UUID(job.resource_id),
        plan_hash=job.plan_hash,
        approval_id=UUID(approval.id) if mutate and approval else None,
        approval_expires_at=utc(approval.expires_at) if mutate and approval else None,
    )


class InstallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition_id: Identifier
    household_id: UUID


@router.get(
    "/deployments/catalog", response_model=list[CuratedImage], operation_id="listCuratedApps"
)
def curated_apps(request: Request, actor: Admin) -> list[CuratedImage]:
    return [
        x for x in catalog(request.app.state.settings).images if x.profile == "notes-postgres-v1"
    ]


@router.post(
    "/deployments/installations",
    response_model=JobView,
    status_code=202,
    operation_id="planInstallation",
)
def plan_installation(
    body: InstallInput,
    request: Request,
    response: Response,
    db: Db,
    actor: Admin,
    idempotency_key: Key,
) -> Job:
    request_hash = digest({"action": "deployment.install", **body.model_dump(mode="json")})

    def replay() -> Job | None:
        job = db.scalar(
            select(Job).where(
                Job.requested_by == actor.subject, Job.idempotency_key == idempotency_key
            )
        )
        if job is not None and job.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key binds a different request")
        return job

    existing = replay()
    if existing is not None:
        return existing
    household(
        db, str(body.household_id)
    )  # PG row lock serializes household deployment reservations.
    # A concurrent request with the same key may have committed while we waited.
    existing = replay()
    if existing is not None:
        return existing
    reserved = db.scalar(
        select(DeploymentTarget)
        .join(Job, Job.id == DeploymentTarget.job_id)
        .where(
            DeploymentTarget.household_id == str(body.household_id),
            DeploymentTarget.definition_id == body.definition_id,
            Job.state.not_in(["cancelled", "expired", "failed"]),
        )
    )
    if reserved is not None:
        raise HTTPException(409, "This household already has an installation or an unresolved plan")
    definition = db.get(AppDefinition, body.definition_id)
    if definition is None:
        raise HTTPException(404, "Registered definition not found")
    manifest = db.scalar(
        select(ServiceManifest).where(
            ServiceManifest.definition_id == definition.id,
            ServiceManifest.version == definition.version,
        )
    )
    if manifest is None:
        raise HTTPException(409, "Registered manifest unavailable")
    installation_id = uuid4()
    try:
        plan = build_plan(
            catalog(request.app.state.settings),
            PlanRequest(
                installation_id=installation_id,
                definition_id=definition.id,
                version=definition.version,
                context=InstallationContext(
                    household_id=body.household_id,
                    subject=actor.subject,
                    manifest_id=UUID(manifest.id),
                    manifest_hash=digest(manifest.content),
                ),
            ),
        )
    except ValueError:
        raise HTTPException(409, "This revision is not curated") from None
    if plan.profile != "notes-postgres-v1":
        raise HTTPException(409, "No Core installation policy for this profile")
    job = Job(
        id=str(uuid4()),
        requested_by=actor.subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        action="deployment.install",
        resource_type="app_installation",
        resource_id=str(installation_id),
        risk="sensitive",
        plan=plan.model_dump(mode="json"),
        plan_hash=plan.plan_hash,
        state="waiting_approval",
        event_sequence=0,
        requires_approval=True,
        correlation_id=request.state.correlation_id,
    )
    db.add(job)
    try:
        db.flush()
        db.add(
            DeploymentTarget(
                id=str(installation_id),
                job_id=job.id,
                household_id=str(body.household_id),
                definition_id=definition.id,
            )
        )
        db.add(
            ApprovalRequest(
                job_id=job.id,
                subject=actor.subject,
                action=job.action,
                resource_type=job.resource_type,
                resource_id=job.resource_id,
                plan_hash=job.plan_hash,
                expires_at=utcnow() + timedelta(minutes=15),
            )
        )
        event(db, job, "submitted", actor.subject)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = replay()
        if existing is None:
            raise
        return existing
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return job


class ForgeInstallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    household_id: UUID


def forge_manifest(definition_id: str, version: str, title: str, image: str) -> Manifest:
    return Manifest.model_validate(
        {
            "schemaVersion": "dkman.io/v1alpha1",
            "id": definition_id,
            "name": title,
            "version": version,
            "type": "web-app",
            "description": "Forge starter with a separately reviewed preview",
            "ui": {"displayName": title, "icon": "grid", "route": f"/run/{definition_id}/"},
            "runtime": {
                "deploymentProvider": "docker-compose",
                "image": image,
                "internalPort": 8080,
                "memoryMb": 256,
                "cpus": 0.5,
            },
            "health": {"livePath": "/health/live", "readyPath": "/health/ready"},
            "capabilities": [],
            "dependencies": [],
        }
    )


@router.post(
    "/forge/previews/{preview_id}/installations",
    response_model=JobView,
    status_code=202,
    operation_id="planForgeInstallation",
)
def plan_forge_installation(
    preview_id: UUID,
    body: ForgeInstallInput,
    request: Request,
    response: Response,
    db: Db,
    actor: Admin,
    idempotency_key: Key,
) -> Job:
    from dkman.forge_api import current_bundle, verify_preview, visible_workspace
    from dkman.planning import plan_for, request_for

    fingerprint = digest(
        {
            "action": "deployment.install",
            "preview_id": str(preview_id),
            **body.model_dump(mode="json"),
        }
    )

    def replay() -> Job | None:
        previous = db.scalar(
            select(Job).where(
                Job.requested_by == actor.subject, Job.idempotency_key == idempotency_key
            )
        )
        if previous is not None and previous.request_hash != fingerprint:
            raise HTTPException(409, "Idempotency key binds a different request")
        return previous

    if (existing := replay()) is not None:
        return existing
    observation = db.get(ForgePreview, str(preview_id))
    artifact = db.get(ForgeBuildArtifact, observation.artifact_id) if observation else None
    if observation is None or artifact is None:
        raise HTTPException(404, "Preview not found")
    workspace = visible_workspace(db, artifact.workspace_id, actor)
    bundle = current_bundle(db, workspace, actor)
    plan_record = plan_for(db, workspace.plan_id, actor)
    parent = request_for(db, plan_record.request_id, actor, lock=True)
    if parent.household_id is not None and parent.household_id != str(body.household_id):
        raise HTTPException(409, "Preview belongs to a different household")
    household(db, str(body.household_id))
    if (existing := replay()) is not None:
        return existing
    verified = verify_preview(observation, artifact, workspace, request)
    if verified.evidence.expires_at <= utcnow():
        raise HTTPException(409, "Preview evidence has expired")
    if bundle.request.template != "react-spa":
        raise HTTPException(409, "Production installation currently supports only the SPA starter")
    definition_id = "forge-" + UUID(parent.id).hex
    reserved = db.scalar(
        select(DeploymentTarget)
        .join(Job, Job.id == DeploymentTarget.job_id)
        .where(
            DeploymentTarget.definition_id == definition_id,
            Job.state.not_in(["cancelled", "expired", "failed"]),
        )
    )
    if reserved is not None:
        raise HTTPException(409, "This app is already installed or has an unresolved plan")
    signed_build = SignedBuildEvidence.model_validate(artifact.attestation)
    signed_preview = SignedPreviewEvidence.model_validate(observation.attestation)
    version = f"0.{plan_record.revision}.{int(UUID(artifact.id).hex[:12], 16)}"
    manifest = forge_manifest(
        definition_id,
        version,
        bundle.request.requirements.title,
        signed_build.evidence.config_digest,
    )
    content = manifest.model_dump(by_alias=True)
    definition = db.get(AppDefinition, definition_id)
    if definition is None:
        definition = AppDefinition(
            id=definition_id,
            name=manifest.name,
            version=version,
            description=manifest.description,
            source=f"forge:{parent.id}",
        )
        db.add(definition)
        db.flush()
    elif definition.source != f"forge:{parent.id}":
        raise HTTPException(409, "Registered app identity changed")
    else:
        # No active or completed reservation exists, so this is a new installation after
        # a cancelled/failed plan rather than an update of a running instance.
        definition.name = manifest.name
        definition.version = version
    record = db.scalar(
        select(ServiceManifest).where(
            ServiceManifest.definition_id == definition_id, ServiceManifest.version == version
        )
    )
    if record is None:
        record = ServiceManifest(
            definition_id=definition_id,
            schema_version=manifest.schema_version,
            version=version,
            content=content,
        )
        db.add(record)
        db.flush()
    elif record.content != content:
        raise HTTPException(409, "Registered app revision differs from the build")
    installation_id = uuid4()
    plan = DeploymentPlan(
        definition_id=definition_id,
        version=version,
        image=signed_build.evidence.config_digest,
        internal_port=8080,
        user="101",
        memory_mb=256,
        cpus=0.5,
        profile="forge-spa-v1",
        source_hash=workspace.bundle_hash,
        installation_id=installation_id,
        context=InstallationContext(
            household_id=body.household_id,
            subject=actor.subject,
            manifest_id=UUID(record.id),
            manifest_hash=digest(content),
        ),
        forge=ForgeReleaseProof(build=signed_build, preview=signed_preview),
    )
    try:
        validate_runtime_policy(request.app.state.settings, plan, fresh=True)
    except ValueError:
        raise HTTPException(
            409, "Forge deployment is not curated or its preview has expired"
        ) from None
    job = Job(
        id=str(uuid4()),
        requested_by=actor.subject,
        idempotency_key=idempotency_key,
        request_hash=fingerprint,
        action="deployment.install",
        resource_type="app_installation",
        resource_id=str(installation_id),
        risk="sensitive",
        plan=plan.model_dump(mode="json"),
        plan_hash=plan.plan_hash,
        state="waiting_approval",
        event_sequence=0,
        requires_approval=True,
        correlation_id=request.state.correlation_id,
    )
    db.add(job)
    try:
        db.flush()
        db.add(
            DeploymentTarget(
                id=str(installation_id),
                job_id=job.id,
                household_id=str(body.household_id),
                definition_id=definition_id,
            )
        )
        db.add(
            ApprovalRequest(
                job_id=job.id,
                subject=actor.subject,
                action=job.action,
                resource_type=job.resource_type,
                resource_id=job.resource_id,
                plan_hash=job.plan_hash,
                expires_at=min(utc(verified.evidence.expires_at), utcnow() + timedelta(minutes=15)),
            )
        )
        event(db, job, "submitted", actor.subject)
        db.commit()
    except IntegrityError:
        db.rollback()
        if (existing := replay()) is None:
            raise
        return existing
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return job


def verified_forge_source(db: Session, actor: Principal, plan: DeploymentPlan, home_id: str) -> int:
    from dkman.forge.attestation import verify_recipe
    from dkman.forge.templates import TemplateProvider
    from dkman.forge_api import current_bundle, visible_workspace
    from dkman.planning import plan_for, request_for

    proof = plan.forge
    if proof is None:
        raise ValueError("Forge proof is missing")
    workspace = visible_workspace(db, str(proof.build.evidence.workspace_id), actor)
    bundle = current_bundle(db, workspace, actor)
    parent_plan = plan_for(db, workspace.plan_id, actor)
    parent = request_for(db, parent_plan.request_id, actor, lock=True)
    artifact = db.get(ForgeBuildArtifact, str(proof.build.evidence.build_id))
    preview = db.get(ForgePreview, str(proof.preview.evidence.preview_id))
    definition = db.get(AppDefinition, plan.definition_id)
    version = f"0.{parent_plan.revision}.{int(proof.build.evidence.build_id.hex[:12], 16)}"
    if (
        artifact is None
        or preview is None
        or definition is None
        or definition.source != f"forge:{parent.id}"
        or artifact.workspace_id != workspace.id
        or preview.artifact_id != artifact.id
        or digest(artifact.attestation) != artifact.evidence_hash
        or digest(preview.attestation) != preview.evidence_hash
        or artifact.attestation != proof.build.model_dump(mode="json")
        or preview.attestation != proof.preview.model_dump(mode="json")
        or workspace.bundle_hash != proof.build.evidence.source_hash
        or TemplateProvider().generate(bundle.request) != bundle
        or plan.definition_id != "forge-" + UUID(parent.id).hex
        or plan.version != version
        or (parent.household_id is not None and parent.household_id != home_id)
    ):
        raise ValueError("Forge authorization or evidence changed")
    verify_recipe(proof.build.evidence, bundle)
    return parent_plan.revision


def verified_plan(db: Session, job: Job, settings: Settings, actor: Principal) -> DeploymentPlan:
    plan = DeploymentPlan.model_validate(job.plan)
    target = db.get(DeploymentTarget, job.resource_id)
    context = plan.context
    if (
        target is None
        or target.job_id != job.id
        or context is None
        or target.household_id != str(context.household_id)
        or target.definition_id != plan.definition_id
        or job.resource_type != "app_installation"
        or job.resource_id != str(plan.installation_id)
        or job.action != "deployment.install"
        or job.requested_by != context.subject
        or job.plan_hash != plan.plan_hash
        or not job.requires_approval
        or job.risk != "sensitive"
    ):
        raise ValueError("Installation binding changed")
    if plan.forge is not None:
        verified_forge_source(db, actor, plan, target.household_id)
        definition = db.get(AppDefinition, plan.definition_id)
        if definition is None or definition.version != plan.version:
            raise ValueError("Registered app revision changed")
    household(db, target.household_id)
    manifest = db.get(ServiceManifest, str(context.manifest_id))
    if (
        manifest is None
        or manifest.definition_id != plan.definition_id
        or manifest.version != plan.version
        or digest(manifest.content) != context.manifest_hash
    ):
        raise ValueError("Registered manifest changed")
    validate_runtime_policy(settings, plan, fresh=plan.forge is not None)
    return plan


def uncertain(db: Session, job: Job, actor: Principal, code: str | None = None) -> Job:
    job.state = "reconciliation_required"
    job.failure_code = (
        code
        if code in {"execution_receipt_missing", "execution_evidence_incomplete"}
        else "execution_outcome_unknown"
    )
    job.lease_token = None
    job.lease_expires_at = None
    event(db, job, "reconciliation_required", actor.subject)
    db.commit()
    return job


def record_runtime(db: Session, installation_id: str, runtime: RuntimeView) -> ServiceInstance:
    service = db.scalar(
        select(ServiceInstance)
        .where(ServiceInstance.id == installation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        service is not None
        and service.checked_at is not None
        and utc(service.checked_at) >= utc(runtime.observed_at)
    ):
        return service  # A delayed read must not overwrite newer stop/start evidence.
    if service is None:
        service = ServiceInstance(
            id=installation_id, installation_id=installation_id, provider="docker-compose"
        )
        db.add(service)
    service.status = {"running": "healthy", "absent": "stopped"}.get(runtime.state, runtime.state)
    service.runtime_id = runtime.container_id
    service.checked_at = runtime.observed_at
    service.status_reason = (
        None
        if service.status == "healthy"
        else (
            "runtime_observation_unavailable"
            if service.status == "unknown"
            else "runtime_observation"
        )
    )
    db.flush()
    db.add(
        HealthObservation(
            service_id=service.id,
            status=service.status,
            reason=service.status_reason,
            created_at=runtime.observed_at,
        )
    )
    return service


def accept_rejection(db: Session, job: Job, result: OperationView, actor: Principal) -> bool:
    proof = result.rejection
    if (
        digest(job.plan) != job.plan_hash
        or result.state != "failed"
        or proof is None
        or result.completion is not None
        or result.operation_id != UUID(job.id)
        or str(result.installation_id) != job.resource_id
        or ("deployment.upgrade" if result.action == "deploy" else f"deployment.{result.action}")
        != job.action
        or result.plan_hash != job.plan_hash
        or proof.operation_id != result.operation_id
        or proof.installation_id != result.installation_id
        or proof.action != result.action
        or proof.plan_hash != result.plan_hash
        or result.failure_code != proof.reason
        or result.finished_at is None
        or job.execution_started_at is None
        or utc(proof.observed_at) < utc(job.execution_started_at)
        or utc(result.finished_at) < utc(proof.observed_at)
        or result.runtime is not None
    ):
        return False
    job.state = "failed"
    job.failure_code = proof.reason
    job.result = {
        "operation_id": job.id,
        "evidence_hash": proof.evidence_hash,
        "evidence_kind": proof.kind,
    }
    job.finished_at = utcnow()
    job.lease_token = None
    job.lease_expires_at = None
    event(db, job, "preflight_rejected", actor.subject)
    db.commit()
    return True


def completion_result(job: Job, outcome: OperationView) -> dict[str, str]:
    if outcome.completion is None:
        if job.action == "deployment.upgrade":
            raise ValueError("Forge update requires an engine receipt")
        if job.action in LIFECYCLE_ACTIONS:
            from dkman.deployments.contracts import LifecyclePlan

            if LifecyclePlan.model_validate(job.plan).runtime.profile == "forge-spa-v1":
                raise ValueError("Forge runtime requires an engine receipt")
        return {}  # Completed historical v1 operations remain compatible.
    runtime = (
        DeploymentPlan.model_validate(job.plan) if job.action == "deployment.install" else None
    )
    from dkman.deployments.contracts import LifecyclePlan

    if runtime:
        command = DeploymentCommand(action="install", plan=runtime)
    elif job.action == "deployment.upgrade":
        update = UpgradePlan.model_validate(job.plan)
        command = DeploymentCommand(action="deploy", plan=update.replacement, upgrade=update)
    else:
        lifecycle = LifecyclePlan.model_validate(job.plan)
        command = DeploymentCommand(
            action=lifecycle.action, plan=lifecycle.runtime, lifecycle=lifecycle
        )
    if job.execution_started_at is None:
        raise ValueError("Execution marker missing")
    evidence, measured = prove_completion(
        command,
        UUID(job.id),
        utc(job.execution_started_at),
        outcome.completion.receipt,
        outcome.completion.after,
    )
    if measured != outcome.runtime:
        raise ValueError("Completion observation mismatch")
    return {"evidence_hash": evidence.evidence_hash, "evidence_kind": evidence.kind}


def accept_outcome(db: Session, job: Job, outcome: OperationView, actor: Principal) -> Job:
    plan = DeploymentPlan.model_validate(job.plan)
    if accept_rejection(db, job, outcome, actor):
        return job
    if plan.profile == "forge-spa-v1" and outcome.completion is None:
        return uncertain(db, job, actor, "execution_evidence_incomplete")
    try:
        proof_result = completion_result(job, outcome)
    except ValueError:
        return uncertain(db, job, actor)
    if (
        plan.plan_hash != job.plan_hash
        or plan.context is None
        or plan.context.subject != job.requested_by
        or job.action != "deployment.install"
        or job.resource_id != str(plan.installation_id)
        or str(outcome.operation_id) != job.id
        or str(outcome.installation_id) != job.resource_id
        or outcome.action != "install"
        or outcome.plan_hash != job.plan_hash
        or outcome.state != "succeeded"
        or outcome.runtime is None
        or outcome.runtime.installation_id != plan.installation_id
        or outcome.runtime.state != "running"
        or not outcome.runtime.container_id
        or outcome.finished_at is None
        or job.execution_started_at is None
        or utc(outcome.finished_at) < utc(job.execution_started_at)
        or utc(outcome.runtime.observed_at) < utc(job.execution_started_at)
    ):
        return uncertain(db, job, actor, outcome.failure_code)
    assert plan.context is not None
    if db.get(AppInstallation, job.resource_id) is None:
        db.add(
            AppInstallation(
                id=job.resource_id,
                definition_id=plan.definition_id,
                manifest_id=str(plan.context.manifest_id),
                household_id=str(plan.context.household_id),
                owner_subject=job.requested_by,
                desired_state="running",
            )
        )
        db.flush()
    record_runtime(db, job.resource_id, outcome.runtime)
    job.state = "succeeded"
    job.failure_code = None
    job.result = {"installation_id": job.resource_id, "operation_id": job.id, **proof_result}
    job.finished_at = utcnow()
    job.lease_token = None
    job.lease_expires_at = None
    event(db, job, "succeeded", actor.subject)
    db.commit()
    return job


def run_installation(job_id: str, db: Session, actor: Principal, request: Request) -> Job:
    pending = db.get(Job, job_id)
    lease_seconds = 600 if pending and pending.plan.get("profile") == "forge-spa-v1" else 180
    token = claim(db, job_id, actor, lease_seconds=lease_seconds)
    job = owned_lease(db, job_id, token, "claimed")
    try:
        plan = verified_plan(db, job, request.app.state.settings, actor)
        # Confirm configured credentials before consuming the approval. No external action.
        credential(request.app.state.settings, actor, job, "operation.read")
    except (ValueError, HTTPException):
        job.state = "failed"
        job.failure_code = "installation_preflight_failed"
        job.finished_at = utcnow()
        job.lease_token = None
        job.lease_expires_at = None
        event(db, job, "preflight_failed", actor.subject)
        db.commit()
        return job
    job = begin_execution(db, job_id, token, actor)
    try:
        delegation = credential(
            request.app.state.settings, actor, job, "install", mutate=True, db=db
        )
        db.commit()  # No open DB transaction/row lock over an external request.
        outcome = request.app.state.deployment_client.execute(
            UUID(job.id), DeploymentCommand(action="install", plan=plan), delegation
        )
        job = owned_lease(db, job_id, token, "running")
        return accept_outcome(db, job, outcome, actor)
    except Exception:
        # Includes transport loss after successful remote execution and local commit errors.
        db.rollback()
        job = locked_job(db, job_id)
        if job.state == "running" and job.lease_token == token:
            return uncertain(db, job, actor)
        return job


@router.post(
    "/jobs/{job_id}/reconcile", response_model=JobView, operation_id="reconcileInstallationJob"
)
def reconcile_job(
    job_id: UUID, request: Request, db: Db, actor: Annotated[Principal, Depends(current_principal)]
) -> Job:
    from dkman.runtime_access import authorize_job

    authorize_job(db, locked_job(db, str(job_id)), actor)
    job = locked_job(db, str(job_id))
    if job.requested_by != actor.subject:
        raise HTTPException(403, "Requesting identity required")
    if (
        job.action not in LIFECYCLE_ACTIONS | {"deployment.install", "deployment.upgrade"}
        or job.state != "reconciliation_required"
    ):
        raise HTTPException(409, "Job does not require installation reconciliation")
    # Do not resend a mutation, even when the adapter returns 404.
    token = credential(request.app.state.settings, actor, job, "reconcile")
    db.commit()
    try:
        outcome = request.app.state.deployment_client.operation(job_id, token, reconcile=True)
    except (AdapterUnavailable, ValidationError):
        raise HTTPException(503, "Operation outcome remains unknown; no retry was sent") from None
    job = locked_job(db, str(job_id))
    if job.state == "succeeded":
        return job
    if job.state != "reconciliation_required":
        raise HTTPException(409, "Job state changed")
    authorize_job(db, job, actor)
    if job.action in LIFECYCLE_ACTIONS:
        from dkman.runtime_api import accept_lifecycle

        return accept_lifecycle(db, job, outcome, actor)
    if job.action == "deployment.upgrade":
        from dkman.forge_upgrade_api import accept_upgrade

        return accept_upgrade(db, job, outcome, actor)
    return accept_outcome(db, job, outcome, actor)


@router.post(
    "/apps/{app_id}/refresh", response_model=RuntimeView, operation_id="refreshInstallationStatus"
)
def refresh_status(app_id: UUID, request: Request, db: Db, actor: Admin) -> RuntimeView:
    target = db.get(DeploymentTarget, str(app_id))
    if target is None or db.get(AppInstallation, str(app_id)) is None:
        raise HTTPException(404, "Installed app not found")
    original = db.get(Job, target.job_id)
    assert original is not None
    plan = DeploymentPlan.model_validate(original.plan)
    # A separate, read-only operation never consumes/reuses an install approval.
    read = Job(id=str(uuid4()), resource_id=str(app_id), plan_hash=original.plan_hash)
    token = credential(request.app.state.settings, actor, read, "status")
    db.commit()
    try:
        result: OperationView = request.app.state.deployment_client.execute(
            UUID(read.id), DeploymentCommand(action="status", plan=plan), token
        )
        if (
            result.state != "succeeded"
            or result.runtime is None
            or result.runtime.installation_id != app_id
            or result.plan_hash != plan.plan_hash
            or str(result.operation_id) != read.id
            or result.action != "status"
        ):
            raise ValueError()
    except (AdapterUnavailable, ValueError):
        raise HTTPException(503, "Runtime observation unavailable") from None
    record_runtime(db, str(app_id), result.runtime)
    db.commit()
    return result.runtime
