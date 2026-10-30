import copy
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from app.correlation.policy import exact_key,primary_actor,parse_timestamp,suggestion
from app.extraction.models import EventCandidate
from app.storage.models import Event,CandidateRecord,EventDocument,EventRevision,CorrelationSuggestion,OutboxEvent,new_id,utcnow


QUALITY_RANK={'low':0,'medium':1,'high':2}


class EventCore:
    def __init__(self,repository,contract,bundle):
        self.repository,self.contract,self.bundle=repository,contract,bundle
    def validate_candidate(self,candidate,document):
        candidate=EventCandidate.model_validate(candidate.model_dump())
        if candidate.document_id!=document['document_id'] or candidate.event_type not in self.bundle.taxonomy.event_types:
            raise ValueError('invalid_candidate_identity_or_type')
        if not set(candidate.topics)<=set(self.bundle.taxonomy.topics) or not set(candidate.jurisdictions)<=set(self.bundle.registry.jurisdictions):
            raise ValueError('invalid_candidate_vocabulary')
        for actor in candidate.actors:
            if actor.resolution=='canonical':
                entity=self.bundle.registry.entities.get(actor.entity_id)
                if entity is None or entity.name!=actor.name or entity.entity_type!=actor.entity_type:
                    raise ValueError('unknown_canonical_actor')
            elif actor.entity_id is not None:
                raise ValueError('unresolved_actor_has_id')
        expected=exact_key(candidate.event_type,primary_actor([a.model_dump() for a in candidate.actors]),
            candidate.event_time,candidate.event_time_precision,candidate.correlation_features.get('identity_namespace'))
        if expected!=candidate.exact_event_key:
            raise ValueError('invalid_exact_key')
        return candidate
    def complete(self,job,document,candidates,quality,extractor_name,extractor_version):
        candidates=[self.validate_candidate(c,document) for c in candidates]
        if len(candidates)>32 or len({c.candidate_id for c in candidates})!=len(candidates):
            raise ValueError('invalid_candidate_batch')
        # Consistent key order limits lock inversion for future multi-candidate extractors.
        candidates.sort(key=lambda c:(c.exact_event_key or c.candidate_id,c.candidate_id))
        with self.repository.sessions.begin() as session:
            current=self.repository.locked_job(session,job)
            result={'outcome':'no_event' if not candidates else 'event_created','candidates':[c.model_dump() for c in candidates],'events':[]}
            run=self.repository.record_run(session,job,document,self.bundle,quality,result,extractor_name,extractor_version)
            outcomes=[]
            for candidate in candidates:
                session.add(CandidateRecord(id=candidate.candidate_id,run_id=run.id,document_id=document['document_id'],payload=candidate.model_dump()))
                session.flush()
                event_id=new_id()
                values=dict(id=event_id,exact_event_key=candidate.exact_event_key,revision=0,event_type=candidate.event_type,
                    primary_actor=primary_actor([a.model_dump() for a in candidate.actors]),payload={},created_at=utcnow(),updated_at=utcnow())
                statement=insert(Event).values(**values)
                session.execute(statement.on_duplicate_key_update(id=Event.id))
                selector=Event.exact_event_key==candidate.exact_event_key if candidate.exact_event_key else Event.id==event_id
                event=session.scalar(select(Event).where(selector).with_for_update().execution_options(populate_existing=True))
                created=event.revision==0
                if not created and (event.event_type!=candidate.event_type or event.primary_actor!=values['primary_actor']):
                    raise ValueError('exact_key_identity_conflict')
                # Two candidates from a document may refer to the same event, but evidence/revision is attached once.
                existing=session.get(EventDocument,(event.id,document['document_id']))
                if existing:
                    result['events'].append({'candidate_id':candidate.candidate_id,'event_id':event.id,'revision':event.revision,'outcome':'already_attached'})
                    continue
                evidence={'document_id':document['document_id'],'input_message_id':document['message_id'],
                    'source_message_id':document['lineage']['source_message_id'],'source_id':document['source']['id'],
                    'relation':'primary' if created else 'supporting','document_status':document['enrichment']['status'],
                    'content_chars':len(document['content']['body']),'quality':quality.quality,'extraction_run_id':run.id}
                session.add(EventDocument(event_id=event.id,document_id=document['document_id'],candidate_id=candidate.candidate_id,
                    relation=evidence['relation'],evidence=evidence))
                payload=self.project(event,candidate,evidence,document,created)
                self.contract.validate(payload)
                # Explicit delivery-size guard: never commit an event that cannot fit the output stream.
                import json
                if len(json.dumps(payload,ensure_ascii=False).encode())>1_000_000:
                    raise ValueError('canonical_payload_size_limit')
                event.revision=payload['event']['revision'];event.payload=payload;event.updated_at=utcnow()
                session.add(EventRevision(event_id=event.id,revision=event.revision,message_id=payload['message_id'],payload=payload))
                session.add(OutboxEvent(event_id=event.id,revision=event.revision,message_id=payload['message_id'],
                    subject='event.detected.v1' if created else 'event.updated.v1',payload=payload))
                session.flush()
                if created:
                    self.suggest(session,event)
                outcome='event_created' if created else 'event_correlated'
                outcomes.append(outcome)
                result['events'].append({'candidate_id':candidate.candidate_id,'event_id':event.id,'revision':event.revision,'outcome':outcome})
            result['outcome']='event_created' if 'event_created' in outcomes else ('event_correlated' if candidates else 'no_event')
            run.result_json=copy.deepcopy(result)  # Only initial transaction; committed runs are immutable.
            current.status,current.outcome='completed',result['outcome']
            current.completed_at=utcnow();current.lease_token=current.lease_until=None
            session.flush()
            return result
    def project(self,event,candidate,evidence,document,created):
        now=utcnow().replace(tzinfo=timezone.utc).isoformat()
        published=document['timestamps']['published_at']
        if created:
            payload={'schema_version':'1.0','message_id':new_id(),'event':{'id':event.id,'revision':1,'change_type':'created'},
                'taxonomy':{'version':candidate.taxonomy_version,'event_type':candidate.event_type,'topics':candidate.topics,'classification_basis':candidate.classification_basis},
                'content':{'canonical_title':candidate.canonical_title},'actors':[a.model_dump() for a in candidate.actors],
                'jurisdictions':candidate.jurisdictions,'time':{'event_time':candidate.event_time,'event_time_precision':candidate.event_time_precision,
                    'event_time_source':candidate.event_time_source,'earliest_source_published_at':published,'latest_source_published_at':published,
                    'first_detected_at':now,'last_updated_at':now},'lifecycle':{'status':'detected'},
                'evidence':{'quality':evidence['quality'],'document_count':1,'independent_source_count':1,'documents':[evidence]},
                'extraction':{'extractor':candidate.extractor_name,'extractor_version':candidate.extractor_version,
                    'ruleset_version':candidate.ruleset_version,'entity_registry_version':candidate.entity_registry_version,
                    'matched_rule_ids':candidate.matched_rule_ids,'configuration_hash':self.bundle.fingerprint(),'core_version':'1.0'},
                'correlation':{'method':'new_event','exact_event_key':candidate.exact_event_key}}
        else:
            payload=copy.deepcopy(event.payload)
            payload['message_id']=new_id()
            payload['event'].update(revision=event.revision+1,change_type='updated')
            payload['correlation']['method']='exact_key'
            payload['time']['last_updated_at']=now
            timestamps=[v for v in [published,payload['time']['earliest_source_published_at'],payload['time']['latest_source_published_at']] if v]
            payload['time']['earliest_source_published_at']=min(timestamps,key=parse_timestamp) if timestamps else None
            payload['time']['latest_source_published_at']=max(timestamps,key=parse_timestamp) if timestamps else None
            payload['evidence']['documents'].append(evidence)
            payload['evidence']['document_count']=len(payload['evidence']['documents'])
            sources=len({d['source_id'] for d in payload['evidence']['documents']})
            payload['evidence']['independent_source_count']=sources
            payload['evidence']['quality']=max((d['quality'] for d in payload['evidence']['documents']),key=QUALITY_RANK.get)
            payload['lifecycle']['status']='corroborated' if sources>=2 else 'detected'
            # Primary title/classification/provenance stays stable. Each supporting run has its own full provenance.
        return payload
    def suggest(self,session,event):
        others=session.scalars(select(Event).where(Event.id!=event.id,Event.event_type==event.event_type,
            Event.primary_actor==event.primary_actor,Event.revision>0).order_by(Event.updated_at.desc(),Event.id)
            .limit(self.bundle.sources.correlation.max_candidates))
        for other in others:
            details=suggestion(event.payload,other.payload,self.bundle.sources.correlation)
            if details:
                a,b=sorted([event.id,other.id])
                statement=insert(CorrelationSuggestion).values(event_a=a,event_b=b,**details,
                    policy_hash=self.bundle.fingerprint(),created_at=utcnow())
                session.execute(statement.on_duplicate_key_update(event_a=CorrelationSuggestion.event_a))
