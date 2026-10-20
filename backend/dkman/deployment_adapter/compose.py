"""The only production module allowed to invoke Docker. No client shell/YAML/env."""

import json
import os
import re
import signal
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryFile
from typing import Any
from uuid import UUID

from dkman.deployment_adapter.journal import AdapterError
from dkman.deployments.contracts import DeploymentPlan, RuntimeView


class CommandError(Exception):
    """Command may have reached the engine. Never expose subprocess output."""


def render_compose(plan: DeploymentPlan) -> dict[str, Any]:
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
    return config


def redact_logs(value: str) -> str:
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    value = "".join(c for c in value if c in "\n\t" or ord(c) >= 32)
    value = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s]+", r"\1[REDACTED]", value)
    value = re.sub(
        r"(?i)((?:password|secret|token|api[_-]?key)\s*[:=]\s*)"
        r"(\"[^\"]*\"|'[^']*'|[^\s]+)",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@", r"\1[REDACTED]@", value)
    value = re.sub(
        r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "[REDACTED]", value
    )
    return value[:8192]


class ComposeProvider:
    def __init__(
        self, root: Path, operation_id: UUID, docker_binary: str = "/usr/local/bin/docker"
    ):
        self.root = root
        self.operation_id = operation_id
        self.binary = docker_binary

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
                or labels.get("com.docker.compose.service") != "app"
            ):
                raise AdapterError("foreign_project")
            result.append(item)
        if len(result) > 1:
            raise AdapterError("unexpected_project_resources")
        return result

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

    def compose(self, plan: DeploymentPlan, arguments: list[str]) -> str:
        path = self.root / "plans" / f"{self.operation_id}.json"
        raw = json.dumps(render_compose(plan), sort_keys=True)
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
        image = json.loads(self.run(["image", "inspect", plan.image]))[0]
        config = image.get("Config") or {}
        volumes = set((config.get("Volumes") or {}).keys())
        if (
            config.get("User") != plan.user
            or not config.get("Healthcheck", {}).get("Test")
            or config["Healthcheck"]["Test"][0] != "CMD"
            or not volumes.issubset({plan.data_path} if plan.data_path else set())
        ):
            raise AdapterError("curated_image_contract_mismatch")
        if plan.image.startswith("sha256:") and image["Id"] != plan.image:
            raise AdapterError("image_digest_mismatch")
        if "@sha256:" in plan.image and plan.image not in image.get("RepoDigests", []):
            raise AdapterError("image_digest_mismatch")

    def discover(self, plan: DeploymentPlan) -> RuntimeView:
        return self.status(plan)

    def pull(self, plan: DeploymentPlan) -> None:
        if not plan.image.startswith("sha256:"):
            self.run(["image", "pull", plan.image], timeout=90)
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

    def start(self, plan: DeploymentPlan) -> RuntimeView:
        if not self.containers(plan):
            raise AdapterError("installation_absent")
        self.verify_image(plan)
        self.compose(
            plan,
            [
                "up",
                "--detach",
                "--no-build",
                "--no-recreate",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "30",
            ],
        )
        return self.status(plan)

    def stop(self, plan: DeploymentPlan) -> RuntimeView:
        self.compose(plan, ["stop", "--timeout", "10", "app"])
        return self.status(plan)

    def restart(self, plan: DeploymentPlan) -> RuntimeView:
        if not self.containers(plan):
            raise AdapterError("installation_absent")
        self.compose(plan, ["restart", "--timeout", "10", "app"])
        return self.status(plan)

    def status(self, plan: DeploymentPlan) -> RuntimeView:
        containers = self.containers(plan)
        state: Any = "absent"
        identifier = None
        if containers:
            item = containers[0]
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
