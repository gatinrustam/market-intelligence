import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, update

from app.extraction.runner import ExtractionRunner
from app.fetching.rate_limit import HostRateLimiter
from app.normalization.document import build_document
from app.policies.sufficiency import EnrichmentPolicy
from app.publishers.outbox import OutboxPublisher
from app.storage.models import (EnrichmentInput, EnrichmentJob, EnrichedDocument, FetchSnapshot,
                                InvalidInput, OutboxEvent, utcnow)
from app.storage.repository import LeaseLost
from app.workers.enrich import EnrichmentWorker
from tests.helpers import make_fetcher, response, BytesStream

pytestmark = pytest.mark.integration


def accept(repository, event):
    return repository.accept(json.dumps(event, ensure_ascii=False, indent=3).encode(), 1)


def count(repository, model):
    with repository.sessions() as session:
        return session.scalar(select(func.count()).select_from(model))


def document(repository):
    with repository.sessions() as session:
        return session.scalar(select(EnrichedDocument)).payload


def worker(repository, policies, settings, fetcher):
    return EnrichmentWorker(repository, policies, fetcher, ExtractionRunner(settings), settings)


def test_exact_input_duplicates_and_conflict(repository, event):
    raw = json.dumps(event, indent=3).encode()
    assert repository.accept(raw, 9) == 'accepted'
    assert repository.accept(raw, 9) == 'duplicate'
    with repository.sessions() as session:
        assert session.get(EnrichmentInput, event['message_id']).exact_payload == raw
    assert count(repository, EnrichmentJob) == 1
    event['content']['body'] = 'conflicting same identity'
    assert accept(repository, event) == 'identity_conflict'
    assert count(repository, InvalidInput) == 1
    assert count(repository, EnrichmentJob) == 1


def test_concurrent_input_race(repository, event):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: accept(repository, event), range(4)))
    assert count(repository, EnrichmentJob) == count(repository, EnrichmentInput) == 1


async def test_sufficient_no_http_duplicate_after_complete(repository, policies, settings, event, output_contract):
    event['content']['body'] = 'Sufficient body with original source information. '*20
    accept(repository, event)
    fetcher = AsyncMock()
    await worker(repository, policies, settings, fetcher).run_once()
    fetcher.fetch.assert_not_awaited()
    result = document(repository)
    output_contract.validate(result)
    assert result['enrichment']['status'] == 'ready'
    assert result['fetch']['status'] == 'not_requested' and result['content']['content_source'] == 'rss'
    accept(repository, event)
    assert not await worker(repository, policies, settings, fetcher).run_once()
    assert count(repository, EnrichedDocument) == count(repository, OutboxEvent) == 1


@pytest.mark.parametrize('same_title', [False, True])
async def test_html_and_title_only(repository, policies, settings, event, html_bytes, same_title):
    event['content']['body'] = event['content']['title'] if same_title else ''
    accept(repository, event)
    requests = []
    def handler(request):
        requests.append(request)
        return response(html_bytes, content_type='text/html; charset=utf-8', headers={'set-cookie': 'secret=value', 'etag': 'fixture'})
    fetcher = make_fetcher(settings, repository, handler)
    try:
        await worker(repository, policies, settings, fetcher).run_once()
    finally:
        await fetcher.close()
    result = document(repository)
    assert result['enrichment']['status'] == 'ready'
    assert result['content']['content_source'] == 'html' and result['content']['title'] == event['content']['title']
    assert result['content']['extracted_title'] and result['classification'] == event['classification']
    assert requests[0].url.host == '93.184.216.34'
    assert requests[0].headers['host'] == 'example.org' and requests[0].extensions['sni_hostname'] == 'example.org'
    with repository.sessions() as session:
        snap = session.scalar(select(FetchSnapshot))
        assert snap.raw_body == html_bytes and snap.response_hash == hashlib.sha256(html_bytes).hexdigest()
        assert 'set-cookie' not in snap.safe_headers and snap.safe_headers['etag'] == 'fixture'


async def test_pdf_mislabelled_snapshot(repository, policies, settings, event, pdf_bytes):
    event['url'] = 'https://example.org/statement.pdf'
    accept(repository, event)
    fetcher = make_fetcher(settings, repository, lambda _: response(pdf_bytes, content_type='application/octet-stream'))
    try:
        await worker(repository, policies, settings, fetcher).run_once()
    finally:
        await fetcher.close()
    result = document(repository)
    assert result['enrichment']['status'] == 'ready' and result['content']['content_source'] == 'pdf'
    assert result['fetch']['content_type'] == 'application/pdf' and result['extraction']['method'] == 'pypdf'


@pytest.mark.parametrize('body,status', [('', 'failed'), ('Original RSS content remains available.', 'partial')])
async def test_404_fallback(repository, policies, settings, event, body, status):
    event['content']['body'] = body
    accept(repository, event)
    fetcher = make_fetcher(settings, repository, lambda _: response(status=404))
    try:
        await worker(repository, policies, settings, fetcher).run_once()
    finally:
        await fetcher.close()
    result = document(repository)
    assert result['enrichment']['status'] == status and result['content']['body'] == body
    assert result['fetch']['http_status'] == 404 and result['enrichment']['failure_reason'] == 'http_404'
    assert count(repository, OutboxEvent) == 1
    with repository.sessions() as session:
        row = session.scalar(select(EnrichmentJob))
        assert row.attempt_count == 1 and row.failed_at and row.last_error_type == 'http_404'


async def test_503_retry_and_exhaustion(repository, policies, settings, event):
    event['content']['body'] = 'Fallback source body.'
    accept(repository, event)
    calls = []
    fetcher = make_fetcher(settings, repository, lambda r: calls.append(r) or response(status=503))
    service = worker(repository, policies, settings, fetcher)
    try:
        for attempt in range(settings.max_attempts):
            await service.run_once()
            with repository.sessions.begin() as session:
                job = session.scalar(select(EnrichmentJob))
                assert job.attempt_count == attempt+1
                if attempt+1 < settings.max_attempts:
                    assert job.status == 'retry_wait' and job.next_retry_at > utcnow()
                    job.next_retry_at = utcnow() - timedelta(seconds=1)
        assert not await service.run_once()
    finally:
        await fetcher.close()
    assert len(calls) == settings.max_attempts
    assert document(repository)['enrichment']['status'] == 'partial'


async def test_transient_recovers(repository, policies, settings, event, html_bytes):
    accept(repository, event)
    responses = iter([response(status=503), response(html_bytes)])
    fetcher = make_fetcher(settings, repository, lambda _: next(responses))
    service = worker(repository, policies, settings, fetcher)
    try:
        await service.run_once()
        with repository.sessions.begin() as session:
            session.execute(update(EnrichmentJob).values(next_retry_at=utcnow()-timedelta(seconds=1)))
        await service.run_once()
    finally:
        await fetcher.close()
    assert document(repository)['enrichment']['status'] == 'ready'


async def test_redirect_private_rejected_before_destination(repository, policies, settings, event):
    accept(repository, event)
    calls = []
    fetcher = make_fetcher(settings, repository, lambda r: calls.append(r) or response(status=302, headers={'location': 'http://127.0.0.1:8000/health'}))
    try:
        await worker(repository, policies, settings, fetcher).run_once()
    finally:
        await fetcher.close()
    assert len(calls) == 1
    assert document(repository)['enrichment']['status'] == 'rejected'
    assert count(repository, FetchSnapshot) == 0


async def test_oversize_aborts_and_next_job_works(repository, policies, settings, event):
    from uuid import uuid4
    import httpx
    limited = settings.model_copy(update={'html_max_bytes': 1024, 'pdf_max_bytes': 1024})
    accept(repository, event)
    stream = BytesStream(b'x'*200000)
    fetcher = make_fetcher(limited, repository, lambda _: httpx.Response(200, headers={'content-type': 'text/html'}, stream=stream))
    try:
        await worker(repository, policies, limited, fetcher).run_once()
    finally:
        await fetcher.close()
    assert document(repository)['enrichment']['failure_reason'] == 'response_too_large'
    assert document(repository)['enrichment']['status'] == 'rejected'
    assert stream.closed and stream.reads < 25
    event['message_id'] = str(uuid4())
    event['content']['body'] = 'Enough original text. '*30
    accept(repository, event)
    await worker(repository, policies, settings, AsyncMock()).run_once()
    assert count(repository, EnrichedDocument) == 2


async def test_restart_reuses_snapshot_and_fences_stale_worker(repository, policies, settings, event, html_bytes):
    accept(repository, event)
    old_job, _ = repository.claim()
    fetcher = make_fetcher(settings, repository, lambda _: response(html_bytes))
    snapshot = await fetcher.fetch(old_job, event['url'], policies.sources['test_authority'])
    await fetcher.close()
    with repository.sessions.begin() as session:
        session.execute(update(EnrichmentJob).values(lease_until=utcnow()-timedelta(seconds=1)))
    fresh_fetcher = AsyncMock()
    await worker(repository, policies, settings, fresh_fetcher).run_once()
    fresh_fetcher.fetch.assert_not_awaited()
    assert document(repository)['fetch']['snapshot_id'] == snapshot.id
    with pytest.raises(LeaseLost):
        repository.complete(old_job, document(repository))
    assert count(repository, FetchSnapshot) == count(repository, EnrichedDocument) == count(repository, OutboxEvent) == 1


async def test_restart_before_snapshot_resumes(repository, policies, settings, event, html_bytes):
    accept(repository, event)
    repository.claim()
    with repository.sessions.begin() as session:
        session.execute(update(EnrichmentJob).values(lease_until=utcnow()-timedelta(seconds=1)))
    fetcher = make_fetcher(settings, repository, lambda _: response(html_bytes))
    try:
        await worker(repository, policies, settings, fetcher).run_once()
    finally:
        await fetcher.close()
    assert document(repository)['enrichment']['status'] == 'ready'


async def test_output_outage_recovery(repository, policies, settings, event, output_contract):
    event['content']['body'] = 'Enough input text. '*30
    accept(repository, event)
    await worker(repository, policies, settings, AsyncMock()).run_once()
    bus = AsyncMock()
    bus.publish.side_effect = ConnectionError('unavailable')
    publisher = OutboxPublisher(repository.sessions, bus, output_contract)
    await publisher.run_once()
    with repository.sessions.begin() as session:
        row = session.scalar(select(OutboxEvent))
        assert row.status == 'pending'
        expected_id = row.message_id
        row.next_attempt_at = utcnow()-timedelta(seconds=1)
    bus.publish.side_effect = None
    await OutboxPublisher(repository.sessions, bus, output_contract).run_once()
    with repository.sessions() as session:
        row = session.scalar(select(OutboxEvent))
        assert row.status == 'published' and row.message_id == expected_id
    assert {call.args[0] for call in bus.publish.call_args_list} == {expected_id}


def test_invalid_input_does_not_poison_queue(repository, event):
    assert repository.accept(b'{invalid', 1) == 'invalid'
    assert repository.accept(b'{"message_id":"bad"}', 2) == 'invalid'
    assert accept(repository, event) == 'accepted'
    assert count(repository, InvalidInput) == 2 and count(repository, EnrichmentJob) == 1


def test_claim_concurrency(repository, event):
    accept(repository, event)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: repository.claim(), range(4)))
    assert sum(result is not None for result in claims) == 1


def test_rate_slots_shared(repository):
    limiter = HostRateLimiter(repository.sessions, 1)
    with ThreadPoolExecutor(max_workers=3) as pool:
        delays = sorted(pool.map(lambda _: limiter.reserve('example.org'), range(3)))
    assert delays[0] < .5 and delays[1] >= .8 and delays[2] >= 1.8


def test_migration_roundtrip_no_drift(database):
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


@pytest.mark.parametrize('kind,body,content_type,status,method', [
    ('plain', b'Plain original document with multiple useful sentences. '*20, 'text/plain; charset=utf-8', 'ready', 'plain_text'),
    ('unsupported', b'GIF89a', 'image/gif', 'partial', 'none'),
    ('invalid_pdf', b'%PDF-invalid', 'application/pdf', 'partial', 'pypdf'),
    ('empty_html', b'<html><script>hidden</script></html>', 'text/html', 'partial', 'trafilatura'),
])
async def test_extraction_fallbacks(repository, policies, settings, event, kind, body, content_type, status, method):
    event['content']['body'] = 'Original RSS fallback.'
    accept(repository, event)
    fetcher = make_fetcher(settings, repository, lambda _: response(body, content_type=content_type))
    try:
        await worker(repository, policies, settings, fetcher).run_once()
    finally:
        await fetcher.close()
    result = document(repository)
    assert result['enrichment']['status'] == status
    assert result['extraction']['method'] == method
    assert result['fetch']['status'] == 'success' and count(repository, FetchSnapshot) == 1
    if status == 'partial':
        assert result['content']['body'] == event['content']['body']


async def test_redirect_limit(repository, policies, settings, event):
    accept(repository, event)
    calls = []
    fetcher = make_fetcher(settings, repository, lambda r: calls.append(r) or response(status=302, headers={'location': '/next'}))
    try:
        await worker(repository, policies, settings, fetcher).run_once()
    finally:
        await fetcher.close()
    assert len(calls) == settings.max_redirects + 1
    assert document(repository)['enrichment']['failure_reason'] == 'too_many_redirects'


async def test_declared_size_rejected_before_read(repository, policies, settings, event):
    import httpx
    accept(repository, event)
    stream = BytesStream(b'x'*200000)
    fetcher = make_fetcher(settings, repository, lambda _: httpx.Response(200,
        headers={'content-type': 'application/pdf', 'content-length': str(settings.pdf_max_bytes+1)}, stream=stream))
    try:
        await worker(repository, policies, settings, fetcher).run_once()
    finally:
        await fetcher.close()
    assert stream.reads == 0 and stream.closed
    assert document(repository)['enrichment']['failure_reason'] == 'response_too_large'


async def test_never_policy_keeps_rss(repository, policies, settings, event):
    policies.sources['test_authority'].mode = 'never'
    event['content']['body'] = 'Small RSS content.'
    accept(repository, event)
    fetcher = AsyncMock()
    await worker(repository, policies, settings, fetcher).run_once()
    fetcher.fetch.assert_not_awaited()
    assert document(repository)['content']['body'] == event['content']['body']
    assert document(repository)['enrichment']['status'] == 'partial'


async def test_missing_policy_rejects_no_http(repository, policies, settings, event):
    policies.sources.clear()
    accept(repository, event)
    fetcher = AsyncMock()
    await worker(repository, policies, settings, fetcher).run_once()
    fetcher.fetch.assert_not_awaited()
    assert document(repository)['enrichment']['failure_reason'] == 'source_policy_missing'
    assert document(repository)['enrichment']['status'] == 'rejected'


async def test_total_http_deadline(repository, policies, settings, event):
    limited = settings.model_copy(update={'request_timeout_seconds': .05})
    accept(repository, event)
    async def slow(_):
        await asyncio.sleep(5)
        return response(b'unreachable')
    fetcher = make_fetcher(limited, repository, slow)
    try:
        await asyncio.wait_for(worker(repository, policies, limited, fetcher).run_once(), 1)
    finally:
        await fetcher.close()
    with repository.sessions() as session:
        job = session.scalar(select(EnrichmentJob))
        assert job.status == 'retry_wait' and job.last_error_type == 'request_timeout'
    assert count(repository, EnrichedDocument) == 0


async def test_extractor_deadline_kills_process(settings, monkeypatch):
    from types import SimpleNamespace
    from app.extraction.runner import ExtractionRunner
    class HangingProcess:
        returncode = None
        killed = False
        async def communicate(self, data):
            await asyncio.sleep(5)
        def kill(self):
            self.killed = True
            self.returncode = -9
        async def wait(self):
            return self.returncode
    process = HangingProcess()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
    snapshot = SimpleNamespace(id='snapshot',job_id='job',final_url='https://example.org/a',
                               content_type='application/pdf',safe_headers={},raw_body=b'%PDF-')
    limited = settings.model_copy(update={'extraction_timeout_seconds': .02})
    result = await ExtractionRunner(limited).extract(snapshot)
    assert result.reason == 'extraction_timeout' and result.method == 'pypdf'
    assert process.killed


async def test_missing_url_terminal(repository, policies, settings, event):
    event['url'] = None
    accept(repository, event)
    fetcher = AsyncMock()
    await worker(repository, policies, settings, fetcher).run_once()
    fetcher.fetch.assert_not_awaited()
    assert document(repository)['enrichment']['failure_reason'] == 'missing_url'
    assert document(repository)['enrichment']['status'] == 'failed'

async def test_read_only_source_summary(repository,event,database,settings,policies):
    import httpx
    from app.main import create_app
    event['content']['body']='RSS evidence remains available.'
    accept(repository,event)
    app=create_app(settings);app.state.sessions=database[1]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        assert (await c.get('/sources')).json()==[]
        fetcher=make_fetcher(settings,repository,lambda _: response(status=403))
        try:await worker(repository,policies,settings,fetcher).run_once()
        finally:await fetcher.close()
        rows=(await c.get('/sources')).json()
        assert rows[0]['documents_count']==1 and rows[0]['enrichment_states']=={'partial':1}
        assert rows[0]['errors']=={'http_403':1}
    assert count(repository,EnrichmentInput)==1
