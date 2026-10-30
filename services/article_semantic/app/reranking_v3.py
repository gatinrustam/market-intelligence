"""Deterministic, versioned precision layer. No model calls and no label learning.
All support is tied to exact source sentences; negative cosine is contrastive
retrieval evidence, never a probability or proof that a statement is false.
"""
import copy,re,time
from statistics import mean
from app.domain import digest,uid,evidence


def match(pattern,text):return bool(re.search(pattern,text,re.I|re.S))

def useful_sentence(sentence,body,title,minimum=45):
    start,end=sentence['start_char'],sentence['end_char'];text=body[start:end]
    # Remove only explicit source metadata lines, preserving absolute offsets.
    for line in text.splitlines(keepends=True):
        stripped=line.strip(' #\t\r\n-')
        if not stripped or stripped==title.strip() or (len(stripped)>15 and title.strip().endswith(stripped)) or match(r'^(Keynote speech by|Speech by|Interview with|Interview .*conducted by|(?:[A-Z][a-z]+, )?\d{1,2} [A-Za-z]+ \d{4}$)',stripped) or stripped in ('Protecting cash: a shared responsibility','Inflation','Economic growth and labour market','Economic growth and labour market results','Housing and credit access','Income and consumption','Key ECB interest rates') or (stripped.endswith('?') and len(text.splitlines())>1) or match(r'^(PRESS RELEASE|INTERVIEW|SPEECH|ПРЕСС.РЕЛИЗ|ИНТЕРВЬЮ|ВЫСТУПЛЕНИЕ|For release at.*|\d{1,2}[./]\d{1,2}[./]\d{4}|\d{1,2} [А-Яа-я]+ \d{4}|[A-Za-z]+ \d{1,2}, \d{4})$',stripped):start+=len(line)
        else:break
    text=body[start:end].strip();end=start+len(body[start:end].rstrip());start=end-len(text)
    if len(text)<minimum:return None,'short_fragment'
    if text.endswith('?') or match(r'^(What|Why|How|Do you|Can you|Ка[кк]|Почему|Что вы|Можете ли)\b.*\?',text):return None,'question_only'
    if match(r'(et al\.|Occasional Paper Series|Economic Bulletin, Issue|Journal of |Working Paper|https?://|ISBN|Список литературы|Поделиться|©|Все права защищены|cookies|cookie policy)',text):return None,'references_or_navigation'
    if match(r'^[-•]?\s*(See |См\.|Источник:|Источники:|Примечание:|Share |Follow us|Contact us|Подписаться)',text):return None,'references_or_navigation'
    if match(r'^(In my remarks|In this speech|Today, (?:we are|I am) discussing|Not out of nostalgia|Let me (?:begin|conclude)|В своем выступлении|В этом выступлении)',text):return None,'speech_outline_or_fragment'
    if match(r'^(I.m here|Thank you|Ladies and gentlemen|Добрый день|Спасибо за|Уважаемые коллеги)',text):return None,'social_boilerplate'
    return {'start_char':start,'end_char':end,'sentence_id':sentence['sentence_id'],'text':text},None


def rerank(base,di,snapshot,c,observed):
    if c['reranking']['version']=='semantic_reranking_v1':
        from app.reranking_legacy import rerank as legacy_rerank
        return legacy_rerank(base,di,snapshot,c,observed)
    if c['reranking']['version']=='semantic_reranking_v2':
        from app.reranking_v2 import rerank as previous_rerank
        return previous_rerank(base,di,snapshot,c,observed)
    result=copy.deepcopy(base);policy=c['reranking'];body=snapshot['document']['content']['body'];title=result['document']['title'];did=result['document']['document_id'];chunks=observed['chunks'];ru=di['language']=='ru'
    ontology={x['id']:x for x in c['ontology']['concepts']};sentences=[];discarded=[]
    reference=re.search(r'(?im)^\s*(References|Bibliography|Footnotes|Список литературы|Источники)\s*$',body)
    for sentence in di['sentences']:
        clean,reason=useful_sentence(sentence,body,title,policy['minimum_claim_characters'])
        if reference and sentence['start_char']>=reference.start():clean=None;reason='reference_section'
        if clean:sentences.append(clean)
        else:discarded.append({'start_char':sentence['start_char'],'end_char':sentence['end_char'],'decision':'rejected','reasons':[reason]})
    def span(s):return evidence(did,body,chunks,s['start_char'],s['end_char'])
    def inside(e,s):return s['start_char']<=e['start_char']<e['end_char']<=s['end_char']
    def entities_in(s):return [e for e in result['entities'] if (e['extractor']=='di' or (e['confidence'] or 0)>=policy['entity_confidence']) and any(inside(p,s) for p in e['evidence'])]
    def facts_for(cid):return [f for f in di['facts'] if any(f['fact_type'].startswith(p) for p in policy['concepts'][cid]['fact_prefixes'])]
    def related(s,cid):
        if not match(policy['concepts'][cid]['anchors'],s['text']):return False
        # Digital central-bank money/cash alone is explicitly not cryptocurrency.
        if cid=='crypto_regulation' and match(r'digital euro|цифров\w* рубл|legal tender|наличн',s['text']) and not match(r'crypto.?assets?|cryptocurrenc|криптовалют|криптоактив',s['text']):return False
        return True
    decisions=[];accepted=[];supported={}
    for cid,rule in policy['concepts'].items():
        hits=[h for h in result['top_matches'] if h['concept_id']==cid];anchored=[s for s in sentences if related(s,cid)]
        facts=facts_for(cid);entity_ids=[];relation_ids=[];supporting=[]
        for sentence in anchored:
            es=entities_in(sentence);entity_ids.extend(e['entity_id'] for e in es)
            rs=[r for r in result['relations'] if r['evidence']['start_char']<sentence['end_char'] and r['evidence']['end_char']>sentence['start_char'] and match(rule['anchors'],r['evidence']['text'])]
            relation_ids.extend(r['relation_id'] for r in rs)
            action=match(policy['action_pattern'],sentence['text'])
            quantified=any(inside(m['evidence'],sentence) for m in di['measurements'])
            canonical=any(e['extractor']=='di' and e['type'] in ('organization','economic_indicator','instrument','cryptocurrency') for e in es)
            if rs or (action and (canonical or es)) or (quantified and cid in ('inflation','employment','economic_growth','interest_rates','risk_parameters')):
                supporting.append(sentence)
        positive=[h for h in hits if h['similarity']>=rule['min_positive']]
        valid=[h for h in positive if h.get('semantic_margin',h['similarity']) is not None and h.get('semantic_margin',h['similarity'])>=rule['min_margin']]
        if rule['requires_direct_support']:
            valid=[h for h in valid if any(ch['chunk_id']==h['chunk_id'] and s['start_char']<ch['end_char'] and s['end_char']>ch['start_char'] for s in anchored for ch in chunks)]
        # Independent chunks may not borrow the same sentence to meet the count.
        independent=[];seen_sentences=set()
        for h in valid:
            ch=next(x for x in chunks if x['chunk_id']==h['chunk_id']);ids=set(ch['sentence_ids'])
            if ids and not ids&seen_sentences and any(s['sentence_id'] in ids for s in anchored):independent.append(h);seen_sentences|=ids
        negative=[h for h in positive if h.get('semantic_margin',h['similarity'])<rule['min_margin']]
        reasons=[];decision='review'
        # A DI fact remains in facts regardless; contrast gates its thematic label.
        contrast_ok=bool(valid) or not ontology[cid].get('negative_examples')
        if not anchored and not facts:decision='rejected';reasons=['No sentence-level topic support; a chunk similarity alone is insufficient']
        elif ontology[cid].get('negative_examples') and not contrast_ok:decision='rejected';reasons=['Positive evidence does not exceed negative examples by the configured margin']
        elif facts:decision='accepted';reasons=['A: exact DI fact support']
        elif supporting and (valid or not rule['requires_direct_support']):decision='accepted';reasons=['B: explicit sentence topic with canonical/entity-action or measurement support']
        elif len(independent)>=2:decision='accepted';reasons=['C: at least two non-overlapping sentence groups in independent topic-supported chunks']
        elif valid and max(h['similarity'] for h in valid)>=policy['very_strong'] and entity_ids:decision='accepted';reasons=['D: very strong contrastive semantic chunk plus extracted entity evidence']
        else:reasons=['Candidate only: insufficient independent or relational evidence']
        summary={'semantic_evidence_count':len(positive),'independent_evidence_count':len(independent),'max_similarity':max((h['similarity'] for h in hits),default=0.),'mean_supporting_similarity':mean(h['similarity'] for h in valid) if valid else 0.,'di_fact_support':[f['fact_id'] for f in facts],'entity_support':sorted(set(entity_ids)),'relation_support':sorted(set(relation_ids)),'article_section_support':['body'] if anchored else [],'negative_evidence':negative[:4],'supporting_spans':[span(s) for s in (supporting or anchored)[:4]]}
        decisions.append({'concept_id':cid,'decision':decision,'reasons':reasons,'summary':summary})
        if decision=='accepted':
            chosen=valid or hits[:1];score=max((h['similarity'] for h in chosen),default=0.)
            accepted.append({'concept_id':cid,'strength':'high' if facts or score>=c['high_threshold'] else 'medium','max_similarity':score,'matches':chosen[:4]})
            supported[cid]=anchored
    active={x['concept_id'] for x in accepted};result['semantic_concepts']=accepted
    result['domains']=sorted({d for cid in active for d in ontology[cid]['domains']})
    # Sentence typing is independent of a neighbouring chunk's winning concept.
    candidates=[];claim_decisions=list(discarded)
    for sentence in sentences:
        fs=[f for f in di['facts'] if f['evidence']['start_char']<sentence['end_char'] and f['evidence']['end_char']>sentence['start_char']]
        rs=[r for r in result['relations'] if r['evidence']['start_char']<sentence['end_char'] and r['evidence']['end_char']>sentence['start_char']]
        ms=[m for m in di['measurements'] if inside(m['evidence'],sentence)]
        types=[cid for cid in sorted(active) if related(sentence,cid)]
        action=match(policy['action_pattern'],sentence['text'])
        predicate=action or match(r'\b(is|are|was|were|has|have|will|remains|continued|expect|seeks|supports?|ensure|must)\b|составля|явля|остае|остаю|ожида|сохран|обеспеч|провод|может|будет|будут|долж',sentence['text'])
        if not (fs or rs or ms or (types and predicate)):
            claim_decisions.append({'start_char':sentence['start_char'],'end_char':sentence['end_char'],'decision':'rejected','reasons':['No supported predicate/action, measurement or specific assertion']});continue
        kind=fs[0]['fact_type'] if fs else 'generic_claim'
        if not fs and len(types)==1:kind=types[0]
        if 'inflation' in types:
            if match(r'perceived|perception|восприяти|воспринима',sentence['text']):kind='inflation_perceptions'
            elif match(r'inflation expectations?|expectations? for inflation|projections?.*inflation|прогноз.*инфляц|инфляционн\w* ожидани|ожидани\w*.*инфляц',sentence['text']):kind='inflation_expectations'
            elif not fs and (ms or len(types)==1):kind='inflation'
        score=(100 if fs else 0)+(40 if rs or action and entities_in(sentence) else 0)+(20 if ms else 0)+min(len(types),3)*3
        candidates.append((score,sentence,fs,rs,kind))
    claims=[]
    for score,s,fs,rs,kind in sorted(candidates,key=lambda x:(-x[0],x[1]['start_char'])):
        if len(claims)>=policy['max_claims']:break
        claim={'claim_id':uid(result['semantic_id'],'sentence_claim',s['start_char'],s['end_char']),'type':kind,'subject':fs[0]['subject']['entity_id'] if fs else rs[0]['subject'] if rs else None,'action':fs[0]['action'] if fs else rs[0]['predicate'] if rs else None,'object_value':rs[0]['object'] if rs else None,'evidence':span(s),'extractor':'di' if fs else 'gliner' if any(r['extractor']=='gliner' for r in rs) else 'semantic','supporting_fact_ids':[f['fact_id'] for f in fs],'status':'deterministic' if fs else 'supported_candidate' if rs else 'semantic_candidate','reason':('Точный фрагмент; приоритет: факт → действие/связь → измерение → тематическая связь. Тип проверен на уровне предложения.' if ru else 'Exact sentence; priority: fact > action/relation > measurement > centrality. Type requires sentence-level support.')}
        claims.append(claim);claim_decisions.append({'start_char':s['start_char'],'end_char':s['end_char'],'decision':'accepted','reasons':['fact' if fs else 'relation/action' if rs or match(policy['action_pattern'],s['text']) else 'measurement' if any(inside(m['evidence'],s) for m in di['measurements']) else 'sentence predicate and centrality']})
    result['claims']=claims
    # Keep format and DI facts, but re-evaluate semantic-only genre on accepted topics.
    if result['article_type'] not in ('interview','speech'):
        if not result['facts']:
            structural='interview' if match(r'interview|интервью',title) else 'speech' if match(r'speech|выступлен|заявление Председателя',title) else None
            if structural and active:result['article_type']=structural
            elif 'personnel' in active:result['article_type']='personnel'
            elif 'administrative' in active and not active&{'interest_rates','trading_suspension','enforcement'}:result['article_type']='administrative'
            elif 'cash_policy' in active and not active&{'interest_rates','enforcement'}:result['article_type']='commentary'
            else:result['article_type']=ontology[max(accepted,key=lambda x:x['max_similarity'])['concept_id']]['article_type'] if accepted else 'unknown'
    result['article_type_basis'].append('DI-5.1: accepted concept evidence and explicit document structure')
    assets=[]
    def add(name,cids,reason,direct=False,spans=None):
        spans=spans or [span(s) for cid in sorted(cids) for s in supported.get(cid,[])[:2]]
        if spans:assets.append({'asset':name,'relevance':'high' if result['facts'] else 'medium','basis':[reason],'evidence':spans[:4],'direct':direct})
    macro=active&{'interest_rates','inflation','employment','economic_growth','monetary_policy'}
    cash_only='cash_policy' in active and not active&{'interest_rates','inflation','employment','economic_growth'}
    if macro and not cash_only:add('rates',macro,'Подтвержденный макроэкономический контекст' if ru else 'Accepted macro-policy/data evidence')
    currency=policy['currencies'].get(result['document']['source_id'])
    if currency and (macro or 'cash_policy' in active):add(currency,macro|({'cash_policy'} if 'cash_policy' in active else set()),'Валюта соответствующего центрального банка и подтвержденный контекст' if ru else 'Relevant central-bank currency with accepted policy/data/cash evidence')
    digital=active&{'crypto_regulation','crypto_exchange','withdrawal_suspension','hack','security_incident','stablecoin','depeg','institutional_crypto','treasury_purchase'}
    # Incident alone is not necessarily crypto; require explicit cryptocurrency context.
    crypto_text=[s for s in sentences if match(r'crypto|bitcoin|ethereum|BTC|ETH|крипт|биткоин|эфир|USDT|USDC',s['text']) and not match(r'кибербезопасност.*обучен',s['text'])]
    if digital and crypto_text:add('crypto_market',digital,'Принятый криптоконтекст с прямым упоминанием криптоактивов' if ru else 'Accepted crypto concept plus explicit cryptocurrency context',spans=[span(s) for s in crypto_text])
    for name,pattern in [('BTC',r'\bBTC\b|bitcoin|биткоин'),('ETH',r'\bETH\b|ethereum|эфири?ум')]:
        relevant=[s for s in crypto_text if match(pattern,s['text']) and match(policy['action_pattern'],s['text']) and (entities_in(s) or any(inside(f['evidence'],s) for f in di['facts']))]
        if digital and relevant:add(name,digital,'Именованный актив и подтвержденное действие в том же предложении' if ru else 'Named asset and supported action in the same sentence',True,[span(s) for s in relevant])
    us=[s for s in sentences if match(r'\b(?:(?-i:U\.?S\.?)|United States|American|NMS)\b.*\b(?:equities|equity|stocks?|shares?)\b|\b(?:equities|equity|stocks?|shares?)\b.*\b(?:(?-i:U\.?S\.?)|United States|America)\b|американск\w* акци|акци\w*.*США',s['text'])]
    if result['document']['source_id']=='sec_press_releases':us += [s for s in sentences if match(r'issuer|broker.dealer',s['text']) and match(r'deliver|disclos|information',s['text']) and 'financial_regulation' in active]
    if us:add('US_equities',active,'Прямая связь с рынком акций США' if ru else 'Explicit US-equity or issuer-disclosure context',spans=[span(s) for s in us])
    companies=[s for s in sentences if active&{'earnings','merger_acquisition'} and entities_in(s) and any(e['type']=='company' for e in entities_in(s)) and any(related(s,cid) for cid in active&{'earnings','merger_acquisition'})]
    if companies:add('specific_company',active,'Компания связана с отчетностью или сделкой' if ru else 'Named company linked to earnings or M&A',True,[span(s) for s in companies])
    if result['document']['source_id']=='moex_news_ru':
        eq=[s for s in sentences if match(r'акци[йяию]|ценной бумаги.{0,40}\(.*?\bа[оп]\b',s['text']) and active&{'equities','listing','trading_suspension','risk_parameters'}]
        if eq:add('RU_equities',active,'Конкретные акции и торговое/листинговое действие',True,[span(s) for s in eq])
        if 'fx_market' in active:add('fx_market',{'fx_market'},'Подтвержденный контекст валютного рынка')
        if any(match(r'RUB|рубл',s['text']) for s in supported.get('fx_market',[])):add('RUB',{'fx_market'},'Рубль указан в валютной паре',True)
    result['affected_assets']=assets
    # Importance never uses similarity as its only trigger.
    def feature(level,reason,spans=()):return {'level':level,'reasons':[reason],'evidence':list(spans)[:3]}
    action_claims=[cl for cl in claims if cl['supporting_fact_ids'] or match(policy['action_pattern'],cl['evidence']['text'])]
    high_topics=active&{'interest_rates','inflation','enforcement','crypto_regulation','trading_suspension','withdrawal_suspension','hack','depeg','earnings','listing','risk_parameters','financial_regulation','economic_growth'}
    low_genre=result['article_type'] in ('personnel','administrative') or ('cash_policy' in active and not active&{'interest_rates','inflation','economic_growth'})
    specific=bool(action_claims and high_topics) and not low_genre
    importance='high' if specific else 'medium' if assets and not low_genre else 'low'
    route='important' if specific else 'low' if low_genre or not active else 'review'
    components={'specific_event_support':feature('high' if specific else 'low','Явное действие и принятая событийная тема' if ru else 'Explicit action and accepted substantive event theme',[x['evidence'] for x in action_claims]),'high_value_fact_support':feature('high' if di['facts'] and not low_genre else 'none','Сохраненные DI-факты; жанр проверен отдельно' if ru else 'Retained DI facts; document genre independently checked',[f['evidence'] for f in claims if f['supporting_fact_ids']]),'source_quality':result['information_value']['source_quality'],'document_quality':result['information_value']['document_quality'],'semantic_centrality':feature('medium' if active else 'none','Только принятые темы, а не максимальный cosine' if ru else 'Accepted evidence-supported themes, not maximum cosine'),'asset_relevance':feature('medium' if assets else 'none','Связи с активами имеют отдельное основание' if ru else 'Asset links require their own source evidence',[a['evidence'][0] for a in assets]),'information_density':feature('medium' if len(claims)>=3 else 'low','Количество отфильтрованных содержательных утверждений' if ru else 'Number of filtered substantive claims',[cl['evidence'] for cl in claims])}
    result['information_value']['market_relevance']=feature(importance,'Явное событие / жанр / доказательства, без маршрутизации по cosine' if ru else 'Specific event, genre and evidence; no similarity-only routing',[cl['evidence'] for cl in action_claims])
    result['information_value']['crypto_relevance']=feature('medium' if any(a['asset']=='crypto_market' for a in assets) else 'none','Проверенные связи с криптоактивами' if ru else 'Evidence-gated crypto links')
    result['routing'].update(semantic_suggested_route=route,disagreement=route!=result['routing']['old_route'] if result['routing']['old_route'] else None,reasons=components['specific_event_support']['reasons']+['Research only; production router unchanged'])
    result['top_matches']=[h for ch in chunks for h in sorted([m for m in result['top_matches'] if m['chunk_id']==ch['chunk_id']],key=lambda m:(-m['similarity'],m['concept_id']))[:c['top_k']]]
    result['reranking']={'policy_version':policy['version'],'status':'complete','decisions':decisions,'claim_decisions':claim_decisions,'importance_components':components,'latency_seconds':observed.get('reranking_seconds',0.0)}
    baseline=snapshot.get('baseline')
    if baseline:
        def changes(before,after):return sorted(before-after),sorted(after-before)
        cr,ca=changes({x['concept_id'] for x in baseline['semantic_concepts']},active);ar,aa=changes({x['asset'] for x in baseline['affected_assets']},{x['asset'] for x in assets})
        before={digest({'span':cl['evidence'],'type':cl['type']}):cl['claim_id'] for cl in baseline['claims']};after={digest({'span':cl['evidence'],'type':cl['type']}):cl['claim_id'] for cl in claims}
        result['comparison']={'baseline_id':baseline['semantic_id'],'baseline_hash':digest(baseline),'concepts_removed':cr,'concepts_added':ca,'assets_removed':ar,'assets_added':aa,'claims_removed':[before[k] for k in sorted(before.keys()-after.keys())],'claims_added':[after[k] for k in sorted(after.keys()-before.keys())],'importance_before':baseline['information_value']['market_relevance']['level'],'importance_after':importance,'routing_before':baseline['routing']['semantic_suggested_route'],'routing_after':route}
    return result
