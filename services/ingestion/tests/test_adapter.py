from unittest.mock import AsyncMock

import httpx
import pytest

from app.adapters.rss import GenericRSSAdapter, FeedTooLarge
from app.config import Settings


async def test_retry_and_body_preservation(source, feed, monkeypatch):
    monkeypatch.setattr('app.adapters.rss.asyncio.sleep', AsyncMock())
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls < 3 else 200, content=feed.body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetched = await GenericRSSAdapter(source, client, Settings()).fetch()
    assert fetched.body == feed.body and calls == 3


async def test_permanent_error_no_retry(source):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(403)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GenericRSSAdapter(source, client, Settings())
        assert not await adapter.healthcheck()
    assert calls == 1


async def test_size_limit(source):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'x' * 2048))) as client:
        with pytest.raises(FeedTooLarge):
            await GenericRSSAdapter(source, client, Settings(max_feed_bytes=1024)).fetch()
