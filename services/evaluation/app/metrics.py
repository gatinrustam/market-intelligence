from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from sqlalchemy import select
from app.storage.models import Evaluation, EvaluationResult

GROUPS = {'horizon','event_type','source','model','prompt_version','confidence'}


def metrics(sessions, groups, origin='model', basis='all'):
    if not groups or len(set(groups)) != len(groups) or not set(groups) <= GROUPS: raise ValueError('unsupported grouping')
    buckets = {}
    with sessions() as session:
        query = select(Evaluation.payload,EvaluationResult.payload).join(EvaluationResult,Evaluation.id==EvaluationResult.evaluation_id)
        if origin != 'all': query = query.where(Evaluation.origin==origin)
        for payload, result in session.execute(query.execution_options(yield_per=1000)):
            decision_basis = payload['decision']['decision_basis']
            if basis!='all' and basis!=decision_basis: continue
            provenance, analysis = payload['provenance'],payload['analysis']
            # These dimensions are always distinct, so policy changes and fixtures
            # cannot silently inflate real/live metrics.
            fixed = {'origin':provenance['origin'],'decision_basis':decision_basis,'policy_hash':payload['policy_hash']}
            dimensions = {'horizon':result['horizon_seconds'],'event_type':provenance['event_type'],
                          'model':analysis['model'],'prompt_version':analysis['prompt_version'],'confidence':result['forecast']['confidence']}
            sources = (provenance['sources'] or ['unknown']) if 'source' in groups else [None]
            for source in sources:
                values = {**fixed,**{g:(source if g=='source' else dimensions[g]) for g in groups}}
                key = tuple(values.items())
                row = buckets.setdefault(key,{'group':values,'n':0,'evaluated':0,'hits':0,'misses':0,'not_scored':0,'unavailable':0,'pending':0,'total_horizons':0,'_analyses':set()})
                row['total_horizons']+=1; row['_analyses'].add(analysis['analysis_id'])
                state=result['status']
                if state=='evaluated':
                    row['evaluated']+=1; row['n']+=1
                    row['hits' if result['evaluation']['direction_result']=='hit' else 'misses']+=1
                else: row[state]+=1
    output=[]
    for row in buckets.values():
        row['analysis_count']=len(row.pop('_analyses'))
        with localcontext() as ctx:
            ctx.prec=40
            row['direction_accuracy_pct']=format((Decimal(row['hits'])*100/row['n']).quantize(Decimal('0.000001'),rounding=ROUND_HALF_EVEN),'f') if row['n'] else None
        output.append(row)
    return {'group_by':groups,'origin':origin,'basis':basis,'confidence_basis':'model_reported_not_calibrated',
            'source_attribution':'each source of an event; source groups overlap',
            'rows':sorted(output,key=lambda r:str(r['group']))}
