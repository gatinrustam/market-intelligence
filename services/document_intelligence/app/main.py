import asyncio
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import JSONResponse
from sqlalchemy import select,text
from app.config import Settings
from app.domain import load_configuration,digest,identity,version_key
from app.pipeline import Pipeline
from app.storage.database import make_database
from app.storage.models import IntelligenceInput,IntelligenceJob,IntelligenceRun
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.consumers.input import InputConsumer
from app.worker import Worker
from app.logging import configure_logging,log
async def supervise(name,fn):
    while True:
        try:active=await fn()
        except Exception as exc:log('worker_error',worker=name,error_type=type(exc).__name__);await asyncio.sleep(3)
        else:
            if not active:await asyncio.sleep(.5)
def create_app(settings=None):
    settings=settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        configure_logging();configuration=load_configuration(settings)
        engine,sessions=make_database(settings.database_url.get_secret_value());repo=Repository(sessions,settings,configuration);repo.register()
        pipeline=Pipeline(configuration);bus=JetStreamBus(settings.nats_url.get_secret_value())
        consumer=InputConsumer(bus,repo,settings.durable_prefix+'_'+digest(configuration)[:16]);worker=Worker(repo,pipeline);publisher=OutboxPublisher(sessions,bus,repo.output_contract)
        app.state.repo=repo;app.state.sessions=sessions;app.state.engine=engine;app.state.bus=bus;app.state.tasks=[]
        if settings.workers_enabled:app.state.tasks=[asyncio.create_task(supervise(name,fn)) for name,fn in [('input',consumer.run_once),('extraction',worker.run_once),('outbox',publisher.run_once)]]
        try:yield
        finally:
            for task in app.state.tasks:task.cancel()
            await asyncio.gather(*app.state.tasks,return_exceptions=True);await bus.close();engine.dispose()
    app=FastAPI(title='Document Intelligence',lifespan=lifespan)
    @app.get('/health')
    def health():return {'status':'alive'}
    @app.get('/ready')
    async def ready():
        def database():
            try:
                with app.state.engine.connect() as c:return c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='di1001'
            except Exception:return False
        checks={'database':await asyncio.to_thread(database),'jetstream':await app.state.bus.healthcheck(),'workers':all(not t.done() for t in app.state.tasks)}
        return JSONResponse(checks,status_code=200 if all(checks.values()) else 503)
    @app.get('/stats')
    def stats():return app.state.repo.stats()
    @app.get('/intelligence/{key}')
    def get(key:UUID):
        p=app.state.repo.view(str(key))
        if p is None:raise HTTPException(404,'No completed intelligence')
        return p
    @app.get('/intelligence/{key}/input')
    def original(key:UUID):
        with app.state.sessions() as s:
            job=s.get(IntelligenceJob,str(key))
            if not job:raise HTTPException(404,'Unknown run')
            row=s.get(IntelligenceInput,job.input_id)
            return {'exact_payload':row.exact_payload,'payload_hash':row.payload_hash,'configuration':job.configuration,'provenance':row.provenance}
    @app.get('/intelligence/{key}/metadata')
    def metadata(key:UUID):
        value=app.state.repo.view(str(key))
        if value is None:raise HTTPException(404,'No completed intelligence')
        with app.state.sessions() as s:
            job=s.get(IntelligenceJob,str(key));row=s.get(IntelligenceInput,job.input_id);d=row.payload
            return {'document_id':d['document_id'],'input_message_id':d['message_id'],'source_message_id':d['lineage']['source_message_id'],
                'source':d['source'],'title':d['content']['title'],'published_at':d['timestamps']['published_at'],
                'document_status':d['enrichment']['status'],'body_length':d['content']['body_length'],'body_hash':value['document']['body_hash'],
                'intelligence_id':value['intelligence_id'],'intelligence_hash':digest(value),'extraction':value['extraction']}
    @app.get('/documents/{document_id}/intelligence')
    def document(document_id:UUID,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as s:
            return [r.payload for r in s.scalars(select(IntelligenceRun).join(IntelligenceJob,IntelligenceJob.id==IntelligenceRun.id).where(IntelligenceJob.input_id==str(document_id),IntelligenceRun.payload.is_not(None)).order_by(IntelligenceJob.version).offset(offset).limit(limit))]
    @app.get('/jobs')
    def jobs(offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as s:return [{'intelligence_id':r.id,'document_id':r.input_id,'version':r.version,'status':r.status,'error':r.error,'attempts':r.attempts} for r in s.scalars(select(IntelligenceJob).order_by(IntelligenceJob.id).offset(offset).limit(limit))]
    @app.post('/documents/{document_id}/research',status_code=202)
    def research(document_id:UUID):
        repo=app.state.repo
        with app.state.sessions() as s:
            row=s.get(IntelligenceInput,str(document_id))
            if row is None:raise HTTPException(404,'Unknown document')
            raw=row.exact_payload.encode();metadata=row.provenance;doc=row.payload
        repo.accept(raw,metadata['stream_sequence'],'document.enriched.v1',metadata)
        return {'intelligence_id':identity(doc,repo.configuration),'version':version_key(repo.configuration)}
    return app
app=create_app()
