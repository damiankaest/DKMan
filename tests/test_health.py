from sqlalchemy import text


def test_liveness_without_database_schema(client):
    result = client.get("/health/live")
    assert result.status_code == 200
    assert result.json()["status"] == "healthy"
    assert len(result.headers["x-request-id"]) == 36
    assert result.headers["cache-control"] == "no-store"


def test_readiness_rejects_missing_and_wrong_revision(client, engine):
    assert client.get("/health/ready").status_code == 503
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('wrong')"))
    assert client.get("/health/ready").status_code == 503
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='0003_deployment_targets'"))
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "ready"
    assert response.json()["schema"] == "current"
