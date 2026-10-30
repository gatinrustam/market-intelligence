import re
from uuid import uuid4
from app.correlation.policy import exact_key
from app.entities.resolution import issuer,speaker
from app.extraction.models import EventCandidate
from app.extraction.quality import quality_gate,normalize
from app.extraction.time import extract_title_time


class RuleBasedEventExtractor:
    name='rule_based'
    version='1.0'
    def __init__(self,bundle):
        self.bundle=bundle
        self.rules=sorted(bundle.rules.rules,key=lambda rule:(-rule.priority,rule.id))
    def extract(self,document):
        quality=quality_gate(document,self.bundle.sources.quality)
        if not quality.usable:
            return []
        source_id=document['source']['id']
        title=normalize(document['content']['title'])
        url=document['source']['url'] or ''
        source=self.bundle.sources.sources.get(source_id)
        rule=next((r for r in self.rules if source_id in r.source_id and
            (any(re.search(p,title) for p in r.title_regex) or any(re.search(p,url) for p in r.url_regex))),None)
        event_type=rule.event_type if rule else (source.fallback_type if source else 'unknown')
        actors=[issuer(source,self.bundle.registry)] if source else []
        if rule and rule.speaker_title_regex:
            match=re.search(rule.speaker_title_regex,title)
            if match:
                # Avoid assigning a single person identity to a combined multi-speaker string.
                name=normalize(match['name'])
                if ',' not in name and ' and ' not in name:
                    actors.append(speaker(name,self.bundle.registry))
        # Dates only interpreted for a configured event identity pattern; incidental title dates
        # (e.g. a report covering a year) do not become event time.
        namespace=None
        event_time,precision,time_source=None,'unknown','not_extracted'
        if rule and rule.identity_title_regex and re.search(rule.identity_title_regex,title):
            event_time,precision,time_source=extract_title_time(title)
            if event_time:
                namespace=rule.identity_namespace
        actor=source.issuer if source else None
        key=exact_key(event_type,actor,event_time,precision,namespace)
        candidate=EventCandidate(candidate_id=str(uuid4()),document_id=document['document_id'],
            event_type=event_type,canonical_title=title,
            topics=rule.topics if rule else [],actors=actors,jurisdictions=source.jurisdictions if source else [],
            classification_basis=rule.classification_basis if rule else 'fallback',
            event_time=event_time,event_time_precision=precision,event_time_source=time_source,exact_event_key=key,
            correlation_features={'identity_namespace':namespace,'primary_actor':actor},
            extractor_name=self.name,extractor_version=self.version,ruleset_version=self.bundle.rules.version,
            taxonomy_version=self.bundle.taxonomy.version,entity_registry_version=self.bundle.registry.version,
            matched_rule_ids=[rule.id] if rule else [f'fallback.{source_id}' if source else 'fallback.unknown'],input_quality=quality)
        return [candidate]
