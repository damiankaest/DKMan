from datetime import timedelta
from uuid import uuid4

import pytest
from test_forge_preview import setup_preview

from dkman.deployments.contracts import (
    Catalog,
    DeploymentPlan,
    ForgeReleaseProof,
    InstallationContext,
    validate_plan,
)
from dkman.forge.attestation import PreviewEvidence, sign_preview
from dkman.models import utcnow

__all__ = ["setup_preview"]


def release_plan(setup_preview, *, expired=False):
    _, _, source, registered, signed, builder, preview, _ = setup_preview
    now = utcnow()
    observed = now - timedelta(minutes=6) if expired else now
    proof = sign_preview(
        PreviewEvidence(
            preview_id=uuid4(),
            artifact_id=signed.evidence.build_id,
            workspace_id=signed.evidence.workspace_id,
            artifact_evidence_hash=registered.evidence_hash,
            source_hash=source.bundle_hash,
            plan_hash=signed.evidence.plan_hash,
            manifest_digest=signed.evidence.manifest_digest,
            config_digest=signed.evidence.config_digest,
            container_id="c" * 64,
            observed_at=observed,
            expires_at=observed + timedelta(minutes=5),
        ),
        preview,
    )
    plan = DeploymentPlan(
        definition_id="forge-" + uuid4().hex,
        version="0.1.0",
        image=signed.evidence.config_digest,
        internal_port=8080,
        user="101",
        memory_mb=256,
        cpus=0.5,
        profile="forge-spa-v1",
        source_hash=source.bundle_hash,
        installation_id=uuid4(),
        context=InstallationContext(
            household_id=uuid4(), subject="admin", manifest_id=uuid4(), manifest_hash="a" * 64
        ),
        forge=ForgeReleaseProof(build=signed, preview=proof),
    )
    return plan, builder, preview


def test_release_policy_binds_both_signatures_and_exact_image(setup_preview):
    plan, builder, preview = release_plan(setup_preview)
    validate_plan(
        Catalog(),
        plan,
        builder_key=builder.public_key(),
        preview_key=preview.public_key(),
        require_fresh_preview=True,
    )
    with pytest.raises(ValueError, match="verification keys"):
        validate_plan(Catalog(), plan)
    with pytest.raises(ValueError):
        validate_plan(
            Catalog(), plan, builder_key=preview.public_key(), preview_key=builder.public_key()
        )
    changed = plan.model_dump(mode="json")
    changed["image"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="signed build and preview"):
        DeploymentPlan.model_validate(changed)


def test_expired_preview_cannot_authorize_install_but_keeps_existing_runtime_usable(setup_preview):
    plan, builder, preview = release_plan(setup_preview, expired=True)
    validate_plan(
        Catalog(), plan, builder_key=builder.public_key(), preview_key=preview.public_key()
    )
    with pytest.raises(ValueError, match="expired"):
        validate_plan(
            Catalog(),
            plan,
            builder_key=builder.public_key(),
            preview_key=preview.public_key(),
            require_fresh_preview=True,
        )


def test_release_rejects_preview_for_a_different_build(setup_preview):
    plan, _, _ = release_plan(setup_preview)
    payload = plan.model_dump(mode="json")
    payload["forge"]["preview"]["evidence"]["artifact_id"] = str(uuid4())
    with pytest.raises(ValueError, match="do not match"):
        DeploymentPlan.model_validate(payload)
