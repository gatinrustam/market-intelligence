import asyncio
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from app.config import Settings
from app.storage.database import make_database
from app.storage.models import Evaluation, EvaluationRevision
from app.storage.repository import Repository
from app.worker import Worker, Upstreams
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.consumers.input import InputConsumer
from app.metrics import metrics
from app.domain import identity
from app.logging import configure_logging, log


async def supervise(name, operation):
    while True:
        try: active=await operation()
        except Exception as exc:
            log('worker_error',worker=name,error_type=type(exc).__name__)
            await asyncio.sleep(3)
        else:
            if not active: await asyncio.sleep(.5)


def create_app(settings=None):
    settings=settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        engine,sessions=make_database(settings.database_url.get_secret_value())
        repo=Repository(sessions,settings); bus=JetStreamBus(settings.nats_url.get_secret_value(),settings.fixtures_enabled)
        upstreams=Upstreams(settings); worker=Worker(repo,upstreams,settings)
        consumer=InputConsumer(bus,repo,settings.durable_name)
        publisher=OutboxPublisher(sessions,bus,repo.output_contract)
        operations=[('input',consumer.run_once),('scheduler',worker.run_once),('outbox',publisher.run_once)]
        if settings.fixtures_enabled:
            fixtures=InputConsumer(bus,repo,settings.durable_name+'_FIXTURES',fixture=True)
            operations.append(('fixture_input',fixtures.run_once))
        app.state.repo,app.state.sessions,app.state.engine,app.state.bus=repo,sessions,engine,bus
        app.state.tasks=[asyncio.create_task(supervise(name,fn),name=name) for name,fn in operations] if settings.workers_enabled else []
        try: yield
        finally:
            for task in app.state.tasks: task.cancel()
            await asyncio.gather(*app.state.tasks,return_exceptions=True)
            await upstreams.close(); await bus.close(); await asyncio.to_thread(engine.dispose)
    app=FastAPI(title='Evaluation Engine',version='0.1.0',lifespan=lifespan)
    @app.get('/health')
    def health(): return {'status':'alive'}
    @app.get('/ready')
    async def ready():
        def database():
            try:
                with app.state.engine.connect() as c: return c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='e50001'
            except Exception: return False
        db,nats=await asyncio.gather(asyncio.to_thread(database),app.state.bus.healthcheck())
        checks={'database':db,'jetstream':nats,'workers':all(not t.done() for t in app.state.tasks)}
        return JSONResponse(checks,status_code=200 if all(checks.values()) else 503)
    @app.get('/stats')
    def stats(): return app.state.repo.stats()
    @app.get('/metrics')
    def aggregate(group_by:str='horizon',origin:Literal['model','fixture','all']='model',basis:Literal['all','live_observed','source_published_at']='all'):
        try: return metrics(app.state.sessions,group_by.split(','),origin,basis)
        except ValueError as exc: raise HTTPException(422,str(exc)) from None
    @app.get('/evaluations/{evaluation_id}')
    def evaluation(evaluation_id:UUID):
        value=app.state.repo.view(str(evaluation_id))
        if value is None: raise HTTPException(404,'Unknown evaluation')
        return value
    @app.get('/analyses/{analysis_id}/evaluation')
    def for_analysis(analysis_id:UUID):
        value=app.state.repo.view(identity(str(analysis_id)))
        if value is None: raise HTTPException(404,'Evaluation not yet available')
        return value
    @app.get('/evaluations/{evaluation_id}/revisions')
    def revisions(evaluation_id:UUID,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as s:
            if s.get(Evaluation,str(evaluation_id)) is None: raise HTTPException(404,'Unknown evaluation')
            return [r.payload for r in s.scalars(select(EvaluationRevision).where(EvaluationRevision.evaluation_id==str(evaluation_id)).order_by(EvaluationRevision.revision).offset(offset).limit(limit))]
    @app.get('/events/{event_id}/evaluations')
    def for_event(event_id:UUID,origin:Literal['model','fixture','all']='model',offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as s:
            q=select(Evaluation).where(Evaluation.event_id==str(event_id))
            if origin!='all': q=q.where(Evaluation.origin==origin)
            return [r.payload for r in s.scalars(q.order_by(Evaluation.created_at.desc(),Evaluation.id).offset(offset).limit(limit))]
    return app

app=create_app()
