"""Online migrations only; never include DB secrets in Alembic logs."""
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config,pool
from flat_detector.database import engine
from flat_detector.models import Base

config=context.config
if config.config_file_name:fileConfig(config.config_file_name)
target_metadata=Base.metadata

def _run_on_connection(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # CI can pass a dedicated PostgreSQL connection with an isolated search_path.
    # Production, which has no injected connection, retains the standard engine.
    supplied = config.attributes.get("connection")
    if supplied is not None:
        _run_on_connection(supplied)
    else:
        with engine.connect() as connection:
            _run_on_connection(connection)

run_migrations_online()
