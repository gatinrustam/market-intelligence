"""Exact, occurrence-aware bootstrap metrics. No thresholds or labels learned here."""
import argparse,json
from pathlib import Path
from collections import Counter
from app.pipeline import Pipeline,validate_spans
from app.domain import load_configuration
from app.config import Settings

def score(expected,predicted):
    gold=Counter(expected);found=Counter(predicted);tp=sum((gold&found).values());fp=sum((found-gold).values());fn=sum((gold-found).values())
    precision=tp/(tp+fp) if tp+fp else None;recall=tp/(tp+fn) if tp+fn else None
    f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
    return {'tp':tp,'fp':fp,'fn':fn,'precision':precision,'recall':recall,'f1':f1}
def keys(gold,out):
    predicted={'entities':[],'measurements':[],'facts':[],'topics':[]};expected={k:[] for k in predicted}
    for e in gold['annotations']['entities']:expected['entities'].append((e['type'],e['entity_id'],e['start_char'],e['end_char']))
    for e in out['entities']:predicted['entities'].append((e['type'],e['entity_id'] if e['registry'] else None,e['evidence']['start_char'],e['evidence']['end_char']))
    def measurement(m,e):return (m['kind'],m['value'],m['min'],m['max'],m['unit'],e['start_char'],e['end_char'])
    for m in gold['annotations']['measurements']:expected['measurements'].append(measurement(m,m))
    for m in out['measurements']:predicted['measurements'].append(measurement(m,m['evidence']))
    for f in gold['annotations']['facts']:expected['facts'].append((f['fact_type'],f['action'],f['subject'],f['predicate_start'],f['predicate_end']))
    relations={r['relation_id']:r for r in out['relations']}
    for f in out['facts']:
        p=relations[f['relation_id']]['predicate'];predicted['facts'].append((f['fact_type'],f['action'],f['subject']['entity_id'],p['start_char'],p['end_char']))
    expected['topics']=sorted(set(gold['annotations']['topics']));predicted['topics']=sorted({t['topic'] for t in out['topics']})
    return expected,predicted

def evaluate(directory,pipeline):
    report={'dataset_version':'1.0','documents':[],'sampling':'purposive single-annotator bootstrap; not general engine quality','matching':{'entities':'exact type, canonical ID for registry entities, and character span','measurements':'exact kind, normalized value/range, unit, and span','facts':'exact taxonomy, action, subject ID and predicate span; value attachment is tested separately','topics':'document-level set'},'metrics':{}}
    totals={k:[[],[]] for k in ('entities','facts','measurements','topics')}
    for path in sorted(Path(directory).glob('*.json')):
        if path.name=='manifest.json':continue
        g=json.loads(path.read_text());out=pipeline.analyze(g['enriched_document']);validate_spans(out,g['body']);expected,predicted=keys(g,out)
        metrics={k:score(expected[k],predicted[k]) for k in totals}
        errors={k:{'false_positives':list((Counter(predicted[k])-Counter(expected[k])).elements()),'false_negatives':list((Counter(expected[k])-Counter(predicted[k])).elements())} for k in totals}
        report['documents'].append({'document_id':g['document_id'],'title':g['title'],'metrics':metrics,'errors':errors})
        for k in totals:
            totals[k][0].extend((g['document_id'],x) for x in expected[k]);totals[k][1].extend((g['document_id'],x) for x in predicted[k])
    report['metrics']={k:score(*v) for k,v in totals.items()};report['document_count']=len(report['documents'])
    return report
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args()
    print(json.dumps(evaluate(args.directory,Pipeline(load_configuration(Settings()))),ensure_ascii=False,indent=2))
