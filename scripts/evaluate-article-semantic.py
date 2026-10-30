"""Offline descriptive evaluation. Requires explicit reviewed labels; no label inference.
Usage: python evaluate-article-semantic.py results.json reviews.json ru-results.jsonl
"""
import collections,json,statistics,sys
report=json.load(open(sys.argv[1]));results=[r['result'] for r in report['results']]
review=json.load(open(sys.argv[2]));by_doc={r['document']['document_id']:r for r in results}
def pr(tp,fp,fn):return {'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None}
itp=ifp=ifn=atp=afp=afn=correct=claims=0
for label in review['documents']:
 r=by_doc[label['document_id']];pred=r['routing']['semantic_suggested_route'] in ('critical','important');gold=label['gold_important']
 itp+=pred and gold;ifp+=pred and not gold;ifn+=not pred and gold
 assets={a['asset'] for a in r['affected_assets']};ga=set(label['gold_assets']);atp+=len(assets&ga);afp+=len(assets-ga);afn+=len(ga-assets)
 claimids={c['claim_id'] for c in r['claims']};accepted=set(label['correct_claim_ids']);assert accepted<=claimids
 correct+=len(accepted);claims+=len(claimids)
n=len(results);latencies=[r['performance']['latency_seconds'] for r in results]
output={'documents_processed':n,'status_counts':dict(collections.Counter(r['status'] for r in results)),
 'semantic_concepts_per_document':sum(len(r['semantic_concepts']) for r in results)/n,
 'claims_per_document':sum(len(r['claims']) for r in results)/n,'affected_assets_per_document':sum(len(r['affected_assets']) for r in results)/n,
 'routing_disagreements':sum(r['routing']['disagreement'] is True for r in results),
 'routing_pairs':dict(collections.Counter(str(r['routing']['old_route'])+' -> '+r['routing']['semantic_suggested_route'] for r in results)),
 'documents_with_di_facts':sum(bool(r['facts']) for r in results),
 'semantic_context_candidates_without_di_facts':sum(bool(r['semantic_concepts']) and not r['facts'] for r in results),
 'documents_with_semantic_conflicts':sum(bool(r['conflicts']) for r in results),
 'review':{'documents':len(review['documents']),'reviewer':review['reviewer'],'independent_human_validation':False,
  'important_prediction_definition':'semantic_suggested_route in critical/important; review is not counted as important',
  'important_article':pr(itp,ifp,ifn),'asset_relevance_micro':pr(atp,afp,afn),
  'claim_precision':{'accepted':correct,'total':claims,'precision':correct/claims if claims else None},
  'useful_added_context':sum(d['useful_added_context'] for d in review['documents']),
  'limitation':'Purposive pilot subset reviewed by Codex against source text; not independent human gold or broad accuracy.'},
 'performance':{'total_document_inference_seconds_excluding_preflight':sum(latencies),'median_latency_seconds':statistics.median(latencies),
  'max_latency_seconds':max(latencies),'documents_per_second':n/sum(latencies),
  'chunks_per_second':sum(r['performance']['chunks'] for r in results)/sum(latencies),
  'max_peak_rss_bytes':max(r['performance']['peak_rss_bytes'] for r in results),
  'total_chunks':sum(r['performance']['chunks'] for r in results)}}
ru=[]
for line in open(sys.argv[3]):
 row=json.loads(line);r=row['result'];f=row['fixture'];pred={c['concept_id'] for c in r['semantic_concepts']};expected=set(f['expected_concepts'])
 ru.append({'id':f['id'],'status':r['status'],'language':r['document']['language'],'expected_concepts':sorted(expected),
  'observed_concepts':sorted(pred),'expected_found':sorted(expected&pred),'expected_missing':sorted(expected-pred),
  'assets':[a['asset'] for a in r['affected_assets']],'gold_assets':f['gold_assets'],
  'gliner_entities':len([e for e in r['entities'] if e['extractor']=='gliner']),
  'full_body_coverage':''.join(c['text'] for c in row['observed']['chunks'])==f['body']})
output['russian_fixtures']=ru
print(json.dumps(output,ensure_ascii=False,indent=2))
