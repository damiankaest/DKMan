"""Approved-plan source snapshots. No Docker, shell or host workspace access."""

import hashlib
import io
import json
from datetime import datetime, timedelta
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
from dkman.forge.attestation import (
    BuildEvidence,
    PreviewEvidence,
    SignedBuildEvidence,
    SignedPreviewEvidence,
    key_id,
    read_public_key,
    verify_preview_signature,
    verify_recipe,
    verify_signature,
)
from dkman.forge.templates import TemplateProvider
from dkman.forge.workspace import SourceBundle
from dkman.jobs import digest
from dkman.models import (
    AuditEvent,
    ForgeBuildArtifact,
    ForgePreview,
    ForgeWorkspace,
    new_id,
    utcnow,
)
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


class BuildInput(BaseModel):
    """Authorized source data; it grants no deployment or host access."""

    workspace_id: str
    bundle_hash: PlanningHash
    bundle: SourceBundle


class BuildArtifactView(BaseModel):
    id: str
    workspace_id: str
    created_at: datetime
    submitted_by: str
    key_id: PlanningHash
    evidence_hash: PlanningHash
    evidence: BuildEvidence


class PreviewView(BaseModel):
    id: str
    artifact_id: str
    created_at: datetime
    submitted_by: str
    evidence_hash: PlanningHash
    key_id: PlanningHash
    evidence: PreviewEvidence


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


def current_bundle(db: Session, workspace: ForgeWorkspace, actor: Principal) -> SourceBundle:
    plan = plan_for(db, workspace.plan_id, actor)
    parent = request_for(db, plan.request_id, actor, lock=True)
    check_household(db, parent.household_id, actor)
    db.refresh(plan)
    bundle = checked_bundle(workspace)
    generation = generation_request_for(db, actor, plan.id, bundle.request.template)
    if generation != bundle.request:
        raise HTTPException(409, "Workspace no longer matches the approved plan")
    return bundle


@router.get(
    "/forge/workspaces/{workspace_id}/build-input",
    response_model=BuildInput,
    operation_id="getForgeBuildInput",
)
def get_build_input(workspace_id: str, db: Db, actor: User) -> BuildInput:
    """Recheck current plan, membership and approval before an isolated build."""
    workspace = visible_workspace(db, workspace_id, actor)
    bundle = current_bundle(db, workspace, actor)
    return BuildInput(workspace_id=workspace.id, bundle_hash=workspace.bundle_hash, bundle=bundle)


def verify_artifact(
    item: ForgeBuildArtifact, workspace: ForgeWorkspace, request: Request
) -> BuildArtifactView:
    public_path = request.app.state.settings.forge_builder_public_key_file
    if public_path is None:
        raise HTTPException(503, "Forge builder verification key is not configured")
    try:
        public = read_public_key(public_path)
    except (OSError, ValueError, TypeError):
        raise HTTPException(503, "Forge builder verification key is unavailable") from None
    try:
        signed = SignedBuildEvidence.model_validate(item.attestation)
        bundle = checked_bundle(workspace)
        verify_signature(signed, public)
        verify_recipe(signed.evidence, bundle)
        if (
            item.id != str(signed.evidence.build_id)
            or item.workspace_id != workspace.id
            or signed.evidence.workspace_id != UUID(workspace.id)
            or signed.evidence.source_hash != workspace.bundle_hash
            or digest(item.attestation) != item.evidence_hash
            or TemplateProvider().generate(bundle.request) != bundle
        ):
            raise ValueError("artifact_binding_changed")
    except (ValidationError, ValueError, TypeError, KeyError):
        raise HTTPException(409, "Build evidence verification failed") from None
    return BuildArtifactView(
        id=item.id,
        workspace_id=item.workspace_id,
        created_at=item.created_at,
        submitted_by=item.submitted_by,
        key_id=signed.key_id,
        evidence_hash=item.evidence_hash,
        evidence=signed.evidence,
    )


@router.post(
    "/forge/workspaces/{workspace_id}/build-artifacts",
    response_model=BuildArtifactView,
    status_code=201,
    operation_id="registerForgeBuildArtifact",
)
def register_build_artifact(
    workspace_id: str, body: SignedBuildEvidence, db: Db, actor: User, request: Request
) -> BuildArtifactView:
    workspace = visible_workspace(db, workspace_id, actor)
    bundle = current_bundle(db, workspace, actor)
    payload = body.model_dump(mode="json")
    identifier = str(body.evidence.build_id)
    fingerprint = digest(payload)
    existing = db.get(ForgeBuildArtifact, identifier)
    if existing is not None:
        if existing.workspace_id != workspace.id or existing.evidence_hash != fingerprint:
            raise HTTPException(409, "Build identifier already binds different evidence")
        return verify_artifact(existing, workspace, request)
    candidate = ForgeBuildArtifact(
        id=identifier,
        workspace_id=workspace.id,
        submitted_by=actor.subject,
        evidence_hash=fingerprint,
        attestation=payload,
    )
    # Validate before persistence; no caller may supply an unsigned build result.
    public_path = request.app.state.settings.forge_builder_public_key_file
    if public_path is None:
        raise HTTPException(503, "Forge builder verification key is not configured")
    try:
        public = read_public_key(public_path)
    except (OSError, ValueError, TypeError):
        raise HTTPException(503, "Forge builder verification key is unavailable") from None
    try:
        verify_signature(body, public)
        verify_recipe(body.evidence, bundle)
        if (
            body.evidence.workspace_id != UUID(workspace.id)
            or body.evidence.source_hash != workspace.bundle_hash
            or TemplateProvider().generate(bundle.request) != bundle
        ):
            raise ValueError("artifact_binding_mismatch")
    except (ValueError, TypeError, KeyError):
        raise HTTPException(409, "Build evidence verification failed") from None
    db.add(candidate)
    db.add(
        AuditEvent(
            actor_subject=actor.subject,
            action="forge.build_artifact.registered",
            resource_id=identifier,
            outcome="succeeded",
            correlation_id=request.state.correlation_id,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(ForgeBuildArtifact, identifier)
        if existing is None or existing.workspace_id != workspace.id:
            raise HTTPException(409, "Build identifier already binds different evidence") from None
        if existing.evidence_hash != fingerprint:
            raise HTTPException(409, "Build identifier already binds different evidence") from None
        return verify_artifact(existing, workspace, request)
    return verify_artifact(candidate, workspace, request)


@router.get(
    "/forge/workspaces/{workspace_id}/build-artifacts",
    response_model=list[BuildArtifactView],
    operation_id="listForgeBuildArtifacts",
)
def list_build_artifacts(
    workspace_id: str, db: Db, actor: User, request: Request
) -> list[BuildArtifactView]:
    workspace = visible_workspace(db, workspace_id, actor)
    items = db.scalars(
        select(ForgeBuildArtifact)
        .where(ForgeBuildArtifact.workspace_id == workspace.id)
        .order_by(ForgeBuildArtifact.created_at.desc(), ForgeBuildArtifact.id.desc())
        .limit(50)
    )
    return [verify_artifact(item, workspace, request) for item in items]


@router.get(
    "/forge/build-artifacts/{artifact_id}",
    response_model=BuildArtifactView,
    operation_id="getForgeBuildArtifact",
)
def get_build_artifact(
    artifact_id: str, db: Db, actor: User, request: Request
) -> BuildArtifactView:
    item = db.get(ForgeBuildArtifact, artifact_id)
    if item is None:
        raise HTTPException(404, "Build artifact not found")
    workspace = visible_workspace(db, item.workspace_id, actor)
    return verify_artifact(item, workspace, request)


def preview_public_key(request: Request) -> object:
    settings = request.app.state.settings
    if (
        settings.forge_builder_public_key_file is None
        or settings.forge_preview_public_key_file is None
    ):
        raise HTTPException(503, "Forge verification keys are not configured")
    try:
        builder = read_public_key(settings.forge_builder_public_key_file)
        preview = read_public_key(settings.forge_preview_public_key_file)
        if key_id(builder) == key_id(preview):
            raise ValueError("Builder and preview keys must differ")
        return preview
    except (OSError, ValueError, TypeError):
        raise HTTPException(503, "Forge verification keys are unavailable") from None


def verify_preview(
    item: ForgePreview, artifact: ForgeBuildArtifact, workspace: ForgeWorkspace, request: Request
) -> PreviewView:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    public = preview_public_key(request)
    assert isinstance(public, Ed25519PublicKey)
    build = verify_artifact(artifact, workspace, request)
    if build.evidence.template != "react-spa":
        raise HTTPException(409, "Preview is not supported for this template")
    try:
        signed = SignedPreviewEvidence.model_validate(item.attestation)
        verify_preview_signature(signed, public)
        evidence = signed.evidence
        if (
            item.id != str(evidence.preview_id)
            or item.artifact_id != artifact.id
            or digest(item.attestation) != item.evidence_hash
            or str(evidence.artifact_id) != artifact.id
            or str(evidence.workspace_id) != workspace.id
            or evidence.artifact_evidence_hash != build.evidence_hash
            or evidence.source_hash != build.evidence.source_hash
            or evidence.plan_hash != build.evidence.plan_hash
            or evidence.manifest_digest != build.evidence.manifest_digest
            or evidence.config_digest != build.evidence.config_digest
        ):
            raise ValueError("preview_binding_changed")
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(409, "Preview evidence verification failed") from None
    return PreviewView(
        id=item.id,
        artifact_id=item.artifact_id,
        created_at=item.created_at,
        submitted_by=item.submitted_by,
        evidence_hash=item.evidence_hash,
        key_id=signed.key_id,
        evidence=signed.evidence,
    )


@router.post(
    "/forge/build-artifacts/{artifact_id}/previews",
    response_model=PreviewView,
    status_code=201,
    operation_id="registerForgePreview",
)
def register_preview(
    artifact_id: str, body: SignedPreviewEvidence, db: Db, actor: User, request: Request
) -> PreviewView:
    artifact = db.get(ForgeBuildArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "Build artifact not found")
    workspace = visible_workspace(db, artifact.workspace_id, actor)
    current_bundle(db, workspace, actor)
    verify_artifact(artifact, workspace, request)
    identifier = str(body.evidence.preview_id)
    payload = body.model_dump(mode="json")
    fingerprint = digest(payload)
    existing = db.get(ForgePreview, identifier)
    if existing is not None:
        if existing.artifact_id != artifact.id or existing.evidence_hash != fingerprint:
            raise HTTPException(409, "Preview identifier already binds different evidence")
        return verify_preview(existing, artifact, workspace, request)
    now = utcnow()
    if body.evidence.expires_at <= now or body.evidence.observed_at > now + timedelta(seconds=30):
        raise HTTPException(409, "Preview evidence is expired or not yet valid")
    candidate = ForgePreview(
        id=identifier,
        artifact_id=artifact.id,
        submitted_by=actor.subject,
        evidence_hash=fingerprint,
        attestation=payload,
        created_at=now,
    )
    verify_preview(candidate, artifact, workspace, request)
    db.add(candidate)
    db.add(
        AuditEvent(
            actor_subject=actor.subject,
            action="forge.preview.registered",
            resource_id=identifier,
            outcome="succeeded",
            correlation_id=request.state.correlation_id,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(ForgePreview, identifier)
        if existing is None or existing.artifact_id != artifact.id:
            raise HTTPException(
                409, "Preview identifier already binds different evidence"
            ) from None
        if existing.evidence_hash != fingerprint:
            raise HTTPException(
                409, "Preview identifier already binds different evidence"
            ) from None
        return verify_preview(existing, artifact, workspace, request)
    return verify_preview(candidate, artifact, workspace, request)


@router.get(
    "/forge/build-artifacts/{artifact_id}/previews",
    response_model=list[PreviewView],
    operation_id="listForgePreviews",
)
def list_previews(artifact_id: str, db: Db, actor: User, request: Request) -> list[PreviewView]:
    artifact = db.get(ForgeBuildArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "Build artifact not found")
    workspace = visible_workspace(db, artifact.workspace_id, actor)
    items = db.scalars(
        select(ForgePreview)
        .where(ForgePreview.artifact_id == artifact.id)
        .order_by(ForgePreview.created_at.desc(), ForgePreview.id.desc())
        .limit(50)
    )
    return [verify_preview(item, artifact, workspace, request) for item in items]


@router.get(
    "/forge/workspaces/{workspace_id}/archive",
    operation_id="downloadForgeWorkspace",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
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
