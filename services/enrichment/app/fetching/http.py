import asyncio
import hashlib
import time
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from app.logging import log
from app.models.errors import ProcessingError


class DocumentFetcher(Protocol):
    async def fetch(self, job, url: str, policy): ...


class HTTPDocumentFetcher:
    def __init__(self, settings, guard, rate_limiter, store, transport=None):
        self.settings, self.guard, self.rate_limiter, self.store = settings, guard, rate_limiter, store
        self.transport = transport  # Only dependency injection in deterministic tests.
        self.clients = {}

    def client(self, destination):
        # Pool separation by original TLS hostname prevents SNI/certificate reuse across hosts sharing an IP.
        key = (urlsplit(destination.url).scheme, destination.hostname, destination.port)
        if key not in self.clients:
            self.clients[key] = httpx.AsyncClient(trust_env=False, follow_redirects=False,
                transport=self.transport, limits=httpx.Limits(max_connections=4, max_keepalive_connections=2))
        return self.clients[key]

    async def close(self):
        for client in self.clients.values():
            await client.aclose()

    async def fetch(self, job, url, policy):
        started = time.monotonic()
        metadata = {'requested_url': url, 'final_url': None, 'http_status': None,
                    'content_type': None, 'redirect_count': 0}
        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds):
                return await self._fetch(job, url, policy, metadata)
        except ProcessingError as exc:
            exc.metadata = metadata | exc.metadata
            raise
        except (httpx.TransportError, TimeoutError) as exc:
            raise ProcessingError('request_timeout' if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else 'connection_failure',
                                  transient=True, metadata=metadata) from None
        finally:
            log('fetch_finished', job_id=job.id, source_message_id=job.source_message_id,
                hostname=urlsplit(metadata['final_url']).hostname if metadata['final_url'] else None,
                attempt=job.attempt_count, http_status=metadata['http_status'],
                duration_ms=round((time.monotonic() - started) * 1000))

    async def _fetch(self, job, url, policy, metadata):
        requested = url
        for redirect_count in range(self.settings.max_redirects + 1):
            destination = await self.guard.validate(url, policy.allowed_hosts)
            metadata.update(final_url=destination.url, redirect_count=redirect_count)
            await self.rate_limiter.wait(destination.hostname)
            original = httpx.URL(destination.url)
            pinned = original.copy_with(host=destination.ip)
            timeout = httpx.Timeout(self.settings.read_timeout_seconds,
                                    connect=self.settings.connect_timeout_seconds)
            request = httpx.Request('GET', pinned, headers={
                'Host': original.netloc.decode('ascii'), 'User-Agent': self.settings.user_agent,
                'Accept-Encoding': 'identity', 'Accept': 'text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9'},
                extensions={'sni_hostname': destination.hostname, 'timeout': timeout.as_dict()})
            response = await self.client(destination).send(request, stream=True)
            try:
                media = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                metadata.update(http_status=response.status_code, content_type=media[:200] or None)
                if len(media) > 200:
                    raise ProcessingError('invalid_content_type')
                if response.status_code in (301, 302, 303, 307, 308):
                    if redirect_count == self.settings.max_redirects:
                        raise ProcessingError('too_many_redirects', rejected=True)
                    location = response.headers.get('location')
                    if not location:
                        raise ProcessingError('missing_redirect_location')
                    url = urljoin(destination.url, location)
                    # Next iteration validates allowlist and every resolved IP before any destination request.
                    continue
                if not 200 <= response.status_code < 300:
                    raise ProcessingError(f'http_{response.status_code}',
                        transient=response.status_code in (408, 429, 500, 502, 503, 504))
                if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                    raise ProcessingError('unsupported_encoding')
                try:
                    declared = int(response.headers['content-length']) if 'content-length' in response.headers else None
                    if declared is not None and declared < 0:
                        raise ValueError()
                except ValueError:
                    raise ProcessingError('invalid_content_length') from None
                if declared is not None and declared > max(self.settings.html_max_bytes, self.settings.pdf_max_bytes):
                    raise ProcessingError('response_too_large', rejected=True)
                body = bytearray()
                limit = self.settings.pdf_max_bytes if media == 'application/pdf' else self.settings.html_max_bytes
                async for chunk in response.aiter_raw(chunk_size=65536):
                    # Signature sniff is bounded and does not depend on a filename extension.
                    if len(body) < 5 and (bytes(body) + chunk).startswith(b'%PDF-'):
                        media, limit = 'application/pdf', self.settings.pdf_max_bytes
                        metadata['content_type'] = media
                    if (declared is not None and declared > limit) or len(body) + len(chunk) > limit:
                        raise ProcessingError('response_too_large', rejected=True)
                    body.extend(chunk)
                safe_headers = {key: response.headers[key][:1024] for key in
                                ('etag', 'last-modified', 'content-type', 'content-length') if key in response.headers}
                snapshot = {
                    'requested_url': requested, 'final_url': destination.url,
                    'fetched_at': datetime.now(timezone.utc).replace(tzinfo=None),
                    'http_status': response.status_code, 'content_type': media or 'application/octet-stream',
                    'content_length': len(body), 'response_hash': hashlib.sha256(body).hexdigest(),
                    'raw_body': bytes(body), 'redirect_count': redirect_count, 'safe_headers': safe_headers}
                return await asyncio.to_thread(self.store.save_snapshot, job, snapshot)
            finally:
                await response.aclose()
        raise AssertionError('unreachable')
