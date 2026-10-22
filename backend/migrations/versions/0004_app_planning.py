"""Persistent application requests and immutable manual planning revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0004_app_planning"
down_revision = "0003_deployment_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_requests",
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("household_id", sa.String(64), nullable=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.UniqueConstraint("requested_by", "idempotency_key", name="uq_app_request_key"),
        sa.CheckConstraint("current_revision >= 1", name="ck_app_request_revision"),
    )
    op.create_index("ix_app_requests_requested_by", "app_requests", ["requested_by"])
    op.create_index("ix_app_requests_household_id", "app_requests", ["household_id"])
    op.create_table(
        "app_plans",
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("approved_job_id", sa.String(64), nullable=True),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["request_id"], ["app_requests.id"]),
        sa.ForeignKeyConstraint(["approved_job_id"], ["jobs.id"]),
        sa.UniqueConstraint("request_id", "revision", name="uq_app_plan_revision"),
        sa.UniqueConstraint("request_id", "created_by", "idempotency_key", name="uq_app_plan_key"),
        sa.UniqueConstraint("approved_job_id"),
        sa.CheckConstraint("revision >= 1", name="ck_app_plan_revision"),
    )
    op.create_index("ix_app_plans_request_id", "app_plans", ["request_id"])


def downgrade() -> None:
    op.drop_table("app_plans")
    op.drop_table("app_requests")
