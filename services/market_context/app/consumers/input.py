import asyncio
import json

from nats.js.api import ConsumerConfig, AckPolicy, DeliverPolicy
from nats.js.errors import NotFoundError

from app.logging import log
from app.domain import iso


class InputConsumer:
    def __init__(self, bus, repository, durable):
        self.bus, self.repository, self.durable = bus, repository, durable
        self.subscription = None
        self.connection = None

    async def subscribe(self):
        await self.bus.connect()
        if self.subscription is not None and self.connection is self.bus.nc:
            return
        try:
            info = await self.bus.js.consumer_info('EVENTS', self.durable)
            if info.config.ack_policy != AckPolicy.EXPLICIT or set(info.config.filter_subjects or []) != {'event.detected.v1','event.updated.v1'}:
                raise RuntimeError('incompatible durable event consumer')
        except NotFoundError:
            await self.bus.js.add_consumer('EVENTS', config=ConsumerConfig(
                durable_name=self.durable, ack_policy=AckPolicy.EXPLICIT,
                deliver_policy=DeliverPolicy.ALL, filter_subjects=['event.detected.v1','event.updated.v1'], ack_wait=30,
                max_ack_pending=128, max_deliver=-1))
        self.subscription = await self.bus.js.pull_subscribe_bind(stream='EVENTS', durable=self.durable)
        self.connection = self.bus.nc

    async def handle(self, message):
        try:
            state = await asyncio.to_thread(self.repository.accept, message.data, message.metadata.sequence.stream, message.subject,
                {'stream': message.metadata.stream, 'consumer': message.metadata.consumer,
                 'stream_sequence': message.metadata.sequence.stream, 'consumer_sequence': message.metadata.sequence.consumer,
                 'num_delivered': message.metadata.num_delivered, 'published_at': iso(message.metadata.timestamp)})
        except Exception as exc:
            log('input_persist_failed', error_type=type(exc).__name__)
            await message.nak(delay=5)
            return
        # No HTTP/extraction before this ACK. Duplicate/invalid input also ACKs only after DB commit.
        await message.ack_sync(timeout=5)
        log('input_persisted', status=state, stream_sequence=message.metadata.sequence.stream)

    async def run_once(self):
        await self.subscribe()
        try:
            messages = await self.subscription.fetch(batch=16, timeout=1)
        except TimeoutError:
            return False
        for message in messages:
            await self.handle(message)
        return bool(messages)
