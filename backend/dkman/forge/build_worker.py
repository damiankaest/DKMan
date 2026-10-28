"""Operator-run BuildKit client for approved, unchanged Forge starters.

The worker must run on a dedicated isolated builder, never on the runtime host.
It does not connect to Docker, deploy images, or expose arbitrary build commands.
"""

import argparse
import json
import os
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dkman.deployments.client import NoRedirect
from dkman.deployments.redaction import redact_logs
from dkman.forge.attestation import BuildEvidence, read_private_key, sign_evidence
from dkman.forge.build_recipe import (
    CHECK_LOCK,
    checks_dockerfile,
    expected_checks,
    image_dockerfile,
)
from dkman.forge.oci import inspect_oci_archive, sha256_file
from dkman.forge.templates import TemplateProvider
from dkman.forge.workspace import SourceBundle, prepare_workspace
from dkman.forge_api import BuildInput, bundle_hash

MAX_OUTPUT = 65536
TIMEOUT_SECONDS = 900


class BuildFailure(Exception):
    def __init__(self, code: str, output: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.output = output


def private_root(path: Path) -> Path:
    root = path.absolute()
    if (
        root.is_symlink()
        or root.resolve(strict=True) != root
        or not root.is_dir()
        or any(character in str(root) for character in ",\n\r")
    ):
        raise ValueError("worker_root_must_be_a_real_directory")
    info = root.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("worker_root_must_be_owned_and_private")
    return root


def buildkit_socket(address: str) -> str:
    if not address.startswith("unix:///"):
        raise ValueError("buildkit_requires_a_local_unix_socket")
    path = Path(address.removeprefix("unix://"))
    if (
        path.name != "buildkitd.sock"
        or path.is_symlink()
        or path.resolve(strict=True) != path
        or not stat.S_ISSOCK(path.stat().st_mode)
    ):
        raise ValueError("invalid_buildkit_socket")
    return address


def fetch_input(origin: str, workspace_id: str, token: str) -> BuildInput:
    parsed = urllib.parse.urlsplit(origin)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("core_origin_requires_https_or_loopback")
    identifier = str(UUID(workspace_id))
    if not token or len(token) > 16384 or any(c.isspace() for c in token):
        raise ValueError("invalid_access_token")
    request = urllib.request.Request(
        origin.rstrip("/") + f"/api/v1/forge/workspaces/{identifier}/build-input",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("build_input_too_large")
        result = BuildInput.model_validate_json(data)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise BuildFailure("access_token_invalid_or_expired") from exc
        raise BuildFailure("approved_source_unavailable") from exc
    except (OSError, ValueError) as exc:
        raise BuildFailure("approved_source_unavailable") from exc
    if result.workspace_id != identifier:
        raise BuildFailure("workspace_binding_mismatch")
    return result


def validate_input(value: BuildInput) -> SourceBundle:
    bundle = SourceBundle.model_validate(value.bundle.model_dump(mode="json"))
    if bundle_hash(bundle) != value.bundle_hash:
        raise BuildFailure("source_hash_mismatch")
    # The initial worker deliberately accepts only the exact bundled templates.
    if TemplateProvider().generate(bundle.request) != bundle:
        raise BuildFailure("unsupported_or_changed_template")
    return bundle


def assert_files(path: Path, bundle: SourceBundle) -> None:
    found: set[str] = set()
    for item in path.rglob("*"):
        if item.is_symlink():
            raise BuildFailure("source_files_changed")
        if item.is_file():
            name = item.relative_to(path).as_posix()
            found.add(name)
            if name not in bundle.files or item.read_bytes() != bundle.files[name].encode("utf-8"):
                raise BuildFailure("source_files_changed")
        elif not item.is_dir():
            raise BuildFailure("source_files_changed")
    if found != set(bundle.files):
        raise BuildFailure("source_files_changed")


def run_command(command: list[str], home: Path) -> str:
    """Drain output with a hard in-memory bound and kill the client on timeout."""
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={"PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8"},
            start_new_session=True,
        )
    except OSError as exc:
        raise BuildFailure("buildctl_unavailable") from exc
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = bytearray()
    deadline = time.monotonic() + TIMEOUT_SECONDS
    timed_out = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                break
            for key, _ in selector.select(min(remaining, 1)):
                data = os.read(key.fd, 8192)
                if not data:
                    selector.unregister(key.fileobj)
                else:
                    output.extend(data)
                    if len(output) > MAX_OUTPUT:
                        del output[:-MAX_OUTPUT]
        process.wait(timeout=5)
    finally:
        selector.close()
        process.stdout.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    text = redact_logs(output.decode("utf-8", errors="replace"))
    if timed_out:
        raise BuildFailure("build_timeout_outcome_unknown", text)
    if process.returncode != 0:
        raise BuildFailure("build_command_failed", text)
    return text


def _command(buildctl: str, address: str, context: Path, recipe: Path, output: str) -> list[str]:
    return [
        buildctl,
        "--addr",
        address,
        "build",
        "--frontend",
        "dockerfile.v0",
        "--no-cache",
        "--progress",
        "plain",
        "--local",
        f"context={context}",
        "--local",
        f"dockerfile={recipe}",
        "--opt",
        "filename=Dockerfile",
        "--output",
        output,
    ]


def write_report(directory: Path, result: dict[str, Any], *, initial: bool = False) -> None:
    target = directory / ("build-artifact.json" if initial else "build-artifact.tmp")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if not initial:
        target.replace(directory / "build-artifact.json")


def execute_build(
    get_input: Callable[[], BuildInput],
    root: Path,
    address: str,
    buildctl: str,
    signing_key: Ed25519PrivateKey | None = None,
) -> dict[str, Any]:
    """Build exactly once; any failure leaves a private, non-deployable report."""
    root = private_root(root)
    buildkit_socket(address)
    initial = get_input()
    bundle = validate_input(initial)
    build_id = str(uuid4())
    output_dir = root / build_id
    output_dir.mkdir(mode=0o700)
    result: dict[str, Any] = {
        "schema_version": 1,
        "build_id": build_id,
        "workspace_id": initial.workspace_id,
        "source_hash": initial.bundle_hash,
        "plan_hash": bundle.request.content_hash,
        "template": bundle.request.template,
        "state": "running",
        "stage": "preparing",
        "started_at": datetime.now(UTC).isoformat(),
        "checks": [],
        "manifest_digest": None,
        "config_digest": None,
        "archive_sha256": None,
        "archive_size": None,
        "check_recipe_sha256": None,
        "check_requirements_sha256": None,
        "image_recipe_sha256": None,
        "failure_code": None,
        "logs": "",
    }
    write_report(output_dir, result, initial=True)
    archive = output_dir / "image.oci.partial"
    try:
        with tempfile.TemporaryDirectory(prefix="work-", dir=root) as temporary:
            work = Path(temporary)
            source = prepare_workspace(work, bundle).path
            check_context = work / "checks-context"
            shutil.copytree(source, check_context)
            shutil.copyfile(CHECK_LOCK, check_context / "requirements-check.lock")
            recipe = work / "recipe"
            recipe.mkdir(mode=0o700)
            (recipe / "Dockerfile").write_text(checks_dockerfile(bundle.request.template))
            result["check_recipe_sha256"] = sha256_file(recipe / "Dockerfile")
            result["check_requirements_sha256"] = sha256_file(CHECK_LOCK)
            check_result = work / "check-result"
            check_result.mkdir(mode=0o700)

            def reauthorize() -> None:
                current = get_input()
                if current != initial:
                    raise BuildFailure("authorization_or_source_changed")
                validate_input(current)
                assert_files(source, bundle)

            reauthorize()
            result["stage"] = "checks"
            write_report(output_dir, result)
            check_log = run_command(
                _command(
                    buildctl, address, check_context, recipe, f"type=local,dest={check_result}"
                ),
                work,
            )
            expected = expected_checks(bundle.request.template)
            if any(
                not (check_result / marker).is_file() or (check_result / marker).is_symlink()
                for marker in expected
            ):
                raise BuildFailure("checks_evidence_missing", check_log)
            result["checks"] = expected
            reauthorize()
            result["stage"] = "image"
            write_report(output_dir, result)
            if bundle.request.template == "python-api":
                context = source / "backend"
            elif bundle.request.template == "react-spa":
                context = source / "web"
            else:
                context = source
            dockerfile = image_dockerfile(bundle)
            (recipe / "Dockerfile").write_text(dockerfile)
            result["image_recipe_sha256"] = sha256_file(recipe / "Dockerfile")
            write_report(output_dir, result)
            run_command(
                _command(buildctl, address, context, recipe, f"type=oci,dest={archive}"), work
            )
            result["stage"] = "verification"
            write_report(output_dir, result)
            verified = inspect_oci_archive(archive)
            reauthorize()
            archive.chmod(0o600)
            archive.replace(output_dir / "image.oci.tar")
            result.update(
                state="succeeded",
                stage="complete",
                manifest_digest=verified.manifest_digest,
                config_digest=verified.config_digest,
                archive_sha256=verified.archive_sha256,
                archive_size=verified.archive_size,
            )
    except BuildFailure as exc:
        archive.unlink(missing_ok=True)
        result.update(state="failed", failure_code=exc.code, logs=redact_logs(exc.output))
    except (OSError, ValueError, subprocess.SubprocessError):
        archive.unlink(missing_ok=True)
        result.update(state="failed", failure_code="worker_or_artifact_invalid")
    result["finished_at"] = datetime.now(UTC).isoformat()
    if result["state"] == "succeeded" and signing_key is not None:
        try:
            evidence = BuildEvidence.model_validate(
                {key: result[key] for key in BuildEvidence.model_fields}
            )
            signed = sign_evidence(evidence, signing_key)
            descriptor = os.open(
                output_dir / "build-attestation.json",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(signed.model_dump_json(indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            result["attestation"] = "build-attestation.json"
        except (OSError, ValueError):
            (output_dir / "image.oci.tar").unlink(missing_ok=True)
            (output_dir / "build-attestation.json").unlink(missing_ok=True)
            result.update(state="failed", failure_code="attestation_failed")
    write_report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--core", required=True, help="HTTPS origin, or loopback HTTP for local tests"
    )
    parser.add_argument("--workspace", required=True, help="Forge workspace UUID")
    parser.add_argument(
        "--root", type=Path, required=True, help="existing private builder directory"
    )
    parser.add_argument("--buildkit-socket", required=True, help="unix:///.../buildkitd.sock")
    parser.add_argument("--signing-key", type=Path, help="private Ed25519 builder key")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    UUID(args.workspace)
    private_root(args.root)
    buildkit_socket(args.buildkit_socket)
    if not args.apply:
        print("Dry-run: check approved source, run isolated tests and verify an OCI archive.")
        print("No build started. Apply requires --apply --confirm BUILD_FORGE_ISOLATED.")
        return
    if args.confirm != "BUILD_FORGE_ISOLATED":
        parser.error("Apply requires --confirm BUILD_FORGE_ISOLATED")
    buildctl = shutil.which("buildctl")
    if not buildctl:
        parser.error("buildctl is required on the isolated builder")
    signing_key = read_private_key(args.signing_key) if args.signing_key else None
    import getpass

    token = getpass.getpass("Current DKMan access token (not echoed): ").strip()

    def authorized_input() -> BuildInput:
        nonlocal token
        try:
            return fetch_input(args.core, args.workspace, token)
        except BuildFailure as exc:
            if exc.code != "access_token_invalid_or_expired":
                raise
            token = getpass.getpass("Access token expired; enter a fresh token: ").strip()
            return fetch_input(args.core, args.workspace, token)

    result = execute_build(
        authorized_input,
        args.root,
        args.buildkit_socket,
        buildctl,
        signing_key,
    )
    print(
        json.dumps({k: v for k, v in result.items() if k != "logs"}, ensure_ascii=False, indent=2)
    )
    if result["state"] != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
