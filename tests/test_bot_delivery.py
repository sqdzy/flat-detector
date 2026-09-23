from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flat_detector.models import Subscriber, Source, Evidence, Outbox, aware
from flat_detector.service import ingest
from flat_detector.bot import apply_command
from flat_detector.delivery import schedule_due, deliver_once, TelegramResult, TelegramError

NOW=datetime(2026,9,23,9,0,tzinfo=timezone.utc)  # 11:00 Berlin DST

def subscriber(db):
    s=Subscriber(chat_id=123,active=False,consent_at=None,timezone="Europe/Berlin",digest_hour=11,max_price_rub=8500000)
    db.add(s);db.commit();return s

def seed_listing(db):
    s=Source(key="fixture",mode="APPROVED_FEED",enabled=True,permission_scope="search,store,notify",permission_proof="synthetic unit-test contract",permission_checked_at=NOW,permission_expires_at=NOW+timedelta(days=10))
    db.add(s);db.commit()
    l=ingest(db,s,dict(external_id="1",original_url="https://example.org/test",price_rub=7_700_000,area_sqm=33.0,
                       rooms=1,address="Демонстрация",geo_approved=True,route_minutes=12,route_method="WALK_ROUTE",route_provider="fixture"),NOW)
    db.add(Evidence(listing_id=l.id,signal="ACTIVE",observed_at=NOW,origin_key="fixture",direct=True));db.commit()

def test_opt_in_and_stop(db):
    s=subscriber(db)
    assert "подпис" in apply_command(db,123,"/start",NOW).lower()
    assert not s.active
    apply_command(db,123,"/subscribe",NOW)
    assert not s.active
    apply_command(db,123,"/confirm",NOW)
    assert s.active and s.consent_at is not None
    apply_command(db,123,"/stop",NOW)
    assert not s.active

def test_scheduler_unique_by_local_day_and_dst(db):
    s=subscriber(db);s.active=True;s.consent_at=NOW;db.commit();seed_listing(db)
    assert schedule_due(db,NOW)==1
    assert schedule_due(db,NOW)==0
    assert db.query(Outbox).count()==1
    # End-of-October CET change: 11:00 Berlin = 10:00 UTC
    later=datetime(2026,10,27,10,0,tzinfo=timezone.utc)
    assert later.astimezone(ZoneInfo("Europe/Berlin")).hour==11

def test_stop_before_send(db):
    s=subscriber(db);s.active=True;s.consent_at=NOW;db.commit();seed_listing(db)
    schedule_due(db,NOW)
    apply_command(db,123,"/stop",NOW)
    class Fake:
        async def send(self,chat_id,text): raise AssertionError("should never send")
    import asyncio
    assert asyncio.run(deliver_once(db,Fake(),NOW))=="EMPTY"

def test_send_429_retries_without_duplicate(db):
    s=subscriber(db);s.active=True;s.consent_at=NOW;db.commit();seed_listing(db)
    schedule_due(db,NOW)
    class Fake:
        calls=0
        async def send(self,chat_id,text):
            self.calls+=1
            if self.calls==1: raise TelegramError(429, 13)
            return TelegramResult(message_id=321)
    import asyncio
    client=Fake()
    assert asyncio.run(deliver_once(db,client,NOW))=="RETRY"
    item=db.query(Outbox).one()
    assert aware(item.next_attempt_at)>=NOW+timedelta(seconds=13)
    assert asyncio.run(deliver_once(db,client,NOW+timedelta(seconds=14)))=="SENT"
    assert asyncio.run(deliver_once(db,client,NOW+timedelta(seconds=16)))=="EMPTY"
    assert client.calls==2

def test_delete_profile_removes_notifications(db):
    s=subscriber(db);s.active=True;s.consent_at=NOW;db.commit();seed_listing(db)
    schedule_due(db,NOW)
    assert "удален" in apply_command(db,123,"/delete_me",NOW).lower()
    assert db.query(Subscriber).count()==0 and db.query(Outbox).count()==0
