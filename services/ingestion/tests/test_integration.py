import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from app.storage.models import RawPayload, NewsItem, OutboxEvent, FailedItem, utcnow
from app.workers.ingest import Ingestor
from app.workers.supervisor import Supervisor
from app.publishers.outbox import OutboxPublisher

pytestmark = pytest.mark.integration


def count(sessions, model):
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(model))


def seed(database, contract, source, feed):
    ingestor = Ingestor(database[1], contract)
    return ingestor.process(source, feed)


def test_save_repeat_restart(database, contract, source, feed):
    sessions = database[1]
    assert seed(database, contract, source, feed)['created'] == 2
    assert seed(database, contract, source, feed)['duplicates'] == 2
    assert Ingestor(sessions, contract).process(source, feed)['duplicates'] == 2
    assert count(sessions, NewsItem) == count(sessions, OutboxEvent) == 2
    with sessions() as session:
        assert session.scalar(select(RawPayload)).body == feed.body
        for event in session.scalars(select(OutboxEvent)):
            contract.validate(event.payload)


def test_external_id_and_content_dedup(database, contract, source, feed):
    seed(database, contract, source, feed)
    changed = replace(feed, body=feed.body.replace(b'Policy   update', b'Updated title'))
    assert seed(database, contract, source, changed)['duplicates'] == 2
    new_ids = replace(feed, body=feed.body.replace(b'release-', b'other-'))
    assert seed(database, contract, source, new_ids)['duplicates'] == 2
    other_source = source.model_copy(update={'id': 'other_authority'})
    assert seed(database, contract, other_source, feed)['created'] == 2


def test_race_database_constraints(database, contract, source, feed):
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: seed(database, contract, source, feed), range(4)))
    assert sum(x['created'] for x in outcomes) == 2
    assert count(database[1], NewsItem) == count(database[1], OutboxEvent) == 2


def test_malformed_item_continues(database, contract, source, feed):
    malformed = feed.body.replace(b'<title> Policy   update </title>', b'<title> </title>')
    counts = seed(database, contract, source, replace(feed, body=malformed))
    assert counts == {'created': 1, 'duplicates': 0, 'failed': 1}
    assert count(database[1], FailedItem) == 1
    assert count(database[1], RawPayload) == 1


def test_bad_feed_retained(database, contract, source, feed):
    counts = seed(database, contract, source, replace(feed, body=b'<html>Error</html>'))
    assert counts['failed'] == 1
    assert count(database[1], FailedItem) == 1
    assert count(database[1], NewsItem) == 0


def test_atomic_rollback(database, contract, source, feed, monkeypatch):
    def fail(_):
        raise OperationalError('simulated storage failure', {}, Exception())
    monkeypatch.setattr(contract, 'validate', fail)
    with pytest.raises(OperationalError):
        seed(database, contract, source, feed)
    for model in (RawPayload, NewsItem, OutboxEvent):
        assert count(database[1], model) == 0


async def test_outbox_unavailable_recovery_restart(database, contract, source, feed):
    seed(database, contract, source, feed)
    sessions = database[1]
    bus = AsyncMock()
    bus.publish.side_effect = ConnectionError('offline')
    publisher = OutboxPublisher(sessions, bus, contract)
    assert await publisher.run_once()
    with sessions() as session:
        failed = session.scalar(select(OutboxEvent).where(OutboxEvent.attempts == 1))
        assert failed.status == 'pending' and failed.last_error == 'ConnectionError'
        assert failed.next_attempt_at > utcnow()
    with sessions.begin() as session:
        session.execute(update(OutboxEvent).values(next_attempt_at=utcnow() - timedelta(seconds=1)))
    bus.publish.side_effect = None
    restarted = OutboxPublisher(sessions, bus, contract)
    while await restarted.run_once():
        pass
    with sessions() as session:
        assert all(row.status == 'published' for row in session.scalars(select(OutboxEvent)))
    for call in bus.publish.call_args_list:
        contract.validate(call.args[1])


async def test_expired_lease_and_stale_ack(database, contract, source, feed):
    seed(database, contract, source, feed)
    sessions = database[1]
    publisher = OutboxPublisher(sessions, AsyncMock(), contract)
    original = publisher.claim()
    second = publisher.claim()
    assert original.id != second.id
    assert publisher.claim() is None
    with sessions.begin() as session:
        session.execute(update(OutboxEvent).where(OutboxEvent.id == original.id).values(lease_until=utcnow() - timedelta(seconds=1)))
    reclaimed = publisher.claim()
    assert reclaimed.id == original.id and reclaimed.lease_token != original.lease_token
    publisher.finish(original)
    with sessions() as session:
        assert session.get(OutboxEvent, original.id).status == 'pending'
    publisher.finish(reclaimed)
    with sessions() as session:
        assert session.get(OutboxEvent, original.id).status == 'published'


async def test_poison_outbox_dead(database, contract, source, feed):
    seed(database, contract, source, feed)
    with database[1].begin() as session:
        row = session.scalar(select(OutboxEvent))
        row.payload = {'invalid': True}
    bus = AsyncMock()
    publisher = OutboxPublisher(database[1], bus, contract)
    while await publisher.run_once():
        pass
    with database[1]() as session:
        statuses = list(session.scalars(select(OutboxEvent.status)))
        assert sorted(statuses) == ['dead', 'published']
    assert bus.publish.await_count == 1


async def test_failed_source_does_not_stop_others(database, contract, source, feed):
    bad = source.model_copy(update={'id': 'bad_authority'})
    adapters = {source.id: AsyncMock(), bad.id: AsyncMock()}
    adapters[source.id].fetch.return_value = feed
    adapters[bad.id].fetch.side_effect = ConnectionError('offline')
    supervisor = Supervisor([source, bad], adapters, Ingestor(database[1], contract), None, 1)
    results = await asyncio.gather(supervisor.poll_once(bad), supervisor.poll_once(source))
    assert results == [False, True]
    assert supervisor.states[bad.id]['status'] == 'failed'
    assert count(database[1], NewsItem) == 2


def test_migration_matches_models_and_roundtrip(database):
    from alembic import command
    from alembic.config import Config
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.storage.models import Base
    with database[0].connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    command.downgrade(Config('alembic.ini'), 'base')
    command.upgrade(Config('alembic.ini'), 'head')
    with database[0].connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def test_no_guid_content_dedup(database, contract, source, feed):
    body = feed.body.replace(b'<guid isPermaLink="false">release-1</guid>', b'').replace(b'<guid isPermaLink="false">release-2</guid>', b'')
    without_ids = replace(feed, body=body)
    assert seed(database, contract, source, without_ids)['created'] == 2
    assert seed(database, contract, source, without_ids)['duplicates'] == 2


def test_concurrent_outbox_claims(database, contract, source, feed):
    seed(database, contract, source, feed)
    publisher = OutboxPublisher(database[1], AsyncMock(), contract)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: publisher.claim(), range(4)))
    rows = [row for row in claims if row]
    assert len(rows) == 2 and rows[0].id != rows[1].id


def test_bounded_poll_retains_complete_raw_feed_and_explicit_backfill(database, contract, source, feed):
    limited = source.model_copy(update={'max_items_per_poll': 1})
    ingestor = Ingestor(database[1], contract)
    assert ingestor.process(limited, feed) == {'created': 1, 'duplicates': 0, 'failed': 0, 'deferred': 1}
    with database[1]() as session:
        assert session.scalar(select(RawPayload)).body == feed.body
    assert ingestor.process(limited, feed, selected_indices=[1])['created'] == 1
    assert count(database[1], NewsItem) == count(database[1], OutboxEvent) == 2


@pytest.mark.parametrize('indices', [[-1], [2], ['0']])
def test_invalid_research_selection_rolls_back(database, contract, source, feed, indices):
    with pytest.raises(ValueError):
        Ingestor(database[1], contract).process(source, feed, selected_indices=indices)
    assert count(database[1], NewsItem) == count(database[1], RawPayload) == 0
