"""Authenticated job API; no client-controlled state/result or execution credentials."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from dkman.auth import Principal, current_principal, require_admin
from dkman.database import get_session
from dkman.deployments.contracts import LIFECYCLE_ACTIONS
from dkman.job_schemas import (
    ApprovalDecision,
    ApprovalView,
    JobEventView,
    JobSubmission,
    JobView,
    ValidationPlan,
)
from dkman.jobs import (
    approval_for,
    begin_execution,
    cancel,
    claim,
    decide,
    digest,
    event,
    finish,
    owned_lease,
    submit,
)
from dkman.manifest import Manifest
from dkman.models import ApprovalRequest, Job, JobEvent, ServiceManifest
from dkman.runtime_access import authorize_job, runtime_principal, runtime_role

router = APIRouter(prefix="/api/v1", tags=["jobs"])
Db = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(current_principal)]
Admin = Annotated[Principal, Depends(require_admin)]
Runtime = Annotated[Principal, Depends(runtime_principal)]


def visible_job(db: Session, job_id: str, actor: Principal) -> Job:
    query = select(Job).where(Job.id == job_id)
    if "admin" not in actor.roles:
        query = query.where(Job.requested_by == actor.subject)
    job = db.scalar(query)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.action in LIFECYCLE_ACTIONS:
        authorize_job(db, job, actor)
    return job


@router.post("/jobs", response_model=JobView, status_code=202, operation_id="submitJob")
def submit_job(
    body: JobSubmission,
    db: Db,
    actor: Admin,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    ],
) -> Job:
    job = submit(db, body, idempotency_key, actor, request.state.correlation_id)
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return job


@router.get("/jobs", response_model=list[JobView], operation_id="listJobs")
def list_jobs(db: Db, actor: User, limit: Annotated[int, Query(ge=1, le=100)] = 50) -> list[Job]:
    query = select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)
    if "admin" not in actor.roles:
        query = query.where(Job.requested_by == actor.subject)
    return list(db.scalars(query))


@router.get("/jobs/{job_id}", response_model=JobView, operation_id="getJob")
def get_job(job_id: str, db: Db, actor: User) -> Job:
    return visible_job(db, job_id, actor)


@router.get("/jobs/{job_id}/events", response_model=list[JobEventView], operation_id="getJobEvents")
def get_events(
    job_id: str,
    db: Db,
    actor: User,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[JobEvent]:
    visible_job(db, job_id, actor)
    return list(
        db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.sequence > after)
            .order_by(JobEvent.sequence)
            .limit(limit)
        )
    )


@router.get("/jobs/{job_id}/approval", response_model=ApprovalView, operation_id="getJobApproval")
def get_approval(job_id: str, db: Db, actor: User) -> ApprovalRequest:
    job = visible_job(db, job_id, actor)
    approval = approval_for(db, job)
    if approval is None:
        raise HTTPException(404, "Job does not require approval")
    return approval


@router.post(
    "/approvals/{approval_id}/decision", response_model=ApprovalView, operation_id="decideApproval"
)
def decide_approval(
    approval_id: str, body: ApprovalDecision, db: Db, actor: Runtime
) -> ApprovalRequest:
    return decide(db, approval_id, body, actor)


@router.post("/jobs/{job_id}/cancel", response_model=JobView, operation_id="cancelJob")
def cancel_job(job_id: str, db: Db, actor: Runtime) -> Job:
    return cancel(db, job_id, actor)


def validate_registered_manifest(db: Session, job: Job) -> dict[str, str | bool]:
    plan = ValidationPlan.model_validate(job.plan)
    if (
        plan.action != job.action
        or plan.resource_id != job.resource_id
        or plan.resource_type != job.resource_type
        or plan.subject != job.requested_by
    ):
        raise ValueError("plan_changed")
    manifest = db.get(ServiceManifest, plan.manifest_id)
    if (
        manifest is None
        or manifest.definition_id != job.resource_id
        or digest(manifest.content) != plan.manifest_hash
    ):
        raise ValueError("resource_changed")
    Manifest.model_validate(manifest.content)
    return {"valid": True, "manifest_id": manifest.id}


@router.post("/jobs/{job_id}/run", response_model=JobView, operation_id="runJob")
def run_validation(job_id: str, db: Db, actor: Runtime, request: Request) -> Job:
    # Both executors use typed server plans and the same durable approval boundary.
    runtime_role(actor)
    job = visible_job(db, job_id, actor)
    authorize_job(db, job, actor)
    if job.action in LIFECYCLE_ACTIONS:
        from dkman.runtime_api import run_lifecycle

        return run_lifecycle(job_id, db, actor, request)
    if job.action == "deployment.install":
        from dkman.deployment_api import run_installation

        return run_installation(job_id, db, actor, request)
    if job.action != "registry.validate":
        raise HTTPException(409, "No executor registered for this action")
    token = claim(db, job_id, actor)
    job = begin_execution(db, job_id, token, actor)
    try:
        result = validate_registered_manifest(db, job)
    except (ValidationError, ValueError):
        return finish(db, job_id, token, failure="manifest_validation_failed")
    except Exception:
        # No exception content is persisted/logged. Unknown outcomes never auto-retry.
        db.rollback()
        job = owned_lease(db, job_id, token, "running")
        job.state = "reconciliation_required"
        job.failure_code = "execution_outcome_unknown"
        job.lease_token = None
        job.lease_expires_at = None
        event(db, job, "reconciliation_required", actor.subject)
        db.commit()
        return job
    return finish(db, job_id, token, result=result)
