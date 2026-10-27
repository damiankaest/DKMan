"""Authenticated, approved-plan bound source workspaces."""

import io
import json
from uuid import uuid4
from zipfile import ZipFile

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_planning import approve, create, plans, review, revision

from dkman.models import AuditEvent, ForgeWorkspace, Job


def generate(client, plan, key=None, **changes):
    return client.post(
        f"/api/v1/app-plans/{plan['id']}/workspaces",
        json={
            "template": "fullstack-fastapi-react",
            "content_hash": plan["content_hash"],
            **changes,
        },
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def prepare(client, as_user):
    as_user("alice", ["developer"])
    item = create(client).json()
    plan = plans(client, item)[0]
    assert generate(client, plan).status_code == 409
    as_user("admin", ["admin"])
    job = review(client, plan).json()
    assert approve(client, job).status_code == 200
    assert client.post(f"/api/v1/jobs/{job['id']}/run").json()["state"] == "succeeded"
    as_user("alice", ["developer"])
    return item, plan


def test_approved_plan_workspace_is_persistent_private_and_downloadable(client, as_user, engine):
    item, plan = prepare(client, as_user)
    first = generate(client, plan, "same")
    assert first.status_code == 201
    workspace = first.json()
    assert workspace["plan_id"] == plan["id"]
    assert "backend/app/main.py" in workspace["files"]
    assert "web/src/App.tsx" in workspace["files"]
    assert generate(client, plan, "same").json() == workspace
    assert generate(client, plan, "same", template="python-api").status_code == 409
    assert generate(client, plan, content_hash="b" * 64).status_code == 409
    assert generate(client, plan, extra="not allowed").status_code == 422
    assert client.get(f"/api/v1/app-plans/{plan['id']}/workspaces").json() == [workspace]
    archive = client.get(f"/api/v1/forge/workspaces/{workspace['id']}/archive")
    assert archive.status_code == 200 and archive.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(archive.content)) as zipped:
        assert sorted(zipped.namelist()) == workspace["files"]
        data = json.loads(zipped.read("plan.json"))
        assert data["content_hash"] == plan["content_hash"]
        assert data["requirements"]["title"] == "Garten"
        assert "BUILD_ARTIFACT_REQUIRED" in zipped.read("dkman.yaml.template").decode()
    assert (
        archive.content == client.get(f"/api/v1/forge/workspaces/{workspace['id']}/archive").content
    )
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ForgeWorkspace)) == 1
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "forge.workspace.created"))
        assert audit is not None and audit.resource_id == workspace["id"]
    as_user("bob", ["developer"])
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}").status_code == 404
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}/archive").status_code == 404
    assert generate(client, plan).status_code == 404
    as_user("alice", ["member"])
    assert generate(client, plan).status_code == 403
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}").status_code == 404
    as_user("alice", ["developer"])
    assert revision(client, item).status_code == 201
    assert generate(client, plan).status_code == 409
    # Historic source remains accessible to its owner, but is not a new build approval.
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}").status_code == 200


def test_workspace_integrity_is_checked_against_stored_binding(client, as_user, engine):
    _, plan = prepare(client, as_user)
    workspace = generate(client, plan).json()
    with Session(engine) as db:
        item = db.get(ForgeWorkspace, workspace["id"])
        item.bundle = {**item.bundle, "files": {"../escape": "bad"}}
        db.commit()
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}").status_code == 409
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}/archive").status_code == 409


def test_requires_authentication_and_strict_input(client, as_user):
    assert client.post("/api/v1/app-plans/x/workspaces", json={}).status_code == 401
    as_user("alice", ["developer"])
    assert client.post("/api/v1/app-plans/x/workspaces", json={}).status_code == 422


def test_membership_revocation_revokes_source_access(client, as_user):
    as_user("alice", ["developer"])
    profile = client.put("/api/v1/me/profile").json()
    as_user("admin", ["admin"])
    home = client.post("/api/v1/households", json={"name": "Home"}).json()
    membership = f"/api/v1/households/{home['id']}/members/{profile['id']}"
    assert client.put(membership).status_code == 204
    as_user("alice", ["developer"])
    item = create(client, household_id=home["id"]).json()
    plan = plans(client, item)[0]
    as_user("admin", ["admin"])
    job = review(client, plan).json()
    assert approve(client, job).status_code == 200
    assert client.post(f"/api/v1/jobs/{job['id']}/run").json()["state"] == "succeeded"
    as_user("alice", ["developer"])
    workspace = generate(client, plan).json()
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}/archive").status_code == 200
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}/build-input").status_code == 200
    as_user("admin", ["admin"])
    assert client.delete(membership).status_code == 204
    as_user("alice", ["developer"])
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}").status_code == 404
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}/archive").status_code == 404
    assert client.get(f"/api/v1/forge/workspaces/{workspace['id']}/build-input").status_code == 404
    assert client.get(f"/api/v1/app-plans/{plan['id']}/workspaces").status_code == 404
    assert generate(client, plan).status_code == 404


def test_distinct_idempotency_keys_create_separate_equal_snapshots(client, as_user):
    _, plan = prepare(client, as_user)
    first = generate(client, plan, "first").json()
    second = generate(client, plan, "second").json()
    assert first["id"] != second["id"]
    assert first["bundle_hash"] == second["bundle_hash"]


def test_build_input_requires_current_authorized_approved_source(client, as_user):
    item, plan = prepare(client, as_user)
    workspace = generate(client, plan).json()
    path = f"/api/v1/forge/workspaces/{workspace['id']}/build-input"
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["workspace_id"] == workspace["id"]
    assert response.json()["bundle_hash"] == workspace["bundle_hash"]
    assert response.json()["bundle"]["request"]["content_hash"] == plan["content_hash"]
    assert response.headers["cache-control"] == "no-store"
    as_user("bob", ["developer"])
    assert client.get(path).status_code == 404
    as_user("alice", ["member"])
    assert client.get(path).status_code == 404
    as_user("alice", ["developer"])
    assert revision(client, item).status_code == 201
    assert client.get(path).status_code == 409
