"""Initial DKMan registry, access control and audit schema.

Immutable migration: no imports from live domain metadata.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_definitions",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=120), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_events_actor_subject"), "audit_events", ["actor_subject"], unique=False
    )
    op.create_index(
        op.f("ix_audit_events_resource_id"), "audit_events", ["resource_id"], unique=False
    )
    op.create_table(
        "households",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "user_profiles",
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject"),
    )
    op.create_table(
        "capabilities",
        sa.Column("definition_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("permission", sa.String(length=20), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["app_definitions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("definition_id", "key"),
    )
    op.create_index(
        op.f("ix_capabilities_definition_id"), "capabilities", ["definition_id"], unique=False
    )
    op.create_table(
        "household_memberships",
        sa.Column("household_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profiles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "user_id"),
    )
    op.create_index(
        op.f("ix_household_memberships_household_id"),
        "household_memberships",
        ["household_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_household_memberships_user_id"), "household_memberships", ["user_id"], unique=False
    )
    op.create_table(
        "service_manifests",
        sa.Column("definition_id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["app_definitions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("definition_id", "version"),
    )
    op.create_index(
        op.f("ix_service_manifests_definition_id"),
        "service_manifests",
        ["definition_id"],
        unique=False,
    )
    op.create_table(
        "app_installations",
        sa.Column("definition_id", sa.String(length=64), nullable=False),
        sa.Column("manifest_id", sa.String(length=64), nullable=False),
        sa.Column("household_id", sa.String(length=64), nullable=False),
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column("desired_state", sa.String(length=20), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["app_definitions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
        ),
        sa.ForeignKeyConstraint(
            ["manifest_id"],
            ["service_manifests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_app_installations_definition_id"),
        "app_installations",
        ["definition_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_app_installations_household_id"),
        "app_installations",
        ["household_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_app_installations_owner_subject"),
        "app_installations",
        ["owner_subject"],
        unique=False,
    )
    op.create_table(
        "permission_grants",
        sa.Column("installation_id", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("permission", sa.String(length=120), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["app_installations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id", "subject", "permission"),
    )
    op.create_index(
        op.f("ix_permission_grants_installation_id"),
        "permission_grants",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_permission_grants_subject"), "permission_grants", ["subject"], unique=False
    )
    op.create_table(
        "service_instances",
        sa.Column("installation_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("runtime_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_reason", sa.String(length=255), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["app_installations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_service_instances_installation_id"),
        "service_instances",
        ["installation_id"],
        unique=False,
    )
    op.create_table(
        "health_observations",
        sa.Column("service_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["service_instances.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_health_service_time", "health_observations", ["service_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_health_service_time", table_name="health_observations")
    op.drop_table("health_observations")
    op.drop_index(op.f("ix_service_instances_installation_id"), table_name="service_instances")
    op.drop_table("service_instances")
    op.drop_index(op.f("ix_permission_grants_subject"), table_name="permission_grants")
    op.drop_index(op.f("ix_permission_grants_installation_id"), table_name="permission_grants")
    op.drop_table("permission_grants")
    op.drop_index(op.f("ix_app_installations_owner_subject"), table_name="app_installations")
    op.drop_index(op.f("ix_app_installations_household_id"), table_name="app_installations")
    op.drop_index(op.f("ix_app_installations_definition_id"), table_name="app_installations")
    op.drop_table("app_installations")
    op.drop_index(op.f("ix_service_manifests_definition_id"), table_name="service_manifests")
    op.drop_table("service_manifests")
    op.drop_index(op.f("ix_household_memberships_user_id"), table_name="household_memberships")
    op.drop_index(op.f("ix_household_memberships_household_id"), table_name="household_memberships")
    op.drop_table("household_memberships")
    op.drop_index(op.f("ix_capabilities_definition_id"), table_name="capabilities")
    op.drop_table("capabilities")
    op.drop_table("user_profiles")
    op.drop_table("households")
    op.drop_index(op.f("ix_audit_events_resource_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_subject"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("app_definitions")
