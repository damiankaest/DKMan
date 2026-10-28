"""Stage a verified Forge SPA archive without loading or executing it.

Run only where the deployment adapter's private staging directory is mounted.
This operation is separate from a human's deployment approval and an install job.
"""

import argparse
import hashlib
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from dkman.deployment_adapter.forge_preview import (
    PreviewError,
    fetch_artifact,
    preview_lock,
    verify_inputs,
)
from dkman.deployments.contracts import MAX_FORGE_DEPLOY_ARCHIVE
from dkman.forge.attestation import SignedBuildEvidence, read_public_key
from dkman.forge.build_worker import BuildFailure, fetch_input, private_root
from dkman.forge.oci import MAX_ARCHIVE, OciInspection, inspect_oci_archive
from dkman.forge_api import BuildArtifactView, BuildInput


def staged_archive(signed: SignedBuildEvidence, staging_root: Path) -> tuple[Path, OciInspection]:
    """Recheck the private, signed staging entry at the adapter trust boundary."""
    root = private_root(staging_root)
    directory = private_root(root / str(signed.evidence.build_id))
    proof = directory / "build-attestation.json"
    if proof.is_symlink() or not proof.is_file() or proof.stat().st_size > 65536:
        raise PreviewError("staged_evidence_unavailable")
    if SignedBuildEvidence.model_validate_json(proof.read_bytes()) != signed:
        raise PreviewError("staged_build_identifier_conflict")
    archive = directory / "image.oci.tar"
    actual = inspect_oci_archive(archive)
    evidence = signed.evidence
    if (
        actual.manifest_digest != evidence.manifest_digest
        or actual.config_digest != evidence.config_digest
        or actual.archive_sha256 != evidence.archive_sha256
        or actual.archive_size != evidence.archive_size
    ):
        raise PreviewError("archive_does_not_match_attestation")
    return archive, actual


def stage_archive(
    signed: SignedBuildEvidence,
    authorize: Callable[[], tuple[BuildInput, BuildArtifactView]],
    builder_public: Ed25519PublicKey,
    archive: Path,
    staging_root: Path,
) -> Path:
    """Atomically publish a verified artifact under its signed build UUID."""
    root = private_root(staging_root)
    if (
        signed.evidence.template != "react-spa"
        or signed.evidence.archive_size > MAX_FORGE_DEPLOY_ARCHIVE
    ):
        raise PreviewError("production_staging_requires_react_spa")
    with preview_lock(root):
        source, registered = authorize()
        verify_inputs(signed, source, registered, builder_public, archive)
        destination = root / str(signed.evidence.build_id)
        if destination.is_symlink():
            raise PreviewError("staged_build_identifier_conflict")
        if destination.exists():
            private_root(destination)
            proof_path = destination / "build-attestation.json"
            if proof_path.is_symlink() or not proof_path.is_file():
                raise PreviewError("staged_evidence_unavailable")
            existing = SignedBuildEvidence.model_validate_json(proof_path.read_bytes())
            if existing != signed:
                raise PreviewError("staged_build_identifier_conflict")
            verify_inputs(signed, source, registered, builder_public, destination / "image.oci.tar")
            return destination
        temporary = root / f".staging-{uuid4()}"
        temporary.mkdir(mode=0o700)
        try:
            target = temporary / "image.oci.tar"
            output_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            checksum = hashlib.sha256()
            size = 0
            with os.fdopen(output_fd, "wb") as output, archive.open("rb") as original:
                while block := original.read(1024 * 1024):
                    size += len(block)
                    if size > MAX_ARCHIVE:
                        raise ValueError("staged_archive_too_large")
                    checksum.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            if (
                size != signed.evidence.archive_size
                or checksum.hexdigest() != signed.evidence.archive_sha256
            ):
                raise PreviewError("staged_archive_changed")
            proof = temporary / "build-attestation.json"
            fd = os.open(proof, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(signed.model_dump_json(indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
            # Check both authorization and copied OCI descriptors again before publishing.
            current_source, current_artifact = authorize()
            verify_inputs(signed, current_source, current_artifact, builder_public, target)
            os.rename(temporary, destination)
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return destination
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core")
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--builder-public-key", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    private_root(args.root)
    if not args.apply:
        print("Dry-run: verify and stage one signed Forge SPA image; do not load or run it.")
        print("Apply requires --apply --confirm STAGE_FORGE_ARCHIVE.")
        return
    if args.confirm != "STAGE_FORGE_ARCHIVE":
        parser.error("Apply requires --confirm STAGE_FORGE_ARCHIVE")
    if not all([args.core, args.artifact_dir, args.builder_public_key]):
        parser.error("Core, artifact directory and builder verification key are required")
    artifact_dir = private_root(args.artifact_dir)
    signed = SignedBuildEvidence.model_validate_json(
        (artifact_dir / "build-attestation.json").read_bytes()
    )
    public = read_public_key(args.builder_public_key)
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

    staged = stage_archive(signed, authorize, public, artifact_dir / "image.oci.tar", args.root)
    print(json.dumps({"build_id": str(signed.evidence.build_id), "staged": str(staged)}))


if __name__ == "__main__":
    main()
