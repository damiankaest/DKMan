from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dkman.auth import Principal, current_principal, require_admin
from dkman.database import get_session
from dkman.jobs import utc
from dkman.manifest import Manifest
from dkman.models import AppDefinition, Capability, DeploymentTarget, ServiceInstance, utcnow
from dkman.registry import register_manifest, visible_installations
from dkman.schemas import AppView, CapabilityView, DefinitionView, MeView, ServiceView

router = APIRouter(prefix="/api/v1")
Db = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(current_principal)]
Admin = Annotated[Principal, Depends(require_admin)]


@router.get("/me", response_model=MeView, operation_id="getMe")
def me(principal: User) -> MeView:
    return MeView(
        subject=principal.subject,
        display_name=principal.display_name,
        roles=sorted(principal.roles),
    )


@router.get("/apps", response_model=list[AppView], operation_id="listApps")
def apps(db: Db, principal: User) -> list[AppView]:
    result = []
    for installation in visible_installations(db, principal):
        definition = db.get(AppDefinition, installation.definition_id)
        assert definition is not None
        # Runtime data and proxy routes are populated only by the deployment adapter.
        service = db.scalar(
            select(ServiceInstance)
            .where(ServiceInstance.installation_id == installation.id)
            .order_by(ServiceInstance.created_at.desc())
            .limit(1)
        )
        result.append(
            AppView(
                id=installation.id,
                definition_id=definition.id,
                name=definition.name,
                version=definition.version,
                description=definition.description,
                status=service.status
                if service
                and service.checked_at
                and utc(service.checked_at) > utcnow() - timedelta(seconds=45)
                else "unknown",  # type: ignore[arg-type]
                checked_at=service.checked_at if service else None,
                route=f"/run/{installation.id}/"
                if service
                and service.status == "healthy"
                and service.checked_at
                and utc(service.checked_at) > utcnow() - timedelta(seconds=45)
                and db.get(DeploymentTarget, installation.id) is not None
                else None,
            )
        )
    return result


@router.get("/apps/{app_id}", response_model=AppView, operation_id="getApp")
def app_detail(app_id: str, db: Db, principal: User) -> AppView:
    for item in apps(db, principal):
        if item.id == app_id:
            return item
    raise HTTPException(404, "App not found")


@router.get("/apps/{app_id}/access", operation_id="authorizeAppAccess")
def authorize_app_access(app_id: str, db: Db, principal: User) -> dict[str, str]:
    app_detail(app_id, db, principal)
    if not principal.roles.intersection({"member", "admin"}):
        raise HTTPException(403, "Member role required")
    return {"installation_id": app_id, "subject": principal.subject}


def as_service(service: ServiceInstance) -> ServiceView:
    return ServiceView(
        id=service.id,
        installation_id=service.installation_id,
        provider=service.provider,
        status=service.status,  # type: ignore[arg-type]
        checked_at=service.checked_at,
        reason=service.status_reason,
    )


@router.get("/services", response_model=list[ServiceView], operation_id="listServices")
def services(db: Db, principal: User) -> list[ServiceView]:
    ids = [item.id for item in visible_installations(db, principal)]
    return [
        as_service(service)
        for service in db.scalars(
            select(ServiceInstance).where(ServiceInstance.installation_id.in_(ids))
        )
    ]


@router.get("/services/{service_id}", response_model=ServiceView, operation_id="getService")
def service_detail(service_id: str, db: Db, principal: User) -> ServiceView:
    for item in services(db, principal):
        if item.id == service_id:
            return item
    raise HTTPException(404, "Service not found")


@router.get("/catalog", response_model=list[DefinitionView], operation_id="listCatalog")
def catalog(db: Db, principal: Admin) -> list[DefinitionView]:
    return [
        DefinitionView(
            id=item.id,
            name=item.name,
            version=item.version,
            description=item.description,
            source=item.source,
        )
        for item in db.scalars(select(AppDefinition).order_by(AppDefinition.name))
    ]


@router.get("/capabilities", response_model=list[CapabilityView], operation_id="listCapabilities")
def capabilities(db: Db, principal: User) -> list[CapabilityView]:
    query = select(Capability)
    if "admin" not in principal.roles:
        ids = [item.definition_id for item in visible_installations(db, principal)]
        query = query.where(Capability.definition_id.in_(ids))
    return [
        CapabilityView(
            id=item.key,
            definition_id=item.definition_id,
            permission=item.permission,
            method=item.method,
            path=item.path,
        )
        for item in db.scalars(query)
        if item.permission in principal.roles or "admin" in principal.roles
    ]


@router.post(
    "/registry/manifests",
    response_model=DefinitionView,
    status_code=201,
    operation_id="registerManifest",
)
def register(manifest: Manifest, db: Db, principal: Admin, request: Request) -> DefinitionView:
    try:
        definition = register_manifest(db, manifest, principal, request.state.correlation_id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Definition or version already exists") from exc
    return DefinitionView(
        id=definition.id,
        name=definition.name,
        version=definition.version,
        description=definition.description,
        source=definition.source,
    )


@router.get("/platform", operation_id="getPlatform")
def platform(principal: User, response: Response, request: Request) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    return {
        "version": "0.1.0",
        "milestone": "curated-installation",
        "deployment": "enabled" if request.app.state.settings.deployment_enabled else "disabled",
    }
