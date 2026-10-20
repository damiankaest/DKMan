"""The only production module allowed to invoke Docker. No client shell/YAML/env."""

import hashlib
import hmac
import json
import os
import re
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryFile
from typing import Any
from uuid import UUID

from dkman.deployment_adapter.journal import AdapterError
from dkman.deployments.contracts import DeploymentPlan, RuntimeView
from dkman.deployments.redaction import redact_logs


class CommandError(Exception):
    """Command may have reached the engine. Never expose subprocess output."""


def render_compose(plan: DeploymentPlan, credential_key: bytes | None = None) -> dict[str, Any]:
    labels = {"io.dkman.managed": "true", "io.dkman.installation": str(plan.installation_id)}
    service: dict[str, Any] = {
        "image": plan.image,
        "user": plan.user,
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": 128,
        "mem_limit": f"{plan.memory_mb}m",
        "cpus": plan.cpus,
        "tmpfs": ["/tmp:rw,noexec,nosuid,size=32m"],
        "restart": "unless-stopped",
        "labels": {**labels, "io.dkman.plan-hash": plan.plan_hash},
        "networks": ["private"],
        "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
    }
    config: dict[str, Any] = {
        "services": {"app": service},
        "networks": {
            "private": {"name": f"{plan.project}-private", "internal": True, "labels": labels}
        },
    }
    if plan.data_path:
        config["volumes"] = {"data": {"name": f"{plan.project}-data", "labels": labels}}
        service["volumes"] = [{"type": "volume", "source": "data", "target": plan.data_path}]
    if plan.profile == "notes-postgres-v1":
        if credential_key is None or len(credential_key) < 32:
            raise ValueError("Notes credential derivation requires the adapter secret")

        # Domain-separated credentials, stable across restart; never sent to Core/Hub.
        def password(purpose: str) -> str:
            return hmac.new(
                credential_key,
                f"notes-v1:{plan.installation_id}:{purpose}".encode(),
                hashlib.sha256,
            ).hexdigest()

        service["environment"] = {
            "NOTES_INSTALLATION_ID": str(plan.installation_id),
            "NOTES_DB_PASSWORD": password("app"),
        }
        service["networks"] = {
            "private": {},
            "gateway": {"aliases": [f"{plan.project}-web"]},
        }
        service["depends_on"] = {"database": {"condition": "service_healthy"}}
        database = {
            **service,
            "image": plan.database_image,
            "mem_limit": "256m",
            "cpus": 0.5,
            "environment": {
                "POSTGRES_USER": "postgres",
                "POSTGRES_DB": "postgres",
                "PGPASSWORD": password("app"),
                "POSTGRES_PASSWORD": password("admin"),
                "NOTES_DB_PASSWORD": password("app"),
            },
            "networks": ["private"],
            "tmpfs": [
                "/tmp:rw,noexec,nosuid,size=32m",
                "/var/run/postgresql:rw,noexec,nosuid,size=8m,uid=10001,gid=10001,mode=0700",
            ],
            "volumes": [{"type": "volume", "source": "data", "target": "/var/lib/postgresql/data"}],
        }
        del database["depends_on"]
        config["services"]["database"] = database
        config["networks"]["gateway"] = {"external": True, "name": "dkman-app-gateway"}
        config["volumes"] = {"data": {"name": f"{plan.project}-data", "labels": labels}}
    return config


class ComposeProvider:
    def __init__(
        self,
        root: Path,
        operation_id: UUID,
        docker_binary: str = "/usr/local/bin/docker",
        credential_key: bytes | None = None,
    ):
        self.root = root
        self.operation_id = operation_id
        self.binary = docker_binary
        self.credential_key = credential_key

    def run(self, arguments: list[str], timeout: int = 45, *, include_stderr: bool = False) -> str:
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(self.root),
            "DOCKER_CONFIG": str(self.root / "docker-config"),
            "COMPOSE_DISABLE_ENV_FILE": "1",
            "COMPOSE_ANSI": "never",
            "DOCKER_CLI_HINTS": "false",
        }
        with TemporaryFile() as output, TemporaryFile() as errors:
            try:
                process = subprocess.Popen(
                    [self.binary, "--host", "unix:///var/run/docker.sock", *arguments],
                    cwd=self.root,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=output if include_stderr else errors,
                    start_new_session=True,
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise CommandError() from None
                if process.returncode or output.tell() > 262144:
                    raise CommandError()
                output.seek(0)
                return output.read().decode("utf-8", errors="replace")
            except OSError as exc:
                raise CommandError() from exc

    def ready(self) -> None:
        if self.run(["info", "--format", "{{.OSType}}"]).strip() != "linux":
            raise AdapterError("linux_engine_required", 503)
        if not re.fullmatch(
            r"v?[0-9]+\.[0-9]+\.[0-9]+", self.run(["compose", "version", "--short"]).strip()
        ):
            raise AdapterError("compose_unavailable", 503)

    def containers(self, plan: DeploymentPlan) -> list[dict[str, Any]]:
        ids = self.run(
            [
                "ps",
                "--all",
                "--filter",
                f"label=com.docker.compose.project={plan.project}",
                "--format",
                "{{.ID}}",
            ]
        )
        result = []
        for container_id in ids.split():
            if not re.fullmatch(r"[a-f0-9]{12,64}", container_id):
                raise AdapterError("invalid_engine_response", 503)
            item = json.loads(self.run(["container", "inspect", container_id]))[0]
            labels = item.get("Config", {}).get("Labels") or {}
            if (
                labels.get("io.dkman.managed") != "true"
                or labels.get("io.dkman.installation") != str(plan.installation_id)
                or labels.get("com.docker.compose.service")
                not in ({"app", "database"} if plan.profile == "notes-postgres-v1" else {"app"})
            ):
                raise AdapterError("foreign_project")
            result.append(item)
        names = [item["Config"]["Labels"]["com.docker.compose.service"] for item in result]
        if len(names) != len(set(names)):
            raise AdapterError("unexpected_project_resources")
        return sorted(
            result, key=lambda item: item["Config"]["Labels"]["com.docker.compose.service"]
        )

    def resource_exists(self, kind: str, name: str, plan: DeploymentPlan) -> bool:
        ids = self.run([kind, "ls", "--filter", f"name=^{name}$", "--format", "{{.Name}}"])
        if not ids.strip():
            return False
        if ids.strip() != name:
            raise AdapterError("unexpected_project_resources")
        resource = json.loads(self.run([kind, "inspect", name]))[0]
        labels = resource.get("Labels") or {}
        if labels.get("io.dkman.managed") != "true" or labels.get("io.dkman.installation") != str(
            plan.installation_id
        ):
            raise AdapterError("foreign_project")
        return True

    def preflight(self, plan: DeploymentPlan, known: bool) -> None:
        found = bool(self.containers(plan))
        found |= self.resource_exists("network", f"{plan.project}-private", plan)
        found |= self.resource_exists("volume", f"{plan.project}-data", plan)
        if found and not known:
            raise AdapterError("unregistered_project_collision")
        if plan.profile == "notes-postgres-v1":
            network = json.loads(self.run(["network", "inspect", "dkman-app-gateway"]))[0]
            if (
                not network.get("Internal")
                or (network.get("Labels") or {}).get("io.dkman.gateway") != "true"
            ):
                raise AdapterError("untrusted_app_gateway")

    def compose(self, plan: DeploymentPlan, arguments: list[str]) -> str:
        path = self.root / "plans" / f"{self.operation_id}.json"
        raw = json.dumps(render_compose(plan, self.credential_key), sort_keys=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            if path.is_symlink() or path.read_text() != raw:
                raise AdapterError("compose_plan_conflict") from None
        else:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(raw)
        return self.run(
            [
                "compose",
                "--project-name",
                plan.project,
                "--project-directory",
                str(self.root),
                "--env-file",
                "/dev/null",
                "--file",
                str(path),
                *arguments,
            ],
            timeout=90,
        )

    def verify_image(self, plan: DeploymentPlan) -> None:
        self.verify_reference(plan.image, plan.user, plan.data_path)
        if plan.database_image:
            self.verify_reference(plan.database_image, plan.user, "/var/lib/postgresql/data")
        if plan.profile == "notes-postgres-v1":
            for reference in [plan.image, plan.database_image]:
                assert reference is not None
                image = json.loads(self.run(["image", "inspect", reference]))[0]
                if (image["Config"].get("Labels") or {}).get(
                    "io.dkman.source-sha256"
                ) != plan.source_hash:
                    raise AdapterError("reviewed_source_mismatch")

    def verify_reference(self, reference: str, user: str, data_path: str | None) -> None:
        image = json.loads(self.run(["image", "inspect", reference]))[0]
        config = image.get("Config") or {}
        volumes = set((config.get("Volumes") or {}).keys())
        if (
            config.get("User") != user
            or not config.get("Healthcheck", {}).get("Test")
            or config["Healthcheck"]["Test"][0] != "CMD"
            or not volumes.issubset({data_path} if data_path else set())
        ):
            raise AdapterError("curated_image_contract_mismatch")
        if reference.startswith("sha256:") and image["Id"] != reference:
            raise AdapterError("image_digest_mismatch")
        if "@sha256:" in reference and reference not in image.get("RepoDigests", []):
            raise AdapterError("image_digest_mismatch")

    def discover(self, plan: DeploymentPlan) -> RuntimeView:
        return self.status(plan)

    def pull(self, plan: DeploymentPlan) -> None:
        for reference in [plan.image, plan.database_image]:
            if reference and not reference.startswith("sha256:"):
                self.run(["image", "pull", reference], timeout=90)
        self.verify_image(plan)

    def install(self, plan: DeploymentPlan) -> RuntimeView:
        if self.containers(plan):
            raise AdapterError("installation_already_exists")
        return self.deploy(plan)

    def deploy(self, plan: DeploymentPlan) -> RuntimeView:
        self.pull(plan)
        self.compose(
            plan,
            ["up", "--detach", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "30"],
        )
        return self.status(plan)

    def require_workload(self, plan: DeploymentPlan) -> None:
        expected = 2 if plan.profile == "notes-postgres-v1" else 1
        if len(self.containers(plan)) != expected:
            raise AdapterError("installation_incomplete")

    def wait_running(self, plan: DeploymentPlan) -> RuntimeView:
        deadline = time.monotonic() + 30
        while True:
            result = self.status(plan)
            if result.state == "running":
                return result
            if time.monotonic() >= deadline:
                raise CommandError("Runtime did not become healthy")
            time.sleep(0.5)

    def start(self, plan: DeploymentPlan) -> RuntimeView:
        self.require_workload(plan)
        self.verify_image(plan)
        # Start existing containers only; never create/recreate a missing sidecar.
        self.compose(plan, ["start", "--wait", "--wait-timeout", "30"])
        return self.wait_running(plan)

    def stop(self, plan: DeploymentPlan) -> RuntimeView:
        self.require_workload(plan)
        self.compose(plan, ["stop", "--timeout", "10"])
        result = self.status(plan)
        if result.state != "stopped":
            raise CommandError("Runtime did not stop")
        return result

    def restart(self, plan: DeploymentPlan) -> RuntimeView:
        self.require_workload(plan)
        self.compose(plan, ["restart", "--timeout", "10"])
        return self.wait_running(plan)

    def status(self, plan: DeploymentPlan) -> RuntimeView:
        containers = self.containers(plan)
        state: Any = "absent"
        identifier = None
        if containers:
            item = containers[0]  # Sorted: app first, database second.
            identifier = item["Id"]
            runtime = item.get("State") or {}
            if runtime.get("Status") in {"exited", "dead", "created"}:
                state = "stopped"
            elif runtime.get("Status") == "running":
                state = {
                    "healthy": "running",
                    "starting": "starting",
                    "unhealthy": "unhealthy",
                }.get(runtime.get("Health", {}).get("Status"), "unknown")
            else:
                state = "unknown"
            if state == "stopped" and plan.profile == "notes-postgres-v1":
                if len(containers) != 2 or containers[1].get("State", {}).get("Status") not in {
                    "exited",
                    "dead",
                    "created",
                }:
                    state = "unknown"
            if state == "running" and plan.profile == "notes-postgres-v1":
                if len(containers) != 2:
                    state = "unhealthy"
                elif containers[1].get("State", {}).get("Health", {}).get("Status") != "healthy":
                    state = "unhealthy"
        return RuntimeView(
            installation_id=plan.installation_id,
            state=state,
            observed_at=datetime.now(UTC),
            container_id=identifier,
        )

    def logs(self, plan: DeploymentPlan) -> str:
        containers = self.containers(plan)
        if not containers:
            raise AdapterError("installation_absent")
        return redact_logs(
            self.run(
                ["container", "logs", "--tail", "100", containers[0]["Id"]], include_stderr=True
            )
        )

    def remove(self, plan: DeploymentPlan) -> RuntimeView:
        self.compose(plan, ["down", "--timeout", "10"])
        return self.status(plan)

    def remove_data(self, plan: DeploymentPlan) -> None:
        if self.containers(plan):
            raise AdapterError("remove_workload_before_deleting_data")
        name = f"{plan.project}-data"
        if self.resource_exists("volume", name, plan):
            self.run(["volume", "rm", name])
