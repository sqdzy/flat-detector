"""Single replica workers; external collection explicitly disabled in MVP."""
import argparse,asyncio,logging,time
from datetime import datetime,timezone,timedelta
from flat_detector.config import get_settings
from flat_detector.database import Session,migrate_dev
from flat_detector.delivery import schedule_due,deliver_once,reconcile_stale_claims
from flat_detector.bot import TelegramBotAPI

log=logging.getLogger(__name__)

async def scheduler():
    migrate_dev()
    while True:
        try:
            with Session() as db:
                count=schedule_due(db,datetime.now(timezone.utc),include_demo=get_settings().demo_mode)
                if count:log.info("digest jobs queued=%d",count)
        except Exception as exc:
            log.warning("schedule failure (%s)",type(exc).__name__)
        await asyncio.sleep(30)

async def sender():
    settings=get_settings()
    token=settings.telegram_token
    if not token and settings.telegram_token_file:
        from pathlib import Path
        token=Path(settings.telegram_token_file).read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("FD_TELEGRAM_TOKEN(_FILE) required for sender")
    migrate_dev()
    api=TelegramBotAPI(token)
    last_recovery = 0.0
    try:
        while True:
            now=datetime.now(timezone.utc)
            try:
                with Session() as db:
                    if time.monotonic() - last_recovery >= 60:
                        stale = reconcile_stale_claims(db, now, claim_timeout=timedelta(minutes=5))
                        if stale:log.warning("unverified stale deliveries marked UNCERTAIN count=%d", stale)
                        last_recovery = time.monotonic()
                    result=await deliver_once(db,api,now,allow_demo_delivery=(not settings.demo_mode or settings.demo_delivery))
            except Exception as exc:
                log.warning("sender failure (%s)",type(exc).__name__)
                result="ERROR"
            await asyncio.sleep(1.1 if result not in ("EMPTY","DEMO_DISABLED") else 5)
    finally:await api.client.aclose()

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    parser=argparse.ArgumentParser();parser.add_argument("role",choices=("scheduler","sender"))
    args=parser.parse_args()
    asyncio.run(scheduler() if args.role=="scheduler" else sender())
