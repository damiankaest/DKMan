"""Actual image builds on an explicitly disposable isolated CI builder only."""

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from dkman.forge.build_worker import execute_build
from dkman.forge.oci import verify_oci_archive
from dkman.forge.templates import TemplateProvider
from dkman.forge.workspace import GenerationRequest
from dkman.forge_api import BuildInput, bundle_hash


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
    result = execute_build(lambda: source, root, address, buildctl)
    assert result["state"] == "succeeded", json.dumps(result, ensure_ascii=False)
    artifact = root / result["build_id"] / "image.oci.tar"
    manifest, archive_hash, size = verify_oci_archive(artifact)
    assert manifest == result["manifest_digest"]
    assert archive_hash == result["archive_sha256"] and size == result["archive_size"]
    evidence = Path(os.environ["DKMAN_BUILD_EVIDENCE_DIR"])
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"{kind}.json").write_text(json.dumps(result, indent=2) + "\n")
