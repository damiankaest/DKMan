"""Real BuildKit/preview/Core/adapter journey on the disposable CI engine.

Authentication is a test dependency override; real Keycloak is covered by the
separate browser journey. No operation targets a developer's Docker host.
"""

import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from test_forge_api import generate, prepare
from test_planning import approve, review, revision

from dkman.deployment_adapter.compose import ComposeProvider
from dkman.deployment_adapter.forge_preview import start_preview
from dkman.deployment_adapter.forge_staging import stage_archive
from dkman.deployment_adapter.journal import migrate
from dkman.deployment_adapter.main import AdapterSettings, create_app
from dkman.deployments.client import AdapterUnavailable
from dkman.deployments.contracts import OperationView
from dkman.forge.attestation import SignedBuildEvidence, SignedPreviewEvidence
from dkman.forge.build_worker import execute_build
from dkman.forge_api import BuildArtifactView, BuildInput


@pytest.mark.buildkit
def test_actual_core_approval_adapter_install_and_revision(client, app, tmp_path, as_user):
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") != "1"
        or os.environ.get("DKMAN_DISPOSABLE_BUILDKIT_TEST") != "1"
    ):
        pytest.skip("Requires a disposable CI BuildKit and Docker engine")
    docker = shutil.which("docker")
    buildctl = shutil.which("buildctl")
    assert docker and buildctl
    address = os.environ["DKMAN_TEST_BUILDKIT_SOCKET"]

    def docker_run(*args, check=True):
        result = subprocess.run([docker, *args], capture_output=True, text=True, timeout=180)
        if check and result.returncode:
            raise AssertionError(f"Docker {args[:2]} failed: {result.stderr[-3000:]}")
        return result

    assert docker_run("network", "inspect", "dkman-app-gateway", check=False).returncode != 0
    root = tmp_path / "worker"
    root.mkdir(mode=0o700)
    stage = tmp_path / "stage"
    stage.mkdir(mode=0o700)
    state = tmp_path / "adapter"
    migrate(state)
    builder = Ed25519PrivateKey.generate()
    preview_key = Ed25519PrivateKey.generate()
    for name, key in [("builder", builder), ("preview", preview_key)]:
        (tmp_path / f"{name}.pem").write_bytes(
            key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
    secret = tmp_path / "delegation"
    secret.write_bytes(b"ci-only-core-to-adapter-key-at-least-thirty-two-bytes")
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"schema_version":1,"images":[]}')
    settings = app.state.settings
    settings.deployment_enabled = True
    settings.deployment_catalog_file = catalog
    settings.deployment_secret_file = secret
    settings.forge_builder_public_key_file = tmp_path / "builder.pem"
    settings.forge_preview_public_key_file = tmp_path / "preview.pem"
    adapter = create_app(
        AdapterSettings(
            state_root=state,
            catalog_file=catalog,
            secret_file=secret,
            docker_binary=docker,
            forge_builder_public_key_file=tmp_path / "builder.pem",
            forge_preview_public_key_file=tmp_path / "preview.pem",
            forge_staging_root=stage,
        )
    )
    owner = uuid4().hex
    installation_id = None
    try:
        docker_run(
            "network",
            "create",
            "--internal",
            "--label",
            "io.dkman.gateway=true",
            "--label",
            f"io.dkman.ci-test={owner}",
            "dkman-app-gateway",
        )
        with TestClient(adapter) as adapter_client:

            class RealAdapter:
                deploy_calls = 0

                def execute(self, operation_id, command, token):
                    response = adapter_client.post(
                        f"/v1/operations/{operation_id}",
                        headers={"Authorization": "Bearer " + token},
                        json=command.model_dump(mode="json"),
                    )
                    assert response.status_code == 200, response.text
                    outcome = OperationView.model_validate(response.json())
                    if command.action == "deploy":
                        self.deploy_calls += 1
                        assert outcome.state == "succeeded"
                        # Simulate a lost response after the real adapter committed its receipt.
                        raise AdapterUnavailable("CI-only transport interruption")
                    return outcome

                def operation(self, operation_id, token, *, reconcile=False):
                    assert reconcile is True
                    response = adapter_client.post(
                        f"/v1/operations/{operation_id}/reconcile",
                        headers={"Authorization": "Bearer " + token},
                        json={},
                    )
                    assert response.status_code == 200, response.text
                    return OperationView.model_validate(response.json())

            transport = RealAdapter()
            app.state.deployment_client = transport
            item, plan = prepare(client, as_user)

            def build_preview(plan_record):
                as_user("alice", ["developer"])
                created = generate(client, plan_record, template="react-spa")
                assert created.status_code == 201, created.text
                workspace = created.json()
                response = client.get(f"/api/v1/forge/workspaces/{workspace['id']}/build-input")
                assert response.status_code == 200, response.text
                source = BuildInput.model_validate(response.json())
                result = execute_build(lambda: source, root, address, buildctl, builder)
                assert result["state"] == "succeeded", result
                artifact_dir = root / result["build_id"]
                archive = artifact_dir / "image.oci.tar"
                signed = SignedBuildEvidence.model_validate_json(
                    (artifact_dir / "build-attestation.json").read_text()
                )
                registration = client.post(
                    f"/api/v1/forge/workspaces/{workspace['id']}/build-artifacts",
                    json=signed.model_dump(mode="json"),
                )
                assert registration.status_code == 201, registration.text
                registered = BuildArtifactView.model_validate(registration.json())
                seen = []

                def ready(origin, proof):
                    with urllib.request.urlopen(origin + "/", timeout=5) as response:
                        assert b"<html" in response.read(4096).lower()
                    seen.append(proof)

                preview = start_preview(
                    signed,
                    lambda: (source, registered),
                    builder.public_key(),
                    preview_key,
                    archive,
                    root,
                    ComposeProvider(root, uuid4(), docker),
                    ttl_seconds=900,
                    on_ready=ready,
                    hold=lambda _: None,
                )
                assert preview["state"] == "stopped" and len(seen) == 1
                observation = SignedPreviewEvidence.model_validate_json(Path(seen[0]).read_text())
                response = client.post(
                    f"/api/v1/forge/build-artifacts/{registered.id}/previews",
                    json=observation.model_dump(mode="json"),
                )
                assert response.status_code == 201, response.text
                stage_archive(
                    signed, lambda: (source, registered), builder.public_key(), archive, stage
                )
                return response.json()

            first = build_preview(plan)
            as_user("admin", ["admin", "member"])
            home = client.post("/api/v1/households", json={"name": "CI home"}).json()
            planned = client.post(
                f"/api/v1/forge/previews/{first['id']}/installations",
                json={"household_id": home["id"]},
                headers={"Idempotency-Key": str(uuid4())},
            )
            assert planned.status_code == 202, planned.text
            job = planned.json()
            installation_id = job["resource_id"]
            assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
            assert approve(client, job).status_code == 200
            result = client.post(f"/api/v1/jobs/{job['id']}/run")
            assert result.status_code == 200 and result.json()["state"] == "succeeded", result.text
            apps = client.get("/api/v1/apps").json()
            assert any(entry["id"] == installation_id and entry["route"] for entry in apps)
            old_container = json.loads(
                docker_run(
                    "ps",
                    "--filter",
                    f"label=io.dkman.installation={installation_id}",
                    "--format",
                    "{{json .ID}}",
                ).stdout.strip()
            )
            as_user("alice", ["developer"])
            revised = revision(client, item)
            assert revised.status_code == 201, revised.text
            next_plan = revised.json()
            as_user("admin", ["admin", "member"])
            reviewed = review(client, next_plan).json()
            assert approve(client, reviewed).status_code == 200
            assert client.post(f"/api/v1/jobs/{reviewed['id']}/run").json()["state"] == "succeeded"
            next_preview = build_preview(next_plan)
            as_user("admin", ["admin", "member"])
            update = client.post(
                f"/api/v1/forge/previews/{next_preview['id']}/upgrades",
                json={"installation_id": installation_id},
                headers={"Idempotency-Key": str(uuid4())},
            )
            assert update.status_code == 202, update.text
            update_job = update.json()
            assert approve(client, update_job).status_code == 200
            result = client.post(f"/api/v1/jobs/{update_job['id']}/run")
            assert result.status_code == 200 and result.json()["state"] == "reconciliation_required"
            result = client.post(f"/api/v1/jobs/{update_job['id']}/reconcile")
            assert result.status_code == 200 and result.json()["state"] == "succeeded", result.text
            assert result.json()["result"]["evidence_kind"] == "engine_acknowledgement"
            assert transport.deploy_calls == 1
            new_container = json.loads(
                docker_run(
                    "ps",
                    "--filter",
                    f"label=io.dkman.installation={installation_id}",
                    "--format",
                    "{{json .ID}}",
                ).stdout.strip()
            )
            assert old_container != new_container
            apps = client.get("/api/v1/apps").json()
            current = next(entry for entry in apps if entry["id"] == installation_id)
            assert current["version"] == update_job["plan"]["replacement"]["version"]
            assert current["route"] == f"/run/{installation_id}/"
    finally:
        if installation_id:
            containers = docker_run(
                "ps",
                "--all",
                "--filter",
                f"label=io.dkman.installation={installation_id}",
                "--format",
                "{{.ID}}",
                check=False,
            ).stdout.split()
            for container in containers:
                details = json.loads(docker_run("container", "inspect", container).stdout)[0]
                assert details["Config"]["Labels"]["io.dkman.installation"] == installation_id
                docker_run("container", "rm", "--force", container)
            private = f"dkman-app-{installation_id}-private"
            probe = docker_run("network", "inspect", private, check=False)
            if probe.returncode == 0:
                assert (
                    json.loads(probe.stdout)[0]["Labels"]["io.dkman.installation"]
                    == installation_id
                )
                docker_run("network", "rm", private)
        probe = docker_run("network", "inspect", "dkman-app-gateway", check=False)
        if probe.returncode == 0:
            assert json.loads(probe.stdout)[0]["Labels"]["io.dkman.ci-test"] == owner
            docker_run("network", "rm", "dkman-app-gateway")
