from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from dkman.auth import Principal
from dkman.manifest import Manifest
from dkman.models import (
    AppDefinition,
    AppInstallation,
    AuditEvent,
    Capability,
    PermissionGrant,
    ServiceManifest,
)


def visible_installations(session: Session, principal: Principal) -> list[AppInstallation]:
    query = select(AppInstallation).order_by(AppInstallation.created_at)
    if "admin" not in principal.roles:
        grants = select(PermissionGrant.installation_id).where(
            PermissionGrant.subject == principal.subject,
            PermissionGrant.permission == "app.use",
        )
        query = query.where(AppInstallation.id.in_(grants))
    return list(session.scalars(query))


def register_manifest(
    session: Session,
    manifest: Manifest,
    principal: Principal,
    correlation_id: str,
    *,
    source: str = "admin-registration",
) -> AppDefinition:
    """Register metadata only. This does not review or authorize an image for deployment."""
    definition = session.get(AppDefinition, manifest.id)
    if definition:
        raise HTTPException(
            409, "Definition already registered; revisions require an update workflow"
        )
    definition = AppDefinition(
        id=manifest.id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        source=source,
    )
    session.add(definition)
    session.flush()
    session.add(
        ServiceManifest(
            definition_id=definition.id,
            schema_version=manifest.schema_version,
            version=manifest.version,
            content=manifest.model_dump(by_alias=True),
        )
    )
    for item in manifest.capabilities:
        session.add(
            Capability(
                definition_id=definition.id,
                key=item.id,
                permission=item.permission,
                method=item.method,
                path=item.path,
            )
        )
    session.add(
        AuditEvent(
            actor_subject=principal.subject,
            action="registry.register",
            resource_id=manifest.id,
            outcome="succeeded",
            correlation_id=correlation_id,
        )
    )
    session.commit()
    return definition
