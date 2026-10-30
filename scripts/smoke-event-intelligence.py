"""Run inside event-intelligence: python - < scripts/smoke-event-intelligence.py.
Read-only smoke of the existing catalogue, immutable results and NATS output.
"""
import asyncio,json
from collections import Counter
from app.config import Settings
from app.storage.contract import Contract
from app.domain import digest
import httpx,nats
async def main():
    settings=Settings();report={'provider_requests':0,'events':[]}
    async with httpx.AsyncClient(timeout=15) as c:
        events=[];offset=0
        while True:
            r=await c.get('http://events:8002/events',params={'offset':offset,'limit':100});r.raise_for_status();page=r.json();events+=page['items'];offset+=len(page['items'])
            if offset>=page['total']:break
            if not page['items']:raise RuntimeError('incomplete catalogue')
        stats=(await c.get('http://event-intelligence:8008/stats')).json();version=stats['ruleset_version']
        for event in events:
            for _ in range(60):
                r=await c.get('http://event-intelligence:8008/events/'+event['event']['id']+'/intelligence',params={'event_revision':event['event']['revision'],'ruleset_version':version});r.raise_for_status();rows=r.json()
                if rows:break
                await asyncio.sleep(1)
            if len(rows)!=1:raise RuntimeError('missing/duplicate intelligence for canonical revision')
            value=rows[0];Contract(settings.contracts_dir/'event/intelligence/v1.schema.json').validate(value)
            assert value['basis']['canonical_hash']==digest(event)
            response=await c.get('http://event-intelligence:8008/intelligence/'+value['intelligence_id']+'/input');response.raise_for_status();frozen=response.json()
            assert digest(frozen['snapshot'])==value['basis']['input_hash']==frozen['input_hash']
            assert digest(frozen['configuration'])==value['basis']['ruleset_hash']
            assert value['surprise']=={'status':'unavailable','value':None} and all(v is None for v in value['expectations'].values())
            report['events'].append({'event_id':event['event']['id'],'event_revision':event['event']['revision'],'title':event['content']['canonical_title'],'event_type':event['taxonomy']['event_type'],'sources':[d['source_id'] for d in event['evidence']['documents']],'intelligence':value})
        nc=await nats.connect(settings.nats_url.get_secret_value())
        try:
            js=nc.jetstream();info=await js.stream_info('EVENT_INTELLIGENCE');published={}
            for seq in range(max(1,info.state.first_seq),info.state.last_seq+1):
                m=await js.get_msg('EVENT_INTELLIGENCE',seq=seq)
                if m.subject=='event.intelligence.v1':
                    value=json.loads(m.data);published[value['intelligence_id']]=value
            for row in report['events']:
                assert published.get(row['intelligence']['intelligence_id'])==row['intelligence'];row['nats_payload_matches']=True
        finally:await nc.close()
        report['event_count']=len(events);report['ruleset_version']=version
        report['distributions']={field:dict(Counter(row['intelligence'][field] for row in report['events'])) for field in ('relevance','event_specificity','information_quality','novelty')}
        report['distributions']['surprise_status']=dict(Counter(row['intelligence']['surprise']['status'] for row in report['events']))
        report['stats']=(await c.get('http://event-intelligence:8008/stats')).json()
        report['examples']={}
        for name,kind in [('Fed FOMC','central_bank.policy_statement'),('ECB speech','central_bank.speech'),('SEC enforcement','regulator.enforcement'),('SEC personnel','regulator.personnel')]:
            report['examples'][name]=next((r for r in report['events'] if r['event_type']==kind and (name!='SEC enforcement' or 'sec.personnel_announcement' not in r['intelligence']['basis']['matched_rule_ids'])),None)
        if report['examples']['SEC personnel'] is None:
            report['examples']['SEC personnel']=next((r for r in report['events'] if 'sec.personnel_announcement' in r['intelligence']['basis']['matched_rule_ids']),None)
        report['examples']['SEC digital market action']=next((r for r in report['events'] if 'sec.tokenized_nms_exemption' in r['intelligence']['basis']['matched_rule_ids']),None)
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
