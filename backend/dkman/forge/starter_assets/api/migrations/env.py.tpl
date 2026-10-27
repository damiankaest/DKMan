import os
from alembic import context
from sqlalchemy import create_engine

url = os.environ.get("DATABASE_URL")
if not url:
    raise RuntimeError("DATABASE_URL is required for migration")
if context.is_offline_mode():
    context.configure(url=url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, hide_parameters=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
