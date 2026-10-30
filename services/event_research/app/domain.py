import copy,hashlib,json,re
from datetime import datetime,timezone
from uuid import uuid5,NAMESPACE_URL
from pydantic import Field,model_validator
from app.di_schema import Strict,Output as DIOutput
from app.schema import Output,Comparison

def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def iso(t):return t.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def now():return datetime.now(timezone.utc)
def uid(*parts):return str(uuid5(NAMESPACE_URL,':'.join(parts)))
def identity(di,c):return uid('event.research.v2',di['intelligence_id'],c['version'])
class Mapping(Strict):
    id:str;fact_type:str;event_type:str;priority:int;allowed_modalities:list[str]
class MetadataRule(Strict):
    id:str;priority:int;source_id:list[str];title_regex:list[str]=[];url_regex:list[str]=[];event_type:str;topics:list[str]
    classification_basis:str|None=None;identity_namespace:str|None=None;identity_title_regex:str|None=None;speaker_title_regex:str|None=None;reason:str|None=None
    @model_validator(mode='after')
    def validate_patterns(self):
        if not self.title_regex and not self.url_regex:raise ValueError('Unbounded metadata rule')
        for pattern in self.title_regex+self.url_regex:re.compile(pattern)
        return self
class Source(Strict):issuer:str;jurisdictions:list[str];fallback_type:str
class Configuration(Strict):
    version:str=Field(pattern=r'^[A-Za-z0-9_.-]{1,32}$');legacy_ruleset_version:str
    legacy_rules:list[MetadataRule];metadata_overrides:list[MetadataRule];sources:dict[str,Source];fact_mapping:list[Mapping]
    @model_validator(mode='after')
    def unique(self):
        ids=[r.id for r in self.legacy_rules+self.metadata_overrides+self.fact_mapping]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate rule ID')
        if len({r.fact_type for r in self.fact_mapping})!=len(self.fact_mapping):raise ValueError('Ambiguous fact mapping')
        return self

def load_configuration(settings):return Configuration.model_validate_json(settings.rules_path.read_text()).model_dump()
def validate_links(di):
    DIOutput.model_validate(di)
    refs={e['mention_id']:e for e in di['entities']};relations={r['relation_id']:r for r in di['relations']};measurements={m['measurement_id']:m for m in di['measurements']}
    for group in ('entities','facts','measurements','relations','dates','topics'):
        for item in di[group]:
            e=item['evidence']
            if e['document_id']!=di['document']['document_id'] or e['end_char']-e['start_char']!=len(e['text']):raise ValueError('Invalid evidence reference')
    for fact in di['facts']:
        relation=relations.get(fact['relation_id'])
        if relation is None or relation['subject']!=fact['subject'] or relation['action']!=fact['action']:raise ValueError('Fact relation mismatch')
        subject=refs.get(fact['subject']['mention_id'])
        if subject is None or subject['entity_id']!=fact['subject']['entity_id']:raise ValueError('Unresolved fact subject reference')
        for m in fact['values']:
            if measurements.get(m['measurement_id'])!=m:raise ValueError('Fact measurement mismatch')
    return refs,relations

def metadata_signals(meta,c):
    matches=[]
    for r in c['metadata_overrides']+c['legacy_rules']:
        if meta['source']['id'] in r['source_id'] and (any(re.search(p,meta['title']) for p in r['title_regex']) or any(re.search(p,meta['source']['url'] or '') for p in r['url_regex'])):matches.append(r)
    return sorted(matches,key=lambda r:(-r['priority'],r['id']))

def build_result(di,snapshot,c,clock=now):
    entities,relations=validate_links(di);meta=snapshot['metadata'];key=identity(di,c)
    maps={m['fact_type']:m for m in c['fact_mapping']};groups={};ignored=[]
    for fact in di['facts']:
        mapping=maps.get(fact['fact_type']);relation=relations[fact['relation_id']]
        if not mapping:ignored.append({'fact_id':fact['fact_id'],'reason':'No configured event mapping'});continue
        if relation['modality'] not in mapping['allowed_modalities']:ignored.append({'fact_id':fact['fact_id'],'reason':'Modality is not eligible for an asserted event'});continue
        # No cross-document/date merging. Preserve different types and different actors/actions within a document.
        group=(mapping['event_type'],fact['subject']['entity_id'],fact['action'])
        groups.setdefault(group,[]).append(fact)
    matches=metadata_signals(meta,c);candidates=[]
    def actor(e):return {'entity_id':e['entity_id'],'mention_id':e['mention_id'],'name':e['canonical_name'],'entity_type':e['type'],'resolution':'canonical' if e['registry'] else 'unresolved'}
    for (typ,subject,action),facts in sorted(groups.items()):
        facts=sorted(facts,key=lambda f:f['fact_id']);fact_ids=[f['fact_id'] for f in facts];actors={};measurements={};dates={};signals=[]
        for f in facts:
            relation=relations[f['relation_id']]
            for ref in [f['subject'],relation['object']]:
                e=entities.get(ref.get('mention_id'))
                if e and e['entity_id']==ref.get('entity_id'):actors[e['mention_id']]=actor(e)
            for m in f['values']:
                entry=measurements.setdefault(m['measurement_id'],{'fact_ids':[],'measurement':m});entry['fact_ids'].append(f['fact_id'])
            for d in di['dates']:
                span=d['evidence'];fs=f['evidence']
                if span['sentence_id']==fs['sentence_id'] and fs['start_char']<=span['start_char']<span['end_char']<=fs['end_char']:
                    entry=dates.setdefault(d['date_id'],{'fact_ids':[],'date':d});entry['fact_ids'].append(f['fact_id'])
            signals.append({'kind':'primary_fact','event_type':typ,'rule_id':maps[f['fact_type']]['id'],'fact_ids':[f['fact_id']],'reason':'Asserted DI domain fact with linked relation and evidence'})
        for r in matches:
            if r['event_type']==typ:signals.append({'kind':'supporting_rule','event_type':typ,'rule_id':r['id'],'fact_ids':[],'reason':r['reason'] or 'Matching title/source/URL supports the fact classification'})
        exact_times=sorted({v['date']['normalized'] for v in dates.values() if v['date']['kind'] in ('date','time') and v['date']['normalized'] and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)',v['date']['normalized'])})
        event_time=exact_times[0] if len(exact_times)==1 else None
        topics=sorted({t['topic'] for t in di['topics'] if set(t['fact_ids']).intersection(fact_ids)})
        candidates.append({'candidate_id':uid(key,typ,subject,action,*fact_ids),'document_id':meta['document_id'],'event_type':typ,'primary_fact_ids':fact_ids,'supporting_fact_ids':[],
            'fact_references':[{'document_id':meta['document_id'],**{k:f[k] for k in ('fact_id','fact_type','relation_id','evidence','extraction')}} for f in facts],
            'actors':list(actors.values()),'topics':topics,'measurements':list(measurements.values()),'dates':list(dates.values()),'event_time':event_time,'event_time_basis':'explicit_fact_datetime' if event_time else 'unavailable',
            'classification_basis':'primary_fact','signals':signals})
    if not candidates and meta['document_status'] in ('ready','partial') and (len(meta['title'].strip())>=8 or meta['body_length']>=80):
        rule=matches[0] if matches else None;source=c['sources'].get(meta['source']['id']);typ=rule['event_type'] if rule else source['fallback_type'] if source else 'unknown'
        issuer=source['issuer'] if source else None;actors=[actor(e) for e in di['entities'] if e['entity_id']==issuer][:1]
        candidates.append({'candidate_id':uid(key,'fallback',typ),'document_id':meta['document_id'],'event_type':typ,'primary_fact_ids':[],'supporting_fact_ids':[],'fact_references':[],
            'actors':actors,'topics':rule['topics'] if rule else [],'measurements':[],'dates':[],'event_time':None,'event_time_basis':'unavailable','classification_basis':'fallback_rule',
            'signals':[{'kind':'fallback_rule','event_type':typ,'rule_id':rule['id'] if rule else 'fallback.'+meta['source']['id'],'fact_ids':[],'reason':(rule['reason'] if rule else None) or 'No eligible domain facts; explicit metadata-only fallback'}]})
    selected=sorted({x['event_type'] for x in candidates});legacy=snapshot['v1_basis'];alternatives=[]
    for b in legacy:
        if b['event_type'] not in selected:alternatives.append({'event_type':b['event_type'],'basis':'legacy_v1','rule_ids':b['rule_ids'],'fact_ids':[]})
    if groups and matches and matches[0]['event_type'] not in selected:
        r=matches[0];alternatives.append({'event_type':r['event_type'],'basis':'supporting_rule','rule_ids':[r['id']],'fact_ids':[]})
    conflicts=[]
    if alternatives and candidates:
        alternatives += [{'event_type':x['event_type'],'basis':x['classification_basis'],'rule_ids':[s['rule_id'] for s in x['signals']],'fact_ids':x['primary_fact_ids']} for x in candidates]
        conflicts=[{'kind':'classification_conflict','selected_event_types':selected,'alternatives':alternatives,'reason':'Selected facts/research rules disagree with observed v1 or strongest metadata rule. Research only; requires review.'}]
    payload={'schema_version':'2.0','message_id':key,'research_id':key,'mode':'research','production_canonical':False,'merge_enabled':False,
        'document':{'intelligence_id':di['intelligence_id'],**di['document']},'candidates':candidates,'conflicts':conflicts,
        'basis':{'ruleset_version':c['version'],'configuration_hash':digest(c),'input_hash':digest(di),'context_hash':digest({k:v for k,v in snapshot.items() if k not in ('intelligence','human_reviews')}),'extraction':di['extraction'],'warnings':snapshot['warnings'],'ignored_facts':ignored},'generated_at':iso(clock())}
    Output.model_validate(payload);return payload

def comparison(result,snapshot):
    old=sorted({v['event_type'] for v in snapshot['v1_basis']});new=sorted({v['event_type'] for v in result['candidates']})
    flags={'same_classification':old==new,'changed_classification':old!=new,'fallback_used':any(v['classification_basis']=='fallback_rule' for v in result['candidates']), 'conflict':bool(result['conflicts']), 'multiple_candidates':len(result['candidates'])>1,'no_event':not result['candidates'],'fact_based':any(v['primary_fact_ids'] for v in result['candidates'])}
    human=[]
    for review in snapshot['human_reviews']:
        for label in review['labels']:
            if label['event_type_correct'] is not None or label['facts_correct'] is not None:
                human.append({'routing_id':review['routing_id'],'request_id':label['request_id'],'revision':label['revision'],'event_type_correct':label['event_type_correct'],'facts_correct':label['facts_correct'],'reviewed_v1_types':review['reviewed_v1_types'],
                    'v2_differs_from_v1':new!=review['reviewed_v1_types'],'v2_conflict_visible':flags['conflict'],'scope':'evaluation_only_not_ground_truth','comment':label['comment']})
    p={'document_id':result['document']['document_id'],'research_id':result['research_id'],'v1_event_types':old,'v2_event_types':new,'v1_basis':snapshot['v1_basis'],'v2_basis':[v['classification_basis'] for v in result['candidates']], 'primary_fact_ids':[f for v in result['candidates'] for f in v['primary_fact_ids']],'flags':flags,'human_evaluation':human,'warnings':snapshot['warnings']}
    Comparison.model_validate(p);return p
