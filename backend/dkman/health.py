from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from dkman.models import utcnow
from dkman.schemas import HealthView

SCHEMA_REVISION = "0002_durable_jobs"


def readiness(engine: Engine) -> HealthView:
    database = False
    schema = False
    try:
        with engine.connect() as connection:
            database = connection.execute(text("SELECT 1")).scalar() == 1
            schema = (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                == SCHEMA_REVISION
            )
    except SQLAlchemyError:
        pass
    return HealthView(
        status="healthy" if database and schema else "unhealthy",
        checked_at=utcnow(),
        database="ready" if database else "unavailable",
        schema_state="current" if schema else "unavailable",
    )
