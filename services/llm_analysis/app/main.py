import asyncio
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import select,text,func
from app.config import Settings
from app.storage.database import make_database
from app.storage.repository import Repository
from app.storage.models import AnalysisJob,AnalysisRun
from app.storage.contract import Contract
from app.provider import OpenAIProvider
from app.intelligence import IntelligenceClient,PROMPT
from app.worker import DecisionClient,Worker
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.consumers.input import InputConsumer
from app.logging import configure_logging,log
class Enqueue(BaseModel):
    model_config=ConfigDict(extra='forbid')
    event_id:UUID
    event_revision:int=Field(ge=1)
    context_id:UUID
    basis:Literal['live','research_hypothetical']='live'
    run_key:UUID|None=None
    intelligence_id:UUID|None=None
class Research(BaseModel):
    model_config=ConfigDict(extra='forbid')
    run_key:UUID
    model:str=Field(min_length=1,max_length=100)
    prompt_version:str='btc_event_analysis_v1'
    reasoning_effort:Literal['low','medium','high','xhigh','max','ultra']='medium'
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
        configure_logging();engine,sessions=make_database(settings.database_url.get_secret_value());repo=Repository(sessions,settings)
        bus=JetStreamBus(settings.nats_url.get_secret_value());decisions=DecisionClient(settings.context_url)
        provider=OpenAIProvider(settings.api_key.get_secret_value(),settings.request_timeout_seconds)
        intelligence=IntelligenceClient(settings.intelligence_url)
        worker=Worker(repo,decisions,provider,settings,intelligence);publisher=OutboxPublisher(sessions,bus,Contract(settings.contracts_dir/'analysis/v1.schema.json'))
        app.state.repo=repo;app.state.sessions=sessions;app.state.engine=engine;app.state.bus=bus;app.state.tasks=[]
        if settings.workers_enabled:
            operations=[('analysis',worker.run_once),('outbox',publisher.run_once)]
            if settings.auto_live_enabled:operations.append(('input',InputConsumer(bus,repo,settings.durable_name).run_once))
            app.state.tasks=[asyncio.create_task(supervise(name,fn)) for name,fn in operations]
        try:yield
        finally:
            for task in app.state.tasks:task.cancel()
            await asyncio.gather(*app.state.tasks,return_exceptions=True)
            await decisions.close();await intelligence.close();await provider.close();await bus.close();await asyncio.to_thread(engine.dispose)
    app=FastAPI(title='LLM Analysis Service',lifespan=lifespan)
    @app.get('/health')
    def health():return {'status':'alive'}
    @app.get('/ready')
    async def ready():
        def db():
            try:
                with app.state.engine.connect() as c:return c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='a40001'
            except Exception:return False
        checks={'database':await asyncio.to_thread(db),'jetstream':await app.state.bus.healthcheck(),'workers':all(not t.done() for t in app.state.tasks),'provider_configured':bool(settings.api_key.get_secret_value())}
        return JSONResponse(checks,status_code=200 if all(checks.values()) else 503)
    @app.get('/stats')
    def stats():return app.state.repo.stats()
    @app.post('/analyses',status_code=202)
    def enqueue(body:Enqueue):
        if body.basis=='research_hypothetical' and body.run_key is None:raise HTTPException(422,'research requires explicit run_key')
        if body.basis=='live' and body.run_key is not None:raise HTTPException(422,'live identity cannot use a run_key; use research rerun endpoint')
        configuration=None
        if body.intelligence_id:
            configuration={**settings.configuration(),'prompt_version':PROMPT,'intelligence_id':str(body.intelligence_id)}
        key=app.state.repo.enqueue({'event_id':str(body.event_id),'event_revision':body.event_revision},str(body.context_id),body.basis,str(body.run_key) if body.run_key else 'live',configuration)
        return {'analysis_id':key}
    @app.get('/analyses')
    def analysis_list(offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        from datetime import timezone
        with app.state.sessions() as session:
            total=session.scalar(select(func.count()).select_from(AnalysisJob))
            rows=list(session.scalars(select(AnalysisJob).order_by(AnalysisJob.created_at.desc(),AnalysisJob.id).offset(offset).limit(limit)))
            latest={}
            if rows:
                for run in session.scalars(select(AnalysisRun).where(AnalysisRun.analysis_id.in_([r.id for r in rows])).order_by(AnalysisRun.attempt.desc())):
                    latest.setdefault(run.analysis_id,run.response_audit or {})
            return {'items':[{'analysis_id':r.id,'event_id':r.event_id,'event_revision':r.event_revision,
                'analysis_status':r.status,'basis':r.basis,'configuration':r.configuration,'error':r.error,
                'created_at':r.created_at.replace(tzinfo=timezone.utc).isoformat(),
                'latency_ms':latest.get(r.id,{}).get('latency_ms'),'usage':latest.get(r.id,{}).get('usage')}
                for r in rows],'total':total,'offset':offset,'limit':limit}
    @app.get('/analyses/{analysis_id}')
    def analysis(analysis_id:UUID):
        value=app.state.repo.view(str(analysis_id))
        if value is None:raise HTTPException(404,'Unknown analysis')
        return value
    @app.get('/analyses/{analysis_id}/input')
    def analysis_input(analysis_id:UUID):
        value=app.state.repo.view(str(analysis_id))
        if value is None:raise HTTPException(404,'Unknown analysis')
        if value['input_hash'] is None:raise HTTPException(409,'No permitted immutable input')
        row=app.state.repo.input(value['input_hash'])
        return {'input_hash':row.id,'canonical_json':row.canonical_json}
    @app.post('/analyses/{analysis_id}/research',status_code=202)
    def research(analysis_id:UUID,body:Research):
        parent=app.state.repo.view(str(analysis_id))
        if parent is None:raise HTTPException(404,'Unknown analysis')
        if parent['input_hash'] is None:raise HTTPException(409,'No immutable input to rerun')
        config={**parent['configuration'],'model':body.model,'prompt_version':body.prompt_version,'reasoning_effort':body.reasoning_effort}
        if (config['prompt_version']==PROMPT)!=bool(config.get('intelligence_id')):raise HTTPException(422,'Intelligence prompt requires its pinned intelligence input')
        try:key=app.state.repo.enqueue({'event_id':parent['event_id'],'event_revision':parent['event_revision']},parent['context_id'],parent['basis'],str(body.run_key),config,parent['input_hash'])
        except ValueError:raise HTTPException(422,'Unknown or modified prompt version') from None
        return {'analysis_id':key,'input_hash':parent['input_hash']}
    @app.get('/events/{event_id}/analyses')
    def analyses(event_id:UUID,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        with app.state.sessions() as s:
            rows=s.scalars(select(AnalysisJob).where(AnalysisJob.event_id==str(event_id)).order_by(AnalysisJob.created_at,AnalysisJob.id).offset(offset).limit(limit)).all()
            return [{'analysis_id':r.id,'analysis_status':r.status,'input_hash':r.input_id,'configuration':r.configuration} for r in rows]
    return app
app=create_app()
