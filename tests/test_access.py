from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dkman.manifest import parse_manifest
from dkman.models import AppInstallation, AuditEvent, ServiceManifest


def register(client, as_user, subject):
    as_user(subject)
    response = client.put("/api/v1/me/profile")
    assert response.status_code == 200
    return response.json()["id"]


def test_profile_is_verified_identity_and_idempotent(client, as_user, engine):
    assert client.put("/api/v1/me/profile").status_code == 401
    uid = register(client, as_user, "alice")
    assert client.put("/api/v1/me/profile", json={"subject": "bob"}).json()["subject"] == "alice"
    assert client.put("/api/v1/me/profile").json()["id"] == uid
    with Session(engine) as db:
        assert len(list(db.scalars(select(AuditEvent)))) == 1


@pytest.mark.parametrize("role", ["member", "developer", "operator"])
def test_management_requires_admin(client, as_user, role):
    as_user("alice", [role])
    for method, path in [
        ("get", "/users"),
        ("post", "/households"),
        ("get", "/households/home/members"),
        ("put", "/households/home/members/user"),
        ("delete", "/households/home/members/user"),
        ("get", "/installations/app/grants"),
        ("put", "/installations/app/grants/user"),
        ("delete", "/installations/app/grants/user"),
    ]:
        assert getattr(client, method)("/api/v1" + path).status_code == 403


def test_membership_grant_isolation_and_revocation(client, as_user, engine):
    alice = register(client, as_user, "alice")
    bob = register(client, as_user, "bob")
    as_user("admin", ["admin"])
    assert len(client.get("/api/v1/users").json()) == 2
    assert client.post("/api/v1/households", json={"name": "  "}).status_code == 422
    homes = [
        client.post("/api/v1/households", json={"name": name}).json()["id"]
        for name in ["Home", "Other"]
    ]
    manifest = parse_manifest(
        (Path(__file__).parents[1] / "examples/demo-notes/dkman.yaml").read_text()
    )
    assert (
        client.post(
            "/api/v1/registry/manifests", json=manifest.model_dump(by_alias=True)
        ).status_code
        == 201
    )
    with Session(engine) as db:
        stored = db.scalar(select(ServiceManifest))
        for index, home in enumerate(homes):
            db.add(
                AppInstallation(
                    id=f"app-{index}",
                    definition_id=manifest.id,
                    manifest_id=stored.id,
                    household_id=home,
                    owner_subject="admin",
                )
            )
        db.commit()
    grant = f"/api/v1/installations/app-0/grants/{alice}"
    member = f"/api/v1/households/{homes[0]}/members/{alice}"
    assert client.put(grant).status_code == 409
    assert client.put(member).status_code == 204
    assert client.put(member).status_code == 204
    assert len(client.get(f"/api/v1/households/{homes[0]}/members").json()) == 1
    assert client.put(grant).status_code == 204
    assert client.put(grant).status_code == 204
    assert len(client.get("/api/v1/installations/app-0/grants").json()) == 1
    assert client.put(f"/api/v1/installations/app-0/grants/{bob}").status_code == 409
    assert client.put(f"/api/v1/households/{homes[1]}/members/{alice}").status_code == 204
    assert client.put(f"/api/v1/installations/app-1/grants/{alice}").status_code == 204
    as_user("bob")
    assert client.get("/api/v1/households").json() == []
    assert client.get("/api/v1/apps").json() == []
    as_user("alice")
    assert len(client.get("/api/v1/households").json()) == 2
    assert len(client.get("/api/v1/apps").json()) == 2
    as_user("admin", ["admin"])
    assert client.delete(member).status_code == 204
    assert client.delete(member).status_code == 204
    assert client.put(member).status_code == 204
    as_user("alice")
    assert [item["id"] for item in client.get("/api/v1/apps").json()] == ["app-1"]
    assert client.get("/api/v1/apps/app-0").status_code == 404
    as_user("admin", ["admin"])
    assert client.delete(f"/api/v1/installations/app-1/grants/{alice}").status_code == 204
    assert client.delete(f"/api/v1/installations/app-1/grants/{alice}").status_code == 204
    as_user("alice")
    assert client.get("/api/v1/apps").json() == []
    with Session(engine) as db:
        events = list(db.scalars(select(AuditEvent)))
        assert sum(event.action == "grant.add" for event in events) == 2
        assert sum(event.action == "membership.remove" for event in events) == 1
        assert all(event.correlation_id for event in events)


def test_missing_resources(client, as_user):
    uid = register(client, as_user, "alice")
    as_user("admin", ["admin"])
    assert client.put(f"/api/v1/households/missing/members/{uid}").status_code == 404
    assert client.put(f"/api/v1/installations/missing/grants/{uid}").status_code == 404
