"""Operator staging is planned by default and never mounts the Docker socket."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/linux/stage_forge_archive.sh"


@pytest.fixture
def staging_args(tmp_path):
    artifact, staging = tmp_path / "artifact", tmp_path / "staging"
    artifact.mkdir()
    staging.mkdir()
    key = tmp_path / "builder.pem"
    key.write_text("public")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    (fakebin / "stat").write_text("#!/bin/sh\nprintf '10001:700\\n'\n")
    (fakebin / "docker").write_text("""#!/bin/bash
printf '%s\\n' "$*" >> "$DKMAN_STAGE_TEST_LOG"
if [[ $1 == ps && "$*" == *"service=hub"* ]]; then printf 'aaaaaaaaaaaa\\n'
elif [[ $1 == ps && "$*" == *"service=deployment-adapter"* ]]; then printf 'bbbbbbbbbbbb\\n'
elif [[ $1 == inspect && "$3" == '{{.Image}}' ]]; then printf 'sha256:%064d\\n' 0
elif [[ $1 == inspect ]]; then printf '%s\\n' "$DKMAN_STAGE_TEST_ROOT"
fi
""")
    for path in fakebin.iterdir():
        path.chmod(0o755)
    log = tmp_path / "docker.log"
    env = {
        **os.environ,
        "PATH": f"{fakebin}:/usr/bin:/bin",
        "DKMAN_STAGE_TEST_ROOT": str(staging),
        "DKMAN_STAGE_TEST_LOG": str(log),
    }
    args = [
        str(SCRIPT),
        "--artifact-dir",
        str(artifact),
        "--root",
        str(staging),
        "--builder-public-key",
        str(key),
    ]
    return args, env, log, artifact


def run(args, env):
    return subprocess.run(args, env=env, text=True, capture_output=True, timeout=10)


def test_dry_run_and_confirmation_do_not_start_helper(staging_args):
    args, env, log, _ = staging_args
    planned = run(args, env)
    assert planned.returncode == 0 and "Dry-run only" in planned.stdout
    assert "run " not in log.read_text()
    log.unlink()
    assert run([*args, "--apply"], env).returncode == 2
    assert not log.exists()


def test_apply_is_restricted_to_expected_adapter_and_has_no_socket(staging_args):
    args, env, log, _ = staging_args
    result = run([*args, "--apply", "--confirm", "STAGE_FORGE_ARCHIVE"], env)
    assert result.returncode == 0, result.stderr
    command = log.read_text().splitlines()[-1]
    assert command.startswith("run --rm -i")
    assert "--network container:aaaaaaaaaaaa" in command
    assert "--user 10001:10001" in command and "--read-only" in command
    assert "/var/run/docker.sock" not in command


def test_rejects_symlink_before_contacting_docker(staging_args, tmp_path):
    args, env, log, artifact = staging_args
    link = tmp_path / "link"
    link.symlink_to(artifact, target_is_directory=True)
    args[2] = str(link)
    assert run(args, env).returncode == 2
    assert not log.exists()
