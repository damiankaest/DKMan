"""Derive generation input from a current, approved and authorized plan snapshot."""

from typing import Literal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from dkman.auth import Principal
from dkman.forge.workspace import GenerationRequest
from dkman.jobs import digest
from dkman.models import Job
from dkman.planning import plan_for, request_for
from dkman.planning_schemas import PlanApprovalCommand, PlanDocument

Template = Literal["python-api", "react-spa", "fullstack-fastapi-react"]


def generation_request_for(
    db: Session, actor: Principal, plan_id: str, template: Template
) -> GenerationRequest:
    """Read and verify a snapshot; callers must recheck before any external side effect."""
    if not actor.roles.intersection({"developer", "admin"}):
        raise HTTPException(403, "Developer or admin role required")
    plan = plan_for(db, plan_id, actor)
    item = request_for(db, plan.request_id, actor)
    if plan.revision != item.current_revision or not plan.approved_job_id:
        raise HTTPException(409, "Current approved plan required")
    job = db.get(Job, plan.approved_job_id)
    try:
        document = PlanDocument.model_validate(plan.document)
        if job is None:
            raise ValueError("missing job")
        command = PlanApprovalCommand.model_validate(job.plan)
        if (
            job.state != "succeeded"
            or job.action != "app_plan.approve"
            or job.resource_type != "app_plan"
            or job.resource_id != plan.id
            or digest(job.plan) != job.plan_hash
            or command.resource_id != plan.id
            or command.request_id != item.id
            or command.revision != plan.revision
            or command.content_hash != plan.content_hash
            or command.subject != job.requested_by
            or document.household_id != item.household_id
            or digest(plan.document) != plan.content_hash
            or job.result
            != {
                "app_plan_id": plan.id,
                "revision": plan.revision,
                "content_hash": plan.content_hash,
                "approved": True,
                "effect": "plan_recorded",
            }
        ):
            raise ValueError("invalid approval binding")
    except (ValidationError, ValueError):
        raise HTTPException(409, "Plan approval could not be verified") from None
    return GenerationRequest(
        plan_id=plan.id,
        content_hash=plan.content_hash,
        template=template,
        requirements=document.requirements,
    )
