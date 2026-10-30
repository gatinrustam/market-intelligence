"""Read-only report of real crypto records and exact persisted pipeline outputs."""
import json
import re
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'datasets/crypto-source-expansion-v1'

def get(port,path):
    with urlopen(f'http://127.0.0.1:{port}{path}',timeout=30) as r:return json.load(r)

def catalogue(port):
    result=[]
    while True:
        page=get(port,f'/articles?limit=100&offset={len(result)}');result+=page['items']
        if not page['items'] or len(result)>=page['total']:return result

def main():
    raw=json.loads(Path('/tmp/crypto-raw-items.json').read_text())
    ids={x['source']['id'] for x in raw}
    articles=[r for r in catalogue(8010) if r['source'] in ids]
    samples=[]
    for row in articles:
        detail=get(8010,'/articles/'+row['id']);doc=detail['snapshot']['document'];di=detail['snapshot']['intelligence']
        samples.append({'routing_id':row['id'],'document_id':row['document_id'],'source':row['source'],'title':row['title'],'published':row['published'],'source_url':doc['source']['url'],
            'source_external_id':doc['source'].get('external_id'),'categories':row.get('categories',[]),'enrichment':doc['enrichment'],'fetch':doc['fetch'],
            'intelligence_id':di['intelligence_id'],'fact_ruleset_version':di['extraction']['fact_ruleset_version'],'entities':di['entities'],'facts':di['facts'],'measurements':di['measurements'],'di_processing':di['processing'],
            'article_route':row['route'],'route_reasons':detail['machine']['basis']['reasons']})
    stats={str(p):get(p,'/stats') for p in (8001,8009,8010,8012)}
    sources=get(8000,'/sources')
    # Export complete machine outputs only for the new sources and final configuration.
    semantic=[]
    latest_ids={x['intelligence_id'] for x in samples}
    for machine in json.loads(Path('/tmp/crypto-semantic-outputs.json').read_text()):
        if machine['document']['source_id'] in ids and machine['provenance']['pipeline_version']=='semantic_crypto_v1_1' and machine['document']['intelligence_id'] in latest_ids:semantic.append(machine)
    snapshot={'captured_at':datetime.now(timezone.utc).isoformat(),'historical_sample':True,
              'raw_counts':dict(Counter(x['source']['id'] for x in raw)),
              'distinct_incidents':{s:len({x['source']['external_id'].split('/')[1] for x in raw if x['source']['id']==s}) for s in ids if s.startswith('kraken')},
              'routed_counts':dict(Counter(x['source'] for x in samples)),
              'semantic_counts':dict(Counter(x['document']['source_id'] for x in semantic)),
              'source_health':[s for s in sources if s.get('metadata',{}).get('domain')=='crypto'],'stats':stats,
              'articles':samples,'semantic_outputs':semantic}
    DEST.mkdir(exist_ok=True,parents=True)
    (DEST/'observed-pipeline.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:snapshot[k] for k in ('captured_at','raw_counts','distinct_incidents','routed_counts','semantic_counts')},ensure_ascii=False))

if __name__=='__main__':main()
