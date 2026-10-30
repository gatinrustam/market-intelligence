"""Three labelled fixture analyses, real market outcomes, isolated fixture subjects.
Never invokes a model or publishes a fixture on analysis.completed.v1.
"""
import asyncio
import json
from uuid import uuid5,NAMESPACE_URL
import httpx
from app.config import Settings
from app.domain import canonical,digest,identity
from app.publishers.nats import JetStreamBus
from app.storage.contract import Contract

CASES = [
    ('Fed','c8e6b183-983a-5509-b7a5-7da8962fbe95',['down','down','up','unclear'],'medium'),
    ('ECB','dc357cc0-33cf-5894-89ca-af8ea5472eb7',['up','neutral','down','up'],'high'),
    ('SEC','aa378c10-f72a-52b3-9b99-9a085235a6e5',['up','down','unclear','neutral'],'low'),
]

async def main():
    settings=Settings()
    if not settings.fixtures_enabled: raise RuntimeError('Enable EVALUATION_FIXTURES_ENABLED for labelled fixture smoke')
    bus=JetStreamBus(settings.nats_url.get_secret_value(),fixtures=True)
    report={'fixture_only':True,'model_requests':0,'cases':[]}
    try:
        await bus.connect()
        async with httpx.AsyncClient(timeout=40) as client:
            for name,context,directions,confidence in CASES:
                response=await client.get(settings.context_url+'/contexts/'+context+'/decision',params={'basis':'research_hypothetical'})
                response.raise_for_status();decision=response.json()
                if not decision['decision_ready']: raise RuntimeError(name+' has no fresh decision anchor')
                fields=('decision_at','decision_basis','historical_simulation')
                package={'event_identity':decision['event'],'event':decision['known_information']['canonical_event'],
                    'decision':{k:decision[k] for k in fields},
                    'market_context':{'symbol':'BTCUSDT','lookup_policy':decision['lookup_policy'],'freshness_policy':decision['freshness_policy'],
                        'points':[{k:p[k] for k in ('offset_seconds','target_at','available','price','price_at','resolution','age_seconds','max_age_seconds')} for p in decision['points'] if p['offset_seconds']==0]}}
                label='stage5-real-outcomes-smoke-v1'
                key=str(uuid5(NAMESPACE_URL,f"{label}:{decision['event']['event_id']}:{decision['event']['event_revision']}"))
                analysis={'schema_version':'1.0','message_id':key,'analysis_id':key,'event':decision['event'],
                    'decision':package['decision'],'asset':{'symbol':'BTCUSDT','relevance':'medium'},
                    'interpretation':{'summary':f'LABELLED FIXTURE {name}; no LLM was called.',
                        'market_mechanism':'Hand-authored forecast for deterministic pipeline verification only.'},
                    'forecast':[{'horizon_seconds':n,'direction':d,'impact':'small','confidence':confidence} for n,d in zip((60,300,900,3600),directions,strict=True)],
                    'uncertainties':['Fixture, not model performance.','Historical content is not verified.'],
                    'unavailable_data':{k:'unavailable' for k in ('market_surprise','consensus_expectation','probability_of_fed_action')},
                    'confidence_basis':'model_reported_not_calibrated',
                    'audit':{'provider':'openai','model':'fixture/hand-authored-v1','prompt_version':'fixture_no_prompt_v1',
                        'reasoning_effort':'not_applicable_fixture','input_hash':digest(package)}}
                Contract(settings.contracts_dir/'analysis/v1.schema.json').validate(analysis)
                payload={'fixture_label':label,'analysis':analysis,'decision_input':package}
                await bus.js.publish('fixture.analysis.completed.v1',canonical(payload).encode(),
                    headers={'Nats-Msg-Id':'fixture-input:'+key,'Nats-Expected-Stream':'EVALUATION_FIXTURE_INPUTS'},timeout=5)
                report['cases'].append({'name':name,'analysis_id':key,'evaluation_id':identity(key),'context_id':context,'decision_at':decision['decision_at']})
            for _ in range(40):
                ready=True
                for case in report['cases']:
                    response=await client.get('http://evaluation:8007/evaluations/'+case['evaluation_id'])
                    if response.status_code!=200:
                        ready=False;continue
                    case['evaluation']=response.json()
                if ready:break
                await asyncio.sleep(1)
            if not ready: raise RuntimeError('Fixture evaluations not available; inspect /stats and logs')
            for case in report['cases']:
                value=case['evaluation'];subject='fixture.evaluation.created.v1' if value['revision']==1 else 'fixture.evaluation.updated.v1'
                # Publication is asynchronous; wait for the matching immutable payload.
                for _ in range(40):
                    found=False
                    stream=await bus.js.stream_info('EVALUATIONS')
                    for sequence in range(stream.state.first_seq,stream.state.last_seq+1):
                        raw=await bus.js.get_msg('EVALUATIONS',seq=sequence)
                        if raw.subject==subject and json.loads(raw.data)==value:found=True;break
                    if found:break
                    await asyncio.sleep(1)
                if not found:raise RuntimeError('Evaluation outbox not published')
                case['nats_subject']=subject;case['nats_payload_matches_api']=True
            report['metrics']={g:(await client.get('http://evaluation:8007/metrics',params={'origin':'fixture','group_by':g})).json() for g in ('horizon','confidence','event_type','source','model','prompt_version')}
            real=(await client.get('http://evaluation:8007/metrics')).json()
            report['real_metrics']=real
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:await bus.close()

if __name__=='__main__':asyncio.run(main())
