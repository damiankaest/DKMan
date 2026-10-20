"""Real data persistence and least-privilege probe, only on disposable CI containers."""

import json
import os
import subprocess
import time
from pathlib import Path
from uuid import UUID


def verify(root: Path) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") != "1"
    ):
        raise ValueError("Disposable GitHub runner required")
    installation = str(UUID((root / ".local/notes-installation.txt").read_text().strip()))

    def docker(*args: str, check: bool = True) -> str:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=90)
        if check and result.returncode:
            raise ValueError("Disposable Notes container probe failed (output withheld)")
        return result.stdout.strip()

    identifiers = docker(
        "ps", "--all", "--quiet", "--filter", f"label=io.dkman.installation={installation}"
    ).split()
    assert len(identifiers) == 2
    containers = {
        item["Config"]["Labels"]["com.docker.compose.service"]: item
        for item in json.loads(docker("container", "inspect", *identifiers))
    }
    for item in containers.values():
        assert item["Config"]["User"] == "10001:10001"
        assert item["HostConfig"]["ReadonlyRootfs"] and item["HostConfig"]["CapDrop"] == ["ALL"]
        assert not item["HostConfig"]["Privileged"] and not item["HostConfig"].get("PortBindings")
        assert not any("docker.sock" in mount.get("Source", "") for mount in item["Mounts"])
    app, database = containers["app"]["Id"], containers["database"]["Id"]
    assert len(containers["database"]["NetworkSettings"]["Networks"]) == 1

    def query(sql: str) -> str:
        # Secret stays in the target process; no inspection/printing of environment values.
        return docker(
            "exec",
            database,
            "/bin/bash",
            "-ec",
            'PGPASSWORD="$NOTES_DB_PASSWORD" exec psql -h 127.0.0.1 -U notes_app '
            '-d notes -A -t -v ON_ERROR_STOP=1 -c "$1"',
            "probe",
            sql,
        )

    assert (
        query(
            "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles "
            "WHERE rolname = current_user"
        )
        == "f"
    )
    before = query("SELECT id::text || ':' || text FROM notes ORDER BY id")
    assert "Gemeinsame echte Notes-Probe" in before and "Notiz vom zweiten Nutzer" in before
    forbidden = docker(
        "exec",
        database,
        "/bin/bash",
        "-ec",
        'PGPASSWORD="$NOTES_DB_PASSWORD" psql -h 127.0.0.1 -U notes_app -d postgres -c "SELECT 1"',
        check=False,
    )
    assert not forbidden
    docker("stop", app, database)
    docker("start", database, app)
    for _ in range(100):
        items = json.loads(docker("container", "inspect", app, database))
        if all(item["State"].get("Health", {}).get("Status") == "healthy" for item in items):
            break
        time.sleep(0.5)
    else:
        raise ValueError("Notes did not recover after container restart")
    assert query("SELECT id::text || ':' || text FROM notes ORDER BY id") == before
    print(
        "PASS: actual Notes data unchanged after app/database stop/start; "
        "isolated non-superuser role"
    )


if __name__ == "__main__":
    verify(Path(__file__).resolve().parents[1])
