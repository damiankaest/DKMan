"""Persistent manual planning; a plan approval never builds or installs an application."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from dkman.auth import Principal, current_principal, require_admin
from dkman.database import get_session
from dkman.job_schemas import JobView
from dkman.models import AppPlan, AppRequest, Job
from dkman.planning import (
    create_request,
    create_revision,
    plan_for,
    request_for,
    submit_plan_approval,
    visible_requests,
)
from dkman.planning_schemas import (
    PlanApprovalInput,
    PlanView,
    RequestInput,
    RequestView,
    RevisionInput,
)

router = APIRouter(prefix="/api/v1", tags=["planning"])
Db = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(current_principal)]
Admin = Annotated[Principal, Depends(require_admin)]
Key = Annotated[str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]


@router.post(
    "/app-requests", response_model=RequestView, status_code=201, operation_id="createAppRequest"
)
def add_request(
    body: RequestInput,
    db: Db,
    actor: User,
    request: Request,
    response: Response,
    idempotency_key: Key,
) -> AppRequest:
    item = create_request(db, body, idempotency_key, actor, request.state.correlation_id)
    response.headers["Location"] = f"/api/v1/app-requests/{item.id}"
    return item


@router.get("/app-requests", response_model=list[RequestView], operation_id="listAppRequests")
def list_requests(
    db: Db, actor: User, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[AppRequest]:
    return list(
        db.scalars(
            visible_requests(actor)
            .order_by(AppRequest.updated_at.desc(), AppRequest.id.desc())
            .limit(limit)
        )
    )


@router.get("/app-requests/{request_id}", response_model=RequestView, operation_id="getAppRequest")
def get_request(request_id: str, db: Db, actor: User) -> AppRequest:
    return request_for(db, request_id, actor)


@router.get(
    "/app-requests/{request_id}/plans", response_model=list[PlanView], operation_id="listAppPlans"
)
def list_plans(
    request_id: str, db: Db, actor: User, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[AppPlan]:
    request_for(db, request_id, actor)
    return list(
        db.scalars(
            select(AppPlan)
            .where(AppPlan.request_id == request_id)
            .order_by(AppPlan.revision.desc())
            .limit(limit)
        )
    )


@router.post(
    "/app-requests/{request_id}/plans",
    response_model=PlanView,
    status_code=201,
    operation_id="createAppPlanRevision",
)
def add_revision(
    request_id: str,
    body: RevisionInput,
    db: Db,
    actor: User,
    request: Request,
    response: Response,
    idempotency_key: Key,
) -> AppPlan:
    plan = create_revision(
        db, request_id, body, idempotency_key, actor, request.state.correlation_id
    )
    response.headers["Location"] = f"/api/v1/app-plans/{plan.id}"
    return plan


@router.get("/app-plans/{plan_id}", response_model=PlanView, operation_id="getAppPlan")
def get_plan(plan_id: str, db: Db, actor: User) -> AppPlan:
    return plan_for(db, plan_id, actor)


@router.get(
    "/app-plans/{plan_id}/jobs", response_model=list[JobView], operation_id="listAppPlanJobs"
)
def plan_jobs(plan_id: str, db: Db, actor: Admin) -> list[Job]:
    plan_for(db, plan_id, actor)
    return list(
        db.scalars(
            select(Job)
            .where(
                Job.resource_type == "app_plan",
                Job.resource_id == plan_id,
                Job.action == "app_plan.approve",
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(50)
        )
    )


@router.post(
    "/app-plans/{plan_id}/approve",
    response_model=JobView,
    status_code=202,
    operation_id="requestAppPlanApproval",
)
def approve_plan(
    plan_id: str,
    body: PlanApprovalInput,
    db: Db,
    actor: Admin,
    request: Request,
    response: Response,
    idempotency_key: Key,
) -> Job:
    job = submit_plan_approval(
        db, plan_id, body, idempotency_key, actor, request.state.correlation_id
    )
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return job
