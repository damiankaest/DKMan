"""Persist immutable, owner-isolated Forge source snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0005_forge_workspaces"
down_revision = "0004_app_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forge_workspaces",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_subject", sa.String(255), nullable=False),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("app_plans.id"), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("template", sa.String(40), nullable=False),
        sa.Column("bundle_hash", sa.String(64), nullable=False),
        sa.Column("bundle", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("owner_subject", "idempotency_key", name="uq_forge_workspace_key"),
    )
    op.create_index("ix_forge_workspaces_owner_subject", "forge_workspaces", ["owner_subject"])
    op.create_index("ix_forge_workspaces_plan_id", "forge_workspaces", ["plan_id"])


def downgrade() -> None:
    op.drop_table("forge_workspaces")
