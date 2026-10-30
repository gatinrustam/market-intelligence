import os
from uuid import uuid4

import json
import pytest
from nats.js.api import StorageType

from app.normalization.rss import normalize
from app.publishers.nats import JetStreamBus

pytestmark = pytest.mark.jetstream


async def test_real_jetstream_ack_contract_and_duplicate(source, feed, contract):
    url = os.getenv('TEST_NATS_URL')
    if not url:
        pytest.skip('TEST_NATS_URL required')
    bus = JetStreamBus(url)
    event = normalize({'id': str(uuid4()), 'title': 'JetStream integration test'}, source, str(uuid4()), feed.received_at)
    try:
        await bus.connect()
        await bus.publish(event['message_id'], event)
        await bus.publish(event['message_id'], event)
        # Other production messages can arrive; inspect by the acknowledged sequence directly.
        ack = await bus.js.publish('news.raw.v1', json.dumps(event).encode(),
                                   headers={'Nats-Msg-Id': event['message_id']})
        assert ack.duplicate is True
        stored = await bus.js.get_msg('NEWS_RAW', seq=ack.seq)
        payload = json.loads(stored.data)
        contract.validate(payload)
        assert payload == event
        assert (await bus.js.stream_info('NEWS_RAW')).config.storage == StorageType.FILE
    finally:
        await bus.close()
