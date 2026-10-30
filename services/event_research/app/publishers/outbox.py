import asyncio
import random
from datetime import timedelta
from typing import Protocol

from jsonschema.exceptions import ValidationError
from sqlalchemy import or_, select, update, exists
from sqlalchemy.orm import aliased

from app.logging import log
from app.storage.models import OutboxEvent, utcnow, new_id


class EventBus(Protocol):
    async def publish(self, message_id: str, payload: dict, subject: str): ...


class OutboxPublisher:
    def __init__(self, sessions, bus: EventBus, contract):
        self.sessions, self.bus, self.contract = sessions, bus, contract

    def claim(self):
        now = utcnow()
        with self.sessions.begin() as session:
            row = session.scalar(select(OutboxEvent).where(
                OutboxEvent.status == 'pending', OutboxEvent.next_attempt_at <= now,
                or_(OutboxEvent.lease_until.is_(None), OutboxEvent.lease_until <= now)
            ).order_by(OutboxEvent.next_attempt_at, OutboxEvent.id).limit(1).with_for_update(skip_locked=True))
            if row is None:
                return None
            row.lease_token, row.lease_until = new_id(), now + timedelta(seconds=60)
            row.attempts += 1
            session.flush()
            return row

    def finish(self, row, error=None, dead=False):
        values = {'lease_until': None, 'lease_token': None, 'last_error': error}
        if error:
            values.update(status='dead' if dead else 'pending',
                          next_attempt_at=utcnow() + timedelta(seconds=min(300, 2 ** min(row.attempts, 9)) + random.random()))
        else:
            values.update(status='published', published_at=utcnow())
        with self.sessions.begin() as session:
            session.execute(update(OutboxEvent).where(OutboxEvent.id == row.id,
                                                      OutboxEvent.lease_token == row.lease_token).values(**values))

    async def run_once(self):
        row = await asyncio.to_thread(self.claim)
        if row is None:
            return False
        context = {'outbox_id': row.id, 'message_id': row.message_id, 'research_id': row.research_id, 'subject': row.subject}
        try:
            self.contract.validate(row.payload)
            # Deadline is shorter than claim lease. Cancel/crash leaves a recoverable lease.
            await asyncio.wait_for(self.bus.publish(row.message_id, row.payload, row.subject), timeout=15)
        except Exception as exc:
            dead = isinstance(exc, ValidationError)
            await asyncio.to_thread(self.finish, row, type(exc).__name__, dead)
            log('outbox_dead' if dead else 'publish_retry', **context, error_type=type(exc).__name__)
        else:
            await asyncio.to_thread(self.finish, row)
            log('published', **context)
        return True
