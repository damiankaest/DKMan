"""Explicit application migration, serialized even across simultaneous starts."""

from pathlib import Path

from sqlalchemy import Engine, text

from notes_demo.database import database_engine


def migrate(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(620034001)"))
        exists = connection.scalar(text("SELECT to_regclass('public.notes_schema')"))
        if exists is None:
            sql = (Path(__file__).parent / "migrations/0001_notes.sql").read_text()
            for statement in sql.split(";"):
                if statement.strip():
                    connection.exec_driver_sql(statement)
        elif connection.scalar(text("SELECT version FROM notes_schema")) != 1:
            raise ValueError("Unsupported Notes schema; restore or migrate explicitly")


if __name__ == "__main__":
    engine = database_engine()
    try:
        migrate(engine)
    finally:
        engine.dispose()
