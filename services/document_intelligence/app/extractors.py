"""Rules consume detached NLP tokens, never a vendor-specific NLP API."""
import re,hashlib
from decimal import Decimal
from datetime import date
from app.domain import uid

def explain(doc_id,sentence,body,start,end,extractor,rule,method='rule_based'):
    if not sentence.start<=start<end<=sentence.end:raise ValueError('span outside sentence')
    return {'evidence':{'document_id':doc_id,'sentence_id':sentence.id,'start_char':start,'end_char':end,'text':body[start:end]},
        'extraction':{'method':method,'extractor':extractor,'rule_id':rule,'extractor_version':'1.0'}}
def ref(e):return {k:e[k] for k in ('entity_id','mention_id')}
def norm(n,language="en"):
    n=n.strip().replace(' ','').replace('‑','-').replace('−','-')
    if language=='en' and re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?',n):n=n.replace(',','')
    else:n=n.replace(',','.')
    if re.fullmatch(r'\d+-\d+/\d+',n):
        whole,fraction=n.split('-');a,b=fraction.split('/');return format(Decimal(whole)+Decimal(a)/Decimal(b),'f')
    if re.fullmatch(r'\d+/\d+',n):
        a,b=n.split('/');return format(Decimal(a)/Decimal(b),'f')
    return format(Decimal(n),'f')
class EntityExtractor:
    def extract(self,nlp,body,doc_id,language,config):
        result=[];registry=config['registry']['entities'];present=set()
        for conditional in (False,True):
            for s in nlp.sentences:
                candidates=[]
                for row in registry:
                    if bool(row.get('requires'))!=conditional:continue
                    if row.get('requires') and row['requires'] not in present:continue
                    for alias in row['aliases'].get(language,[]):
                        for m in re.finditer(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',s.text,0 if row.get('case_sensitive') else re.I):candidates.append((m.start()+s.start,m.end()+s.start,row))
                for start,end,row in sorted(candidates,key=lambda x:-(x[1]-x[0])):
                    if any(start<e['evidence']['end_char'] and end>e['evidence']['start_char'] for e in result):continue
                    result.append({'mention_id':uid(doc_id,'entity',start,end,row['entity_id']),'entity_id':row['entity_id'],'canonical_name':row['canonical_name'],'type':row['type'],'registry':True,**explain(doc_id,s,body,start,end,'entity_registry','alias.'+row['entity_id'],'registry')});present.add(row['entity_id'])
        for ne in nlp.entities:
            typ={'ORG':'organization','PERSON':'person','PER':'person','GPE':'location','LOC':'location'}.get(ne.label)
            if typ is None or any(ne.start<e['evidence']['end_char'] and ne.end>e['evidence']['start_char'] for e in result):continue
            s=next((s for s in nlp.sentences if s.start<=ne.start<ne.end<=s.end),None)
            if not s:continue
            text=body[ne.start:ne.end];entity_id=typ+':mention:'+hashlib.sha256(text.casefold().encode()).hexdigest()[:20]
            result.append({'mention_id':uid(doc_id,'entity',ne.start,ne.end,entity_id),'entity_id':entity_id,'canonical_name':text,'type':typ,'registry':False,**explain(doc_id,s,body,ne.start,ne.end,'spacy_ner','ner.'+ne.label,'statistical_ner')})
        return sorted(result,key=lambda e:(e['evidence']['start_char'],e['entity_id']))

NUMBER=r'[-−]?\d+(?:[-‑]\d+/\d+|/\d+|[.,]\d+)?'
RANGE=re.compile(r'(?<![\w.,])('+NUMBER+r')\s*(?:%\s*)?(?:–|—|\bto\b|\bдо\b|-)\s*('+NUMBER+r')\s*(%|percent\b|процент\w*)',re.I)
UNITS=re.compile(r'(?<![\w.,])('+NUMBER+r')\s*(percentage\s+points?|basis\s+points?|bps\b|б\.?\s*п\.|п\.?\s*п\.|%|percent(?:age)?\b|процент(?:а|ов)?\b)',re.I)
MONEY=re.compile(r'(?<!\w)(?:(?P<c1>USD|EUR|\$|€)\s*(?P<n1>'+NUMBER+r'(?:,\d{3})*)\s*(?P<s1>million|billion|млн|млрд)?|(?P<n2>'+NUMBER+r'(?:,\d{3})*)\s*(?P<s2>million|billion|млн|млрд)?\s*(?P<c2>USD|EUR|dollars?|euros?|доллар\w*|евро))(?!\w)',re.I)
class MeasurementExtractor:
    def extract(self,nlp,body,doc_id,language,*_):
        out=[]
        number=lambda value:norm(value,language)
        def add(s,m,kind,value=None,minimum=None,maximum=None,unit=None,currency=None,rule=None):
            start,end=s.start+m.start(),s.start+m.end()
            if any(start<x['evidence']['end_char'] and end>x['evidence']['start_char'] for x in out):return
            out.append({'measurement_id':uid(doc_id,'measurement',start,end,kind),'kind':kind,'value':value,'min':minimum,'max':maximum,'unit':unit,'currency':currency,**explain(doc_id,s,body,start,end,'measurements',rule or 'measurement.'+kind+'.v1')})
        for s in nlp.sentences:
            for m in RANGE.finditer(s.text):
                lo,hi=number(m[1]),number(m[2])
                if Decimal(lo)<=Decimal(hi):add(s,m,'rate',minimum=lo,maximum=hi,unit='percent')
            for m in UNITS.finditer(s.text):
                value=number(m[1]);u=m[2].lower()
                if u.startswith(('basis','bps','б')):kind='basis_points';unit='percentage_points';value=format(Decimal(value)/100,'f')
                elif u.startswith(('percentage point','п.','пп')):kind='percentage_points';unit='percentage_points'
                else:kind='percentage';unit='percent'
                add(s,m,kind,value=value,unit=unit)
            for m in MONEY.finditer(s.text):
                raw=m['n1'] or m['n2'];currency=m['c1'] or m['c2'];scale=(m['s1'] or m['s2'] or '').lower();value=Decimal(number(raw))*({'million':10**6,'млн':10**6,'billion':10**9,'млрд':10**9}.get(scale,1))
                curr='EUR' if currency.lower() in ('eur','€','euro','euros','евро') else 'USD'
                kind='price' if re.search(r'\b(?:price|traded|цена|торговал)\w*\b',s.text[:m.start()],re.I) else 'money'
                add(s,m,kind,value=format(value,'f'),unit=curr,currency=curr)
            for m in re.finditer(r'(?<!\w)('+NUMBER+r')\s*(BTC|ETH|bitcoins?|биткоин\w*|shares?|акци\w*)(?!\w)',s.text,re.I):
                unit='BTC' if m[2].lower().startswith(('btc','bitcoin','биткоин')) else 'ETH' if m[2].lower()=='eth' else 'shares'
                add(s,m,'quantity',value=number(m[1]),unit=unit)
            for m in re.finditer(r'(?<![\d:])('+NUMBER+r')\s*:\s*('+NUMBER+r')(?![\d:])',s.text):
                if re.fullmatch(r'\d{1,2}:\d{2}',m[0]) and not re.search(r'\bratio\b|\bсоотношен\w*',s.text,re.I):continue
                add(s,m,'ratio',value=number(m[1])+':'+number(m[2]),unit='ratio')
        return sorted(out,key=lambda x:x['evidence']['start_char'])

MONTHS={n.lower():i for i,n in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'],1)}
MONTHS.update({n:i for i,n in enumerate(['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'],1)})
class DateExtractor:
    def extract(self,nlp,body,doc_id,*_):
        out=[]
        patterns=[('date_range',r'\b\d{4}-\d{2}-\d{2}\s*(?:to|–|—|до)\s*\d{4}-\d{2}-\d{2}\b'),('date',r'\b\d{4}-\d{2}-\d{2}\b'),('date',r'\b(?:'+ '|'.join(list(MONTHS)[:12])+r')\s+\d{1,2}(?:,?\s+\d{4})?\b'),('date',r'\b\d{1,2}\s+(?:'+'|'.join(list(MONTHS))+r')(?:\s+\d{4})?\b'),('time',r'\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s*(?:UTC|GMT|ET|EST|EDT|MSK|CET|CEST))?\b'),('period',r'\b(?:Q[1-4]\s+\d{4}|\d{4}\s+Q[1-4]|[1-4]\s+квартал\s+\d{4})\b')]
        for s in nlp.sentences:
            for kind,pattern in patterns:
                for m in re.finditer(pattern,s.text,re.I):
                    start,end=s.start+m.start(),s.start+m.end()
                    if any(start<d['evidence']['end_char'] and end>d['evidence']['start_char'] for d in out):continue
                    raw=m[0];normalized=None
                    try:
                        if kind=='date_range':normalized='/'.join(date.fromisoformat(v).isoformat() for v in re.findall(r'\d{4}-\d{2}-\d{2}',raw))
                        elif kind=='date':
                            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw):normalized=date.fromisoformat(raw).isoformat()
                            else:
                                nums=re.findall(r'\d+',raw);month=next(v for k,v in MONTHS.items() if k in raw.lower())
                                if len(nums)==2:normalized=date(int(nums[1]),month,int(nums[0])).isoformat()
                        elif kind=='time':normalized=raw.upper() # No date or timezone inferred.
                        else:normalized=raw
                    except (ValueError,StopIteration):continue
                    out.append({'date_id':uid(doc_id,'date',start,end),'kind':kind,'raw':raw,'normalized':normalized,**explain(doc_id,s,body,start,end,'dates','date.'+kind+'.v1')})
        return sorted(out,key=lambda x:x['evidence']['start_char'])

class RelationExtractor:
    def extract(self,nlp,body,doc_id,language,config,entities):
        relations=[]
        for s in nlp.sentences:
            tokens={t.id:t for t in s.tokens}
            def descendants(root,clause=False):
                found={root};pending=[root]
                while pending:
                    head=pending.pop()
                    for t in s.tokens:
                        if t.head==head and t.id not in found:
                            if clause and t.dep in ('conj','advcl','ccomp','parataxis','relcl','acl:relcl'):continue
                            found.add(t.id);pending.append(t.id)
                return found
            def entity_for(ids):
                return [e for e in entities if any(t.id in ids and e['evidence']['start_char']<=t.start<e['evidence']['end_char'] for t in s.tokens)]
            for verb in s.tokens:
                if verb.pos not in ('VERB','AUX'):continue
                for rule in config['rules']['rules']:
                    if verb.lemma not in rule['lemmas'].get(language,[]):continue
                    chain=[verb];v=verb
                    while v.dep in ('xcomp','conj') and v.head in tokens and v.head!=v.id:
                        v=tokens[v.head];chain.append(v)
                    scope=descendants(verb.id,True)
                    guards=set(scope)|{t.id for t in chain}
                    # Scope includes auxiliaries/negation on controlling verbs, not an unrelated clause.
                    guards|={t.id for t in s.tokens if t.head in {x.id for x in chain}}
                    if any(t.id in guards and (t.dep=='neg' or t.lemma in ('not','never','no','не','никогда','ни')) for t in s.tokens):continue
                    subjects=[]
                    for head in chain:
                        subjects=[t for t in s.tokens if t.head==head.id and t.dep in ('nsubj','csubj')]
                        if subjects:break
                    candidates=entity_for(set().union(*(descendants(t.id) for t in subjects))) if subjects else []
                    candidates=[e for e in candidates if e['type'] in ('organization','person','economic_indicator')]
                    if rule.get('subject_entity'):candidates=[e for e in candidates if e['entity_id']==rule['subject_entity']]
                    if rule.get('crypto_subject_required'):candidates=[e for e in candidates if e['entity_id'] in ('organization:binance','organization:coinbase','organization:kraken','organization:tether','organization:circle','organization:strategy')]
                    if not candidates:continue
                    subject=next((e for e in candidates if e['registry']),candidates[0])
                    if rule['fact_type'].startswith('monetary_policy.') and subject['entity_id'] not in ('organization:federal_reserve','organization:ecb'):continue
                    if (rule['fact_type'].startswith('regulation.') or rule['fact_type']=='crypto.etf_action') and subject['entity_id']!='organization:sec':continue
                    objects=[t for t in s.tokens if t.head==verb.id and t.dep in (('dobj','obj','attr','oprd','prep','obl') if rule.get('requires_measurement') else ('dobj','obj','attr','oprd'))]
                    if not objects:continue
                    objids=set().union(*(descendants(t.id,True) for t in objects))
                    objtokens=[t for t in s.tokens if t.id in objids]
                    start,end=min(t.start for t in objtokens),max(t.end for t in objtokens)
                    objtext=body[start:end];mentions=entity_for(objids)
                    wanted=rule.get('object_entities',[])
                    if wanted and not any(e['entity_id'].split(':')[-1] in wanted for e in mentions):continue
                    pattern=rule.get('object_patterns',{}).get(language)
                    clause_text=body[min(tokens[k].start for k in scope):max(tokens[k].end for k in scope)]
                    if rule.get('requires_measurement'):
                        # A benchmark/target in prose is not an observed indicator value.
                        if re.search(r'\b(?:goal|target|forecast|project|expect|relative)\w*|целев|прогноз|ожида',s.text,re.I):continue
                        # Do not promote a coordinated shock or other noun via inherited subject.
                        if verb.dep=='conj' and not any(t.head==verb.id and t.dep=='nsubj' for t in s.tokens):continue
                    if pattern and not re.search(pattern,clause_text,re.I):continue
                    if rule['action']=='suspend' and not re.search(pattern,objtext,re.I):continue
                    if rule['action']=='suspend' and subject['entity_id'] not in (('organization:binance','organization:coinbase','organization:kraken') if config['rules'].get('structured_treasury_version') else ('organization:binance','organization:coinbase')) and not any(e['type']=='asset' for e in mentions):continue
                    object_entity=next((e for e in mentions if e['entity_id']!=subject['entity_id']),None)
                    modality='forward_looking' if any(t.id in guards and t.lemma in ('may','might','could','will','would','plan','expect','intend','мочь','планировать','ожидать') for t in s.tokens) or any(t.lemma in ('if','если') for t in s.tokens) else 'asserted'
                    relations.append({'relation_id':uid(doc_id,'relation',verb.start,rule['id']),'subject':ref(subject),'action':rule['action'],'predicate':{'text':verb.text,'start_char':verb.start,'end_char':verb.end},
                        'object':{'entity_id':object_entity['entity_id'] if object_entity else None,'mention_id':object_entity['mention_id'] if object_entity else None,'text':objtext,'start_char':start,'end_char':end},'modality':modality,
                        **explain(doc_id,s,body,s.start,s.end,'dependency_relations',rule['id'],'dependency_rule')})
        return relations
class FactExtractor:
    def extract(self,nlp,body,doc_id,language,config,relations,measurements):
        facts=[];rules={r['id']:r for r in config['rules']['rules']}
        for r in relations:
            rule=rules[r['extraction']['rule_id']]
            announced = bool(config['rules'].get('structured_treasury_version') and rule['fact_type'] in ('crypto.exchange_listing','crypto.exchange_delisting') and re.search(r'\bwill\s+(?:list|delist|remove)\b',r['evidence']['text'],re.I) and not re.search(r'\b(?:if|may|might|could|would)\b',r['evidence']['text'],re.I))
            if r['modality']!='asserted' and not announced:continue
            sid=r['evidence']['sentence_id'];s=nlp.sentences[sid]
            values=[m for m in measurements if m['evidence']['sentence_id']==sid]
            if rule['fact_type']=='monetary_policy.rate_decision':values=[m for m in values if m['kind'] in ('rate','percentage','percentage_points','basis_points')]
            elif rule['action']=='purchase' or (config['rules'].get('structured_treasury_version') and rule['fact_type'] in ('crypto.treasury_sale','crypto.treasury_holdings')):values=[m for m in values if m['kind'] in ('quantity','money','price')]
            elif rule.get('requires_measurement'):
                # More than one number can mix actuals, thresholds and comparisons.
                if len(values)!=1:continue
            else:values=[]
            # Multiple distinct action clauses make sentence-wide value attachment unsafe.
            if sum(x['evidence']['sentence_id']==sid for x in relations)>1:values=[]
            facts.append({'fact_id':uid(doc_id,'fact',r['relation_id'],rule['fact_type']),'fact_type':rule['fact_type'],'subject':r['subject'],'action':('announced_'+r['action']) if announced else r['action'],'relation_id':r['relation_id'],'values':values,**explain(doc_id,s,body,s.start,s.end,'domain_facts',rule['id'])})
        return facts
class TopicExtractor:
    def extract(self,nlp,body,doc_id,language,config,facts,entities):
        out=[];rules={r['id']:r for r in config['rules']['rules']}
        for fact in facts:
            s=nlp.sentences[fact['evidence']['sentence_id']]
            topics=list(rules[fact['extraction']['rule_id']]['topics'])
            if fact['fact_type'].startswith('crypto.'):
                for name in ('bitcoin','ethereum'):
                    if any(e['entity_id']=='asset:'+name and e['evidence']['sentence_id']==s.id for e in entities):topics.append(name)
            for topic in topics:out.append({'topic':topic,'fact_ids':[fact['fact_id']],**explain(doc_id,s,body,s.start,s.end,'fact_topics','topic.'+topic+'.v1')})
        return out
