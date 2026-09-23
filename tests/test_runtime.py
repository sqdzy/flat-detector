from datetime import datetime,timedelta,timezone
import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient
from flat_detector.web import app
from flat_detector.models import Source,Evidence,Listing,Subscriber,Outbox,aware
from flat_detector.service import ingest,safe_original_url,evaluate_status
from flat_detector.bot import TelegramBotAPI
from flat_detector.delivery import deliver_once,schedule_due

NOW=datetime(2026,9,23,9,0,tzinfo=timezone.utc)

def test_health():
    with TestClient(app) as c:
        assert c.get("/health/live").json()=={"status":"live"}

def test_display_url_validation():
    for url in ("http://example.org/a","https://127.0.0.1/a","https://example.org:22/a", "https://evil@example.org/x","https://localhost/a"):
        with pytest.raises(ValueError):safe_original_url(url)
    assert safe_original_url("https://example.org/a") == "https://example.org/a"

def test_blocked_source_not_removed(db):
    src=Source(key="partner",enabled=True,mode="APPROVED_FEED",permission_scope="search,store,notify",permission_proof="synthetic unit-test contract",permission_checked_at=NOW,permission_expires_at=NOW+timedelta(days=1))
    db.add(src);db.commit()
    l=ingest(db,src,dict(external_id="id",original_url="https://example.org/1",price_rub=7000000,area_sqm=33,rooms=1,address="test"),NOW)
    from flat_detector.service import store_source_error
    db.add(Evidence(listing_id=l.id,signal="ACTIVE",origin_key="partner",direct=True,observed_at=NOW));db.commit()
    store_source_error(db,src,403,NOW)
    assert evaluate_status(db,l,NOW)=="ACTIVE_DIRECT"
    assert src.last_error_code=="SOURCE_BLOCKED"

@pytest.mark.asyncio
async def test_telegram_http_mock():
    def server(req:httpx.Request):
        assert req.url.host=="api.telegram.org"
        assert req.url.path.endswith("/sendMessage")
        return httpx.Response(200,json={"ok":True,"result":{"message_id":42}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        t=TelegramBotAPI("fake-token",client=client)
        sent=await t.send(111,"hi")
        assert sent.message_id==42

@pytest.mark.asyncio
async def test_unknown_delivery_result_is_not_retried(db):
    src=Source(key="partner",enabled=True,mode="APPROVED_FEED",permission_scope="search,store,notify",permission_proof="synthetic unit-test contract",permission_checked_at=NOW,permission_expires_at=NOW+timedelta(days=1))
    db.add(src);db.commit()
    l=ingest(db,src,dict(external_id="id",original_url="https://example.org/1",price_rub=7000000,area_sqm=33,rooms=1,address="test",geo_approved=True,route_minutes=11,route_method="WALK_ROUTE",route_provider="fixture"),NOW)
    db.add(Evidence(listing_id=l.id,signal="ACTIVE",origin_key="partner",direct=True,observed_at=NOW))
    db.add(Subscriber(chat_id=123,active=True,consent_at=NOW,timezone="Europe/Berlin",digest_hour=11))
    db.commit()
    assert schedule_due(db,NOW)==1
    class Unknown:
        calls=0
        async def send(self,*args):self.calls+=1;raise TimeoutError("unknown result")
    sender=Unknown()
    assert await deliver_once(db,sender,NOW)=="UNCERTAIN"
    assert await deliver_once(db,sender,NOW+timedelta(seconds=10))=="EMPTY"
    assert db.query(Outbox).one().status=="UNCERTAIN" and sender.calls==1
