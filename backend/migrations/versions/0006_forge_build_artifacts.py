"""Persist signed Forge build attestations without storing the image in Core."""

import sqlalchemy as sa
from alembic import op

revision = "0006_forge_build_artifacts"
down_revision = "0005_forge_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forge_build_artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "workspace_id", sa.String(64), sa.ForeignKey("forge_workspaces.id"), nullable=False
        ),
        sa.Column("submitted_by", sa.String(255), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("attestation", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_forge_build_artifacts_workspace_id", "forge_build_artifacts", ["workspace_id"]
    )
    op.create_index(
        "ix_forge_build_artifacts_submitted_by", "forge_build_artifacts", ["submitted_by"]
    )
    op.create_table(
        "forge_previews",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "artifact_id", sa.String(64), sa.ForeignKey("forge_build_artifacts.id"), nullable=False
        ),
        sa.Column("submitted_by", sa.String(255), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("attestation", sa.JSON(), nullable=False),
    )
    op.create_index("ix_forge_previews_artifact_id", "forge_previews", ["artifact_id"])
    op.create_index("ix_forge_previews_submitted_by", "forge_previews", ["submitted_by"])


def downgrade() -> None:
    op.drop_table("forge_previews")
    op.drop_table("forge_build_artifacts")
