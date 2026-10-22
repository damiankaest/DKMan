import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
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


class Job(Record, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("requested_by", "idempotency_key", name="uq_job_request_key"),
        CheckConstraint(
            "state IN ('waiting_approval','queued','claimed','running','succeeded','failed',"
            "'cancelled','expired','reconciliation_required')",
            name="ck_job_state",
        ),
        CheckConstraint(
            "risk IN ('read_only','reversible','sensitive','destructive')", name="ck_job_risk"
        ),
        Index("ix_jobs_recovery", "state", "lease_expires_at"),
    )
    requested_by: Mapped[str] = mapped_column(String(255), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(120), index=True)
    risk: Mapped[str] = mapped_column(String(20))
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    plan_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_sequence: Mapped[int] = mapped_column(default=0)
    attempt: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    requires_approval: Mapped[bool] = mapped_column(default=True)
    correlation_id: Mapped[str] = mapped_column(String(36))


class JobEvent(Record, Base):
    __tablename__ = "job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_job_event_sequence"),
        Index("ix_job_events_cursor", "job_id", "sequence"),
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    sequence: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(32))
    actor_subject: Mapped[str] = mapped_column(String(255))


class ApprovalRequest(Record, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_approval_job"),
        CheckConstraint(
            "state IN ('pending','approved','rejected','expired','consumed','cancelled')",
            name="ck_approval_state",
        ),
        Index("ix_approvals_expiry", "state", "expires_at"),
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    subject: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(120))
    plan_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(20), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeploymentTarget(Record, Base):
    """Reservation and immutable job link, separate from an actual installation."""

    __tablename__ = "deployment_targets"
    __table_args__ = (Index("ix_deployment_target_household_app", "household_id", "definition_id"),)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"))
    definition_id: Mapped[str] = mapped_column(ForeignKey("app_definitions.id"))


class AppRequest(Record, Base):
    __tablename__ = "app_requests"
    __table_args__ = (
        UniqueConstraint("requested_by", "idempotency_key", name="uq_app_request_key"),
        CheckConstraint("current_revision >= 1", name="ck_app_request_revision"),
    )
    requested_by: Mapped[str] = mapped_column(String(255), index=True)
    household_id: Mapped[str | None] = mapped_column(ForeignKey("households.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    current_revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))


class AppPlan(Record, Base):
    __tablename__ = "app_plans"
    __table_args__ = (
        UniqueConstraint("request_id", "revision", name="uq_app_plan_revision"),
        UniqueConstraint("request_id", "created_by", "idempotency_key", name="uq_app_plan_key"),
        CheckConstraint("revision >= 1", name="ck_app_plan_revision"),
    )
    request_id: Mapped[str] = mapped_column(ForeignKey("app_requests.id"), index=True)
    revision: Mapped[int] = mapped_column()
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    approved_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), unique=True)
