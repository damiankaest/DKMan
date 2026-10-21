"""Single-host adapter journal. Explicit migration, durable commits, process-safe locks."""

import fcntl
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from dkman.deployments.auth import Delegation
from dkman.deployments.contracts import (
    DeploymentCommand,
    DeploymentPlan,
    EngineReceipt,
    OperationView,
    RejectionEvidence,
    WorkloadEvidence,
    canonical_hash,
)


class AdapterError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code = code
        self.status = status


def migrate(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise ValueError("Adapter state may not be a symlink")
    path = root / "operations.sqlite3"
    if path.is_symlink():
        raise ValueError("Journal may not be a symlink")
    with closing(sqlite3.connect(path)) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            db.executescript((Path(__file__).parent / "migrations/0001_operations.sql").read_text())
            version = 1
        if version == 1:
            db.executescript(
                (Path(__file__).parent / "migrations/0002_single_use_approvals.sql").read_text()
            )
            version = 2
        if version == 2:
            db.executescript(
                (Path(__file__).parent / "migrations/0003_execution_receipts.sql").read_text()
            )
        elif version != 3:
            raise ValueError("Unknown adapter journal revision")


class Journal:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if root.is_symlink() or (root / "operations.sqlite3").is_symlink():
            raise ValueError("Symlinks are forbidden for adapter state")
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 3:
                raise ValueError("Run the explicit adapter journal migration")
        for name in ["locks", "plans", "docker-config"]:
            path = self.root / name
            if path.is_symlink():
                raise ValueError("Adapter state directories may not be symlinks")
            path.mkdir(exist_ok=True, mode=0o700)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(
            f"file:{self.root / 'operations.sqlite3'}?mode=rw", uri=True, timeout=5
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def lock(
        self, installation_id: UUID, *, shared: bool = False, wait_seconds: float = 0
    ) -> Iterator[None]:
        path = self.root / "locks" / str(installation_id)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            deadline = time.monotonic() + wait_seconds
            mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
            while True:
                try:
                    fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise AdapterError("resource_busy") from exc
                    time.sleep(0.01)
            yield
        finally:
            os.close(descriptor)

    def get(self, operation_id: UUID) -> OperationView | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT result FROM operations WHERE operation_id=?", (str(operation_id),)
            ).fetchone()
            return OperationView.model_validate_json(row[0]) if row else None

    def stored_command(self, operation_id: UUID) -> DeploymentCommand:
        with self.connect() as db:
            row = db.execute(
                "SELECT command FROM operations WHERE operation_id=?", (str(operation_id),)
            ).fetchone()
            if row is None:
                raise AdapterError("operation_not_found", 404)
            return DeploymentCommand.model_validate_json(row[0])

    def require_subject(self, operation_id: UUID, subject: str) -> None:
        with self.connect() as db:
            row = db.execute(
                "SELECT subject FROM operations WHERE operation_id=?", (str(operation_id),)
            ).fetchone()
            if row is None or row[0] != subject:
                raise AdapterError("operation_subject_mismatch", 403)

    def record_receipt(self, receipt: EngineReceipt) -> None:
        """Only called after the exact Compose command returned exit zero; never inferred."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT result,command FROM operations WHERE operation_id=? AND state='running'",
                (str(receipt.operation_id),),
            ).fetchone()
            if row is None:
                raise AdapterError("operation_ownership_lost")
            item = OperationView.model_validate_json(row[0])
            command = DeploymentCommand.model_validate_json(row[1])
            if (
                receipt.installation_id != item.installation_id
                or receipt.action != command.action
                or receipt.plan_hash != command.plan_hash
                or not item.created_at <= receipt.before.observed_at <= receipt.acknowledged_at
            ):
                raise AdapterError("receipt_binding_mismatch")
            db.execute(
                "INSERT INTO execution_receipts VALUES (?,?,?)",
                (
                    str(receipt.operation_id),
                    receipt.model_dump_json(),
                    canonical_hash(receipt.model_dump(mode="json")),
                ),
            )

    def receipt(self, operation_id: UUID) -> EngineReceipt | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT receipt,receipt_hash FROM execution_receipts WHERE operation_id=?",
                (str(operation_id),),
            ).fetchone()
            if row is None:
                return None
            receipt = EngineReceipt.model_validate_json(row[0])
            if canonical_hash(receipt.model_dump(mode="json")) != row[1]:
                raise AdapterError("receipt_integrity_mismatch")
            return receipt

    def resolve(self, operation_id: UUID, after: WorkloadEvidence) -> OperationView:
        from dkman.deployments.evidence import prove_completion

        item = self.get(operation_id)
        if item is None or item.state != "reconciliation_required":
            raise AdapterError("operation_not_uncertain")
        receipt = self.receipt(operation_id)
        if receipt is None:
            return item
        command = self.stored_command(operation_id)
        try:
            completion, runtime = prove_completion(
                command, operation_id, item.created_at, receipt, after
            )
        except ValueError:
            return item.model_copy(update={"failure_code": "execution_evidence_incomplete"})
        result = item.model_copy(
            update={
                "state": "succeeded",
                "failure_code": None,
                "finished_at": datetime.now(UTC),
                "runtime": runtime,
                "completion": completion,
            }
        )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            blocked = db.execute(
                "SELECT blocked_by FROM resources WHERE installation_id=?",
                (str(item.installation_id),),
            ).fetchone()
            if blocked is None or blocked[0] != str(operation_id):
                raise AdapterError("resource_fence_changed")
            changed = db.execute(
                "UPDATE operations SET state='succeeded',result=? WHERE operation_id=? "
                "AND state='reconciliation_required'",
                (result.model_dump_json(), str(operation_id)),
            )
            if changed.rowcount != 1:
                raise AdapterError("operation_ownership_lost")
            # The original plan and all volumes stay unchanged.
            db.execute(
                "UPDATE resources SET blocked_by=NULL WHERE installation_id=? AND blocked_by=?",
                (str(item.installation_id), str(operation_id)),
            )
        return result

    def reject(
        self,
        command: DeploymentCommand,
        grant: Delegation,
        reason: Literal[
            "curation_rejected", "resource_preflight_rejected", "engine_preflight_unavailable"
        ],
    ) -> OperationView:
        rejection = RejectionEvidence(
            operation_id=grant.jti,
            installation_id=command.plan.installation_id,
            action=command.action,
            plan_hash=command.plan_hash,
            reason=reason,
            observed_at=datetime.now(UTC),
        )
        result = OperationView(
            operation_id=grant.jti,
            installation_id=command.plan.installation_id,
            action=command.action,
            plan_hash=command.plan_hash,
            state="failed",
            created_at=rejection.observed_at,
            finished_at=rejection.observed_at,
            failure_code=reason,
            rejection=rejection,
        )
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if grant.exp <= int(time.time()):
                    raise AdapterError("delegation_expired_before_execution", 401)
                if (
                    grant.approval_id is not None
                    and db.execute(
                        "SELECT operation_id FROM consumed_approvals WHERE approval_id=?",
                        (str(grant.approval_id),),
                    ).fetchone()
                    is not None
                ):
                    raise AdapterError("approval_already_consumed")
                # Rejections never own or release a resource fence.
                db.execute(
                    "INSERT INTO operations VALUES (?,?,?,?,?,?,?)",
                    (
                        str(grant.jti),
                        str(command.plan.installation_id),
                        grant.sub,
                        self.fingerprint(command, grant),
                        command.model_dump_json(),
                        "failed",
                        result.model_dump_json(),
                    ),
                )
                if grant.approval_id is not None:
                    db.execute(
                        "INSERT INTO consumed_approvals VALUES (?,?)",
                        (str(grant.approval_id), str(grant.jti)),
                    )
        except sqlite3.IntegrityError as error:
            raise AdapterError("operation_id_conflict") from error
        return result

    def current_plan(self, installation_id: UUID) -> DeploymentPlan | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT plan FROM resources WHERE installation_id=?", (str(installation_id),)
            ).fetchone()
            return DeploymentPlan.model_validate_json(row[0]) if row else None

    def replay(self, command: DeploymentCommand, grant: Delegation) -> OperationView | None:
        fingerprint = self.fingerprint(command, grant)
        with self.connect() as db:
            row = db.execute(
                "SELECT fingerprint,result FROM operations WHERE operation_id=?", (str(grant.jti),)
            ).fetchone()
            if row is not None:
                if row[0] != fingerprint:
                    raise AdapterError("operation_id_conflict")
                return OperationView.model_validate_json(row[1])
        return None

    @staticmethod
    def fingerprint(command: DeploymentCommand, grant: Delegation) -> str:
        return canonical_hash(
            {
                "command": command.model_dump(mode="json"),
                "subject": grant.sub,
                "approval_id": str(grant.approval_id),
                "approval_expires_at": grant.approval_expires_at,
            }
        )

    def begin(self, command: DeploymentCommand, grant: Delegation, mutating: bool) -> OperationView:
        try:
            return self._begin(command, grant, mutating)
        except sqlite3.IntegrityError as error:
            raise AdapterError("operation_id_conflict") from error

    def _begin(
        self, command: DeploymentCommand, grant: Delegation, mutating: bool
    ) -> OperationView:
        result = OperationView(
            operation_id=grant.jti,
            installation_id=command.plan.installation_id,
            action=command.action,
            plan_hash=command.plan_hash,
            state="running",
            created_at=datetime.now(UTC),
        )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if grant.exp <= int(time.time()):
                raise AdapterError("delegation_expired_before_execution", 401)
            if grant.approval_id is not None:
                used = db.execute(
                    "SELECT operation_id FROM consumed_approvals WHERE approval_id=?",
                    (str(grant.approval_id),),
                ).fetchone()
                if used is not None:
                    raise AdapterError("approval_already_consumed")
            if mutating:
                row = db.execute(
                    "SELECT blocked_by FROM resources WHERE installation_id=?",
                    (str(command.plan.installation_id),),
                ).fetchone()
                if row and row[0]:
                    raise AdapterError("resource_requires_reconciliation")
            db.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?,?,?)",
                (
                    str(grant.jti),
                    str(command.plan.installation_id),
                    grant.sub,
                    self.fingerprint(command, grant),
                    command.model_dump_json(),
                    "running",
                    result.model_dump_json(),
                ),
            )
            if grant.approval_id is not None:
                db.execute(
                    "INSERT INTO consumed_approvals VALUES (?,?)",
                    (str(grant.approval_id), str(grant.jti)),
                )
            if mutating:
                db.execute(
                    "INSERT INTO resources VALUES (?,?,?) ON CONFLICT(installation_id) "
                    "DO UPDATE SET blocked_by=excluded.blocked_by",
                    (
                        str(command.plan.installation_id),
                        command.plan.model_dump_json(),
                        str(grant.jti),
                    ),
                )
        return result

    def finish(self, result: OperationView, command: DeploymentCommand, mutating: bool) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                "UPDATE operations SET state=?,result=? WHERE operation_id=? AND state='running'",
                (result.state, result.model_dump_json(), str(result.operation_id)),
            )
            if updated.rowcount != 1:
                raise AdapterError("operation_ownership_lost")
            if mutating and result.state == "succeeded":
                if command.action in {"install", "deploy"}:
                    db.execute(
                        "UPDATE resources SET plan=? WHERE installation_id=? AND blocked_by=?",
                        (
                            command.plan.model_dump_json(),
                            str(result.installation_id),
                            str(result.operation_id),
                        ),
                    )
                db.execute(
                    "UPDATE resources SET blocked_by=NULL WHERE installation_id=? AND blocked_by=?",
                    (
                        str(result.installation_id),
                        str(result.operation_id),
                    ),
                )

    def recover(self) -> int:
        with self.connect() as db:
            rows = db.execute(
                "SELECT operation_id,installation_id FROM operations WHERE state='running'"
            ).fetchall()
        count = 0
        for row in rows:
            try:
                with self.lock(UUID(row[1])):
                    result = self.get(UUID(row[0]))
                    if result is not None and result.state == "running":
                        command = self.stored_command(result.operation_id)
                        result = result.model_copy(
                            update={
                                "state": "reconciliation_required",
                                "failure_code": "execution_outcome_unknown",
                                "finished_at": datetime.now(UTC),
                            }
                        )
                        self.finish(result, command, mutating=True)
                        count += 1
            except AdapterError as error:
                if error.code != "resource_busy":
                    raise
        return count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Apply explicit adapter journal migrations")
    parser.add_argument("--state-root", type=Path, required=True)
    arguments = parser.parse_args()
    migrate(arguments.state_root)
