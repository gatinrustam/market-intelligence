"""Append corrected DI research revisions using identical frozen model observations.

Only same document/body/language/sentence boundaries AND identical semantic
configuration may reuse observations. Existing results are never updated.
This is the same frozen-observation research workflow as DI-5.1 re-ranking.
"""
import asyncio,copy,json,time
from pathlib import Path
from datetime import timedelta
from sqlalchemy import select
from app.config import Settings
from app.domain import load_configuration,build_result,digest,identity
from app.storage.database import make_database
from app.storage.models import SemanticInput,SemanticRun,SemanticResult,utcnow,new_id
from app.storage.repository import Repository
from app.worker import InputClient

async def main():
    settings=Settings();c=load_configuration(settings);engine,sessions=make_database(settings.database_url.get_secret_value())
    repo=Repository(sessions,settings,c);client=InputClient(settings);count=0
    source_messages=[x['message_id'] for x in json.loads(Path('/tmp/crypto-raw-items.json').read_text())]
    with sessions() as db:
        query=select(SemanticInput.payload).where(SemanticInput.payload['extraction']['fact_ruleset_version'].as_string()=='crypto_v1_1',SemanticInput.payload['document']['source_message_id'].as_string().in_(source_messages))
        inputs=list(db.scalars(query))
    for di in inputs:
        key=identity(di,c)
        with sessions() as db:
            target=db.get(SemanticRun,key)
            if target is None or target.status!='pending' or target.lease_token:continue
            candidates=list(db.scalars(select(SemanticRun).join(SemanticResult,SemanticResult.id==SemanticRun.id).where(SemanticResult.document_id==di['document']['document_id'],SemanticRun.ruleset_version==c['version'])))
            reusable=None
            for old in candidates:
                snapshot=old.snapshot;prior=snapshot['intelligence']
                if snapshot['document']['source']['id'] not in c['official_sources'] or not snapshot['document']['classification']['categories'] or 'crypto' not in snapshot['document']['classification']['categories']:continue
                if digest(old.configuration)!=digest(c) or prior['document']['body_hash']!=di['document']['body_hash'] or prior['sentences']!=di['sentences'] or prior['language']!=di['language']:continue
                if snapshot['observed']['embedding_available'] and snapshot['observed']['gliner_available']:
                    reusable=(old.id,copy.deepcopy(snapshot['observed']));break
        if reusable is None:continue
        old_id,observed=reusable
        snapshot=await client.snapshot(di)
        snapshot['observed']=observed;snapshot['inference_reused_from']=old_id
        snapshot['inference_reuse_checks']=['same_document','same_body_hash','same_sentences','same_language','identical_semantic_configuration']
        baseline=repo.ensure_baseline(di,snapshot,observed)
        if baseline:snapshot['baseline']=baseline
        start=time.monotonic();result=build_result(di,snapshot,c,observed)
        result['reranking']['latency_seconds']=time.monotonic()-start
        if result['reranking']['status']!='complete':raise RuntimeError('reranker failed')
        with sessions.begin() as db:
            run=db.scalar(select(SemanticRun).where(SemanticRun.id==key).with_for_update())
            if run.status!='pending' or run.lease_token:continue
            run.lease_token=new_id();run.lease_until=utcnow()+timedelta(seconds=settings.lease_seconds);run.attempts+=1;db.flush()
        if repo.finish(run,snapshot,result):
            count+=1
            print(json.dumps({'reused':old_id,'new_revision':key}),flush=True)
    print(json.dumps({'appended_corrected_revisions':count}),flush=True)
    await client.close();engine.dispose()

asyncio.run(main())
