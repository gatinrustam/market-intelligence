"""Run inside document-intelligence; emits fixtures, never writes DB or NATS."""
import copy,json,sys
from uuid import uuid5,NAMESPACE_URL
from app.config import Settings
from app.domain import load_configuration
from app.pipeline import Pipeline
source=json.load(sys.stdin);pipeline=Pipeline(load_configuration(Settings()));results=[]
for fixture in source['fixtures']:
 doc=copy.deepcopy(source['template']);key=fixture['id']
 doc['document_id']=str(uuid5(NAMESPACE_URL,'semantic-fixture-document:'+key))
 doc['message_id']=str(uuid5(NAMESPACE_URL,'semantic-fixture-input:'+key))
 doc['lineage']['source_message_id']=str(uuid5(NAMESPACE_URL,'semantic-fixture-source:'+key))
 doc['content']['title']=fixture['title'];doc['content']['body']=fixture['body'];doc['content']['language']='ru'
 doc['source']['id']='synthetic_ru_fixture';doc['source']['url']='https://example.invalid/'+key
 doc['enrichment']['status']='ready'
 results.append({'fixture':fixture,'document':doc,'intelligence':pipeline.analyze(doc),'old_route':None,'warnings':['Synthetic Russian evaluation fixture; not a published article']})
print(json.dumps(results,ensure_ascii=False))
