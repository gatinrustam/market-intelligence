"""One explicit EN/RU research run using unchanged local model revisions.
Consumes existing real DI inputs; no synthetic document injection or LLM APIs.
"""
import asyncio,json,time,sys
from app.config import Settings
from app.domain import load_configuration,iso
from app.runtime import LocalModels
from app.storage.database import make_database
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.worker import InputClient,Worker
from app.logging import configure_logging
async def main():
 configure_logging();settings=Settings();c=load_configuration(settings,sys.argv[1] if len(sys.argv)>1 else 'policy.v1.json');e,ss=make_database(settings.database_url.get_secret_value());repo=Repository(ss,settings,c);repo.register()
 bus=JetStreamBus(settings.nats_url.get_secret_value());await bus.connect();info=await bus.js.stream_info('DOCUMENT_INTELLIGENCE')
 for seq in range(info.state.first_seq,info.state.last_seq+1):
  msg=await bus.js.get_msg('DOCUMENT_INTELLIGENCE',seq=seq);repo.accept(msg.data,seq,msg.subject,{'stream':'DOCUMENT_INTELLIGENCE','published_at':iso(msg.time),'mode':'explicit_precision_research'})
 models=LocalModels(settings,c);start=time.monotonic();await asyncio.to_thread(models.load)
 if models.encoder is None or models.gliner is None:raise RuntimeError(str(models.warnings))
 print(json.dumps({'model_load_seconds':time.monotonic()-start,'version':c['version']}),flush=True)
 client=InputClient(settings);worker=Worker(repo,client,models);publisher=OutboxPublisher(ss,bus,repo.output_contract)
 while await worker.run_once():
  while await publisher.run_once():pass
  print(json.dumps(repo.stats()),flush=True)
 while await publisher.run_once():pass
 final=repo.stats();print(json.dumps({'final':final}),flush=True)
 if final['runs'].get('pending') or final['runs'].get('failed'):raise RuntimeError('Research run incomplete')
 await bus.close();await client.close();e.dispose()
asyncio.run(main())
