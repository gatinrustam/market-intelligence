"""Real isolated broker outage with two context revisions and a fresh recovery process."""
import asyncio,json,os,sys
from pathlib import Path
from datetime import timedelta
from sqlalchemy import select,func
from app.config import Settings
from app.storage.contract import CanonicalContract,ContextContract
from app.storage.database import make_database
from app.storage.models import Base,OutboxEvent,ContextRevision,utcnow
from app.storage.repository import Repository,identity
from app.worker import ContextWorker
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from tests.test_context import exact,accept,Market,T,force_due

async def main():
    url=os.environ['TEST_DATABASE_URL'];nats_url=os.environ['TEST_NATS_URL'];assert '/market_context_test?' in url and 'nats-test' in nats_url
    engine,sessions=make_database(url);settings=Settings();contract=ContextContract(settings.output_schema_path)
    repo=Repository(sessions,CanonicalContract(settings.input_schema_path),contract,settings);bus=JetStreamBus(nats_url);publisher=OutboxPublisher(sessions,bus,contract)
    try:
        if sys.argv[1]=='offline':
            Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
            event=exact(json.loads(Path('tests/canonical.json').read_text()));accept(repo,event)
            worker=ContextWorker(repo,Market('realtime'),settings,clock=lambda:T);await worker.run_once()
            publishing=asyncio.create_task(publisher.run_once())
            force_due(sessions,identity(event));worker.clock=lambda:T+timedelta(seconds=61);await worker.run_once()
            await publishing
            with sessions() as s:
                assert s.scalar(select(func.count()).select_from(ContextRevision))==2
                assert s.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status=='pending'))==2
            print(json.dumps({'broker':'offline','context_revisions_saved':2,'outbox_pending':2,'scheduler_continued':True}))
        else:
            await bus.connect();await bus.js.purge_stream('MARKET_CONTEXTS')
            with sessions.begin() as s:
                for row in s.scalars(select(OutboxEvent)):row.next_attempt_at=utcnow()
            while await publisher.run_once():pass
            info=await bus.js.stream_info('MARKET_CONTEXTS');assert info.state.messages==2
            seen=[]
            with sessions() as s:
                for seq in range(info.state.first_seq,info.state.last_seq+1):
                    raw=await bus.js.get_msg('MARKET_CONTEXTS',seq=seq);p=json.loads(raw.data);contract.validate(p)
                    assert s.get(ContextRevision,(p['context_id'],p['revision'])).payload==p
                    seen.append({'revision':p['revision'],'subject':raw.subject})
                assert [x['revision'] for x in seen]==[1,2]
                assert all(r.status=='published' for r in s.scalars(select(OutboxEvent)))
            print(json.dumps({'broker':'recovered','fresh_process':True,'published':seen,'outbox_pending':0}))
    finally:await bus.close();engine.dispose()
if __name__=='__main__':asyncio.run(main())
