"""Operator-only single-recipient Telegram delivery proof; never a daily digest.

No database mutations and no source ingestion. Never run automatically as a worker.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from flat_detector.models import Subscriber


DEMO_TEXT = (
    "ТЕСТ FLAT-DETECTOR — ВЫМЫШЛЕННЫЕ ДАННЫЕ\n\n"
    "Проверяем только доставку уведомления в Telegram.\n"
    "Пример 1: 7 990 000 ₽ · 33,4 м² · вымышленный объект, Химки.\n"
    "Пример 2: 8 750 000 ₽ · 42,1 м² · вымышленный объект, Левобережная.\n\n"
    "Это НЕ реальные объявления. Наличие квартир, цена, расстояние до МЦД "
    "и возможность покупки НЕ проверялись.\n"
    "Автоматическая ежедневная рассылка пока отключена."
)


class PilotGuardError(Exception):
    """Deliberate safety gate; do not display private subscriber identifiers."""


def sole_consenting_subscriber(db: OrmSession) -> Subscriber:
    """Deliberately refuse all group/bulk sending; no subscriber IDs in output."""
    candidates = db.scalars(
        select(Subscriber)
        .where(Subscriber.active.is_(True), Subscriber.consent_at.is_not(None))
        .limit(2)
    ).all()
    if len(candidates) != 1:
        raise PilotGuardError(
            "Пилот требует ровно одного активного подписчика с подтверждённым согласием. "
            "Не отправляем никому; проверь подписки локально."
        )
    return candidates[0]


async def send_one(chat_id: int, token: str, *, bot_factory=None) -> None:
    from flat_detector.bot import TelegramBotAPI
    factory = bot_factory or TelegramBotAPI
    bot = factory(token)
    try:
        result = await bot.send(chat_id, DEMO_TEXT)
        if not result.message_id:
            raise PilotGuardError("Telegram did not return a message ID")
    finally:
        await bot.client.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot pilot to the sole consenting Telegram subscriber")
    parser.add_argument("--send", action="store_true", help="Explicitly authorize ONE test message")
    args = parser.parse_args()

    # Do not open the credential until the operator explicitly requested --send.
    from flat_detector.database import Session
    with Session() as db:
        try:
            user = sole_consenting_subscriber(db)
        except PilotGuardError as e:
            print(f"STOP: {e}")
            return 2
        # Never echo chat ID, recipient, token or any subscriber profile.
        print("Target check: exactly one active consenting subscriber")
        print(DEMO_TEXT)
        if not args.send:
            print("DRY RUN ONLY: no Telegram message was sent. For one actual send use --send.")
            return 0
        token_path = Path("/run/secrets/telegram_token")
        try:
            token = token_path.read_text(encoding="utf-8").strip()
            if not token:
                print("STOP: Telegram token file is empty")
                return 2
            # Hold PostgreSQL subscriber row lock across network send. This serializes
            # /stop with delivery; re-fetch under lock immediately before sending.
            locked = db.scalar(
                select(Subscriber)
                .where(Subscriber.id == user.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not locked or not locked.active or locked.consent_at is None:
                print("STOP: subscriber disabled before send")
                db.rollback()
                return 2
            asyncio.run(send_one(locked.chat_id, token))
            db.commit()
        except Exception as exc:
            db.rollback()
            # Never serialize HTTPX exceptions: URLs can contain BotFather credentials.
            logging.warning("Pilot send failed, redacted exception type: %s", type(exc).__name__)
            print("Message delivery not confirmed; do not rerun --send without checking Telegram.")
            return 1
    print("Telegram confirmed: one explicitly requested fictional test message delivered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())