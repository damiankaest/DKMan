import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_planning import approve, create, plans, review, revision

from dkman.auth import Principal
from dkman.forge.approved_plan import generation_request_for
from dkman.models import AppPlan, Job


def principal(subject, *roles):
    return Principal(subject=subject, display_name=subject, roles=frozenset(roles))


def test_requires_current_approved_plan_and_permissions(client, as_user, engine):
    as_user("alice", ["admin"])
    item = create(client).json()
    plan = plans(client, item)[0]
    with Session(engine) as db:
        with pytest.raises(HTTPException) as exc:
            generation_request_for(db, principal("alice", "member"), plan["id"], "python-api")
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            generation_request_for(db, principal("alice", "admin"), plan["id"], "python-api")
        assert exc.value.status_code == 409
    job = review(client, plan).json()
    assert approve(client, job).status_code == 200
    assert client.post(f"/api/v1/jobs/{job['id']}/run").json()["state"] == "succeeded"
    with Session(engine) as db:
        result = generation_request_for(db, principal("alice", "admin"), plan["id"], "react-spa")
        assert result.content_hash == plan["content_hash"]
        assert result.requirements.title == "Garten"
        with pytest.raises(HTTPException) as exc:
            generation_request_for(db, principal("bob", "developer"), plan["id"], "python-api")
        assert exc.value.status_code == 404
    assert revision(client, item).status_code == 201
    with Session(engine) as db:
        with pytest.raises(HTTPException) as exc:
            generation_request_for(db, principal("alice", "admin"), plan["id"], "python-api")
        assert exc.value.status_code == 409


def test_tampered_approval_is_rejected(client, as_user, engine):
    as_user("alice", ["admin"])
    item = create(client).json()
    plan = plans(client, item)[0]
    job = review(client, plan).json()
    assert approve(client, job).status_code == 200
    assert client.post(f"/api/v1/jobs/{job['id']}/run").json()["state"] == "succeeded"
    with Session(engine) as db:
        saved = db.get(Job, job["id"])
        saved.result = {"approved": True}
        db.commit()
        with pytest.raises(HTTPException) as exc:
            generation_request_for(db, principal("alice", "admin"), plan["id"], "python-api")
        assert exc.value.status_code == 409
        assert db.get(AppPlan, plan["id"]).approved_job_id == job["id"]
