"""Opt-in Telegram bot via the documented HTTPS Bot API (no bot framework required)."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from flat_detector.models import Subscriber, Outbox, BotOffset
from flat_detector.config import get_settings
from flat_detector.database import Session as SessionFactory, migrate_dev

log=logging.getLogger(__name__)


def apply_command(db: Session, chat_id: int, text: str, now: datetime) -> str:
    """Pure domain state handler. Do not accept group chats at the transport layer."""
    parts=text.strip().split(maxsplit=1)
    cmd=parts[0].lower().split("@")[0] if parts else ""
    arg=parts[1].strip() if len(parts)>1 else ""
    user=db.scalar(select(Subscriber).where(Subscriber.chat_id==chat_id).with_for_update())
    if cmd=="/delete_me":
        if user:
            db.execute(delete(Outbox).where(Outbox.subscriber_id==user.id));db.delete(user);db.commit()
        return "Профиль и история рассылки удалены. Для повторной подписки отправь /start."
    if cmd=="/start":
        if user is None:db.add(Subscriber(chat_id=chat_id));db.commit()
        return "Мониторинг ближних Химок. Подписка только по согласию: /subscribe, затем /confirm. Настройки: /settings. Отключение: /stop."
    if cmd=="/help":
        return "/start /subscribe /confirm /settings /budget 8500000 /timezone Europe/Berlin /hour 11 /stop /delete_me /digest"
    if user is None:
        return "Сначала отправь /start."
    if cmd=="/subscribe":
        user.awaiting_confirmation=True;db.commit()
        return "Подтверждаешь ежедневные сообщения о квартирах? Отправь /confirm. В любой момент можно /stop или /delete_me."
    if cmd=="/confirm":
        if not user.awaiting_confirmation:
            return "Сначала запроси подписку командой /subscribe."
        user.active=True;user.consent_at=now;user.awaiting_confirmation=False;db.commit()
        return "Подписка включена. Посмотреть настройки: /settings."
    if cmd=="/stop":
        user.active=False;user.awaiting_confirmation=False
        db.execute(delete(Outbox).where(Outbox.subscriber_id==user.id,Outbox.status.in_(["PENDING","CLAIMED","UNCERTAIN"])))
        db.commit()
        return "Будущие уведомления остановлены. Данные можно удалить через /delete_me."
    if cmd=="/settings":
        return (f"Подписка: {'включена' if user.active else 'выключена'}\n"
                f"Бюджет: {user.max_price_rub:,} ₽\nВремя: {user.digest_hour:02d}:00, {user.timezone}\n"
                "Настроить: /budget 8500000, /timezone Europe/Berlin, /hour 11")
    if cmd=="/budget":
        try:price=int(arg.replace(" ",""))
        except ValueError:return "Укажи бюджет целым числом: /budget 8500000"
        if not 1_000_000<=price<=9_000_000:return "Допустимый бюджет: от 1 до 9 млн ₽."
        user.max_price_rub=price;db.commit();return f"Лимит изменён: {price:,} ₽."
    if cmd=="/timezone":
        if len(arg)>90 or not arg:return "Пример: /timezone Europe/Berlin"
        try:ZoneInfo(arg)
        except (ZoneInfoNotFoundError,ValueError):return "Неизвестная временная зона. Пример: Europe/Berlin"
        user.timezone=arg;db.commit();return f"Часовой пояс: {arg}."
    if cmd=="/hour":
        try:hour=int(arg)
        except ValueError:return "Пример: /hour 11"
        if not 0<=hour<=23:return "Укажи час от 0 до 23."
        user.digest_hour=hour;db.commit();return f"Дайджест будет в {hour:02d}:00."
    if cmd=="/digest":
        from flat_detector.delivery import render_digest
        from flat_detector.service import DailyProfile
        return render_digest(db, DailyProfile(user.max_price_rub),now,local_day=now.astimezone(ZoneInfo(user.timezone)).date().isoformat(),include_demo=get_settings().demo_mode) or "Сейчас подходящих подтверждённых квартир нет."
    return "Неизвестная команда. Отправь /help."


class TelegramBotAPI:
    def __init__(self,token:str,*,client:httpx.AsyncClient|None=None):
        if not token:raise ValueError("FD_TELEGRAM_TOKEN is required")
        self.base=f"https://api.telegram.org/bot{token}/"
        self.client=client or httpx.AsyncClient(timeout=httpx.Timeout(40,connect=10))

    async def _request(self,method:str,payload:dict)->dict:
        from flat_detector.delivery import TelegramError
        try:
            response=await self.client.post(self.base+method,json=payload)
        except (httpx.TimeoutException,httpx.NetworkError) as e:
            # No safe retry: Telegram may already have accepted the message.
            raise TimeoutError("Telegram delivery result is unknown") from None
        data=response.json()
        if not data.get("ok"):
            raise TelegramError(data.get("error_code",response.status_code),
                                data.get("parameters",{}).get("retry_after"))
        return data["result"]

    async def send(self,chat_id:int,text:str):
        from flat_detector.delivery import TelegramResult
        result=await self._request("sendMessage",{"chat_id":chat_id,"text":text[:4096],"disable_web_page_preview":True})
        return TelegramResult(message_id=result["message_id"])

    async def updates(self,offset:int):
        return await self._request("getUpdates",{"offset":offset,"timeout":25,"allowed_updates":["message"]})


async def poll() -> None:
    """One replica only. Update offset persisted after each command processing."""
    settings=get_settings()
    token=settings.telegram_token
    if not token and settings.telegram_token_file:
        with open(settings.telegram_token_file,encoding="utf-8") as f:token=f.read().strip()
    if not token:raise RuntimeError("Telegram token not configured")
    migrate_dev()
    async with httpx.AsyncClient(timeout=httpx.Timeout(45,connect=10)) as client:
        bot=TelegramBotAPI(token,client=client)
        while True:
            with SessionFactory() as db:
                state=db.get(BotOffset,1)
                if state is None:state=BotOffset(id=1,next_update_id=0);db.add(state);db.commit()
                offset=state.next_update_id
            try:
                updates=await bot.updates(offset)
            except Exception as exc:
                log.warning("telegram polling failure (%s); retrying",type(exc).__name__)
                await asyncio.sleep(5)
                continue
            for update in updates:
                ident=int(update["update_id"])
                with SessionFactory() as db:
                    state=db.get(BotOffset,1)
                    if ident<state.next_update_id:continue
                    message=update.get("message") or {}
                    chat=message.get("chat") or {}
                    sender=message.get("from") or {}
                    if (chat.get("type")=="private" and chat.get("id")==sender.get("id")
                            and isinstance(message.get("text"),str)):
                        reply=apply_command(db,int(chat["id"]),message["text"],datetime.now(timezone.utc))
                        try:await bot.send(int(chat["id"]),reply)
                        except Exception: log.warning("command reply failed (redacted); subscriber command persisted")
                    state.next_update_id=ident+1;db.commit()


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(poll())
