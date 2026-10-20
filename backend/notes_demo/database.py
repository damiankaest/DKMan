import os

from sqlalchemy import URL, Engine, create_engine


def database_engine() -> Engine:
    return create_engine(
        URL.create(
            "postgresql+psycopg",
            username="notes_app",
            password=os.environ["NOTES_DB_PASSWORD"],
            host="database",
            database="notes",
        ),
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
