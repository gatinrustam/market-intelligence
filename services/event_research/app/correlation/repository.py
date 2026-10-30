import asyncio
import copy
from collections import Counter
from sqlalchemy import select, exists
from sqlalchemy.exc import IntegrityError
from app.domain import digest, uid, iso, now
from app.correlation.domain import Policy, scope, projection, fingerprint, correlate
from app.storage.models import (CorrelationPolicy, CorrelationCandidate, CorrelationEvent,
    CorrelationRevision, CorrelationDecision, CorrelationSuggestion, CorrelationProcessed,
    ResearchResult, ResearchRun)

class CorrelationRepository:
    def __init__(self, sessions, policy):
        self.sessions = sessions
        self.policy = Policy.model_validate(policy).model_dump()
        self.scope = scope(self.policy)

    def register(self):
        try:
            with self.sessions.begin() as s:
                existing = s.get(CorrelationPolicy, self.scope)
                if existing is None:
                    s.add(CorrelationPolicy(id=self.scope, configuration=self.policy, configuration_hash=digest(self.policy)))
                elif existing.configuration_hash != digest(self.policy):
                    raise ValueError('Correlation policy version already frozen with other content')
        except IntegrityError:
            with self.sessions() as s:
                if s.get(CorrelationPolicy, self.scope).configuration_hash != digest(self.policy):
                    raise ValueError('Correlation version conflict')

    def locked(self, s):
        # One lock per immutable policy serializes small research-corpus transactions,
        # including the first exact identity. No absent-row lock/duplicate-event race.
        row = s.scalar(select(CorrelationPolicy).where(CorrelationPolicy.id == self.scope).with_for_update())
        if row is None or row.configuration_hash != digest(self.policy):
            raise ValueError('Unregistered or mutated correlation policy')

    def ingest(self, rows):
        with self.sessions.begin() as s:
            self.locked(s)
            return [self._accept(s, row) for row in rows]

    def _accept(self, s, row):
        if row['input_ruleset_version'] != self.policy['input_ruleset_version']:
            raise ValueError('Different extraction ruleset requires a separate research policy')
        candidate = row['candidate']; cid = candidate['candidate_id']
        if candidate['document_id'] != row['document']['document_id']:
            raise ValueError('Candidate document mismatch')
        key = uid(self.scope, cid)
        old = s.get(CorrelationCandidate, key)
        if old:
            if old.payload_hash != digest(row):
                raise ValueError('Candidate identity reused with different payload')
            return {'status': 'duplicate', 'event_id': old.event_id}
        fp = fingerprint(row, self.policy)
        prior = list(s.scalars(select(CorrelationCandidate).where(CorrelationCandidate.policy_id == self.scope).order_by(CorrelationCandidate.id)))
        decisions = []; exact = []
        for other in prior:
            decision = correlate(other.payload, row, other.fingerprint, fp, self.policy)
            did = uid(self.scope, *sorted([other.candidate_id, cid]))
            decision['decision_id'] = did
            decision['source_research_ids'] = [other.payload['research_id'], row['research_id']]
            decisions.append(decision)
            if decision['mode'] == 'exact_match':
                exact.append(other.event_id)
            s.add(CorrelationDecision(id=did, policy_id=self.scope, mode=decision['mode'],
                candidate_a=other.candidate_id, candidate_b=cid, payload=decision))
            if decision['mode'] == 'suggestion':
                s.add(CorrelationSuggestion(decision_id=did, payload=copy.deepcopy(decision)))
        if len(set(exact)) > 1:
            raise ValueError('Exact identity split; refusing implicit group union')
        event_id = exact[0] if exact else uid(self.scope, 'event', fp['exact_key'] or cid)
        event = s.get(CorrelationEvent, event_id)
        if event is None:
            event = CorrelationEvent(id=event_id, policy_id=self.scope, revision=0)
            s.add(event); s.flush()
        members = [p for p in prior if p.event_id == event_id]
        # All-member guard prevents A~B~C bridging when A conflicts with C.
        if any(d['mode'] != 'exact_match' for d in decisions if d['candidate_a'] in {p.candidate_id for p in members}):
            raise ValueError('Unsafe transitive merge')
        record = CorrelationCandidate(id=key, policy_id=self.scope, candidate_id=cid,
            document_id=row['document']['document_id'], event_id=event_id,
            payload=copy.deepcopy(row), payload_hash=digest(row), fingerprint=fp)
        s.add(record); members.append(record)
        event.revision += 1
        documents = {}
        for member in members:
            item = member.payload; doc = item['document']
            entry = documents.setdefault(doc['document_id'], {'document_id': doc['document_id'],
                'sources': [], 'candidate_ids': [], 'input_message_ids': [], 'research_ids': [], 'title': item['metadata']['title']})
            for name, value in [('sources', item['metadata']['source']['id']), ('candidate_ids', item['candidate']['candidate_id']),
                                ('input_message_ids', doc['input_message_id']), ('research_ids', item['research_id'])]:
                entry[name] = sorted(set(entry[name]) | {value})
        exact_decisions = [d['decision_id'] for d in decisions if d['mode'] == 'exact_match']
        previous = s.get(CorrelationRevision, (event_id, event.revision - 1)) if event.revision > 1 else None
        payload = {'schema_version': '1.0', 'mode': 'research', 'production_canonical': False,
            'event_id': event_id, 'revision': event.revision, 'event_type': candidate['event_type'],
            'correlation_mode': 'exact_match' if exact else 'insufficient_data',
            'ruleset_version': self.policy['ruleset_version'], 'fingerprint_version': self.policy['fingerprint_version'],
            'policy_id': self.scope, 'configuration_hash': digest(self.policy),
            'document_count': len(documents),
            'independent_source_count': len({source for doc in documents.values() for source in doc['sources']}),
            'source_count_semantics': 'distinct source_id values; not verified independent publishers',
            'documents': [documents[k] for k in sorted(documents)],
            'candidate_ids': sorted(m.candidate_id for m in members),
            'merge_decision_ids': sorted(set((previous.payload['merge_decision_ids'] if previous else []) + exact_decisions)),
            'fingerprints': {m.candidate_id: m.fingerprint for m in sorted(members, key=lambda m: m.candidate_id)},
            'created_at': iso(now())}
        s.add(CorrelationRevision(event_id=event_id, revision=event.revision, payload=payload))
        s.flush()
        return {'status': 'exact_merge' if exact else 'created', 'event_id': event_id, 'revision': event.revision}

    def run_once(self):
        with self.sessions.begin() as s:
            self.locked(s)
            result = s.scalar(select(ResearchResult).where(
                ResearchResult.ruleset_version == self.policy['input_ruleset_version'],
                ~exists().where(CorrelationProcessed.policy_id == self.scope, CorrelationProcessed.research_id == ResearchResult.id)
            ).order_by(ResearchResult.created_at, ResearchResult.id).limit(1))
            if result is None:
                return False
            run = s.get(ResearchRun, result.id)
            rows = projection(result.payload, run.snapshot)
            for row in rows:
                self._accept(s, row)
            s.add(CorrelationProcessed(policy_id=self.scope, research_id=result.id, input_hash=digest(result.payload)))
        return True

    async def work(self):
        return await asyncio.to_thread(self.run_once)

    def stats(self):
        with self.sessions() as s:
            members = list(s.scalars(select(CorrelationCandidate).where(CorrelationCandidate.policy_id == self.scope)))
            decisions = list(s.scalars(select(CorrelationDecision).where(CorrelationDecision.policy_id == self.scope)))
            counts = Counter(d.mode for d in decisions)
            v1 = {e for m in members for e in m.payload['v1_event_ids']}
            processed_documents = set(s.scalars(select(ResearchResult.document_id).join(
                CorrelationProcessed, CorrelationProcessed.research_id == ResearchResult.id
            ).where(CorrelationProcessed.policy_id == self.scope)))
            return {'policy_id': self.scope, 'ruleset_version': self.policy['ruleset_version'],
                'fingerprint_version': self.policy['fingerprint_version'], 'mode': 'research',
                'documents_processed': len(processed_documents | {m.document_id for m in members}),
                'events_before_correlation': len(members), 'events_after_correlation': len({m.event_id for m in members}),
                'exact_merges': len(members) - len({m.event_id for m in members}),
                'pair_decisions': {mode: counts[mode] for mode in ('exact_match', 'strong_match', 'suggestion', 'separate', 'insufficient_data')},
                'suggestions': counts['suggestion'], 'rejected_merges': counts['separate'],
                'conflict_reasons': dict(Counter(k for d in decisions for k in d.payload['conflicting_fields'])),
                'v1_events': len(v1), 'v1_same_event_pairs': sum(d.payload['v1_same_event'] for d in decisions)}

    def events(self):
        with self.sessions() as s:
            return [s.get(CorrelationRevision, (e.id, e.revision)).payload for e in s.scalars(
                select(CorrelationEvent).where(CorrelationEvent.policy_id == self.scope).order_by(CorrelationEvent.id))]

    def revisions(self, event_id):
        with self.sessions() as s:
            return [r.payload for r in s.scalars(select(CorrelationRevision).where(CorrelationRevision.event_id == event_id).order_by(CorrelationRevision.revision))]

    def decisions(self, mode=None, offset=0, limit=100):
        with self.sessions() as s:
            q = select(CorrelationDecision).where(CorrelationDecision.policy_id == self.scope)
            if mode:
                q = q.where(CorrelationDecision.mode == mode)
            return [d.payload for d in s.scalars(q.order_by(CorrelationDecision.id).offset(offset).limit(limit))]

    def for_document(self, document_id):
        with self.sessions() as s:
            rows = []
            for m in s.scalars(select(CorrelationCandidate).where(CorrelationCandidate.document_id == document_id).order_by(CorrelationCandidate.policy_id, CorrelationCandidate.candidate_id)):
                event = s.get(CorrelationEvent, m.event_id)
                decisions = [d.payload for d in s.scalars(select(CorrelationDecision).where(
                    CorrelationDecision.policy_id == m.policy_id,
                    (CorrelationDecision.candidate_a == m.candidate_id) | (CorrelationDecision.candidate_b == m.candidate_id)
                ).order_by(CorrelationDecision.id))]
                rows.append({'document': m.payload['document'], 'research_id': m.payload['research_id'],
                    'candidate_id': m.candidate_id, 'fingerprint': m.fingerprint,
                    'event': s.get(CorrelationRevision, (event.id, event.revision)).payload,
                    'decisions': decisions, 'suggestions': [d for d in decisions if d['mode'] == 'suggestion']})
            return rows
