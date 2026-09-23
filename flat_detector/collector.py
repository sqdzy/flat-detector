"""Generic *approved JSON feed*, not a CIAN/Avito/Domclick scraper.

Only the operator can instantiate this adapter with a fixed provider URL after obtaining
specific documented search/storage/notification rights. MCP NEVER calls this module.
The underlying container needs egress firewall/DNS policy before enabling live calls.
"""
from __future__ import annotations
import json
from datetime import datetime
from urllib.parse import urlsplit
from typing import Literal
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError
from sqlalchemy.orm import Session
from flat_detector.models import Source, Evidence
from flat_detector.service import source_is_permitted, ingest, safe_original_url, store_source_error

MAX_BYTES=1_048_576
MAX_ITEMS=50


class FeedDenied(RuntimeError):
    """Request denied by provider, or a transient/network failure. Not removal evidence."""


class FeedRejected(ValueError):
    """Invalid provider payload; nothing from that batch is ingested."""


class FeedRecord(BaseModel):
    model_config=ConfigDict(extra="ignore")
    external_id: StrictStr = Field(min_length=1,max_length=120)
    original_url: StrictStr = Field(min_length=14,max_length=600)
    price_rub: StrictInt = Field(ge=1,le=1_000_000_000)
    area_sqm: float = Field(gt=0,le=1000,allow_inf_nan=False)
    rooms: StrictInt = Field(ge=1,le=20)
    address: StrictStr = Field(min_length=3,max_length=250)
    availability: Literal["ACTIVE","RESERVED","REMOVED","SOLD","UNKNOWN"]="UNKNOWN"


class FeedDocument(BaseModel):
    model_config=ConfigDict(extra="ignore")
    items:list[FeedRecord] = Field(max_length=MAX_ITEMS)


class ApprovedJSONFeed:
    """Fixed URL and exact provider origin; no arbitrary URL fetching or redirects.

    Source approval is checked again on EVERY invocation. This component is not exposed
    via MCP. The operator must apply an egress firewall that blocks private/link-local IPs;
    DNS preflight alone cannot eliminate DNS-rebinding TOCTOU.
    """
    def __init__(self,url:str,*,approved_origin:str,client:httpx.AsyncClient,
                 allowed_listing_hosts:frozenset[str]|None=None):
        # exact origin match ensures subdomain suffix confusion doesn't grant access.
        parsed=urlsplit(url)
        origin=urlsplit(approved_origin)
        safe_original_url(url)
        safe_original_url(approved_origin.rstrip("/")+"/")
        if (parsed.scheme,parsed.hostname,parsed.port)!=(origin.scheme,origin.hostname,origin.port):
            raise ValueError("Feed URL origin is not approved")
        if origin.path not in ("", "/") or origin.query or origin.fragment or parsed.fragment:
            raise ValueError("Origin must be bare HTTPS origin; feed fragment forbidden")
        if not parsed.path.startswith("/api/") or parsed.query:
            raise ValueError("Only operator-approved, query-free /api/ paths accepted")
        self.url=url
        self.host=parsed.hostname
        self.allowed_listing_hosts=allowed_listing_hosts or frozenset({self.host})
        self.client=client

    async def collect(self,db:Session,source:Source,now:datetime)->int:
        if source.demo_only or source.mode!="APPROVED_FEED" or not source_is_permitted(source,now):
            raise PermissionError("Approved feed source is disabled, expired or missing proof")
        try:
            async with self.client.stream("GET",self.url,follow_redirects=False,timeout=10) as response:
                code=response.status_code
                if code!=200:
                    store_source_error(db,source,code,now)
                    raise FeedDenied("Provider denied request or redirected; no retry or removal")
                if response.headers.get("content-type","").split(";",1)[0].strip().lower()!="application/json":
                    store_source_error(db,source,502,now)
                    raise FeedRejected("Not a JSON feed")
                if int(response.headers.get("content-length","0"))>MAX_BYTES:
                    store_source_error(db,source,502,now)
                    raise FeedRejected("Feed too large")
                chunks=[];used=0
                async for chunk in response.aiter_bytes():
                    used+=len(chunk)
                    if used>MAX_BYTES:
                        store_source_error(db,source,502,now)
                        raise FeedRejected("Feed too large")
                    chunks.append(chunk)
        except httpx.RequestError:
            store_source_error(db,source,502,now)
            raise FeedDenied("Provider transport unavailable; no automatic retry") from None
        try:
            payload=FeedDocument.model_validate(json.loads(b"".join(chunks)))
            validated=[]
            for item in payload.items:
                parsed=urlsplit(safe_original_url(item.original_url))
                if parsed.hostname not in self.allowed_listing_hosts:
                    raise ValueError("Listing URL origin outside approved provider hosts")
                # Provider must not confer arbitrary geographical approval or route estimates.
                validated.append(item.model_dump(exclude={"availability"}))
        except (ValidationError,ValueError,UnicodeDecodeError,TypeError):
            store_source_error(db,source,502,now)
            raise FeedRejected("Invalid provider payload; no batch data written") from None
        try:
            for item,raw in zip(payload.items,validated,strict=True):
                listing=ingest(db,source,raw,now,commit=False)
                if item.availability!="UNKNOWN":
                    db.add(Evidence(listing_id=listing.id,signal=item.availability,
                                    observed_at=now,origin_key=source.key,direct=True,
                                    note="Approved JSON feed observation"))
            source.last_error_code=None
            source.last_success_at=now
            db.commit()
        except Exception:
            db.rollback()
            raise
        return len(payload.items)
