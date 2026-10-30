import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text

from app.config import Settings, load_policies
from app.consumers.input import InputConsumer
from app.extraction.runner import ExtractionRunner
from app.fetching.http import HTTPDocumentFetcher
from app.fetching.rate_limit import HostRateLimiter
from app.fetching.security import URLGuard
from app.logging import configure_logging, log
from app.normalization.contract import Contract
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.storage.database import make_database
from app.storage.models import EnrichmentInput, InvalidInput, EnrichmentJob, EnrichedDocument, FetchSnapshot, OutboxEvent
from app.storage.repository import Repository
from app.workers.enrich import EnrichmentWorker


async def supervise(name, operation):
    while True:
        try:
            active = await operation()
        except Exception as exc:
            log('worker_error', worker=name, error_type=type(exc).__name__)
            await asyncio.sleep(5)
        else:
            if not active:
                await asyncio.sleep(0.5)


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        policies = load_policies(settings.policy_path)
        input_contract, output_contract = Contract(settings.input_schema_path), Contract(settings.output_schema_path)
        engine, sessions = make_database(settings.database_url.get_secret_value())
        repository = Repository(sessions, input_contract, output_contract, settings)
        bus = JetStreamBus(settings.nats_url.get_secret_value())
        fetcher = HTTPDocumentFetcher(settings, URLGuard(),
            HostRateLimiter(sessions, settings.max_requests_per_second_per_host), repository)
        consumer = InputConsumer(bus, repository, settings.durable_name)
        worker = EnrichmentWorker(repository, policies, fetcher, ExtractionRunner(settings), settings)
        publisher = OutboxPublisher(sessions, bus, output_contract)
        app.state.engine, app.state.sessions, app.state.bus = engine, sessions, bus
        app.state.tasks = []
        if settings.workers_enabled:
            app.state.tasks = [asyncio.create_task(supervise(name, operation), name=name) for name, operation in
                               [('input', consumer.run_once), ('enrich', worker.run_once), ('outbox', publisher.run_once)]]
        try:
            yield
        finally:
            for task in app.state.tasks:
                task.cancel()
            await asyncio.gather(*app.state.tasks, return_exceptions=True)
            await fetcher.close()
            await bus.close()
            await asyncio.to_thread(engine.dispose)

    app = FastAPI(title='Content Enrichment', version='0.1.0', lifespan=lifespan)

    @app.get('/health')
    async def health():
        return {'status': 'alive'}

    @app.get('/ready')
    async def ready():
        def check_db():
            try:
                with app.state.engine.connect() as connection:
                    revision = connection.execute(text('SELECT version_num FROM alembic_version')).scalar()
                    connection.execute(text('SELECT id FROM enrichment_jobs LIMIT 1'))
                    return revision == 'e0001'
            except Exception:
                return False
        db, bus = await asyncio.gather(asyncio.to_thread(check_db), app.state.bus.healthcheck())
        workers = all(not task.done() for task in app.state.tasks)
        return JSONResponse({'database': db, 'jetstream': bus, 'workers': workers}, status_code=200 if db and bus and workers else 503)

    @app.get('/stats')
    def stats():
        with app.state.sessions() as session:
            counts = {name: session.scalar(select(func.count()).select_from(model)) for name, model in
                      [('inputs', EnrichmentInput), ('invalid_inputs', InvalidInput), ('snapshots', FetchSnapshot)]}
            for name, model in [('jobs', EnrichmentJob), ('documents', EnrichedDocument), ('outbox', OutboxEvent)]:
                counts[name] = dict(session.execute(select(model.status, func.count()).group_by(model.status)).all())
            counts['retry_count'] = session.scalar(select(func.coalesce(func.sum(EnrichmentJob.attempt_count - 1), 0)).where(EnrichmentJob.attempt_count > 1))
            return counts

    @app.get('/sources')
    def source_summary():
        with app.state.sessions() as session:
            grouped=session.execute(select(EnrichmentInput.source_id,EnrichedDocument.status,func.count()).join(
                EnrichedDocument,EnrichedDocument.source_message_id==EnrichmentInput.source_message_id).group_by(EnrichmentInput.source_id,EnrichedDocument.status)).all()
            result={}
            for source,status,count in grouped:
                item=result.setdefault(source,{'source_id':source,'documents_count':0,'enrichment_states':{},'errors':{}})
                item['documents_count']+=count;item['enrichment_states'][status]=count
            for source,error,count in session.execute(select(EnrichmentInput.source_id,EnrichmentJob.last_error_type,func.count()).join(
                EnrichmentJob,EnrichmentJob.source_message_id==EnrichmentInput.source_message_id).where(EnrichmentJob.last_error_type.is_not(None)).group_by(EnrichmentInput.source_id,EnrichmentJob.last_error_type)):
                item=result.setdefault(source,{'source_id':source,'documents_count':0,'enrichment_states':{},'errors':{}});item['errors'][error]=count
            return list(result.values())
    @app.get('/documents/{document_id}')
    def document(document_id: str):
        with app.state.sessions() as session:
            row = session.get(EnrichedDocument, document_id)
            if row is None:
                raise HTTPException(404, 'Unknown document')
            return row.payload

    @app.get('/jobs/{job_id}')
    def job(job_id: str):
        with app.state.sessions() as session:
            row = session.get(EnrichmentJob, job_id)
            if row is None:
                raise HTTPException(404, 'Unknown job')
            return {field: getattr(row, field) for field in ('id', 'source_message_id', 'status', 'attempt_count',
                'next_retry_at', 'last_error_type', 'last_error_message', 'failed_at', 'completed_at')}

    return app


app = create_app()
