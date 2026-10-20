"""Persist deployment reservations without pretending that an app is installed."""

import sqlalchemy as sa
from alembic import op

revision = "0003_deployment_targets"
down_revision = "0002_durable_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployment_targets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("household_id", sa.String(64), sa.ForeignKey("households.id"), nullable=False),
        sa.Column(
            "definition_id", sa.String(64), sa.ForeignKey("app_definitions.id"), nullable=False
        ),
    )
    op.create_index(
        "ix_deployment_target_household_app",
        "deployment_targets",
        ["household_id", "definition_id"],
    )


def downgrade() -> None:
    op.drop_table("deployment_targets")
