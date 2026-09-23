"""Service layer for MCP; cannot fetch URLs or send Telegram messages."""
from __future__ import annotations
import uuid
from datetime import datetime,timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from flat_detector.models import Listing, Source, Evidence, RecheckJob, aware
from flat_detector.service import DailyProfile, shortlist, evaluate_status, source_is_permitted
from flat_detector.delivery import render_digest


def _public_listing(db:Session,l:Listing,now:datetime)->dict:
    return {"id":l.id,"url":l.original_url,"source":l.source.key,"price_rub":l.price_rub,
            "area_sqm":l.area_sqm,"address":l.address,"route_minutes":l.route_minutes,
            "route_method":l.route_method,"route_provider":l.route_provider,
            "status":evaluate_status(db,l,now),"observed_at":aware(l.observed_at).isoformat(),
            "premium_reason":l.premium_reason,"demo":l.source.demo_only}


def list_active_listings(db:Session,*,max_price_rub:int=9_000_000,availability:str|None=None,page_size:int=10,cursor:str|None=None,now:datetime|None=None,include_demo:bool=False)->dict:
    if not 1<=page_size<=20 or not 1<=max_price_rub<=9_000_000:raise ValueError("Out of bounds")
    if availability not in (None,"ACTIVE_DIRECT","ACTIVE_INDIRECT"):raise ValueError("Invalid availability")
    now=now or datetime.now(timezone.utc)
    base,premium=shortlist(db,DailyProfile(max_price_rub),now,include_demo=include_demo)
    records=[_public_listing(db,l,now) for l in base+premium]
    records=[l for l in records if availability is None or l["status"]==availability]
    records.sort(key=lambda d:(d["price_rub"],d["id"]))
    # Cursor is an opaque encoded integer index, not SQL/URL input.
    if cursor is None:start=0
    else:
        try:start=int(cursor)
        except ValueError:raise ValueError("Invalid cursor")
        if start<0:raise ValueError("Invalid cursor")
    return {"items":records[start:start+page_size],"next_cursor":str(start+page_size) if len(records)>start+page_size else None}


def get_listing_evidence(db:Session,listing_id:str,*,now:datetime|None=None)->dict:
    try:uid=str(uuid.UUID(listing_id))
    except ValueError:raise ValueError("Invalid listing id")
    l=db.get(Listing,uid)
    if not l:raise LookupError("Listing not found")
    now=now or datetime.now(timezone.utc)
    facts=_public_listing(db,l,now)
    facts["evidence"]=[{"signal":e.signal,"time":aware(e.observed_at).isoformat(),"origin":e.origin_key,"direct":e.direct,"independence_group":e.independence_group} for e in l.evidence]
    facts["provenance"]=l.provenance
    return facts


def get_source_health(db:Session,source_id:str|None=None)->list[dict]:
    rows=db.scalars(select(Source).where(Source.key==source_id) if source_id else select(Source)).all()
    return [{"key":s.key,"mode":s.mode,"enabled":s.enabled,"last_error_code":s.last_error_code,
             "last_success_at":aware(s.last_success_at).isoformat() if s.last_success_at else None,
             "permission_valid":source_is_permitted(s,datetime.now(timezone.utc),demo_run=s.demo_only),"demo":s.demo_only} for s in rows]


def preview_daily_digest(db:Session,local_day:str,*,max_price_rub:int=8500000,now:datetime|None=None,include_demo:bool=False)->dict:
    from datetime import date
    date.fromisoformat(local_day)
    return {"local_day":local_day,"text":render_digest(db,DailyProfile(max_price_rub),now or datetime.now(timezone.utc),local_day=local_day,include_demo=include_demo)}


def request_listing_recheck(db:Session,listing_id:str,confirmed:bool,reason:str,idempotency_key:str,role:str,now:datetime)->dict:
    if role!="owner":raise PermissionError("Owner role required")
    if not confirmed:raise PermissionError("Explicit confirmation required")
    if len(reason)<3 or len(reason)>200:raise ValueError("Invalid reason")
    try:lid=str(uuid.UUID(listing_id));key=str(uuid.UUID(idempotency_key))
    except ValueError:raise ValueError("Invalid UUID")
    old=db.scalar(select(RecheckJob).where(RecheckJob.idempotency_key==key))
    if old:
        if old.listing_id!=lid:raise ValueError("Idempotency key belongs to another listing")
        return {"job_id":old.id,"state":old.state}
    l=db.get(Listing,lid)
    if not l:raise LookupError("Unknown listing")
    if not source_is_permitted(l.source,now):raise PermissionError("Source is not eligible for automatic recheck")
    # Job execution remains disabled until a real approved source adapter is installed.
    job=RecheckJob(listing_id=lid,idempotency_key=key,reason=reason,state="WAITING_FOR_APPROVED_ADAPTER",created_at=now)
    db.add(job);db.commit()
    return {"job_id":job.id,"state":job.state}
