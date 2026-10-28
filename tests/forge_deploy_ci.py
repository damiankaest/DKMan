"""Disposable CI probe for the real Forge install through the existing adapter."""

import json
import os
import shutil
import subprocess
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from dkman.deployment_adapter.forge_staging import stage_archive
from dkman.deployment_adapter.journal import migrate
from dkman.deployment_adapter.main import AdapterSettings, create_app
from dkman.deployments.auth import sign_delegation
from dkman.deployments.contracts import (
    DeploymentCommand,
    DeploymentPlan,
    ForgeReleaseProof,
    InstallationContext,
)


def exercise_forge_install(root, archive, source, registered, signed, builder, preview_key, proof):
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") == "1"
    docker = shutil.which("docker")
    assert docker is not None

    def command(*args, check=True):
        result = subprocess.run([docker, *args], capture_output=True, text=True, timeout=180)
        if check and result.returncode:
            raise AssertionError(f"Docker {args[:2]} failed: {result.stderr[-4000:]}")
        return result

    assert command("network", "inspect", "dkman-app-gateway", check=False).returncode != 0
    staging = root / "stage"
    staging.mkdir(mode=0o700)
    stage_archive(signed, lambda: (source, registered), builder.public_key(), archive, staging)
    state = root / "adapter"
    migrate(state)
    secret = root / "delegation-key"
    secret.write_bytes(b"ci-only-forge-delegation-key-with-more-than-32-bytes")
    catalog = root / "catalog.json"
    catalog.write_text('{"schema_version":1,"images":[]}')
    for name, key in [("builder", builder.public_key()), ("preview", preview_key.public_key())]:
        (root / f"{name}.pem").write_bytes(
            key.public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
    settings = AdapterSettings(
        state_root=state,
        catalog_file=catalog,
        secret_file=secret,
        docker_binary=docker,
        forge_builder_public_key_file=root / "builder.pem",
        forge_preview_public_key_file=root / "preview.pem",
        forge_staging_root=staging,
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
            household_id=uuid4(), subject="ci-admin", manifest_id=uuid4(), manifest_hash="a" * 64
        ),
        forge=ForgeReleaseProof(build=signed, preview=proof),
    )
    operation = uuid4()
    gateway_owner = uuid4().hex
    grant = sign_delegation(
        secret=secret.read_bytes(),
        subject="ci-admin",
        roles=["admin"],
        operation_id=operation,
        action="install",
        resource_id=plan.installation_id,
        plan_hash=plan.plan_hash,
        approval_id=uuid4(),
        approval_expires_at=datetime.now(UTC) + timedelta(minutes=3),
    )
    try:
        command(
            "network",
            "create",
            "--internal",
            "--label",
            "io.dkman.gateway=true",
            "--label",
            "io.dkman.managed=true",
            "--label",
            f"io.dkman.ci-test={gateway_owner}",
            "dkman-app-gateway",
        )
        app = create_app(settings)
        with TestClient(app) as client:
            response = client.post(
                f"/v1/operations/{operation}",
                headers={"Authorization": "Bearer " + grant},
                json=DeploymentCommand(action="install", plan=plan).model_dump(mode="json"),
            )
            assert response.status_code == 200, response.text
            outcome = response.json()
            if outcome["state"] != "succeeded":
                found = command(
                    "ps",
                    "--all",
                    "--filter",
                    f"label=io.dkman.installation={plan.installation_id}",
                    "--format",
                    "{{.ID}}",
                    check=False,
                ).stdout.split()
                for container in found:
                    diagnostic = command("container", "inspect", container, check=False)
                    print("Disposable Forge container:", diagnostic.stdout[-10000:])
                    logs = command("container", "logs", "--tail", "40", container, check=False)
                    print("Disposable Forge logs:", logs.stdout[-5000:], logs.stderr[-5000:])
            assert outcome["state"] == "succeeded", outcome
            assert outcome["completion"]["receipt"]["plan_hash"] == plan.plan_hash
            container = outcome["runtime"]["container_id"]
            inspected = json.loads(command("container", "inspect", container).stdout)[0]
            assert inspected["Image"] == plan.image and inspected["Config"]["User"] == "101"
            assert inspected["HostConfig"]["ReadonlyRootfs"] and not inspected["HostConfig"].get(
                "PortBindings"
            )
            assert not any(mount["Type"] in {"bind", "volume"} for mount in inspected["Mounts"])
            address = inspected["NetworkSettings"]["Networks"][f"{plan.project}-private"][
                "IPAddress"
            ]
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://{address}:8080/health/ready", timeout=5) as response:
                assert json.load(response) == {"status": "healthy"}
    finally:
        resources = command(
            "ps",
            "--all",
            "--filter",
            f"label=io.dkman.installation={plan.installation_id}",
            "--format",
            "{{.ID}}",
            check=False,
        ).stdout.split()
        for container in resources:
            details = json.loads(command("container", "inspect", container).stdout)[0]
            assert details["Config"]["Labels"].get("io.dkman.installation") == str(
                plan.installation_id
            )
            command("container", "rm", "--force", container)
        private_network = f"{plan.project}-private"
        if command("network", "inspect", private_network, check=False).returncode == 0:
            details = json.loads(command("network", "inspect", private_network).stdout)[0]
            assert details["Labels"].get("io.dkman.installation") == str(plan.installation_id)
            command("network", "rm", private_network)
        gateway = command("network", "inspect", "dkman-app-gateway", check=False)
        if gateway.returncode == 0:
            details = json.loads(gateway.stdout)[0]
            assert details["Labels"].get("io.dkman.ci-test") == gateway_owner
            command("network", "rm", "dkman-app-gateway")
