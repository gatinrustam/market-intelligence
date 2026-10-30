"""Offline metrics from explicit pilot decisions; never infers correctness labels.
Usage: python evaluate-semantic-precision.py results.json en-review.json ru-review.json
"""
import json,sys
rows=json.load(open(sys.argv[1]));by_doc={x['result']['document']['document_id']:x for x in rows}
en=json.load(open(sys.argv[2]));ru=json.load(open(sys.argv[3]));old=json.load(open('datasets/article_semantic/review/completed-review.v1.json'))
def pr(tp,fp,fn):return {'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None}
def metrics(labels,baseline=False,concepts=False):
 itp=ifp=ifn=atp=afp=afn=ctp=cfp=cfn=good=total=0;documents=[]
 for label in labels:
  row=by_doc[label['document_id']];r=row['snapshot']['baseline'] if baseline else row['result']
  assert label['semantic_id']==r['semantic_id']
  predicted=r['routing']['semantic_suggested_route'] in ('important','critical');expected=label['gold_important']
  itp+=bool(predicted and expected);ifp+=bool(predicted and not expected);ifn+=bool(not predicted and expected)
  assets={a['asset'] for a in r['affected_assets']};ga=set(label['gold_assets']);atp+=len(assets&ga);afp+=len(assets-ga);afn+=len(ga-assets)
  allclaims={c['claim_id'] for c in r['claims']};correct=set(label['correct_claim_ids']);assert correct<=allclaims
  good+=len(correct);total+=len(allclaims)
  if concepts:
   topics={c['concept_id'] for c in r['semantic_concepts']};gt=set(label['gold_concepts']);ctp+=len(topics&gt);cfp+=len(topics-gt);cfn+=len(gt-topics)
  documents.append({'document_id':label['document_id'],'title':r['document']['title'],'important_predicted':predicted,'important_gold':expected,'assets_predicted':sorted(assets),'assets_gold':sorted(ga),'claims_correct':len(correct),'claims_total':len(allclaims)})
 out={'documents_reviewed':len(labels),'important':pr(itp,ifp,ifn),'assets_micro':pr(atp,afp,afn),'claims':{'correct':good,'total':total,'precision':good/total if total else None},'per_document':documents}
 if concepts:out['concepts_micro']=pr(ctp,cfp,cfn)
 return out
before=metrics(old['documents'],baseline=True);after=metrics(en['documents']);russian=metrics(ru['documents'],concepts=True)
print(json.dumps({'independent_human_validation':False,'sample':'Purposive Codex pilot, not held-out or independent human gold','en':{'before':before,'after':after,'claim_recall_limitation':'No exhaustive claim gold. Correct-claim count and per-document coverage are shown alongside importance/asset recall; claim precision alone does not establish recall.'},'ru':russian,'precision_targets':{'asset_above_51_9_percent':after['assets_micro']['precision']>0.519,'claim_above_58_8_percent':after['claims']['precision']>0.588}},ensure_ascii=False,indent=2))
