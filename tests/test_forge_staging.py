import stat

import pytest
from test_forge_preview import setup_preview

from dkman.deployment_adapter.forge_preview import PreviewError
from dkman.deployment_adapter.forge_staging import stage_archive
from dkman.forge.attestation import SignedBuildEvidence
from dkman.forge.oci import inspect_oci_archive

__all__ = ["setup_preview"]


def test_staging_is_private_bound_and_idempotent(setup_preview):
    root, archive, source, registered, signed, builder, _, _ = setup_preview
    staging = root / "staging"
    staging.mkdir(mode=0o700)

    def authorize():
        return source, registered

    result = stage_archive(signed, authorize, builder.public_key(), archive, staging)
    assert result == staging / str(signed.evidence.build_id)
    assert stat.S_IMODE(result.stat().st_mode) == 0o700
    assert stat.S_IMODE((result / "image.oci.tar").stat().st_mode) == 0o600
    assert (
        inspect_oci_archive(result / "image.oci.tar").config_digest == signed.evidence.config_digest
    )
    assert (
        SignedBuildEvidence.model_validate_json((result / "build-attestation.json").read_bytes())
        == signed
    )
    assert stage_archive(signed, authorize, builder.public_key(), archive, staging) == result


def test_staging_fails_closed_if_plan_changes_after_copy(setup_preview):
    root, archive, source, registered, signed, builder, _, _ = setup_preview
    staging = root / "staging"
    staging.mkdir(mode=0o700)
    calls = 0

    def authorize():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PreviewError("authorization_revoked")
        return source, registered

    with pytest.raises(PreviewError, match="authorization_revoked"):
        stage_archive(signed, authorize, builder.public_key(), archive, staging)
    assert not (staging / str(signed.evidence.build_id)).exists()
    assert not list(staging.glob(".staging-*"))


def test_staging_rejects_tampered_existing_archive(setup_preview):
    root, archive, source, registered, signed, builder, _, _ = setup_preview
    staging = root / "staging"
    staging.mkdir(mode=0o700)

    def authorize():
        return source, registered

    result = stage_archive(signed, authorize, builder.public_key(), archive, staging)
    existing = result / "image.oci.tar"
    existing.write_bytes(existing.read_bytes() + b"tampered")
    with pytest.raises(PreviewError, match="archive_does_not_match"):
        stage_archive(signed, authorize, builder.public_key(), archive, staging)
    assert existing.read_bytes().endswith(b"tampered")


@pytest.mark.parametrize("setup_preview", ["python-api", "fullstack-fastapi-react"], indirect=True)
def test_staging_restricts_production_to_the_reviewed_spa(setup_preview):
    root, archive, source, registered, signed, builder, _, _ = setup_preview
    staging = root / "staging"
    staging.mkdir(mode=0o700)
    with pytest.raises(PreviewError, match="production_staging_requires_react_spa"):
        stage_archive(signed, lambda: (source, registered), builder.public_key(), archive, staging)
    assert not (staging / str(signed.evidence.build_id)).exists()
