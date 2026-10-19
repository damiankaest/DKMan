import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "local_config", ROOT / "scripts/generate_local_config.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def copy_template(tmp_path):
    folder = tmp_path / "infrastructure/keycloak"
    folder.mkdir(parents=True)
    (folder / "dkman-realm.template.json").write_bytes(
        (ROOT / "infrastructure/keycloak/dkman-realm.template.json").read_bytes()
    )


def test_generated_secrets_are_random_and_idempotent(tmp_path):
    copy_template(tmp_path)
    module.generate(tmp_path, 8080)
    folder = tmp_path / ".local/secrets"
    initial = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert len(set(initial.values())) == 4
    assert all(len(value) > 40 for value in initial.values())
    module.generate(tmp_path, 8080)
    assert initial == {p.name: p.read_bytes() for p in folder.iterdir()}
    realm = json.loads((tmp_path / ".local/keycloak/dkman-realm.json").read_text())
    assert realm["clients"][0]["attributes"]["pkce.code.challenge.method"] == "S256"
    assert realm["users"][0]["credentials"][0]["temporary"] is True
    (folder / "core-db-password").unlink()
    with pytest.raises(ValueError, match="Incomplete existing"):
        module.generate(tmp_path, 8080)


def test_config_does_not_overwrite_or_follow_symlinks(tmp_path):
    copy_template(tmp_path)
    (tmp_path / ".env").write_text("DO_NOT_OVERWRITE=true\n")
    with pytest.raises(ValueError, match="differs"):
        module.generate(tmp_path, 8080)
    assert (tmp_path / ".env").read_text() == "DO_NOT_OVERWRITE=true\n"
    (tmp_path / ".env").unlink()
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    (tmp_path / ".env").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        module.generate(tmp_path, 8080)


def test_scripts_parse_and_bootstrap_defaults_to_dry_run():
    for path in list((ROOT / "scripts/linux").glob("*.sh")) + list(
        (ROOT / "infrastructure").glob("*/*.sh")
    ):
        subprocess.run(["bash", "-n", str(path)], check=True)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/linux/bootstrap.sh")],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Dry-run" in result.stdout


def test_compose_trust_boundary_and_loopback():
    config = yaml.safe_load((ROOT / "infrastructure/compose/compose.yaml").read_text())
    for name, service in config["services"].items():
        assert service["labels"]["io.dkman.managed"] == "true"
        assert not service.get("privileged")
        assert service.get("network_mode") != "host"
        assert "docker.sock" not in json.dumps(service)
        if name != "hub":
            assert "ports" not in service
    assert config["services"]["hub"]["ports"] == ["127.0.0.1:${DKMAN_HTTP_PORT:-8080}:8080"]
    assert config["networks"]["data"]["internal"] is True


@pytest.mark.parametrize(
    "label, list_exit, expected_exit", [("true", 0, 0), ("", 0, 1), ("true", 1, 1)]
)
def test_installer_refuses_foreign_or_uninspectable_project(label, list_exit, expected_exit):
    script = r"""
source scripts/linux/common.sh
docker() {
  case "$1" in
    context) echo test-context ;;
    info) echo 'test-engine / linux' ;;
    ps) echo test-container; return "$MOCK_LIST_EXIT" ;;
    inspect) echo "$MOCK_LABEL" ;;
    *) return 1 ;;
  esac
}
require_own_project
"""
    import os

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "MOCK_LABEL": label, "MOCK_LIST_EXIT": str(list_exit)},
    )
    assert result.returncode == expected_exit
