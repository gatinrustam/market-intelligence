import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
from uuid import uuid4
import httpx
import pytest
from nats.js.api import StreamConfig,StorageType
from nats.js.errors import NotFoundError
from pydantic import SecretStr
from app.consumers.input import InputConsumer
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.storage.models import EventInput,EventJob,Event,EventRevision,OutboxEvent,DeadInput
from app.main import create_app
from tests.test_integration import count,rows,accept,different

pytestmark=pytest.mark.integration


def message(raw,ack):
 return SimpleNamespace(data=raw,subject='document.enriched.v1',ack_sync=ack,nak=AsyncMock(),
  metadata=SimpleNamespace(stream='DOCUMENT_ENRICHED',consumer='test',num_delivered=1,sequence=SimpleNamespace(stream=1,consumer=1)))


async def test_ack_after_commit(repository,document):
 raw=json.dumps(document,indent=2).encode()
 async def ack(**kwargs):
  assert rows(repository,EventInput)[0].exact_payload==raw
  assert count(repository,EventJob)==1 and count(repository,Event)==0
 msg=message(raw,AsyncMock(side_effect=ack))
 consumer=InputConsumer(None,repository,'test')
 await consumer.handle(msg);await consumer.handle(msg)
 assert msg.ack_sync.await_count==2
 msg.nak.assert_not_awaited()


async def test_db_failure_nak(document):
 repo=Mock();repo.accept.side_effect=ConnectionError()
 msg=message(json.dumps(document).encode(),AsyncMock())
 await InputConsumer(None,repo,'test').handle(msg)
 msg.ack_sync.assert_not_awaited();msg.nak.assert_awaited_once_with(delay=5)


async def test_real_nats_durable_redelivery_outputs(repository,worker,document,output_contract):
 url=os.getenv('TEST_NATS_URL')
 if not url: pytest.skip('TEST_NATS_URL required')
 assert 'nats-test:' in url
 bus=JetStreamBus(url);durable='EVENT_TEST_'+uuid4().hex
 try:
  await bus.connect()
  try: await bus.js.stream_info('DOCUMENT_ENRICHED')
  except NotFoundError:
   await bus.js.add_stream(config=StreamConfig(name='DOCUMENT_ENRICHED',subjects=['document.enriched.v1'],storage=StorageType.FILE))
  await bus.js.purge_stream('DOCUMENT_ENRICHED')
  before=(await bus.js.stream_info('DOCUMENT_ENRICHED')).config.as_dict()
  consumer=InputConsumer(bus,repository,durable)
  await consumer.subscribe()
  document['content']['title']='FOMC statement April 29, 2026'
  raw=json.dumps(document,indent=3).encode()
  await bus.js.publish('document.enriched.v1',raw)
  msg=(await consumer.subscription.fetch(batch=1,timeout=2))[0]
  repository.accept(msg.data,msg.metadata.sequence.stream)
  # Simulate process stopping after commit, before ACK, then server redelivery.
  await msg.nak()
  resumed=InputConsumer(bus,repository,durable)
  await resumed.run_once()
  assert count(repository,EventJob)==1
  await bus.js.publish('document.enriched.v1',b'{malformed')
  await bus.js.publish('document.enriched.v1',raw)
  await consumer.run_once()
  assert count(repository,DeadInput)==1
  assert (await bus.js.consumer_info('DOCUMENT_ENRICHED',durable)).num_ack_pending==0
  await worker.run_once()
  supporting=different(document)
  await bus.js.publish('document.enriched.v1',json.dumps(supporting).encode())
  await consumer.run_once();await worker.run_once()
  publisher=OutboxPublisher(repository.sessions,bus,output_contract)
  while await publisher.run_once(): pass
  outbox=sorted(rows(repository,OutboxEvent),key=lambda r:r.revision)
  assert len(outbox)==2 and count(repository,Event)==1 and count(repository,EventRevision)==2
  for row in outbox:
   assert row.status=='published'
   ack=await bus.js.publish(row.subject,json.dumps(row.payload).encode(),headers={'Nats-Msg-Id':row.message_id})
   assert ack.duplicate
   stored=await bus.js.get_msg('EVENTS',seq=ack.seq)
   assert stored.subject==row.subject and json.loads(stored.data)==row.payload
   output_contract.validate(json.loads(stored.data))
  assert (await bus.js.stream_info('DOCUMENT_ENRICHED')).config.as_dict()==before
 finally:
  if bus.js: await bus.js.delete_consumer('DOCUMENT_ENRICHED',durable)
  await bus.close()


async def test_api(repository,worker,document,settings):
 accept(repository,document);await worker.run_once()
 app=create_app(settings.model_copy(update={'database_url':SecretStr(os.environ['TEST_DATABASE_URL'])}))
 async with app.router.lifespan_context(app):
  app.state.bus.healthcheck=AsyncMock(return_value=True)
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
   assert (await client.get('/health')).status_code==200
   assert (await client.get('/ready')).status_code==200
   app.state.bus.healthcheck.return_value=False
   assert (await client.get('/ready')).status_code==503
   stats=(await client.get('/stats')).json()
   assert stats['events_total']==1 and stats['documents_processed']==1
   event=rows(repository,Event)[0]
   assert (await client.get('/events/'+event.id)).json()==event.payload
   assert len((await client.get('/events/'+event.id+'/revisions')).json())==1
   assert (await client.get('/documents/'+document['document_id']+'/extraction')).json()['runs'][0]['result_json']['outcome']=='event_created'
   assert (await client.get('/correlation-suggestions')).json()==[]
   for path in ['/events/missing','/events/missing/revisions','/documents/missing/extraction']:
    assert (await client.get(path)).status_code==404
   assert (await client.get('/correlation-suggestions?limit=1000')).status_code==422
