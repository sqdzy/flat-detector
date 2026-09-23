"""Crash-safe semantics: an abandoned CLAIMED send is ambiguous, never silently retried."""
from datetime import datetime,timedelta,timezone
from flat_detector.models import Subscriber,Outbox
from flat_detector.delivery import reconcile_stale_claims

NOW=datetime(2026,9,23,13,0,tzinfo=timezone.utc)

def test_stale_claim_becomes_uncertain_but_recent_claim_is_left_alone(db):
    sub=Subscriber(chat_id=555,active=True,consent_at=NOW)
    db.add(sub);db.commit()
    old=Outbox(subscriber_id=sub.id,local_day="2026-09-22",text="old",status="CLAIMED",
               attempts=1,next_attempt_at=NOW-timedelta(days=1),claimed_at=NOW-timedelta(minutes=7))
    current=Outbox(subscriber_id=sub.id,local_day="2026-09-23",text="current",status="CLAIMED",
                   attempts=1,next_attempt_at=NOW,claimed_at=NOW-timedelta(minutes=1))
    db.add_all([old,current]);db.commit()
    assert reconcile_stale_claims(db,NOW,claim_timeout=timedelta(minutes=5))==1
    db.refresh(old);db.refresh(current)
    assert old.status=="UNCERTAIN" and old.last_error_code=="STALE_CLAIM_UNVERIFIED"
    assert current.status=="CLAIMED"
    assert reconcile_stale_claims(db,NOW+timedelta(minutes=1),claim_timeout=timedelta(minutes=5))==0
