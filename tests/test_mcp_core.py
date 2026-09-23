import uuid
from datetime import datetime,timedelta,timezone
import pytest
from flat_detector.models import Source, Evidence, RecheckJob
from flat_detector.service import ingest
from flat_detector.mcp_tools import list_active_listings, request_listing_recheck, get_source_health

NOW=datetime(2026,9,23,9,0,tzinfo=timezone.utc)

def test_mcp_readonly_no_pii(db):
    s=Source(key="fixture",enabled=True,mode="APPROVED_FEED",permission_scope="search,store,notify",permission_proof="synthetic unit-test contract",permission_checked_at=NOW,permission_expires_at=NOW+timedelta(days=1))
    db.add(s);db.commit()
    l=ingest(db,s,dict(external_id="1",original_url="https://example.org/a",price_rub=8_000_000,area_sqm=32,
                       rooms=1,address="test",geo_approved=True,route_minutes=10,route_method="WALK_ROUTE",route_provider="fixture"),NOW)
    db.add(Evidence(listing_id=l.id,signal="ACTIVE",observed_at=NOW,origin_key="fixture",direct=True));db.commit()
    data=list_active_listings(db, max_price_rub=8_500_000, now=NOW)
    assert len(data['items'])==1 and "chat_id" not in str(data)
    assert get_source_health(db)[0]['key']=="fixture"

def test_recheck_gate(db):
    s=Source(key="fixture",enabled=False,mode="UNKNOWN_PERMISSION")
    db.add(s);db.commit()
    l=ingest.__name__ # disabled sources never ingest; insert existing via ORM for test
    from flat_detector.models import Listing
    item=Listing(source_id=s.id,external_id="x",original_url="https://example.org/x",price_rub=8000000,
                 area_sqm=30,rooms=1,address="test",geo_approved=True)
    db.add(item);db.commit()
    key=str(uuid.uuid4())
    with pytest.raises(PermissionError):request_listing_recheck(db,str(item.id),True,"check status",key,"owner",NOW)
    assert db.query(RecheckJob).count()==0
