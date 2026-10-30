"""Explicit local research run: retained DI-1 stream -> immutable DI-5 + 10 RU fixtures.
Run as the sole semantic worker. Uses existing inputs only, never invokes a paid API.
Usage: python research-article-semantic.py /fixtures/ru-snapshots.json /reports/ru-results.jsonl
"""
import asyncio,json,sys,time
from app.logging import configure_logging
configure_logging()
from app.config import Settings
from app.domain import load_configuration,build_result,iso
from app.runtime import LocalModels
from app.storage.database import make_database
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.worker import InputClient,Worker
async def main():
 settings=Settings();configuration=load_configuration(settings)
 engine,sessions=make_database(settings.database_url.get_secret_value());repo=Repository(sessions,settings,configuration);repo.register()
 bus=JetStreamBus(settings.nats_url.get_secret_value());await bus.connect()
 info=await bus.js.stream_info('DOCUMENT_INTELLIGENCE');accepted=[]
 for sequence in range(info.state.first_seq,info.state.last_seq+1):
  message=await bus.js.get_msg('DOCUMENT_INTELLIGENCE',seq=sequence)
  accepted.append(repo.accept(message.data,sequence,message.subject,{'stream':'DOCUMENT_INTELLIGENCE','published_at':iso(message.time),'mode':'explicit_local_research'}))
 print(json.dumps({'accepted_inputs':len(accepted),'states':{s:accepted.count(s) for s in set(accepted)}}),flush=True)
 client=InputClient(settings);models=LocalModels(settings,configuration);worker=Worker(repo,client,models);publisher=OutboxPublisher(sessions,bus,repo.output_contract)
 preflight=time.monotonic();await asyncio.to_thread(models.load)
 if models.encoder is None or models.gliner is None:raise RuntimeError('Research preflight failed: '+str(models.warnings))
 print(json.dumps({'model_preflight_seconds':time.monotonic()-preflight,'both_models_available':True}),flush=True)
 while await worker.run_once():
  await publisher.run_once();print(json.dumps(repo.stats()),flush=True)
 while await publisher.run_once():pass
 if len(sys.argv)>1:
  with open(sys.argv[2],'w') as output:
   for snapshot in json.load(open(sys.argv[1])):
    observed=await asyncio.to_thread(models.analyze,snapshot['intelligence'],snapshot['document']['content']['body'])
    result=build_result(snapshot['intelligence'],snapshot,configuration,observed)
    output.write(json.dumps({'fixture':snapshot['fixture'],'result':result,'observed':observed},ensure_ascii=False)+'\n');output.flush()
    print(json.dumps({'russian_fixture':snapshot['fixture']['id'],'status':result['status']}),flush=True)
 stats=repo.stats();print(json.dumps({'final':stats}),flush=True)
 if stats['runs'].get('pending',0) or stats['runs'].get('failed',0):raise RuntimeError('Research corpus incomplete; inspect run errors before reporting success')
 await client.close();await bus.close();engine.dispose()
asyncio.run(main())
