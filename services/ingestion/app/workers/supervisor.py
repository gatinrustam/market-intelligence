import asyncio
import random
from datetime import datetime, timezone

from app.logging import log
from app.workers.ingest import InvalidFeed


class Supervisor:
    def __init__(self, sources, adapters, ingestor, publisher, interval):
        self.sources, self.adapters, self.ingestor = sources, adapters, ingestor
        self.publisher, self.interval = publisher, interval
        self.states = {s.id: {'id': s.id, 'name': s.name, 'enabled': s.enabled,
                            'metadata': {k: getattr(s, k) for k in ('domain', 'source_class', 'source_quality', 'source_role', 'poll_priority', 'language', 'expected_content_types')},
                            'status': 'starting' if s.enabled else 'disabled',
                            'last_success_at': None, 'last_error_type': None, 'counts': None}
                       for s in sources}
        self.tasks = []

    async def poll_once(self, source):
        state = self.states[source.id]
        try:
            log('fetch_started', source_id=source.id)
            fetched = await self.adapters[source.id].fetch()
            counts = await asyncio.to_thread(self.ingestor.process, source, fetched)
            state['counts'] = counts
            if counts['failed'] and not (counts['created'] or counts['duplicates']):
                raise InvalidFeed('no valid items')
            state.update(status='degraded' if counts['failed'] else 'healthy',
                         last_success_at=datetime.now(timezone.utc).isoformat(), last_error_type=None)
            return True
        except Exception as exc:
            state.update(status='degraded' if isinstance(exc, InvalidFeed) else 'failed', last_error_type=type(exc).__name__)
            log('source_failed', source_id=source.id, error_type=type(exc).__name__)
            return False

    async def source_loop(self, source):
        failures = 0
        while True:
            ok = await self.poll_once(source)
            failures = 0 if ok else min(failures + 1, 8)
            delay = source.poll.interval_seconds if ok else min(1800, source.poll.interval_seconds * 2 ** failures)
            await asyncio.sleep(delay + random.uniform(0, 1))

    async def publisher_loop(self):
        while True:
            try:
                if await self.publisher.run_once():
                    continue
            except Exception as exc:
                log('publisher_failed', error_type=type(exc).__name__)
            await asyncio.sleep(self.interval)

    def start(self):
        self.tasks = [asyncio.create_task(self.source_loop(s), name=s.id) for s in self.sources if s.enabled]
        self.tasks.append(asyncio.create_task(self.publisher_loop(), name='outbox'))

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
