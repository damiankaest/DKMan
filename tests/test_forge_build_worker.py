import hashlib
import io
import json
import os
import tarfile
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dkman.forge import build_worker
from dkman.forge.attestation import SignedBuildEvidence, verify_signature
from dkman.forge.build_recipe import image_dockerfile
from dkman.forge.build_worker import BuildFailure, execute_build, validate_input
from dkman.forge.oci import verify_oci_archive
from dkman.forge.templates import TemplateProvider
from dkman.forge.workspace import GenerationRequest
from dkman.forge_api import BuildInput, bundle_hash


def build_input(kind="fullstack-fastapi-react"):
    request = GenerationRequest(
        plan_id=str(uuid4()),
        content_hash="a" * 64,
        template=kind,
        requirements={"title": "Garden", "goal": "Care for plants", "features": ["Photos"]},
    )
    bundle = TemplateProvider().generate(request)
    return BuildInput(workspace_id=str(uuid4()), bundle_hash=bundle_hash(bundle), bundle=bundle)


def sample_oci(path: Path, *, corrupt=False, layer_repetitions=1):
    def descriptor(content, media):
        return {
            "mediaType": media,
            "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }

    config = b'{"architecture":"amd64","os":"linux"}'
    layer = b"sample layer"
    config_desc = descriptor(config, "application/vnd.oci.image.config.v1+json")
    layer_desc = descriptor(layer, "application/vnd.oci.image.layer.v1.tar")
    manifest = json.dumps(
        {"schemaVersion": 2, "config": config_desc, "layers": [layer_desc] * layer_repetitions}
    ).encode()
    manifest_desc = descriptor(manifest, "application/vnd.oci.image.manifest.v1+json")
    index = json.dumps({"schemaVersion": 2, "manifests": [manifest_desc]}).encode()
    contents = {
        "oci-layout": b'{"imageLayoutVersion":"1.0.0"}',
        "index.json": index,
        "blobs/sha256/" + config_desc["digest"][7:]: config,
        "blobs/sha256/" + layer_desc["digest"][7:]: b"invalid data" if corrupt else layer,
        "blobs/sha256/" + manifest_desc["digest"][7:]: manifest,
    }
    with tarfile.open(path, "w") as archive:
        for name, content in contents.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    return manifest_desc["digest"]


@pytest.fixture
def builder(tmp_path, monkeypatch):
    root = tmp_path / "results"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(build_worker, "buildkit_socket", lambda address: address)
    return root, "unix:///isolated/buildkitd.sock"


def test_authorized_source_must_match_exact_template():
    value = build_input()
    validate_input(value)
    value.bundle.files["backend/app/main.py"] += "\nprint('changed')\n"
    value.bundle_hash = bundle_hash(value.bundle)
    with pytest.raises(BuildFailure, match="unsupported_or_changed_template"):
        validate_input(value)


@pytest.mark.parametrize(
    "kind,required_copies",
    [
        ("python-api", ["app ./app", "alembic.ini ./", "migrations ./migrations"]),
        ("react-spa", ["nginx.conf /etc/nginx/conf.d/default.conf"]),
        (
            "fullstack-fastapi-react",
            ["backend/app ./app", "backend/alembic.ini ./", "backend/migrations ./migrations"],
        ),
    ],
)
def test_private_source_files_are_owned_by_the_fixed_runtime_user(kind, required_copies):
    recipe = image_dockerfile(build_input(kind).bundle)
    user = "101:101" if kind == "react-spa" else "10001:10001"
    for copy in required_copies:
        assert f"COPY --chown={user} {copy}" in recipe


@pytest.mark.parametrize(
    "kind,markers",
    [
        ("python-api", ["api-passed"]),
        ("react-spa", ["web-passed"]),
        ("fullstack-fastapi-react", ["api-passed", "web-passed"]),
    ],
)
def test_build_rechecks_authorization_and_persists_verified_evidence(
    builder, monkeypatch, kind, markers
):
    root, address = builder
    source = build_input(kind)
    fetches = []
    calls = []

    def fetch():
        fetches.append(1)
        return source.model_copy(deep=True)

    def run(command, home):
        calls.append(command)
        assert "--no-cache" in command and "docker" not in command[0]
        recipe = (home / "recipe/Dockerfile").read_text()
        assert "RUN --network=none" in recipe or (kind == "python-api" and len(calls) == 2)
        output = command[-1]
        if output.startswith("type=local,dest="):
            target = Path(output.removeprefix("type=local,dest="))
            for marker in markers:
                (target / marker).touch()
        else:
            sample_oci(Path(output.removeprefix("type=oci,dest=")))
        return "ok"

    monkeypatch.setattr(build_worker, "run_command", run)
    signing_key = Ed25519PrivateKey.generate()
    result = execute_build(fetch, root, address, "/usr/bin/buildctl", signing_key)
    assert result["state"] == "succeeded"
    assert result["checks"] == markers
    assert len(fetches) == 4 and len(calls) == 2
    artifact_dir = root / result["build_id"]
    assert result == json.loads((artifact_dir / "build-artifact.json").read_text())
    assert verify_oci_archive(artifact_dir / "image.oci.tar")[0] == result["manifest_digest"]
    signed = SignedBuildEvidence.model_validate_json(
        (artifact_dir / "build-attestation.json").read_text()
    )
    verify_signature(signed, signing_key.public_key())
    assert signed.evidence.archive_sha256 == result["archive_sha256"]
    assert signed.evidence.config_digest == result["config_digest"]
    assert os.stat(artifact_dir / "image.oci.tar").st_mode & 0o077 == 0


def test_failure_is_recorded_without_image_or_secret(builder, monkeypatch):
    root, address = builder
    source = build_input()

    def fail(*_):
        raise BuildFailure("build_command_failed", "test failed\nAuthorization: Bearer very-secret")

    monkeypatch.setattr(build_worker, "run_command", fail)
    result = execute_build(lambda: source, root, address, "/usr/bin/buildctl")
    assert result["state"] == "failed" and result["stage"] == "checks"
    assert result["failure_code"] == "build_command_failed"
    assert "very-secret" not in result["logs"]
    assert not (root / result["build_id"] / "image.oci.tar").exists()


def test_revocation_after_tests_stops_image_build(builder, monkeypatch):
    root, address = builder
    source = build_input("python-api")
    fetches = 0
    commands = []

    def fetch():
        nonlocal fetches
        fetches += 1
        if fetches == 3:
            raise BuildFailure("approved_source_unavailable")
        return source

    def run(command, _home):
        commands.append(command)
        Path(command[-1].removeprefix("type=local,dest=")).joinpath("api-passed").touch()
        return "ok"

    monkeypatch.setattr(build_worker, "run_command", run)
    result = execute_build(fetch, root, address, "/usr/bin/buildctl")
    assert result["state"] == "failed" and result["failure_code"] == "approved_source_unavailable"
    assert len(commands) == 1 and not (root / result["build_id"] / "image.oci.tar").exists()


def test_revocation_after_image_removes_partial_archive(builder, monkeypatch):
    root, address = builder
    source = build_input("python-api")
    fetches = 0

    def fetch():
        nonlocal fetches
        fetches += 1
        if fetches == 4:
            raise BuildFailure("approved_source_unavailable")
        return source

    def run(command, _home):
        output = command[-1]
        if output.startswith("type=local,dest="):
            Path(output.removeprefix("type=local,dest=")).joinpath("api-passed").touch()
        else:
            sample_oci(Path(output.removeprefix("type=oci,dest=")))
        return "ok"

    monkeypatch.setattr(build_worker, "run_command", run)
    result = execute_build(fetch, root, address, "/usr/bin/buildctl")
    artifact_dir = root / result["build_id"]
    assert result["state"] == "failed" and result["manifest_digest"] is None
    assert not (artifact_dir / "image.oci.tar").exists()
    assert not (artifact_dir / "image.oci.partial").exists()


def test_interrupted_worker_leaves_running_report_not_success(builder, monkeypatch):
    root, address = builder
    source = build_input("python-api")

    def interrupted(*_):
        raise KeyboardInterrupt

    monkeypatch.setattr(build_worker, "run_command", interrupted)
    with pytest.raises(KeyboardInterrupt):
        execute_build(lambda: source, root, address, "/usr/bin/buildctl")
    reports = list(root.glob("*/build-artifact.json"))
    assert len(reports) == 1
    result = json.loads(reports[0].read_text())
    assert result["state"] == "running" and result["stage"] == "checks"
    assert result["manifest_digest"] is None


def test_oci_verification_rejects_corrupt_layer(tmp_path):
    path = tmp_path / "image.tar"
    sample_oci(path)
    expected, archive_hash, size = verify_oci_archive(path)
    assert expected.startswith("sha256:") and len(archive_hash) == 64 and size > 0
    sample_oci(path, corrupt=True)
    with pytest.raises(ValueError, match="digest_mismatch"):
        verify_oci_archive(path)


def test_worker_rejects_exposed_or_insecure_inputs(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    root.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        execute_build(lambda: build_input(), root, "unix:///invalid", "/usr/bin/buildctl")
    with pytest.raises(ValueError, match="unix_socket"):
        build_worker.buildkit_socket("tcp://example.com:1234")
    with pytest.raises(ValueError, match="https"):
        build_worker.fetch_input("http://remote.example", str(uuid4()), "token")
