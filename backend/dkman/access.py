"""Household membership and explicit app-use grants; identity stays in OIDC."""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dkman.auth import Principal, current_principal, require_admin
from dkman.database import get_session
from dkman.models import (
    AppInstallation,
    AuditEvent,
    Household,
    HouseholdMembership,
    PermissionGrant,
    UserProfile,
)

router = APIRouter(prefix="/api/v1", tags=["access"])
Db = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(current_principal)]
Admin = Annotated[Principal, Depends(require_admin)]


class ProfileView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    subject: str
    display_name: str


class HouseholdInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


class HouseholdView(HouseholdInput):
    model_config = ConfigDict(from_attributes=True)
    id: str


class GrantView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    installation_id: str
    subject: str
    permission: str


def audit(db: Session, actor: Principal, request: Request, action: str, resource: str) -> None:
    db.add(
        AuditEvent(
            actor_subject=actor.subject,
            action=action,
            resource_id=resource,
            outcome="succeeded",
            correlation_id=request.state.correlation_id,
        )
    )


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent change; reload and retry") from exc


def household(db: Session, household_id: str) -> Household:
    # Serialize membership/grant changes within the household in PostgreSQL.
    item = db.scalar(select(Household).where(Household.id == household_id).with_for_update())
    if item is None:
        raise HTTPException(404, "Household not found")
    return item


def profile(db: Session, user_id: str) -> UserProfile:
    item = db.get(UserProfile, user_id)
    if item is None:
        raise HTTPException(404, "User not found; user must sign in first")
    return item


@router.put("/me/profile", response_model=ProfileView, operation_id="syncMyProfile")
def sync_profile(db: Db, actor: User, request: Request) -> UserProfile:
    item = db.scalar(select(UserProfile).where(UserProfile.subject == actor.subject))
    if item is None:
        item = UserProfile(
            id=str(uuid4()), subject=actor.subject, display_name=actor.display_name[:255]
        )
        db.add(item)
        audit(db, actor, request, "profile.register", item.id)
    else:
        item.display_name = actor.display_name[:255]
    try:
        commit(db)
    except HTTPException as exc:
        # Concurrent first sign-ins converge on the unique verified OIDC subject.
        existing = db.scalar(select(UserProfile).where(UserProfile.subject == actor.subject))
        if existing is None:
            raise exc
        return existing
    return item


@router.get("/users", response_model=list[ProfileView], operation_id="listUsers")
def users(db: Db, actor: Admin) -> list[UserProfile]:
    return list(db.scalars(select(UserProfile).order_by(UserProfile.display_name, UserProfile.id)))


@router.get("/households", response_model=list[HouseholdView], operation_id="listHouseholds")
def households(db: Db, actor: User) -> list[Household]:
    query = select(Household).order_by(Household.name, Household.id)
    if "admin" not in actor.roles:
        query = query.where(
            Household.id.in_(
                select(HouseholdMembership.household_id)
                .join(UserProfile, UserProfile.id == HouseholdMembership.user_id)
                .where(UserProfile.subject == actor.subject)
            )
        )
    return list(db.scalars(query))


@router.post(
    "/households", response_model=HouseholdView, status_code=201, operation_id="createHousehold"
)
def create_household(body: HouseholdInput, db: Db, actor: Admin, request: Request) -> Household:
    item = Household(id=str(uuid4()), name=body.name)
    db.add(item)
    audit(db, actor, request, "household.create", item.id)
    commit(db)
    return item


@router.get(
    "/households/{household_id}/members",
    response_model=list[ProfileView],
    operation_id="listHouseholdMembers",
)
def members(household_id: str, db: Db, actor: Admin) -> list[UserProfile]:
    household(db, household_id)
    return list(
        db.scalars(
            select(UserProfile)
            .join(HouseholdMembership)
            .where(HouseholdMembership.household_id == household_id)
            .order_by(UserProfile.display_name, UserProfile.id)
        )
    )


@router.put(
    "/households/{household_id}/members/{user_id}",
    status_code=204,
    operation_id="addHouseholdMember",
)
def add_member(household_id: str, user_id: str, db: Db, actor: Admin, request: Request) -> Response:
    household(db, household_id)
    profile(db, user_id)
    existing = db.scalar(
        select(HouseholdMembership).where(
            HouseholdMembership.household_id == household_id, HouseholdMembership.user_id == user_id
        )
    )
    if existing is None:
        item = HouseholdMembership(id=str(uuid4()), household_id=household_id, user_id=user_id)
        db.add(item)
        audit(db, actor, request, "membership.add", item.id)
        commit(db)
    return Response(status_code=204)


@router.delete(
    "/households/{household_id}/members/{user_id}",
    status_code=204,
    operation_id="removeHouseholdMember",
)
def remove_member(
    household_id: str, user_id: str, db: Db, actor: Admin, request: Request
) -> Response:
    household(db, household_id)
    person = profile(db, user_id)
    item = db.scalar(
        select(HouseholdMembership).where(
            HouseholdMembership.household_id == household_id, HouseholdMembership.user_id == user_id
        )
    )
    if item is not None:
        # Rejoining must not resurrect earlier grants.
        db.execute(
            delete(PermissionGrant).where(
                PermissionGrant.subject == person.subject,
                PermissionGrant.installation_id.in_(
                    select(AppInstallation.id).where(AppInstallation.household_id == household_id)
                ),
            )
        )
        audit(db, actor, request, "membership.remove", item.id)
        db.delete(item)
        commit(db)
    return Response(status_code=204)


def installation(db: Session, installation_id: str) -> AppInstallation:
    item = db.get(AppInstallation, installation_id)
    if item is None:
        raise HTTPException(404, "Installation not found")
    household(db, item.household_id)
    return item


@router.get(
    "/installations/{installation_id}/grants",
    response_model=list[GrantView],
    operation_id="listInstallationGrants",
)
def grants(installation_id: str, db: Db, actor: Admin) -> list[PermissionGrant]:
    installation(db, installation_id)
    return list(
        db.scalars(
            select(PermissionGrant)
            .where(PermissionGrant.installation_id == installation_id)
            .order_by(PermissionGrant.subject)
        )
    )


@router.put(
    "/installations/{installation_id}/grants/{user_id}", status_code=204, operation_id="grantAppUse"
)
def grant(installation_id: str, user_id: str, db: Db, actor: Admin, request: Request) -> Response:
    return change_grant(installation_id, user_id, db, actor, request, "app.use", False)


def change_grant(
    installation_id: str,
    user_id: str,
    db: Session,
    actor: Principal,
    request: Request,
    permission: str,
    remove: bool,
) -> Response:
    app = installation(db, installation_id)
    person = profile(db, user_id)
    member = db.scalar(
        select(HouseholdMembership).where(
            HouseholdMembership.household_id == app.household_id,
            HouseholdMembership.user_id == user_id,
        )
    )
    if member is None:
        raise HTTPException(409, "User must belong to the installation household")
    existing = db.scalar(
        select(PermissionGrant).where(
            PermissionGrant.installation_id == installation_id,
            PermissionGrant.subject == person.subject,
            PermissionGrant.permission == permission,
        )
    )
    if remove and existing is not None:
        audit(db, actor, request, "grant.remove", existing.id)
        db.delete(existing)
        commit(db)
    elif not remove and existing is None:
        item = PermissionGrant(
            id=str(uuid4()),
            installation_id=installation_id,
            subject=person.subject,
            permission=permission,
        )
        db.add(item)
        audit(db, actor, request, "grant.add", item.id)
        commit(db)
    return Response(status_code=204)


@router.delete(
    "/installations/{installation_id}/grants/{user_id}",
    status_code=204,
    operation_id="revokeAppUse",
)
def revoke(installation_id: str, user_id: str, db: Db, actor: Admin, request: Request) -> Response:
    installation(db, installation_id)
    person = profile(db, user_id)
    item = db.scalar(
        select(PermissionGrant).where(
            PermissionGrant.installation_id == installation_id,
            PermissionGrant.subject == person.subject,
            PermissionGrant.permission == "app.use",
        )
    )
    if item is not None:
        audit(db, actor, request, "grant.remove", item.id)
        db.delete(item)
        commit(db)
    return Response(status_code=204)


@router.put(
    "/installations/{installation_id}/runtime-grants/{user_id}",
    status_code=204,
    operation_id="grantAppOperate",
)
def grant_runtime(
    installation_id: str, user_id: str, db: Db, actor: Admin, request: Request
) -> Response:
    return change_grant(installation_id, user_id, db, actor, request, "app.operate", False)


@router.delete(
    "/installations/{installation_id}/runtime-grants/{user_id}",
    status_code=204,
    operation_id="revokeAppOperate",
)
def revoke_runtime(
    installation_id: str, user_id: str, db: Db, actor: Admin, request: Request
) -> Response:
    return change_grant(installation_id, user_id, db, actor, request, "app.operate", True)
