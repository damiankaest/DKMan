import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_forge_preview_api import prepare_preview, setup_artifact
from test_planning import approve, revision

from dkman.forge.attestation import sign_preview
from dkman.models import AppInstallation, ApprovalRequest, DeploymentTarget, utcnow

__all__ = ["setup_artifact"]


@pytest.fixture
def candidate(client, app, tmp_path, setup_artifact, as_user):
    item, _, build, private, evidence = prepare_preview(client, app, tmp_path, setup_artifact)
    observation = client.post(
        f"/api/v1/forge/build-artifacts/{build['id']}/previews",
        json=sign_preview(evidence, private).model_dump(mode="json"),
    )
    assert observation.status_code == 201
    as_user("admin", ["admin"])
    home = client.post("/api/v1/households", json={"name": "Test home"}).json()
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"schema_version": 1, "images": []}))
    app.state.settings.deployment_enabled = True
    app.state.settings.deployment_catalog_file = path
    secret = tmp_path / "adapter-secret"
    secret.write_text("s" * 48)
    app.state.settings.deployment_secret_file = secret
    return item, build, observation.json(), home


def submit(client, preview, home, key=None):
    return client.post(
        f"/api/v1/forge/previews/{preview['id']}/installations",
        json={"household_id": home["id"]},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def test_installation_plan_binds_current_preview_and_requires_separate_approval(
    client, candidate, engine
):
    _, build, preview, home = candidate
    response = submit(client, preview, home, "one")
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["state"] == "waiting_approval"
    assert job["action"] == "deployment.install"
    assert job["plan"]["image"] == build["evidence"]["config_digest"]
    assert job["plan"]["forge"]["preview"]["evidence"]["preview_id"] == preview["id"]
    assert submit(client, preview, home, "one").json()["id"] == job["id"]
    assert submit(client, preview, home).status_code == 409
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AppInstallation)) == 0
        assert db.scalar(select(func.count()).select_from(DeploymentTarget)) == 1
        approval = db.scalar(select(ApprovalRequest).where(ApprovalRequest.job_id == job["id"]))
        assert approval is not None and approval.state == "pending"


def test_revoked_plan_cannot_execute_even_after_approval(client, candidate, as_user, app):
    item, _, preview, home = candidate
    job = submit(client, preview, home).json()
    assert approve(client, job).status_code == 200
    as_user("alice", ["developer"])
    assert revision(client, item).status_code == 201
    as_user("admin", ["admin"])

    class NeverCalled:
        def execute(self, *_):
            pytest.fail("Stale approval must not reach the deployment adapter")

    app.state.deployment_client = NeverCalled()
    response = client.post(f"/api/v1/jobs/{job['id']}/run")
    assert response.status_code == 200
    assert response.json()["state"] == "failed"
    assert response.json()["failure_code"] == "installation_preflight_failed"


def test_only_admin_and_current_preview_can_prepare_installation(
    client, candidate, as_user, engine
):
    _, _, preview, home = candidate
    as_user("alice", ["developer"])
    assert submit(client, preview, home).status_code == 403
    as_user("admin", ["admin"])
    with Session(engine) as db:
        from dkman.models import ForgePreview

        item = db.get(ForgePreview, preview["id"])
        payload = dict(item.attestation)
        payload["evidence"] = {
            **payload["evidence"],
            "expires_at": (utcnow() - timedelta(minutes=1)).isoformat(),
        }
        item.attestation = payload
        db.commit()
    assert submit(client, preview, home).status_code == 409
