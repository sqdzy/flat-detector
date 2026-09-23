"""Timezone-aware daily scheduling and durable single-worker Telegram outbox."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session
from flat_detector.models import Subscriber, Outbox, Listing, aware
from flat_detector.service import DailyProfile, shortlist, evaluate_status

@dataclass(frozen=True)
class TelegramResult:
    message_id:int

class TelegramError(Exception):
    def __init__(self,code:int,retry_after:int|None=None):
        super().__init__(str(code));self.code=code;self.retry_after=retry_after


def render_digest(db:Session,profile:DailyProfile,now:datetime,*,local_day:str,include_demo:bool=False)->str|None:
    base,premium=shortlist(db,profile,now,include_demo=include_demo)
    if not(base or premium):return None
    sections=[f"Квартиры рядом с Москвой — {local_day}"]
    for title,arr in [("До 8,5 млн ₽",base),("8,5–9 млн ₽ — только с преимуществом",premium)]:
        if not arr:continue
        sections.append("\n"+title)
        for l in arr[:6]:
            status=evaluate_status(db,l,now)
            mark="напрямую" if status=="ACTIVE_DIRECT" else "косвенно (проверь у продавца)"
            prefix="[СИНТЕТИЧЕСКИЕ ДАННЫЕ] " if l.source.demo_only else ""
            line=f"{prefix}{l.price_rub:,} ₽ · {l.area_sqm:g} м² · {l.address}\nМЦД: {l.route_minutes} мин пешком ({l.route_provider}) · актуальность: {mark}, {aware(l.observed_at).strftime('%d.%m %H:%M UTC')}\n{l.original_url}"
            if l.premium_reason:line+="\nПреимущество: "+l.premium_reason
            sections.append(line)
    sections.append("\nДанные не подтверждают чистоту сделки. Уточняй наличие и документы у продавца.")
    return "\n\n".join(sections)[:4050]


def schedule_due(db:Session,now:datetime,*,include_demo:bool=False)->int:
    """Single scheduler instance MVP; unique DB key tolerates repeated runs."""
    queued=0
    for sub in db.scalars(select(Subscriber).where(Subscriber.active==True,Subscriber.consent_at.is_not(None))).all():
        local=now.astimezone(ZoneInfo(sub.timezone))
        if local.hour!=sub.digest_hour:continue
        day=local.date().isoformat()
        existing=db.scalar(select(Outbox.id).where(Outbox.subscriber_id==sub.id,Outbox.local_day==day))
        if existing:continue
        text=render_digest(db,DailyProfile(sub.max_price_rub),now,local_day=day,include_demo=include_demo)
        if not text:continue
        db.add(Outbox(subscriber_id=sub.id,local_day=day,text=text,status="PENDING",next_attempt_at=now))
        db.commit();queued+=1
    return queued


async def deliver_once(db:Session,telegram,now:datetime,*,allow_demo_delivery:bool=True)->str:
    """At-most-one worker. CLAIMED persisted BEFORE network call; ambiguity -> UNCERTAIN."""
    item=db.scalar(select(Outbox).where(Outbox.status=="PENDING",Outbox.next_attempt_at<=now)
                   .order_by(Outbox.next_attempt_at,Outbox.id).with_for_update(skip_locked=True))
    if item is None:return "EMPTY"
    user=db.get(Subscriber,item.subscriber_id)
    if user is None or not user.active or user.consent_at is None:
        item.status="CANCELLED";db.commit();return "SKIPPED"
    if not allow_demo_delivery:
        # Explicitly no external delivery of synthetic data unless operator opted in.
        return "DEMO_DISABLED"
    item.status="CLAIMED";item.claimed_at=now;item.attempts+=1;db.commit()
    # PostgreSQL row lock serializes /stop and send. /stop can only return
    # after an already-in-flight send completed; after that, it disables future sends.
    db.expire_all()
    user=db.scalar(select(Subscriber).where(Subscriber.id==item.subscriber_id).with_for_update().execution_options(populate_existing=True))
    if user is None or not user.active:
        item=db.get(Outbox,item.id)
        item.status="CANCELLED";db.commit();return "SKIPPED"
    try:
        result=await telegram.send(user.chat_id,item.text)
    except TelegramError as exc:
        if exc.code==403:
            user.active=False;item.status="BLOCKED";item.last_error_code="TELEGRAM_BLOCKED"
        elif exc.code==429:
            item.status="PENDING";item.next_attempt_at=now+timedelta(seconds=max(1,min(exc.retry_after or 60,3600)))
            item.last_error_code="RATE_LIMITED"
        elif exc.code in (400,401):
            item.status="BLOCKED";item.last_error_code="TELEGRAM_REJECTED"
        else:
            item.status="UNCERTAIN";item.last_error_code="TELEGRAM_UNKNOWN_ERROR"
        db.commit()
        return "RETRY" if item.status=="PENDING" else item.status
    except Exception:
        # Any network timeout/crash leaves a claim; never automatically resend unknown state.
        item.status="UNCERTAIN";item.last_error_code="DELIVERY_RESULT_UNKNOWN";db.commit()
        return "UNCERTAIN"
    item.status="SENT";item.telegram_message_id=result.message_id;item.last_error_code=None
    db.commit();return "SENT"


def reconcile_stale_claims(db: Session, now: datetime, *, claim_timeout: timedelta = timedelta(minutes=5)) -> int:
    """A crashed worker may leave CLAIMED records; fail closed, not resend.

    Run in the singleton sender before polling and periodically. Any unknown
    Telegram result is manually reviewed, never requeued automatically.
    """
    if claim_timeout.total_seconds() < 60:
        raise ValueError("Claim timeout must be at least a minute")
    stale = db.scalars(
        select(Outbox)
        .where(Outbox.status == "CLAIMED", Outbox.claimed_at <= now - claim_timeout)
        .with_for_update(skip_locked=True)
    ).all()
    for item in stale:
        item.status = "UNCERTAIN"
        item.last_error_code = "STALE_CLAIM_UNVERIFIED"
    if stale:
        db.commit()
    return len(stale)
