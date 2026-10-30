import asyncio
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,text
from app.config import Settings
from app.domain import load_rules,identity,input_identity,digest,iso
from app.storage.database import make_database
from app.storage.models import IntelligenceInput,IntelligenceRun,IntelligenceResult,OutboxEvent
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.consumers.input import InputConsumer
from app.worker import EventsClient,Worker
from app.logging import configure_logging,log

class Research(BaseModel):
    model_config=ConfigDict(extra='forbid')
    event_revision:int=Field(ge=1)
    ruleset_version:str=Field(min_length=1,max_length=32)
async def supervise(name,operation):
    while True:
        try:active=await operation()
        except Exception as exc:log('worker_error',worker=name,error_type=type(exc).__name__);await asyncio.sleep(3)
        else:
            if not active:await asyncio.sleep(.5)
def create_app(settings=None):
    settings=settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        configure_logging();configuration=load_rules(settings.rules_path)
        engine,sessions=make_database(settings.database_url.get_secret_value());repo=Repository(sessions,settings,configuration)
        await asyncio.to_thread(repo.register)
        bus=JetStreamBus(settings.nats_url.get_secret_value());events=EventsClient(settings)
        consumer=InputConsumer(bus,repo,settings.durable_prefix+'_'+digest(configuration)[:16])
        worker=Worker(repo,events);publisher=OutboxPublisher(sessions,bus,repo.output_contract)
        app.state.repo=repo;app.state.engine=engine;app.state.sessions=sessions;app.state.bus=bus;app.state.tasks=[]
        if settings.workers_enabled:
            app.state.tasks=[asyncio.create_task(supervise(name,op)) for name,op in [('input',consumer.run_once),('intelligence',worker.run_once),('outbox',publisher.run_once)]]
        try:yield
        finally:
            for task in app.state.tasks:task.cancel()
            await asyncio.gather(*app.state.tasks,return_exceptions=True)
            await events.close();await bus.close();await asyncio.to_thread(engine.dispose)
    app=FastAPI(title='Event Intelligence',lifespan=lifespan)
    @app.get('/health')
    def health():return {'status':'alive'}
    @app.get('/ready')
    async def ready():
        def db():
            try:
                with app.state.engine.connect() as c:return c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='i55001'
            except Exception:return False
        checks={'database':await asyncio.to_thread(db),'jetstream':await app.state.bus.healthcheck(),'workers':all(not t.done() for t in app.state.tasks)}
        return JSONResponse(checks,status_code=200 if all(checks.values()) else 503)
    @app.get('/stats')
    def stats():return app.state.repo.stats()
    @app.get('/intelligence/{intelligence_id}')
    def intelligence(intelligence_id:UUID):
        value=app.state.repo.view(str(intelligence_id))
        if value is None:raise HTTPException(404,'Intelligence not available')
        return value
    @app.get('/intelligence/{intelligence_id}/availability')
    def availability(intelligence_id:UUID):
        from datetime import timezone
        value=app.state.repo.view(str(intelligence_id))
        if value is None:raise HTTPException(404,'Intelligence not available')
        with app.state.sessions() as s:
            row=s.scalar(select(OutboxEvent).where(OutboxEvent.intelligence_id==str(intelligence_id)))
            if row is None or row.status!='published' or row.published_at is None:raise HTTPException(409,'Durable publication not confirmed')
            return {'intelligence':value,'available_at':iso(row.published_at.replace(tzinfo=timezone.utc)),'availability_basis':'confirmed_jetstream_publication'}
    @app.get('/intelligence/{intelligence_id}/input')
    def frozen(intelligence_id:UUID):
        with app.state.sessions() as s:
            row=s.get(IntelligenceRun,str(intelligence_id))
            if row is None:raise HTTPException(404,'Unknown intelligence run')
            if row.snapshot is None:raise HTTPException(409,'No frozen completed input')
            return {'input_hash':digest(row.snapshot),'snapshot':row.snapshot,'configuration':row.configuration}
    @app.get('/events/{event_id}/intelligence')
    def for_event(event_id:UUID,event_revision:int|None=Query(None,ge=1),ruleset_version:str|None=Query(None,max_length=32),offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as s:
            q=select(IntelligenceResult).where(IntelligenceResult.event_id==str(event_id))
            if event_revision is not None:q=q.where(IntelligenceResult.event_revision==event_revision)
            if ruleset_version is not None:q=q.where(IntelligenceResult.ruleset_version==ruleset_version)
            return [r.payload for r in s.scalars(q.order_by(IntelligenceResult.event_revision,IntelligenceResult.ruleset_version).offset(offset).limit(limit))]
    @app.post('/events/{event_id}/research',status_code=202)
    def research(event_id:UUID,body:Research):
        repo=app.state.repo
        if body.ruleset_version!=repo.configuration['version']:raise HTTPException(422,'Load the requested versioned ruleset first')
        event={'id':str(event_id),'revision':body.event_revision}
        with app.state.sessions() as s:
            row=s.get(IntelligenceInput,input_identity(event))
            if row is None:raise HTTPException(404,'Unknown canonical revision')
            raw=row.exact_payload.encode();metadata=row.provenance
        repo.accept(raw,metadata.get('stream_sequence',0),metadata['subject'],metadata)
        return {'intelligence_id':identity(event,body.ruleset_version)}
    return app
app=create_app()
