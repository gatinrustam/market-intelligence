import hashlib,json,re
from datetime import datetime,timezone
from uuid import uuid5,NAMESPACE_URL
from pydantic import BaseModel,ConfigDict,Field,model_validator
from app.schema import Route,Relevance,Output,Features

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def iso(value):return value.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def now():return datetime.now(timezone.utc)
def identity(di,c):return str(uuid5(NAMESPACE_URL,':'.join(['article.routing.v1',di['document']['document_id'],di['intelligence_id'],di['extraction']['pipeline_version'],c['version'],c['high_value_registry']['version']])))
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Rule(Strict):
    id:str;fact_types:list[str]=[];sources:list[str]=[];event_types:list[str]=[];topics_any:list[str]=[];metadata_rule_ids:list[str]=[];title_patterns:list[str]=[]
    categories_any:list[str]=[]
    no_high_value:bool=False;no_facts:bool=False
    route:Route;priority:int=Field(ge=0);reason:str=Field(min_length=1)
    crypto_relevance:Relevance|None=None;macro_relevance:Relevance|None=None
    @model_validator(mode='after')
    def valid(self):
        if not any((self.fact_types,self.sources,self.event_types,self.topics_any,self.metadata_rule_ids,self.title_patterns,self.categories_any)):raise ValueError('unbounded rule')
        for p in self.title_patterns:re.compile(p)
        return self
class Density(Strict):high_fact_count:int=Field(ge=1);high_value_with_measurements:int=Field(ge=1);medium_measurements:int=Field(ge=1)
class HighValue(Strict):version:str;fact_types:list[str]
class Rules(Strict):
    version:str=Field(pattern=r'^[A-Za-z0-9_.-]{1,32}$');high_value_registry_file:str
    source_metadata:dict[str,dict]={}
    source_quality:dict[str,str];financial_prefixes:list[str];macro_prefixes:list[str];crypto_prefixes:list[str]
    density:Density;default_route:Route;empty_unknown_source_route:Route;rules:list[Rule];high_value_registry:HighValue
    @model_validator(mode='after')
    def valid(self):
        if len({r.id for r in self.rules})!=len(self.rules):raise ValueError('duplicate rules')
        if not set(self.source_quality.values())<=set(('official_primary','high','medium','low','unknown')):raise ValueError('quality')
        return self

def load_configuration(settings):
    c=json.loads(settings.rules_path.read_text());c['high_value_registry']=json.loads((settings.rules_path.parent/c['high_value_registry_file']).read_text())
    return Rules.model_validate(c).model_dump()
def fact_signature(f):
    values=[{k:m.get(k) for k in ('kind','value','min','max','unit','currency')} for m in f['values']]
    return digest({'type':f['fact_type'],'action':f['action'],'subject':f['subject']['entity_id'],'values':sorted(values,key=canonical)})
def build_result(di,snapshot,c,clock=now):
    document=snapshot['document'];events=snapshot['events'];intelligences=snapshot['event_intelligence']
    facts=list({fact_signature(f):f for f in di['facts']}.values())
    financial=[f for f in facts if any(f['fact_type'].startswith(p) for p in c['financial_prefixes'])]
    high=[f for f in financial if f['fact_type'] in c['high_value_registry']['fact_types']]
    types={f['fact_type'] for f in facts};event_types={e['taxonomy']['event_type'] for e in events};topics={t['topic'] for t in di['topics']}
    topics|={t for e in events for t in e['taxonomy']['topics']}
    metadata_rules={r for e in intelligences for r in e['basis']['matched_rule_ids']}
    source=document['source']['id'];basis={};ids=[f['fact_id'] for f in financial]
    def reason(key,text,paths,rule_ids=(),fact_ids=()):basis[key]={'reason':text,'input_paths':paths,'rule_ids':list(rule_ids),'fact_ids':list(fact_ids)}
    features={'financial_fact_count':len(financial),'measurement_count':len(di['measurements']),'high_value_fact_count':len(high)}
    reason('financial_fact_count',f'{len(financial)} distinct exact financial fact signatures; {len(di["facts"])} raw occurrences',['/intelligence/facts'],['features.distinct_financial_facts'],ids)
    reason('measurement_count','Count of separately evidenced measurement occurrences',['/intelligence/measurements'],['features.measurements'])
    reason('high_value_fact_count','Distinct financial facts matching the frozen high-value registry',['/intelligence/facts','/configuration/high_value_registry'],['features.high_value_registry'],[f['fact_id'] for f in high])
    features['source_quality']=c['source_quality'].get(source,'unknown');reason('source_quality','Static source registry; independent of completeness of this document',['/document/source','/configuration/source_quality'],['features.source_quality'])
    features['document_quality']='high' if di['processing']['status']=='complete' and document['enrichment']['status']=='ready' else 'low' if di['processing']['status'] in ('partial','unsupported') else 'unknown'
    reason('document_quality','Exact enriched status and DI processing status/warnings; partial evidence is low quality even for an official source',['/document/enrichment','/intelligence/processing'],['features.document_quality'])
    d=c['density'];nf=len(financial);nm=len(di['measurements']);nr=len(di['relations']);ne=len({e['entity_id'] for e in di['entities'] if e['registry']})
    features['information_density']='high' if nf>=d['high_fact_count'] or len(high)>=d['high_value_with_measurements'] and nm else 'medium' if nf or nm>=d['medium_measurements'] and nr and ne else 'low'
    reason('information_density',f'facts={nf}, measurements={nm}, relations={nr}, unique registry entities={ne}; configured count thresholds, no length score',['/intelligence/facts','/intelligence/measurements','/intelligence/relations','/intelligence/entities','/configuration/density'],['features.density'])
    features['event_specificity']='specific' if financial else next((e['event_specificity'] for e in intelligences if e['event_specificity'] in ('commentary','general','specific')),'unknown')
    reason('event_specificity','Concrete financial facts, else pinned compatible Event Intelligence metadata, else unknown',['/intelligence/facts','/event_intelligence'],['features.specificity'],ids)
    novelty='unknown';novelty_reason='Insufficient correlation history; transport redelivery is not semantic novelty'
    if snapshot.get('repeated_source_item'):
        novelty='repeated_source_item';novelty_reason='Earlier completed routing input has the same source ID and source message ID'
    elif any(e['novelty']=='duplicate_like' for e in intelligences):novelty='duplicate_like';novelty_reason='Pinned Event Intelligence exact canonical-history duplicate-like result'
    elif any(e['novelty']=='update' for e in intelligences):novelty='supporting_update';novelty_reason='Pinned canonical correlation update'
    elif intelligences and all(e['novelty']=='new' for e in intelligences):novelty='new';novelty_reason='First canonical revision in pinned history, not global semantic novelty'
    features['novelty']=novelty;reason('novelty',novelty_reason,['/event_intelligence','/repeated_source_item'],['features.novelty'])
    features['macro_relevance']='high' if any(any(f['fact_type'].startswith(p) for p in c['macro_prefixes']) for f in financial) else 'none'
    features['crypto_relevance']='high' if any(any(f['fact_type'].startswith(p) for p in c['crypto_prefixes']) for f in financial) else 'medium' if topics.intersection(('digital_assets','bitcoin','ethereum')) else 'none'
    matches=[]
    for r in c['rules']:
        if r.get('categories_any') and not set(document.get('classification',{}).get('categories',[])).intersection(r['categories_any']):continue
        if r['fact_types'] and not types.intersection(r['fact_types']):continue
        if r['sources'] and source not in r['sources']:continue
        if r['event_types'] and not event_types.intersection(r['event_types']):continue
        if r['topics_any'] and not topics.intersection(r['topics_any']):continue
        if r['metadata_rule_ids'] and not metadata_rules.intersection(r['metadata_rule_ids']):continue
        if r['title_patterns'] and not any(re.search(p,document['content']['title']) for p in r['title_patterns']):continue
        if r['no_high_value'] and high:continue
        if r['no_facts'] and financial:continue
        matches.append(r)
    rank={'none':0,'unknown':0,'low':1,'medium':2,'high':3}
    for field in ('macro_relevance','crypto_relevance'):
        applicable=[r for r in matches if r[field] is not None]
        for r in applicable:features[field]=max(features[field],r[field],key=rank.get)
        reason(field,'Supported fact categories, evidenced topics and matched source/context rules; no single body keyword score',['/intelligence/facts','/intelligence/topics','/events','/event_intelligence','/document/content/title'],[r['id'] for r in applicable],ids)
    features['market_relevance']=max(features['macro_relevance'],features['crypto_relevance'],'medium' if financial else 'none',key=rank.get)
    reason('market_relevance','Maximum of explained macro/crypto relevance and presence of a financial fact',['/intelligence/facts','/features/macro_relevance','/features/crypto_relevance'],['features.market_relevance'],ids)
    winner=max(matches,key=lambda r:r['priority']) if matches else None
    route=winner['route'] if winner else c['empty_unknown_source_route'] if not financial and features['source_quality']=='unknown' and di['processing']['status']!='unsupported' else c['default_route']
    reasons=[r['reason'] for r in sorted(matches,key=lambda r:-r['priority'])] or ['No decisive rule; conservative review' if route=='review' else 'No supported financial facts or known source; retained as low priority']
    if features['document_quality']!='high':reasons.append('Incomplete/unsupported evidence remains visible to reviewers; source prestige does not repair document quality')
    key=identity(di,c)
    payload={'schema_version':'1.0','message_id':key,'routing_id':key,'document':{'document_id':di['document']['document_id'],'intelligence_id':di['intelligence_id'],**{k:di['extraction'][k] for k in ('pipeline_version','fact_ruleset_version','entity_registry_version')}},
        'classification':{'route':route},'features':features,'basis':{'ruleset_version':c['version'],'high_value_registry_version':c['high_value_registry']['version'],'configuration_hash':digest(c),'input_hash':digest(di),'snapshot_hash':digest(snapshot),'matched_rule_ids':[r['id'] for r in matches],'reasons':reasons,'feature_basis':basis,'metadata_warnings':snapshot['metadata_warnings']},'generated_at':iso(clock())}
    Output.model_validate(payload);return payload
