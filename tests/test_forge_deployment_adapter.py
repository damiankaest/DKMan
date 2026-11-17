import json
import tarfile
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from test_deployment_adapter import adapter, catalog, submit, token
from test_forge_preview import setup_preview
from test_forge_release_contract import release_plan

from dkman.deployment_adapter.compose import ComposeProvider, render_compose
from dkman.deployment_adapter.forge_preview import PreviewError
from dkman.deployment_adapter.forge_staging import stage_archive, staged_archive

__all__ = ["adapter", "catalog", "setup_preview"]


def test_forge_runtime_profile_has_fixed_health_and_no_host_exposure(setup_preview):
    plan, _, _ = release_plan(setup_preview)
    config = render_compose(plan)
    service = config["services"]["app"]
    assert service["image"] == plan.image and service["user"] == "101"
    assert service["read_only"] and service["cap_drop"] == ["ALL"]
    assert "ports" not in service and "volumes" not in service and "environment" not in service
    assert service["healthcheck"]["test"] == [
        "CMD",
        "wget",
        "-qO-",
        "http://127.0.0.1:8080/health/ready",
    ]
    assert config["networks"]["private"]["internal"] is True
    assert config["networks"]["gateway"]["name"] == "dkman-app-gateway"


def test_adapter_loads_only_the_verified_tagless_staged_archive(setup_preview, monkeypatch):
    root, archive, source, registered, signed, builder, _, _ = setup_preview
    staging = root / "staging"
    staging.mkdir(mode=0o700)
    plan, _, _ = release_plan(setup_preview)
    stage_archive(signed, lambda: (source, registered), builder.public_key(), archive, staging)
    assert staged_archive(signed, staging)[1].config_digest == plan.image
    (root / "plans").mkdir(mode=0o700)
    provider = ComposeProvider(root, uuid4(), forge_staging_root=staging)
    calls = []

    def run(arguments, timeout=45):
        calls.append(arguments)
        if arguments[:2] == ["image", "load"]:
            with tarfile.open(arguments[-1]) as target:
                assert json.load(target.extractfile("manifest.json"))[0]["RepoTags"] == []
            return "loaded"
        if arguments[:2] == ["image", "inspect"]:
            return json.dumps([{"Id": plan.image, "Config": {"User": "101", "Volumes": None}}])
        raise AssertionError(arguments)

    monkeypatch.setattr(provider, "run", run)
    provider.pull(plan)
    assert [call[:2] for call in calls] == [["image", "load"], ["image", "inspect"]]
    assert not list((root / "plans").glob("*.forge-load.tar"))
    (staging / str(signed.evidence.build_id) / "image.oci.tar").write_bytes(b"changed")
    with pytest.raises((ValueError, PreviewError)):
        provider.pull(plan)
    assert len(calls) == 2


def test_adapter_rechecks_keys_and_never_claims_success_without_receipt(
    adapter, setup_preview, tmp_path
):
    client, _, engine, settings, _ = adapter
    plan, builder, preview = release_plan(setup_preview)
    for name, key in [("builder", builder.public_key()), ("preview", preview.public_key())]:
        path = tmp_path / f"{name}.pem"
        path.write_bytes(
            key.public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        setattr(settings, f"forge_{name}_public_key_file", path)
    operation = uuid4()
    grant = token(plan, operation, "install", subject="admin")
    response, _, _ = submit(client, plan, operation_id=operation, credential=grant)
    assert response.status_code == 200
    assert response.json()["state"] == "reconciliation_required"
    assert len(engine.calls) == 1
    # A differently signed plan is rejected before any provider mutation.
    settings.forge_preview_public_key_file = settings.forge_builder_public_key_file
    operation = uuid4()
    response, _, _ = submit(
        client,
        plan,
        operation_id=operation,
        credential=token(plan, operation, "install", subject="admin"),
    )
    assert response.status_code == 200
    assert (
        response.json()["state"] == "failed"
        and response.json()["failure_code"] == "curation_rejected"
    )
    assert len(engine.calls) == 1
