"""Verify workers connect scheduling/recovery without hitting live Telegram."""
from contextlib import nullcontext
from types import SimpleNamespace
import pytest
from flat_detector import worker


class ExitWorker(Exception):
    pass


async def exit_sleep(_seconds):
    raise ExitWorker()


@pytest.mark.asyncio
async def test_scheduler_invokes_due_check_and_can_stop(monkeypatch):
    events=[]
    monkeypatch.setattr(worker,"migrate_dev",lambda: events.append("migration"))
    monkeypatch.setattr(worker,"Session",lambda: nullcontext(object()))
    monkeypatch.setattr(worker,"get_settings",lambda: SimpleNamespace(demo_mode=False))
    monkeypatch.setattr(worker,"schedule_due",lambda db,now,include_demo: events.append("schedule") or 2)
    monkeypatch.setattr(worker.asyncio,"sleep",exit_sleep)
    with pytest.raises(ExitWorker):
        await worker.scheduler()
    assert events == ["migration","schedule"]


@pytest.mark.asyncio
async def test_sender_reconciles_stale_claims_before_attempting_any_send(monkeypatch):
    events=[]
    monkeypatch.setattr(worker,"migrate_dev",lambda: events.append("migration"))
    monkeypatch.setattr(worker,"Session",lambda: nullcontext(object()))
    monkeypatch.setattr(worker,"get_settings",lambda: SimpleNamespace(telegram_token="fixture",
                         telegram_token_file="",demo_mode=False,demo_delivery=False))
    class MockTelegram:
        def __init__(self,token):
            assert token=="fixture"
            self.client=self
        async def aclose(self): events.append("close")
    monkeypatch.setattr(worker,"TelegramBotAPI",MockTelegram)
    monkeypatch.setattr(worker,"reconcile_stale_claims",lambda db,now,claim_timeout: events.append("reconcile") or 0)
    async def fake_deliver(db,api,now,allow_demo_delivery):
        assert allow_demo_delivery
        events.append("deliver")
        return "EMPTY"
    monkeypatch.setattr(worker,"deliver_once",fake_deliver)
    monkeypatch.setattr(worker.asyncio,"sleep",exit_sleep)
    with pytest.raises(ExitWorker):
        await worker.sender()
    assert events==["migration","reconcile","deliver","close"]
