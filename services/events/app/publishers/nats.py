import asyncio
import json

import nats
from nats.js.api import StreamConfig, StorageType, RetentionPolicy, DiscardPolicy
from nats.js.errors import NotFoundError


class JetStreamBus:
    def __init__(self, url):
        self.url, self.nc, self.js = url, None, None
        self.lock = asyncio.Lock()

    async def connect(self):
        async with self.lock:
            if self.nc is None or self.nc.is_closed:
                async def ignore_error(exc):
                    pass
                self.nc = await nats.connect(self.url, connect_timeout=2, max_reconnect_attempts=2,
                                             reconnect_time_wait=1, error_cb=ignore_error)
                self.js = self.nc.jetstream()
            if not self.nc.is_connected:
                raise ConnectionError('NATS reconnecting')
            try:
                info = await self.js.stream_info('EVENTS')
            except NotFoundError:
                info = await self.js.add_stream(config=StreamConfig(name='EVENTS',
                    subjects=['event.detected.v1', 'event.updated.v1'], storage=StorageType.FILE,
                    retention=RetentionPolicy.LIMITS, discard=DiscardPolicy.NEW,
                    num_replicas=1, duplicate_window=86400, max_bytes=1_073_741_824, max_msg_size=1_000_000))
            if info.config.storage != StorageType.FILE or info.config.subjects != ['event.detected.v1', 'event.updated.v1']:
                raise RuntimeError('incompatible EVENTS stream configuration')

    async def publish(self, message_id, payload, subject):
        await self.connect()
        await self.js.publish(subject, json.dumps(payload, ensure_ascii=False).encode(),
            headers={'Nats-Msg-Id': message_id, 'Nats-Expected-Stream': 'EVENTS'}, timeout=5)

    async def healthcheck(self):
        try:
            await asyncio.wait_for(self.connect(), timeout=5)
            # Read-only check; Stage 1.5 owns DOCUMENT_ENRICHED and its configuration.
            await self.js.stream_info('DOCUMENT_ENRICHED')
            return True
        except Exception:
            return False

    async def close(self):
        if self.nc:
            await self.nc.close()
