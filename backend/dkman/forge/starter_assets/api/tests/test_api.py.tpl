from fastapi.testclient import TestClient
from app.access import Access, current_access
from app.main import app


def test_health_and_access_fail_closed(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "healthy"}
        assert client.get("/api/me").status_code == 401
        assert client.get("/health/ready").status_code == 503


def test_authenticated_subject():
    app.dependency_overrides[current_access] = lambda: Access("tester")
    try:
        with TestClient(app) as client:
            assert client.get("/api/me").json() == {"subject": "tester"}
    finally:
        app.dependency_overrides.clear()


def test_core_authorization_is_bound_to_installation(monkeypatch):
    import json
    import urllib.error
    from app import access
    from fastapi import HTTPException
    from pytest import raises

    installation = "12345678-1234-1234-1234-123456789abc"
    monkeypatch.setenv("DKMAN_INSTALLATION_ID", installation)
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def read(self, limit):
            assert limit == 4097
            return json.dumps({"installation_id": installation, "subject": "alice"}).encode()
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == f"http://core:8000/api/v1/apps/{installation}/access"
            assert request.get_header("Authorization") == "Bearer sample"
            assert timeout == 3
            return Reply()
    monkeypatch.setattr(access.urllib.request, "build_opener", lambda *_: Opener())
    assert access.current_access("Bearer sample").subject == "alice"
    class Denied:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "denied", {}, None)
    monkeypatch.setattr(access.urllib.request, "build_opener", lambda *_: Denied())
    with raises(HTTPException) as denied:
        access.current_access("Bearer sample")
    assert denied.value.status_code == 403
    monkeypatch.delenv("DKMAN_INSTALLATION_ID")
    with raises(HTTPException) as missing:
        access.current_access("Bearer sample")
    assert missing.value.status_code == 503


def test_database_revision_is_checked_after_explicit_migration(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from pathlib import Path
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "starter_test.db"))
    root = Path(__file__).resolve().parents[1]
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 503
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=os.environ.copy(), check=True)
        assert client.get("/health/ready").status_code == 200
        subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=root, env=os.environ.copy(), check=True)
        assert client.get("/health/ready").status_code == 503
