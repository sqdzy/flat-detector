"""Safety properties for one-shot operator-initiated Telegram test."""
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from flat_detector.models import Subscriber
from flat_detector.pilot import DEMO_TEXT, PilotGuardError, sole_consenting_subscriber, send_one

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def test_deny_with_zero_subscribers(db):
    with pytest.raises(PilotGuardError):
        sole_consenting_subscriber(db)


def test_deny_with_multiple_or_unconfirmed_subscribers(db):
    db.add(Subscriber(chat_id=111, active=True, consent_at=NOW))
    db.add(Subscriber(chat_id=222, active=True, consent_at=NOW))
    db.commit()
    with pytest.raises(PilotGuardError):
        sole_consenting_subscriber(db)
    for s in db.query(Subscriber).all():
        s.active = False
    db.commit()
    with pytest.raises(PilotGuardError):
        sole_consenting_subscriber(db)


def test_only_one_active_confirmed(db):
    db.add(Subscriber(chat_id=111, active=True, consent_at=NOW))
    db.add(Subscriber(chat_id=222, active=True, consent_at=None))
    db.commit()
    assert sole_consenting_subscriber(db).chat_id == 111


@pytest.mark.asyncio
async def test_exactly_one_message_and_closes_client():
    sent = []
    closed = []

    class FakeClient:
        async def aclose(self):
            closed.append(True)

    class FakeBot:
        def __init__(self, token):
            assert token == "fake-test-token"
            self.client = FakeClient()

        async def send(self, chat_id, body):
            sent.append((chat_id, body))
            return SimpleNamespace(message_id=10)

    await send_one(111, "fake-test-token", bot_factory=FakeBot)
    assert len(sent) == 1
    assert sent[0][0] == 111
    assert "ВЫМЫШЛЕННЫЕ" in sent[0][1]
    assert closed == [True]


def test_demo_text_contains_no_real_listing_links():
    assert "НЕ реальные объявления" in DEMO_TEXT
    assert "http://" not in DEMO_TEXT and "https://" not in DEMO_TEXT