"""Core lifecycle security/recovery; real Docker and OIDC run in notes-journey."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_installations import KEY, approve, configured, plan

from dkman.deployments.auth import verify_delegation
from dkman.deployments.client import AdapterUnavailable
from dkman.deployments.contracts import OperationView, RuntimeView
from dkman.jobs import recover
from dkman.models import (
    AppInstallation,
    ApprovalRequest,
    AuditEvent,
    Household,
    Job,
    ServiceInstance,
    utcnow,
)

# Reuse the curated installation fixture, not an alternate production path.
__all__ = ["configured"]


class LifecycleTransport:
    def __init__(self, engine):
        self.engine = engine
        self.calls = []
        self.reads = []
        self.results = {}
        self.state = "running"
        self.lose = False
        self.unproven = False
        self.fail_read = False
        self.mismatch = None
        self.logtext = (
            "<script>window.pwned=1</script> password=private "
            "api_key=supersecret Authorization: Bearer hidden"
        )

    def execute(self, operation_id, command, token):
        grant = verify_delegation(token, KEY)
        assert grant.plan_hash == command.plan_hash
        assert grant.resource_id == command.plan.installation_id
        if command.action in {"start", "stop", "restart"}:
            with Session(self.engine) as db:
                job = db.get(Job, str(operation_id))
                assert job.state == "running" and job.execution_started_at
                assert command.lifecycle.plan_hash == job.plan_hash
                assert command.lifecycle.subject == grant.sub
                approval = db.get(ApprovalRequest, str(grant.approval_id))
                assert approval.state == "consumed" and approval.consumed_at
            self.calls.append(command.action)
            self.state = "stopped" if command.action == "stop" else "running"
        result = OperationView(
            operation_id=operation_id,
            installation_id=command.plan.installation_id,
            action=command.action,
            plan_hash=command.plan_hash,
            state="reconciliation_required" if self.unproven else "succeeded",
            created_at=utcnow(),
            finished_at=utcnow(),
            runtime=RuntimeView(
                installation_id=command.plan.installation_id,
                state=self.state,
                container_id="c" * 64,
                observed_at=utcnow(),
            ),
            logs=self.logtext if command.action == "logs" else None,
        )
        if self.mismatch:
            field, value = self.mismatch
            result = result.model_copy(update={field: value})
        self.results[operation_id] = result
        if self.lose:
            raise AdapterUnavailable("password=private provider error")
        return result

    def operation(self, operation_id, token, *, reconcile=False):
        assert verify_delegation(token, KEY).action == "reconcile"
        assert reconcile is True
        self.reads.append(operation_id)
        if self.fail_read:
            raise AdapterUnavailable("secret provider error")
        return self.results[operation_id]


@pytest.fixture
def installed(client, configured, engine, app):
    job = plan(client, configured).json()
    approve(client, job)
    assert client.post(f"/api/v1/jobs/{job['id']}/run").json()["state"] == "succeeded"
    transport = LifecycleTransport(engine)
    app.state.deployment_client = transport
    return job["resource_id"], transport, configured[0]


def submit(client, installed, action="stop", key="runtime-1", **extra):
    return client.post(
        f"/api/v1/installations/{installed[0]}/{action}",
        json=extra,
        headers={"Idempotency-Key": key},
    )


def execute(client, job):
    approve(client, job)
    return client.post(f"/api/v1/jobs/{job['id']}/run")


def operator(client, installed, as_user, operate=True):
    as_user("op", ("operator", "member"))
    person = client.put("/api/v1/me/profile").json()
    as_user("admin", ("admin",))
    client.put(f"/api/v1/households/{installed[2]}/members/{person['id']}")
    client.put(f"/api/v1/installations/{installed[0]}/grants/{person['id']}")
    if operate:
        assert (
            client.put(
                f"/api/v1/installations/{installed[0]}/runtime-grants/{person['id']}"
            ).status_code
            == 204
        )
    as_user("op", ("operator", "member"))
    return person


def test_mutations_preserve_installation_and_have_action_specific_outcomes(
    client, installed, engine
):
    for action in ["stop", "start", "restart"]:
        job = submit(client, installed, action, action).json()
        assert job["plan"]["action"] == action and job["plan"]["subject"] == "admin"
        from dkman.jobs import digest

        assert job["plan_hash"] == digest(job["plan"])
        assert job["plan_hash"] != digest(job["plan"]["runtime"])
        assert client.get("/api/v1/apps").json()[0]["route"] is None
        result = execute(client, job)
        assert result.status_code == 200 and result.json()["state"] == "succeeded"
        state = client.get(f"/api/v1/installations/{installed[0]}/status").json()
        assert state["state"] == ("stopped" if action == "stop" else "running")
        assert state["observed_at"] and state["blocked_job_id"] is None
        app = client.get("/api/v1/apps").json()[0]
        assert (app["route"] is None) == (action == "stop")
    assert installed[1].calls == ["stop", "start", "restart"]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AppInstallation)) == 1
        assert db.get(AppInstallation, installed[0]).desired_state == "running"


@pytest.mark.parametrize("roles", [("member",), ("developer",), ("operator",)])
def test_use_grant_is_not_runtime_authority(client, installed, as_user, roles):
    operator(client, installed, as_user, operate=False)
    as_user("op", roles)
    expected = 404 if "operator" in roles else 403
    assert submit(client, installed).status_code == expected
    for read in ["status", "logs", "jobs"]:
        assert client.get(f"/api/v1/installations/{installed[0]}/{read}").status_code == expected
    assert installed[1].calls == []


def test_operator_full_flow_and_foreign_installation_isolation(client, installed, as_user):
    operator(client, installed, as_user)
    assert client.get("/api/v1/runtime/installations").json()[0]["id"] == installed[0]
    foreign = (str(uuid4()), installed[1], installed[2])
    assert submit(client, foreign).status_code == 404
    assert client.get(f"/api/v1/installations/{foreign[0]}/logs").status_code == 404
    job = submit(client, installed).json()
    as_user("other", ("operator",))
    assert client.get(f"/api/v1/jobs/{job['id']}").status_code == 404
    as_user("op", ("operator", "member"))
    assert execute(client, job).json()["state"] == "succeeded"
    assert client.get(f"/api/v1/installations/{installed[0]}/logs").status_code == 200
    # Operator authority does not allow an installation, registry job, or permission write.
    assert (
        client.post(
            "/api/v1/jobs",
            json={"action": "registry.validate", "resource_id": "demo-notes"},
            headers={"Idempotency-Key": "registry"},
        ).status_code
        == 403
    )


@pytest.mark.parametrize("revoked", ["role", "grant", "membership"])
def test_rights_rechecked_before_decision_and_execution(client, installed, as_user, revoked):
    person = operator(client, installed, as_user)
    job = submit(client, installed).json()
    approve(client, job)
    as_user("admin", ("admin",))
    if revoked == "grant":
        client.delete(f"/api/v1/installations/{installed[0]}/runtime-grants/{person['id']}")
    if revoked == "membership":
        client.delete(f"/api/v1/households/{installed[2]}/members/{person['id']}")
    as_user("op", ("member",) if revoked == "role" else ("operator",))
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code in {403, 404}
    assert installed[1].calls == []


def test_keys_conflict_and_different_keys_cannot_bypass_reservation(client, installed):
    first = submit(client, installed).json()
    assert submit(client, installed).json()["id"] == first["id"]
    assert submit(client, installed, "start").status_code == 409
    assert submit(client, installed, "start", "different").status_code == 409
    assert client.post(f"/api/v1/jobs/{first['id']}/cancel").status_code == 200
    assert submit(client, installed).json()["id"] == first["id"]
    assert submit(client, installed, "start", "different").status_code == 202


@pytest.mark.parametrize(
    "field,value",
    [
        ("action", "deployment.start"),
        ("subject", "other"),
        ("resource_id", str(uuid4())),
        ("resource_type", "app_definition"),
        ("plan_hash", "f" * 64),
        ("expires_at", "2099-01-01T00:00:00Z"),
    ],
)
def test_approval_binding_must_match_entire_lifecycle(client, installed, field, value):
    job = submit(client, installed).json()
    binding = client.get(f"/api/v1/jobs/{job['id']}/approval").json()
    body = {
        key: binding[key]
        for key in ["subject", "action", "resource_type", "resource_id", "plan_hash", "expires_at"]
    }
    body[field] = value
    assert (
        client.post(
            f"/api/v1/approvals/{binding['id']}/decision", json={**body, "decision": "approve"}
        ).status_code
        == 409
    )
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    assert installed[1].calls == []


def test_expiry_and_changed_runtime_fail_before_dispatch(client, installed, engine):
    job = submit(client, installed).json()
    binding = approve(client, job)
    with Session(engine) as db:
        db.get(ApprovalRequest, binding["id"]).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    job = submit(client, installed, key="changed").json()
    approve(client, job)
    with Session(engine) as db:
        item = db.get(AppInstallation, installed[0])
        group = Household(name="Different household")
        db.add(group)
        db.flush()
        item.household_id = group.id
        db.commit()
    result = client.post(f"/api/v1/jobs/{job['id']}/run").json()
    assert result["state"] == "failed" and installed[1].calls == []


def test_read_only_status_logs_redaction_and_failure_codes(client, installed, engine):
    transport = installed[1]
    response = client.get(f"/api/v1/installations/{installed[0]}/logs")
    assert response.status_code == 200
    assert all(secret not in response.text for secret in ["private", "supersecret", "hidden"])
    assert "<script>" in response.json()["text"]  # The UI must render text, not HTML.
    transport.logtext = ("ü" * 200 + "\n") * 200
    response = client.get(f"/api/v1/installations/{installed[0]}/logs").json()
    assert len(response["text"].encode()) <= 8192 and len(response["text"].splitlines()) <= 100
    transport.lose = True
    status = client.get(f"/api/v1/installations/{installed[0]}/status").json()
    assert status["state"] == "unknown" and status["reason"] == "runtime_observation_unavailable"
    response = client.get(f"/api/v1/installations/{installed[0]}/logs")
    assert response.status_code == 503 and "private" not in response.text
    assert client.get("/api/v1/apps").json()[0]["route"] is None
    assert transport.calls == []
    with Session(engine) as db:
        assert "private" not in str([row.outcome for row in db.scalars(select(AuditEvent))])


@pytest.mark.parametrize("unproven", [False, True])
def test_lost_reply_recovery_requires_matching_completed_operation(
    client, installed, engine, unproven
):
    job = submit(client, installed, "restart").json()
    installed[1].lose = True
    installed[1].unproven = unproven
    assert execute(client, job).json()["state"] == "reconciliation_required"
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    assert submit(client, installed, "stop", "another").status_code == 409
    # Even a fresh healthy poll never unlocks or supplies a launch URL.
    installed[1].lose = False
    assert client.get(f"/api/v1/installations/{installed[0]}/status").json()["state"] in {
        "running",
        "unknown",
    }
    assert client.get("/api/v1/apps").json()[0]["route"] is None
    result = client.post(f"/api/v1/jobs/{job['id']}/reconcile").json()
    assert result["state"] == ("reconciliation_required" if unproven else "succeeded")
    assert installed[1].calls == ["restart"]
    if unproven:
        installed[1].fail_read = True
        assert client.post(f"/api/v1/jobs/{job['id']}/reconcile").status_code == 503
        assert submit(client, installed, "stop", "yet-another").status_code == 409


def test_crash_running_marker_recovered_in_new_session_never_resends(client, installed, engine):
    job = submit(client, installed, "restart").json()
    assert execute(client, job).json()["state"] == "succeeded"
    with Session(engine) as db:
        current = db.get(Job, job["id"])
        current.state = "running"
        current.lease_expires_at = utcnow() - timedelta(seconds=1)
        current.lease_token = str(uuid4())
        db.commit()
    with Session(engine) as fresh:
        assert recover(fresh) == 1
    assert submit(client, installed, "stop", "blocked").status_code == 409
    assert client.post(f"/api/v1/jobs/{job['id']}/reconcile").json()["state"] == "succeeded"
    assert installed[1].calls == ["restart"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("action", "start"),
        ("plan_hash", "f" * 64),
        ("operation_id", uuid4()),
        ("installation_id", uuid4()),
        ("finished_at", None),
        ("runtime", None),
    ],
)
def test_wrong_operations_never_close_a_runtime_job(client, installed, field, value):
    job = submit(client, installed, "restart").json()
    installed[1].mismatch = (field, value)
    assert execute(client, job).json()["state"] == "reconciliation_required"
    assert installed[1].calls == ["restart"]


def test_delayed_healthy_observation_cannot_overwrite_newer_stop(client, installed, engine):
    from dkman.deployment_api import record_runtime

    older = utcnow()
    job = submit(client, installed).json()
    assert execute(client, job).json()["state"] == "succeeded"
    with Session(engine) as db:
        record_runtime(
            db,
            installed[0],
            RuntimeView(
                installation_id=UUID(installed[0]),
                state="running",
                observed_at=older,
                container_id="c" * 64,
            ),
        )
        db.commit()
        assert db.get(ServiceInstance, installed[0]).status == "stopped"
    assert client.get("/api/v1/apps").json()[0]["route"] is None


@pytest.mark.parametrize(
    "defect", [None, "missing", "operation", "hash", "action", "time", "resource"]
)
def test_only_bound_durable_non_execution_proof_can_close_a_rejection(
    client, installed, engine, monkeypatch, defect
):
    from dkman.deployments.contracts import RejectionEvidence

    job = submit(client, installed).json()

    def rejected(operation_id, command, token):
        grant = verify_delegation(token, KEY)
        with Session(engine) as db:
            running = db.get(Job, str(operation_id))
            assert running.state == "running" and running.execution_started_at
            assert db.get(ApprovalRequest, str(grant.approval_id)).state == "consumed"
        proof = RejectionEvidence(
            operation_id=operation_id,
            installation_id=command.plan.installation_id,
            action=command.action,
            plan_hash=command.plan_hash,
            reason="curation_rejected",
            observed_at=utcnow(),
        )
        if defect in {"operation", "hash", "action", "time", "resource"}:
            proof = proof.model_copy(
                update={
                    "operation": {"operation_id": uuid4()},
                    "hash": {"plan_hash": "f" * 64},
                    "action": {"action": "restart"},
                    "time": {"observed_at": utcnow() - timedelta(days=1)},
                    "resource": {"installation_id": uuid4()},
                }[defect]
            )
        return OperationView(
            operation_id=operation_id,
            installation_id=command.plan.installation_id,
            action=command.action,
            plan_hash=command.plan_hash,
            state="failed",
            created_at=utcnow(),
            finished_at=utcnow(),
            failure_code="curation_rejected",
            rejection=None if defect == "missing" else proof,
        )

    monkeypatch.setattr(installed[1], "execute", rejected)
    result = execute(client, job).json()
    assert result["state"] == ("failed" if defect is None else "reconciliation_required")
    assert installed[1].calls == []
    assert submit(client, installed, "restart", "next").status_code == (
        202 if defect is None else 409
    )
    if defect is None:
        assert len(result["result"]["evidence_hash"]) == 64
        assert result["result"]["evidence_kind"] == "preflight_rejected"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AppInstallation)) == 1
