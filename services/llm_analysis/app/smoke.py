"""Bounded 3-example real Astra smoke, or read-only --prepare-only provenance preflight."""
import argparse,asyncio,json,time
from uuid import uuid5,NAMESPACE_URL
import httpx
from app.config import Settings
from app.domain import canonical,digest,now,iso
from app.guard import build_input,Blocked
from app.worker import DecisionClient

EXAMPLES={'Fed':'c8e6b183-983a-5509-b7a5-7da8962fbe95','ECB':'dc357cc0-33cf-5894-89ca-af8ea5472eb7','SEC':'aa378c10-f72a-52b3-9b99-9a085235a6e5'}
async def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--run-label',default='stage4-astra-smoke-v1');args=parser.parse_args()
    settings=Settings();decisions=DecisionClient(settings.context_url)
    report={'captured_at':iso(now()),'mode':'preflight_only' if args.prepare_only else 'real_openai','configuration':settings.configuration(),'api_key_configured':bool(settings.api_key.get_secret_value()),'examples':{}}
    if not args.prepare_only and not settings.api_key.get_secret_value():raise SystemExit('OPENAI_API_KEY missing; no provider calls made')
    try:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8005',timeout=40) as api:
            for name,context in EXAMPLES.items():
                p=await decisions.fetch(context,'research_hypothetical')
                try:value=build_input(p,p['event'],settings)
                except Blocked as error:
                    report['examples'][name]={'status':'blocked','reason':str(error)};continue
                entry={'status':'prepared','input_hash':digest(value),'analysis_input':value,'provider_called':False}
                report['examples'][name]=entry
                if args.prepare_only:continue
                body={**p['event'],'context_id':context,'basis':'research_hypothetical','run_key':str(uuid5(NAMESPACE_URL,args.run_label+':'+name))}
                response=await api.post('/analyses',json=body);response.raise_for_status();key=response.json()['analysis_id']
                deadline=time.monotonic()+900
                while time.monotonic()<deadline:
                    response=await api.get('/analyses/'+key);response.raise_for_status();state=response.json()
                    if state['analysis_status'] in ('completed','failed','blocked'):break
                    await asyncio.sleep(2)
                else:raise RuntimeError('smoke deadline exceeded; inspect queued job '+key)
                entry.update(status=state['analysis_status'],analysis_id=key,audit=state,provider_called=any(r['response_audit'] and r['response_audit'].get('provider_response_id') for r in state['runs']))
                response=await api.get('/analyses/'+key+'/input');response.raise_for_status();frozen=response.json()
                entry['input_hash']=frozen['input_hash'];entry['analysis_input']=json.loads(frozen['canonical_json'])
                assert digest(entry['analysis_input'])==entry['input_hash']
                # Keep this report bounded. Manual review is required; no automatic factual-verification claim.
            report['manual_response_review']='pending' if not args.prepare_only else 'not_applicable_no_provider_responses'
            report['completed']=sum(e['status']=='completed' for e in report['examples'].values())
            print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:await decisions.close()
if __name__=='__main__':asyncio.run(main())
