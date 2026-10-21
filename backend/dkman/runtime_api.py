"""Lifecycle of existing installations through durable jobs and the isolated adapter."""

from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dkman.access import household
from dkman.auth import Principal, current_principal
from dkman.database import get_session
from dkman.deployment_api import (
    Key,
    accept_rejection,
    catalog,
    completion_result,
    credential,
    record_runtime,
    uncertain,
)
from dkman.deployments.contracts import (
    DeploymentCommand,
    DeploymentPlan,
    LifecycleAction,
    LifecyclePlan,
    OperationView,
    RuntimeView,
    validate_plan,
)
from dkman.deployments.redaction import redact_logs
from dkman.job_schemas import JobView
from dkman.jobs import begin_execution, claim, digest, event, locked_job, owned_lease, utc
from dkman.models import (
    AppDefinition,
    AppInstallation,
    ApprovalRequest,
    DeploymentTarget,
    Job,
    ServiceManifest,
    utcnow,
)
from dkman.runtime_access import (
    active_runtime_job,
    can_operate,
    runtime_installation,
    runtime_role,
)

router = APIRouter(prefix="/api/v1", tags=["runtime"])
Db = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(current_principal)]


class RuntimeInstallationView(BaseModel):
    id: str
    name: str
    household_id: str


class RuntimeStatusView(RuntimeView):
    reason: Literal["runtime_observation_unavailable", "runtime_not_healthy"] | None = None
    blocked_job_id: str | None = None


class RuntimeLogsView(BaseModel):
    installation_id: UUID
    observed_at: datetime
    text: str
    max_lines: Literal[100] = 100
    max_bytes: Literal[8192] = 8192


class LifecycleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.get(
    "/runtime/installations",
    response_model=list[RuntimeInstallationView],
    operation_id="listRuntimeInstallations",
)
def installations(db: Db, actor: User) -> list[RuntimeInstallationView]:
    runtime_role(actor)
    result = []
    for item in db.scalars(select(AppInstallation).order_by(AppInstallation.created_at)):
        if can_operate(db, item, actor):
            definition = db.get(AppDefinition, item.definition_id)
            assert definition is not None
            result.append(
                RuntimeInstallationView(
                    id=item.id, household_id=item.household_id, name=definition.name
                )
            )
    return result


def installed_plan(db: Session, item: AppInstallation) -> DeploymentPlan:
    target = db.get(DeploymentTarget, item.id)
    original = db.get(Job, target.job_id) if target else None
    if original is None or original.state != "succeeded" or original.action != "deployment.install":
        raise HTTPException(409, "Installed runtime provenance unavailable")
    plan = DeploymentPlan.model_validate(original.plan)
    if (
        str(plan.installation_id) != item.id
        or plan.context is None
        or str(plan.context.household_id) != item.household_id
        or str(plan.context.manifest_id) != item.manifest_id
        or plan.definition_id != item.definition_id
        or plan.plan_hash != original.plan_hash
    ):
        raise HTTPException(409, "Installed runtime provenance changed")
    return plan


def plan_lifecycle(
    action: LifecycleAction,
    installation_id: UUID,
    request: Request,
    response: Response,
    db: Session,
    actor: Principal,
    key: str,
) -> Job:
    item = runtime_installation(db, str(installation_id), actor)
    request_hash = digest(
        {"action": f"deployment.{action}", "installation_id": str(installation_id)}
    )

    def replay() -> Job | None:
        job = db.scalar(
            select(Job).where(Job.requested_by == actor.subject, Job.idempotency_key == key)
        )
        if job is not None and job.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key binds a different request")
        return job

    existing = replay()
    if existing:
        return existing
    # Same lock order as grant changes, then installation reservation. No external calls.
    household(db, item.household_id)
    db.scalar(select(AppInstallation).where(AppInstallation.id == item.id).with_for_update())
    runtime_installation(db, item.id, actor)  # Recheck after a concurrent grant revocation.
    existing = replay()
    if existing:
        return existing
    if active_runtime_job(db, item.id):
        raise HTTPException(409, "Installation has an active or unresolved runtime job")
    runtime = installed_plan(db, item)
    try:
        validate_plan(catalog(request.app.state.settings), runtime)
    except ValueError:
        raise HTTPException(409, "Installed runtime is no longer curated") from None
    plan = LifecyclePlan(
        action=action, resource_id=installation_id, subject=actor.subject, runtime=runtime
    )
    job = Job(
        id=str(uuid4()),
        requested_by=actor.subject,
        idempotency_key=key,
        request_hash=request_hash,
        action=f"deployment.{action}",
        resource_type="app_installation",
        resource_id=item.id,
        risk="reversible",
        plan=plan.model_dump(mode="json"),
        plan_hash=plan.plan_hash,
        state="waiting_approval",
        requires_approval=True,
        event_sequence=0,
        correlation_id=request.state.correlation_id,
    )
    db.add(job)
    try:
        db.flush()
        db.add(
            ApprovalRequest(
                job_id=job.id,
                subject=actor.subject,
                action=job.action,
                resource_type=job.resource_type,
                resource_id=item.id,
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


@router.post(
    "/installations/{installation_id}/start",
    response_model=JobView,
    status_code=202,
    operation_id="planInstallationStart",
)
def start(
    installation_id: UUID,
    body: LifecycleInput,
    request: Request,
    response: Response,
    db: Db,
    actor: User,
    idempotency_key: Key,
) -> Job:
    return plan_lifecycle("start", installation_id, request, response, db, actor, idempotency_key)


@router.post(
    "/installations/{installation_id}/stop",
    response_model=JobView,
    status_code=202,
    operation_id="planInstallationStop",
)
def stop(
    installation_id: UUID,
    body: LifecycleInput,
    request: Request,
    response: Response,
    db: Db,
    actor: User,
    idempotency_key: Key,
) -> Job:
    return plan_lifecycle("stop", installation_id, request, response, db, actor, idempotency_key)


@router.post(
    "/installations/{installation_id}/restart",
    response_model=JobView,
    status_code=202,
    operation_id="planInstallationRestart",
)
def restart(
    installation_id: UUID,
    body: LifecycleInput,
    request: Request,
    response: Response,
    db: Db,
    actor: User,
    idempotency_key: Key,
) -> Job:
    return plan_lifecycle("restart", installation_id, request, response, db, actor, idempotency_key)


def verified_lifecycle(db: Session, job: Job, request: Request, actor: Principal) -> LifecyclePlan:
    item = runtime_installation(db, job.resource_id, actor)
    household(db, item.household_id)
    runtime_installation(db, item.id, actor)
    plan = LifecyclePlan.model_validate(job.plan)
    if (
        job.action != f"deployment.{plan.action}"
        or job.resource_type != plan.resource_type
        or job.resource_id != str(plan.resource_id)
        or job.requested_by != plan.subject
        or job.plan_hash != plan.plan_hash
        or not job.requires_approval
        or job.risk != "reversible"
        or plan.runtime != installed_plan(db, item)
    ):
        raise ValueError("Lifecycle binding changed")
    manifest = db.get(ServiceManifest, item.manifest_id)
    if (
        manifest is None
        or plan.runtime.context is None
        or digest(manifest.content) != plan.runtime.context.manifest_hash
    ):
        raise ValueError("Installed manifest changed")
    validate_plan(catalog(request.app.state.settings), plan.runtime)
    return plan


def accept_lifecycle(db: Session, job: Job, result: OperationView, actor: Principal) -> Job:
    plan = LifecyclePlan.model_validate(job.plan)
    if accept_rejection(db, job, result, actor):
        return job
    try:
        proof_result = completion_result(job, result)
    except ValueError:
        return uncertain(db, job, actor)
    expected = "stopped" if plan.action == "stop" else "running"
    item = db.get(AppInstallation, job.resource_id)
    if (
        item is None
        or job.plan_hash != plan.plan_hash
        or job.action != f"deployment.{plan.action}"
        or job.resource_type != plan.resource_type
        or job.resource_id != str(plan.resource_id)
        or job.requested_by != plan.subject
        or result.operation_id != UUID(job.id)
        or result.installation_id != plan.resource_id
        or result.action != plan.action
        or result.plan_hash != job.plan_hash
        or result.state != "succeeded"
        or result.finished_at is None
        or result.runtime is None
        or result.runtime.installation_id != plan.resource_id
        or result.runtime.state != expected
        or not result.runtime.container_id
        or job.execution_started_at is None
        or utc(result.finished_at) < utc(job.execution_started_at)
        or utc(result.runtime.observed_at) < utc(job.execution_started_at)
    ):
        return uncertain(db, job, actor, result.failure_code)
    # Update only existing metadata; a lifecycle never materializes a new installation.
    item.desired_state = expected
    record_runtime(db, item.id, result.runtime)
    job.state = "succeeded"
    job.failure_code = None
    job.result = {
        "installation_id": item.id,
        "operation_id": job.id,
        "state": expected,
        **proof_result,
    }
    job.finished_at = utcnow()
    job.lease_token = None
    job.lease_expires_at = None
    event(db, job, "succeeded", actor.subject)
    db.commit()
    return job


def run_lifecycle(job_id: str, db: Session, actor: Principal, request: Request) -> Job:
    token = claim(db, job_id, actor, lease_seconds=180)
    job = owned_lease(db, job_id, token, "claimed")
    try:
        plan = verified_lifecycle(db, job, request, actor)
        credential(request.app.state.settings, actor, job, "operation.read")
    except (ValueError, HTTPException):
        job.state = "failed"
        job.failure_code = "lifecycle_preflight_failed"
        job.finished_at = utcnow()
        job.lease_token = None
        job.lease_expires_at = None
        event(db, job, "preflight_failed", actor.subject)
        db.commit()
        return job
    job = begin_execution(db, job_id, token, actor)
    try:
        delegation = credential(
            request.app.state.settings, actor, job, plan.action, mutate=True, db=db
        )
        db.commit()
        result = request.app.state.deployment_client.execute(
            UUID(job.id),
            DeploymentCommand(action=plan.action, plan=plan.runtime, lifecycle=plan),
            delegation,
        )
        job = owned_lease(db, job_id, token, "running")
        return accept_lifecycle(db, job, result, actor)
    except Exception:
        db.rollback()
        job = locked_job(db, job_id)
        if job.state == "running" and job.lease_token == token:
            return uncertain(db, job, actor)
        return job


@router.get(
    "/installations/{installation_id}/jobs",
    response_model=list[JobView],
    operation_id="listInstallationJobs",
)
def installation_jobs(installation_id: UUID, db: Db, actor: User) -> list[Job]:
    runtime_installation(db, str(installation_id), actor)
    query = (
        select(Job)
        .where(Job.resource_type == "app_installation", Job.resource_id == str(installation_id))
        .order_by(Job.created_at.desc())
        .limit(100)
    )
    if "admin" not in actor.roles:
        query = query.where(Job.requested_by == actor.subject)
    return list(db.scalars(query))


def observe(
    installation_id: UUID,
    request: Request,
    db: Session,
    actor: Principal,
    action: Literal["status", "logs"],
) -> OperationView:
    item = runtime_installation(db, str(installation_id), actor)
    plan = installed_plan(db, item)
    read = Job(id=str(uuid4()), resource_id=item.id, plan_hash=plan.plan_hash)
    token = credential(request.app.state.settings, actor, read, action)
    db.commit()
    result: OperationView = request.app.state.deployment_client.execute(
        UUID(read.id), DeploymentCommand(action=action, plan=plan), token
    )
    if (
        result.state != "succeeded"
        or result.operation_id != UUID(read.id)
        or result.installation_id != installation_id
        or result.action != action
        or result.plan_hash != plan.plan_hash
    ):
        raise ValueError("Observation does not match request")
    runtime_installation(db, str(installation_id), actor)  # Rights may change during I/O.
    return result


@router.get(
    "/installations/{installation_id}/status",
    response_model=RuntimeStatusView,
    operation_id="getInstallationStatus",
)
def status(installation_id: UUID, request: Request, db: Db, actor: User) -> RuntimeStatusView:
    runtime_installation(db, str(installation_id), actor)
    reason: Literal["runtime_observation_unavailable", "runtime_not_healthy"] | None
    try:
        result = observe(installation_id, request, db, actor, "status")
        if result.runtime is None or result.runtime.installation_id != installation_id:
            raise ValueError()
        runtime = result.runtime
        reason = None if runtime.state == "running" else "runtime_not_healthy"
    except HTTPException:
        raise
    except Exception:
        runtime = RuntimeView(
            installation_id=installation_id, state="unknown", observed_at=utcnow()
        )
        reason = "runtime_observation_unavailable"
    record_runtime(db, str(installation_id), runtime)
    blocked = active_runtime_job(db, str(installation_id))
    db.commit()
    return RuntimeStatusView(
        **runtime.model_dump(), reason=reason, blocked_job_id=blocked.id if blocked else None
    )


@router.get(
    "/installations/{installation_id}/logs",
    response_model=RuntimeLogsView,
    operation_id="getInstallationLogs",
)
def logs(installation_id: UUID, request: Request, db: Db, actor: User) -> RuntimeLogsView:
    runtime_installation(db, str(installation_id), actor)
    try:
        result = observe(installation_id, request, db, actor, "logs")
        if result.logs is None:
            raise ValueError()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "runtime_logs_unavailable") from None
    return RuntimeLogsView(
        installation_id=installation_id, observed_at=utcnow(), text=redact_logs(result.logs)
    )
