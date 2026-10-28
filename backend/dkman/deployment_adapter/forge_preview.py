"""Manual preview adapter for a disposable, isolated Linux Docker host.

This is never called by Core. It accepts only signed Forge SPA builds and creates
no production mounts, credentials, shared networks or non-loopback ports.
"""

import argparse
import fcntl
import ipaddress
import json
import os
import re
import select
import selectors
import socket
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from dkman.deployment_adapter.compose import CommandError, ComposeProvider
from dkman.deployments.client import NoRedirect
from dkman.forge.attestation import (
    PreviewEvidence,
    SignedBuildEvidence,
    key_id,
    read_private_key,
    read_public_key,
    sign_preview,
    verify_recipe,
    verify_signature,
)
from dkman.forge.build_worker import BuildFailure, fetch_input, private_root, validate_input
from dkman.forge.oci import OciInspection, inspect_oci_archive, write_docker_load_archive
from dkman.forge_api import BuildArtifactView, BuildInput
from dkman.jobs import digest

MAX_TTL_SECONDS = 900
PREVIEW_DATABASE_URL = "sqlite:////tmp/dkman-preview.sqlite3"


class PreviewError(Exception):
    pass


def preview_address(item: dict[str, Any], network: str, isolated: dict[str, Any]) -> str:
    """Accept only the container's IPv4 address on its verified internal bridge."""
    try:
        networks = item["NetworkSettings"]["Networks"]
        if set(networks) != {network} or isolated.get("Driver") != "bridge":
            raise ValueError()
        endpoint = networks[network]
        if endpoint["NetworkID"] != isolated["Id"]:
            raise ValueError()
        address = ipaddress.IPv4Address(endpoint["IPAddress"])
        if not address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError()
        for config in isolated["IPAM"]["Config"]:
            subnet = ipaddress.ip_network(config["Subnet"], strict=False)
            if not isinstance(subnet, ipaddress.IPv4Network):
                continue
            gateway = ipaddress.IPv4Address(config["Gateway"])
            if address in subnet and address not in {
                subnet.network_address,
                subnet.broadcast_address,
                gateway,
            }:
                return str(address)
    except (KeyError, TypeError, ValueError):
        pass
    raise PreviewError("invalid_preview_network_address")


class PreviewForwarder:
    """Forward loopback traffic only to a verified preview container's fixed port."""

    def __init__(self, address: str, port: int = 8080):
        slots = threading.BoundedSemaphore(16)

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                try:
                    with socket.create_connection((address, port), timeout=5) as upstream:
                        client = self.request
                        client.settimeout(5)
                        upstream.settimeout(5)
                        with selectors.DefaultSelector() as selector:
                            selector.register(client, selectors.EVENT_READ, upstream)
                            selector.register(upstream, selectors.EVENT_READ, client)
                            while True:
                                ready = selector.select(timeout=5)
                                if not ready:
                                    return
                                for key, _ in ready:
                                    data = cast(socket.socket, key.fileobj).recv(65536)
                                    if not data:
                                        return
                                    key.data.sendall(data)
                except OSError:
                    return

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            block_on_close = False
            request_queue_size = 16

            def process_request(self, request: Any, client_address: Any) -> None:
                if not slots.acquire(blocking=False):
                    self.close_request(request)
                    return
                try:
                    super().process_request(request, client_address)
                except BaseException:
                    slots.release()
                    raise

            def process_request_thread(self, request: Any, client_address: Any) -> None:
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    slots.release()

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        try:
            self.thread.start()
        except BaseException:
            self.server.server_close()
            raise

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@contextmanager
def preview_lock(root: Path) -> Iterator[None]:
    """Serialize preview/cleanup operations on the dedicated adapter host."""
    fd = os.open(root / ".preview.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PreviewError("preview_adapter_busy") from exc
        yield
    finally:
        os.close(fd)


def fetch_artifact(origin: str, artifact_id: UUID, token: str) -> BuildArtifactView:
    # fetch_input validates origin/token before this function is called.
    request = urllib.request.Request(
        origin.rstrip("/") + f"/api/v1/forge/build-artifacts/{artifact_id}",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("artifact_response_too_large")
        return BuildArtifactView.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise PreviewError("registered_artifact_unavailable") from exc


def verify_inputs(
    signed: SignedBuildEvidence,
    source: BuildInput,
    registered: BuildArtifactView,
    public: Ed25519PublicKey,
    archive: Path,
) -> OciInspection:
    bundle = validate_input(source)
    verify_signature(signed, public)
    verify_recipe(signed.evidence, bundle)
    evidence = signed.evidence
    if (
        str(evidence.workspace_id) != source.workspace_id
        or evidence.source_hash != source.bundle_hash
        or registered.id != str(evidence.build_id)
        or registered.workspace_id != source.workspace_id
        or registered.evidence != evidence
        or registered.evidence_hash != digest(signed.model_dump(mode="json"))
    ):
        raise PreviewError("artifact_or_approval_binding_mismatch")
    archive = archive.absolute()
    if archive.name != "image.oci.tar" or archive.resolve(strict=True) != archive:
        raise PreviewError("invalid_archive_path")
    actual = inspect_oci_archive(archive)
    if (
        actual.manifest_digest != evidence.manifest_digest
        or actual.config_digest != evidence.config_digest
        or actual.archive_sha256 != evidence.archive_sha256
        or actual.archive_size != evidence.archive_size
    ):
        raise PreviewError("archive_does_not_match_attestation")
    return actual


def _inspect_object(provider: ComposeProvider, kind: str, resource: str) -> dict[str, Any]:
    value = json.loads(provider.run([kind, "inspect", resource]))
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise PreviewError("invalid_docker_inspect_response")
    return value[0]


def cleanup_preview(provider: ComposeProvider, preview_id: UUID) -> None:
    """Delete only a specifically labelled preview and its own internal network."""
    identifier = str(preview_id)
    names = provider.run(
        [
            "ps",
            "--all",
            "--filter",
            f"label=io.dkman.preview-id={identifier}",
            "--format",
            "{{.ID}}",
        ]
    ).split()
    if len(names) > 1:
        raise PreviewError("unexpected_preview_containers")
    for name in names:
        if not re.fullmatch(r"[a-f0-9]{12,64}", name):
            raise PreviewError("invalid_container_id")
        item = _inspect_object(provider, "container", name)
        labels = item.get("Config", {}).get("Labels") or {}
        if labels.get("io.dkman.preview-id") != identifier:
            raise PreviewError("foreign_preview_container")
        provider.run(["container", "rm", "--force", name], timeout=30)
    network = f"dkman-preview-{identifier}"
    found = provider.run(
        ["network", "ls", "--filter", f"name=^{network}$", "--format", "{{.Name}}"]
    )
    if found.strip():
        if found.strip() != network:
            raise PreviewError("unexpected_preview_network")
        item = _inspect_object(provider, "network", network)
        if (item.get("Labels") or {}).get("io.dkman.preview-id") != identifier:
            raise PreviewError("foreign_preview_network")
        provider.run(["network", "rm", network], timeout=30)


def _start_preview(
    signed: SignedBuildEvidence,
    authorize: Callable[[], tuple[BuildInput, BuildArtifactView]],
    builder_public: Ed25519PublicKey,
    preview_private: Ed25519PrivateKey,
    archive: Path,
    root: Path,
    provider: ComposeProvider,
    *,
    ttl_seconds: int = 300,
    on_ready: Callable[[str, Path], None] | None = None,
    hold: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Run one SPA preview, sign a measured observation, then remove its container/network."""
    root = private_root(root)
    if not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError("invalid_preview_ttl")
    if key_id(builder_public) == key_id(preview_private.public_key()):
        raise ValueError("preview_and_builder_keys_must_differ")
    source, registered = authorize()
    inspected_archive = verify_inputs(signed, source, registered, builder_public, archive)
    if provider.run(["info", "--format", "{{.OSType}}"]).strip() != "linux":
        raise PreviewError("linux_engine_required")
    active = provider.run(
        ["ps", "--all", "--filter", "label=io.dkman.preview=true", "--format", "{{.ID}}"]
    )
    if active.strip():
        raise PreviewError("existing_preview_requires_cleanup")
    preview_id = uuid4()
    report_dir = root / str(preview_id)
    report_dir.mkdir(mode=0o700)
    report = {"preview_id": str(preview_id), "artifact_id": registered.id, "state": "starting"}
    (report_dir / "preview-status.json").write_text(json.dumps(report) + "\n")
    (report_dir / "preview-status.json").chmod(0o600)
    network = f"dkman-preview-{preview_id}"
    needs_database = signed.evidence.template != "react-spa"
    image_user = "10001:10001" if needs_database else "101"
    forwarder = None
    try:
        load_archive = report_dir / "docker-load.tar"
        write_docker_load_archive(archive, load_archive, inspected_archive)
        try:
            provider.run(["image", "load", "--input", str(load_archive)], timeout=300)
        finally:
            load_archive.unlink(missing_ok=True)
        image = _inspect_object(provider, "image", signed.evidence.config_digest)
        config = image.get("Config") or {}
        if (
            image.get("Id") != signed.evidence.config_digest
            or config.get("User") != image_user
            or config.get("Volumes")
        ):
            raise PreviewError("preview_image_contract_mismatch")
        provider.run(
            [
                "network",
                "create",
                "--internal",
                "--label",
                f"io.dkman.preview-id={preview_id}",
                network,
            ]
        )
        isolated_network = _inspect_object(provider, "network", network)
        if isolated_network.get("Internal") is not True or (
            isolated_network.get("Labels") or {}
        ).get("io.dkman.preview-id") != str(preview_id):
            raise PreviewError("preview_network_not_isolated")
        arguments = [
            "container",
            "run",
            "--detach",
            "--name",
            network,
            "--label",
            "io.dkman.preview=true",
            "--label",
            f"io.dkman.preview-id={preview_id}",
            "--network",
            network,
            "--user",
            image_user,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "128",
            "--memory",
            "256m",
            "--cpus",
            "0.5",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
            "--restart",
            "no",
            "--pull",
            "never",
        ]
        if needs_database:
            arguments.extend(["--env", f"DATABASE_URL={PREVIEW_DATABASE_URL}"])
        arguments.append(signed.evidence.config_digest)
        container = provider.run(arguments, timeout=60).strip()
        if not re.fullmatch(r"[a-f0-9]{64}", container):
            raise PreviewError("invalid_preview_container")
        item = _inspect_object(provider, "container", container)
        labels = item.get("Config", {}).get("Labels") or {}
        host = item.get("HostConfig") or {}
        environment = item.get("Config", {}).get("Env") or []
        database_env = [
            value
            for value in environment
            if isinstance(value, str) and value.startswith("DATABASE_URL=")
        ]
        if (
            item.get("Image") != signed.evidence.config_digest
            or labels.get("io.dkman.preview-id") != str(preview_id)
            or item.get("Config", {}).get("User") != image_user
            or database_env != ([f"DATABASE_URL={PREVIEW_DATABASE_URL}"] if needs_database else [])
            or item.get("State", {}).get("Status") != "running"
            or host.get("Privileged") is not False
            or host.get("ReadonlyRootfs") is not True
            or host.get("NetworkMode") != network
            or "ALL" not in (host.get("CapDrop") or [])
            or host.get("Memory") != 256 * 1024 * 1024
            or host.get("NanoCpus") != 500_000_000
            or host.get("PidsLimit") != 128
            or host.get("Binds")
            or host.get("PortBindings")
            or any(
                mount.get("Type") != "tmpfs" or mount.get("Destination") != "/tmp"
                for mount in (item.get("Mounts") or [])
            )
        ):
            raise PreviewError("preview_container_contract_mismatch")
        address = preview_address(item, network, isolated_network)
        if needs_database:
            # The exact reviewed starter migration creates only an ephemeral SQLite DB in tmpfs.
            provider.run(
                [
                    "container",
                    "exec",
                    "--user",
                    image_user,
                    container,
                    "/usr/local/bin/alembic",
                    "-c",
                    "/app/alembic.ini",
                    "upgrade",
                    "head",
                ],
                timeout=60,
            )
        forwarder = PreviewForwarder(address)
        origin = forwarder.origin
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.build_opener(
                    urllib.request.ProxyHandler({}), NoRedirect()
                ).open(origin + "/health/ready", timeout=2) as response:
                    data = json.loads(response.read(4097))
                    if response.status != 200 or data != {"status": "healthy"}:
                        raise ValueError("preview_health_invalid")
                break
            except (OSError, ValueError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise PreviewError("preview_health_unavailable") from None
                time.sleep(0.5)
        current_source, current_artifact = authorize()
        verify_inputs(signed, current_source, current_artifact, builder_public, archive)
        now = datetime.now(UTC)
        evidence = PreviewEvidence(
            preview_id=preview_id,
            artifact_id=signed.evidence.build_id,
            workspace_id=signed.evidence.workspace_id,
            artifact_evidence_hash=registered.evidence_hash,
            source_hash=signed.evidence.source_hash,
            plan_hash=signed.evidence.plan_hash,
            manifest_digest=signed.evidence.manifest_digest,
            config_digest=signed.evidence.config_digest,
            container_id=container,
            observed_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        proof = sign_preview(evidence, preview_private)
        proof_path = report_dir / "preview-attestation.json"
        proof_path.write_text(proof.model_dump_json(indent=2) + "\n")
        proof_path.chmod(0o600)
        report.update(state="observed_healthy", container_id=container, preview_origin=origin)
        (report_dir / "preview-status.json").write_text(json.dumps(report) + "\n")
        if on_ready:
            on_ready(origin, proof_path)
        if hold:
            hold(ttl_seconds)
    except (BuildFailure, CommandError, OSError, ValueError) as exc:
        raise PreviewError("preview_failed") from exc
    finally:
        if forwarder is not None:
            forwarder.close()
        try:
            cleanup_preview(provider, preview_id)
            report["state"] = "stopped" if report["state"] == "observed_healthy" else "failed"
        except (CommandError, OSError, ValueError, PreviewError):
            report["state"] = "cleanup_required"
        (report_dir / "preview-status.json").write_text(json.dumps(report) + "\n")
    return report


def start_preview(
    signed: SignedBuildEvidence,
    authorize: Callable[[], tuple[BuildInput, BuildArtifactView]],
    builder_public: Ed25519PublicKey,
    preview_private: Ed25519PrivateKey,
    archive: Path,
    root: Path,
    provider: ComposeProvider,
    *,
    ttl_seconds: int = 300,
    on_ready: Callable[[str, Path], None] | None = None,
    hold: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    root = private_root(root)
    with preview_lock(root):
        return _start_preview(
            signed,
            authorize,
            builder_public,
            preview_private,
            archive,
            root,
            provider,
            ttl_seconds=ttl_seconds,
            on_ready=on_ready,
            hold=hold,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core")
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--builder-public-key", type=Path)
    parser.add_argument("--preview-private-key", type=Path)
    parser.add_argument("--docker-binary", default="/usr/local/bin/docker")
    parser.add_argument("--ttl", type=int, default=300)
    parser.add_argument("--cleanup-id", type=UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    root = private_root(args.root)
    if args.cleanup_id:
        if not args.apply:
            print(f"Dry-run: remove only resources labeled for preview {args.cleanup_id}.")
            return
        if args.confirm != "CLEANUP_FORGE_PREVIEW":
            parser.error("Cleanup requires --confirm CLEANUP_FORGE_PREVIEW")
        with preview_lock(root):
            cleanup_preview(ComposeProvider(root, uuid4(), args.docker_binary), args.cleanup_id)
        print("Preview resources removed, if present; images were left unchanged.")
        return
    if not args.apply:
        print(
            "Dry-run: verify build, start an isolated preview on loopback and remove it afterwards."
        )
        print("Apply requires --apply --confirm PREVIEW_ISOLATED_VM on a dedicated preview VM.")
        return
    if args.confirm != "PREVIEW_ISOLATED_VM":
        parser.error("Apply requires --confirm PREVIEW_ISOLATED_VM")
    if not all([args.core, args.artifact_dir, args.builder_public_key, args.preview_private_key]):
        parser.error("Core, artifact directory and both signing keys are required")
    artifact_dir = private_root(args.artifact_dir)
    signed = SignedBuildEvidence.model_validate_json(
        (artifact_dir / "build-attestation.json").read_text()
    )
    builder_public = read_public_key(args.builder_public_key)
    preview_private = read_private_key(args.preview_private_key)
    import getpass

    token = getpass.getpass("Current DKMan access token (not echoed): ").strip()

    def authorize() -> tuple[BuildInput, BuildArtifactView]:
        nonlocal token
        try:
            source = fetch_input(args.core, str(signed.evidence.workspace_id), token)
        except BuildFailure as exc:
            if exc.code != "access_token_invalid_or_expired":
                raise
            token = getpass.getpass("Access token expired; enter a fresh token: ").strip()
            source = fetch_input(args.core, str(signed.evidence.workspace_id), token)
        return source, fetch_artifact(args.core, signed.evidence.build_id, token)

    def ready(origin: str, proof: Path) -> None:
        print(f"Preview: {origin} (loopback on the isolated preview VM)", flush=True)
        print(f"Signed observation: {proof}", flush=True)
        print("Press Enter to stop, or wait for expiry.", flush=True)

    def hold(seconds: int) -> None:
        readable, _, _ = select.select([sys.stdin], [], [], seconds)
        if readable:
            sys.stdin.readline()

    provider = ComposeProvider(root, uuid4(), args.docker_binary)
    result = start_preview(
        signed,
        authorize,
        builder_public,
        preview_private,
        artifact_dir / "image.oci.tar",
        root,
        provider,
        ttl_seconds=args.ttl,
        on_ready=ready,
        hold=hold,
    )
    print(json.dumps(result, indent=2))
    if result["state"] != "stopped":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
