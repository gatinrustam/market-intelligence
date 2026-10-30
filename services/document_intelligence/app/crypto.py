"""Versioned extraction of explicitly labelled treasury acquisition figures.

No arithmetic inference, no issuer/asset inferred from source configuration.
Ambiguous/repeated table columns are intentionally left for review.
"""
import re
from decimal import Decimal
from app.domain import uid
from app.extractors import explain, ref

NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
LABELS = {
    'quantity': r'BTC\s+Acquired\s*:?\s*('+NUMBER+r')\b',
    'aggregate_value_usd': r'Aggregate\s+Purchase\s+Price\s*:?\s*\$\s*('+NUMBER+r')\s*(million|billion|m|b)?\b',
    'average_price_usd': r'Average\s+Purchase\s+Price\s*:?\s*\$\s*('+NUMBER+r')\s*(million|billion|m|b)?\b',
}


def extract_labelled_purchase(out, nlp, body):
    actors=[e for e in out['entities'] if e['type']=='organization' and e['registry']]
    # Multiple possible corporate actors make table ownership ambiguous.
    actors=[e for e in actors if e['entity_id'] not in ('organization:sec',)]
    if len({e['entity_id'] for e in actors})!=1:
        return
    matches={key:list(re.finditer(pattern,body,re.I)) for key,pattern in LABELS.items()}
    if not all(len(ms)==1 for ms in matches.values()):
        return
    matches={key:ms[0] for key,ms in matches.items()}
    start=min(m.start() for m in matches.values());end=max(m.end() for m in matches.values())
    if end-start>600 or re.search(r'\b(?:example|illustrative|hypothetical|forecast|not|no|would|could|may)\b',body[max(0,start-100):end],re.I):
        return
    doc_id=out['document']['document_id'];values=[];structured={'asset':'BTC'}
    for key,m in matches.items():
        s=next((s for s in nlp.sentences if s.start<=m.start()<m.end()<=s.end),None)
        if s is None:
            return
        scale=(m[2] or '').lower() if key!='quantity' else ''
        value=format((Decimal(m[1].replace(',',''))*{'million':10**6,'m':10**6,'billion':10**9,'b':10**9}.get(scale,1)).normalize(),'f')
        structured[key]=value
        measurement={'measurement_id':uid(doc_id,'crypto_label',key,m.start()),'kind':'quantity' if key=='quantity' else 'money' if key=='aggregate_value_usd' else 'price',
                     'value':value,'min':None,'max':None,'unit':'BTC' if key=='quantity' else 'USD','currency':None if key=='quantity' else 'USD',
                     **explain(doc_id,s,body,m.start(),m.end(),'crypto_treasury','crypto.label.'+key+'.v1')}
        values.append(measurement)
    m=matches['quantity'];s=next(s for s in nlp.sentences if s.start<=m.start()<m.end()<=s.end)
    rule='crypto.treasury_purchase.labelled.v1';relation_id=uid(doc_id,rule,m.start());subject=ref(actors[0])
    evidence=explain(doc_id,s,body,m.start(),m.end(),'crypto_treasury',rule)
    out['relations'].append({'relation_id':relation_id,'subject':subject,'action':'purchase','predicate':{'text':body[m.start():m.end()],'start_char':m.start(),'end_char':m.end()},
                            'object':{'entity_id':None,'mention_id':None,'text':body[m.start():m.end()],'start_char':m.start(),'end_char':m.end()},'modality':'asserted',**evidence})
    out['measurements'].extend(values)
    out['facts'].append({'fact_id':uid(doc_id,rule,m.start(),'fact'),'fact_type':'crypto.treasury_purchase','subject':subject,'action':'purchase','relation_id':relation_id,'values':values,**structured,**evidence})
