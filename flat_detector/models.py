"""Persistence layer. DateTimes are stored as UTC; SQLite used for isolated tests only."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import (String, Integer, Float, Boolean, DateTime, ForeignKey, UniqueConstraint,
                        Index, Text, JSON)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    mode: Mapped[str] = mapped_column(String(40), default="UNKNOWN_PERMISSION")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    permission_scope: Mapped[str] = mapped_column(Text, default="")
    permission_proof: Mapped[str | None] = mapped_column(Text, nullable=True)
    permission_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    permission_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    demo_only: Mapped[bool] = mapped_column(Boolean, default=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_source_external"), Index("idx_listing_price", "price_rub"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(120))
    original_url: Mapped[str] = mapped_column(String(600))
    price_rub: Mapped[int] = mapped_column(Integer)
    area_sqm: Mapped[float] = mapped_column(Float)
    rooms: Mapped[int] = mapped_column(Integer)
    address: Mapped[str] = mapped_column(String(250))
    geo_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    route_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    route_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    route_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    premium_reason: Mapped[str | None] = mapped_column(String(250), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[Source] = relationship()
    evidence: Mapped[list[Evidence]] = relationship(back_populates="listing", cascade="all, delete-orphan")


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), index=True)
    signal: Mapped[str] = mapped_column(String(40))  # ACTIVE, RESERVED, REMOVED, SOLD, SOURCE_BLOCKED, RATE_LIMITED
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    origin_key: Mapped[str] = mapped_column(String(60))
    direct: Mapped[bool] = mapped_column(Boolean, default=False)
    independence_group: Mapped[str | None] = mapped_column(String(90), nullable=True)
    note: Mapped[str | None] = mapped_column(String(250), nullable=True)
    listing: Mapped[Listing] = relationship(back_populates="evidence")


class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), index=True)
    price_rub: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Subscriber(Base):
    __tablename__ = "subscribers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(90), default="Europe/Berlin")
    digest_hour: Mapped[int] = mapped_column(Integer, default=11)
    max_price_rub: Mapped[int] = mapped_column(Integer, default=8500000)
    awaiting_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (UniqueConstraint("subscriber_id", "local_day", name="uq_sub_day"), Index("idx_outbox_status", "status", "next_attempt_at"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    subscriber_id: Mapped[int] = mapped_column(ForeignKey("subscribers.id", ondelete="CASCADE"), index=True)
    local_day: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING, CLAIMED, SENT, BLOCKED, UNCERTAIN, CANCELLED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subscriber: Mapped[Subscriber] = relationship()


class RecheckJob(Base):
    __tablename__ = "recheck_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    idempotency_key: Mapped[str] = mapped_column(String(36), unique=True)
    reason: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(20), default="QUEUED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BotOffset(Base):
    __tablename__ = "bot_offset"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    next_update_id: Mapped[int] = mapped_column(Integer, default=0)
