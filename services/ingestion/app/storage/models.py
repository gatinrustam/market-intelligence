from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    # DB dates are UTC, naive to avoid MariaDB silently discarding timezone offsets.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class RawPayload(Base):
    __tablename__ = 'raw_payloads'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    body: Mapped[bytes] = mapped_column(LargeBinary().with_variant(LONGBLOB(), 'mysql', 'mariadb'))
    content_type: Mapped[str] = mapped_column(String(200))


class NewsItem(Base):
    __tablename__ = 'news_items'
    __table_args__ = (
        UniqueConstraint('source_id', 'external_id_hash', name='uq_news_external'),
        UniqueConstraint('source_id', 'content_hash', name='uq_news_content'),
    )
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64))
    external_id_hash: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_payload_id: Mapped[str] = mapped_column(ForeignKey('raw_payloads.id'))
    item_index: Mapped[int] = mapped_column(Integer)
    event: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OutboxEvent(Base):
    __tablename__ = 'outbox_events'
    __table_args__ = (Index('ix_outbox_due', 'status', 'next_attempt_at', 'lease_until'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(ForeignKey('news_items.message_id'), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    last_error: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class FailedItem(Base):
    __tablename__ = 'failed_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload_id: Mapped[str] = mapped_column(ForeignKey('raw_payloads.id'))
    item_index: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
