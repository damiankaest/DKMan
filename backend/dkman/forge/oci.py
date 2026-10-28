"""Verify a single-platform OCI image archive without extracting it."""

import hashlib
import io
import json
import os
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, cast

MAX_ARCHIVE = 2 * 1024 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
MAX_LAYERS = 256
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
            if not isinstance(layers, list) or not layers or len(layers) > MAX_LAYERS:
                raise ValueError("invalid_oci_layers")
            config = manifest.get("config")
            config_name = verify_descriptor(config)
            read_json(config_name)
            assert isinstance(config, dict)  # verify_descriptor already rejects other values
            config_digest = str(config["digest"])
            layer_total = 0
            for layer in layers:
                if not isinstance(layer, dict) or type(layer.get("size")) is not int:
                    raise ValueError("invalid_oci_descriptor")
                layer_total += layer["size"]
                if layer_total > MAX_ARCHIVE:
                    raise ValueError("oci_layers_too_large")
                verify_descriptor(layer)
            digest_value = str(descriptor["digest"])
    except (tarfile.TarError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        raise ValueError("invalid_oci_archive") from exc
    return OciInspection(digest_value, config_digest, sha256_file(path), size)


def verify_oci_archive(path: Path) -> tuple[str, str, int]:
    """Compatibility wrapper for the existing P4-002 worker interface."""
    result = inspect_oci_archive(path)
    return result.manifest_digest, result.archive_sha256, result.archive_size


class _HashingReader:
    def __init__(self, source: BinaryIO):
        self.source = source
        self.hash = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self.source.read(size)
        self.hash.update(data)
        return data


def write_docker_load_archive(source: Path, destination: Path, expected: OciInspection) -> None:
    """Repackage a verified OCI image for Docker without changing its config or layers.

    Only the blobs selected by the signed manifest are written, with no image tags.
    Each copied blob is checked again before the resulting archive may be loaded.
    """
    manifest_match = DIGEST.fullmatch(expected.manifest_digest)
    if not manifest_match or not DIGEST.fullmatch(expected.config_digest):
        raise ValueError("invalid_expected_image_digest")
    if inspect_oci_archive(source) != expected:
        raise ValueError("oci_archive_changed")
    created = False
    complete = False
    try:
        with tarfile.open(source, mode="r:") as archive:
            member = archive.getmember(f"blobs/sha256/{manifest_match.group(1)}")
            if not member.isfile() or member.size > MAX_JSON:
                raise ValueError("invalid_oci_manifest")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("invalid_oci_manifest")
            raw_manifest = stream.read(MAX_JSON + 1)
            if hashlib.sha256(raw_manifest).hexdigest() != manifest_match.group(1):
                raise ValueError("oci_manifest_changed")
            manifest = json.loads(raw_manifest)
            if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2:
                raise ValueError("invalid_oci_manifest")
            config = manifest.get("config")
            layers = manifest.get("layers")
            if (
                not isinstance(config, dict)
                or config.get("digest") != expected.config_digest
                or not isinstance(layers, list)
                or not layers
                or len(layers) > MAX_LAYERS
            ):
                raise ValueError("invalid_oci_manifest")
            if (
                any(
                    not isinstance(layer, dict)
                    or type(layer.get("size")) is not int
                    or layer["size"] < 0
                    for layer in layers
                )
                or sum(layer["size"] for layer in layers) > MAX_ARCHIVE
            ):
                raise ValueError("invalid_oci_layers")

            layer_names = [f"layers/{index}.tar" for index in range(len(layers))]
            metadata = json.dumps(
                [{"Config": "config.json", "RepoTags": [], "Layers": layer_names}],
                separators=(",", ":"),
            ).encode("utf-8")
            descriptor = os.open(
                destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            created = True
            with (
                os.fdopen(descriptor, "wb") as output,
                tarfile.open(fileobj=output, mode="w") as target,
            ):

                def copy_blob(item: Any, name: str, *, is_layer: bool) -> None:
                    if not isinstance(item, dict):
                        raise ValueError("invalid_oci_descriptor")
                    value, size = item.get("digest"), item.get("size")
                    match = DIGEST.fullmatch(value) if isinstance(value, str) else None
                    if not match or type(size) is not int or size < 0 or size > MAX_ARCHIVE:
                        raise ValueError("invalid_oci_descriptor")
                    if is_layer and item.get("mediaType") not in {
                        "application/vnd.oci.image.layer.v1.tar",
                        "application/vnd.oci.image.layer.v1.tar+gzip",
                        "application/vnd.docker.image.rootfs.diff.tar",
                        "application/vnd.docker.image.rootfs.diff.tar.gzip",
                    }:
                        raise ValueError("unsupported_oci_layer")
                    blob = archive.getmember(f"blobs/sha256/{match.group(1)}")
                    if not blob.isfile() or blob.size != size:
                        raise ValueError("missing_oci_blob")
                    data = archive.extractfile(blob)
                    if data is None:
                        raise ValueError("missing_oci_blob")
                    reader = _HashingReader(cast(BinaryIO, data))
                    entry = tarfile.TarInfo(name)
                    entry.mode = 0o600
                    entry.size = size
                    target.addfile(entry, cast(BinaryIO, reader))
                    if reader.hash.hexdigest() != match.group(1):
                        raise ValueError("oci_blob_digest_mismatch")

                copy_blob(config, "config.json", is_layer=False)
                for item, name in zip(layers, layer_names, strict=True):
                    copy_blob(item, name, is_layer=True)
                entry = tarfile.TarInfo("manifest.json")
                entry.mode = 0o600
                entry.size = len(metadata)
                target.addfile(entry, io.BytesIO(metadata))
        if (
            source.stat().st_size != expected.archive_size
            or sha256_file(source) != expected.archive_sha256
        ):
            raise ValueError("oci_archive_changed")
        complete = True
    except (tarfile.TarError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        raise ValueError("invalid_oci_archive") from exc
    finally:
        if created and not complete:
            destination.unlink(missing_ok=True)
