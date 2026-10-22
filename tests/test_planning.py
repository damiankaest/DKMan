from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from dkman.auth import Principal, current_principal
from dkman.config import Settings
from dkman.jobs import recover
from dkman.main import create_app
from dkman.models import (
    AppInstallation,
    AppPlan,
    AppRequest,
    ApprovalRequest,
    AuditEvent,
    Base,
    Job,
    JobEvent,
    utcnow,
)

REQUIREMENTS = {
    "title": "Garten",
    "goal": "Pflanzen gemeinsam pflegen",
    "features": ["Pflanzen verwalten", "Gießaufgaben"],
    "entities": ["Pflanze"],
    "screens": ["Übersicht"],
    "acceptance_checks": ["Neue Pflanze bleibt gespeichert"],
}


def create(client, key=None, **extra):
    return client.post(
        "/api/v1/app-requests",
        json={"requirements": REQUIREMENTS, **extra},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def plans(client, request):
    return client.get(f"/api/v1/app-requests/{request['id']}/plans").json()


def review(client, plan, key=None):
    return client.post(
        f"/api/v1/app-plans/{plan['id']}/approve",
        json={"content_hash": plan["content_hash"]},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def approve(client, job):
    binding = client.get(f"/api/v1/jobs/{job['id']}/approval").json()
    body = {
        key: binding[key]
        for key in ["subject", "action", "resource_type", "resource_id", "plan_hash", "expires_at"]
    }
    return client.post(
        f"/api/v1/approvals/{binding['id']}/decision", json={**body, "decision": "approve"}
    )


def revision(client, request, key=None, **extra):
    return client.post(
        f"/api/v1/app-requests/{request['id']}/plans",
        json={
            "expected_revision": request["current_revision"],
            "requirements": {**REQUIREMENTS, "features": ["Fotos verwalten"]},
            **extra,
        },
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def test_auth_roles_and_private_requests(client, as_user):
    assert create(client).status_code == 401
    as_user("alice", ["operator"])
    assert create(client).status_code == 403
    as_user("alice")
    item = create(client).json()
    plan = plans(client, item)[0]
    assert review(client, plan).status_code == 403
    as_user("bob", ["developer"])
    assert client.get("/api/v1/app-requests").json() == []
    assert client.get(f"/api/v1/app-requests/{item['id']}").status_code == 404
    assert client.get(f"/api/v1/app-plans/{plan['id']}").status_code == 404
    assert client.get(f"/api/v1/app-requests/{item['id']}/plans").status_code == 404
    assert revision(client, item).status_code == 404
    as_user("admin", ["admin"])
    assert client.get("/api/v1/app-requests").json()[0]["id"] == item["id"]


def test_request_idempotency_and_revision_history(client, as_user, engine):
    as_user()
    first = create(client, "same")
    assert first.status_code == 201
    item = first.json()
    assert first.headers["location"].endswith(item["id"])
    original = plans(client, item)[0]
    assert original["document"]["planning_mode"] == "manual"
    assert create(client, "same").json()["id"] == item["id"]
    assert (
        create(client, "same", requirements={**REQUIREMENTS, "goal": "Anderes Ziel"}).status_code
        == 409
    )
    newer = revision(client, item, "rev2")
    assert newer.status_code == 201
    assert newer.json()["revision"] == 2
    assert revision(client, item, "rev2").json()["id"] == newer.json()["id"]
    assert revision(client, item).status_code == 409
    history = plans(client, item)
    assert [p["revision"] for p in history] == [2, 1]
    assert history[1] == original
    assert create(client, "same").json()["current_revision"] == 2
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AppRequest)) == 1
        assert db.scalar(select(func.count()).select_from(AppPlan)) == 2
        assert len(list(db.scalars(select(AuditEvent)))) == 3


@pytest.mark.parametrize(
    "extra",
    [
        {"subject": "admin"},
        {"image": "evil:latest"},
        {"requirements": {**REQUIREMENTS, "features": []}},
        {"requirements": {**REQUIREMENTS, "title": "  "}},
        {"requirements": {**REQUIREMENTS, "shell": "rm -rf /"}},
    ],
)
def test_typed_bounded_requirements(client, as_user, extra):
    as_user()
    assert create(client, **extra).status_code == 422
    assert client.get("/api/v1/app-requests").json() == []


def test_household_scope_is_rechecked_and_does_not_share_requests(client, as_user):
    as_user("alice")
    person = client.put("/api/v1/me/profile").json()["id"]
    as_user("admin", ["admin"])
    household = client.post("/api/v1/households", json={"name": "Zuhause"}).json()["id"]
    member_path = f"/api/v1/households/{household}/members/{person}"
    as_user("alice")
    assert create(client, household_id=household).status_code == 404
    as_user("admin", ["admin"])
    assert client.put(member_path).status_code == 204
    as_user("alice")
    item = create(client, "home", household_id=household).json()
    old = plans(client, item)[0]
    as_user("admin", ["admin"])
    assert client.delete(member_path).status_code == 204
    as_user("alice")
    assert client.get("/api/v1/app-requests").json() == []
    assert create(client, "home", household_id=household).status_code == 404
    assert revision(client, item).status_code == 404
    assert client.get(f"/api/v1/app-plans/{old['id']}").status_code == 404


def test_approval_uses_job_contract_and_only_records_plan(client, as_user, engine):
    as_user()
    item = create(client).json()
    plan = plans(client, item)[0]
    as_user("admin", ["admin"])
    result = review(client, plan, "review")
    assert result.status_code == 202
    job = result.json()
    assert job["action"] == "app_plan.approve"
    assert job["state"] == "waiting_approval"
    assert review(client, plan, "review").json()["id"] == job["id"]
    assert review(client, plan).status_code == 409
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    assert approve(client, job).status_code == 200
    as_user("different-admin", ["admin"])
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 403
    as_user("admin", ["admin"])
    finished = client.post(f"/api/v1/jobs/{job['id']}/run").json()
    assert finished["state"] == "succeeded"
    assert finished["result"]["effect"] == "plan_recorded"
    assert review(client, plan, "review").json()["state"] == "succeeded"
    assert review(client, plan).status_code == 409
    assert client.get(f"/api/v1/app-plans/{plan['id']}").json()["approved_job_id"] == job["id"]
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AppInstallation)) == 0
        assert db.scalar(select(ApprovalRequest)).state == "consumed"
        assert [
            e.sequence for e in db.scalars(select(JobEvent).order_by(JobEvent.sequence))
        ] == list(range(1, 6))


def test_new_revision_cannot_inherit_or_execute_old_approval(client, as_user):
    as_user("admin", ["admin"])
    item = create(client).json()
    old = plans(client, item)[0]
    job = review(client, old).json()
    assert approve(client, job).status_code == 200
    new = revision(client, item).json()
    outcome = client.post(f"/api/v1/jobs/{job['id']}/run").json()
    assert outcome["state"] == "failed"
    assert outcome["failure_code"] == "app_plan_superseded"
    assert client.get(f"/api/v1/app-plans/{old['id']}").json()["approved_job_id"] is None
    assert new["approved_job_id"] is None
    assert review(client, old).status_code == 409
    assert review(client, new).status_code == 202


def test_changed_snapshot_and_wrong_hash_cannot_be_approved(client, as_user, engine):
    as_user("admin", ["admin"])
    item = create(client).json()
    plan = plans(client, item)[0]
    assert review(client, {**plan, "content_hash": "0" * 64}).status_code == 409
    job = review(client, plan).json()
    assert approve(client, job).status_code == 200
    with Session(engine) as db:
        stored = db.get(AppPlan, plan["id"])
        stored.document = {**stored.document, "household_id": "changed"}
        db.commit()
    result = client.post(f"/api/v1/jobs/{job['id']}/run").json()
    assert result["state"] == "failed"
    assert result["failure_code"] == "app_plan_changed"
    with Session(engine) as db:
        assert db.get(AppPlan, plan["id"]).approved_job_id is None


def test_create_is_atomic_when_audit_fails(client, as_user, engine):
    as_user()
    with patch("dkman.planning.audit", side_effect=SQLAlchemyError("sensitive database content")):
        response = create(client)
    assert response.status_code == 503
    assert "sensitive" not in response.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AppRequest)) == 0
        assert db.scalar(select(func.count()).select_from(AppPlan)) == 0


def test_failed_completion_cannot_publish_an_approval_or_auto_retry(client, as_user, engine):
    as_user("admin", ["admin"])
    item = create(client).json()
    plan = plans(client, item)[0]
    job = review(client, plan).json()
    assert approve(client, job).status_code == 200
    with patch("dkman.planning.finish", side_effect=SQLAlchemyError("private completion error")):
        response = client.post(f"/api/v1/jobs/{job['id']}/run")
    assert response.status_code == 503
    assert "private" not in response.text
    with Session(engine) as db:
        assert db.get(AppPlan, plan["id"]).approved_job_id is None
        stored = db.get(Job, job["id"])
        assert stored.state == "running"
        stored.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        recover(db)
        assert db.get(Job, job["id"]).state == "reconciliation_required"
        assert db.get(AppPlan, plan["id"]).approved_job_id is None
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409


def test_revision_failure_keeps_the_previous_document_and_counter(client, as_user, engine):
    as_user()
    item = create(client).json()
    original = plans(client, item)[0]
    with patch("dkman.planning.audit", side_effect=SQLAlchemyError("private revision error")):
        response = revision(client, item)
    assert response.status_code == 503
    assert client.get(f"/api/v1/app-requests/{item['id']}").json()["current_revision"] == 1
    assert plans(client, item) == [original]


def test_fresh_process_preserves_revisions_and_never_auto_approves(tmp_path):
    url = f"sqlite:///{tmp_path / 'planning.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    def application():
        app = create_app(Settings(), engine)
        app.dependency_overrides[current_principal] = lambda: Principal(
            "admin", "Admin", frozenset({"admin"})
        )
        return app

    with TestClient(application()) as first:
        item = create(first).json()
        plan = plans(first, item)[0]
        job = review(first, plan).json()
    with TestClient(application()) as second:
        assert plans(second, item)[0] == plan
        assert second.get(f"/api/v1/jobs/{job['id']}").json()["state"] == "waiting_approval"
        assert second.get(f"/api/v1/app-plans/{plan['id']}").json()["approved_job_id"] is None
    with Session(engine) as db:
        approval = db.scalar(select(ApprovalRequest))
        approval.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        recover(db)
        assert db.get(Job, job["id"]).state == "expired"
        assert db.get(AppPlan, plan["id"]).approved_job_id is None
    engine.dispose()
