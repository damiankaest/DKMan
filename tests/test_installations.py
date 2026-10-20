"""Test doubles only for transport; the actual Docker/OIDC journey is a separate CI gate."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dkman.deployment_health import poll_once
from dkman.deployments.auth import verify_delegation
from dkman.deployments.client import AdapterUnavailable
from dkman.deployments.contracts import Catalog, CuratedImage, OperationView, RuntimeView
from dkman.jobs import recover
from dkman.models import (
    AppInstallation,
    ApprovalRequest,
    DeploymentTarget,
    Household,
    Job,
    ServiceInstance,
    ServiceManifest,
    utcnow,
)
from dkman.seed import seed

KEY = b"test-only-installation-transport-key-at-least-32-bytes"


class TestTransport:
    __test__ = False

    def __init__(self, engine):
        self.engine = engine
        self.calls = []
        self.reads = []
        self.results = {}
        self.lose_response = False
        self.read_error = False
        self.unproven = False

    def execute(self, operation_id, command, token):
        grant = verify_delegation(token, KEY)
        assert grant.jti == operation_id and grant.plan_hash == command.plan.plan_hash
        if command.action == "install":
            with Session(self.engine) as db:
                assert db.get(Job, str(operation_id)).state == "running"
                approval = db.get(ApprovalRequest, str(grant.approval_id))
                assert approval.state == "consumed"
                assert approval.plan_hash == command.plan.plan_hash
                assert grant.sub == command.plan.context.subject
            self.calls.append(operation_id)
        result = OperationView(
            operation_id=operation_id,
            installation_id=command.plan.installation_id,
            action=command.action,
            plan_hash=command.plan.plan_hash,
            state="reconciliation_required" if self.unproven else "succeeded",
            created_at=utcnow(),
            finished_at=utcnow(),
            runtime=RuntimeView(
                installation_id=command.plan.installation_id,
                state="running",
                observed_at=utcnow(),
                container_id="a" * 64,
            ),
        )
        self.results[operation_id] = result
        if self.lose_response:
            raise AdapterUnavailable("private transport exception must not enter job result")
        return result

    def operation(self, operation_id, token):
        assert verify_delegation(token, KEY).action == "operation.read"
        self.reads.append(operation_id)
        if self.read_error:
            raise AdapterUnavailable()
        return self.results[operation_id]


@pytest.fixture
def configured(app, engine, tmp_path, as_user):
    settings = app.state.settings
    settings.deployment_enabled = True
    settings.deployment_secret_file = tmp_path / "key"
    settings.deployment_secret_file.write_bytes(KEY)
    settings.deployment_catalog_file = tmp_path / "catalog.json"
    settings.deployment_catalog_file.write_text(
        Catalog(
            images=[
                CuratedImage(
                    definition_id="demo-notes",
                    version="0.1.0",
                    image="sha256:" + "a" * 64,
                    database_image="sha256:" + "b" * 64,
                    internal_port=8080,
                    profile="notes-postgres-v1",
                    source_hash="c" * 64,
                )
            ]
        ).model_dump_json()
    )
    with Session(engine) as db:
        seed(db, Path(__file__).resolve().parents[1] / "examples")
        group = Household(name="Test household")
        db.add(group)
        db.commit()
        group_id = group.id
    as_user("admin", ("admin", "member"))
    transport = TestTransport(engine)
    app.state.deployment_client = transport
    return group_id, transport


def plan(client, configured, key="install-1", **changes):
    return client.post(
        "/api/v1/deployments/installations",
        json={"definition_id": "demo-notes", "household_id": configured[0], **changes},
        headers={"Idempotency-Key": key},
    )


def approve(client, job):
    binding = client.get(f"/api/v1/jobs/{job['id']}/approval").json()
    body = {
        key: binding[key]
        for key in ["subject", "action", "resource_type", "resource_id", "plan_hash", "expires_at"]
    }
    result = client.post(
        f"/api/v1/approvals/{binding['id']}/decision", json={**body, "decision": "approve"}
    )
    assert result.status_code == 200
    return binding


def test_plan_replay_conflict_and_no_phantom_installation(client, configured, engine):
    first = plan(client, configured)
    assert first.status_code == 202
    job = first.json()
    assert job["state"] == "waiting_approval" and job["requires_approval"]
    assert job["resource_id"] == job["plan"]["installation_id"]
    assert job["plan"]["context"]["household_id"] == configured[0]
    assert plan(client, configured).json()["id"] == job["id"]
    assert plan(client, configured, definition_id="status-api").status_code == 409
    assert plan(client, configured, key="another").status_code == 409
    assert client.get("/api/v1/apps").json() == []
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(DeploymentTarget)) == 1
        assert db.scalar(select(func.count()).select_from(AppInstallation)) == 0


def test_only_curated_server_plan_accepts_no_docker_parameters(client, configured):
    for extra in [
        {"image": "bad:latest"},
        {"ports": [80]},
        {"require_approval": False},
        {"plan_hash": "a" * 64},
    ]:
        assert plan(client, configured, **extra).status_code == 422
    assert plan(client, configured, definition_id="status-api").status_code == 409
    assert plan(client, configured, household_id=str(uuid4())).status_code == 404


def test_installation_requires_admin_and_requesting_identity(client, configured, as_user):
    job = plan(client, configured).json()
    approve(client, job)
    as_user("other-admin", ("admin",))
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 403
    as_user("member", ("member",))
    assert plan(client, configured).status_code == 403
    assert client.get("/api/v1/deployments/catalog").status_code == 403
    assert client.get(f"/api/v1/jobs/{job['id']}").status_code == 404
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 403
    assert configured[1].calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("subject", "other"),
        ("action", "deployment.remove"),
        ("resource_type", "app_definition"),
        ("resource_id", "other"),
        ("plan_hash", "f" * 64),
    ],
)
def test_install_approval_cannot_be_rebound(client, configured, field, value):
    job = plan(client, configured).json()
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
    assert configured[1].calls == []


def test_expired_approval_never_dispatches_and_releases_reservation(client, configured, engine):
    job = plan(client, configured).json()
    binding = approve(client, job)
    with Session(engine) as db:
        db.get(ApprovalRequest, binding["id"]).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    assert configured[1].calls == []
    assert plan(client, configured, key="replacement").status_code == 202


@pytest.mark.parametrize("change", ["manifest", "catalog", "plan"])
def test_changed_source_or_plan_does_not_execute(client, configured, engine, app, change):
    job = plan(client, configured).json()
    approve(client, job)
    with Session(engine) as db:
        current = db.get(Job, job["id"])
        if change == "manifest":
            manifest = db.get(ServiceManifest, current.plan["context"]["manifest_id"])
            manifest.content = {**manifest.content, "description": "changed"}
        elif change == "plan":
            current.plan = {**current.plan, "memory_mb": 256}
        else:
            app.state.settings.deployment_catalog_file.write_text(Catalog().model_dump_json())
        db.commit()
    result = client.post(f"/api/v1/jobs/{job['id']}/run")
    assert result.json()["state"] == "failed"
    assert configured[1].calls == []


def test_actual_result_materializes_installation_once_and_permissions_still_apply(
    client, configured, engine, as_user
):
    job = plan(client, configured).json()
    approve(client, job)
    result = client.post(f"/api/v1/jobs/{job['id']}/run")
    assert result.status_code == 200 and result.json()["state"] == "succeeded"
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    assert configured[1].calls == [UUID(job["id"])]
    apps = client.get("/api/v1/apps").json()
    assert apps[0]["status"] == "healthy" and apps[0]["route"] == f"/run/{job['resource_id']}/"
    assert client.get(f"/api/v1/apps/{job['resource_id']}/access").json()["subject"] == "admin"
    as_user("member", ("member",))
    profile = client.put("/api/v1/me/profile").json()
    assert client.get(f"/api/v1/apps/{job['resource_id']}/access").status_code == 404
    as_user("admin", ("admin",))
    assert (
        client.put(f"/api/v1/households/{configured[0]}/members/{profile['id']}").status_code == 204
    )
    assert (
        client.put(f"/api/v1/installations/{job['resource_id']}/grants/{profile['id']}").status_code
        == 204
    )
    as_user("member", ("member",))
    assert client.get(f"/api/v1/apps/{job['resource_id']}/access").status_code == 200
    as_user("admin", ("admin",))
    client.delete(f"/api/v1/households/{configured[0]}/members/{profile['id']}")
    as_user("member", ("member",))
    assert client.get(f"/api/v1/apps/{job['resource_id']}/access").status_code == 404
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AppInstallation)) == 1


def test_lost_success_response_reconciles_by_id_without_reexecution(client, configured, engine):
    job = plan(client, configured).json()
    approve(client, job)
    transport = configured[1]
    transport.lose_response = True
    result = client.post(f"/api/v1/jobs/{job['id']}/run").json()
    assert result["state"] == "reconciliation_required"
    assert "private transport" not in str(result)
    assert client.get("/api/v1/apps").json() == []
    assert plan(client, configured, key="duplicate-install").status_code == 409
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    assert client.post(f"/api/v1/jobs/{job['id']}/reconcile").json()["state"] == "succeeded"
    assert transport.calls == [UUID(job["id"])] and transport.reads == [UUID(job["id"])]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AppInstallation)) == 1


def test_restart_after_durable_running_marker_only_reads_authoritative_outcome(
    client, configured, engine
):
    job = plan(client, configured).json()
    approve(client, job)
    client.post(f"/api/v1/jobs/{job['id']}/run")
    with Session(engine) as db:
        # Crash boundary: remote succeeded, local completion transaction did not commit.
        current = db.get(Job, job["id"])
        current.state = "running"
        current.lease_token = str(uuid4())
        current.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with Session(engine) as fresh_process:
        assert recover(fresh_process) == 1
    assert client.post(f"/api/v1/jobs/{job['id']}/reconcile").json()["state"] == "succeeded"
    assert len(configured[1].calls) == 1


def test_unproven_healthy_runtime_or_missing_result_never_implies_success(client, configured):
    job = plan(client, configured).json()
    approve(client, job)
    transport = configured[1]
    transport.unproven = True
    assert client.post(f"/api/v1/jobs/{job['id']}/run").json()["state"] == "reconciliation_required"
    assert (
        client.post(f"/api/v1/jobs/{job['id']}/reconcile").json()["state"]
        == "reconciliation_required"
    )
    transport.read_error = True
    assert client.post(f"/api/v1/jobs/{job['id']}/reconcile").status_code == 503
    assert len(transport.calls) == 1 and client.get("/api/v1/apps").json() == []


def test_health_expiry_and_engine_outage_hide_launch_route(client, configured, app, engine):
    job = plan(client, configured).json()
    approve(client, job)
    client.post(f"/api/v1/jobs/{job['id']}/run")
    with Session(engine) as db:
        db.get(ServiceInstance, job["resource_id"]).checked_at = utcnow() - timedelta(minutes=2)
        db.commit()
    assert client.get("/api/v1/apps").json()[0]["route"] is None
    poll_once(engine, app.state.settings, configured[1])
    assert client.get("/api/v1/apps").json()[0]["route"] is not None
    configured[1].lose_response = True
    poll_once(engine, app.state.settings, configured[1])
    item = client.get("/api/v1/apps").json()[0]
    assert item["status"] == "unknown" and item["route"] is None
