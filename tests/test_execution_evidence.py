"""Evidence gaps must retain fences, even when the entire workload is healthy."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_deployment_adapter import (
    SECRET,
    TestProvider,
    adapter,
    catalog,
    plan,
    token,
)

from dkman.deployment_adapter.journal import AdapterError, Journal, migrate
from dkman.deployment_adapter.main import create_app
from dkman.deployments.auth import verify_delegation
from dkman.deployments.contracts import (
    ContainerEvidence,
    DeploymentCommand,
    EngineReceipt,
    WorkloadEvidence,
    canonical_hash,
)
from dkman.deployments.evidence import prove_completion

__all__ = ["adapter", "catalog", "plan"]


def snapshots(plan, action, start):
    def container(**changes):
        values = dict(
            service="app",
            container_id="c" * 64,
            image_id=plan.image,
            runtime_plan_hash=plan.plan_hash,
            status="running",
            health="healthy",
            started_at=start - timedelta(minutes=1),
            finished_at=start - timedelta(minutes=2),
            volumes=[f"{plan.project}-data"],
        )
        values.update(changes)
        return ContainerEvidence(**values)

    before = [] if action == "install" else [container()]
    if action == "start":
        before = [container(status="exited")]
    after = [container(started_at=start + timedelta(seconds=1))]
    if action == "stop":
        after = [container(status="exited", finished_at=start + timedelta(seconds=1))]
    return WorkloadEvidence(observed_at=start, containers=before), WorkloadEvidence(
        observed_at=start + timedelta(seconds=3),
        containers=after,
    )


def uncertain_operation(journal, plan, action="restart", *, acknowledge=True):
    operation_id = uuid4()
    command = DeploymentCommand(action=action, plan=plan)
    grant = verify_delegation(token(plan, operation_id, action), SECRET)
    with journal.lock(plan.installation_id):
        item = journal.begin(command, grant, True)
        before, after = snapshots(plan, action, item.created_at + timedelta(milliseconds=1))
        receipt = EngineReceipt(
            operation_id=operation_id,
            installation_id=plan.installation_id,
            action=action,
            plan_hash=command.plan_hash,
            before=before,
            acknowledged_at=before.observed_at + timedelta(seconds=2),
        )
        if acknowledge:
            journal.record_receipt(receipt)
        # Simulate process death: no finish. A new instance sees only durable state.
    assert Journal(journal.root).recover() == 1
    return item, command, receipt, after


@pytest.mark.parametrize("action", ["install", "start", "stop", "restart"])
def test_acknowledged_command_can_complete_after_crash_without_runtime_replay(
    tmp_path, plan, action
):
    migrate(tmp_path)
    first = Journal(tmp_path)
    item, command, receipt, after = uncertain_operation(first, plan, action)
    second = Journal(tmp_path)
    assert second.receipt(item.operation_id) == receipt
    with second.lock(plan.installation_id):
        result = second.resolve(item.operation_id, after)
    assert result.state == "succeeded"
    assert result.runtime.state == ("stopped" if action == "stop" else "running")
    assert result.completion.receipt == receipt
    assert result.completion.evidence_hash == canonical_hash(
        result.completion.model_dump(mode="json")
    )
    with second.connect() as db:
        assert db.execute("SELECT blocked_by FROM resources").fetchone()[0] is None
    # The original worker is fenced out after recovery, even if it returns late.
    with pytest.raises(AdapterError, match="operation_ownership_lost"):
        first.finish(result, command, True)
    assert second.current_plan(plan.installation_id) == plan


@pytest.mark.parametrize(
    "change",
    [
        "container",
        "image",
        "volume",
        "plan",
        "unhealthy",
        "unchanged_restart",
        "late_restart",
        "partial",
        "wrong_operation",
        "wrong_hash",
        "early_receipt",
    ],
)
def test_incomplete_or_unrelated_evidence_never_releases_fence(tmp_path, plan, change):
    migrate(tmp_path)
    journal = Journal(tmp_path)
    item, command, receipt, after = uncertain_operation(journal, plan)
    current = after.containers[0]
    updates = {
        "container": {"container_id": "d" * 64},
        "image": {"image_id": "sha256:" + "f" * 64},
        "volume": {"volumes": ["foreign-data"]},
        "plan": {"runtime_plan_hash": "f" * 64},
        "unhealthy": {"health": "unhealthy"},
        "unchanged_restart": {"started_at": receipt.before.containers[0].started_at},
        "late_restart": {"started_at": after.observed_at},
    }
    if change in updates:
        after = after.model_copy(
            update={"containers": [current.model_copy(update=updates[change])]}
        )
    elif change == "partial":
        after = after.model_copy(update={"containers": []})
    else:
        receipt = receipt.model_copy(
            update={
                "wrong_operation": {"operation_id": uuid4()},
                "wrong_hash": {"plan_hash": "f" * 64},
                "early_receipt": {"acknowledged_at": item.created_at - timedelta(seconds=1)},
            }[change]
        )
        # A valid JSON+checksum alone cannot substitute for action/resource/time binding.
        with journal.connect() as db:
            db.execute(
                "UPDATE execution_receipts SET receipt=?,receipt_hash=?",
                (
                    receipt.model_dump_json(),
                    canonical_hash(receipt.model_dump(mode="json")),
                ),
            )
    with journal.lock(plan.installation_id):
        assert journal.resolve(item.operation_id, after).state == "reconciliation_required"
    with journal.connect() as db:
        assert db.execute("SELECT blocked_by FROM resources").fetchone()[0] == str(
            item.operation_id
        )
    new = verify_delegation(token(plan, uuid4(), "stop"), SECRET)
    with pytest.raises(AdapterError, match="resource_requires_reconciliation"):
        journal.begin(DeploymentCommand(action="stop", plan=plan), new, True)


def test_no_receipt_and_corrupt_receipt_are_not_current_health_proof(tmp_path, plan):
    migrate(tmp_path)
    journal = Journal(tmp_path)
    item, _, receipt, after = uncertain_operation(journal, plan, acknowledge=False)
    assert journal.resolve(item.operation_id, after).state == "reconciliation_required"
    with journal.connect() as db:
        db.execute(
            "INSERT INTO execution_receipts VALUES (?,?,?)",
            (
                str(item.operation_id),
                receipt.model_dump_json(),
                "f" * 64,
            ),
        )
    with pytest.raises(AdapterError, match="receipt_integrity_mismatch"):
        journal.resolve(item.operation_id, after)


def test_notes_requires_both_containers_to_have_restarted(plan):
    from dkman.deployments.contracts import DeploymentPlan

    values = plan.model_dump()
    values.update(
        definition_id="demo-notes",
        version="0.1.0",
        profile="notes-postgres-v1",
        source_hash="f" * 64,
        database_image="sha256:" + "d" * 64,
        data_path=None,
    )
    notes = DeploymentPlan.model_validate(values)
    start = datetime.now(UTC)
    before, after = snapshots(plan, "restart", start)
    app_before = before.containers[0].model_copy(
        update={"runtime_plan_hash": notes.plan_hash, "volumes": []}
    )
    app_after = after.containers[0].model_copy(
        update={"runtime_plan_hash": notes.plan_hash, "volumes": []}
    )
    db_before = app_before.model_copy(
        update={
            "service": "database",
            "container_id": "d" * 64,
            "image_id": notes.database_image,
            "volumes": [f"{notes.project}-data"],
        }
    )
    db_after = db_before  # App restarted, database did not.
    receipt = EngineReceipt(
        operation_id=uuid4(),
        installation_id=notes.installation_id,
        action="restart",
        plan_hash=notes.plan_hash,
        before=before.model_copy(update={"containers": [app_before, db_before]}),
        acknowledged_at=start + timedelta(seconds=2),
    )
    with pytest.raises(ValueError):
        prove_completion(
            DeploymentCommand(action="restart", plan=notes),
            receipt.operation_id,
            start,
            receipt,
            after.model_copy(update={"containers": [app_after, db_after]}),
        )


def test_reconcile_uses_exclusive_lock_original_identity_and_no_mutating_provider(
    adapter, plan, monkeypatch
):
    client, app, engine, settings, factory = adapter
    journal = app.state.journal
    item, _, _, after = uncertain_operation(journal, plan)
    monkeypatch.setattr(TestProvider, "evidence", lambda self, plan: after)
    url = f"/v1/operations/{item.operation_id}/reconcile"
    headers = {"Authorization": "Bearer " + token(plan, item.operation_id, "reconcile")}
    with journal.lock(plan.installation_id):
        assert client.post(url, headers=headers).status_code == 409
        assert journal.get(item.operation_id).state == "reconciliation_required"
    wrong = {
        "Authorization": "Bearer " + token(plan, item.operation_id, "reconcile", subject="bob")
    }
    assert client.post(url, headers=wrong).status_code == 403
    with TestClient(create_app(settings, factory)) as restarted:
        response = restarted.post(url, headers=headers)
        assert response.status_code == 200 and response.json()["state"] == "succeeded"
        assert restarted.post(url, headers=headers).json() == response.json()
    assert engine.calls == []


def test_v2_journal_upgrade_preserves_existing_operations_and_is_explicit(tmp_path, plan):
    migration_root = Path(__file__).parents[1] / "backend/dkman/deployment_adapter/migrations"
    tmp_path.mkdir(exist_ok=True)
    with sqlite3.connect(tmp_path / "operations.sqlite3") as db:
        for path in ["0001_operations.sql", "0002_single_use_approvals.sql"]:
            db.executescript((migration_root / path).read_text())
        db.execute(
            "INSERT INTO operations VALUES (?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                str(plan.installation_id),
                "legacy-subject",
                "legacy-fingerprint",
                json.dumps({"action": "install", "plan": plan.model_dump(mode="json")}),
                "running",
                "{}",
            ),
        )
    with pytest.raises(ValueError, match="explicit"):
        Journal(tmp_path)
    migrate(tmp_path)
    migrate(tmp_path)
    with Journal(tmp_path).connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT subject,fingerprint FROM operations").fetchone()[:] == (
            "legacy-subject",
            "legacy-fingerprint",
        )
        assert db.execute("SELECT COUNT(*) FROM execution_receipts").fetchone()[0] == 0


def test_stopped_database_with_cached_healthy_state_never_reports_ready(
    tmp_path, plan, monkeypatch
):
    from dkman.deployment_adapter.compose import ComposeProvider
    from dkman.deployments.contracts import DeploymentPlan

    values = plan.model_dump()
    values.update(
        definition_id="demo-notes",
        version="0.1.0",
        profile="notes-postgres-v1",
        source_hash="f" * 64,
        database_image="sha256:" + "d" * 64,
        data_path=None,
    )
    notes = DeploymentPlan.model_validate(values)
    provider = ComposeProvider(tmp_path, uuid4())
    monkeypatch.setattr(
        provider,
        "containers",
        lambda plan: [
            {"Id": "c" * 64, "State": {"Status": "running", "Health": {"Status": "healthy"}}},
            {"Id": "d" * 64, "State": {"Status": "exited", "Health": {"Status": "healthy"}}},
        ],
    )
    assert provider.status(notes).state == "unhealthy"
