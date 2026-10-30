import json
import os
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from nats.js.api import StreamConfig, StorageType
from nats.js.errors import NotFoundError
from sqlalchemy import select
from fastapi.testclient import TestClient

from app.consumers.input import InputConsumer
from app.main import create_app
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.storage.models import EnrichmentInput, EnrichmentJob, EnrichedDocument, InvalidInput, OutboxEvent
from tests.test_integration import accept, count, worker, document

pytestmark = pytest.mark.integration


async def test_ack_observes_committed_exact_input(repository, event):
    raw = json.dumps(event, indent=2).encode()
    async def check_commit(**kwargs):
        with repository.sessions() as session:
            assert session.get(EnrichmentInput, event['message_id']).exact_payload == raw
            assert session.scalar(select(EnrichmentJob)).source_message_id == event['message_id']
        assert count(repository, EnrichedDocument) == 0
    message = SimpleNamespace(data=raw, metadata=SimpleNamespace(sequence=SimpleNamespace(stream=1)),
                              ack_sync=AsyncMock(side_effect=check_commit), nak=AsyncMock())
    consumer = InputConsumer(None, repository, 'test')
    await consumer.handle(message)
    await consumer.handle(message)
    assert message.ack_sync.await_count == 2
    message.nak.assert_not_awaited()
    assert count(repository, EnrichmentJob) == 1


async def test_database_failure_nak_no_ack(event):
    from unittest.mock import Mock
    repository = Mock()
    repository.accept.side_effect = ConnectionError('DB down')
    message = SimpleNamespace(data=json.dumps(event).encode(), metadata=SimpleNamespace(sequence=SimpleNamespace(stream=1)),
                              ack_sync=AsyncMock(), nak=AsyncMock())
    await InputConsumer(None, repository, 'test').handle(message)
    message.ack_sync.assert_not_awaited()
    message.nak.assert_awaited_once_with(delay=5)


async def test_real_nats_pipeline_duplicates_and_malformed(repository, policies, settings, event, output_contract):
    url = os.getenv('TEST_NATS_URL')
    if not url:
        pytest.skip('TEST_NATS_URL required')
    assert 'nats-test:' in url, 'Never mutate production broker in tests'
    bus = JetStreamBus(url)
    durable = 'ENRICHMENT_TEST_' + uuid4().hex
    try:
        await bus.connect()
        try:
            await bus.js.stream_info('NEWS_RAW')
        except NotFoundError:
            await bus.js.add_stream(config=StreamConfig(name='NEWS_RAW', subjects=['news.raw.v1'], storage=StorageType.FILE))
        await bus.js.purge_stream('NEWS_RAW')
        before = (await bus.js.stream_info('NEWS_RAW')).config.as_dict()
        consumer = InputConsumer(bus, repository, durable)
        await consumer.subscribe()
        event['content']['body'] = 'A sufficient original document body. '*30
        raw = json.dumps(event, indent=4).encode()
        await bus.js.publish('news.raw.v1', b'{malformed')
        await bus.js.publish('news.raw.v1', raw)
        await bus.js.publish('news.raw.v1', raw)  # no broker dedup header: exercise DB idempotency
        assert await consumer.run_once()
        info = await bus.js.consumer_info('NEWS_RAW', durable)
        assert info.num_ack_pending == 0 and info.num_pending == 0
        assert count(repository, InvalidInput) == count(repository, EnrichmentInput) == count(repository, EnrichmentJob) == 1
        with repository.sessions() as session:
            assert session.get(EnrichmentInput, event['message_id']).exact_payload == raw
        fetcher = AsyncMock()
        await worker(repository, policies, settings, fetcher).run_once()
        fetcher.fetch.assert_not_awaited()
        await OutboxPublisher(repository.sessions, bus, output_contract).run_once()
        payload = document(repository)
        ack = await bus.js.publish('document.enriched.v1', json.dumps(payload).encode(), headers={'Nats-Msg-Id': payload['message_id']})
        assert ack.duplicate
        published = json.loads((await bus.js.get_msg('DOCUMENT_ENRICHED', seq=ack.seq)).data)
        output_contract.validate(published)
        assert published == payload and published['enrichment']['status'] == 'ready'
        # A new consumer object binds the existing durable after restart.
        resumed = InputConsumer(bus, repository, durable)
        await bus.js.publish('news.raw.v1', raw)
        assert await resumed.run_once()
        assert count(repository, EnrichedDocument) == count(repository, OutboxEvent) == count(repository, EnrichmentJob) == 1
        assert (await bus.js.stream_info('NEWS_RAW')).config.as_dict() == before
    finally:
        if bus.js:
            await bus.js.delete_consumer('NEWS_RAW', durable)
        await bus.close()


async def test_api_database_nats_readiness_and_documents(repository, policies, settings, event):
    event['content']['body'] = 'Sufficient original source body. '*30
    accept(repository, event)
    await worker(repository, policies, settings, AsyncMock()).run_once()
    configured = settings.model_copy(update={'database_url': settings.database_url.__class__(os.environ['TEST_DATABASE_URL'])})
    app = create_app(configured)
    with TestClient(app) as client:
        app.state.bus.healthcheck = AsyncMock(return_value=True)
        assert client.get('/health').json() == {'status': 'alive'}
        assert client.get('/ready').status_code == 200
        app.state.bus.healthcheck.return_value = False
        assert client.get('/ready').status_code == 503
        assert client.get('/stats').json()['documents'] == {'ready': 1}
        payload = document(repository)
        assert client.get('/documents/'+payload['document_id']).json() == payload
        with repository.sessions() as session:
            job = session.scalar(select(EnrichmentJob))
            assert client.get('/jobs/'+job.id).json()['status'] == 'completed'
        assert client.get('/documents/missing').status_code == 404
        assert client.get('/jobs/missing').status_code == 404
