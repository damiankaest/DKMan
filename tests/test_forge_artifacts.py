"""Authenticated and signed build evidence: no execution or deployment."""

import hashlib
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_forge_api import generate, prepare
from test_planning import revision

from dkman.forge.attestation import BuildEvidence, sign_evidence
from dkman.forge.build_recipe import (
    CHECK_LOCK,
    checks_dockerfile,
    expected_checks,
    image_dockerfile,
)
from dkman.forge.oci import sha256_file
from dkman.forge.workspace import SourceBundle
from dkman.models import ForgeBuildArtifact, utcnow


@pytest.fixture
def setup_artifact(client, as_user, app, tmp_path, request):
    item, plan = prepare(client, as_user)
    workspace = generate(client, plan, template=getattr(request, "param", "react-spa")).json()
    build_input = client.get(f"/api/v1/forge/workspaces/{workspace['id']}/build-input").json()
    bundle = SourceBundle.model_validate(build_input["bundle"])
    key = Ed25519PrivateKey.generate()
    public_path = tmp_path / "public.pem"
    public_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    app.state.settings.forge_builder_public_key_file = public_path
    evidence = BuildEvidence(
        build_id=uuid4(),
        workspace_id=workspace["id"],
        source_hash=workspace["bundle_hash"],
        plan_hash=plan["content_hash"],
        template=bundle.request.template,
        checks=expected_checks(bundle.request.template),
        manifest_digest="sha256:" + "a" * 64,
        config_digest="sha256:" + "b" * 64,
        archive_sha256="c" * 64,
        archive_size=100,
        check_recipe_sha256=hashlib.sha256(
            checks_dockerfile(bundle.request.template).encode()
        ).hexdigest(),
        check_requirements_sha256=sha256_file(CHECK_LOCK),
        image_recipe_sha256=hashlib.sha256(image_dockerfile(bundle).encode()).hexdigest(),
        finished_at=utcnow(),
    )
    body = sign_evidence(evidence, key).model_dump(mode="json")
    return item, plan, workspace, key, body


def path(workspace):
    return f"/api/v1/forge/workspaces/{workspace['id']}/build-artifacts"


def test_signed_artifact_is_persisted_and_replay_is_idempotent(client, setup_artifact, engine):
    _, _, workspace, _, body = setup_artifact
    response = client.post(path(workspace), json=body)
    assert response.status_code == 201
    artifact = response.json()
    assert artifact["id"] == body["evidence"]["build_id"]
    assert artifact["evidence"]["manifest_digest"] == body["evidence"]["manifest_digest"]
    assert client.post(path(workspace), json=body).json() == artifact
    assert client.get(path(workspace)).json() == [artifact]
    assert client.get(f"/api/v1/forge/build-artifacts/{artifact['id']}").json() == artifact
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ForgeBuildArtifact)) == 1


def test_rejects_unsigned_wrong_key_and_modified_evidence(client, setup_artifact, engine):
    _, _, workspace, key, body = setup_artifact
    changed = {**body, "evidence": {**body["evidence"], "archive_sha256": "d" * 64}}
    assert client.post(path(workspace), json=changed).status_code == 409
    invalid_key = sign_evidence(
        BuildEvidence.model_validate(body["evidence"]), Ed25519PrivateKey.generate()
    ).model_dump(mode="json")
    assert client.post(path(workspace), json=invalid_key).status_code == 409
    forged = BuildEvidence.model_validate({**body["evidence"], "source_hash": "d" * 64})
    assert (
        client.post(
            path(workspace), json=sign_evidence(forged, key).model_dump(mode="json")
        ).status_code
        == 409
    )
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ForgeBuildArtifact)) == 0


def test_artifact_requires_current_plan_and_user_access(client, setup_artifact, as_user):
    item, _, workspace, _, body = setup_artifact
    as_user("bob", ["developer"])
    assert client.post(path(workspace), json=body).status_code == 404
    assert client.get(path(workspace)).status_code == 404
    as_user("alice", ["developer"])
    assert revision(client, item).status_code == 201
    assert client.post(path(workspace), json=body).status_code == 409


def test_key_is_required_and_revalidated_on_read(client, setup_artifact, app, tmp_path):
    _, _, workspace, _, body = setup_artifact
    previous_key = app.state.settings.forge_builder_public_key_file
    app.state.settings.forge_builder_public_key_file = None
    assert client.post(path(workspace), json=body).status_code == 503
    app.state.settings.forge_builder_public_key_file = previous_key
    assert client.post(path(workspace), json=body).status_code == 201
    other = Ed25519PrivateKey.generate().public_key()
    public_path = tmp_path / "other.pem"
    public_path.write_bytes(
        other.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    app.state.settings.forge_builder_public_key_file = public_path
    assert client.get(path(workspace)).status_code == 409
