import hashlib
import json
import tarfile
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_forge_build_worker import build_input, sample_oci

from dkman.deployment_adapter import forge_preview
from dkman.deployment_adapter.compose import CommandError
from dkman.deployment_adapter.forge_preview import PreviewError, cleanup_preview, start_preview
from dkman.forge.attestation import (
    BuildEvidence,
    SignedPreviewEvidence,
    sign_evidence,
    verify_preview_signature,
)
from dkman.forge.build_recipe import (
    CHECK_LOCK,
    checks_dockerfile,
    expected_checks,
    image_dockerfile,
)
from dkman.forge.oci import inspect_oci_archive, sha256_file
from dkman.forge_api import BuildArtifactView
from dkman.jobs import digest
from dkman.models import utcnow


class FakeDocker:
    def __init__(self, image, user="101"):
        self.image = image
        self.user = user
        self.environment = []
        self.calls = []
        self.preview_id = None
        self.container = None
        self.network = None

    def run(self, args, timeout=45):
        self.calls.append(args)
        if args[:2] == ["info", "--format"]:
            return "linux"
        if args[:2] == ["version", "--format"]:
            return "28.0.0"
        if args[:2] == ["ps", "--all"]:
            if "label=io.dkman.preview=true" in args:
                return "" if self.container is None else self.container
            return self.container or ""
        if args[:2] == ["image", "load"]:
            with tarfile.open(args[-1]) as archive:
                manifest = json.load(archive.extractfile("manifest.json"))
                assert manifest[0]["RepoTags"] == []
            return "loaded"
        if args[:2] == ["image", "inspect"]:
            return json.dumps([{"Id": self.image, "Config": {"User": self.user, "Volumes": None}}])
        if args[:2] == ["network", "create"]:
            self.network = args[-1]
            self.preview_id = self.network.removeprefix("dkman-preview-")
            return "network"
        if args[:2] == ["container", "run"]:
            self.container = "c" * 64
            self.environment = [
                args[index + 1] for index, value in enumerate(args) if value == "--env"
            ]
            return self.container
        if args[:2] == ["container", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": self.container,
                        "Image": self.image,
                        "Config": {
                            "User": self.user,
                            "Env": self.environment,
                            "Labels": {"io.dkman.preview-id": self.preview_id},
                        },
                        "State": {"Status": "running"},
                        "HostConfig": {
                            "ReadonlyRootfs": True,
                            "Privileged": False,
                            "NetworkMode": self.network,
                            "CapDrop": ["ALL"],
                            "Memory": 256 * 1024 * 1024,
                            "NanoCpus": 500_000_000,
                            "PidsLimit": 128,
                            "Binds": None,
                        },
                        "Mounts": [],
                    }
                ]
            )
        if args[:2] == ["container", "port"]:
            return "127.0.0.1:43210"
        if args[:2] == ["container", "exec"]:
            return "migrated"
        if args[:2] == ["container", "rm"]:
            self.container = None
            return "removed"
        if args[:2] == ["network", "ls"]:
            return self.network or ""
        if args[:2] == ["network", "inspect"]:
            return json.dumps(
                [{"Internal": True, "Labels": {"io.dkman.preview-id": self.preview_id}}]
            )
        if args[:2] == ["network", "rm"]:
            self.network = None
            return "removed"
        raise AssertionError(args)


@pytest.fixture
def setup_preview(tmp_path, monkeypatch, request):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    archive = root / "image.oci.tar"
    sample_oci(archive)
    info = inspect_oci_archive(archive)
    kind = getattr(request, "param", "react-spa")
    source = build_input(kind)
    bundle = source.bundle
    builder = Ed25519PrivateKey.generate()
    preview = Ed25519PrivateKey.generate()
    evidence = BuildEvidence(
        build_id=uuid4(),
        workspace_id=source.workspace_id,
        source_hash=source.bundle_hash,
        plan_hash=bundle.request.content_hash,
        template=bundle.request.template,
        checks=expected_checks(bundle.request.template),
        manifest_digest=info.manifest_digest,
        config_digest=info.config_digest,
        archive_sha256=info.archive_sha256,
        archive_size=info.archive_size,
        check_recipe_sha256=hashlib.sha256(
            checks_dockerfile(bundle.request.template).encode()
        ).hexdigest(),
        check_requirements_sha256=sha256_file(CHECK_LOCK),
        image_recipe_sha256=hashlib.sha256(image_dockerfile(bundle).encode()).hexdigest(),
        finished_at=utcnow(),
    )
    signed = sign_evidence(evidence, builder)
    registered = BuildArtifactView(
        id=str(evidence.build_id),
        workspace_id=source.workspace_id,
        created_at=utcnow(),
        submitted_by="alice",
        key_id=signed.key_id,
        evidence_hash=digest(signed.model_dump(mode="json")),
        evidence=evidence,
    )

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, _):
            return b'{"status":"healthy"}'

    class Opener:
        def open(self, url, timeout):
            assert url == "http://127.0.0.1:43210/health/ready" and timeout == 2
            return Response()

    monkeypatch.setattr(forge_preview.urllib.request, "build_opener", lambda *_: Opener())
    docker = FakeDocker(info.config_digest, "101" if kind == "react-spa" else "10001:10001")
    return root, archive, source, registered, signed, builder, preview, docker


def test_preview_checks_build_and_cleans_only_its_resources(setup_preview):
    root, archive, source, registered, signed, builder, preview, docker = setup_preview
    ready = []
    report = start_preview(
        signed,
        lambda: (source, registered),
        builder.public_key(),
        preview,
        archive,
        root,
        docker,
        ttl_seconds=60,
        on_ready=lambda url, path: ready.append((url, path)),
        hold=lambda _: None,
    )
    assert report["state"] == "stopped" and docker.container is None and docker.network is None
    assert ready[0][0] == "http://127.0.0.1:43210"
    proof = SignedPreviewEvidence.model_validate_json(ready[0][1].read_text())
    verify_preview_signature(proof, preview.public_key())
    assert proof.evidence.artifact_evidence_hash == registered.evidence_hash
    assert proof.evidence.expires_at - proof.evidence.observed_at == timedelta(seconds=60)
    run = next(args for args in docker.calls if args[:2] == ["container", "run"])
    assert "127.0.0.1::8080" in run and "--read-only" in run and "--cap-drop" in run
    assert "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777" in run
    assert "--privileged" not in run and "--mount" not in run
    load = next(args for args in docker.calls if args[:2] == ["image", "load"])
    assert Path(load[-1]).name == "docker-load.tar" and not Path(load[-1]).exists()


def test_preview_rejects_changed_archive_before_docker(setup_preview):
    root, archive, source, registered, signed, builder, preview, docker = setup_preview
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(PreviewError, match="archive_does_not_match"):
        start_preview(
            signed,
            lambda: (source, registered),
            builder.public_key(),
            preview,
            archive,
            root,
            docker,
        )
    assert docker.calls == []


def test_preview_rejects_older_docker_before_loading_an_image(setup_preview):
    root, archive, source, registered, signed, builder, preview, docker = setup_preview
    run = docker.run

    def old_engine(args, timeout=45):
        return "27.5.1" if args[:2] == ["version", "--format"] else run(args, timeout=timeout)

    docker.run = old_engine
    with pytest.raises(PreviewError, match="docker_28_or_newer_required"):
        start_preview(
            signed,
            lambda: (source, registered),
            builder.public_key(),
            preview,
            archive,
            root,
            docker,
        )
    assert not any(args[:2] == ["image", "load"] for args in docker.calls)


def test_preview_cleans_up_when_authorization_changes(setup_preview):
    root, archive, source, registered, signed, builder, preview, docker = setup_preview
    calls = 0

    def authorize():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PreviewError("authorization_revoked")
        return source, registered

    with pytest.raises(PreviewError, match="authorization_revoked"):
        start_preview(signed, authorize, builder.public_key(), preview, archive, root, docker)
    assert docker.container is None and docker.network is None
    assert not list(root.glob("*/preview-attestation.json"))


def test_cleanup_refuses_a_network_without_the_correct_label(setup_preview):
    _, _, _, _, _, _, _, docker = setup_preview
    identifier = uuid4()
    docker.network = f"dkman-preview-{identifier}"
    docker.preview_id = str(uuid4())
    with pytest.raises(PreviewError, match="foreign_preview_network"):
        cleanup_preview(docker, identifier)
    assert docker.network is not None


def test_only_one_preview_can_run_in_a_shared_adapter_root(setup_preview):
    root, archive, source, registered, signed, builder, preview, docker = setup_preview
    with forge_preview.preview_lock(root):
        with pytest.raises(PreviewError, match="preview_adapter_busy"):
            start_preview(
                signed,
                lambda: (source, registered),
                builder.public_key(),
                preview,
                archive,
                root,
                docker,
            )
    assert docker.calls == []


@pytest.mark.parametrize("setup_preview", ["python-api", "fullstack-fastapi-react"], indirect=True)
def test_api_previews_migrate_only_an_ephemeral_database(setup_preview):
    root, archive, source, registered, signed, builder, preview, docker = setup_preview
    report = start_preview(
        signed, lambda: (source, registered), builder.public_key(), preview, archive, root, docker
    )
    assert report["state"] == "stopped"
    run = next(args for args in docker.calls if args[:2] == ["container", "run"])
    assert "DATABASE_URL=sqlite:////tmp/dkman-preview.sqlite3" in run
    migration = next(args for args in docker.calls if args[:2] == ["container", "exec"])
    assert migration[2:] == [
        "--user",
        "10001:10001",
        "c" * 64,
        "/usr/local/bin/alembic",
        "-c",
        "/app/alembic.ini",
        "upgrade",
        "head",
    ]
    assert docker.container is None and docker.network is None


@pytest.mark.parametrize("setup_preview", ["python-api"], indirect=True)
def test_failed_preview_migration_cleans_up_without_signing(setup_preview):
    root, archive, source, registered, signed, builder, preview, docker = setup_preview
    run = docker.run

    def fail_migration(args, timeout=45):
        if args[:2] == ["container", "exec"]:
            raise CommandError()
        return run(args, timeout=timeout)

    docker.run = fail_migration
    with pytest.raises(PreviewError, match="preview_failed"):
        start_preview(
            signed,
            lambda: (source, registered),
            builder.public_key(),
            preview,
            archive,
            root,
            docker,
        )
    assert docker.container is None and docker.network is None
    assert not list(root.glob("*/preview-attestation.json"))
