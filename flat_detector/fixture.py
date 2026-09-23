"""Explicit synthetic demo importer. Never claims real listing availability."""
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from flat_detector.models import Source,Evidence
from flat_detector.service import ingest
from flat_detector.database import Session, migrate_dev
from flat_detector.config import get_settings

SYNTHETIC=[
    {"external_id":"SYNTH-001","original_url":"https://example.org/demo/001","price_rub":7990000,"area_sqm":33.4,"rooms":1,
     "address":"СИНТЕТИЧЕСКИЙ ОБЪЕКТ №1 — Химки","geo_approved":True,"route_minutes":12,
     "route_method":"WALK_ROUTE","route_provider":"synthetic-test-only"},
    {"external_id":"SYNTH-002","original_url":"https://example.org/demo/002","price_rub":8750000,"area_sqm":42.1,"rooms":1,
     "address":"СИНТЕТИЧЕСКИЙ ОБЪЕКТ №2 — Левобережная","geo_approved":True,"route_minutes":10,
     "route_method":"WALK_ROUTE","route_provider":"synthetic-test-only","premium_reason":"Больше площадь (только тест)"},
    {"external_id":"SYNTH-003","original_url":"https://example.org/demo/003","price_rub":7200000,"area_sqm":31,"rooms":1,
     "address":"СИНТЕТИЧЕСКИЙ ОБЪЕКТ №3 — снят","geo_approved":True,"route_minutes":11,
     "route_method":"WALK_ROUTE","route_provider":"synthetic-test-only"},
]


def seed(now:datetime|None=None)->int:
    if not get_settings().demo_mode:
        raise PermissionError("FD_DEMO_MODE=true required. No live source access is granted.")
    migrate_dev()
    now=now or datetime.now(timezone.utc)
    with Session() as db:
        s=db.scalar(select(Source).where(Source.key=="synthetic_fixtures"))
        if s is None:s=Source(key="synthetic_fixtures",demo_only=True,mode="APPROVED_FEED");db.add(s);db.flush()
        s.enabled=True;s.permission_scope="search,store,notify"
        s.permission_proof="Project-owned synthetic fixtures; no real-world permissions implied"
        s.permission_checked_at=now;s.permission_expires_at=now+timedelta(days=2)
        db.commit()
        for i,data in enumerate(SYNTHETIC):
            l=ingest(db,s,data,now,demo_run=True)
            if not db.scalar(select(Evidence.id).where(Evidence.listing_id==l.id)):
                db.add(Evidence(listing_id=l.id,signal="REMOVED" if i==2 else "ACTIVE",observed_at=now,
                                origin_key="synthetic_fixtures",direct=True,note="SYNTHETIC DATA"));db.commit()
        return len(SYNTHETIC)

if __name__=="__main__":
    print(f"Seeded {seed()} synthetic records")
