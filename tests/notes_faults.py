"""Bounded fault injection into disposable CI containers only; never print raw engine output."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]


def inject(action: str, installation: UUID, operation: UUID | None = None) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") != "1"
    ):
        raise ValueError("Disposable CI required")

    def docker(*args: str) -> str:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise ValueError("Disposable fault command failed (output withheld)")
        return result.stdout.strip()

    def service(name: str) -> str:
        ids = docker(
            "ps",
            "-aq",
            "--filter",
            "label=com.docker.compose.project=dkman",
            "--filter",
            f"label=com.docker.compose.service={name}",
        ).split()
        assert len(ids) == 1
        item = json.loads(docker("inspect", ids[0]))[0]
        assert item["Config"]["Labels"]["io.dkman.managed"] == "true"
        return item["Id"]

    def database() -> str:
        ids = docker(
            "ps",
            "-aq",
            "--filter",
            f"label=io.dkman.installation={installation}",
            "--filter",
            "label=com.docker.compose.service=database",
        ).split()
        assert len(ids) == 1
        return ids[0]

    def wait_healthy(identifier: str) -> None:
        for _ in range(100):
            item = json.loads(docker("inspect", identifier))[0]
            if (
                item["State"]["Status"] == "running"
                and item["State"].get("Health", {}).get("Status") == "healthy"
            ):
                return
            time.sleep(0.3)
        raise ValueError("Disposable service did not recover")

    if action in {"before_receipt", "after_receipt"}:
        assert operation is not None
        adapter = service("deployment-adapter")
        # No production fault switch. The separately mounted test entrypoint consumes this once.
        raw = json.dumps({"stage": action, "operation_id": str(operation)})
        docker(
            "exec",
            adapter,
            "python",
            "-c",
            "import pathlib,sys; pathlib.Path('/tmp/dkman-ci-fault.json').write_text(sys.argv[1])",
            raw,
        )
    elif action == "adapter-ready":
        wait_healthy(service("deployment-adapter"))
        ids = docker("ps", "-aq", "--filter", f"label=io.dkman.installation={installation}").split()
        assert len(ids) == 2
        for identifier in ids:
            wait_healthy(identifier)
    else:
        identifier = database() if action.startswith("notes-db-") else service("postgres")
        if action.endswith("stop"):
            docker("stop", "--time", "10", identifier)
        else:
            docker("start", identifier)
            wait_healthy(identifier)
    path = ROOT / ".local/notes-faults.json"
    history = json.loads(path.read_text()) if path.exists() else []
    history.append(
        {
            "action": action,
            "installation_id": str(installation),
            "operation_id": str(operation) if operation else None,
        }
    )
    path.write_text(json.dumps(history, indent=2) + "\n")
    print(f"PASS: disposable fault step {action}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=[
            "notes-db-stop",
            "notes-db-start",
            "core-db-stop",
            "core-db-start",
            "before_receipt",
            "after_receipt",
            "adapter-ready",
        ],
    )
    parser.add_argument("installation", type=UUID)
    parser.add_argument("operation", type=UUID, nargs="?")
    args = parser.parse_args()
    inject(args.action, args.installation, args.operation)
