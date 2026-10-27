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
