import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url


@pytest.mark.postgres
def test_postgres_migrations_round_trip(monkeypatch):
    url = os.environ.get("DKMAN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("No disposable PostgreSQL: set DKMAN_TEST_DATABASE_URL")
    if not make_url(url).database.endswith("_test"):
        pytest.fail("Refusing migration test: database name must end with _test")
    monkeypatch.setenv("DKMAN_DATABASE_URL", url)
    config = Config("backend/alembic.ini")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)
    engine = create_engine(url)
    assert "app_installations" in inspect(engine).get_table_names()
    command.downgrade(config, "base")
    assert "app_installations" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    engine.dispose()
