"""PostgreSQL in production, ephemeral SQLite only for local/CI fixture tests."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from flat_detector.config import get_settings

settings=get_settings()
url=settings.database_url
if settings.database_url == "postgresql+psycopg://":
    from sqlalchemy.engine import URL
    from pathlib import Path
    import os
    password_path=os.getenv("FD_DB_PASSWORD_FILE","")
    if not password_path:raise RuntimeError("FD_DB_PASSWORD_FILE required for PostgreSQL")
    url=URL.create("postgresql+psycopg",username=os.getenv("FD_DB_USER","flat_detector"),
                   password=Path(password_path).read_text(encoding="utf-8").strip(),
                   host=os.getenv("FD_DB_HOST","db"),port=5432,database=os.getenv("FD_DB_NAME","flat_detector"))
engine=create_engine(url, pool_pre_ping=True)
Session=sessionmaker(bind=engine, expire_on_commit=False)


def migrate_dev() -> None:
    # Only initial SQLite development; production MUST use Alembic.
    if engine.dialect.name != "sqlite": return
    from flat_detector.models import Base
    Base.metadata.create_all(engine)
