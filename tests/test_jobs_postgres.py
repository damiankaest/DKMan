"""Real concurrent transactions; SQLite tests cannot prove PostgreSQL row locking."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from dkman.auth import Principal
from dkman.job_schemas import ApprovalBinding, ApprovalDecision, JobSubmission
from dkman.jobs import begin_execution, cancel, claim, decide, finish, locked_job, recover, submit
from dkman.models import ApprovalRequest, Job, JobEvent, utcnow
from dkman.seed import seed

pytestmark = pytest.mark.postgres
ADMIN = Principal("pg-admin", "Admin", frozenset({"admin"}))


@pytest.fixture(scope="module")
def pg_engine():
    url = os.environ.get("DKMAN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set DKMAN_TEST_DATABASE_URL for real concurrent PostgreSQL transactions")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Refusing integration test: database name must end with _test")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DKMAN_DATABASE_URL", url)
        command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 3})
    with Session(engine) as db:
        seed(db, Path(__file__).resolve().parents[1] / "examples")
    yield engine
    engine.dispose()


def submission(pg_engine, key=None, **overrides):
    with Session(pg_engine) as db:
        return submit(
            db,
            JobSubmission(action="registry.validate", resource_id="demo-notes", **overrides),
            key or str(uuid4()),
            ADMIN,
            str(uuid4()),
        ).id


def race(functions):
    barrier = Barrier(len(functions))

    def run(function):
        barrier.wait(timeout=10)
        try:
            return function()
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return list(pool.map(run, functions))


def test_concurrent_duplicate_submission_converges(pg_engine):
    key = str(uuid4())
    ids = race([lambda: submission(pg_engine, key) for _ in range(4)])
    assert len(set(ids)) == 1
    with Session(pg_engine) as db:
        assert (
            db.scalar(select(func.count()).select_from(Job).where(Job.idempotency_key == key)) == 1
        )
        assert (
            db.scalar(select(func.count()).select_from(JobEvent).where(JobEvent.job_id == ids[0]))
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ApprovalRequest)
                .where(ApprovalRequest.job_id == ids[0])
            )
            == 1
        )


def test_concurrent_conflicting_submission_has_one_winner(pg_engine):
    key = str(uuid4())
    result = race(
        [
            lambda: submission(pg_engine, key, require_approval=True),
            lambda: submission(pg_engine, key, require_approval=False),
        ]
    )
    assert result.count(409) == 1


def test_claim_and_completion_have_only_one_owner(pg_engine):
    job_id = submission(pg_engine, require_approval=False)

    def acquire():
        with Session(pg_engine) as db:
            return claim(db, job_id, ADMIN)

    result = race([acquire, acquire])
    assert result.count(409) == 1
    token = next(x for x in result if x != 409)
    with Session(pg_engine) as db:
        assert db.get(Job, job_id).attempt == 1
        begin_execution(db, job_id, token, ADMIN)
        finish(db, job_id, token, result={"valid": True})
    result = race([acquire, acquire])
    assert result == [409, 409]


def test_conflicting_approval_decisions_serialize(pg_engine):
    job_id = submission(pg_engine)
    with Session(pg_engine) as db:
        item = db.scalar(select(ApprovalRequest).where(ApprovalRequest.job_id == job_id))
        approval_id = item.id
        binding = ApprovalBinding.model_validate(item).model_dump()

    def decision(value):
        with Session(pg_engine) as db:
            return decide(db, approval_id, ApprovalDecision(**binding, decision=value), ADMIN).state

    result = race([lambda: decision("approve"), lambda: decision("reject")])
    assert result.count(409) == 1
    assert any(x in {"approved", "rejected"} for x in result)


def test_approval_and_cancel_cannot_leave_executable_approval(pg_engine):
    job_id = submission(pg_engine)
    with Session(pg_engine) as db:
        item = db.scalar(select(ApprovalRequest).where(ApprovalRequest.job_id == job_id))
        approval_id = item.id
        body = ApprovalDecision(
            **ApprovalBinding.model_validate(item).model_dump(), decision="approve"
        )

    def approve():
        with Session(pg_engine) as db:
            return decide(db, approval_id, body, ADMIN).state

    def stop():
        with Session(pg_engine) as db:
            return cancel(db, job_id, ADMIN).state

    race([approve, stop])
    with Session(pg_engine) as db:
        assert db.get(Job, job_id).state == "cancelled"
        assert db.get(ApprovalRequest, approval_id).state == "cancelled"


def test_recovery_skips_locks_preserves_live_workers_and_never_replays_running(pg_engine):
    job_id = submission(pg_engine, require_approval=False)
    with Session(pg_engine) as db:
        token = claim(db, job_id, ADMIN)
        assert recover(db) == 0
        begin_execution(db, job_id, token, ADMIN)
        job = db.get(Job, job_id)
        job.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with Session(pg_engine) as owner:
        locked_job(owner, job_id)
        with ThreadPoolExecutor(max_workers=1) as pool:

            def recover_other():
                with Session(pg_engine) as db:
                    return recover(db)

            assert pool.submit(recover_other).result(timeout=10) == 0
        owner.rollback()
    with Session(pg_engine) as db:
        assert recover(db) == 1
        assert db.get(Job, job_id).state == "reconciliation_required"
        with pytest.raises(HTTPException):
            finish(db, job_id, token, result={"valid": True})
        db.rollback()
        assert recover(db) == 0
