"""An entire bot subscription -> scheduler -> outbox -> mock delivery, with zero network."""
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from flat_detector.models import Base,Subscriber,Outbox
from flat_detector.bot import apply_command
from flat_detector.delivery import schedule_due,deliver_once,TelegramResult

NOW=datetime(2026,9,23,9,0,tzinfo=timezone.utc) # Berlin 11:00

@pytest.mark.asyncio
async def test_synthetic_e2e_optin_and_no_accidental_demo_message(monkeypatch):
    from flat_detector import fixture
    engine=create_engine('sqlite+pysqlite:///:memory:',poolclass=StaticPool,connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(fixture,"Session",factory)
    monkeypatch.setattr(fixture,"migrate_dev",lambda:None)
    monkeypatch.setattr(fixture,"get_settings",lambda:SimpleNamespace(demo_mode=True))
    assert fixture.seed(NOW)==3
    class Sink:
        sent=[]
        async def send(self,chat,text):
            self.sent.append((chat,text))
            return TelegramResult(message_id=101)
    sink=Sink()
    with factory() as db:
        apply_command(db,444,"/start",NOW)
        assert schedule_due(db,NOW,include_demo=True)==0
        apply_command(db,444,"/subscribe",NOW)
        assert schedule_due(db,NOW,include_demo=True)==0
        apply_command(db,444,"/confirm",NOW)
        # Default user budget 8.5m limits premium 8.75m fixture, and removed is excluded.
        assert schedule_due(db,NOW,include_demo=True)==1
        assert await deliver_once(db,sink,NOW,allow_demo_delivery=False)=="DEMO_DISABLED"
        assert not sink.sent
        assert db.scalar(select(Outbox)).status=="PENDING"
        # Explicit operator opt-in for a mock send only; *no external Bot API* in test.
        assert await deliver_once(db,sink,NOW,allow_demo_delivery=True)=="SENT"
        assert len(sink.sent)==1 and sink.sent[0][0]==444
        assert sink.sent[0][1].count("[СИНТЕТИЧЕСКИЕ ДАННЫЕ]")==1
        assert await deliver_once(db,sink,NOW)=="EMPTY"
        apply_command(db,444,"/stop",NOW)
        assert not db.scalar(select(Subscriber)).active
        assert schedule_due(db,NOW,include_demo=True)==0
    engine.dispose()
