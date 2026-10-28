"""Revision approval and evidence-gated replacement; these tests use a fake adapter."""

import hashlib
import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from test_forge_api import generate
from test_forge_artifacts import path, setup_artifact
from test_forge_install_planning import submit
from test_forge_preview_api import prepare_preview
from test_planning import approve, review, revision

from dkman.deployment_health import poll_once
from dkman.deployments.contracts import (
    ContainerEvidence,
    DeploymentCommand,
    EngineReceipt,
    OperationView,
    UpgradePlan,
    WorkloadEvidence,
)
from dkman.deployments.evidence import prove_completion
from dkman.forge.attestation import BuildEvidence, sign_evidence, sign_preview
from dkman.forge.build_recipe import image_dockerfile
from dkman.forge.workspace import SourceBundle
from dkman.models import AppDefinition, AppInstallation, Job, ServiceManifest, utcnow
from dkman.runtime_api import installed_plan

__all__ = ["setup_artifact"]


@pytest.fixture
def upgrade_candidate(client, app, tmp_path, setup_artifact, as_user, engine):
    item, _, workspace, builder, first_build_body = setup_artifact
    _, _, first_build, preview_key, preview_evidence = prepare_preview(
        client, app, tmp_path, setup_artifact
    )
    first_preview = client.post(
        f"/api/v1/forge/build-artifacts/{first_build['id']}/previews",
        json=sign_preview(preview_evidence, preview_key).model_dump(mode="json"),
    ).json()
    as_user("admin", ["admin"])
    home = client.post("/api/v1/households", json={"name": "Zuhause"}).json()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"schema_version": 1, "images": []}))
    secret = tmp_path / "delegation-secret"
    secret.write_text("s" * 48)
    app.state.settings.deployment_enabled = True
    app.state.settings.deployment_catalog_file = catalog
    app.state.settings.deployment_secret_file = secret
    first = submit(client, first_preview, home).json()
    initial = first["plan"]
    # Seed the preceding installation; a separate integration test exercises the real engine.
    with Session(engine) as db:
        job = db.get(Job, first["id"])
        job.state = "succeeded"
        job.finished_at = utcnow()
        db.add(
            AppInstallation(
                id=first["resource_id"],
                definition_id=initial["definition_id"],
                manifest_id=initial["context"]["manifest_id"],
                household_id=home["id"],
                owner_subject="admin",
                desired_state="running",
            )
        )
        db.commit()
    as_user("alice", ["developer"])
    next_plan = revision(client, item).json()
    as_user("admin", ["admin"])
    review_job = review(client, next_plan).json()
    assert approve(client, review_job).status_code == 200
    assert client.post(f"/api/v1/jobs/{review_job['id']}/run").json()["state"] == "succeeded"
    as_user("alice", ["developer"])
    next_workspace = generate(client, next_plan, template="react-spa").json()
    source = client.get(f"/api/v1/forge/workspaces/{next_workspace['id']}/build-input").json()
    bundle = SourceBundle.model_validate(source["bundle"])
    old_evidence = BuildEvidence.model_validate(first_build_body["evidence"])
    new_evidence = old_evidence.model_copy(
        update={
            "build_id": uuid4(),
            "workspace_id": UUID(next_workspace["id"]),
            "source_hash": next_workspace["bundle_hash"],
            "plan_hash": next_plan["content_hash"],
            "config_digest": "sha256:" + "d" * 64,
            "manifest_digest": "sha256:" + "e" * 64,
            "image_recipe_sha256": hashlib.sha256(image_dockerfile(bundle).encode()).hexdigest(),
            "finished_at": utcnow(),
        }
    )
    built = client.post(
        path(next_workspace), json=sign_evidence(new_evidence, builder).model_dump(mode="json")
    )
    assert built.status_code == 201, built.text
    build = built.json()
    now = utcnow()
    fresh = preview_evidence.model_copy(
        update={
            "preview_id": uuid4(),
            "artifact_id": new_evidence.build_id,
            "workspace_id": UUID(next_workspace["id"]),
            "artifact_evidence_hash": build["evidence_hash"],
            "source_hash": new_evidence.source_hash,
            "plan_hash": new_evidence.plan_hash,
            "manifest_digest": new_evidence.manifest_digest,
            "config_digest": new_evidence.config_digest,
            "observed_at": now,
            "expires_at": now + timedelta(minutes=5),
        }
    )
    observed = client.post(
        f"/api/v1/forge/build-artifacts/{build['id']}/previews",
        json=sign_preview(fresh, preview_key).model_dump(mode="json"),
    )
    assert observed.status_code == 201, observed.text
    as_user("admin", ["admin"])
    return item, first, observed.json(), home


def submit_upgrade(client, first, preview, key=None):
    return client.post(
        f"/api/v1/forge/previews/{preview['id']}/upgrades",
        json={"installation_id": first["resource_id"]},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


class FakeEngine:
    def __init__(self, *, omit_receipt=False):
        self.omit_receipt = omit_receipt
        self.calls = []

    def execute(self, operation, command, _credential):
        self.calls.append(command)
        assert command.upgrade is not None and command.action == "deploy"
        now = utcnow()
        before_time, started, acknowledged, after_time = (
            now + timedelta(milliseconds=i) for i in range(4)
        )

        def container(plan, identity, start):
            return ContainerEvidence(
                service="app",
                container_id=identity * 64,
                image_id=plan.image,
                runtime_plan_hash=plan.plan_hash,
                status="running",
                health="healthy",
                started_at=start,
                finished_at=now - timedelta(hours=2),
                volumes=[],
            )

        old = container(command.upgrade.previous, "a", now - timedelta(hours=1))
        new = container(command.plan, "b", started)
        before = WorkloadEvidence(observed_at=before_time, containers=[old])
        after = WorkloadEvidence(observed_at=after_time, containers=[new])
        receipt = EngineReceipt(
            operation_id=operation,
            installation_id=command.plan.installation_id,
            action="deploy",
            plan_hash=command.plan_hash,
            before=before,
            acknowledged_at=acknowledged,
        )
        completion, runtime = prove_completion(command, operation, now, receipt, after)
        return OperationView(
            operation_id=operation,
            installation_id=command.plan.installation_id,
            action="deploy",
            plan_hash=command.plan_hash,
            state="succeeded",
            created_at=now,
            finished_at=after_time,
            runtime=runtime,
            completion=None if self.omit_receipt else completion,
        )


def test_upgrade_requires_separate_approval_and_preserves_prior_revision(
    client, app, engine, upgrade_candidate
):
    _, first, preview, _ = upgrade_candidate
    response = submit_upgrade(client, first, preview, "update-one")
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["state"] == "waiting_approval" and job["action"] == "deployment.upgrade"
    assert job["plan"]["previous"] == first["plan"]
    assert (
        job["plan"]["replacement"]["context"]["manifest_id"]
        != first["plan"]["context"]["manifest_id"]
    )
    assert submit_upgrade(client, first, preview, "update-one").json()["id"] == job["id"]
    assert submit_upgrade(client, first, preview).status_code == 409
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    with Session(engine) as db:
        assert (
            db.get(AppInstallation, first["resource_id"]).manifest_id
            == first["plan"]["context"]["manifest_id"]
        )
    assert approve(client, job).status_code == 200
    fake = FakeEngine()
    app.state.deployment_client = fake
    response = client.post(f"/api/v1/jobs/{job['id']}/run")
    assert response.status_code == 200 and response.json()["state"] == "succeeded", response.text
    assert len(fake.calls) == 1
    with Session(engine) as db:
        item = db.get(AppInstallation, first["resource_id"])
        assert item.manifest_id == job["plan"]["replacement"]["context"]["manifest_id"]
        assert db.get(ServiceManifest, first["plan"]["context"]["manifest_id"]) is not None
        assert (
            db.get(AppDefinition, item.definition_id).version
            == job["plan"]["replacement"]["version"]
        )
        assert installed_plan(db, item).model_dump(mode="json") == job["plan"]["replacement"]

    class StatusEngine:
        def execute(self, operation, command, _token):
            assert command.action == "status"
            assert command.plan.model_dump(mode="json") == job["plan"]["replacement"]
            now = utcnow() + timedelta(seconds=1)
            return OperationView(
                operation_id=operation,
                installation_id=command.plan.installation_id,
                action="status",
                plan_hash=command.plan_hash,
                state="succeeded",
                created_at=now,
                finished_at=now,
                runtime={
                    "installation_id": command.plan.installation_id,
                    "state": "running",
                    "observed_at": now,
                    "container_id": "b" * 64,
                },
            )

    poll_once(engine, app.state.settings, StatusEngine())
    assert client.get("/api/v1/apps").json()[0]["route"].endswith(first["resource_id"] + "/")
    app.state.deployment_client = StatusEngine()
    refreshed = client.post(f"/api/v1/apps/{first['resource_id']}/refresh")
    assert refreshed.status_code == 200 and refreshed.json()["state"] == "running"


def test_missing_receipt_keeps_old_revision_and_blocks_retry(
    client, app, engine, upgrade_candidate
):
    _, first, preview, _ = upgrade_candidate
    job = submit_upgrade(client, first, preview).json()
    assert approve(client, job).status_code == 200
    fake = FakeEngine(omit_receipt=True)
    app.state.deployment_client = fake
    result = client.post(f"/api/v1/jobs/{job['id']}/run").json()
    assert result["state"] == "reconciliation_required"
    assert client.post(f"/api/v1/jobs/{job['id']}/run").status_code == 409
    assert submit_upgrade(client, first, preview).status_code == 409
    assert len(fake.calls) == 1
    with Session(engine) as db:
        assert (
            db.get(AppInstallation, first["resource_id"]).manifest_id
            == first["plan"]["context"]["manifest_id"]
        )


def test_changed_plan_after_approval_never_calls_adapter(client, app, upgrade_candidate, as_user):
    item, first, preview, _ = upgrade_candidate
    job = submit_upgrade(client, first, preview).json()
    assert approve(client, job).status_code == 200
    as_user("alice", ["developer"])
    item["current_revision"] = 2
    assert revision(client, item).status_code == 201
    as_user("admin", ["admin"])
    fake = FakeEngine()
    app.state.deployment_client = fake
    result = client.post(f"/api/v1/jobs/{job['id']}/run").json()
    assert result["state"] == "failed" and result["failure_code"] == "upgrade_preflight_failed"
    assert fake.calls == []


@pytest.mark.parametrize(
    "change", ["same_container", "wrong_image", "wrong_plan", "volume", "unhealthy", "old_plan"]
)
def test_update_receipt_must_prove_both_revisions(client, upgrade_candidate, change):
    _, first, preview, _ = upgrade_candidate
    raw = submit_upgrade(client, first, preview).json()
    plan = UpgradePlan.model_validate(raw["plan"])
    command = DeploymentCommand(action="deploy", plan=plan.replacement, upgrade=plan)
    operation = uuid4()
    outcome = FakeEngine().execute(operation, command, "")
    assert outcome.completion is not None
    receipt = outcome.completion.receipt
    after = outcome.completion.after
    current = after.containers[0]
    if change == "old_plan":
        old = receipt.before.containers[0].model_copy(update={"runtime_plan_hash": "f" * 64})
        before = receipt.before.model_copy(update={"containers": [old]})
        receipt = receipt.model_copy(update={"before": before})
    else:
        values = {
            "same_container": {"container_id": receipt.before.containers[0].container_id},
            "wrong_image": {"image_id": "sha256:" + "f" * 64},
            "wrong_plan": {"runtime_plan_hash": "f" * 64},
            "volume": {"volumes": ["foreign-volume"]},
            "unhealthy": {"health": "unhealthy"},
        }
        current = current.model_copy(update=values[change])
        after = after.model_copy(update={"containers": [current]})
    with pytest.raises(ValueError):
        prove_completion(command, operation, outcome.created_at, receipt, after)
