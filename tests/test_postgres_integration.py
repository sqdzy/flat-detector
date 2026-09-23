"""Real PostgreSQL gates. CI provides ephemeral PG 17; never silently use SQLite."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text, select, func
from sqlalchemy.orm import sessionmaker
from flat_detector.models import Base, Source, Subscriber, Outbox, Evidence
from flat_detector.service import ingest
from flat_detector.delivery import schedule_due, deliver_once, TelegramResult


@pytest.fixture(scope="module")
def pg_engine():
    dsn = os.getenv("FD_PG_INTEGRATION_DSN")
    if not dsn:
        pytest.skip("FD_PG_INTEGRATION_DSN not configured; real PG CI runs this test")
    if not dsn.startswith("postgresql+psycopg://"):
        pytest.fail("FD_PG_INTEGRATION_DSN must use PostgreSQL psycopg, never SQLite")
    schema = "fd_ci_" + uuid.uuid4().hex[:16]
    root = create_engine(dsn, pool_pre_ping=True)
    with root.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = create_engine(dsn, connect_args={"options": f"-c search_path={schema}"}, pool_pre_ping=True)
    try:
        with isolated.begin() as conn:
            config = Config("alembic.ini")
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        assert "subscribers" in inspect(isolated).get_table_names()
        assert "outbox" in inspect(isolated).get_table_names()
        yield isolated
        with isolated.begin() as conn:
            config = Config("alembic.ini")
            config.attributes["connection"] = conn
            command.downgrade(config, "base")
        assert "subscribers" not in inspect(isolated).get_table_names()
    finally:
        isolated.dispose()
        with root.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        root.dispose()


@pytest.mark.asyncio
async def test_postgres_unique_digest_and_concurrent_delivery(pg_engine):
    session_factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    # September 23, 2026: 09:00 UTC equals 11:00 Europe/Berlin (DST).
    now = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
    with session_factory() as db:
        source = Source(key="pg_fixture", mode="APPROVED_FEED", enabled=True,
                        permission_scope="search,store,notify", permission_proof="ephemeral PostgreSQL CI fixture",
                        permission_checked_at=now-timedelta(days=1), permission_expires_at=now+timedelta(days=1))
        db.add(source)
        user = Subscriber(chat_id=54321,active=True,consent_at=now, timezone="Europe/Berlin",digest_hour=11)
        db.add(user); db.commit()
        listing=ingest(db,source,dict(external_id="pg-1",original_url="https://example.org/fixture",
            price_rub=7_500_000,area_sqm=31,rooms=1,address="Postgres synthetic",
            geo_approved=True,route_minutes=7,route_method="WALK_ROUTE",route_provider="CI fixture"),now)
        db.add(Evidence(listing_id=listing.id,signal="ACTIVE",observed_at=now,origin_key="pg_fixture",direct=True))
        db.commit()
        assert schedule_due(db,now)==1
        assert schedule_due(db,now)==0

    class DelayedTransport:
        def __init__(self):
            self.started=asyncio.Event()
            self.release=asyncio.Event()
            self.count=0
        async def send(self,chat_id,message):
            self.count+=1
            self.started.set()
            await self.release.wait()
            return TelegramResult(message_id=991)

    transport=DelayedTransport()
    with session_factory() as s1, session_factory() as s2:
        first=asyncio.create_task(deliver_once(s1,transport,now))
        await asyncio.wait_for(transport.started.wait(),5)
        # PostgreSQL SKIP LOCKED + persisted CLAIMED prevents a second send.
        assert await asyncio.wait_for(deliver_once(s2,transport,now),5)=="EMPTY"
        transport.release.set()
        assert await asyncio.wait_for(first,5)=="SENT"
        assert transport.count==1
        assert s2.scalar(select(func.count()).select_from(Outbox).where(Outbox.status=="SENT"))==1
