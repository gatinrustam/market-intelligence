import httpx
from unittest.mock import AsyncMock

from app.fetching.http import HTTPDocumentFetcher
from app.fetching.rate_limit import HostRateLimiter
from app.fetching.security import URLGuard


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, data, chunk_size=8192):
        self.data, self.chunk_size, self.reads, self.closed = data, chunk_size, 0, False

    async def __aiter__(self):
        for start in range(0, len(self.data), self.chunk_size):
            self.reads += 1
            yield self.data[start:start+self.chunk_size]

    async def aclose(self):
        self.closed = True


def response(data=b'', status=200, content_type='text/html', headers=None):
    return httpx.Response(status, headers={'content-type': content_type, **(headers or {})}, stream=BytesStream(data))


def make_fetcher(settings, repository, handler, limiter=None):
    guard = URLGuard(AsyncMock(return_value=['93.184.216.34']))
    limiter = limiter or AsyncMock()
    return HTTPDocumentFetcher(settings, guard, limiter, repository, transport=httpx.MockTransport(handler))
