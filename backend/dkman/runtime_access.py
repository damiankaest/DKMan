"""Runtime authority is separate from app use: admin, or operator + explicit scope."""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from dkman.auth import Principal, current_principal
from dkman.deployments.contracts import LIFECYCLE_ACTIONS
from dkman.models import AppInstallation, HouseholdMembership, Job, PermissionGrant, UserProfile


def runtime_role(actor: Principal) -> None:
    if not actor.roles.intersection({"admin", "operator"}):
        raise HTTPException(403, "Admin or operator role required")


def runtime_principal(actor: Annotated[Principal, Depends(current_principal)]) -> Principal:
    runtime_role(actor)
    return actor


def can_operate(db: Session, item: AppInstallation, actor: Principal) -> bool:
    if "admin" in actor.roles:
        return True
    if "operator" not in actor.roles:
        return False
    member = db.scalar(
        select(HouseholdMembership.id)
        .join(UserProfile, UserProfile.id == HouseholdMembership.user_id)
        .where(
            HouseholdMembership.household_id == item.household_id,
            UserProfile.subject == actor.subject,
        )
    )
    grant = db.scalar(
        select(PermissionGrant.id).where(
            PermissionGrant.installation_id == item.id,
            PermissionGrant.subject == actor.subject,
            PermissionGrant.permission == "app.operate",
        )
    )
    return member is not None and grant is not None


def runtime_installation(db: Session, resource_id: str, actor: Principal) -> AppInstallation:
    runtime_role(actor)
    item = db.get(AppInstallation, resource_id)
    if item is None or not can_operate(db, item, actor):
        raise HTTPException(404, "Authorized installation not found")
    return item


def authorize_job(db: Session, job: Job, actor: Principal) -> None:
    if job.action in LIFECYCLE_ACTIONS:
        runtime_installation(db, job.resource_id, actor)
        if "admin" not in actor.roles and job.requested_by != actor.subject:
            raise HTTPException(404, "Job not found")
    elif "admin" not in actor.roles:
        raise HTTPException(403, "Admin role required")


def active_runtime_job(db: Session, installation_id: str) -> Job | None:
    return db.scalar(
        select(Job)
        .where(
            Job.resource_type == "app_installation",
            Job.resource_id == installation_id,
            Job.action.in_(LIFECYCLE_ACTIONS | {"deployment.install", "deployment.upgrade"}),
            Job.state.not_in({"succeeded", "failed", "cancelled", "expired"}),
        )
        .order_by(Job.created_at)
    )
