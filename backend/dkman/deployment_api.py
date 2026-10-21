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
    Identifier,
    InstallationContext,
    OperationView,
    PlanRequest,
    RuntimeView,
    build_plan,
    validate_plan,
)
from dkman.deployments.evidence import prove_completion
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
from dkman.models import (
    AppDefinition,
    AppInstallation,
    ApprovalRequest,
    DeploymentTarget,
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


def verified_plan(db: Session, job: Job, settings: Settings) -> DeploymentPlan:
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
    household(db, target.household_id)
    manifest = db.get(ServiceManifest, str(context.manifest_id))
    if (
        manifest is None
        or manifest.definition_id != plan.definition_id
        or manifest.version != plan.version
        or digest(manifest.content) != context.manifest_hash
    ):
        raise ValueError("Registered manifest changed")
    validate_plan(catalog(settings), plan)
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
        or f"deployment.{result.action}" != job.action
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
        return {}  # Completed historical v1 operations remain compatible.
    runtime = (
        DeploymentPlan.model_validate(job.plan) if job.action == "deployment.install" else None
    )
    from dkman.deployments.contracts import LifecyclePlan

    command = (
        DeploymentCommand(action="install", plan=runtime)
        if runtime
        else DeploymentCommand(
            action=LifecyclePlan.model_validate(job.plan).action,
            plan=LifecyclePlan.model_validate(job.plan).runtime,
            lifecycle=LifecyclePlan.model_validate(job.plan),
        )
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
    token = claim(db, job_id, actor, lease_seconds=180)
    job = owned_lease(db, job_id, token, "claimed")
    try:
        plan = verified_plan(db, job, request.app.state.settings)
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
        job.action not in LIFECYCLE_ACTIONS | {"deployment.install"}
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
