import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Relevance = Literal['none','low','medium','high']
Specificity = Literal['specific','general','commentary','unknown']
RANK = {'none':0, 'low':1, 'medium':2, 'high':3}
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def now(): return datetime.now(timezone.utc)
def iso(value): return value.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def input_identity(event): return str(uuid5(NAMESPACE_URL, f"intelligence.input:{event['id']}:{event['revision']}"))
def identity(event, version): return str(uuid5(NAMESPACE_URL, f"event.intelligence.v1:{event['id']}:{event['revision']}:BTCUSDT:{version}"))
class Strict(BaseModel): model_config = ConfigDict(extra='forbid')
class Rule(Strict):
    id: str = Field(min_length=1, max_length=100)
    event_types: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    topics_any: list[str] = Field(default_factory=list)
    canonical_rule_ids: list[str] = Field(default_factory=list)
    title_patterns: list[str] = Field(default_factory=list)
    relevance: Relevance | None = None
    minimum_relevance: Relevance | None = None
    specificity: Specificity | None = None
    @model_validator(mode='after')
    def bounded(self):
        if not any((self.event_types,self.sources,self.topics_any,self.canonical_rule_ids,self.title_patterns)): raise ValueError('unbounded rule')
        if not any((self.relevance,self.minimum_relevance,self.specificity)): raise ValueError('empty rule')
        for pattern in self.title_patterns:re.compile(pattern)
        return self
class Quality(Strict):
    trusted_sources: list[str]
    trusted_source_types: list[str]
    high_min_sources: int = Field(ge=1)
    corroborated_min_sources: int = Field(ge=2)
    partial_cap: Literal['low','medium']
class Novelty(Strict):
    new_methods: list[str]
    update_methods: list[str]
    scope: Literal['canonical_revision_history_only']
class Rules(Strict):
    version: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,32}$')
    asset: Literal['BTCUSDT']
    default_relevance: Relevance
    default_specificity: Specificity
    rules: list[Rule]
    quality: Quality
    novelty: Novelty
    @model_validator(mode='after')
    def unique(self):
        if len({r.id for r in self.rules}) != len(self.rules): raise ValueError('duplicate rule id')
        return self

def load_rules(path): return Rules.model_validate_json(path.read_text()).model_dump()

def semantic(event):
    return {k:event[k] for k in ('taxonomy','content','actors','jurisdictions')} | {'event_time':event['time']['event_time']}

def features(snapshot, config):
    event, docs = snapshot['event'], snapshot['documents']
    sources = {r['source_id'] for r in event['evidence']['documents']}
    topics = set(event['taxonomy']['topics'])
    matched = []
    relevance, specificity = config['default_relevance'], config['default_specificity']
    for rule in config['rules']:
        if rule['event_types'] and event['taxonomy']['event_type'] not in rule['event_types']: continue
        if rule['sources'] and not sources.intersection(rule['sources']): continue
        if rule['topics_any'] and not topics.intersection(rule['topics_any']): continue
        if rule['canonical_rule_ids'] and not set(event['extraction']['matched_rule_ids']).intersection(rule['canonical_rule_ids']): continue
        if rule.get('title_patterns') and not any(re.search(pattern,event['content']['canonical_title']) for pattern in rule['title_patterns']):continue
        matched.append(rule['id'])
        if rule['relevance'] is not None: relevance = rule['relevance']
        if rule['minimum_relevance'] is not None: relevance = max(relevance, rule['minimum_relevance'], key=RANK.get)
        if rule['specificity'] is not None: specificity = rule['specificity']
    previous = snapshot['previous']
    if event['event']['revision'] > 1:
        novelty = 'update' if event['correlation']['method'] in config['novelty']['update_methods'] else 'unknown'
        if previous and semantic(event)==semantic(previous['event']):
            before = {d['integrity']['content_hash'] for d in previous['documents']}
            if docs and {d['integrity']['content_hash'] for d in docs} <= before:
                novelty = 'duplicate_like'
    else:
        novelty = 'new' if event['correlation']['method'] in config['novelty']['new_methods'] else 'unknown'
    matched.append('novelty.'+novelty)
    q = config['quality']
    statuses = [d['enrichment']['status'] for d in docs]
    ref_quality = [r['quality'] for r in event['evidence']['documents']]
    trusted = bool(docs) and all(d['source']['id'] in q['trusted_sources'] and d['source']['type'] in q['trusted_source_types'] for d in docs)
    quality = 'low'
    if docs and any(d['content']['body'] for d in docs) and event['evidence']['quality']!='low':
        quality = 'medium'
        independent = event['evidence']['independent_source_count']
        if trusted and all(s=='ready' for s in statuses) and all(x=='high' for x in ref_quality) and event['evidence']['quality']=='high' and independent>=q['high_min_sources']:
            quality='high';matched.append('quality.trusted_ready')
        if event['lifecycle']['status']=='corroborated' and trusted and independent>=q['corroborated_min_sources'] and all(s=='ready' for s in statuses) and 'low' not in ref_quality:
            quality='high';matched.append('quality.corroborated')
        if any(s!='ready' for s in statuses):
            quality=min(quality,q['partial_cap'],key=RANK.get);matched.append('quality.partial_cap')
    matched.append('quality.'+quality)
    return {'relevance':relevance,'novelty':novelty,'information_quality':quality,'event_specificity':specificity,
        'surprise':{'status':'unavailable','value':None},
        'expectations':dict.fromkeys(('type','previous','consensus','actual','unit','source'))}, matched

def build_result(run, snapshot, clock=now):
    values, matched = features(snapshot, run.configuration)
    event = snapshot['event']
    return {'schema_version':'1.0','message_id':run.id,'intelligence_id':run.id,
        'event':{'event_id':event['event']['id'],'event_revision':event['event']['revision']},'asset':{'symbol':'BTCUSDT'},
        **values,'generated_at':iso(clock()),
        'basis':{'ruleset_version':run.ruleset_version,'ruleset_hash':digest(run.configuration),'matched_rule_ids':matched,
            'canonical_hash':digest(event),'input_hash':digest(snapshot),'novelty_scope':'canonical_revision_history_only',
            'previous_event_revision':snapshot['previous']['event']['event']['revision'] if snapshot['previous'] else None,
            'evidence_hashes':[{'document_id':d['document_id'],'message_id':d['message_id'],'content_hash':d['integrity']['content_hash']} for d in snapshot['documents']],
            'quality_basis':'deterministic_not_statistical_confidence','expectations_basis':'no_external_provider'}}
