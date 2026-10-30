import asyncio,json,os,sys
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from app.config import Settings
from app.domain import load_configuration,canonical,identity
from app.storage.database import make_database
from app.storage.models import Base,OutboxEvent,utcnow
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from tests.test_storage import accept
from app.worker import Worker
from app.pipeline import Pipeline
async def main():
    url=os.environ['TEST_DATABASE_URL'];broker=os.environ['TEST_NATS_URL'];assert '/document_intelligence_test?' in url and 'nats-test' in broker
    engine,sessions=make_database(url);settings=Settings();repo=Repository(sessions,settings,load_configuration(settings));bus=JetStreamBus(broker);pub=OutboxPublisher(sessions,bus,repo.output_contract)
    try:
        if sys.argv[1]=='offline':
            Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
            document=json.loads(Path('tests/document.json').read_text());document['document_id']=str(uuid4());accept(repo,document);await Worker(repo,Pipeline(repo.configuration)).run_once();assert await pub.run_once()
            with sessions() as s:assert s.scalar(select(OutboxEvent)).status=='pending'
            print(json.dumps({'broker':'offline','intelligence_saved':1,'outbox_pending':1}))
        else:
            await bus.connect();await bus.js.purge_stream('DOCUMENT_INTELLIGENCE')
            with sessions.begin() as s:
                for row in s.scalars(select(OutboxEvent)):row.next_attempt_at=utcnow()
            assert await pub.run_once();assert not await pub.run_once()
            info=await bus.js.stream_info('DOCUMENT_INTELLIGENCE');msg=await bus.js.get_msg('DOCUMENT_INTELLIGENCE',seq=info.state.last_seq);value=json.loads(msg.data)
            assert value==repo.view(value['intelligence_id']);repo.output_contract.validate(value)
            await bus.publish(value['message_id'],value,msg.subject)
            assert (await bus.js.stream_info('DOCUMENT_INTELLIGENCE')).state.messages==1
            print(json.dumps({'broker':'recovered','fresh_process':True,'published':1,'duplicate_suppressed':True}))
    finally:await bus.close();engine.dispose()
if __name__=='__main__':asyncio.run(main())
