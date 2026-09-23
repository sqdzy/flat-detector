"""Authorized JSON feed adapter must never turn HTTP denial into removed listings."""
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from sqlalchemy import select
from flat_detector.models import Source, Listing, Evidence
from flat_detector.collector import ApprovedJSONFeed, FeedDenied, FeedRejected
from flat_detector.service import shortlist,DailyProfile

NOW=datetime(2026,9,23,8,tzinfo=timezone.utc)
URL="https://partner.example.test/api/v1/flats"


def make_source(db, *, enabled=True, proof="Fixture-only authorization"):
    s=Source(key="test_partner",mode="APPROVED_FEED",enabled=enabled,
             permission_scope="search,store,notify",permission_proof=proof,
             permission_checked_at=NOW,permission_expires_at=NOW+timedelta(days=7))
    db.add(s);db.commit();return s


def sample():
    return {"items":[{"external_id":"P1", "original_url":"https://partner.example.test/flats/1",
                      "price_rub":8_100_000,"area_sqm":32.0,"rooms":1,
                      "address":"TEST — Химки", "availability":"ACTIVE"}]}


@pytest.mark.asyncio
async def test_permission_denial_does_not_make_network_request(db):
    s=make_source(db,proof="")
    calls=[]
    def reply(request):
        calls.append(request)
        return httpx.Response(200,json=sample())
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        feed=ApprovedJSONFeed(URL,approved_origin="https://partner.example.test",client=client)
        with pytest.raises(PermissionError):await feed.collect(db,s,NOW)
    assert calls==[]


@pytest.mark.asyncio
async def test_strict_origin_path_and_https(db):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,json=sample()))) as client:
        for url in ["http://partner.example.test/api/v1/flats", "https://partner.example.test.attacker.invalid/api/v1/flats", 
                    "https://localhost/api/v1/flats", "https://user@partner.example.test/api/v1/flats"]:
            with pytest.raises(ValueError):ApprovedJSONFeed(url,approved_origin="https://partner.example.test",client=client)
        with pytest.raises(ValueError):ApprovedJSONFeed(URL,approved_origin="https://other.example.test",client=client)


@pytest.mark.asyncio
async def test_403_429_and_redirect_are_fail_closed_and_preserve_existing_evidence(db):
    s=make_source(db)
    for status,expected in [(403,"SOURCE_BLOCKED"),(429,"RATE_LIMITED"),(302,"SOURCE_ERROR")]:
        def reply(request):return httpx.Response(status,headers={"Location":"http://169.254.169.254/latest/meta-data/"} if status==302 else {})
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            feed=ApprovedJSONFeed(URL,approved_origin="https://partner.example.test",client=client)
            with pytest.raises(FeedDenied):await feed.collect(db,s,NOW)
        assert s.last_error_code==expected
        assert db.scalars(select(Evidence)).all()==[]


@pytest.mark.asyncio
async def test_ingested_records_require_separate_geo_route_verification(db):
    s=make_source(db)
    payload=sample()
    payload["items"][0].update({"geo_approved":True,"route_minutes":5,"route_method":"WALK_ROUTE"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=payload))) as client:
        feed=ApprovedJSONFeed(URL,approved_origin="https://partner.example.test",client=client)
        assert await feed.collect(db,s,NOW)==1
        assert await feed.collect(db,s,NOW+timedelta(minutes=1))==1
    listing=db.scalar(select(Listing))
    assert listing.geo_approved is False
    assert listing.route_minutes is None
    assert shortlist(db,DailyProfile(),NOW+timedelta(minutes=1))==([],[])
    assert len(db.scalars(select(Evidence)).all())==2


@pytest.mark.asyncio
async def test_malformed_feed_does_not_partially_write(db):
    s=make_source(db)
    valid=sample()["items"][0]
    bad={"items":[valid,{"external_id":"P2","original_url":"https://partner.example.test/flats/2",
                         "price_rub":-1,"area_sqm":20,"rooms":1,"address":"bad"}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=bad))) as client:
        feed=ApprovedJSONFeed(URL,approved_origin="https://partner.example.test",client=client)
        with pytest.raises(FeedRejected):await feed.collect(db,s,NOW)
    assert db.scalars(select(Listing)).all()==[]


@pytest.mark.asyncio
async def test_feed_refresh_retains_review_until_location_changes(db):
    from flat_detector.service import approve_route
    s=make_source(db)
    state=sample()
    def reply(req): return httpx.Response(200,json=state)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        feed=ApprovedJSONFeed(URL,approved_origin="https://partner.example.test",client=client)
        assert await feed.collect(db,s,NOW)==1
        row=db.scalar(select(Listing))
        with pytest.raises(PermissionError):
            approve_route(db,row.id,station="Химки",minutes=12,provider="manual-test",note="проверил маршрут",role="viewer",now=NOW)
        approve_route(db,row.id,station="Химки",minutes=12,provider="manual-test",note="проверил маршрут",role="owner",now=NOW)
        assert await feed.collect(db,s,NOW+timedelta(hours=1))==1
        db.refresh(row)
        assert row.geo_approved and row.route_minutes==12
        assert len(shortlist(db,DailyProfile(),NOW+timedelta(hours=1))[0])==1
        state["items"][0]["address"]="TEST — новое расположение"
        assert await feed.collect(db,s,NOW+timedelta(hours=2))==1
        db.refresh(row)
        assert not row.geo_approved and row.route_minutes is None
        assert shortlist(db,DailyProfile(),NOW+timedelta(hours=2))==([],[])
