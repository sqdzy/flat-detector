"""Integration of the real MCP SDK with a seeded, in-memory database (not mocked MCP)."""
import json
from datetime import datetime, timedelta, timezone
import pytest
from mcp import Client
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from flat_detector.models import Base, Source, Evidence, Subscriber
from flat_detector.service import ingest
from flat_detector import mcp_server

@pytest.mark.asyncio
async def test_mcp_four_tools_return_real_readonly_data_and_no_subscribers(monkeypatch):
    now = datetime.now(timezone.utc)
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(mcp_server, "Session", session_factory)
    with session_factory() as db:
        src = Source(key="sdk_fixture", mode="APPROVED_FEED", enabled=True,
                     permission_scope="search,store,notify", permission_proof="synthetic test-only approval",
                     permission_checked_at=now-timedelta(days=1),permission_expires_at=now+timedelta(days=1))
        db.add(src); db.commit()
        listing=ingest(db,src,dict(external_id="sdk-1",original_url="https://example.org/test-card",
                                 price_rub=7_700_000,area_sqm=34.5,rooms=1,address="Synthetic Khimki",
                                 geo_approved=True,route_minutes=10,route_method="WALK_ROUTE",route_provider="manual fixture"),now)
        db.add(Evidence(listing_id=listing.id,signal="ACTIVE",observed_at=now,origin_key="sdk_fixture",direct=True))
        db.add(Subscriber(chat_id=987654321,active=True,consent_at=now))
        db.commit()
        listing_id=listing.id

    async with Client(mcp_server.mcp) as client:
        cases = [
            ("list_active_listings", {"max_price_rub":8_500_000}),
            ("get_listing_evidence", {"listing_id":listing_id}),
            ("get_source_health", {}),
            ("preview_daily_digest", {"local_day":now.date().isoformat()}),
        ]
        outputs={}
        for name,inputs in cases:
            result=await client.call_tool(name,inputs)
            assert not result.is_error, (name,result.content)
            assert result.content and result.content[0].type == "text", name
            outputs[name]=result.structured_content or json.loads(result.content[0].text)
        assert len(outputs["list_active_listings"]["items"])==1
        assert outputs["get_listing_evidence"]["id"]==listing_id
        assert outputs["get_source_health"]["sources"][0]["key"]=="sdk_fixture"
        assert "Synthetic Khimki" in outputs["preview_daily_digest"]["text"]
        assert "987654321" not in str(outputs), "Subscriber identifiers must never reach model tools"
        denied=await client.call_tool("execute_command",{"command":"echo hello"})
        assert denied.is_error
    engine.dispose()
