"""Approved replacement of an existing Forge SPA by a newly previewed revision."""

from datetime import timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dkman.access import household
from dkman.auth import Principal, require_admin
from dkman.config import Settings
from dkman.database import get_session
from dkman.deployment_api import (
    Key,
    accept_rejection,
    completion_result,
    credential,
    forge_manifest,
    record_runtime,
    uncertain,
    validate_runtime_policy,
    verified_forge_source,
)
from dkman.deployments.contracts import (
    DeploymentCommand,
    DeploymentPlan,
    ForgeReleaseProof,
    InstallationContext,
    OperationView,
    UpgradePlan,
)
from dkman.forge.attestation import SignedBuildEvidence, SignedPreviewEvidence
from dkman.forge_api import current_bundle, verify_preview, visible_workspace
from dkman.job_schemas import JobView
from dkman.jobs import begin_execution, claim, digest, event, locked_job, owned_lease, utc
from dkman.models import (
    AppDefinition,
    AppInstallation,
    AppPlan,
    ApprovalRequest,
    ForgeBuildArtifact,
    ForgePreview,
    ForgeWorkspace,
    Job,
    ServiceManifest,
    utcnow,
)
from dkman.planning import plan_for, request_for
from dkman.runtime_access import active_runtime_job
from dkman.runtime_api import installed_plan

router = APIRouter(prefix="/api/v1", tags=["deployments"])
Db = Annotated[Session, Depends(get_session)]
Admin = Annotated[Principal, Depends(require_admin)]


class ForgeUpgradeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installation_id: UUID


def prior_revision(db: Session, plan: DeploymentPlan) -> int:
    if plan.forge is None:
        raise ValueError("Existing installation is not a Forge release")
    workspace = db.get(ForgeWorkspace, str(plan.forge.build.evidence.workspace_id))
    record = db.get(AppPlan, workspace.plan_id) if workspace else None
    if record is None or workspace is None or workspace.bundle_hash != plan.source_hash:
        raise ValueError("Previous app revision is unavailable")
    return record.revision


@router.post(
    "/forge/previews/{preview_id}/upgrades",
    response_model=JobView,
    status_code=202,
    operation_id="planForgeUpgrade",
)
def plan_forge_upgrade(
    preview_id: UUID,
    body: ForgeUpgradeInput,
    request: Request,
    response: Response,
    db: Db,
    actor: Admin,
    idempotency_key: Key,
) -> Job:
    fingerprint = digest(
        {
            "action": "deployment.upgrade",
            "preview_id": str(preview_id),
            **body.model_dump(mode="json"),
        }
    )

    def replay() -> Job | None:
        job = db.scalar(
            select(Job).where(
                Job.requested_by == actor.subject, Job.idempotency_key == idempotency_key
            )
        )
        if job is not None and job.request_hash != fingerprint:
            raise HTTPException(409, "Idempotency key binds a different request")
        return job

    if (existing := replay()) is not None:
        return existing
    observation = db.get(ForgePreview, str(preview_id))
    artifact = db.get(ForgeBuildArtifact, observation.artifact_id) if observation else None
    if observation is None or artifact is None:
        raise HTTPException(404, "Preview not found")
    workspace = visible_workspace(db, artifact.workspace_id, actor)
    bundle = current_bundle(db, workspace, actor)  # Request lock precedes household/installation.
    plan_record = plan_for(db, workspace.plan_id, actor)
    parent = request_for(db, plan_record.request_id, actor, lock=True)
    item = db.get(AppInstallation, str(body.installation_id))
    if item is None:
        raise HTTPException(404, "Installation not found")
    household(db, item.household_id)
    item = db.scalar(
        select(AppInstallation)
        .where(AppInstallation.id == str(body.installation_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise HTTPException(404, "Installation not found")
    if (existing := replay()) is not None:
        return existing
    if active_runtime_job(db, item.id):
        raise HTTPException(409, "Installation has an active or unresolved runtime job")
    definition_id = "forge-" + UUID(parent.id).hex
    if (
        bundle.request.template != "react-spa"
        or item.definition_id != definition_id
        or (parent.household_id is not None and parent.household_id != item.household_id)
    ):
        raise HTTPException(409, "Preview does not belong to this installation")
    verified = verify_preview(observation, artifact, workspace, request)
    if verified.evidence.expires_at <= utcnow():
        raise HTTPException(409, "Preview evidence has expired")
    previous = installed_plan(db, item)
    definition = db.get(AppDefinition, definition_id)
    try:
        validate_runtime_policy(request.app.state.settings, previous)
        old_revision = prior_revision(db, previous)
    except ValueError:
        raise HTTPException(409, "Current runtime provenance is unavailable") from None
    if (
        definition is None
        or definition.source != f"forge:{parent.id}"
        or definition.version != previous.version
        or plan_record.revision <= old_revision
    ):
        raise HTTPException(409, "Update requires a newer approved app-plan revision")
    signed_build = SignedBuildEvidence.model_validate(artifact.attestation)
    signed_preview = SignedPreviewEvidence.model_validate(observation.attestation)
    version = f"0.{plan_record.revision}.{int(UUID(artifact.id).hex[:12], 16)}"
    manifest = forge_manifest(
        definition_id,
        version,
        bundle.request.requirements.title,
        signed_build.evidence.config_digest,
    )
    content = manifest.model_dump(by_alias=True)
    record = db.scalar(
        select(ServiceManifest).where(
            ServiceManifest.definition_id == definition_id, ServiceManifest.version == version
        )
    )
    if record is None:
        record = ServiceManifest(
            definition_id=definition_id,
            schema_version=manifest.schema_version,
            version=version,
            content=content,
        )
        db.add(record)
        db.flush()
    elif record.content != content:
        raise HTTPException(409, "Registered app revision differs from the build")
    replacement = DeploymentPlan(
        definition_id=definition_id,
        version=version,
        image=signed_build.evidence.config_digest,
        internal_port=8080,
        user="101",
        memory_mb=256,
        cpus=0.5,
        profile="forge-spa-v1",
        source_hash=workspace.bundle_hash,
        installation_id=body.installation_id,
        context=InstallationContext(
            household_id=UUID(item.household_id),
            subject=actor.subject,
            manifest_id=UUID(record.id),
            manifest_hash=digest(content),
        ),
        forge=ForgeReleaseProof(build=signed_build, preview=signed_preview),
    )
    try:
        validate_runtime_policy(request.app.state.settings, replacement, fresh=True)
        plan = UpgradePlan(
            resource_id=body.installation_id,
            subject=actor.subject,
            previous=previous,
            replacement=replacement,
        )
    except ValueError:
        raise HTTPException(409, "Update evidence is invalid or has expired") from None
    job = Job(
        id=str(uuid4()),
        requested_by=actor.subject,
        idempotency_key=idempotency_key,
        request_hash=fingerprint,
        action="deployment.upgrade",
        resource_type="app_installation",
        resource_id=item.id,
        risk="sensitive",
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
                expires_at=min(utc(verified.evidence.expires_at), utcnow() + timedelta(minutes=15)),
            )
        )
        event(db, job, "submitted", actor.subject)
        db.commit()
    except IntegrityError:
        db.rollback()
        if (existing := replay()) is None:
            raise
        return existing
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return job


def verified_upgrade(db: Session, job: Job, settings: Settings, actor: Principal) -> UpgradePlan:
    plan = UpgradePlan.model_validate(job.plan)
    if (
        job.action != "deployment.upgrade"
        or job.resource_type != "app_installation"
        or job.resource_id != str(plan.resource_id)
        or job.requested_by != plan.subject
        or actor.subject != plan.subject
        or job.plan_hash != plan.plan_hash
        or not job.requires_approval
        or job.risk != "sensitive"
        or plan.replacement.context is None
    ):
        raise ValueError("Update binding changed")
    # Recheck the approved source under Request -> Household -> Installation locks.
    revision = verified_forge_source(
        db, actor, plan.replacement, str(plan.replacement.context.household_id)
    )
    household(db, str(plan.replacement.context.household_id))
    item = db.scalar(
        select(AppInstallation)
        .where(AppInstallation.id == job.resource_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        item is None
        or installed_plan(db, item) != plan.previous
        or revision <= prior_revision(db, plan.previous)
    ):
        raise ValueError("Current installation or app revision changed")
    definition = db.get(AppDefinition, item.definition_id)
    manifest = db.get(ServiceManifest, str(plan.replacement.context.manifest_id))
    if (
        definition is None
        or definition.version != plan.previous.version
        or manifest is None
        or manifest.definition_id != item.definition_id
        or manifest.version != plan.replacement.version
        or digest(manifest.content) != plan.replacement.context.manifest_hash
    ):
        raise ValueError("Registered app revision changed")
    validate_runtime_policy(settings, plan.previous)
    validate_runtime_policy(settings, plan.replacement, fresh=True)
    return plan


def accept_upgrade(db: Session, job: Job, outcome: OperationView, actor: Principal) -> Job:
    plan = UpgradePlan.model_validate(job.plan)
    if accept_rejection(db, job, outcome, actor):
        return job
    try:
        result = completion_result(job, outcome)
    except ValueError:
        return uncertain(db, job, actor, "execution_evidence_incomplete")
    if (
        plan.plan_hash != job.plan_hash
        or job.action != "deployment.upgrade"
        or job.resource_id != str(plan.resource_id)
        or job.requested_by != plan.subject
        or str(outcome.operation_id) != job.id
        or str(outcome.installation_id) != job.resource_id
        or outcome.action != "deploy"
        or outcome.plan_hash != job.plan_hash
        or outcome.state != "succeeded"
        or outcome.runtime is None
        or outcome.runtime.installation_id != plan.resource_id
        or outcome.runtime.state != "running"
        or not outcome.runtime.container_id
        or outcome.finished_at is None
        or job.execution_started_at is None
        or utc(outcome.finished_at) < utc(job.execution_started_at)
        or utc(outcome.runtime.observed_at) < utc(job.execution_started_at)
    ):
        return uncertain(db, job, actor, outcome.failure_code)
    item = db.scalar(
        select(AppInstallation)
        .where(AppInstallation.id == job.resource_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    context = plan.replacement.context
    if item is None or context is None or installed_plan(db, item) != plan.previous:
        return uncertain(db, job, actor)
    definition = db.get(AppDefinition, item.definition_id)
    manifest = db.get(ServiceManifest, str(context.manifest_id))
    if (
        definition is None
        or definition.version != plan.previous.version
        or manifest is None
        or manifest.definition_id != item.definition_id
        or manifest.version != plan.replacement.version
        or digest(manifest.content) != context.manifest_hash
    ):
        return uncertain(db, job, actor)
    item.manifest_id = str(context.manifest_id)
    definition.version = plan.replacement.version
    definition.name = str(manifest.content["name"])
    record_runtime(db, item.id, outcome.runtime)
    job.state = "succeeded"
    job.failure_code = None
    job.result = {"installation_id": item.id, "operation_id": job.id, **result}
    job.finished_at = utcnow()
    job.lease_token = None
    job.lease_expires_at = None
    event(db, job, "succeeded", actor.subject)
    db.commit()
    return job


def run_upgrade(job_id: str, db: Session, actor: Principal, request: Request) -> Job:
    token = claim(db, job_id, actor, lease_seconds=600)
    job = owned_lease(db, job_id, token, "claimed")
    try:
        plan = verified_upgrade(db, job, request.app.state.settings, actor)
        credential(request.app.state.settings, actor, job, "operation.read")
    except (ValueError, HTTPException):
        job.state = "failed"
        job.failure_code = "upgrade_preflight_failed"
        job.finished_at = utcnow()
        job.lease_token = None
        job.lease_expires_at = None
        event(db, job, "preflight_failed", actor.subject)
        db.commit()
        return job
    job = begin_execution(db, job_id, token, actor)
    try:
        delegation = credential(
            request.app.state.settings, actor, job, "deploy", mutate=True, db=db
        )
        db.commit()
        outcome = request.app.state.deployment_client.execute(
            UUID(job.id),
            DeploymentCommand(action="deploy", plan=plan.replacement, upgrade=plan),
            delegation,
        )
        job = owned_lease(db, job_id, token, "running")
        return accept_upgrade(db, job, outcome, actor)
    except Exception:
        db.rollback()
        job = locked_job(db, job_id)
        if job.state == "running" and job.lease_token == token:
            return uncertain(db, job, actor)
        return job
