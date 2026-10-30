import asyncio
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import FastAPI,HTTPException,Query,Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,text
from app.config import Settings
from app.domain import load_configuration,digest,iso
from app.storage.database import make_database
from sqlalchemy.exc import IntegrityError
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.consumers.input import InputConsumer
from app.worker import MetadataClient,Worker
from app.correlation.domain import load_policy
from app.correlation.repository import CorrelationRepository
from typing import Literal
from app.logging import configure_logging,log

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
        configure_logging();configuration=load_configuration(settings)
        engine,sessions=make_database(settings.database_url.get_secret_value());repo=Repository(sessions,settings,configuration)
        await asyncio.to_thread(repo.register)
        correlation=CorrelationRepository(sessions,load_policy(settings.correlation_rules_path))
        await asyncio.to_thread(correlation.register)
        app.state.correlation=correlation
        bus=JetStreamBus(settings.nats_url.get_secret_value());events=MetadataClient(settings)
        consumer=InputConsumer(bus,repo,settings.durable_prefix+'_'+digest(configuration)[:16])
        worker=Worker(repo,events);publisher=OutboxPublisher(sessions,bus,repo.output_contract)
        app.state.repo=repo;app.state.engine=engine;app.state.sessions=sessions;app.state.bus=bus;app.state.tasks=[]
        if settings.workers_enabled:
            app.state.tasks=[asyncio.create_task(supervise(name,op)) for name,op in [('input',consumer.run_once),('intelligence',worker.run_once),('outbox',publisher.run_once),('correlation',correlation.work)]]
        try:yield
        finally:
            for task in app.state.tasks:task.cancel()
            await asyncio.gather(*app.state.tasks,return_exceptions=True)
            await events.close();await bus.close();await asyncio.to_thread(engine.dispose)
    app=FastAPI(title='Event Engine v2 Research',lifespan=lifespan)
    @app.get('/health')
    def health():return {'status':'alive'}
    @app.get('/ready')
    async def ready():
        def db():
            try:
                with app.state.engine.connect() as c:return c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='di4001'
            except Exception:return False
        checks={'database':await asyncio.to_thread(db),'jetstream':await app.state.bus.healthcheck(),'workers':all(not t.done() for t in app.state.tasks)}
        return JSONResponse(checks,status_code=200 if all(checks.values()) else 503)
    @app.get('/stats')
    def stats():return app.state.repo.stats()
    @app.get('/research')
    def catalogue(offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        return app.state.repo.catalogue(offset,limit)
    @app.get('/research/{key}')
    def research(key:UUID):
        result=app.state.repo.detail(str(key))
        if result is None:raise HTTPException(404,'Unknown research result')
        return result
    @app.get('/documents/{key}/comparison')
    def comparison(key:UUID):return app.state.repo.for_document(str(key))
    @app.get('/correlation/stats')
    def correlation_stats():return app.state.correlation.stats()
    @app.get('/correlation/events')
    def correlation_events():return app.state.correlation.events()
    @app.get('/correlation/events/{key}/revisions')
    def correlation_revisions(key:UUID):
        rows=app.state.correlation.revisions(str(key))
        if not rows:raise HTTPException(404,'Unknown research event')
        return rows
    @app.get('/correlation/decisions')
    def correlation_decisions(mode:Literal['exact_match','strong_match','suggestion','separate','insufficient_data']|None=None,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        return app.state.correlation.decisions(mode,offset,limit)
    @app.get('/documents/{key}/correlation')
    def document_correlation(key:UUID):return app.state.correlation.for_document(str(key))
    return app
app=create_app()
