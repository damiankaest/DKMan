"""Actual image builds on an explicitly disposable isolated CI builder only."""

import json
import os
import shutil
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dkman.forge.attestation import SignedBuildEvidence, verify_recipe, verify_signature
from dkman.forge.build_worker import execute_build
from dkman.forge.oci import inspect_oci_archive, verify_oci_archive
from dkman.forge.templates import TemplateProvider
from dkman.forge.workspace import GenerationRequest
from dkman.forge_api import BuildArtifactView, BuildInput, bundle_hash
from dkman.jobs import digest
from dkman.models import utcnow


@pytest.mark.buildkit
@pytest.mark.parametrize("kind", ["python-api", "react-spa", "fullstack-fastapi-react"])
def test_build_generated_starter_on_disposable_builder(tmp_path, kind):
    if os.environ.get("DKMAN_DISPOSABLE_BUILDKIT_TEST") != "1":
        pytest.skip("Requires an explicitly disposable isolated BuildKit worker")
    address = os.environ["DKMAN_TEST_BUILDKIT_SOCKET"]
    buildctl = shutil.which("buildctl")
    assert buildctl is not None
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    request = GenerationRequest(
        plan_id=str(uuid4()),
        content_hash="a" * 64,
        template=kind,
        requirements={"title": "Garden", "goal": "Grow plants", "features": ["Photos"]},
    )
    bundle = TemplateProvider().generate(request)
    source = BuildInput(workspace_id=str(uuid4()), bundle_hash=bundle_hash(bundle), bundle=bundle)
    signing_key = Ed25519PrivateKey.generate()
    result = execute_build(lambda: source, root, address, buildctl, signing_key)
    assert result["state"] == "succeeded", json.dumps(result, ensure_ascii=False)
    artifact = root / result["build_id"] / "image.oci.tar"
    manifest, archive_hash, size = verify_oci_archive(artifact)
    assert manifest == result["manifest_digest"]
    assert archive_hash == result["archive_sha256"] and size == result["archive_size"]
    signed = SignedBuildEvidence.model_validate_json(
        (artifact.parent / "build-attestation.json").read_text()
    )
    verify_signature(signed, signing_key.public_key())
    verify_recipe(signed.evidence, bundle)
    assert signed.evidence.config_digest == inspect_oci_archive(artifact).config_digest
    if kind == "react-spa" and os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") == "1":
        from dkman.deployment_adapter.compose import ComposeProvider
        from dkman.deployment_adapter.forge_preview import start_preview

        docker = shutil.which("docker")
        assert docker is not None
        preview_key = Ed25519PrivateKey.generate()
        registered = BuildArtifactView(
            id=str(signed.evidence.build_id),
            workspace_id=source.workspace_id,
            created_at=utcnow(),
            submitted_by="ci",
            key_id=signed.key_id,
            evidence_hash=digest(signed.model_dump(mode="json")),
            evidence=signed.evidence,
        )
        seen = []

        def ready(origin, proof):
            with urllib.request.urlopen(origin + "/", timeout=5) as response:
                assert response.status == 200
                assert b"<html" in response.read(4096).lower()
            seen.append(proof)

        preview = start_preview(
            signed,
            lambda: (source, registered),
            signing_key.public_key(),
            preview_key,
            artifact,
            root,
            ComposeProvider(root, uuid4(), docker),
            ttl_seconds=5,
            on_ready=ready,
            hold=lambda _: None,
        )
        assert preview["state"] == "stopped" and len(seen) == 1
    evidence = Path(os.environ["DKMAN_BUILD_EVIDENCE_DIR"])
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"{kind}.json").write_text(json.dumps(result, indent=2) + "\n")
