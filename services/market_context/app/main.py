import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Literal
import copy
from types import SimpleNamespace
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import JSONResponse
from sqlalchemy import select,text
from app.config import Settings
from app.storage.database import make_database
from app.storage.contract import CanonicalContract,ContextContract
from app.storage.models import MarketContext,ContextRevision,ContextInput
from app.storage.repository import Repository
from app.market import MarketDataClient
from app.worker import ContextWorker
from app.consumers.input import InputConsumer
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.logging import configure_logging,log
from app.causal import POLICY
from app.decision import DecisionInputs,DecisionResolver,DecisionUnavailable
from app.outcomes import outcome_view

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
        configure_logging();engine,sessions=make_database(settings.database_url.get_secret_value())
        contract=ContextContract(settings.output_schema_path)
        repo=Repository(sessions,CanonicalContract(settings.input_schema_path),contract,settings)
        bus=JetStreamBus(settings.nats_url.get_secret_value());market=MarketDataClient(settings.market_data_url)
        decision_inputs=DecisionInputs(bus,settings)
        app.state.decisions=DecisionResolver(decision_inputs,market,settings)
        worker=ContextWorker(repo,market,settings);consumer=InputConsumer(bus,repo,settings.durable_name);publisher=OutboxPublisher(sessions,bus,contract)
        app.state.sessions=sessions;app.state.engine=engine;app.state.repo=repo;app.state.bus=bus;app.state.market=market;app.state.tasks=[]
        if settings.workers_enabled:
            app.state.tasks=[asyncio.create_task(supervise(name,fn),name=name) for name,fn in [('input',consumer.run_once),('resolver',worker.run_once),('publisher',publisher.run_once)]]
        try:yield
        finally:
            for task in app.state.tasks:task.cancel()
            await asyncio.gather(*app.state.tasks,return_exceptions=True)
            await decision_inputs.close();await market.close();await bus.close();await asyncio.to_thread(engine.dispose)
    app=FastAPI(title='Market Context Resolver',lifespan=lifespan)
    @app.get('/health')
    def health():return {'status':'alive'}
    @app.get('/ready')
    async def ready():
        def database():
            try:
                with app.state.engine.connect() as c:return c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='c35101'
            except Exception:return False
        db,nats=await asyncio.gather(asyncio.to_thread(database),app.state.bus.healthcheck())
        checks={'database':db,'jetstream':nats,'workers':all(not t.done() for t in app.state.tasks)}
        return JSONResponse(checks,status_code=200 if all(checks.values()) else 503)
    @app.get('/stats')
    def stats():return app.state.repo.stats()
    @app.get('/contexts/{context_id}')
    def context(context_id:str):
        with app.state.sessions() as s:
            row=s.get(MarketContext,context_id)
            if row is None:raise HTTPException(404,'Unknown context')
            return row.payload
    @app.get('/contexts/{context_id}/decision')
    async def decision(context_id:str,basis:Literal['live','research_hypothetical']='live',additional_input_available_at:datetime|None=None):
        if additional_input_available_at is not None and (additional_input_available_at.tzinfo is None or basis!='live'):raise HTTPException(422,'Additional input availability requires timezone-aware live mode')
        def read_input():
            with app.state.sessions() as s:
                row=s.get(MarketContext,context_id)
                if row is None:raise HTTPException(404,'Unknown context')
                if row.lookup_policy!=POLICY:raise HTTPException(409,'Context requires causal recomputation')
                source=s.get(ContextInput,context_id)
                return SimpleNamespace(payload=copy.deepcopy(source.payload),exact_payload=source.exact_payload,
                    subject=source.subject,jetstream_metadata=copy.deepcopy(source.jetstream_metadata),received_at=source.received_at)
        source=await asyncio.to_thread(read_input)
        try:return await asyncio.wait_for(app.state.decisions.build(context_id,source,basis,additional_input_available_at.isoformat() if additional_input_available_at else None),timeout=30)
        except DecisionUnavailable as exc:raise HTTPException(409,str(exc)) from None
        except Exception as exc:
            log('decision_projection_unavailable',error_type=type(exc).__name__)
            raise HTTPException(503,'Decision provenance or causal market data source unavailable; no fallback to event/publication time') from None
    @app.get('/contexts/{context_id}/outcomes')
    async def outcomes(context_id:str,decision_at:datetime):
        if decision_at.tzinfo is None:raise HTTPException(422,'Timezone required')
        def read_context():
            with app.state.sessions() as s:
                row=s.get(MarketContext,context_id)
                if row is None:raise HTTPException(404,'Unknown context')
                return copy.deepcopy(row.payload)
        value=await asyncio.to_thread(read_context)
        try:return await asyncio.wait_for(outcome_view(value,decision_at.isoformat(),app.state.market,settings),timeout=30)
        except Exception as exc:
            log('outcome_projection_unavailable',error_type=type(exc).__name__)
            raise HTTPException(503,'Outcome market data source unavailable') from None
    @app.get('/contexts/{context_id}/revisions')
    def revisions(context_id:str,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as s:
            if s.get(MarketContext,context_id) is None:raise HTTPException(404,'Unknown context')
            return [r.payload for r in s.scalars(select(ContextRevision).where(ContextRevision.context_id==context_id).order_by(ContextRevision.revision).offset(offset).limit(limit))]
    @app.get('/events/{event_id}/contexts')
    def contexts(event_id:str,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as s:return [r.payload for r in s.scalars(select(MarketContext).where(MarketContext.event_id==event_id).order_by(MarketContext.event_revision).offset(offset).limit(limit))]
    return app
app=create_app()
