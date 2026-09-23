"""Validated fixture/licensed-feed ingestion and deterministic evidence-based filtering."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from ipaddress import ip_address
from sqlalchemy import select
from sqlalchemy.orm import Session
from flat_detector.models import Source, Listing, Evidence, PriceHistory, aware

ALLOWED_MODES = {"LICENSED_API", "APPROVED_FEED", "PERMITTED_HTML"}
REQUIRED_SCOPES = {"search", "store", "notify"}
NEGATIVE = {"RESERVED", "REMOVED", "SOLD"}
TRANSIENT = {"SOURCE_BLOCKED", "RATE_LIMITED", "SOURCE_ERROR"}

@dataclass(frozen=True)
class DailyProfile:
    max_price_rub: int = 8_500_000


def source_is_permitted(source: Source, now: datetime, *, demo_run: bool = False) -> bool:
    if not source.enabled or source.mode not in ALLOWED_MODES:
        return False
    if source.demo_only and not demo_run:
        return False
    if not (source.permission_proof and source.permission_proof.strip() and source.permission_checked_at and source.permission_expires_at):
        return False
    if not aware(source.permission_checked_at) <= now < aware(source.permission_expires_at):
        return False
    return REQUIRED_SCOPES.issubset({x.strip() for x in source.permission_scope.split(",")})


def safe_original_url(raw: str) -> str:
    """Safe to display as a link, *never* permission to fetch it."""
    p=urlsplit(raw)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None,443) or len(raw)>600:
        raise ValueError("Only simple HTTPS source links are accepted")
    host=p.hostname.lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Private source URL")
    try:
        ip_address(host)
    except ValueError:
        return raw
    raise ValueError("Literal-IP links are not accepted")


def ingest(db: Session, source: Source, data: dict, now: datetime, *, demo_run: bool=False, commit:bool=True) -> Listing:
    if not source_is_permitted(source, now, demo_run=demo_run):
        raise PermissionError("Source not permitted; import fail closed")
    price=int(data["price_rub"]); area=float(data["area_sqm"]); rooms=int(data["rooms"])
    if price <= 0 or area <= 0 or not (0 < rooms < 30):
        raise ValueError("Invalid listing dimensions")
    external_id=str(data["external_id"])
    if not external_id or len(external_id)>120:
        raise ValueError("Invalid source external ID")
    url=safe_original_url(str(data["original_url"]))
    l=db.scalar(select(Listing).where(Listing.source_id==source.id,Listing.external_id==external_id))
    if l is None:
        l=Listing(source_id=source.id,external_id=external_id,original_url=url,price_rub=price,
                  area_sqm=area,rooms=rooms,address=str(data["address"])[:250],observed_at=now)
        db.add(l);db.flush()
    if l.price_rub != price or db.scalar(select(PriceHistory.id).where(PriceHistory.listing_id==l.id)) is None:
        db.add(PriceHistory(listing_id=l.id,price_rub=price,observed_at=now))
    # Refreshing a feed must not silently overwrite a previously reviewed route.
    # An address change invalidates earlier manual geographical approval.
    address=str(data["address"])[:250]
    moved = bool(l.address != address)
    l.price_rub=price;l.area_sqm=area;l.rooms=rooms;l.original_url=url
    l.address=address;l.observed_at=now
    if moved:
        l.geo_approved=False;l.route_minutes=None;l.route_method=None;l.route_provider=None
    if "geo_approved" in data:l.geo_approved=bool(data["geo_approved"])
    if "route_minutes" in data:l.route_minutes=data["route_minutes"]
    if "route_method" in data:l.route_method=data["route_method"]
    if "route_provider" in data:l.route_provider=data["route_provider"]
    if "premium_reason" in data:l.premium_reason=data["premium_reason"]
    prior=dict(l.provenance or {})
    if moved:prior.pop("geo_review",None)
    l.provenance={**prior,"source":source.key,"observed_at":now.isoformat(),"demo":source.demo_only}
    if commit:db.commit()
    else:db.flush()
    return l


def evaluate_status(db:Session, listing:Listing, now:datetime, freshness_hours:int=24) -> str:
    events=db.scalars(select(Evidence).where(Evidence.listing_id==listing.id)).all()
    if not events:
        return "UNVERIFIED"
    events=sorted(events,key=lambda e:aware(e.observed_at),reverse=True)
    decisive=[e for e in events if e.signal in NEGATIVE | {"ACTIVE"}]
    if not decisive:
        return "UNVERIFIED"
    # A fresh negative signal dominates older positives. A fresh later explicit positive can reactivate.
    recent=[e for e in decisive if now-timedelta(hours=freshness_hours) <= aware(e.observed_at) <= now]
    if not recent:
        return "STALE"
    most_recent=recent[0]
    if most_recent.signal in NEGATIVE:
        return most_recent.signal
    # If two contradictory observations share the exact time, never assert ACTIVE.
    if any(e.signal in NEGATIVE and aware(e.observed_at) == aware(most_recent.observed_at) for e in recent):
        return "UNVERIFIED"
    later_negative=next((e for e in recent if e.signal in NEGATIVE),None)
    positives=[e for e in recent if e.signal=="ACTIVE" and (later_negative is None or aware(e.observed_at)>aware(later_negative.observed_at))]
    if any(e.direct for e in positives):
        return "ACTIVE_DIRECT"
    groups={e.independence_group for e in positives if e.independence_group}
    return "ACTIVE_INDIRECT" if len(groups)>=2 else "UNVERIFIED"


def shortlist(db:Session, profile:DailyProfile, now:datetime,*,include_demo:bool=False) -> tuple[list[Listing],list[Listing]]:
    if not 1<=profile.max_price_rub<=9_000_000:
        raise ValueError("Invalid price limit")
    base=[];premium=[]
    for l in db.scalars(select(Listing).where(Listing.rooms==1,Listing.price_rub<=profile.max_price_rub).order_by(Listing.price_rub)).all():
        if not source_is_permitted(l.source,now,demo_run=include_demo):continue
        if l.source.demo_only and not include_demo:continue
        if not l.geo_approved:continue
        if l.route_method!="WALK_ROUTE" or l.route_minutes is None or not 0<l.route_minutes<=15:continue
        if evaluate_status(db,l,now) not in {"ACTIVE_DIRECT","ACTIVE_INDIRECT"}:continue
        if l.price_rub<=8_500_000:base.append(l)
        elif l.premium_reason: premium.append(l)
    return base,premium


def store_source_error(db:Session,source:Source,status:int,now:datetime):
    # Not a listing event: a 403/429 cannot make every listing look removed.
    source.last_error_code = {403:"SOURCE_BLOCKED",429:"RATE_LIMITED"}.get(status,"SOURCE_ERROR")
    db.commit()


def approve_route(db:Session,listing_id:str,*,station:str,minutes:int,provider:str,note:str,role:str,now:datetime)->None:
    """Manual operator review; not accessible via Telegram or the read-only MCP."""
    if role!="owner":raise PermissionError("Owner-only route review")
    if station not in {"Химки","Левобережная"}:raise ValueError("Outside approved near-Moscow stations")
    if not isinstance(minutes,int) or not 0<minutes<=15:raise ValueError("Route must be a verified walk of 1..15 minutes")
    if not 3<=len(provider)<=80 or not 8<=len(note)<=250:raise ValueError("Manual route review needs provider and evidence note")
    listing=db.get(Listing,listing_id)
    if listing is None:raise LookupError("Listing not found")
    if not source_is_permitted(listing.source,now):raise PermissionError("Unapproved source")
    listing.geo_approved=True
    listing.route_minutes=minutes
    listing.route_method="WALK_ROUTE"
    listing.route_provider=provider
    listing.provenance={**(listing.provenance or {}),"geo_review":{"station":station,"verified_at":now.isoformat(),"provider":provider,"note":note}}
    db.commit()
