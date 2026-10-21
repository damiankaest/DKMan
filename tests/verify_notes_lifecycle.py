"""Engine evidence for Hub-driven actions, guarded to disposable CI only. No mutations."""

import argparse
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID


def checkpoint(installation: UUID, phase: str) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") != "1"
    ):
        raise ValueError("Disposable GitHub runner required")

    def docker(*args: str) -> str:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise ValueError("Engine observation unavailable (output withheld)")
        return result.stdout

    ids = docker("ps", "-aq", "--filter", f"label=io.dkman.installation={installation}").split()
    assert len(ids) == 2
    observation = {}
    for item in json.loads(docker("container", "inspect", *ids)):
        labels = item["Config"]["Labels"]
        assert labels["io.dkman.installation"] == str(installation)
        service = labels["com.docker.compose.service"]
        assert service in {"app", "database"}
        observation[service] = {
            "id": item["Id"],
            "image": item["Image"],
            "status": item["State"]["Status"],
            "started_at": item["State"]["StartedAt"],
            "health": item["State"].get("Health", {}).get("Status"),
            "volumes": sorted(
                mount["Name"] for mount in item["Mounts"] if mount["Type"] == "volume"
            ),
        }
    path = Path(__file__).resolve().parents[1] / ".local/notes-lifecycle.json"
    evidence = (
        json.loads(path.read_text()) if path.exists() else {"installation_id": str(installation)}
    )
    assert evidence["installation_id"] == str(installation)
    if phase != "before":
        before = evidence["before"]
        for service, item in observation.items():
            assert item["id"] == before[service]["id"]
            assert item["image"] == before[service]["image"]
            assert item["volumes"] == before[service]["volumes"]
            if phase == "stop":
                assert item["status"] == "exited"
            else:
                assert item["status"] == "running" and item["health"] == "healthy"
                previous_phase = {
                    "restart": "start",
                    "reconciled_restart": "restart",
                    "unproven_restart": "reconciled_restart",
                    "after_reconcile": "unproven_restart",
                }.get(phase, "before")
                previous = evidence[previous_phase]
                if phase == "after_reconcile":
                    assert item["started_at"] == previous[service]["started_at"]
                else:
                    assert item["started_at"] > previous[service]["started_at"]
    evidence[phase] = observation
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"PASS: {phase} actual app/database identity, state and volume evidence")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("installation", type=UUID)
    parser.add_argument(
        "phase",
        choices=[
            "before",
            "stop",
            "start",
            "restart",
            "reconciled_restart",
            "unproven_restart",
            "after_reconcile",
        ],
    )
    args = parser.parse_args()
    checkpoint(args.installation, args.phase)
