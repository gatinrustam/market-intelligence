import asyncio
import random
from datetime import datetime, timezone

import httpx

from app.adapters.base import FetchResult
from app.config import SourceConfig, Settings
from app.logging import log


class FeedTooLarge(ValueError):
    pass


class GenericRSSAdapter:
    def __init__(self, source: SourceConfig, client: httpx.AsyncClient, settings: Settings):
        self.source, self.client, self.settings = source, client, settings

    async def fetch(self) -> FetchResult:
        for attempt in range(3):
            try:
                async with self.client.stream('GET', str(self.source.connector.url),
                                              headers={'User-Agent': self.settings.user_agent},
                                              timeout=self.settings.http_timeout_seconds,
                                              follow_redirects=True) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.settings.max_feed_bytes:
                            raise FeedTooLarge('feed exceeds configured size limit')
                    return FetchResult(bytes(body), datetime.now(timezone.utc),
                                       response.headers.get('content-type', '')[:200])
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                transient = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in (408, 429) or exc.response.status_code >= 500
                if not transient or attempt == 2:
                    raise
                log('fetch_retry', source_id=self.source.id, error_type=type(exc).__name__, attempt=attempt + 1)
                await asyncio.sleep(2 ** attempt + random.uniform(0, 0.5))
        raise AssertionError('unreachable')

    async def healthcheck(self) -> bool:
        try:
            await self.fetch()
            return True
        except Exception:
            return False
