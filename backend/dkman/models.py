import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserProfile(Record, Base):
    __tablename__ = "user_profiles"
    subject: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))


class Household(Record, Base):
    __tablename__ = "households"
    name: Mapped[str] = mapped_column(String(120))


class HouseholdMembership(Record, Base):
    __tablename__ = "household_memberships"
    __table_args__ = (UniqueConstraint("household_id", "user_id"),)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("user_profiles.id"), index=True)


class AppDefinition(Record, Base):
    __tablename__ = "app_definitions"
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(2000), default="")
    source: Mapped[str] = mapped_column(String(255))


class ServiceManifest(Record, Base):
    __tablename__ = "service_manifests"
    __table_args__ = (UniqueConstraint("definition_id", "version"),)
    definition_id: Mapped[str] = mapped_column(ForeignKey("app_definitions.id"), index=True)
    schema_version: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(40))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)


class Capability(Record, Base):
    __tablename__ = "capabilities"
    __table_args__ = (UniqueConstraint("definition_id", "key"),)
    definition_id: Mapped[str] = mapped_column(ForeignKey("app_definitions.id"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    permission: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(255))


class AppInstallation(Record, Base):
    __tablename__ = "app_installations"
    definition_id: Mapped[str] = mapped_column(ForeignKey("app_definitions.id"), index=True)
    manifest_id: Mapped[str] = mapped_column(ForeignKey("service_manifests.id"))
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    owner_subject: Mapped[str] = mapped_column(String(255), index=True)
    desired_state: Mapped[str] = mapped_column(String(20), default="stopped")


class PermissionGrant(Record, Base):
    __tablename__ = "permission_grants"
    __table_args__ = (UniqueConstraint("installation_id", "subject", "permission"),)
    installation_id: Mapped[str] = mapped_column(ForeignKey("app_installations.id"), index=True)
    subject: Mapped[str] = mapped_column(String(255), index=True)
    permission: Mapped[str] = mapped_column(String(120), default="app.use")


class ServiceInstance(Record, Base):
    __tablename__ = "service_instances"
    installation_id: Mapped[str] = mapped_column(ForeignKey("app_installations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    runtime_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_reason: Mapped[str | None] = mapped_column(String(255))


class HealthObservation(Record, Base):
    __tablename__ = "health_observations"
    __table_args__ = (Index("ix_health_service_time", "service_id", "created_at"),)
    service_id: Mapped[str] = mapped_column(ForeignKey("service_instances.id"))
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(255))


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    actor_subject: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(120), index=True)
    outcome: Mapped[str] = mapped_column(String(20))
    correlation_id: Mapped[str] = mapped_column(String(36))
