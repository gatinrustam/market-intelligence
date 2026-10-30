"""Real stopped broker probe, isolated events_test DB and nats-test only."""
import asyncio,json,os,sys
from pathlib import Path
from uuid import uuid4
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.engine import make_url
from app.config import Settings
from app.taxonomy.configuration import load_bundle
from app.extraction.rules import RuleBasedEventExtractor
from app.correlation.core import EventCore
from app.storage.contract import Contract,CanonicalContract
from app.storage.database import make_database
from app.storage.models import Event,EventRevision,OutboxEvent,utcnow
from app.storage.repository import Repository
from app.workers.process import EventWorker
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher


async def main():
 url,nats_url=os.environ['TEST_DATABASE_URL'],os.environ['TEST_NATS_URL']
 assert make_url(url).database=='events_test' and 'nats-test:' in nats_url
 engine,sessions=make_database(url)
 settings=Settings(workers_enabled=False);bundle=load_bundle(settings.config_dir)
 contract=CanonicalContract(settings.output_schema_path)
 repo=Repository(sessions,Contract(settings.input_schema_path),settings)
 worker=EventWorker(repo,RuleBasedEventExtractor(bundle),EventCore(repo,contract,bundle),bundle,settings)
 bus=JetStreamBus(nats_url);publisher=OutboxPublisher(sessions,bus,contract)
 try:
  if sys.argv[1]=='offline':
   doc=json.loads(Path('tests/fixtures/fed.json').read_text())
   doc['document_id']=str(uuid4());doc['message_id']=str(uuid4())
   doc['content']['title']='Broker outage event probe'
   repo.accept(json.dumps(doc).encode(),0)
   while await worker.run_once(): pass
   while await publisher.run_once(): pass
   with sessions() as s:
    rows=list(s.scalars(select(OutboxEvent).join(Event).where(Event.payload['content']['canonical_title'].as_string()=='Broker outage event probe')))
    assert rows and all(r.status=='pending' and r.attempts>=1 for r in rows)
    assert all(s.get(EventRevision,(r.event_id,r.revision)) for r in rows)
    print('PASS: real stopped NATS, canonical event/revision committed, outbox pending:',[r.message_id for r in rows])
  else:
   with sessions.begin() as s:
    for row in s.scalars(select(OutboxEvent).where(OutboxEvent.status=='pending')):
     row.next_attempt_at=utcnow()-timedelta(seconds=1)
   while await publisher.run_once(): pass
   await bus.connect()
   info=await bus.js.stream_info('EVENTS');found={}
   for seq in range(info.state.first_seq,info.state.last_seq+1):
    msg=await bus.js.get_msg('EVENTS',seq=seq);payload=json.loads(msg.data);contract.validate(payload)
    found[payload['message_id']]=payload
   with sessions() as s:
    rows=list(s.scalars(select(OutboxEvent).join(Event).where(Event.payload['content']['canonical_title'].as_string()=='Broker outage event probe')))
    assert rows and all(r.status=='published' and r.attempts>=2 and found[r.message_id]==r.payload for r in rows)
    assert all(s.get(Event,r.event_id).revision==r.revision==1 for r in rows)
   print('PASS: fresh publisher process recovers same message_id/payload with no new revision')
 finally:
  await bus.close();engine.dispose()

asyncio.run(main())
