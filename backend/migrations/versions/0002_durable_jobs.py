"""Add durable jobs events and bound approvals"""

import sqlalchemy as sa
from alembic import op

revision = "0002_durable_jobs"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=120), nullable=False),
        sa.Column("risk", sa.String(length=20), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "risk IN ('read_only','reversible','sensitive','destructive')", name="ck_job_risk"
        ),
        sa.CheckConstraint(
            "state IN ('waiting_approval','queued','claimed','running','succeeded','failed',"
            "'cancelled','expired','reconciliation_required')",
            name="ck_job_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requested_by", "idempotency_key", name="uq_job_request_key"),
    )
    op.create_index("ix_jobs_recovery", "jobs", ["state", "lease_expires_at"], unique=False)
    op.create_index(op.f("ix_jobs_requested_by"), "jobs", ["requested_by"], unique=False)
    op.create_index(op.f("ix_jobs_resource_id"), "jobs", ["resource_id"], unique=False)
    op.create_table(
        "approval_requests",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=120), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending','approved','rejected','expired','consumed','cancelled')",
            name="ck_approval_state",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_approval_job"),
    )
    op.create_index(
        "ix_approvals_expiry", "approval_requests", ["state", "expires_at"], unique=False
    )
    op.create_table(
        "job_events",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "sequence", name="uq_job_event_sequence"),
    )
    op.create_index("ix_job_events_cursor", "job_events", ["job_id", "sequence"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_events_cursor", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_approvals_expiry", table_name="approval_requests")
    op.drop_table("approval_requests")
    op.drop_index(op.f("ix_jobs_resource_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_requested_by"), table_name="jobs")
    op.drop_index("ix_jobs_recovery", table_name="jobs")
    op.drop_table("jobs")
