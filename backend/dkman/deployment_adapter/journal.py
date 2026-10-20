"""Single-host adapter journal. Explicit migration, durable commits, process-safe locks."""

import fcntl
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from dkman.deployments.auth import Delegation
from dkman.deployments.contracts import (
    DeploymentCommand,
    DeploymentPlan,
    OperationView,
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
        elif version != 2:
            raise ValueError("Unknown adapter journal revision")


class Journal:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if root.is_symlink() or (root / "operations.sqlite3").is_symlink():
            raise ValueError("Symlinks are forbidden for adapter state")
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 2:
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
    def lock(self, installation_id: UUID) -> Iterator[None]:
        path = self.root / "locks" / str(installation_id)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AdapterError("resource_busy") from exc
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
