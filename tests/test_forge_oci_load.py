import hashlib
import json
import stat
import tarfile

import pytest
from test_forge_build_worker import sample_oci

from dkman.forge import oci


def test_repackaged_image_preserves_verified_blobs_and_cannot_assign_tags(tmp_path):
    source = tmp_path / "image.oci.tar"
    destination = tmp_path / "docker-load.tar"
    sample_oci(source)
    expected = oci.inspect_oci_archive(source)

    oci.write_docker_load_archive(source, destination, expected)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    with tarfile.open(source) as image, tarfile.open(destination) as result:
        source_manifest = json.load(
            image.extractfile("blobs/sha256/" + expected.manifest_digest[7:])
        )
        load_manifest = json.load(result.extractfile("manifest.json"))
        assert len(load_manifest) == 1 and load_manifest[0]["RepoTags"] == []
        assert set(result.getnames()) == {"config.json", "layers/0.tar", "manifest.json"}
        assert (
            hashlib.sha256(result.extractfile("config.json").read()).hexdigest()
            == expected.config_digest[7:]
        )
        layer_hash = hashlib.sha256(
            result.extractfile(load_manifest[0]["Layers"][0]).read()
        ).hexdigest()
        assert layer_hash == source_manifest["layers"][0]["digest"][7:]


def test_repackaging_rejects_changed_source_and_does_not_overwrite(tmp_path):
    source = tmp_path / "image.oci.tar"
    destination = tmp_path / "docker-load.tar"
    sample_oci(source)
    expected = oci.inspect_oci_archive(source)
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="oci_archive_changed"):
        oci.write_docker_load_archive(source, destination, expected)
    assert not destination.exists()

    sample_oci(source)
    destination.write_bytes(b"do not replace")
    with pytest.raises(FileExistsError):
        oci.write_docker_load_archive(source, destination, expected)
    assert destination.read_bytes() == b"do not replace"


def test_repackaging_detects_layer_change_after_verification(tmp_path, monkeypatch):
    source = tmp_path / "image.oci.tar"
    destination = tmp_path / "docker-load.tar"
    sample_oci(source)
    expected = oci.inspect_oci_archive(source)
    sample_oci(source, corrupt=True)
    # Simulate a concurrent replacement immediately after the first verification.
    monkeypatch.setattr(oci, "inspect_oci_archive", lambda _: expected)
    with pytest.raises(ValueError, match="oci_blob_digest_mismatch"):
        oci.write_docker_load_archive(source, destination, expected)
    assert not destination.exists()


def test_oci_archive_rejects_excessive_repeated_layers(tmp_path):
    source = tmp_path / "image.oci.tar"
    sample_oci(source, layer_repetitions=oci.MAX_LAYERS + 1)
    with pytest.raises(ValueError, match="invalid_oci_layers"):
        oci.inspect_oci_archive(source)
