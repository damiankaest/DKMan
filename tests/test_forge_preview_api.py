"""Preview attestations are signed observations, never live status or approval."""

from datetime import timedelta
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_forge_artifacts import path, setup_artifact
from test_planning import revision

from dkman.forge.attestation import PreviewEvidence, sign_preview
from dkman.models import utcnow

__all__ = ["setup_artifact"]


def prepare_preview(client, app, tmp_path, setup_artifact):
    item, _, workspace, _, body = setup_artifact
    build = client.post(path(workspace), json=body).json()
    private = Ed25519PrivateKey.generate()
    public_path = tmp_path / "preview-public.pem"
    public_path.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    app.state.settings.forge_preview_public_key_file = public_path
    now = utcnow()
    evidence = PreviewEvidence(
        preview_id=uuid4(),
        artifact_id=build["id"],
        workspace_id=workspace["id"],
        artifact_evidence_hash=build["evidence_hash"],
        source_hash=build["evidence"]["source_hash"],
        plan_hash=build["evidence"]["plan_hash"],
        manifest_digest=build["evidence"]["manifest_digest"],
        config_digest=build["evidence"]["config_digest"],
        container_id="c" * 64,
        observed_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    return item, workspace, build, private, evidence


def test_records_verified_observation_and_enforces_owner(
    client, as_user, app, tmp_path, setup_artifact
):
    _, _, build, key, evidence = prepare_preview(client, app, tmp_path, setup_artifact)
    path = f"/api/v1/forge/build-artifacts/{build['id']}/previews"
    body = sign_preview(evidence, key).model_dump(mode="json")
    response = client.post(path, json=body)
    assert response.status_code == 201
    result = response.json()
    assert result["evidence"]["state"] == "healthy"
    assert result["evidence"]["manifest_digest"] == build["evidence"]["manifest_digest"]
    assert client.post(path, json=body).json() == result
    assert client.get(path).json() == [result]
    as_user("bob", ["developer"])
    assert client.get(path).status_code == 404
    assert client.post(path, json=body).status_code == 404


def test_requires_distinct_key_current_plan_and_unexpired_bound_evidence(
    client, as_user, app, tmp_path, setup_artifact
):
    item, _, build, key, evidence = prepare_preview(client, app, tmp_path, setup_artifact)
    path = f"/api/v1/forge/build-artifacts/{build['id']}/previews"
    body = sign_preview(evidence, key).model_dump(mode="json")
    configured_preview_key = app.state.settings.forge_preview_public_key_file
    app.state.settings.forge_preview_public_key_file = (
        app.state.settings.forge_builder_public_key_file
    )
    assert client.post(path, json=body).status_code == 503
    app.state.settings.forge_preview_public_key_file = configured_preview_key
    wrong = evidence.model_copy(update={"config_digest": "sha256:" + "f" * 64})
    assert (
        client.post(path, json=sign_preview(wrong, key).model_dump(mode="json")).status_code == 409
    )
    now = utcnow()
    expired = evidence.model_copy(
        update={
            "observed_at": now - timedelta(minutes=10),
            "expires_at": now - timedelta(minutes=5),
        }
    )
    assert (
        client.post(path, json=sign_preview(expired, key).model_dump(mode="json")).status_code
        == 409
    )
    as_user("alice", ["developer"])
    assert revision(client, item).status_code == 201
    assert client.post(path, json=body).status_code == 409
