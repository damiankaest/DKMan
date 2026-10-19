from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dkman.manifest import parse_manifest
from dkman.models import (
    AppDefinition,
    AppInstallation,
    AuditEvent,
    Household,
    PermissionGrant,
    ServiceInstance,
    ServiceManifest,
)
from dkman.seed import seed

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def manifest():
    return parse_manifest((ROOT / "examples/demo-notes/dkman.yaml").read_text())


def test_api_is_closed_by_default(client):
    for route in ["me", "apps", "services", "catalog", "capabilities", "platform"]:
        assert client.get(f"/api/v1/{route}").status_code == 401
    assert client.post("/api/v1/registry/manifests", json={}).status_code == 401


def test_member_cannot_register_or_view_catalog(client, as_user, manifest):
    as_user()
    assert (
        client.post(
            "/api/v1/registry/manifests", json=manifest.model_dump(by_alias=True)
        ).status_code
        == 403
    )
    assert client.get("/api/v1/catalog").status_code == 403


def test_registration_is_metadata_only_and_audited(client, as_user, engine, manifest):
    as_user("admin", ["admin"])
    data = manifest.model_dump(by_alias=True)
    response = client.post("/api/v1/registry/manifests", json=data)
    assert response.status_code == 201
    assert client.post("/api/v1/registry/manifests", json=data).status_code == 409
    assert len(client.get("/api/v1/catalog").json()) == 1
    assert client.get("/api/v1/apps").json() == []
    with Session(engine) as db:
        audit = db.scalar(select(AuditEvent))
        assert audit.actor_subject == "admin"
        assert audit.action == "registry.register"
        assert len(audit.correlation_id) == 36


def test_assigned_apps_only_and_no_fake_runtime(client, as_user, engine, manifest):
    as_user("admin", ["admin"])
    assert (
        client.post(
            "/api/v1/registry/manifests", json=manifest.model_dump(by_alias=True)
        ).status_code
        == 201
    )
    with Session(engine) as db:
        household = Household(id="home", name="Test home")
        db.add(household)
        db.flush()
        stored = db.scalar(select(ServiceManifest))
        db.add(
            AppInstallation(
                id="notes-one",
                definition_id=manifest.id,
                manifest_id=stored.id,
                household_id=household.id,
                owner_subject="alice",
            )
        )
        db.flush()
        db.add(PermissionGrant(installation_id="notes-one", subject="alice", permission="app.use"))
        db.add(
            ServiceInstance(
                id="service-one",
                installation_id="notes-one",
                provider="docker-compose",
                runtime_id=None,
                status="unknown",
            )
        )
        db.commit()
    as_user("bob")
    assert client.get("/api/v1/apps").json() == []
    assert client.get("/api/v1/apps/notes-one").status_code == 404
    assert client.get("/api/v1/services/service-one").status_code == 404
    assert client.get("/api/v1/capabilities").json() == []
    as_user("alice")
    result = client.get("/api/v1/apps").json()
    assert [item["id"] for item in result] == ["notes-one"]
    assert result[0]["status"] == "unknown"
    assert result[0]["checked_at"] is None
    assert result[0]["route"] is None
    assert client.get("/api/v1/services/service-one").status_code == 200
    assert len(client.get("/api/v1/capabilities").json()) == 2
    as_user("admin", ["admin"])
    assert len(client.get("/api/v1/apps").json()) == 1


def test_unknown_extra_field_rejected(client, as_user, manifest):
    as_user("admin", ["admin"])
    data = manifest.model_dump(by_alias=True)
    data["runtime"]["privileged"] = True
    assert client.post("/api/v1/registry/manifests", json=data).status_code == 422


def test_database_failure_is_sanitized(client, engine, as_user):
    as_user("admin", ["admin"])
    AppDefinition.__table__.drop(engine)
    result = client.get("/api/v1/catalog")
    assert result.status_code == 503
    assert result.json()["detail"] == "Database operation unavailable"
    assert "SQL" not in result.text


def test_bundled_seed_is_idempotent_metadata_only(engine):
    with Session(engine) as db:
        assert seed(db, ROOT / "examples") == 2
        assert seed(db, ROOT / "examples") == 0
        assert list(db.scalars(select(AppInstallation))) == []
