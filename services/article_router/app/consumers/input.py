import asyncio
from nats.js.api import ConsumerConfig, AckPolicy, DeliverPolicy
from nats.js.errors import NotFoundError
from app.domain import iso
from app.logging import log


class InputConsumer:
    def __init__(self, bus, repository, durable, fixture=False):
        self.bus, self.repo, self.durable = bus, repository, durable
        self.stream = 'DOCUMENT_INTELLIGENCE'
        self.subject = 'document.intelligence.v1'
        self.subscription = self.connection = None

    async def subscribe(self):
        await self.bus.connect()
        if self.subscription is not None and self.connection is self.bus.nc: return
        try:
            info = await self.bus.js.consumer_info(self.stream,self.durable)
            if info.config.deliver_policy != DeliverPolicy.ALL or info.config.ack_policy != AckPolicy.EXPLICIT or info.config.filter_subject != self.subject:
                raise RuntimeError('incompatible intelligence consumer')
        except NotFoundError:
            await self.bus.js.add_consumer(self.stream,config=ConsumerConfig(durable_name=self.durable,
                ack_policy=AckPolicy.EXPLICIT,deliver_policy=DeliverPolicy.ALL,filter_subject=self.subject,ack_wait=30,max_ack_pending=128,max_deliver=-1))
        self.subscription = await self.bus.js.pull_subscribe_bind(stream=self.stream,durable=self.durable)
        self.connection = self.bus.nc

    async def handle(self, message):
        try:
            state = await asyncio.to_thread(self.repo.accept,message.data,message.metadata.sequence.stream,message.subject,
                {'stream':message.metadata.stream,'published_at':iso(message.metadata.timestamp),'num_delivered':message.metadata.num_delivered})
        except Exception as exc:
            log('input_persist_failed',error_type=type(exc).__name__)
            await message.nak(delay=5)
            return
        await message.ack_sync(timeout=5)
        log('input_persisted',status=state,stream=self.stream)

    async def run_once(self):
        await self.subscribe()
        try: messages = await self.subscription.fetch(batch=16,timeout=1)
        except TimeoutError: return False
        for message in messages: await self.handle(message)
        return bool(messages)
