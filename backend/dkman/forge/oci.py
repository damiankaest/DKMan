"""Verify a single-platform OCI image archive without extracting it."""

import hashlib
import json
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_ARCHIVE = 2 * 1024 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
DIGEST = re.compile(r"^sha256:([a-f0-9]{64})$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class OciInspection:
    manifest_digest: str
    config_digest: str
    archive_sha256: str
    archive_size: int


def inspect_oci_archive(path: Path) -> OciInspection:
    """Verify all descriptors and expose the immutable config/image ID separately."""
    size = path.stat().st_size
    if not path.is_file() or path.is_symlink() or size <= 0 or size > MAX_ARCHIVE:
        raise ValueError("invalid_oci_archive_size")
    try:
        with tarfile.open(path, mode="r:") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(members) > 10000 or len(names) != len(set(names)):
                raise ValueError("invalid_oci_members")
            by_name = {member.name: member for member in members}

            def read_json(name: str, limit: int = MAX_JSON) -> Any:
                member = by_name.get(name)
                if member is None or not member.isfile() or member.size > limit:
                    raise ValueError("invalid_oci_json")
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("invalid_oci_json")
                return json.loads(source.read(limit + 1))

            def verify_descriptor(descriptor: Any) -> str:
                if not isinstance(descriptor, dict):
                    raise ValueError("invalid_oci_descriptor")
                digest_value = descriptor.get("digest")
                match = DIGEST.fullmatch(digest_value) if isinstance(digest_value, str) else None
                expected_size = descriptor.get("size")
                if not match or type(expected_size) is not int or expected_size < 0:
                    raise ValueError("invalid_oci_descriptor")
                name = f"blobs/sha256/{match.group(1)}"
                member = by_name.get(name)
                if member is None or not member.isfile() or member.size != expected_size:
                    raise ValueError("missing_oci_blob")
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("missing_oci_blob")
                actual = hashlib.sha256()
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    actual.update(block)
                if actual.hexdigest() != match.group(1):
                    raise ValueError("oci_blob_digest_mismatch")
                return name

            if read_json("oci-layout", 1024) != {"imageLayoutVersion": "1.0.0"}:
                raise ValueError("invalid_oci_layout")
            index = read_json("index.json")
            manifests = index.get("manifests") if isinstance(index, dict) else None
            if (
                not isinstance(index, dict)
                or index.get("schemaVersion") != 2
                or not isinstance(manifests, list)
                or len(manifests) != 1
                or not isinstance(manifests[0], dict)
            ):
                raise ValueError("expected_single_image_manifest")
            descriptor = manifests[0]
            if descriptor.get("mediaType") not in {
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.docker.distribution.manifest.v2+json",
            }:
                raise ValueError("unsupported_oci_manifest")
            manifest_name = verify_descriptor(descriptor)
            manifest = read_json(manifest_name)
            if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2:
                raise ValueError("invalid_oci_manifest")
            layers = manifest.get("layers")
            if not isinstance(layers, list) or not layers:
                raise ValueError("invalid_oci_layers")
            config = manifest.get("config")
            config_name = verify_descriptor(config)
            read_json(config_name)
            assert isinstance(config, dict)  # verify_descriptor already rejects other values
            config_digest = str(config["digest"])
            for layer in layers:
                verify_descriptor(layer)
            digest_value = str(descriptor["digest"])
    except (tarfile.TarError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        raise ValueError("invalid_oci_archive") from exc
    return OciInspection(digest_value, config_digest, sha256_file(path), size)


def verify_oci_archive(path: Path) -> tuple[str, str, int]:
    """Compatibility wrapper for the existing P4-002 worker interface."""
    result = inspect_oci_archive(path)
    return result.manifest_digest, result.archive_sha256, result.archive_size
