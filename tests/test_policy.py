from datetime import datetime, timedelta, timezone
import pytest
from flat_detector.models import Source, Listing, Evidence
from flat_detector.service import ingest, source_is_permitted, evaluate_status, shortlist, DailyProfile

NOW = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)

def source(db, *, permitted=True, demo=False):
    s = Source(key="partner_a", mode="APPROVED_FEED" if permitted else "UNKNOWN_PERMISSION", enabled=permitted,
               permission_scope="search,store,notify" if permitted else "",
               permission_proof="synthetic unit-test contract" if permitted else None, permission_checked_at=NOW,
               permission_expires_at=NOW + timedelta(days=30), demo_only=demo)
    db.add(s);db.commit();return s

def record(eid="A1",price=8_000_000):
    return dict(external_id=eid,original_url="https://example.org/listing/1",price_rub=price,
                area_sqm=34.2,rooms=1,address="Химки — демонстрационные данные",geo_approved=True,
                route_minutes=12,route_method="WALK_ROUTE",route_provider="test-fixture")

def test_unknown_source_cannot_ingest(db):
    s=source(db,permitted=False)
    assert not source_is_permitted(s,NOW)
    with pytest.raises(PermissionError):ingest(db,s,record(),NOW)
    assert db.query(Listing).count()==0

def test_permission_expiry_denies(db):
    s=source(db);s.permission_expires_at=NOW-timedelta(seconds=1);db.commit()
    with pytest.raises(PermissionError):ingest(db,s,record(),NOW)

def test_idempotent_ingest_and_price_history(db):
    from flat_detector.models import PriceHistory
    s=source(db)
    a=ingest(db,s,record(),NOW); b=ingest(db,s,record(),NOW)
    assert a.id==b.id and db.query(PriceHistory).count()==1
    ingest(db,s,record(price=7_900_000),NOW+timedelta(hours=1))
    assert db.query(PriceHistory).count()==2

def test_403_does_not_mark_removed(db):
    s=source(db); l=ingest(db,s,record(),NOW)
    db.add(Evidence(listing_id=l.id,signal="ACTIVE",observed_at=NOW,origin_key="partner_a",direct=True));db.commit()
    assert evaluate_status(db,l,NOW)=="ACTIVE_DIRECT"
    db.add(Evidence(listing_id=l.id,signal="SOURCE_BLOCKED",observed_at=NOW+timedelta(minutes=1),origin_key="partner_a",direct=True));db.commit()
    assert evaluate_status(db,l,NOW+timedelta(minutes=2))=="ACTIVE_DIRECT"

def test_negative_signal_wins_and_stale(db):
    s=source(db);l=ingest(db,s,record(),NOW)
    db.add(Evidence(listing_id=l.id,signal="ACTIVE",observed_at=NOW,origin_key="partner_a",direct=True));db.commit()
    assert evaluate_status(db,l,NOW+timedelta(hours=25))=="STALE"
    db.add(Evidence(listing_id=l.id,signal="RESERVED",observed_at=NOW+timedelta(hours=1),origin_key="partner_a",direct=True));db.commit()
    assert evaluate_status(db,l,NOW+timedelta(hours=2))=="RESERVED"

def test_independent_indirect_sources(db):
    s=source(db);l=ingest(db,s,record(),NOW)
    db.add_all([Evidence(listing_id=l.id,signal="ACTIVE",observed_at=NOW,origin_key="mirror1",direct=False,independence_group="owner_a"),
                Evidence(listing_id=l.id,signal="ACTIVE",observed_at=NOW,origin_key="mirror2",direct=False,independence_group="owner_a")]);db.commit()
    assert evaluate_status(db,l,NOW)=="UNVERIFIED"
    db.add(Evidence(listing_id=l.id,signal="ACTIVE",observed_at=NOW,origin_key="mirror3",direct=False,independence_group="owner_b"));db.commit()
    assert evaluate_status(db,l,NOW)=="ACTIVE_INDIRECT"

def test_shortlist_excludes_unknown_geography_and_premium_without_justification(db):
    s=source(db)
    for eid,price,approved,advantage in [("1",8_000_000,True,None),("2",8_600_000,True,None),("3",8_600_000,True,"larger approved area"),("4",9_200_000,True,None),("5",7_000_000,False,None)]:
        d=record(eid,price);d["geo_approved"]=approved;d["premium_reason"]=advantage
        l=ingest(db,s,d,NOW); db.add(Evidence(listing_id=l.id,signal="ACTIVE",observed_at=NOW,origin_key="partner_a",direct=True))
    db.commit()
    base,premium=shortlist(db,DailyProfile(max_price_rub=9_000_000),NOW)
    assert len(base)==1 and len(premium)==1 and premium[0].external_id=="3"


def test_missing_permission_proof_deny_and_disable_publication(db):
    s=source(db)
    s.permission_proof=None
    db.commit()
    assert not source_is_permitted(s,NOW)
    with pytest.raises(PermissionError):ingest(db,s,record(),NOW)
    s.permission_proof="project-owned synthetic test adapter (NOT a production license)"
    db.commit()
    l=ingest(db,s,record(),NOW)
    db.add(Evidence(listing_id=l.id,signal="ACTIVE",observed_at=NOW,origin_key="partner_a",direct=True))
    db.commit()
    assert len(shortlist(db,DailyProfile(),NOW)[0])==1
    s.enabled=False
    db.commit()
    assert shortlist(db,DailyProfile(),NOW)==([],[])
