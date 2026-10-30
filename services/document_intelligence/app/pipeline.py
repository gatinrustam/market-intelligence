import hashlib
from app.nlp import LanguageDetector,EnglishSpacyBackend,RussianSpacyBackend
from app.extractors import EntityExtractor,MeasurementExtractor,DateExtractor,RelationExtractor,FactExtractor,TopicExtractor
from app.schema import Output
from app.domain import digest,identity

class Pipeline:
    def __init__(self,configuration,auxiliaries=()):
        self.configuration=configuration;self.detector=LanguageDetector(configuration['language_profiles']);self.backends={'en':EnglishSpacyBackend(),'ru':RussianSpacyBackend()}
        self.components={'entities':EntityExtractor(),'measurements':MeasurementExtractor(),'dates':DateExtractor(),'relations':RelationExtractor(),'facts':FactExtractor(),'topics':TopicExtractor()}
        self.auxiliaries=auxiliaries
    def analyze(self,document):
        c=self.configuration;body=document['content']['body'];doc_id=document['document_id'];language=self.detector.detect(body)
        key=identity(document,c)
        out={'schema_version':'1.0','message_id':key,'intelligence_id':key,
            'document':{'document_id':doc_id,'source_message_id':document['lineage']['source_message_id'],'input_message_id':document['message_id'],'body_hash':hashlib.sha256(body.encode()).hexdigest()},
            'language':language,'language_detector':'langdetect_seed_0_rules_v1','sentences':[],**{k:[] for k in self.components},
            'extraction':{'pipeline_version':c['pipeline_version'],'entity_registry_version':c['registry']['version'],'fact_ruleset_version':c['rules']['version'],'configuration_hash':digest(c),'nlp_models':c['models']},
            'processing':{'status':'unsupported' if language=='unsupported' else 'complete','warnings':[]}}
        if language!='unsupported':
            nlp=self.backends[language].analyze(body) # Core NLP failures fail the job, never fabricate a parse.
            out['sentences']=[{'sentence_id':s.id,'start_char':s.start,'end_char':s.end} for s in nlp.sentences]
            for name,extractor in self.components.items():
                args=[nlp,body,doc_id,language,c]
                if name=='relations':args += [out['entities']]
                elif name=='facts':args += [out['relations'],out['measurements']]
                elif name=='topics':
                    if c['rules'].get('structured_treasury_version'):
                        from app.crypto import extract_labelled_purchase
                        extract_labelled_purchase(out,nlp,body)
                    args += [out['facts'],out['entities']]
                try:out[name]=extractor.extract(*args)
                except Exception as exc:
                    if name=='entities':raise # Registry/entity validation is core.
                    out['processing']['warnings'].append({'component':name,'code':type(exc).__name__});out['processing']['status']='partial'
            for auxiliary in self.auxiliaries:
                # Optional proposals are not canonical facts. Future components need an explicit versioned promotion rule.
                try:auxiliary.extract(nlp,body)
                except Exception as exc:
                    out['processing']['warnings'].append({'component':auxiliary.name,'code':type(exc).__name__});out['processing']['status']='partial'
        if document['enrichment']['status']!='ready' and language!='unsupported':
            out['processing']['status']='partial';out['processing']['warnings'].append({'component':'input','code':'partial_enrichment'})
        Output.model_validate(out)
        validate_spans(out,body)
        return out

def validate_spans(out,body):
    sentences={s['sentence_id']:s for s in out['sentences']}
    def visit(value):
        if isinstance(value,dict):
            if 'evidence' in value:
                e=value['evidence'];s=sentences[e['sentence_id']]
                if e['document_id']!=out['document']['document_id'] or not s['start_char']<=e['start_char']<e['end_char']<=s['end_char'] or body[e['start_char']:e['end_char']]!=e['text']:raise ValueError('evidence span invariant')
                if not value.get('extraction'):raise ValueError('unexplained value')
            for v in value.values():visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    visit(out)
    mentions={e['mention_id']:e for e in out['entities']}
    relations={r['relation_id']:r for r in out['relations']}
    measurements={m['measurement_id']:m for m in out['measurements']}
    facts={f['fact_id']:f for f in out['facts']}
    for r in out['relations']:
        if r['subject']['mention_id'] not in mentions:raise ValueError('unknown subject')
        for a in (r['object'],r['predicate']):
            if body[a['start_char']:a['end_char']]!=a['text']:raise ValueError('argument span invariant')
    for f in out['facts']:
        if f['relation_id'] not in relations:raise ValueError('unknown relation')
        for m in f['values']:
            if measurements.get(m['measurement_id'])!=m:raise ValueError('invented fact measurement')
    for f in out['facts']:
        if any(f.get(k) is not None for k in ('quantity','aggregate_value_usd','average_price_usd')):
            if f.get('asset')!='BTC':raise ValueError('structured treasury asset requires explicit BTC')
            for key,unit in (('quantity','BTC'),('aggregate_value_usd','USD'),('average_price_usd','USD')):
                if f.get(key) is not None and not any(m['value']==f[key] and m['unit']==unit and m['extraction']['rule_id']=='crypto.label.'+key+'.v1' for m in f['values']):raise ValueError('unfounded structured treasury value')
    for t in out['topics']:
        if any(i not in facts for i in t['fact_ids']):raise ValueError('unfounded topic')
