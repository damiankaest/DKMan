"""Read tools and typed proposals. All writes remain in the existing approved APIs."""

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from dkman import api
from dkman.auth import Principal, current_principal
from dkman.chat_schemas import (
    ChatEvent,
    ChatInput,
    ChatJob,
    ChatView,
    DraftProposal,
    InstallProposal,
    IntentDecision,
    ProviderView,
    RegistryMatch,
    RuntimeProposal,
)
from dkman.config import Settings
from dkman.database import get_session
from dkman.deployment_api import catalog
from dkman.intent_provider import IntentContext, IntentProvider, IntentResource, ProviderUnavailable
from dkman.job_api import visible_job
from dkman.job_schemas import JobState
from dkman.models import AppDefinition, AppInstallation, DeploymentTarget, Job, JobEvent, utcnow
from dkman.registry import visible_installations
from dkman.runtime_access import can_operate, runtime_installation

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
Db = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(current_principal)]


def definitions(db: Session, actor: Principal) -> list[AppDefinition]:
    query = select(AppDefinition).order_by(AppDefinition.name, AppDefinition.id)
    if "admin" not in actor.roles:
        ids = [item.definition_id for item in visible_installations(db, actor)]
        query = query.where(AppDefinition.id.in_(ids))
    return list(db.scalars(query))


def runtime_resources(db: Session, actor: Principal) -> tuple[IntentResource, ...]:
    if not actor.roles.intersection({"admin", "operator"}):
        return ()
    return tuple(
        IntentResource(item.id, definition.name)
        for item, definition in db.execute(
            select(AppInstallation, AppDefinition)
            .join(AppDefinition, AppDefinition.id == AppInstallation.definition_id)
            .join(DeploymentTarget, DeploymentTarget.id == AppInstallation.id)
            .order_by(AppInstallation.id)
        )
        if can_operate(db, item, actor)
    )


def authorized_jobs(db: Session, actor: Principal) -> list[Job]:
    query = select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(100)
    if "admin" not in actor.roles:
        query = query.where(Job.requested_by == actor.subject)
    result = []
    for item in db.scalars(query):
        try:
            result.append(visible_job(db, item.id, actor))
        except HTTPException as exc:
            if exc.status_code not in {403, 404}:
                raise
        if len(result) == 10:
            break
    return result


def context_for(db: Session, actor: Principal, settings: Settings) -> IntentContext:
    allowed = ["help", "apps.search", "registry.search", "jobs.status"]
    if actor.roles.intersection({"admin", "member", "developer"}):
        allowed.append("app.draft")
    if actor.roles.intersection({"admin", "operator"}):
        allowed.extend(["runtime.start", "runtime.stop", "runtime.restart"])
    if "admin" in actor.roles and settings.deployment_enabled:
        allowed.append("catalog.install")
    return IntentContext(
        tuple(allowed),
        tuple(IntentResource(item.id, item.name) for item in api.apps(db, actor)),
        tuple(IntentResource(item.id, item.name) for item in definitions(db, actor)),
        runtime_resources(db, actor),
        tuple(IntentResource(item.id, item.action) for item in authorized_jobs(db, actor)),
    )


def matches(query: str | None, *values: str) -> bool:
    return not query or any(query.casefold() in value.casefold() for value in values)


def resolve(target: str, resources: tuple[IntentResource, ...]) -> list[IntentResource]:
    exact = [
        item
        for item in resources
        if target.casefold() in {item.id.casefold(), item.name.casefold()}
    ]
    return exact or [item for item in resources if target.casefold() in item.name.casefold()]


def dispatch(
    decision: IntentDecision, db: Session, actor: Principal, settings: Settings, info: ProviderView
) -> ChatView:
    # Rebuild authorization after external inference. No ORM snapshot or model-selected
    # subject can carry authority across the provider call.
    context = context_for(db, actor, settings)
    if decision.kind not in context.allowed_intents:
        raise HTTPException(403, "Chat intent not permitted")
    result = ChatView(
        provider=info,
        intent=decision.kind,
        observed_at=utcnow(),
        summary=(
            "Bitte formuliere einen einzelnen Auftrag, zum Beispiel: „Zeige meine Apps“, "
            "„Suche Dienste“, „Zeige Jobs“ oder „Plane eine Garten-App mit Pflanzen und Fotos“. "
            "Für eine bestimmte Installation kannst du ihre ID angeben. "
            "Freigaben erfolgen im jeweiligen Plan."
        ),
    )
    if decision.kind == "apps.search":
        result.apps = [
            item
            for item in api.apps(db, actor)
            if matches(decision.query, item.name, item.description, item.definition_id, item.id)
        ][:50]
        result.summary = (
            f"{len(result.apps)} berechtigte Installation(en) gefunden. "
            "Der Status stammt aus gespeicherten Messungen; "
            "nach 45 Sekunden gilt er als unbekannt."
        )
    elif decision.kind == "registry.search":
        capabilities = api.capabilities(db, actor)
        result.registry = [
            RegistryMatch(
                id=item.id,
                name=item.name,
                version=item.version,
                description=item.description,
                capabilities=[cap.id for cap in capabilities if cap.definition_id == item.id],
            )
            for item in definitions(db, actor)
            if matches(decision.query, item.id, item.name, item.description)
        ][:50]
        result.summary = (
            f"{len(result.registry)} berechtigte Registry-Einträge gefunden. "
            "Registrierung allein ist keine Installationsfreigabe."
        )
    elif decision.kind == "jobs.status":
        if decision.target:
            try:
                target = str(UUID(decision.target))
            except ValueError as exc:
                raise HTTPException(422, "Valid job ID required") from exc
            jobs = [visible_job(db, target, actor)]
        else:
            jobs = authorized_jobs(db, actor)
        for job in jobs:
            events = list(
                db.scalars(
                    select(JobEvent)
                    .where(JobEvent.job_id == job.id)
                    .order_by(JobEvent.sequence.desc())
                    .limit(20)
                )
            )
            result.jobs.append(
                ChatJob(
                    id=job.id,
                    action=job.action,
                    state=cast(JobState, job.state),
                    updated_at=job.updated_at,
                    events=[
                        ChatEvent(
                            sequence=item.sequence,
                            kind=item.kind,
                            state=cast(JobState, item.state),
                            created_at=item.created_at,
                        )
                        for item in reversed(events)
                    ],
                )
            )
        result.summary = (
            f"{len(result.jobs)} berechtigte Aufträge, "
            "jeweils mit den letzten maximal 20 Ereignissen. "
            "Erneutes Abfragen lädt den aktuellen Stand."
        )
    elif decision.kind == "app.draft":
        assert decision.requirements is not None
        result.proposal = DraftProposal(requirements=decision.requirements)
        result.summary = (
            "Deine App-Idee ist als Vorschlag vorbereitet. Übernimm und prüfe "
            "die Felder in der App-Planung und speichere sie dort."
        )
    elif decision.kind.startswith("runtime.") or decision.kind == "catalog.install":
        assert decision.target is not None
        resources = context.runtime if decision.kind.startswith("runtime.") else context.definitions
        found = resolve(decision.target, resources)
        if not found:
            raise HTTPException(404, "Authorized target not found")
        if len(found) != 1:
            result.summary = (
                "Mehrere passende Ziele. Bitte wiederhole den einzelnen Auftrag "
                "mit einer eindeutigen ID: "
                + "; ".join(f"{item.name} ({item.id})" for item in found[:10])
            )
            return result
        item = found[0]
        if decision.kind.startswith("runtime."):
            runtime_installation(db, item.id, actor)
            result.proposal = RuntimeProposal(
                installation_id=item.id,
                name=item.name,
                action=cast(Literal["start", "stop", "restart"], decision.kind.split(".")[1]),
            )
            result.summary = (
                "Öffne den Containerbetrieb für diese Installation. Dort erstellst und "
                "prüfst du den gebundenen Runtimeplan und gibst ihn anschließend frei."
            )
        else:
            definition = db.get(AppDefinition, item.id)
            curated = next(
                (
                    image
                    for image in catalog(settings).images
                    if image.definition_id == item.id
                    and definition
                    and image.version == definition.version
                    and image.profile == "notes-postgres-v1"
                ),
                None,
            )
            if not definition or not curated:
                raise HTTPException(409, "No matching curated build available")
            result.proposal = InstallProposal(
                definition_id=item.id, name=item.name, version=curated.version
            )
            result.summary = (
                "Ein passender kuratierter Build ist vorhanden. Wähle in der "
                "Installationsplanung den Haushalt und prüfe danach Ressourcen und Freigabe."
            )
    return result


@router.get("/config", response_model=ProviderView, operation_id="getChatConfig")
def config(request: Request, actor: User) -> ProviderView:
    provider: IntentProvider = request.app.state.intent_provider
    return provider.info


@router.post("", response_model=ChatView, operation_id="dispatchChatIntent")
def chat(body: ChatInput, request: Request, db: Db, actor: User) -> ChatView:
    provider: IntentProvider = request.app.state.intent_provider
    settings: Settings = request.app.state.settings
    context = context_for(db, actor, settings)
    # Release the read transaction before network I/O and refresh permissions afterward.
    db.rollback()
    try:
        raw = provider.interpret(body.message, context)
        if len(raw.encode()) > 16384:
            raise ValueError("Oversized intent")
        decision = IntentDecision.model_validate_json(raw, strict=True)
    except ProviderUnavailable as exc:
        code = str(exc)
        if code not in {
            "chat_provider_not_configured",
            "chat_provider_busy",
            "chat_provider_unavailable",
            "chat_provider_invalid_response",
        }:
            code = "chat_provider_unavailable"
        raise HTTPException(503, code) from None
    except (ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(502, "chat_provider_invalid_intent") from exc
    return dispatch(decision, db, actor, settings, provider.info)
