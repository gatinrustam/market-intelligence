import asyncio,json,os,sys
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from app.config import Settings
from app.domain import load_rules,canonical,identity
from app.storage.database import make_database
from app.storage.models import Base,OutboxEvent,utcnow
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from tests.test_intelligence import accept,worker
async def main():
    url=os.environ['TEST_DATABASE_URL'];broker=os.environ['TEST_NATS_URL'];assert '/event_intelligence_test?' in url and 'nats-test' in broker
    engine,sessions=make_database(url);settings=Settings();repo=Repository(sessions,settings,load_rules(settings.rules_path));bus=JetStreamBus(broker);pub=OutboxPublisher(sessions,bus,repo.output_contract)
    try:
        if sys.argv[1]=='offline':
            Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
            snapshot=json.loads(Path('tests/examples.json').read_text())['Fed'];snapshot['event']['event']['id']=str(uuid4());accept(repo,snapshot);await worker(repo,snapshot).run_once();assert await pub.run_once()
            with sessions() as s:assert s.scalar(select(OutboxEvent)).status=='pending'
            print(json.dumps({'broker':'offline','intelligence_saved':1,'outbox_pending':1}))
        else:
            await bus.connect();await bus.js.purge_stream('EVENT_INTELLIGENCE')
            with sessions.begin() as s:
                for row in s.scalars(select(OutboxEvent)):row.next_attempt_at=utcnow()
            assert await pub.run_once();assert not await pub.run_once()
            info=await bus.js.stream_info('EVENT_INTELLIGENCE');msg=await bus.js.get_msg('EVENT_INTELLIGENCE',seq=info.state.last_seq);value=json.loads(msg.data)
            assert value==repo.view(value['intelligence_id']);repo.output_contract.validate(value)
            await bus.publish(value['message_id'],value,msg.subject)
            assert (await bus.js.stream_info('EVENT_INTELLIGENCE')).state.messages==1
            print(json.dumps({'broker':'recovered','fresh_process':True,'published':1,'duplicate_suppressed':True}))
    finally:await bus.close();engine.dispose()
if __name__=='__main__':asyncio.run(main())
