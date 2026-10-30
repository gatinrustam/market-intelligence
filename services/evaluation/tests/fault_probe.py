"""Runs against isolated evaluation_test and nats-test only."""
import asyncio,json,os,sys
from sqlalchemy import select,func
from app.config import Settings
from app.storage.database import make_database
from app.storage.models import Base,Evaluation,OutboxEvent,utcnow
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.worker import Worker
from tests.conftest import package as package_fixture,analysis as analysis_fixture
from tests.test_evaluation import accept,Outcomes

async def main():
    url=os.environ['TEST_DATABASE_URL'];nats_url=os.environ['TEST_NATS_URL']
    assert '/evaluation_test?' in url and 'nats-test' in nats_url
    engine,sessions=make_database(url);settings=Settings(fixtures_enabled=True);repo=Repository(sessions,settings)
    bus=JetStreamBus(nats_url,fixtures=True);publisher=OutboxPublisher(sessions,bus,repo.output_contract)
    try:
        if sys.argv[1]=='offline':
            Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
            package=package_fixture.__wrapped__();analysis=analysis_fixture.__wrapped__(package)
            accept(repo,analysis,package);up=Outcomes(analysis,package);up.ready={60,300,900,3600}
            await Worker(repo,up,settings).run_once();assert await publisher.run_once()
            with sessions() as s:
                assert s.scalar(select(OutboxEvent)).status=='pending'
                assert s.scalar(select(func.count()).select_from(Evaluation))==1
            print(json.dumps({'broker':'offline','evaluation_saved':1,'outbox_pending':1}))
        else:
            await bus.connect();await bus.js.purge_stream('EVALUATIONS')
            with sessions.begin() as s:
                for row in s.scalars(select(OutboxEvent)):row.next_attempt_at=utcnow()
            assert await publisher.run_once();assert not await publisher.run_once()
            info=await bus.js.stream_info('EVALUATIONS');raw=await bus.js.get_msg('EVALUATIONS',seq=info.state.last_seq)
            value=json.loads(raw.data);repo.output_contract.validate(value)
            with sessions() as s:assert s.get(Evaluation,value['evaluation_id']).payload==value
            await bus.publish(value['message_id'],value,raw.subject)
            assert (await bus.js.stream_info('EVALUATIONS')).state.messages==1
            print(json.dumps({'broker':'recovered','fresh_process':True,'published':1,'duplicate_suppressed':True}))
    finally:await bus.close();engine.dispose()
if __name__=='__main__':asyncio.run(main())
