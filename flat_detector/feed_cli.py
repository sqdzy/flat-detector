"""Operator-controlled polling of exactly one licensed JSON feed.

Intentionally absent from the default Compose profile. No scraping of major housing sites.
A denied/redirected/rate-limited feed STOPS this worker for human investigation.
"""
from __future__ import annotations
import asyncio
import logging
import os
from pathlib import Path
from datetime import datetime,timezone
import httpx
from sqlalchemy import select
from flat_detector.database import Session
from flat_detector.models import Source
from flat_detector.collector import ApprovedJSONFeed,FeedDenied,FeedRejected

log=logging.getLogger(__name__)


def checked_config(env:dict[str,str])->tuple[str,str,str,int,str|None]:
    key=env.get("FD_FEED_SOURCE_KEY","")
    url=env.get("FD_FEED_URL","")
    origin=env.get("FD_FEED_ORIGIN","")
    interval=int(env.get("FD_FEED_POLL_SECONDS","86400"))
    if not key or not url or not origin:
        raise ValueError("Approved feed requires source key, fixed feed URL and approved origin")
    if not 3600<=interval<=604800:
        raise ValueError("Approved feed interval must be between 1 hour and 7 days")
    token_file=env.get("FD_FEED_TOKEN_FILE") or None
    if token_file and not Path(token_file).is_file():
        raise ValueError("Configured bearer token file does not exist")
    return key,url,origin,interval,token_file


async def main()->None:
    key,url,origin,interval,token_file=checked_config(os.environ)
    headers={"User-Agent":"flat-detector/0.1 approved-feed-client"}
    if token_file:
        # No credential in URL, command line, logs or MCP responses.
        token=Path(token_file).read_text(encoding="utf-8").strip()
        if not token:raise RuntimeError("Empty feed bearer token file")
        headers["Authorization"]=f"Bearer {token}"
    async with httpx.AsyncClient(trust_env=False,follow_redirects=False,headers=headers) as client:
        feed=ApprovedJSONFeed(url,approved_origin=origin,client=client)
        while True:
            now=datetime.now(timezone.utc)
            try:
                with Session() as db:
                    source=db.scalar(select(Source).where(Source.key==key))
                    if source is None:
                        raise PermissionError("No verified source registration; refusing network request")
                    count=await feed.collect(db,source,now)
                    log.info("Approved feed scan committed: count=%d source=%s",count,key)
            except (FeedDenied,FeedRejected,PermissionError) as exc:
                log.error("Approved feed stopped for owner review: source=%s reason=%s",key,type(exc).__name__)
                raise SystemExit(2) from None
            await asyncio.sleep(interval)

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
