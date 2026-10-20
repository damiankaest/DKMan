"""Sanitized failure output restricted to this disposable job's managed containers."""

import json
import os
import re
import subprocess

from dkman.deployment_adapter.compose import redact_logs

if __name__ == "__main__":
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") != "1"
    ):
        raise ValueError("Disposable CI required")
    ids = subprocess.check_output(
        ["docker", "ps", "-aq", "--filter", "label=io.dkman.managed=true"], text=True
    ).split()
    for identifier in ids:
        item = json.loads(subprocess.check_output(["docker", "inspect", identifier], text=True))[0]
        service = (item["Config"].get("Labels") or {}).get("com.docker.compose.service")
        if service not in {"app", "database", "core", "deployment-adapter"}:
            continue
        result = subprocess.run(
            ["docker", "logs", "--tail", "30", identifier],
            capture_output=True,
            text=True,
            timeout=10,
        )
        print(f"Managed CI service: {service}")
        output = result.stdout + result.stderr
        for entry in item["Config"].get("Env") or []:
            name, _, value = entry.partition("=")
            if len(value) >= 6 and re.search("PASSWORD|TOKEN|SECRET|KEY", name):
                output = output.replace(value, "[REDACTED]")
        print(redact_logs(output))
