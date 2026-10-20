"""Real PostgreSQL locking at lifecycle reservation and execution boundaries."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.orm import Session
from test_installations_postgres import pg_setup

from dkman.auth import Principal
from dkman.deployment_api import InstallInput, plan_installation
from dkman.jobs import begin_execution, claim, recover
from dkman.models import AppInstallation, ApprovalRequest, Job, utcnow
from dkman.runtime_api import plan_lifecycle

__all__ = ["pg_setup"]
pytestmark = pytest.mark.postgres
ACTOR = Principal("pg-lifecycle-admin", "Admin", frozenset({"admin"}))


@pytest.fixture
def pg_installed(pg_setup):
    engine, settings, group = pg_setup
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        state=SimpleNamespace(correlation_id=str(uuid4())),
    )
    with Session(engine) as db:
        original = plan_installation(
            InstallInput(definition_id="demo-notes", household_id=group),
            request,
            Response(),
            db,
            ACTOR,
            str(uuid4()),
        )
        original.state = "succeeded"
        item = AppInstallation(
            id=original.resource_id,
            definition_id="demo-notes",
            manifest_id=original.plan["context"]["manifest_id"],
            household_id=group,
            owner_subject=ACTOR.subject,
            desired_state="running",
        )
        db.add(item)
        db.commit()
        identifier = UUID(item.id)
    return engine, identifier, request


def race(pg_installed, keys):
    engine, identifier, request = pg_installed
    barrier = Barrier(len(keys))

    def submit(key):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                return plan_lifecycle("stop", identifier, request, Response(), db, ACTOR, key).id
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        return list(pool.map(submit, keys))


def test_lifecycle_same_keys_converge_across_connections(pg_installed):
    result = race(pg_installed, [str(uuid4())] * 4)
    assert len(set(result)) == 1 and isinstance(result[0], str)


def test_lifecycle_different_keys_serialize_and_unknown_outcome_retains_reservation(pg_installed):
    result = race(pg_installed, [str(uuid4()) for _ in range(4)])
    assert result.count(409) == 3
    job_id = next(value for value in result if isinstance(value, str))
    engine, _, _ = pg_installed
    with Session(engine) as db:
        job = db.get(Job, job_id)
        approval = db.query(ApprovalRequest).filter_by(job_id=job.id).one()
        approval.state = "approved"
        job.state = "queued"
        db.commit()
        token = claim(db, job_id, ACTOR)
        begin_execution(db, job_id, token, ACTOR)
        job.lease_expires_at = utcnow()
        db.commit()
    with Session(engine) as restarted:
        assert recover(restarted) >= 1
        assert restarted.get(Job, job_id).state == "reconciliation_required"
    assert race(pg_installed, [str(uuid4()), str(uuid4())]) == [409, 409]
