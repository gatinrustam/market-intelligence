"""Read-only Stage 3.5.3 freshness proof. Run with Python 3 on the Docker host."""
import hashlib,json,urllib.request,urllib.error
from datetime import datetime,timezone

def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8004'+path,timeout=40) as response:return json.load(response)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def dt(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
ids={'Fed':'c8e6b183-983a-5509-b7a5-7da8962fbe95','ECB':'dc357cc0-33cf-5894-89ca-af8ea5472eb7','SEC':'aa378c10-f72a-52b3-9b99-9a085235a6e5'}
report={'captured_at':datetime.now(timezone.utc).isoformat(),'examples':{}}
for name,cid in ids.items():
    path='/contexts/'+cid
    before=get(path+'/revisions')
    live=get(path+'/decision');research=get(path+'/decision?basis=research_hypothetical')
    assert live['decision_basis']=='live_observed' and not live['historical_simulation']
    assert research['decision_basis']=='source_published_at' and research['historical_simulation']
    assert dt(live['decision_at'])>=max(dt(live[k]) for k in ('canonical_available_at','evidence_available_at','canonical_generated_at'))
    assert dt(research['decision_at'])==dt(research['known_information']['canonical_event']['time']['earliest_source_published_at'])
    for package in (live,research):
        assert not package['historical_content_verified']
        assert [p['offset_seconds'] for p in package['points']]==[-900,-300,0]
        for point in package['points']:
            assert point['role']=='causal'
            assert dt(point['target_at'])<=dt(package['decision_at'])
            if point['available']:assert dt(point['price_at'])<=dt(point['target_at'])
        for evidence in package['known_information']['evidence']:
            assert not evidence['historical_content_verified']
            doc=evidence['document']
            with urllib.request.urlopen('http://127.0.0.1:8002/documents/'+doc['document_id']+'/input') as response:
                assert json.load(response)['document']==doc
            if package is live:assert dt(evidence['evidence_available_at'])<=dt(live['decision_at'])
    after=get(path+'/revisions');assert before==after
    report['examples'][name]={'revisions_unchanged':True,'revision_count':len(before),'revision_history_sha256':digest(before),'live':live,'research_hypothetical':research}
fed=report['examples']['Fed']['research_hypothetical']
assert fed['decision_at']=='2026-04-29T18:00:00Z' and fed['complete']
assert fed['points'][-1]['price_at']=='2026-04-29T17:59:59.999000Z'
for path,status in [('/contexts/'+ids['Fed']+'/decision?basis=unknown',422),('/contexts/cf5bc01c-0b06-55c6-9835-183e48119cce/decision',409)]:
    try:get(path)
    except urllib.error.HTTPError as error:assert error.code==status
    else:raise AssertionError('expected rejection')
report['readiness']={}
for name,port in [('ingestion',8000),('enrichment',8001),('events',8002),('market-data',8003),('market-context',8004)]:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/ready') as response:report['readiness'][name]=json.load(response)
report['all_causal_cutoffs_verified']=True
report['outcomes_absent']=True
for name,example in report['examples'].items():
    for basis in ('live','research_hypothetical'):
        package=example[basis]
        assert package['lookup_policy']=='causal_asof_fresh_v1'
        assert package['freshness_policy']['version']==package['lookup_policy']
        assert package['decision_ready']==package['points'][-1]['available']
        assert package['complete']==all(p['available'] for p in package['points'])
        assert package['market_data_status']==('available' if package['complete'] else 'market_data_unavailable')
        for point in package['points']:
            if point['available']:
                age=(dt(point['target_at'])-dt(point['price_at'])).total_seconds()
                assert 0<=age<=point['max_age_seconds'] and age==point['age_seconds']
                assert point['max_age_seconds']==package['freshness_policy']['max_age_seconds'][point['resolution']]
            else:
                assert all(point[k] is None for k in ('price','price_at','candle','bid','ask','spread_bps','return_pct_from_anchor','absolute_return_pct'))
                if point['reason']=='stale_market_data':assert point['age_seconds']>point['max_age_seconds']
report['all_freshness_cutoffs_verified']=True
print(json.dumps(report,ensure_ascii=False,indent=2))
