"""Actual image builds on an explicitly disposable isolated CI builder only."""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dkman.forge.attestation import (
    SignedBuildEvidence,
    SignedPreviewEvidence,
    verify_preview_signature,
    verify_recipe,
    verify_signature,
)
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
    if os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") == "1":
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
            endpoint = "/health/live" if kind == "python-api" else "/"
            with urllib.request.urlopen(origin + endpoint, timeout=5) as response:
                assert response.status == 200
                payload = response.read(4096)
                if kind == "python-api":
                    assert json.loads(payload) == {"status": "healthy"}
                else:
                    assert b"<html" in payload.lower()
                    script = re.search(
                        rb'<script[^>]+src="((?:\./|/)assets/[a-zA-Z0-9._-]+\.js)"', payload
                    )
                    assert script is not None, payload.decode("utf-8", errors="replace")
                    with urllib.request.urlopen(
                        urllib.parse.urljoin(origin + "/", script.group(1).decode("ascii")),
                        timeout=5,
                    ) as asset:
                        assert asset.status == 200
                        assert "javascript" in asset.headers.get("Content-Type", "")
                        assert len(asset.read(4096)) > 100
            seen.append(proof)

        # Disposable CI only: surface Docker stderr on failure without retrying a mutation.
        # The production provider keeps subprocess output private.
        popen = subprocess.Popen

        class ObservedProcess:
            def __init__(self, process, output, errors, arguments):
                self.process, self.output, self.errors, self.arguments = (
                    process,
                    output,
                    errors,
                    arguments,
                )

            def __getattr__(self, name):
                return getattr(self.process, name)

            def wait(self, timeout=None):
                result = self.process.wait(timeout=timeout)
                if result:
                    self.errors.seek(0)
                    message = self.errors.read(4096).decode("utf-8", errors="replace")
                    print(f"Docker {self.arguments[3:5]} failed: {message}", file=sys.stderr)
                    self.output.seek(0)
                    output = self.output.read(4096).decode("utf-8", errors="replace")
                    print(f"Docker output: {output}", file=sys.stderr)
                    if self.arguments[3:5] == ["container", "port"]:
                        container_id = self.arguments[5]
                        probes = [
                            [
                                "container",
                                "inspect",
                                "--format",
                                "{{json .State}} {{json .NetworkSettings.Ports}} "
                                "{{json .HostConfig.PortBindings}}",
                                container_id,
                            ],
                            ["container", "logs", "--tail", "30", container_id],
                        ]
                        for probe in probes:
                            process = popen(
                                [docker, "--host", "unix:///var/run/docker.sock", *probe],
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                            )
                            details, _ = process.communicate(timeout=10)
                            print(details[:8192].decode("utf-8", errors="replace"), file=sys.stderr)
                return result

        def observed_popen(arguments, **kwargs):
            return ObservedProcess(
                popen(arguments, **kwargs), kwargs["stdout"], kwargs["stderr"], arguments
            )

        with patch("dkman.deployment_adapter.compose.subprocess.Popen", observed_popen):
            preview = start_preview(
                signed,
                lambda: (source, registered),
                signing_key.public_key(),
                preview_key,
                artifact,
                root,
                ComposeProvider(root, uuid4(), docker),
                ttl_seconds=300,
                on_ready=ready,
                hold=lambda _: None,
            )
        assert preview["state"] == "stopped" and len(seen) == 1
        observation = SignedPreviewEvidence.model_validate_json(seen[0].read_text())
        verify_preview_signature(observation, preview_key.public_key())
        assert observation.evidence.config_digest == signed.evidence.config_digest
        assert observation.evidence.artifact_id == signed.evidence.build_id
        if kind == "react-spa":
            from forge_deploy_ci import exercise_forge_install

            exercise_forge_install(
                root, artifact, source, registered, signed, signing_key, preview_key, observation
            )
    evidence = Path(os.environ["DKMAN_BUILD_EVIDENCE_DIR"])
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"{kind}.json").write_text(json.dumps(result, indent=2) + "\n")
