"""AppRequest is the planning workflow; immutable revisions reuse durable approval jobs."""

from datetime import timedelta

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dkman.auth import Principal
from dkman.jobs import admin, begin_execution, claim, digest, event, finish, owned_lease
from dkman.models import (
    AppPlan,
    AppRequest,
    ApprovalRequest,
    AuditEvent,
    Household,
    HouseholdMembership,
    Job,
    UserProfile,
    new_id,
    utcnow,
)
from dkman.planning_schemas import (
    PlanApprovalCommand,
    PlanApprovalInput,
    PlanDocument,
    RequestInput,
    Requirements,
    RevisionInput,
)


def planning_role(actor: Principal) -> None:
    if not actor.roles.intersection({"member", "developer", "admin"}):
        raise HTTPException(403, "Member, developer or admin role required")


def member_households(actor: Principal) -> Select[str]:
    return (
        select(HouseholdMembership.household_id)
        .join(UserProfile, HouseholdMembership.user_id == UserProfile.id)
        .where(UserProfile.subject == actor.subject)
    )


def visible_requests(actor: Principal) -> Select[AppRequest]:
    planning_role(actor)
    query = select(AppRequest)
    if "admin" not in actor.roles:
        query = query.where(
            AppRequest.requested_by == actor.subject,
            (AppRequest.household_id.is_(None))
            | AppRequest.household_id.in_(member_households(actor)),
        )
    return query


def request_for(
    db: Session, request_id: str, actor: Principal, *, lock: bool = False
) -> AppRequest:
    query = visible_requests(actor).where(AppRequest.id == request_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    item = db.scalar(query)
    if item is None:
        raise HTTPException(404, "App request not found")
    return item


def check_household(db: Session, household_id: str | None, actor: Principal) -> None:
    if household_id is None:
        return
    group = db.scalar(select(Household).where(Household.id == household_id).with_for_update())
    if group is None or (
        "admin" not in actor.roles
        and db.scalar(
            select(Household.id).where(
                Household.id.in_(member_households(actor)), Household.id == household_id
            )
        )
        is None
    ):
        raise HTTPException(404, "Authorized household not found")


def audit(db: Session, actor: Principal, action: str, resource: str, correlation: str) -> None:
    db.add(
        AuditEvent(
            actor_subject=actor.subject,
            action=action,
            resource_id=resource,
            outcome="succeeded",
            correlation_id=correlation,
        )
    )


def new_plan(
    item: AppRequest, requirements: Requirements, actor: Principal, key: str, request_hash: str
) -> AppPlan:
    document = PlanDocument(household_id=item.household_id, requirements=requirements).model_dump(
        mode="json"
    )
    return AppPlan(
        id=new_id(),
        request_id=item.id,
        revision=item.current_revision,
        document=document,
        content_hash=digest(document),
        created_by=actor.subject,
        idempotency_key=key,
        request_hash=request_hash,
    )


def create_request(
    db: Session, body: RequestInput, key: str, actor: Principal, correlation: str
) -> AppRequest:
    planning_role(actor)
    fingerprint = digest(body.model_dump(mode="json"))

    def replay() -> AppRequest | None:
        existing = db.scalar(
            select(AppRequest).where(
                AppRequest.requested_by == actor.subject, AppRequest.idempotency_key == key
            )
        )
        if existing is not None:
            request_for(db, existing.id, actor)
            if existing.request_hash != fingerprint:
                raise HTTPException(409, "Idempotency key already binds a different request")
        return existing

    if (existing := replay()) is not None:
        return existing
    check_household(db, body.household_id, actor)
    item = AppRequest(
        id=new_id(),
        requested_by=actor.subject,
        household_id=body.household_id,
        title=body.requirements.title,
        current_revision=1,
        idempotency_key=key,
        request_hash=fingerprint,
    )
    db.add(item)
    try:
        db.flush()
        plan = new_plan(item, body.requirements, actor, key, fingerprint)
        db.add(plan)
        audit(db, actor, "app_request.created", item.id, correlation)
        audit(db, actor, "app_plan.created", plan.id, correlation)
        db.commit()
    except IntegrityError:
        db.rollback()
        if (existing := replay()) is None:
            raise
        return existing
    return item


def create_revision(
    db: Session, request_id: str, body: RevisionInput, key: str, actor: Principal, correlation: str
) -> AppPlan:
    # All writes serialize on the request. Review completion locks Job -> Request -> Household.
    item = request_for(db, request_id, actor, lock=True)
    check_household(db, item.household_id, actor)
    fingerprint = digest(body.model_dump(mode="json"))
    existing = db.scalar(
        select(AppPlan).where(
            AppPlan.request_id == item.id,
            AppPlan.created_by == actor.subject,
            AppPlan.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.request_hash != fingerprint:
            raise HTTPException(409, "Idempotency key already binds a different revision")
        return existing
    if item.current_revision != body.expected_revision:
        raise HTTPException(409, "App request has a newer revision; reload before editing")
    item.current_revision += 1
    item.title = body.requirements.title
    item.updated_at = utcnow()
    plan = new_plan(item, body.requirements, actor, key, fingerprint)
    db.add(plan)
    audit(db, actor, "app_plan.created", plan.id, correlation)
    db.commit()
    return plan


def plan_for(db: Session, plan_id: str, actor: Principal) -> AppPlan:
    plan = db.get(AppPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "App plan not found")
    request_for(db, plan.request_id, actor)
    return plan


def submit_plan_approval(
    db: Session, plan_id: str, body: PlanApprovalInput, key: str, actor: Principal, correlation: str
) -> Job:
    admin(actor)
    fingerprint = digest(
        {"action": "app_plan.approve", "resource_id": plan_id, **body.model_dump(mode="json")}
    )

    def replay() -> Job | None:
        existing = db.scalar(
            select(Job).where(Job.requested_by == actor.subject, Job.idempotency_key == key)
        )
        if existing is not None and existing.request_hash != fingerprint:
            raise HTTPException(409, "Idempotency key already binds a different request")
        return existing

    if (existing := replay()) is not None:
        return existing
    plan = plan_for(db, plan_id, actor)
    item = request_for(db, plan.request_id, actor, lock=True)
    db.refresh(plan)
    if item.current_revision != plan.revision or plan.approved_job_id is not None:
        raise HTTPException(409, "Only the current unapproved revision can be reviewed")
    if digest(plan.document) != plan.content_hash or body.content_hash != plan.content_hash:
        raise HTTPException(409, "App plan content changed; reload before approval")
    if (
        db.scalar(
            select(Job.id).where(
                Job.action == "app_plan.approve",
                Job.resource_id == plan.id,
                Job.state.not_in({"succeeded", "failed", "cancelled", "expired"}),
            )
        )
        is not None
    ):
        if (existing := replay()) is not None:
            return existing
        raise HTTPException(409, "This revision already has an active review")
    command = PlanApprovalCommand(
        resource_id=plan.id,
        subject=actor.subject,
        request_id=item.id,
        revision=plan.revision,
        content_hash=plan.content_hash,
    ).model_dump(mode="json")
    job = Job(
        id=new_id(),
        requested_by=actor.subject,
        idempotency_key=key,
        request_hash=fingerprint,
        action="app_plan.approve",
        resource_type="app_plan",
        resource_id=plan.id,
        risk="reversible",
        plan=command,
        plan_hash=digest(command),
        state="waiting_approval",
        requires_approval=True,
        event_sequence=0,
        correlation_id=correlation,
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
                resource_id=plan.id,
                plan_hash=job.plan_hash,
                expires_at=utcnow() + timedelta(minutes=15),
            )
        )
        event(db, job, "submitted", actor.subject)
        db.commit()
    except IntegrityError:
        db.rollback()
        if (existing := replay()) is None:
            raise
        return existing
    return job


def run_plan_approval(job_id: str, db: Session, actor: Principal) -> Job:
    admin(actor)
    token = claim(db, job_id, actor)
    begin_execution(db, job_id, token, actor)
    job = owned_lease(db, job_id, token, "running")
    try:
        command = PlanApprovalCommand.model_validate(job.plan)
        item = request_for(db, command.request_id, actor, lock=True)
        plan = db.get(AppPlan, command.resource_id, populate_existing=True)
        if (
            plan is None
            or plan.request_id != item.id
            or plan.revision != command.revision
            or plan.id != job.resource_id
            or job.resource_type != command.resource_type
            or command.subject != actor.subject
            or job.action != command.action
            or plan.content_hash != command.content_hash
            or digest(plan.document) != command.content_hash
            or PlanDocument.model_validate(plan.document).household_id != item.household_id
        ):
            raise ValueError("app_plan_changed")
        if item.current_revision != command.revision:
            raise ValueError("app_plan_superseded")
        if plan.approved_job_id is not None:
            raise ValueError("app_plan_already_approved")
    except (ValidationError, HTTPException, ValueError) as exc:
        code = "app_plan_superseded" if str(exc) == "app_plan_superseded" else "app_plan_changed"
        return finish(db, job_id, token, failure=code)
    # The approval record and succeeded job/event/audit commit together. No external side effect.
    plan.approved_job_id = job.id
    return finish(
        db,
        job_id,
        token,
        result={
            "app_plan_id": plan.id,
            "revision": plan.revision,
            "content_hash": plan.content_hash,
            "approved": True,
            "effect": "plan_recorded",
        },
    )
