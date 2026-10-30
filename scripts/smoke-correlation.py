"""Read-only DI-4 audit. Run inside event-research; emit JSON for the report."""
import asyncio
import json
import httpx
from sqlalchemy import select
from app.config import Settings
from app.domain import digest
from app.storage.database import make_database
from app.storage.models import (ResearchResult, ResearchRun, CorrelationCandidate, CorrelationRevision,
    CorrelationDecision, CorrelationPolicy, CorrelationProcessed)
from app.correlation.domain import load_policy, projection, fingerprint, correlate
from app.correlation.repository import CorrelationRepository

async def main():
    settings=Settings();engine,sessions=make_database(settings.database_url.get_secret_value())
    repo=CorrelationRepository(sessions,load_policy(settings.correlation_rules_path));stats=repo.stats()
    assert stats['documents_processed']==55 and stats['events_before_correlation']==55
    assert sum(stats['pair_decisions'].values())==55*54//2
    verified_inputs=verified_decisions=verified_revisions=0
    documents=[];di3_hashes={}
    async with httpx.AsyncClient(timeout=30) as client:
        with sessions() as s:
            inputs=list(s.scalars(select(CorrelationCandidate).where(CorrelationCandidate.policy_id==repo.scope)))
            by_id={m.candidate_id:m for m in inputs}
            for result in s.scalars(select(ResearchResult).where(ResearchResult.ruleset_version==repo.policy['input_ruleset_version'])):
                run=s.get(ResearchRun,result.id)
                di3_hashes[result.id]={'result_hash':digest(result.payload),'snapshot_hash':digest(run.snapshot)}
                for row in projection(result.payload,run.snapshot):
                    stored=by_id[row['candidate']['candidate_id']]
                    assert stored.payload==row and stored.fingerprint==fingerprint(row,repo.policy)
                    assert stored.payload_hash==digest(row)
                    documents.append({'title':row['metadata']['title'],'source':row['metadata']['source']['id'],
                        'document_id':row['document']['document_id'],'correlation':repo.for_document(row['document']['document_id'])})
                    verified_inputs+=1
                processed=s.get(CorrelationProcessed,(repo.scope,result.id));assert processed.input_hash==digest(result.payload)
            for d in s.scalars(select(CorrelationDecision).where(CorrelationDecision.policy_id==repo.scope)):
                a,b=by_id[d.candidate_a],by_id[d.candidate_b]
                expected=correlate(a.payload,b.payload,a.fingerprint,b.fingerprint,repo.policy)
                assert all(d.payload[k]==v for k,v in expected.items())
                if d.mode=='exact_match':assert a.event_id==b.event_id
                else:assert a.event_id!=b.event_id
                verified_decisions+=1
            for event in repo.events():
                histories=repo.revisions(event['event_id'])
                assert [r['revision'] for r in histories]==list(range(1,event['revision']+1))
                assert event['document_count']==len({d['document_id'] for d in event['documents']})
                assert event['independent_source_count']==len({x for d in event['documents'] for x in d['sources']})
                verified_revisions+=len(histories)
        r=await client.get('http://events:8002/events?limit=100');r.raise_for_status()
        v1=r.json();assert v1['total']==55
    engine.dispose()
    print(json.dumps({'stats':stats,'verified_frozen_inputs':verified_inputs,'reproduced_pair_decisions':verified_decisions,
        'verified_revisions':verified_revisions,'di3_hashes':di3_hashes,'policy':repo.policy,'v1_event_count':v1['total'],'documents':documents},ensure_ascii=False))

asyncio.run(main())
