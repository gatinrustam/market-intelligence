import asyncio
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.storage.models import HostSlot, utcnow


class HostRateLimiter:
    """Shared DB reservation slots; transactions end before sleeping or HTTP I/O."""
    def __init__(self, sessions, rate):
        self.sessions, self.interval = sessions, 1.0 / rate

    def reserve(self, hostname):
        # Insert races are resolved by PK; do not swallow unrelated integrity failures.
        try:
            with self.sessions.begin() as session:
                if session.get(HostSlot, hostname) is None:
                    session.add(HostSlot(hostname=hostname, next_allowed_at=utcnow()))
        except IntegrityError as exc:
            if getattr(exc.orig, 'args', [None])[0] != 1062:
                raise
        with self.sessions.begin() as session:
            row = session.scalar(select(HostSlot).where(HostSlot.hostname == hostname).with_for_update())
            now = utcnow()
            slot = max(now, row.next_allowed_at)
            row.next_allowed_at = slot + timedelta(seconds=self.interval)
            return max(0, (slot - now).total_seconds())

    async def wait(self, hostname):
        delay = await asyncio.to_thread(self.reserve, hostname)
        if delay:
            await asyncio.sleep(delay)
