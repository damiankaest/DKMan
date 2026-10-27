"""Real PostgreSQL idempotency and current-plan serialization for Forge."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_planning_postgres import ACTOR, pg_engine, race, request

from dkman.forge_api import WorkspaceInput, create_workspace
from dkman.job_schemas import ApprovalBinding, ApprovalDecision
from dkman.jobs import decide
from dkman.models import AppPlan, ApprovalRequest, ForgeWorkspace
from dkman.planning import run_plan_approval, submit_plan_approval
from dkman.planning_schemas import PlanApprovalInput

__all__ = ["pg_engine"]
pytestmark = pytest.mark.postgres


def test_concurrent_same_key_creates_only_one_workspace(pg_engine):
    request_id = request(pg_engine)
    with Session(pg_engine) as db:
        plan = db.scalar(select(AppPlan).where(AppPlan.request_id == request_id))
        plan_id, content_hash = plan.id, plan.content_hash
        job = submit_plan_approval(
            db,
            plan_id,
            PlanApprovalInput(content_hash=content_hash),
            str(uuid4()),
            ACTOR,
            str(uuid4()),
        )
        approval = db.scalar(select(ApprovalRequest).where(ApprovalRequest.job_id == job.id))
        decide(
            db,
            approval.id,
            ApprovalDecision(
                **ApprovalBinding.model_validate(approval).model_dump(), decision="approve"
            ),
            ACTOR,
        )
        assert run_plan_approval(job.id, db, ACTOR).state == "succeeded"
    key = str(uuid4())
    body = WorkspaceInput(template="python-api", content_hash=content_hash)

    def create():
        with Session(pg_engine) as db:
            http_request = SimpleNamespace(state=SimpleNamespace(correlation_id=str(uuid4())))
            return create_workspace(plan_id, body, db, ACTOR, http_request, key).id

    results = race([create for _ in range(4)])
    assert len(set(results)) == 1 and results[0] != 409
    with Session(pg_engine) as db:
        count = db.scalar(
            select(func.count())
            .select_from(ForgeWorkspace)
            .where(ForgeWorkspace.plan_id == plan_id)
        )
        assert count == 1
