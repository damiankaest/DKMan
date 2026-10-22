"""PostgreSQL concurrency proves revision and approval serialization, beyond SQLite."""

import os
from concurrent.futures import ThreadPoolExecutor
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
from dkman.job_schemas import ApprovalBinding, ApprovalDecision
from dkman.jobs import decide
from dkman.models import AppPlan, AppRequest, Job
from dkman.planning import (
    create_request,
    create_revision,
    run_plan_approval,
    submit_plan_approval,
)
from dkman.planning_schemas import PlanApprovalInput, RequestInput, Requirements, RevisionInput

pytestmark = pytest.mark.postgres
ACTOR = Principal("planning-admin", "Planner", frozenset({"admin"}))
REQUIREMENTS = Requirements(title="Garten", goal="Pflanzen pflegen", features=["Pflanzen"])


@pytest.fixture(scope="module")
def pg_engine():
    url = os.environ.get("DKMAN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set DKMAN_TEST_DATABASE_URL for real PostgreSQL planning transactions")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Refusing integration test: database name must end with _test")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DKMAN_DATABASE_URL", url)
        command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 3})
    yield engine
    engine.dispose()


def race(functions):
    barrier = Barrier(len(functions))

    def execute(function):
        barrier.wait(timeout=10)
        try:
            return function()
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return list(pool.map(execute, functions))


def request(pg_engine, key=None):
    with Session(pg_engine) as db:
        return create_request(
            db, RequestInput(requirements=REQUIREMENTS), key or str(uuid4()), ACTOR, str(uuid4())
        ).id


def test_concurrent_request_replays_create_one_workflow(pg_engine):
    key = str(uuid4())
    ids = race([lambda: request(pg_engine, key) for _ in range(4)])
    assert len(set(ids)) == 1
    with Session(pg_engine) as db:
        assert (
            db.scalar(select(func.count()).select_from(AppPlan).where(AppPlan.request_id == ids[0]))
            == 1
        )


def test_concurrent_revisions_preserve_the_winner_and_replay(pg_engine):
    request_id = request(pg_engine)
    body = RevisionInput(expected_revision=1, requirements=REQUIREMENTS)

    def revise(key):
        with Session(pg_engine) as db:
            return create_revision(db, request_id, body, key, ACTOR, str(uuid4())).id

    results = race([lambda: revise(str(uuid4())), lambda: revise(str(uuid4()))])
    assert results.count(409) == 1
    with Session(pg_engine) as db:
        assert db.get(AppRequest, request_id).current_revision == 2
    key = str(uuid4())
    body = RevisionInput(expected_revision=2, requirements=REQUIREMENTS)
    results = race([lambda: revise(key) for _ in range(4)])
    assert len(set(results)) == 1
    assert results[0] != 409
    with Session(pg_engine) as db:
        assert db.get(AppRequest, request_id).current_revision == 3


def test_approval_racing_with_revision_never_approves_new_content(pg_engine):
    request_id = request(pg_engine)
    with Session(pg_engine) as db:
        plan = db.scalar(select(AppPlan).where(AppPlan.request_id == request_id))
        plan_id = plan.id
        job = submit_plan_approval(
            db,
            plan_id,
            PlanApprovalInput(content_hash=plan.content_hash),
            str(uuid4()),
            ACTOR,
            str(uuid4()),
        )
        job_id = job.id
        from dkman.models import ApprovalRequest

        approval = db.scalar(select(ApprovalRequest).where(ApprovalRequest.job_id == job_id))
        decide(
            db,
            approval.id,
            ApprovalDecision(
                **ApprovalBinding.model_validate(approval).model_dump(), decision="approve"
            ),
            ACTOR,
        )

    def complete():
        with Session(pg_engine) as db:
            return run_plan_approval(job_id, db, ACTOR).state

    def revise():
        with Session(pg_engine) as db:
            return create_revision(
                db,
                request_id,
                RevisionInput(expected_revision=1, requirements=REQUIREMENTS),
                str(uuid4()),
                ACTOR,
                str(uuid4()),
            ).id

    result = race([complete, revise])
    assert all(value != 409 for value in result)
    with Session(pg_engine) as db:
        old = db.get(AppPlan, plan_id)
        new = db.scalar(
            select(AppPlan).where(AppPlan.request_id == request_id, AppPlan.revision == 2)
        )
        assert new.approved_job_id is None
        assert db.get(Job, job_id).state == ("succeeded" if old.approved_job_id else "failed")
