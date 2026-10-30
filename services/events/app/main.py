import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import JSONResponse
from sqlalchemy import func,select,text
from app.config import Settings
from app.taxonomy.configuration import load_bundle
from app.extraction.rules import RuleBasedEventExtractor
from app.correlation.core import EventCore
from app.consumers.input import InputConsumer
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.storage.contract import Contract,CanonicalContract
from app.storage.database import make_database
from app.storage.models import EventInput,EventJob,Event,EventRevision,ExtractionRun,CorrelationSuggestion,OutboxEvent,DeadInput
from app.storage.repository import Repository
from app.workers.process import EventWorker
from app.logging import configure_logging,log


async def supervise(name,operation):
    while True:
        try:
            active=await operation()
        except Exception as exc:
            log('worker_error',worker=name,error_type=type(exc).__name__)
            await asyncio.sleep(5)
        else:
            if not active:
                await asyncio.sleep(.5)


def create_app(settings=None):
    settings=settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        bundle=load_bundle(settings.config_dir)
        engine,sessions=make_database(settings.database_url.get_secret_value())
        contract=CanonicalContract(settings.output_schema_path)
        repository=Repository(sessions,Contract(settings.input_schema_path),settings)
        bus=JetStreamBus(settings.nats_url.get_secret_value())
        extractor=RuleBasedEventExtractor(bundle)
        core=EventCore(repository,contract,bundle)
        consumer=InputConsumer(bus,repository,settings.durable_name)
        worker=EventWorker(repository,extractor,core,bundle,settings)
        publisher=OutboxPublisher(sessions,bus,contract)
        app.state.engine,app.state.sessions,app.state.bus=engine,sessions,bus
        app.state.tasks=[]
        if settings.workers_enabled:
            app.state.tasks=[asyncio.create_task(supervise(name,op),name=name) for name,op in
                [('input',consumer.run_once),('events',worker.run_once),('outbox',publisher.run_once)]]
        try:
            yield
        finally:
            for task in app.state.tasks:
                task.cancel()
            await asyncio.gather(*app.state.tasks,return_exceptions=True)
            await bus.close()
            await asyncio.to_thread(engine.dispose)
    app=FastAPI(title='Event Engine',version='0.1.0',lifespan=lifespan)
    @app.get('/health')
    async def health():
        return {'status':'alive'}
    @app.get('/ready')
    async def ready():
        def check_db():
            try:
                with app.state.engine.connect() as conn:
                    revision=conn.execute(text('SELECT version_num FROM alembic_version')).scalar()
                    conn.execute(text('SELECT id FROM event_jobs LIMIT 1'))
                    return revision=='v20001'
            except Exception:
                return False
        database,jetstream=await asyncio.gather(asyncio.to_thread(check_db),app.state.bus.healthcheck())
        workers=all(not t.done() for t in app.state.tasks)
        return JSONResponse({'database':database,'jetstream':jetstream,'workers':workers},status_code=200 if database and jetstream and workers else 503)
    @app.get('/stats')
    def stats():
        with app.state.sessions() as session:
            def count(model,*conditions):
                return session.scalar(select(func.count()).select_from(model).where(*conditions))
            jobs=dict(session.execute(select(EventJob.status,func.count()).group_by(EventJob.status)).all())
            outcomes=dict(session.execute(select(EventJob.outcome,func.count()).where(EventJob.outcome.is_not(None)).group_by(EventJob.outcome)).all())
            types=dict(session.execute(select(Event.event_type,func.count()).group_by(Event.event_type)).all())
            return {'documents_received':count(EventInput),'documents_processed':sum(outcomes.values()),'outcomes':outcomes,
                'events_total':count(Event),'events_created':count(Event),'events_by_type':types,'unknown_events':types.get('unknown',0),
                'correlated_documents':outcomes.get('event_correlated',0),'correlation_suggestions':count(CorrelationSuggestion),
                'jobs':jobs,'jobs_pending':sum(jobs.get(k,0) for k in ('pending','processing','retry_wait')),
                'jobs_failed':jobs.get('failed',0),'outbox_pending':count(OutboxEvent,OutboxEvent.status=='pending'),
                'outbox_dead':count(OutboxEvent,OutboxEvent.status=='dead'),'dead_inputs':count(DeadInput)}
    @app.get('/events')
    def event_list(offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as session:
            total=session.scalar(select(func.count()).select_from(Event))
            rows=session.scalars(select(Event).order_by(Event.created_at.desc(),Event.id).offset(offset).limit(limit))
            return {'items':[r.payload for r in rows],'total':total,'offset':offset,'limit':limit}
    @app.get('/events/{event_id}')
    def event(event_id:str):
        with app.state.sessions() as session:
            row=session.get(Event,event_id)
            if row is None:
                raise HTTPException(404,'Unknown event')
            return row.payload
    @app.get('/events/{event_id}/revisions')
    def revisions(event_id:str,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as session:
            if session.get(Event,event_id) is None:
                raise HTTPException(404,'Unknown event')
            return [r.payload for r in session.scalars(select(EventRevision).where(EventRevision.event_id==event_id)
                .order_by(EventRevision.revision).offset(offset).limit(limit))]
    @app.get('/documents/{document_id}/input')
    def document_input(document_id:str):
        # Immutable exact input used by this Event Engine, not a refetch/current web page.
        from datetime import timezone
        with app.state.sessions() as session:
            row=session.get(EventInput,document_id)
            if row is None:raise HTTPException(404,'Unknown document input')
            return {'document':row.payload,'input_received_at':row.received_at.replace(tzinfo=timezone.utc).isoformat(),
                'stream_sequence':row.stream_sequence,'payload_sha256':row.payload_hash}
    @app.get('/documents/{document_id}/extraction')
    def extraction(document_id:str):
        with app.state.sessions() as session:
            if session.get(EventInput,document_id) is None:
                raise HTTPException(404,'Unknown document')
            rows=session.scalars(select(ExtractionRun).where(ExtractionRun.document_id==document_id).order_by(ExtractionRun.created_at))
            job=session.scalar(select(EventJob).where(EventJob.document_id==document_id))
            return {'job':{field:getattr(job,field) for field in ('id','status','outcome','attempt_count','next_retry_at','last_error_type','failed_at')},
                'runs':[{field:getattr(row,field) for field in ('id','extractor_name','extractor_version','ruleset_version','taxonomy_version',
                    'entity_registry_version','config_hash','input_quality','result_json','created_at')} for row in rows]}
    @app.get('/correlation-suggestions')
    def suggestions(offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as session:
            return [{field:getattr(r,field) for field in ('event_a','event_b','same_event_type','same_primary_actor','title_similarity',
                'time_distance_seconds','time_distance_basis','suggestion_reason','policy_hash','created_at')} for r in
                session.scalars(select(CorrelationSuggestion).order_by(CorrelationSuggestion.created_at,CorrelationSuggestion.event_a,
                    CorrelationSuggestion.event_b).offset(offset).limit(limit))]
    return app


app=create_app()
