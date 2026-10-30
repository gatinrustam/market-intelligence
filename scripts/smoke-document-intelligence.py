"""Read-only catalogue/DI/NATS smoke; run inside document-intelligence."""
import asyncio,json,hashlib
from collections import Counter
import httpx,nats
from app.config import Settings
from app.domain import digest
from app.pipeline import validate_spans
from app.storage.contract import Contract
async def main():
    settings=Settings();report={'provider_requests':0,'documents':[]}
    async with httpx.AsyncClient(timeout=20) as c:
        events=(await c.get('http://events:8002/events',params={'limit':100})).json();assert events['total']==len(events['items'])
        documents={};titles={};types={}
        for event in events['items']:
            for ref in event['evidence']['documents']:
                key=ref['document_id'];titles[key]=event['content']['canonical_title'];types[key]=event['taxonomy']['event_type']
                if key not in documents:
                    r=await c.get('http://events:8002/documents/'+key+'/input');r.raise_for_status();documents[key]=r.json()['document']
        for key,doc in documents.items():
            for _ in range(60):
                r=await c.get('http://localhost:8009/documents/'+key+'/intelligence');r.raise_for_status();rows=r.json()
                if rows:break
                await asyncio.sleep(1)
            if not rows:raise RuntimeError('missing document '+key)
            out=rows[-1];Contract(settings.contracts_dir/'document/intelligence/v1.schema.json').validate(out)
            assert out['document']['input_message_id']==doc['message_id']
            assert out['document']['body_hash']==hashlib.sha256(doc['content']['body'].encode()).hexdigest()
            validate_spans(out,doc['content']['body'])
            frozen=(await c.get('http://localhost:8009/intelligence/'+out['intelligence_id']+'/input')).json()
            assert json.loads(frozen['exact_payload'])==doc and digest(doc)==frozen['payload_hash']
            assert digest(frozen['configuration'])==out['extraction']['configuration_hash']
            report['documents'].append({'document_id':key,'title':titles[key],'source':doc['source']['id'],'event_type':types[key],'input_status':doc['enrichment']['status'],'span_invariant':True,'exact_input_matches':True,'output':out})
        nc=await nats.connect(settings.nats_url.get_secret_value())
        try:
            js=nc.jetstream();info=await js.stream_info('DOCUMENT_INTELLIGENCE');messages={}
            for seq in range(info.state.first_seq,info.state.last_seq+1):
                m=await js.get_msg('DOCUMENT_INTELLIGENCE',seq=seq);p=json.loads(m.data);messages[p['intelligence_id']]=p
            for row in report['documents']:
                assert messages.get(row['output']['intelligence_id'])==row['output'];row['nats_payload_matches']=True
        finally:await nc.close()
        outputs=[r['output'] for r in report['documents']]
        report['document_count']=len(outputs);report['languages']=dict(Counter(p['language'] for p in outputs))
        report['counts']={k:sum(len(p[k]) for p in outputs) for k in ('entities','facts','measurements','relations','dates')}
        report['topics_documents']=dict(Counter(t for p in outputs for t in {x['topic'] for x in p['topics']}))
        report['with_facts']=sum(bool(p['facts']) for p in outputs);report['zero_facts']=len(outputs)-report['with_facts'];report['processing']=dict(Counter(p['processing']['status'] for p in outputs))
        report['stats']=(await c.get('http://localhost:8009/stats')).json()
        report['examples']={}
        for name,source,typ in [('Fed FOMC','fed_monetary_policy','central_bank.policy_statement'),('ECB speech','ecb_press','central_bank.speech'),('ECB interview','ecb_press','central_bank.interview'),('SEC proposal','sec_press_releases','regulator.rule_proposal'),('SEC partial RSS','sec_press_releases',None)]:
            row=next((r for r in report['documents'] if r['source']==source and (r['event_type']==typ if typ else r['input_status']=='partial')),None)
            report['examples'][name]=row
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
