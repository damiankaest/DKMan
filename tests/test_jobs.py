from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from dkman.auth import Principal
from dkman.config import Settings
from dkman.job_schemas import JobSubmission
from dkman.jobs import begin_execution, claim, finish, recover, submit
from dkman.main import create_app
from dkman.models import (
    ApprovalRequest,
    AuditEvent,
    Base,
    Job,
    JobEvent,
    ServiceManifest,
    utcnow,
)
from dkman.seed import seed

ADMIN = Principal("alice", "Alice", frozenset({"admin"}))


@pytest.fixture
def registered(engine, as_user):
    as_user("alice", ["admin"])
    with Session(engine) as db:
        seed(db, Path(__file__).resolve().parents[1] / "examples")


def create(client, key="request-1", **overrides):
    return client.post(
        "/api/v1/jobs",
        headers={"Idempotency-Key": key},
        json={
            "action": "registry.validate",
            "resource_id": "demo-notes",
            **overrides,
        },
    )


def approval(client, job):
    result = client.get(f"/api/v1/jobs/{job['id']}/approval")
    assert result.status_code == 200
    return result.json()


def decision(client, item, decision="approve", **overrides):
    body = {
        k: item[k]
        for k in ["subject", "action", "resource_type", "resource_id", "plan_hash", "expires_at"]
    }
    return client.post(
        f"/api/v1/approvals/{item['id']}/decision", json={**body, "decision": decision, **overrides}
    )


def test_job_routes_require_auth_and_admin(client, as_user):
    assert client.get("/api/v1/jobs").status_code == 401
    assert create(client).status_code == 401
    for roles in [["member"], ["developer"], ["operator"]]:
        as_user("bob", roles)
        assert create(client).status_code == 403
        assert client.post("/api/v1/jobs/missing/run").status_code == 403
        assert client.post("/api/v1/jobs/missing/cancel").status_code == 403
        assert client.post("/api/v1/approvals/missing/decision", json={}).status_code == 403


def test_real_validation_approval_audit_and_cursor(client, registered, engine):
    response = create(client)
    assert response.status_code == 202
    job = response.json()
    assert response.headers["location"] == f"/api/v1/jobs/{job['id']}"
    assert "lease_token" not in job and "idempotency_key" not in job
    assert job["state"] == "waiting_approval"
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    item = approval(client, job)
    assert decision(client, item).json()["state"] == "approved"
    assert decision(client, item).status_code == 200
    assert decision(client, item, "reject").status_code == 409
    response = client.post(f"/api/v1/jobs/{job['id']}/run")
    assert response.status_code == 200
    assert response.json()["state"] == "succeeded"
    assert response.json()["result"]["valid"] is True
    assert approval(client, job)["state"] == "consumed"
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    assert client.post(f"/api/v1/jobs/{job['id']}/cancel").status_code == 409
    events = client.get(f"/api/v1/jobs/{job['id']}/events").json()
    assert [e["sequence"] for e in events] == [1, 2, 3, 4, 5]
    assert events[-1]["state"] == "succeeded"
    assert len(client.get(f"/api/v1/jobs/{job['id']}/events?after=2&limit=2").json()) == 2
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.resource_id == job["id"])
            )
            == 5
        )


def test_idempotency_replay_conflict_and_subject_scope(client, registered, engine, as_user):
    one = create(client).json()
    two = create(client).json()
    assert one["id"] == two["id"] and one["plan_hash"] == two["plan_hash"]
    assert create(client, resource_id="status-api").status_code == 409
    assert create(client, require_approval=False).status_code == 409
    assert create(client, approval_ttl_seconds=3600).status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        assert db.scalar(select(func.count()).select_from(JobEvent)) == 1
        assert db.scalar(select(func.count()).select_from(ApprovalRequest)) == 1
    as_user("bob", ["admin"])
    assert create(client).json()["id"] != one["id"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject": "bob"},
        {"action": "deployment.install"},
        {"resource_type": "installation"},
        {"resource_id": "status-api"},
        {"plan_hash": "0" * 64},
        {"expires_at": "2030-01-01T00:00:00Z"},
    ],
)
def test_approval_binding_cannot_be_substituted(client, registered, overrides):
    job = create(client).json()
    item = approval(client, job)
    assert decision(client, item, **overrides).status_code == 409
    assert approval(client, job)["state"] == "pending"


def test_jobs_and_approvals_are_private_and_execution_is_identity_bound(
    client, registered, as_user
):
    job = create(client).json()
    item = approval(client, job)
    as_user("bob")
    assert client.get("/api/v1/jobs").json() == []
    for suffix in ["", "/events", "/approval"]:
        assert client.get(f"/api/v1/jobs/{job['id']}{suffix}").status_code == 404
    as_user("bob", ["admin"])
    assert decision(client, item).status_code == 200
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 403
    as_user("alice", ["member"])
    assert client.get(f"/api/v1/jobs/{job['id']}").status_code == 200
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 403


@pytest.mark.parametrize("approved", [False, True])
def test_expired_approval_is_durable_and_cannot_execute(client, registered, engine, approved):
    job = create(client).json()
    item = approval(client, job)
    if approved:
        assert decision(client, item).status_code == 200
    with Session(engine) as db:
        db.scalar(select(ApprovalRequest)).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    # Echo the authoritative expired binding; the decision cannot extend its deadline.
    item = approval(client, job)
    result = client.post(f"/api/v1/jobs/{job['id']}/run") if approved else decision(client, item)
    assert result.status_code == 409
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["state"] == "expired"
    assert approval(client, job)["state"] == "expired"


def test_cancel_and_reject_are_terminal(client, registered):
    job = create(client).json()
    item = approval(client, job)
    assert decision(client, item, "reject").json()["state"] == "rejected"
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    another = create(client, key="another").json()
    path = f"/api/v1/jobs/{another['id']}/cancel"
    assert client.post(path).json()["state"] == "cancelled"
    assert client.post(path).json()["state"] == "cancelled"
    assert approval(client, another)["state"] == "cancelled"
    assert decision(client, approval(client, another)).status_code == 409


def test_read_only_job_can_run_without_approval_and_unknown_actions_are_rejected(
    client, registered
):
    job = create(client, require_approval=False).json()
    assert job["state"] == "queued"
    assert client.get(f"/api/v1/jobs/{job['id']}/approval").status_code == 404
    assert client.post(f"/api/v1/jobs/{job['id']}/run").json()["state"] == "succeeded"
    assert create(client, action="deployment.install").status_code == 422
    assert create(client, plan={"shell": "anything"}).status_code == 422
    assert create(client, resource_id="missing").status_code == 409  # key already bound
    assert create(client, key="missing", resource_id="missing").status_code == 404
    assert (
        client.post(
            "/api/v1/jobs", json={"action": "registry.validate", "resource_id": "demo-notes"}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/jobs?limit=101").status_code == 422


def test_changed_manifest_fails_without_false_success(client, registered, engine):
    job = create(client, require_approval=False).json()
    with Session(engine) as db:
        manifest = db.get(ServiceManifest, job["plan"]["manifest_id"])
        manifest.content = {**manifest.content, "name": "Changed"}
        db.commit()
    response = client.post(f"/api/v1/jobs/{job['id']}/run")
    assert response.json()["state"] == "failed"
    assert response.json()["failure_code"] == "manifest_validation_failed"


def test_unexpected_failure_is_sanitized_and_never_retried(client, registered, monkeypatch):
    job = create(client, require_approval=False).json()

    def fail(*_):
        raise RuntimeError("postgresql://secret:password@host")

    monkeypatch.setattr("dkman.job_api.validate_registered_manifest", fail)
    response = client.post(f"/api/v1/jobs/{job['id']}/run")
    assert response.json()["state"] == "reconciliation_required"
    assert "password" not in response.text
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409


def test_recovery_preserves_live_lease_requeues_only_before_start_and_fences_old_worker(
    client,
    registered,
    engine,
):
    job = create(client, require_approval=False).json()
    with Session(engine) as db:
        old = claim(db, job["id"], ADMIN)
        assert recover(db) == 0
        assert recover(db, now=utcnow() + timedelta(seconds=120)) == 1
        assert db.get(Job, job["id"]).state == "queued"
        new = claim(db, job["id"], ADMIN)
        assert new != old
        with pytest.raises(HTTPException):
            begin_execution(db, job["id"], old, ADMIN)
        db.rollback()
        begin_execution(db, job["id"], new, ADMIN)
        assert recover(db, now=utcnow() + timedelta(seconds=120)) == 1
        assert db.get(Job, job["id"]).state == "reconciliation_required"
        with pytest.raises(HTTPException):
            finish(db, job["id"], new, result={"valid": True})
        db.rollback()
        assert recover(db, now=utcnow() + timedelta(seconds=240)) == 0
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409


def test_expiry_between_claim_and_execution_blocks_consumption(client, registered, engine):
    job = create(client).json()
    assert decision(client, approval(client, job)).status_code == 200
    with Session(engine) as db:
        token = claim(db, job["id"], ADMIN)
        db.scalar(select(ApprovalRequest)).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException):
            begin_execution(db, job["id"], token, ADMIN)
        assert db.get(Job, job["id"]).state == "expired"
        assert db.scalar(select(ApprovalRequest)).consumed_at is None


def test_tampered_persisted_approval_is_rejected_at_execution(client, registered, engine):
    job = create(client).json()
    assert decision(client, approval(client, job)).status_code == 200
    with Session(engine) as db:
        db.scalar(select(ApprovalRequest)).subject = "bob"
        db.commit()
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["state"] == "failed"


def test_job_event_and_approval_creation_roll_back_together(
    client, registered, engine, monkeypatch
):
    import dkman.jobs

    original = dkman.jobs.event

    def fail(*_):
        raise SQLAlchemyError("sensitive-database-content")

    monkeypatch.setattr(dkman.jobs, "event", fail)
    response = create(client)
    assert response.status_code == 503
    assert "sensitive-database-content" not in response.text
    with Session(engine) as db:
        for model in [Job, JobEvent, ApprovalRequest]:
            assert db.scalar(select(func.count()).select_from(model)) == 0
    monkeypatch.setattr(dkman.jobs, "event", original)
    assert create(client).status_code == 202


@pytest.mark.parametrize("started,expected", [(False, "queued"), (True, "reconciliation_required")])
def test_persisted_jobs_recover_in_new_application_lifespan(tmp_path, started, expected):
    url = f"sqlite:///{tmp_path / 'restart-test.db'}"
    old_engine = create_engine(url)
    Base.metadata.create_all(old_engine)
    with Session(old_engine) as db:
        seed(db, Path(__file__).resolve().parents[1] / "examples")
        job_id = submit(
            db,
            JobSubmission(
                action="registry.validate", resource_id="demo-notes", require_approval=False
            ),
            "restart",
            ADMIN,
            "0" * 36,
        ).id
        token = claim(db, job_id, ADMIN)
        if started:
            begin_execution(db, job_id, token, ADMIN)
        db.get(Job, job_id).lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    old_engine.dispose()
    new_engine = create_engine(url, connect_args={"check_same_thread": False})
    with TestClient(create_app(Settings(), new_engine)):
        with Session(new_engine) as db:
            assert db.get(Job, job_id).state == expected
            assert db.get(Job, job_id).lease_token is None
    new_engine.dispose()
