"""Actual Docker/Compose boundary test. May run only on a disposable GitHub runner."""

import json
import os
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from dkman.deployments.auth import sign_delegation
from dkman.deployments.client import AdapterUnavailable, HttpDeploymentClient
from dkman.deployments.contracts import (
    READ_ACTIONS,
    Catalog,
    CuratedImage,
    DeploymentCommand,
    PlanRequest,
    canonical_hash,
)

ROOT = Path(__file__).resolve().parents[1]
pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") != "1",
        reason="Requires explicitly disposable GitHub Actions Docker runner",
    ),
]


def docker(*arguments, check=True):
    result = subprocess.run(
        ["docker", *map(str, arguments)], capture_output=True, text=True, timeout=240, cwd=ROOT
    )
    if check and result.returncode:
        pytest.fail(f"Disposable Docker command failed: {arguments[:2]} (output withheld)")
    return result.stdout.strip()


def test_real_adapter_lifecycle_persistence_isolation_and_uncertain_recovery(tmp_path):
    # Test-only artifacts are built here and registered by actual immutable image IDs.
    iid = tmp_path / "fixture.iid"
    docker("build", "--quiet", "--iidfile", iid, "-f", "tests/deployment-fixture/Dockerfile", ".")
    healthy_image = iid.read_text().strip()
    iid.unlink()
    docker(
        "build",
        "--quiet",
        "--iidfile",
        iid,
        "--build-arg",
        "FIXTURE_UNHEALTHY=1",
        "-f",
        "tests/deployment-fixture/Dockerfile",
        ".",
    )
    unhealthy_image = iid.read_text().strip()
    adapter_image = f"dkman-adapter-ci:{uuid4().hex}"
    docker(
        "build",
        "--quiet",
        "-t",
        adapter_image,
        "-f",
        "infrastructure/deployment-adapter/Dockerfile",
        ".",
    )
    catalog = Catalog(
        images=[
            CuratedImage(
                definition_id="fixture",
                version="1.0.0",
                image=healthy_image,
                internal_port=8080,
                data_path="/data",
            ),
            CuratedImage(
                definition_id="fixture-unhealthy",
                version="1.0.0",
                image=unhealthy_image,
                internal_port=8080,
                data_path="/data",
            ),
        ]
    )
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(catalog.model_dump_json())
    catalog_file.chmod(0o444)
    secret = secrets.token_urlsafe(48).encode()
    key_file = tmp_path / "key"
    key_file.write_bytes(secret)
    key_file.chmod(0o444)
    name = "dkman-adapter-ci-" + uuid4().hex
    state_volume = name + "-state"
    installation_ids = [uuid4(), uuid4(), uuid4()]
    sentinel = None
    try:
        docker(
            "run",
            "--rm",
            "--volume",
            f"{state_volume}:/var/lib/dkman-adapter",
            adapter_image,
            "python",
            "-m",
            "dkman.deployment_adapter.journal",
            "--state-root",
            "/var/lib/dkman-adapter",
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        docker(
            "run",
            "--detach",
            "--name",
            name,
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--group-add",
            os.stat("/var/run/docker.sock").st_gid,
            "--volume",
            "/var/run/docker.sock:/var/run/docker.sock",
            "--volume",
            f"{state_volume}:/var/lib/dkman-adapter",
            "--volume",
            f"{catalog_file}:/etc/dkman-adapter/catalog.json:ro",
            "--volume",
            f"{key_file}:/run/secrets/adapter-delegation-key:ro",
            "--publish",
            f"127.0.0.1:{port}:8010",
            adapter_image,
        )
        client = HttpDeploymentClient(f"http://127.0.0.1:{port}")

        def wait_ready():
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=2):
                        return
                except OSError:
                    time.sleep(0.2)
            pytest.fail("Disposable adapter did not become ready")

        def credential(plan, operation_id, action, *, approval_id=None, expiry=None, digest=None):
            return sign_delegation(
                secret=secret,
                subject="ci-admin",
                roles=["admin"],
                operation_id=operation_id,
                action=action,
                resource_id=plan.installation_id,
                plan_hash=digest or plan.plan_hash,
                approval_id=(approval_id or uuid4())
                if action not in READ_ACTIONS | {"plan", "operation.read", "reconcile"}
                else None,
                approval_expires_at=(expiry or datetime.now(UTC) + timedelta(minutes=10))
                if action not in READ_ACTIONS | {"plan", "operation.read", "reconcile"}
                else None,
            )

        def execute(plan, action):
            operation_id = uuid4()
            return client.execute(
                operation_id,
                DeploymentCommand(action=action, plan=plan),
                credential(plan, operation_id, action),
            )

        wait_ready()
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/operations/{uuid4()}")
        assert denied.value.code == 401
        request = PlanRequest(
            installation_id=installation_ids[0], definition_id="fixture", version="1.0.0"
        )
        from dkman.deployments.contracts import build_plan

        expected = build_plan(catalog, request)
        plan = client.plan(
            request,
            credential(
                expected, uuid4(), "plan", digest=canonical_hash(request.model_dump(mode="json"))
            ),
        )
        assert plan == expected
        forbidden = plan.model_copy(update={"image": "sha256:" + "f" * 64})
        denied = execute(forbidden, "install")
        assert denied.state == "failed" and denied.rejection.reason == "curation_rejected"
        assert not docker(
            "ps", "-aq", "--filter", f"label=io.dkman.installation={plan.installation_id}"
        )
        installed = execute(plan, "install")
        assert installed.state == "succeeded" and installed.runtime.state == "running"
        container_id = installed.runtime.container_id
        inspection = json.loads(docker("container", "inspect", container_id))[0]
        assert inspection["Config"]["User"] == "10001:10001"
        assert inspection["HostConfig"]["ReadonlyRootfs"]
        assert inspection["HostConfig"]["CapDrop"] == ["ALL"]
        assert not inspection["HostConfig"]["Privileged"]
        assert not inspection["HostConfig"].get("PortBindings")
        assert not any("docker.sock" in item.get("Source", "") for item in inspection["Mounts"])
        network = json.loads(docker("network", "inspect", f"{plan.project}-private"))[0]
        assert network["Internal"]
        output = execute(plan, "logs").logs
        assert "counter=1" in output and "smoke-only-secret" not in output
        assert "[REDACTED]" in output
        assert execute(plan, "stop").runtime.state == "stopped"
        assert execute(plan, "start").runtime.state == "running"
        assert "counter=2" in execute(plan, "logs").logs
        assert execute(plan, "restart").state == "succeeded"
        for _ in range(30):
            if execute(plan, "status").runtime.state == "running":
                break
            time.sleep(0.2)
        assert "counter=3" in execute(plan, "logs").logs
        with pytest.raises(AdapterUnavailable) as blocked:
            execute(plan, "remove_data")
        assert blocked.value.__cause__.code == 409
        assert execute(plan, "remove").runtime.state == "absent"
        assert json.loads(docker("volume", "inspect", f"{plan.project}-data"))
        assert execute(plan, "install").runtime.state == "running"
        assert "counter=4" in execute(plan, "logs").logs
        assert execute(plan, "remove").state == "succeeded"
        assert execute(plan, "remove_data").state == "succeeded"
        assert not docker("volume", "ls", "--quiet", "--filter", f"name=^{plan.project}-data$")

        # A deliberately unhealthy real image causes an uncertain operation after Compose timeout.
        bad_plan = build_plan(
            catalog,
            PlanRequest(
                installation_id=installation_ids[1],
                definition_id="fixture-unhealthy",
                version="1.0.0",
            ),
        )
        operation_id = uuid4()
        auth = credential(bad_plan, operation_id, "install")
        command = DeploymentCommand(action="install", plan=bad_plan)
        uncertain = client.execute(operation_id, command, auth)
        assert uncertain.state == "reconciliation_required"
        before = docker(
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=io.dkman.installation={bad_plan.installation_id}",
        )
        assert before
        assert client.execute(operation_id, command, auth).state == "reconciliation_required"
        with pytest.raises(AdapterUnavailable):
            execute(bad_plan, "deploy")
        docker("restart", name)
        wait_ready()
        observed = client.operation(
            operation_id, credential(bad_plan, operation_id, "reconcile"), reconcile=True
        )
        assert observed.state == "reconciliation_required"
        assert observed.runtime.state == "unhealthy"
        with pytest.raises(AdapterUnavailable):
            execute(bad_plan, "deploy")
        assert before == docker(
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=io.dkman.installation={bad_plan.installation_id}",
        )

        # Foreign same-project resources must remain intact, even for a valid signed plan.
        foreign = build_plan(
            catalog,
            PlanRequest(
                installation_id=installation_ids[2], definition_id="fixture", version="1.0.0"
            ),
        )
        sentinel = docker(
            "create",
            "--label",
            f"com.docker.compose.project={foreign.project}",
            "--label",
            "io.dkman.managed=false",
            healthy_image,
        )
        collision = execute(foreign, "install")
        assert collision.state == "failed"
        assert collision.rejection.reason == "resource_preflight_rejected"
        assert json.loads(docker("container", "inspect", sentinel))[0]["Id"] == sentinel
    finally:
        # Only UUIDs created in this test; never prune or inspect another project's resources.
        if sentinel:
            docker("rm", "--force", sentinel, check=False)
        for installation_id in installation_ids:
            ids = docker(
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=io.dkman.installation={installation_id}",
                check=False,
            )
            for identifier in ids.split():
                docker("rm", "--force", identifier, check=False)
            docker("network", "rm", f"dkman-app-{installation_id}-private", check=False)
            docker("volume", "rm", f"dkman-app-{installation_id}-data", check=False)
        docker("rm", "--force", name, check=False)
        docker("volume", "rm", state_volume, check=False)
