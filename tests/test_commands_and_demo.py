"""Extra negative/consent/demonstration tests from the pilot safety gate."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import asyncio
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from flat_detector.bot import apply_command
from flat_detector.models import Source,Subscriber,Evidence,Outbox,Listing,Base
from flat_detector.delivery import TelegramError,deliver_once, schedule_due,render_digest,TelegramResult
from flat_detector.service import DailyProfile,ingest,source_is_permitted,evaluate_status,safe_original_url
from flat_detector.mcp_tools import request_listing_recheck, list_active_listings,get_listing_evidence,preview_daily_digest

NOW=datetime(2026,9,23,9,0,tzinfo=timezone.utc)

def test_bot_consent_commands_and_errors(db):
    assert "Сначала" in apply_command(db,456,"/subscribe",NOW)
    assert "/subscribe" in apply_command(db,456,"/start",NOW)
    assert "Сначала" in apply_command(db,456,"/confirm",NOW)
    assert "Подтверждаешь" in apply_command(db,456,"/subscribe",NOW)
    assert "включена" in apply_command(db,456,"/confirm",NOW)
    assert "бюджет" in apply_command(db,456,"/budget 99999999",NOW).lower()
    assert "Лимит" in apply_command(db,456,"/budget 8500000",NOW)
    assert "Неизвестная" in apply_command(db,456,"/timezone Invalid/Nowhere",NOW)
    assert "Часовой" in apply_command(db,456,"/timezone Europe/Berlin",NOW)
    assert "от 0 до 23" in apply_command(db,456,"/hour 30",NOW)
    assert "11:00" in apply_command(db,456,"/hour 11",NOW)
    assert "включена" in apply_command(db,456,"/settings",NOW)
    assert "подходящих" in apply_command(db,456,"/digest",NOW)
    apply_command(db,456,"/stop",NOW)
    assert not db.scalar(select(Subscriber).where(Subscriber.chat_id==456)).active
    assert "выключена" in apply_command(db,456,"/settings",NOW)


def test_synthetic_fixture_cannot_be_queried_without_demo_flag(monkeypatch):
    from flat_detector import fixture
    engine=create_engine('sqlite+pysqlite:///:memory:',poolclass=StaticPool,connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(fixture,"Session",factory)
    monkeypatch.setattr(fixture,"migrate_dev",lambda:None)
    monkeypatch.setattr(fixture,"get_settings",lambda:SimpleNamespace(demo_mode=False))
    with pytest.raises(PermissionError):fixture.seed(NOW)
    monkeypatch.setattr(fixture,"get_settings",lambda:SimpleNamespace(demo_mode=True))
    assert fixture.seed(NOW)==3
    with factory() as db:
        assert list_active_listings(db,now=NOW)["items"]==[]
        visible=list_active_listings(db,now=NOW,max_price_rub=9_000_000,include_demo=True)["items"]
        assert len(visible)==2 and all(x["demo"] for x in visible)
        assert preview_daily_digest(db,'2026-09-23',now=NOW,max_price_rub=9_000_000,include_demo=True)["text"].count('[СИНТЕТИЧЕСКИЕ ДАННЫЕ]')==2
        removed=db.scalar(select(Listing).where(Listing.external_id=="SYNTH-003"))
        assert evaluate_status(db,removed,NOW)=="REMOVED"
        assert get_listing_evidence(db,removed.id,now=NOW)["status"]=="REMOVED"
    engine.dispose()


def test_owner_recheck_strict(db):
    import uuid
    src=Source(key="partner",mode="APPROVED_FEED",enabled=True,permission_scope="search,store,notify",permission_proof="synthetic unit-test contract",permission_checked_at=NOW,permission_expires_at=NOW+timedelta(days=5))
    db.add(src);db.commit()
    listing=ingest(db,src,{"external_id":"1","original_url":"https://example.org/test","price_rub":8_000_000,
                         "area_sqm":30,"rooms":1,"address":"test","geo_approved":False},NOW)
    key=str(uuid.uuid4())
    with pytest.raises(PermissionError):request_listing_recheck(db,listing.id,True,"recheck",key,"analyst",NOW)
    with pytest.raises(PermissionError):request_listing_recheck(db,listing.id,False,"recheck",key,"owner",NOW)
    created=request_listing_recheck(db,listing.id,True,"recheck",key,"owner",NOW)
    assert created["state"]=="WAITING_FOR_APPROVED_ADAPTER"
    assert created==request_listing_recheck(db,listing.id,True,"recheck",key,"owner",NOW)


@pytest.mark.asyncio
async def test_telegram_403_unsubscribes(db):
    src=Source(key="partner",mode="APPROVED_FEED",enabled=True,permission_scope="search,store,notify",permission_proof="synthetic unit-test contract",permission_checked_at=NOW,permission_expires_at=NOW+timedelta(days=5))
    db.add(src);db.commit()
    l=ingest(db,src,{"external_id":"1","original_url":"https://example.org/test","price_rub":8_000_000,
                     "area_sqm":30,"rooms":1,"address":"test","geo_approved":True,"route_minutes":11,
                     "route_method":"WALK_ROUTE","route_provider":"test"},NOW)
    db.add(Evidence(listing_id=l.id,signal="ACTIVE",observed_at=NOW,origin_key="partner",direct=True))
    sub=Subscriber(chat_id=123,active=True,consent_at=NOW,timezone="Europe/Berlin",digest_hour=11)
    db.add(sub);db.commit()
    assert schedule_due(db,NOW)==1
    class Blocked:
        async def send(self,*args):raise TelegramError(403)
    assert await deliver_once(db,Blocked(),NOW)=="BLOCKED"
    assert not sub.active
    assert await deliver_once(db,Blocked(),NOW)=="EMPTY"


def test_new_update_cannot_make_deleted_listing_appear(db):
    src=Source(key="partner",mode="APPROVED_FEED",enabled=True,permission_scope="search,store,notify",permission_proof="synthetic unit-test contract",permission_checked_at=NOW,permission_expires_at=NOW+timedelta(days=5))
    db.add(src);db.commit()
    l=ingest(db,src,{"external_id":"1","original_url":"https://example.org/test","price_rub":8_000_000,
                     "area_sqm":30,"rooms":1,"address":"test"},NOW)
    db.add_all([Evidence(listing_id=l.id,signal="ACTIVE",origin_key="partner",direct=True,observed_at=NOW),
                Evidence(listing_id=l.id,signal="REMOVED",origin_key="partner",direct=True,observed_at=NOW+timedelta(minutes=5))])
    db.commit()
    assert evaluate_status(db,l,NOW+timedelta(minutes=6))=="REMOVED"
