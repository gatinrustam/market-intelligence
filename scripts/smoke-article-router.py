"""Run inside article-router; read-only verification of HTTP, frozen inputs and NATS."""
import asyncio,json,hashlib
from collections import Counter,defaultdict
import httpx,nats
from app.domain import digest,build_result
from app.config import Settings
from app.storage.contract import Contract
async def main():
    settings=Settings();contract=Contract(settings.contracts_dir/'article/routing/v1.schema.json')
    async with httpx.AsyncClient(base_url='http://localhost:8010',timeout=30) as client:
        async def get(path):
            r=await client.get(path);r.raise_for_status();return r.json()
        stats=await get('/stats');articles=await get('/articles?limit=100');assert articles['total']==55
        details=[await get('/articles/'+a['id']) for a in articles['items']]
        nc=await nats.connect(settings.nats_url.get_secret_value());js=nc.jetstream();info=await js.stream_info('ARTICLE_ROUTING');published={}
        for seq in range(info.state.first_seq,info.state.last_seq+1):
            msg=await js.get_msg('ARTICLE_ROUTING',seq=seq);p=json.loads(msg.data);published[p['routing_id']]=p
        by_source=defaultdict(Counter);by_topic=defaultdict(Counter);by_fact=defaultdict(Counter);rows=[]
        from datetime import datetime
        for a in details:
            p=a['machine'];snapshot=a['snapshot'];contract.validate(p)
            expected=build_result(snapshot['intelligence'],snapshot,a['configuration'],clock=lambda:datetime.fromisoformat(p['generated_at'].replace('Z','+00:00')))
            assert p==expected;assert published[p['routing_id']]==p
            assert p['basis']['snapshot_hash']==digest(snapshot)
            route=p['classification']['route'];d=snapshot['document'];by_source[d['source']['id']][route]+=1
            topics=({t['topic'] for t in snapshot['intelligence']['topics']} | {t for e in snapshot['events'] for t in e['taxonomy']['topics']}) or {'none'}
            for topic in topics:by_topic[topic][route]+=1
            types={f['fact_type'] for f in snapshot['intelligence']['facts']} or {'none'}
            for kind in types:by_fact[kind][route]+=1
            rows.append({'routing_id':p['routing_id'],'document_id':d['document_id'],'title':d['content']['title'],'source':d['source']['id'],'route':route,'machine_hash':digest(p),'snapshot_hash':digest(snapshot),'metadata_warnings':p['basis']['metadata_warnings'],'features':p['features'],'matched_rule_ids':p['basis']['matched_rule_ids'],'review':a['review'],'labels':a['labels']})
        await nc.close()
        print(json.dumps({'stats':stats,'by_source':by_source,'by_topic':by_topic,'by_fact_type':by_fact,'nats_exact_match':len(rows),'reproduced_from_frozen_input':len(rows),'articles':rows},ensure_ascii=False,indent=2))
asyncio.run(main())
