"""Run inside events on JSON fixtures from DI-4 tests; policy-level comparison only.

Explicit dates/namespaces are supplied by the synthetic adapter, not v1 extraction.
This measures v1 identity/suggestion policy, not end-to-end v1 recall.
"""
import json
import sys
from types import SimpleNamespace
from itertools import combinations
from app.correlation.policy import exact_key, suggestion

report=json.load(sys.stdin)
for scenario in report:
    inputs=scenario['inputs'];keys=[];pairs=[]
    def adapt(row):
        c=row['candidate'];f=row['facts'][0]
        return {'taxonomy':{'event_type':c['event_type']},
            'actors':[{'role':'issuer','resolution':'canonical','entity_id':f['primary_actor']}],
            'jurisdictions':[], 'time':{'event_time':c['event_time'],'earliest_source_published_at':row['metadata']['published_at']},
            'content':{'canonical_title':row['metadata']['title']}}
    for row in inputs:
        c=row['candidate'];f=row['facts'][0]
        keys.append(exact_key(c['event_type'],f['primary_actor'],c['event_time'],'date' if c['event_time'] else 'unknown','synthetic.explicit_event'))
    for i,j in combinations(range(len(inputs)),2):
        exact=bool(keys[i] and keys[i]==keys[j])
        features=suggestion(adapt(inputs[i]),adapt(inputs[j]),SimpleNamespace(time_window_seconds=604800,title_jaccard_threshold=.7))
        pairs.append({'candidate_a':inputs[i]['candidate']['candidate_id'],'candidate_b':inputs[j]['candidate']['candidate_id'],
            'mode':'exact_match' if exact else 'suggestion' if features else 'separate_or_insufficient','features':features})
    scenario['v1_policy_comparison']={'scope':'actual v1 policy functions; synthetic explicit-date adapter, not full v1 extraction',
        'events_after_correlation':len(set(k or inputs[i]['candidate']['candidate_id'] for i,k in enumerate(keys))), 'pair_decisions':pairs}
print(json.dumps(report,ensure_ascii=False,indent=2))
