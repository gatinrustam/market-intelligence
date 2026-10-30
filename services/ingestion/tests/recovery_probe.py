"""Real broker stop/start probe; run only against isolated ingestion_test database."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlalchemy import select, update

from app.adapters.base import FetchResult
from app.config import SourceConfig
from app.normalization.contract import Contract
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.storage.database import make_database
from app.storage.models import NewsItem, OutboxEvent, utcnow
from app.workers.ingest import Ingestor


async def main():
    url = os.environ['TEST_DATABASE_URL']
    assert '/ingestion_test' in url
    engine, sessions = make_database(url)
    contract = Contract(Path('/workspace/contracts/news/raw/v1.schema.json'))
    bus = JetStreamBus(os.environ['TEST_NATS_URL'])
    publisher = OutboxPublisher(sessions, bus, contract)
    source = SourceConfig(id='fault_probe', name='Fault probe', connector={'type': 'rss', 'url': 'https://example.org/rss'})
    try:
        if sys.argv[1] == 'offline':
            feed = FetchResult(Path('tests/fixtures/feed.xml').read_bytes(), datetime.now(timezone.utc), 'application/rss+xml')
            assert Ingestor(sessions, contract).process(source, feed)['created'] == 2
            while await publisher.run_once():
                pass
            with sessions() as session:
                rows = list(session.scalars(select(OutboxEvent).join(NewsItem).where(NewsItem.source_id == 'fault_probe')))
                assert len(rows) == 2
                assert all(row.status == 'pending' and row.attempts >= 1 for row in rows)
            print('PASS: stopped real NATS leaves both committed events pending')
        else:
            with sessions.begin() as session:
                session.execute(update(OutboxEvent).where(OutboxEvent.status == 'pending').values(next_attempt_at=utcnow() - timedelta(seconds=1)))
            while await publisher.run_once():
                pass
            with sessions() as session:
                rows = list(session.scalars(select(OutboxEvent).join(NewsItem).where(NewsItem.source_id == 'fault_probe')))
                assert len(rows) == 2 and all(row.status == 'published' for row in rows)
            await bus.connect()
            # Stored messages are fetched via management API, not a future consumer.
            info = await bus.js.stream_info('NEWS_RAW')
            found = set()
            for seq in range(info.state.first_seq, info.state.last_seq + 1):
                stored = await bus.js.get_msg('NEWS_RAW', seq=seq)
                event = json.loads(stored.data)
                contract.validate(event)
                found.add(event['message_id'])
            assert {r.message_id for r in rows} <= found
            print('PASS: new publisher process recovers both pending events into real JetStream')
    finally:
        await bus.close()
        engine.dispose()

asyncio.run(main())
