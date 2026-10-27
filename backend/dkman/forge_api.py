"""Approved-plan source snapshots. No Docker, shell or host workspace access."""

import hashlib
import io
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dkman.auth import Principal, current_principal
from dkman.database import get_session
from dkman.forge.approved_plan import generation_request_for
from dkman.forge.templates import TemplateProvider
from dkman.forge.workspace import SourceBundle
from dkman.jobs import digest
from dkman.models import AuditEvent, ForgeWorkspace, new_id
from dkman.planning import check_household, plan_for, request_for
from dkman.planning_schemas import PlanningHash

router = APIRouter(prefix="/api/v1", tags=["forge"])
Db = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(current_principal)]
Key = Annotated[str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]


class WorkspaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: Literal["python-api", "react-spa", "fullstack-fastapi-react"]
    content_hash: PlanningHash


class WorkspaceView(BaseModel):
    id: str
    plan_id: str
    plan_hash: PlanningHash
    template: Literal["python-api", "react-spa", "fullstack-fastapi-react"]
    bundle_hash: PlanningHash
    created_at: datetime
    files: list[str] = Field(max_length=100)


def bundle_hash(bundle: SourceBundle) -> str:
    payload = json.dumps(
        bundle.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def checked_bundle(item: ForgeWorkspace) -> SourceBundle:
    try:
        bundle = SourceBundle.model_validate(item.bundle)
        if (
            bundle.request.plan_id != item.plan_id
            or bundle.request.content_hash != item.plan_hash
            or bundle.request.template != item.template
            or bundle_hash(bundle) != item.bundle_hash
        ):
            raise ValueError("workspace binding changed")
        return bundle
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(409, "Workspace integrity verification failed") from None


def visible_workspace(db: Session, item_id: str, actor: Principal) -> ForgeWorkspace:
    query = select(ForgeWorkspace).where(ForgeWorkspace.id == item_id)
    if "admin" not in actor.roles:
        query = query.where(ForgeWorkspace.owner_subject == actor.subject)
    item = db.scalar(query)
    if item is None:
        raise HTTPException(404, "Workspace not found")
    if not actor.roles.intersection({"developer", "admin"}):
        raise HTTPException(404, "Workspace not found")
    plan_for(db, item.plan_id, actor)
    return item


def view(item: ForgeWorkspace) -> WorkspaceView:
    return WorkspaceView(
        id=item.id,
        plan_id=item.plan_id,
        plan_hash=item.plan_hash,
        template=item.template,  # type: ignore[arg-type]
        bundle_hash=item.bundle_hash,
        created_at=item.created_at,
        files=sorted(checked_bundle(item).files),
    )


@router.post(
    "/app-plans/{plan_id}/workspaces",
    response_model=WorkspaceView,
    status_code=201,
    operation_id="createForgeWorkspace",
)
def create_workspace(
    plan_id: str, body: WorkspaceInput, db: Db, actor: User, request: Request, idempotency_key: Key
) -> WorkspaceView:
    if not actor.roles.intersection({"developer", "admin"}):
        raise HTTPException(403, "Developer or admin role required")
    fingerprint = digest({"plan_id": plan_id, **body.model_dump(mode="json")})

    def replay() -> ForgeWorkspace | None:
        previous = db.scalar(
            select(ForgeWorkspace).where(
                ForgeWorkspace.owner_subject == actor.subject,
                ForgeWorkspace.idempotency_key == idempotency_key,
            )
        )
        if previous is not None:
            visible_workspace(db, previous.id, actor)
            if previous.request_hash != fingerprint:
                raise HTTPException(409, "Idempotency key already binds a different request")
        return previous

    if (existing := replay()) is not None:
        return view(existing)
    plan = plan_for(db, plan_id, actor)
    # Plan revisions and membership changes follow Request -> Household locks.
    item = request_for(db, plan.request_id, actor, lock=True)
    check_household(db, item.household_id, actor)
    db.refresh(plan)
    generation = generation_request_for(db, actor, plan_id, body.template)
    if generation.content_hash != body.content_hash:
        raise HTTPException(409, "Plan content changed; reload before generation")
    bundle = TemplateProvider().generate(generation)
    item_id = new_id()
    workspace = ForgeWorkspace(
        id=item_id,
        owner_subject=actor.subject,
        plan_id=plan_id,
        plan_hash=generation.content_hash,
        template=body.template,
        bundle_hash=bundle_hash(bundle),
        bundle=bundle.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        request_hash=fingerprint,
    )
    db.add(workspace)
    db.add(
        AuditEvent(
            actor_subject=actor.subject,
            action="forge.workspace.created",
            resource_id=item_id,
            outcome="succeeded",
            correlation_id=request.state.correlation_id,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = replay()
        if existing is None:
            raise
        return view(existing)
    return view(workspace)


@router.get(
    "/app-plans/{plan_id}/workspaces",
    response_model=list[WorkspaceView],
    operation_id="listForgeWorkspaces",
)
def list_workspaces(plan_id: str, db: Db, actor: User) -> list[WorkspaceView]:
    if not actor.roles.intersection({"developer", "admin"}):
        raise HTTPException(403, "Developer or admin role required")
    plan_for(db, plan_id, actor)
    query = select(ForgeWorkspace).where(ForgeWorkspace.plan_id == plan_id)
    if "admin" not in actor.roles:
        query = query.where(ForgeWorkspace.owner_subject == actor.subject)
    return [
        view(item)
        for item in db.scalars(query.order_by(ForgeWorkspace.created_at.desc()).limit(50))
    ]


@router.get(
    "/forge/workspaces/{workspace_id}",
    response_model=WorkspaceView,
    operation_id="getForgeWorkspace",
)
def get_workspace(workspace_id: str, db: Db, actor: User) -> WorkspaceView:
    return view(visible_workspace(db, workspace_id, actor))


@router.get("/forge/workspaces/{workspace_id}/archive", operation_id="downloadForgeWorkspace")
def download_workspace(workspace_id: str, db: Db, actor: User) -> Response:
    item = visible_workspace(db, workspace_id, actor)
    bundle = checked_bundle(item)
    # Fixed permissions and timestamps; validation has already rejected unsafe paths.
    target = io.BytesIO()
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(bundle.files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content.encode("utf-8"))
    try:
        safe_id = str(UUID(item.id))
    except ValueError:
        raise HTTPException(409, "Invalid workspace identifier") from None
    return Response(
        content=target.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="dkman-workspace-{safe_id}.zip"'},
    )
