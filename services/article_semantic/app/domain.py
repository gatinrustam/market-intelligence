import copy,hashlib,json,re
from datetime import datetime,timezone
from uuid import uuid5,NAMESPACE_URL
from pathlib import Path
from app.schema import Output

def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def uid(*parts):return str(uuid5(NAMESPACE_URL,':'.join(map(str,parts))))
def iso(t):return t.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def identity(di,c):return uid('article.semantic.v1',di['intelligence_id'],c['version'])
def load_configuration(settings,policy_file="policy.v1.json"):
    directory=settings.configuration_dir
    c=json.loads((directory/policy_file).read_text())
    c['ontology']=json.loads((directory/c.get('ontology_file','ontology.v1.json')).read_text())
    c['models']=json.loads((directory/'models.lock.json').read_text())
    c['artifacts']=json.loads((directory/'model-artifacts.lock.json').read_text())
    if not 0<=c['concept_threshold']<=c['high_threshold']<=1 or not 32<=c['max_chunk_tokens']<=384:raise ValueError('Invalid semantic policy')
    ids=[x['id'] for x in c['ontology']['concepts']]
    if len(set(ids))!=len(ids) or any(not x['descriptions'].get('en') or not x['descriptions'].get('ru') for x in c['ontology']['concepts']):raise ValueError('Ontology must be unique and bilingual')
    if c.get('reranking_policy_file'):
        c['reranking']=json.loads((directory/c['reranking_policy_file']).read_text())
        c['baseline_configuration']=load_configuration(settings,c['baseline_policy_file'])
    return c

def chunk_document(document_id,body,sentences,max_tokens,count_tokens):
    """Lossless Unicode character partition. Oversized sentences split without truncation."""
    boundaries=sorted({0,len(body),*[s['end_char'] for s in sentences if 0<s['end_char']<=len(body)],
        *[m.end() for m in re.finditer(r'\n\s*\n',body)]})
    chunks=[];start=0
    while start<len(body):
        end=start
        for boundary in boundaries:
            if boundary<=start:continue
            if count_tokens(body[start:boundary])<=max_tokens:end=boundary
            else:break
        if end==start:
            lo,hi=start+1,len(body)
            while lo<=hi:
                mid=(lo+hi)//2
                if count_tokens(body[start:mid])<=max_tokens:end=mid;lo=mid+1
                else:hi=mid-1
            if end==start:raise ValueError('One character exceeds tokenizer budget')
        text=body[start:end]
        ids=[s['sentence_id'] for s in sentences if s['start_char']<end and s['end_char']>start]
        chunks.append({'chunk_id':uid(document_id,start,end),'document_id':document_id,'start_char':start,'end_char':end,
            'text':text,'sentence_ids':ids,'token_count':count_tokens(text)})
        start=end
    if ''.join(c['text'] for c in chunks)!=body:raise ValueError('Chunk coverage violation')
    return chunks

def evidence(document_id,body,chunks,start,end,limit=None):
    if limit is not None:end=min(end,start+limit)
    if not 0<=start<end<=len(body):raise ValueError('Invalid evidence span')
    chunk=next(c for c in chunks if c['start_char']<=start<c['end_char'])
    return {'document_id':document_id,'chunk_id':chunk['chunk_id'],'start_char':start,'end_char':end,'text':body[start:end]}

def _build_base_result(di,snapshot,c,observed):
    doc=snapshot['document'];body=doc['content']['body'];did=di['document']['document_id'];key=identity(di,c)
    chunks=observed['chunks'];refs=[{k:v for k,v in chunk.items() if k!='text'} for chunk in chunks]
    def ev(span,limit=None):return evidence(did,body,chunks,span['start_char'],span['end_char'],limit)
    matches=[]
    for hit in observed['matches']:
        chunk=next(x for x in chunks if x['chunk_id']==hit['chunk_id'])
        matches.append({**hit,'evidence':ev(chunk,360),'model_version':c['models']['bge']['revision'],'ontology_version':c['ontology']['version']})
    concepts=[];ontology={x['id']:x for x in c['ontology']['concepts']}
    for cid in sorted(ontology):
        hits=sorted([m for m in matches if m['concept_id']==cid and m['similarity']>=c['concept_threshold']],key=lambda m:-m['similarity'])
        if hits:concepts.append({'concept_id':cid,'strength':'high' if hits[0]['similarity']>=c['high_threshold'] else 'medium','max_similarity':hits[0]['similarity'],'matches':hits})
    active={x['concept_id']:x for x in concepts};domains=sorted({d for x in active for d in ontology[x]['domains']})
    entities=[]
    for source in di['entities']:
        span=ev(source['evidence'])
        entities.append({'entity_id':source['entity_id'],'name':source['canonical_name'],'type':source['type'],'extractor':'di','confidence':None,
            'evidence':[span],'status':'deterministic'})
    for source in observed['entities']:
        entities.append({'entity_id':uid(key,'gliner',source['start_char'],source['end_char'],source['label']),
            'name':body[source['start_char']:source['end_char']],'type':source['label'],'extractor':'gliner','confidence':source['score'],
            'evidence':[ev(source)],'status':'candidate'})
    grouped={}
    for e in entities:
        group=(e['extractor'],e['entity_id'],e['type'])
        if group in grouped:grouped[group]['evidence']+=e['evidence']
        else:grouped[group]=e
    entities=list(grouped.values())
    facts=copy.deepcopy(di['facts']);claims=[];relations=[];fact_by_relation={f['relation_id']:f for f in facts}
    for fact in facts:
        claims.append({'claim_id':uid(key,'fact',fact['fact_id']),'type':fact['fact_type'],'subject':fact['subject']['entity_id'],
            'action':fact['action'],'object_value':canonical([{k:m[k] for k in ('kind','value','min','max','unit')} for m in fact['values']]),
            'evidence':ev(fact['evidence']),'extractor':'di','supporting_fact_ids':[fact['fact_id']],'status':'deterministic','reason':'Exact DI rule-backed fact; takes precedence over semantic candidates'})
    for r in di['relations']:
        relations.append({'relation_id':r['relation_id'],'subject':r['subject']['entity_id'],'predicate':r['action'],'object':r['object']['text'],
            'extractor':'di','confidence':None,'support_method':'DI linked dependency/rule extraction','status':'deterministic','evidence':ev(r['evidence']),
            'supporting_fact_ids':[fact_by_relation[r['relation_id']]['fact_id']] if r['relation_id'] in fact_by_relation else []})
    # GLiNER is NER, not a relation classifier. Entity-guided candidates need an explicit
    # predicate span in the same sentence; model confidence is entity confidence only.
    patterns=r'(?i)\b(suspended|halted|acquired|purchased|reported|proposed|charged|appointed|resigned|приостановила|приостановил|приобрела|купила|сообщила|предложила|предъявила|назначила|ушёл|ушел)\b'
    if c.get('require_named_asset_relation'):patterns=patterns.replace('resigned|','resigned|approved|одобрил|одобрила|')
    for sentence in di['sentences']:
        text=body[sentence['start_char']:sentence['end_char']]
        es=[e for e in entities if e['extractor']=='gliner' and any(sentence['start_char']<=sp['start_char']<sp['end_char']<=sentence['end_char'] for sp in e['evidence'])]
        predicate=re.search(patterns,text)
        if predicate and es:
            predicate_start=sentence['start_char']+predicate.start()
            subjects=[(sp['end_char'],e) for e in es if e['type'] in ('organization','company','person') for sp in e['evidence']
                if sentence['start_char']<=sp['start_char'] and sp['end_char']<=predicate_start]
            if not subjects:continue
            subject=max(subjects,key=lambda pair:pair[0])[1]
            objects=[(sp['start_char'],e) for e in es for sp in e['evidence']
                if predicate_start+len(predicate.group())<=sp['start_char']<sp['end_char']<=sentence['end_char']]
            obj=min(objects,key=lambda pair:pair[0])[1] if objects else None
            span=ev(sentence,c.get('claim_excerpt_limit',600));relation={'relation_id':uid(key,'gliner_relation',sentence['sentence_id']),
                'subject':subject['name'],'predicate':predicate.group(),'object':obj['name'] if obj else None,
                'extractor':'gliner','confidence':min(subject['confidence'],obj['confidence']) if obj else subject['confidence'],'support_method':'GLiNER entity candidates plus explicit same-sentence predicate rule; not model relation probability',
                'status':'candidate','evidence':span,'supporting_fact_ids':[]}
            relations.append(relation)
            if not any(f['evidence']['start_char']<=sentence['start_char']<f['evidence']['end_char'] for f in facts):
                claims.append({'claim_id':uid(key,'gliner_claim',sentence['sentence_id']),'type':'entity_supported_statement',
                    'subject':relation['subject'],'action':relation['predicate'],'object_value':relation['object'],
                    'evidence':span,'extractor':'gliner','supporting_fact_ids':[],'status':'supported_candidate','reason':relation['support_method']})
    # Extractive claims are exact sentences ranked by semantic support; no generated summary.
    candidates=[]
    for sentence in di['sentences']:
        if sentence['end_char']>len(body):raise ValueError('DI sentence beyond body')
        text=body[sentence['start_char']:sentence['end_char']]
        if len(text.strip())<40 or any(x['evidence']['start_char']<=sentence['start_char']<x['evidence']['end_char'] for x in claims):continue
        chunk_ids={ch['chunk_id'] for ch in chunks if ch['start_char']<sentence['end_char'] and ch['end_char']>sentence['start_char']}
        hits=[h for h in matches if h['chunk_id'] in chunk_ids and h['similarity']>=c['concept_threshold']]
        if not hits:continue
        best=max(hits,key=lambda h:h['similarity']);numbers=any(m['evidence']['start_char']>=sentence['start_char'] and m['evidence']['end_char']<=sentence['end_char'] for m in di['measurements'])
        candidates.append((best['similarity']+(.05 if numbers else 0),sentence,best['concept_id']))
    for _,sentence,cid in sorted(candidates,key=lambda x:(-x[0],x[1]['start_char'])):
        if len(claims)>=c['max_claims']:break
        claims.append({'claim_id':uid(key,'semantic_claim',sentence['sentence_id']),'type':cid,'subject':None,'action':None,'object_value':None,
            'evidence':ev(sentence,c.get('claim_excerpt_limit',600)),'extractor':'semantic','supporting_fact_ids':[],'status':'semantic_candidate','reason':'Exact text selected from a concept-supported chunk; thematic similarity is not verification of this assertion'})
    def concept_evidence(ids):return [m['evidence'] for cid in ids if cid in active for m in active[cid]['matches'][:2]]
    macro=[cid for cid in active if 'macroeconomics' in ontology[cid]['domains'] or 'monetary_policy' in ontology[cid]['domains']]
    crypto=[cid for cid in active if 'digital_assets' in ontology[cid]['domains']]
    assets=[]
    def asset(name,level,basis,spans,direct=False):
        if spans:assets.append({'asset':name,'relevance':level,'basis':basis,'evidence':spans[:4],'direct':direct})
    if macro:
        asset('rates','high' if facts else 'medium',['Policy/inflation/employment context; candidate market exposure, not a predicted price move'],concept_evidence(macro))
        if doc['source']['id']=='fed_monetary_policy':asset('USD','high' if facts else 'medium',['US official macro source plus supported macro concepts'],concept_evidence(macro))
        if doc['source']['id']=='ecb_press':asset('EUR','high' if facts else 'medium',['Euro-area official macro source plus supported macro concepts'],concept_evidence(macro))
    if crypto:asset('crypto_market','medium',['Supported digital-asset concept; broad market candidate'],concept_evidence(crypto))
    aliases_by_asset=c.get('asset_aliases',{'BTC':['bitcoin','биткоин','btc'],'ETH':['ethereum','эфириум','eth'],'gold':['gold','золото']})
    for name,aliases in aliases_by_asset.items():
        named=[e for e in entities if e['name'].casefold() in aliases]
        spans=[sp for e in named for sp in e['evidence'] if any(m['chunk_id']==sp['chunk_id'] for cid in crypto for m in active[cid]['matches'])]
        if c.get('require_named_asset_relation'):
            support=[f['evidence'] for f in facts]+[r['evidence'] for r in relations if r['status']=='candidate']
            spans=[sp for sp in spans if any(e['start_char']<=sp['start_char']<sp['end_char']<=e['end_char'] for e in support)]
        if name=='gold':spans=[] # No gold-specific semantic concept in v1; mention alone is insufficient.
        if spans:asset(name,'medium',['Named asset in a DI fact or entity-predicate candidate and a supported digital-asset context' if c.get('require_named_asset_relation') else 'Explicit extracted asset mention inside a supported digital-asset context; not mention-only relevance'],spans,True)
    equity=[cid for cid in ('equities','earnings','merger_acquisition') if cid in active]
    if equity:
        companies=[e for e in entities if e['type']=='company']
        if companies:asset('specific_company','medium',['Extracted company with supported equity/earnings/M&A context'],[sp for e in companies for sp in e['evidence']][:4],True)
        if doc['source']['id']=='sec_press_releases':asset('US_equities','medium',['US securities source and supported equity context'],concept_evidence(equity))
    # DI type always wins. A semantic-only type remains a research candidate.
    facttypes={f['fact_type'] for f in facts};article_type='unknown';typebasis=[]
    if any(x.startswith('monetary_policy.rate_decision') for x in facttypes):article_type='primary_announcement'
    elif any(x.startswith('regulation.') for x in facttypes):article_type='regulatory_action'
    elif any(x.startswith('economic_data.') for x in facttypes):article_type='data_release'
    elif any(x.startswith('crypto.') for x in facttypes):article_type='incident'
    if article_type!='unknown':typebasis.append('DI deterministic facts have precedence: '+', '.join(sorted(facttypes)))
    strongest=max(concepts,key=lambda x:x['max_similarity']) if concepts else None
    semantic_type=ontology[strongest['concept_id']]['article_type'] if strongest else 'unknown'
    title=doc['content']['title'];lower=title.casefold()
    if not facts:
        article_type=semantic_type;typebasis.append('Best supported concept: '+(strongest['concept_id'] if strongest else 'none'))
        # Structure/title only modifies a semantic-supported document, never creates support.
        if concepts and re.search(r'\b(interview|интервью)\b',lower):article_type='interview';typebasis.append('Interview title/structure with semantic-supported body')
        elif concepts and re.search(r'\b(speech|remarks|выступление|речь)\b',lower):article_type='speech';typebasis.append('Speech title/structure with semantic-supported body')
    if c.get('structure_type_signals') and (concepts or facts):
        header=re.search(r'(?im)^\s*[-#]?\s*(INTERVIEW|SPEECH|REMARKS|ИНТЕРВЬЮ|ВЫСТУПЛЕНИЕ|РЕЧЬ)\s*$',body[:256])
        if header:
            article_type='interview' if header.group(1).casefold() in ('interview','интервью') else 'speech'
            typebasis.append('Explicit document format: '+header.group(1)+'; all underlying DI facts retained')
    conflicts=[]
    if facts and strongest and strongest['strength']=='high' and semantic_type in ('personnel','administrative','incident') and semantic_type!=article_type:
        conflicts.append({'status':'conflict','deterministic_fact_ids':[f['fact_id'] for f in facts],'semantic_concept_ids':[strongest['concept_id']],
            'reason':'Dominant semantic genre disagrees with deterministic fact classification; DI retained, both layers visible','evidence':[m['evidence'] for m in strongest['matches'][:2]]})
    def feat(level,reason,spans=None):return {'level':level,'reasons':[reason],'evidence':spans or []}
    allspans=[x['evidence'] for x in claims[:3]]
    official=doc['source']['id'] in c['official_sources'];partial=doc['enrichment']['status']!='ready'
    substantive=any(cid not in ('general_commentary','personnel','administrative') for cid in active)
    relevance='high' if facts else 'medium' if substantive else 'low' if concepts else 'none'
    if article_type in ('personnel','administrative') and not facts:relevance='low'
    features={'market_relevance':feat(relevance,'Rule-backed financial facts' if facts else 'Thematic market context only; unverified event candidates',allspans),
        'crypto_relevance':feat('medium' if crypto else 'none','Digital asset concepts present' if crypto else 'No supported digital asset context',concept_evidence(crypto)),
        'macro_relevance':feat('high' if macro and facts else 'medium' if macro else 'none','Macro concepts with DI fact support' if macro and facts else 'Macro concept evidence' if macro else 'No supported macro context',concept_evidence(macro)),
        'event_specificity':feat('high' if facts else 'medium' if any(r['extractor']=='gliner' for r in relations) else 'low','DI facts / entity-predicate candidates / topic-only evidence hierarchy',allspans),
        'information_density':feat('high' if len(facts)>=2 else 'medium' if len(claims)>=3 else 'low','Distinct retained claims and rule-backed facts; not a length-only score',allspans),
        'actionability':feat('medium' if facts and not partial else 'low' if claims else 'none','Research triage only; no investment or trading action is inferred',allspans),
        'source_quality':feat('high' if official else 'medium','Configured official primary source' if official else 'Source not in official-primary registry'),
        'document_quality':feat('low' if partial else 'high','Partial/RSS observed content; full original article may be unavailable' if partial else 'Full body of the stored enriched document processed'),
        'semantic_strength':feat('high' if any(x['strength']=='high' for x in concepts) else 'medium' if concepts else 'none','Thresholded cosine similarity, not a probability',concept_evidence([x['concept_id'] for x in concepts[:3]])),
        'fact_support':feat('high' if facts else 'none','Exact DI fact IDs retained' if facts else 'No deterministic facts; semantic claims remain candidates',[ev(f['evidence']) for f in facts[:3]])}
    route='important' if relevance=='high' or (relevance=='medium' and official and not partial and any(x['strength']=='high' for x in concepts)) else 'review' if relevance=='medium' or partial else 'low'
    old=snapshot.get('old_route');warnings=list(observed['warnings'])+list(snapshot.get('warnings',[]))
    if partial:warnings.append('Observed body is partial/RSS; no missing source text was invented')
    warnings.append('Cosine similarity is not probability; model confidence is uncalibrated; extractive claims are not independently verified')
    status='failed' if not observed['embedding_available'] else 'partial' if warnings and (partial or not observed['gliner_available']) else 'complete'
    provenance={'semantic_model':c['models']['bge']['model'],'semantic_model_revision':c['models']['bge']['revision'],
        'semantic_model_hash':c['artifacts']['bge/pytorch_model.bin']['sha256'],'gliner_model':c['models']['gliner']['model'],
        'gliner_model_revision':c['models']['gliner']['revision'],'gliner_model_hash':c['artifacts']['gliner/model.safetensors']['sha256'],
        'gliner_backbone_revision':c['models']['gliner_backbone']['revision'],'ontology_version':c['ontology']['version'],
        'threshold_version':c['threshold_version'],'pipeline_version':c['version'],'chunking_version':c['chunking_version'],
        'configuration_hash':digest(c),'input_hash':digest(di),'runtime_versions':observed['runtime_versions'],'dtype':c['dtype']}
    if c.get('encoder_artifact'):provenance['semantic_runtime_hash']=c['artifacts'][c['encoder_artifact']]['sha256']
    result={'schema_version':'1.0','message_id':key,'semantic_id':key,'mode':'research','document':{
        **di['document'],'intelligence_id':di['intelligence_id'],'title':title,'source_id':doc['source']['id'],'source_url':doc['source']['url'],
        'language':di['language'],'published_at':doc['timestamps']['published_at'],'body_characters':len(body),'document_status':doc['enrichment']['status']},
        'status':status,'domains':domains,'chunks':refs,'semantic_concepts':concepts,'top_matches':matches,'entities':entities,'relations':relations,'facts':facts,'claims':claims,
        'affected_assets':assets,'article_type':article_type,'article_type_basis':typebasis,'information_value':features,'important_numbers':di['measurements'],
        'conflicts':conflicts,'routing':{'old_route':old['route'] if old else None,'old_routing_id':old['routing_id'] if old else None,
            'semantic_suggested_route':route,'disagreement':route!=old['route'] if old else None,'production_switch':False,
            'reasons':['Semantic triage considers full observed body; DI-2 output unchanged',*features['market_relevance']['reasons'],*features['document_quality']['reasons']]},
        'provenance':provenance,'warnings':warnings,'performance':observed['performance'],'generated_at':iso(datetime.now(timezone.utc))}
    Output.model_validate(result)
    return result

def insight(result):
    from app.presentation import present_insight
    return present_insight(result)


def build_result(di,snapshot,c,observed):
    base=_build_base_result(di,snapshot,c,observed)
    if not c.get('reranking'):return base
    try:
        from app.reranking import rerank
        result=rerank(base,di,snapshot,c,observed)
        Output.model_validate(result)
        return result
    except Exception as exc:
        # A failed reranker never hides the separately persisted DI-5 base result.
        base['status']='partial' if observed['embedding_available'] else 'failed'
        base['warnings'].append('reranker_failed:'+type(exc).__name__)
        base['reranking']={'policy_version':c['reranking']['version'],'status':'failed','decisions':[],
            'claim_decisions':[],'importance_components':{},'latency_seconds':0.0}
        return base
