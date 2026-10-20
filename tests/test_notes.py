from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from scripts.build_notes import build, source_hash
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from dkman.deployment_adapter.compose import render_compose
from dkman.deployments.contracts import Catalog, CuratedImage, PlanRequest, build_plan
from notes_demo.main import Access, create_app, current_access


@pytest.fixture
def notes_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as db:
        db.execute(text("CREATE TABLE notes_schema (version INTEGER)"))
        db.execute(text("INSERT INTO notes_schema VALUES (1)"))
        db.execute(
            text(
                "CREATE TABLE notes (id VARCHAR PRIMARY KEY, author_subject VARCHAR, "
                "text VARCHAR, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
        )
    app = create_app(engine)
    with TestClient(app) as client:
        yield client, app, engine
    engine.dispose()


def test_notes_health_is_real_and_data_requires_authorization(notes_client):
    client, _, engine = notes_client
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/notes").status_code == 401
    assert client.post("/api/notes", json={"text": "secret"}).status_code == 401
    with engine.begin() as db:
        db.execute(text("DROP TABLE notes_schema"))
    assert client.get("/health/ready").status_code == 503


def test_shared_notes_use_server_identity_and_parameterized_storage(notes_client):
    client, app, _ = notes_client
    app.dependency_overrides[current_access] = lambda: Access("alice")
    payload = "<script>alert('x')</script>'); DROP TABLE notes; --"
    created = client.post("/api/notes", json={"text": payload})
    assert created.status_code == 201 and created.json()["author_subject"] == "alice"
    assert client.post("/api/notes", json={"text": "x", "author_subject": "bob"}).status_code == 422
    assert client.post("/api/notes", json={"text": "   "}).status_code == 422
    assert client.post("/api/notes", json={"text": "x" * 4001}).status_code == 422
    app.dependency_overrides[current_access] = lambda: Access("bob")
    items = client.get("/api/notes")
    assert items.json()[0]["text"] == payload
    assert items.headers["cache-control"] == "no-store"
    assert client.post("/api/notes", json={"text": "from Bob"}).json()["author_subject"] == "bob"


def test_notes_proxy_authorization_fails_closed(monkeypatch):
    from uuid import uuid4

    from fastapi import HTTPException

    monkeypatch.setenv("NOTES_INSTALLATION_ID", str(uuid4()))

    class Unavailable:
        def open(self, *args, **kwargs):
            raise OSError("test-only connection loss")

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Unavailable())
    with pytest.raises(HTTPException) as result:
        current_access("Bearer invalid-token")
    assert result.value.status_code == 503  # Fixed internal Core is unavailable locally.


def test_missing_adapter_data_key_is_not_silently_rotated(tmp_path):
    from scripts.generate_adapter_config import generate

    generate(tmp_path, apply=True, confirmation="ADAPTER_CONFIG")
    key = tmp_path / ".local/secrets/adapter-data-key"
    original = key.read_bytes()
    generate(tmp_path, apply=True, confirmation="ADAPTER_CONFIG")
    assert key.read_bytes() == original
    key.unlink()
    with pytest.raises(ValueError, match="Incomplete data"):
        generate(tmp_path, apply=True, confirmation="ADAPTER_CONFIG")
    assert not key.exists()


def test_runtime_overlay_keeps_socket_and_app_data_key_out_of_core_and_hub():
    import yaml

    root = Path(__file__).resolve().parents[1]
    overlay = yaml.safe_load((root / "infrastructure/compose/runtime.yaml").read_text())
    for name, service in overlay["services"].items():
        if name != "deployment-adapter":
            assert "docker.sock" not in str(service)
            assert "adapter-data-key" not in service.get("secrets", [])
        assert not service.get("ports")
    assert overlay["networks"]["app-gateway"]["internal"]


def test_build_plan_is_dry_run_and_does_not_call_docker(tmp_path, monkeypatch, capsys):
    import subprocess

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: pytest.fail("Dry-run invoked Docker")
    )
    before = source_hash(root)
    build(root)
    assert "Dry-run" in capsys.readouterr().out and source_hash(root) == before
    with pytest.raises(ValueError):
        build(tmp_path, apply=True, confirmation="wrong")


def test_curated_notes_profile_has_isolated_database_and_no_host_access():
    from uuid import uuid4

    image = CuratedImage(
        definition_id="demo-notes",
        version="0.1.0",
        image="sha256:" + "a" * 64,
        database_image="sha256:" + "b" * 64,
        internal_port=8080,
        profile="notes-postgres-v1",
        source_hash="c" * 64,
    )
    plan = build_plan(
        Catalog(images=[image]),
        PlanRequest(installation_id=uuid4(), definition_id="demo-notes", version="0.1.0"),
    )
    result = render_compose(plan, b"test-only-derivation-key-at-least-32-bytes")
    assert result["services"]["database"]["networks"] == ["private"]
    assert result["networks"]["private"]["internal"]
    assert "gateway" not in result["services"]["database"]["networks"]
    for service in result["services"].values():
        assert service["user"] == "10001:10001" and service["read_only"]
        assert service["cap_drop"] == ["ALL"]
        assert "ports" not in service and "docker.sock" not in str(service)
        assert all(mount["type"] == "volume" for mount in service.get("volumes", []))
    db = result["services"]["database"]["environment"]
    assert db["POSTGRES_PASSWORD"] != db["NOTES_DB_PASSWORD"]
    assert result == render_compose(plan, b"test-only-derivation-key-at-least-32-bytes")
