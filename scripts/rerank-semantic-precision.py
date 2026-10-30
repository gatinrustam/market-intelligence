"""Append a new precision revision using frozen local observations, no model calls.
The initial research inference may still be completing. Old results are untouched.
"""
import asyncio,copy,json,time
from sqlalchemy import select,func
from app.config import Settings
from app.domain import load_configuration,build_result
from app.storage.database import make_database
from app.storage.models import SemanticRun,SemanticResult,SemanticInput
from app.storage.repository import Repository
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
async def main():
 settings=Settings();c=load_configuration(settings);engine,sessions=make_database(settings.database_url.get_secret_value());repo=Repository(sessions,settings,c);repo.register()
 bus=JetStreamBus(settings.nats_url.get_secret_value());await bus.connect();publisher=OutboxPublisher(sessions,bus,repo.output_contract);seen=set()
 while True:
  with sessions() as db:
   ids=list(db.scalars(select(SemanticResult.id).where(SemanticResult.ruleset_version=='semantic_precision_v1')))
   expected=db.scalar(select(func.count()).select_from(SemanticRun).where(SemanticRun.ruleset_version=='semantic_precision_v1'))
  for source_id in ids:
   if source_id in seen:continue
   with sessions() as db:
    source=db.get(SemanticRun,source_id);di=db.get(SemanticInput,source.input_id).payload;snapshot=copy.deepcopy(source.snapshot)
   repo.accept(json.dumps(di,ensure_ascii=False).encode(),None,'document.intelligence.v1',{'mode':'frozen_observation_rerank','source_semantic_id':source_id})
   claimed=repo.claim()
   if claimed:
    run,accepted_di=claimed
    if accepted_di['intelligence_id']!=di['intelligence_id']:raise RuntimeError('Unexpected pending run; rerun in an isolated revision')
    snapshot['inference_reused_from']=source_id;observed=snapshot['observed'];start=time.monotonic()
    result=build_result(di,snapshot,c,observed)
    observed['reranking_seconds']=time.monotonic()-start;result['reranking']['latency_seconds']=observed['reranking_seconds']
    if result['reranking']['status']!='complete':raise RuntimeError('Reranking failed')
    if not repo.finish(run,snapshot,result):raise RuntimeError('Lost revision lease')
   seen.add(source_id)
   while await publisher.run_once():pass
   print(json.dumps({'revision':c['version'],'completed':len(seen),'expected':expected}),flush=True)
  if len(seen)==expected:break
  await asyncio.sleep(5)
 print(json.dumps({'final':repo.stats()}),flush=True)
 await bus.close();engine.dispose()
asyncio.run(main())
