import asyncio,secrets
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import FastAPI,HTTPException,Query,Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,text
from app.config import Settings
from app.domain import load_configuration,digest,iso
from app.storage.database import make_database
from app.schema import LabelRequest
from sqlalchemy.exc import IntegrityError
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.consumers.input import InputConsumer
from app.worker import MetadataClient,Worker
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
        bus=JetStreamBus(settings.nats_url.get_secret_value());events=MetadataClient(settings)
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
    app=FastAPI(title='Article Router',lifespan=lifespan)
    @app.get('/health')
    def health():return {'status':'alive'}
    @app.get('/ready')
    async def ready():
        def db():
            try:
                with app.state.engine.connect() as c:return c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='di2001'
            except Exception:return False
        checks={'database':await asyncio.to_thread(db),'jetstream':await app.state.bus.healthcheck(),'workers':all(not t.done() for t in app.state.tasks)}
        return JSONResponse(checks,status_code=200 if all(checks.values()) else 503)
    @app.get('/stats')
    def stats():return app.state.repo.stats()
    @app.get('/articles')
    def articles(offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100)):
        return app.state.repo.articles(offset,limit)
    @app.get('/articles/{key}')
    def article(key:UUID):
        result=app.state.repo.detail(str(key))
        if result is None:raise HTTPException(404,'Unknown article')
        return result
    @app.get('/documents/{document_id}/reviews')
    def document_reviews(document_id:UUID):
        from app.storage.models import RoutingResult,RoutingRun,HumanLabel
        with app.state.sessions() as s:
            return [{'routing_id':r.id,'intelligence_id':r.payload['document']['intelligence_id'],'ruleset_version':r.ruleset_version,'reviewed_v1_types':sorted({e['taxonomy']['event_type'] for e in s.get(RoutingRun,r.id).snapshot['events']}),
                'labels':[{'revision':l.revision,'created_at':l.created_at.isoformat()+'Z',**l.payload} for l in s.scalars(select(HumanLabel).where(HumanLabel.routing_id==r.id).order_by(HumanLabel.revision))]}
                for r in s.scalars(select(RoutingResult).where(RoutingResult.document_id==str(document_id)).order_by(RoutingResult.created_at,RoutingResult.id))]
    @app.get('/routing/{key}')
    def routing(key:UUID):
        result=app.state.repo.view(str(key))
        if result is None:raise HTTPException(404,'Unknown routing')
        return result
    @app.post('/reviews/{key}/labels')
    def label(key:UUID,body:LabelRequest,authorization:str|None=Header(None)):
        token=settings.review_token.get_secret_value()
        if not token:raise HTTPException(503,'Review writes are not configured')
        if not authorization or not secrets.compare_digest(authorization,'Bearer '+token):raise HTTPException(401,'Unauthorized')
        try:return app.state.repo.label(str(key),body)
        except LookupError as exc:raise HTTPException(404,str(exc))
        except (ValueError,IntegrityError) as exc:raise HTTPException(409,'Review conflict; reload before retrying')
    return app
app=create_app()
