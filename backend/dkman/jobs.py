"""Durable state machine. Functions commit their transitions before returning.

PostgreSQL READ COMMITTED + job row locks serialize approval/cancel/claim/recovery.
No provider call may happen before begin_execution has successfully committed.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dkman.auth import Principal
from dkman.job_schemas import ApprovalBinding, ApprovalDecision, JobSubmission
from dkman.models import (
    AppDefinition,
    ApprovalRequest,
    AuditEvent,
    Job,
    JobEvent,
    ServiceManifest,
    new_id,
    utcnow,
)
from dkman.runtime_access import authorize_job, runtime_role

LEASE_SECONDS = 60
TERMINAL = {"succeeded", "failed", "cancelled", "expired"}


def utc(value: datetime) -> datetime:
    # SQLite test storage does not retain timezone information; PostgreSQL does.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


def admin(actor: Principal) -> None:
    if "admin" not in actor.roles:
        raise HTTPException(403, "Admin role required")


def locked_job(db: Session, job_id: str) -> Job:
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def approval_for(db: Session, job: Job) -> ApprovalRequest | None:
    # Always lock the job first. All approval mutations use this same lock order.
    return db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.job_id == job.id)
        .execution_options(populate_existing=True)
    )


def event(db: Session, job: Job, kind: str, actor: str) -> None:
    job.event_sequence += 1
    job.updated_at = utcnow()
    db.add(
        JobEvent(
            job_id=job.id,
            sequence=job.event_sequence,
            kind=kind,
            state=job.state,
            actor_subject=actor,
        )
    )
    db.add(
        AuditEvent(
            actor_subject=actor,
            action=f"job.{kind}",
            resource_id=job.id,
            outcome="unknown" if job.state == "reconciliation_required" else job.state,
            correlation_id=job.correlation_id,
        )
    )


def expire(db: Session, job: Job, approval: ApprovalRequest | None, now: datetime) -> bool:
    if approval and approval.state in {"pending", "approved"} and utc(approval.expires_at) <= now:
        approval.state = "expired"
        job.state = "expired"
        job.finished_at = now
        job.lease_token = None
        job.lease_expires_at = None
        event(db, job, "approval_expired", "system:recovery")
        return True
    return False


def matches(job: Job, approval: ApprovalRequest) -> bool:
    return (
        approval.subject == job.requested_by
        and approval.action == job.action
        and approval.resource_type == job.resource_type
        and approval.resource_id == job.resource_id
        and approval.plan_hash == job.plan_hash
        and digest(job.plan) == job.plan_hash
    )


def submit(db: Session, body: JobSubmission, key: str, actor: Principal, correlation: str) -> Job:
    admin(actor)
    request_hash = digest(body.model_dump(mode="json"))

    def replay() -> Job | None:
        existing = db.scalar(
            select(Job).where(Job.requested_by == actor.subject, Job.idempotency_key == key)
        )
        if existing is not None and existing.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key already binds a different request")
        return existing

    existing = replay()
    if existing is not None:
        return existing
    definition = db.get(AppDefinition, body.resource_id)
    if definition is None:
        raise HTTPException(404, "Definition not found")
    manifest = db.scalar(
        select(ServiceManifest).where(
            ServiceManifest.definition_id == definition.id,
            ServiceManifest.version == definition.version,
        )
    )
    if manifest is None:
        raise HTTPException(409, "Registered manifest unavailable")
    plan = {
        "schema_version": 1,
        "action": body.action,
        "resource_type": "app_definition",
        "resource_id": definition.id,
        "subject": actor.subject,
        "manifest_id": manifest.id,
        "manifest_hash": digest(manifest.content),
    }
    job = Job(
        id=new_id(),
        requested_by=actor.subject,
        idempotency_key=key,
        request_hash=request_hash,
        action=body.action,
        resource_type="app_definition",
        resource_id=definition.id,
        risk="read_only",
        plan=plan,
        plan_hash=digest(plan),
        state="waiting_approval" if body.require_approval else "queued",
        event_sequence=0,
        requires_approval=body.require_approval,
        correlation_id=correlation,
    )
    db.add(job)
    try:
        db.flush()  # Unique constraint arbitrates concurrent first submissions.
        if body.require_approval:
            db.add(
                ApprovalRequest(
                    job_id=job.id,
                    subject=actor.subject,
                    action=job.action,
                    resource_type=job.resource_type,
                    resource_id=job.resource_id,
                    plan_hash=job.plan_hash,
                    expires_at=utcnow() + timedelta(seconds=body.approval_ttl_seconds),
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
    return job


def decide(
    db: Session, approval_id: str, body: ApprovalDecision, actor: Principal
) -> ApprovalRequest:
    runtime_role(actor)
    job_id = db.scalar(select(ApprovalRequest.job_id).where(ApprovalRequest.id == approval_id))
    if job_id is None:
        raise HTTPException(404, "Approval not found")
    job = locked_job(db, job_id)
    authorize_job(db, job, actor)
    approval = approval_for(db, job)
    assert approval is not None
    expected = ApprovalBinding.model_validate(approval).model_dump()
    actual = body.model_dump(exclude={"decision"})
    expected["expires_at"] = utc(expected["expires_at"])
    actual["expires_at"] = utc(actual["expires_at"])
    if expected != actual or not matches(job, approval):
        raise HTTPException(409, "Approval binding mismatch")
    if expire(db, job, approval, utcnow()):
        db.commit()
        raise HTTPException(409, "Approval expired")
    target = "approved" if body.decision == "approve" else "rejected"
    if approval.state == target and approval.decided_by == actor.subject:
        return approval  # Exact decision replay does not extend expiry or append events.
    if approval.state != "pending" or job.state != "waiting_approval":
        raise HTTPException(409, "Approval decision conflicts with current state")
    approval.state = target
    approval.decided_by = actor.subject
    approval.decided_at = utcnow()
    job.state = "queued" if target == "approved" else "cancelled"
    if target == "rejected":
        job.finished_at = utcnow()
    event(db, job, f"approval_{target}", actor.subject)
    db.commit()
    return approval


def cancel(db: Session, job_id: str, actor: Principal) -> Job:
    runtime_role(actor)
    job = locked_job(db, job_id)
    authorize_job(db, job, actor)
    if job.state == "cancelled":
        return job
    if job.state not in {"waiting_approval", "queued"}:
        raise HTTPException(409, "Job cannot be cancelled in its current state")
    job.state = "cancelled"
    job.finished_at = utcnow()
    approval = approval_for(db, job)
    if approval is not None:
        approval.state = "cancelled"
    event(db, job, "cancelled", actor.subject)
    db.commit()
    return job


def claim(db: Session, job_id: str, actor: Principal, *, lease_seconds: int = LEASE_SECONDS) -> str:
    job = locked_job(db, job_id)
    authorize_job(db, job, actor)
    if job.requested_by != actor.subject:
        raise HTTPException(403, "Only the requesting identity may execute this job")
    approval = approval_for(db, job)
    if job.state == "queued" and expire(db, job, approval, utcnow()):
        db.commit()
    if job.state != "queued":
        raise HTTPException(409, "Job is not queued")
    job.state = "claimed"
    job.attempt += 1
    token = str(uuid4())
    job.lease_token = token
    job.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
    event(db, job, "claimed", actor.subject)
    db.commit()
    return token


def owned_lease(db: Session, job_id: str, token: str, state: str) -> Job:
    job = locked_job(db, job_id)
    if (
        job.state != state
        or job.lease_token != token
        or job.lease_expires_at is None
        or utc(job.lease_expires_at) <= utcnow()
    ):
        raise HTTPException(409, "Worker lease lost; reconcile before any further execution")
    return job


def begin_execution(db: Session, job_id: str, token: str, actor: Principal) -> Job:
    job = owned_lease(db, job_id, token, "claimed")
    authorize_job(db, job, actor)
    if actor.subject != job.requested_by:
        raise HTTPException(403, "Requesting identity mismatch")
    approval = approval_for(db, job)
    if expire(db, job, approval, utcnow()):
        db.commit()
        raise HTTPException(409, "Approval expired")
    if digest(job.plan) != job.plan_hash or (
        job.requires_approval
        and (approval is None or approval.state != "approved" or not matches(job, approval))
    ):
        job.state = "failed"
        job.failure_code = "approval_binding_invalid"
        job.finished_at = utcnow()
        job.lease_token = None
        job.lease_expires_at = None
        event(db, job, "authorization_failed", actor.subject)
        db.commit()
        raise HTTPException(409, "Approval or plan no longer matches")
    if approval is not None:
        approval.state = "consumed"
        approval.consumed_at = utcnow()
    job.state = "running"
    job.execution_started_at = utcnow()
    event(db, job, "execution_started", actor.subject)
    db.commit()  # Durable boundary BEFORE calling an action/provider.
    return job


def finish(
    db: Session,
    job_id: str,
    token: str,
    *,
    failure: str | None = None,
    result: dict[str, Any] | None = None,
) -> Job:
    job = owned_lease(db, job_id, token, "running")
    job.state = "failed" if failure else "succeeded"
    job.failure_code = failure
    job.result = result
    job.finished_at = utcnow()
    job.lease_token = None
    job.lease_expires_at = None
    event(db, job, job.state, job.requested_by)
    db.commit()
    return job


def recover(db: Session, *, now: datetime | None = None, limit: int = 100) -> int:
    """Metadata only. Never replay actions, and never steal another live lease."""
    now = now or utcnow()
    count = 0
    # Expiry and lease queries are bounded; SKIP LOCKED permits multiple Core replicas.
    jobs = db.scalars(
        select(Job)
        .where(
            ((Job.state.in_(["claimed", "running"])) & (Job.lease_expires_at <= now))
            | (
                (Job.state.in_(["waiting_approval", "queued"]))
                & Job.id.in_(
                    select(ApprovalRequest.job_id).where(
                        ApprovalRequest.expires_at <= now,
                        ApprovalRequest.state.in_(["pending", "approved"]),
                    )
                )
            )
        )
        .order_by(Job.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    for job in jobs:
        approval = approval_for(db, job)
        if job.state != "running" and expire(db, job, approval, now):
            count += 1
            continue
        if job.state == "claimed" and job.execution_started_at is None:
            job.state = "queued"
            kind = "recovered_before_execution"
        else:
            job.state = "reconciliation_required"
            job.failure_code = "execution_outcome_unknown"
            kind = "reconciliation_required"
        job.lease_token = None
        job.lease_expires_at = None
        event(db, job, kind, "system:recovery")
        count += 1
    db.commit()
    return count
