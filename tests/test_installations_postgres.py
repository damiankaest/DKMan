"""Actual PostgreSQL reservation races; no SQLite lock claims."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from dkman.auth import Principal
from dkman.config import Settings
from dkman.deployment_api import InstallInput, plan_installation
from dkman.deployments.contracts import Catalog, CuratedImage
from dkman.models import DeploymentTarget, Household, Job
from dkman.seed import seed

pytestmark = pytest.mark.postgres


@pytest.fixture
def pg_setup(tmp_path, monkeypatch):
    url = os.environ.get("DKMAN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires disposable PostgreSQL for deployment reservation races")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Refusing database without _test suffix")
    monkeypatch.setenv("DKMAN_DATABASE_URL", url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_engine(url, hide_parameters=True)
    settings = Settings(deployment_enabled=True, deployment_catalog_file=tmp_path / "catalog.json")
    settings.deployment_catalog_file.write_text(
        Catalog(
            images=[
                CuratedImage(
                    definition_id="demo-notes",
                    version="0.1.0",
                    image="sha256:" + "a" * 64,
                    database_image="sha256:" + "b" * 64,
                    internal_port=8080,
                    profile="notes-postgres-v1",
                    source_hash="c" * 64,
                )
            ]
        ).model_dump_json()
    )
    with Session(engine) as db:
        seed(db, Path(__file__).resolve().parents[1] / "examples")
        group = Household(name="Concurrent deployment " + str(uuid4()))
        db.add(group)
        db.commit()
        group_id = group.id
    yield engine, settings, group_id
    engine.dispose()


def race_plans(pg_setup, keys):
    engine, settings, group_id = pg_setup
    barrier = Barrier(len(keys))
    actor = Principal("pg-install-admin", "Admin", frozenset({"admin"}))

    def submit(key):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            request = SimpleNamespace(
                app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
                state=SimpleNamespace(correlation_id=str(uuid4())),
            )
            try:
                return plan_installation(
                    InstallInput(definition_id="demo-notes", household_id=group_id),
                    request,
                    Response(),
                    db,
                    actor,
                    key,
                ).id
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        return list(pool.map(submit, keys))


def test_concurrent_install_duplicates_share_one_job_target_and_approval(pg_setup):
    key = str(uuid4())
    result = race_plans(pg_setup, [key] * 4)
    assert len(set(result)) == 1 and result[0] != 409
    with Session(pg_setup[0]) as db:
        assert (
            db.scalar(select(func.count()).select_from(Job).where(Job.idempotency_key == key)) == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(DeploymentTarget)
                .where(DeploymentTarget.household_id == pg_setup[2])
            )
            == 1
        )


def test_different_keys_cannot_create_two_installations_in_one_household(pg_setup):
    result = race_plans(pg_setup, [str(uuid4()), str(uuid4())])
    assert result.count(409) == 1
    with Session(pg_setup[0]) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DeploymentTarget)
                .where(DeploymentTarget.household_id == pg_setup[2])
            )
            == 1
        )
