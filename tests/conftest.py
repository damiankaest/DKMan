import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from dkman.auth import Principal, current_principal
from dkman.config import Settings
from dkman.main import create_app
from dkman.models import Base


@pytest.fixture
def engine():
    value = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(value, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(value)
    yield value
    value.dispose()


@pytest.fixture
def app(engine):
    return create_app(Settings(), engine)


@pytest.fixture
def client(app):
    with TestClient(app) as value:
        yield value


@pytest.fixture
def as_user(app):
    def login(subject="alice", roles=("member",)):
        app.dependency_overrides[current_principal] = lambda: Principal(
            subject=subject, display_name=subject, roles=frozenset(roles)
        )

    yield login
    app.dependency_overrides.clear()
