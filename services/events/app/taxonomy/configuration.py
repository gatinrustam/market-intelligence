import hashlib
import json
import re
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Taxonomy(StrictModel):
    version: str = Field(pattern=r'^\d+\.\d+$')
    event_types: list[str] = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    @model_validator(mode='after')
    def vocabulary(self):
        for values in (self.event_types, self.topics):
            if len(values)!=len(set(values)) or any(not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?', v) for v in values):
                raise ValueError('invalid or duplicate vocabulary')
        if 'unknown' not in self.event_types:
            raise ValueError('unknown event type required')
        return self


class Entity(StrictModel):
    entity_type: Literal['organization','person','company','government','exchange','protocol']
    name: str = Field(min_length=1,max_length=200)
    aliases: list[str] = []


class Registry(StrictModel):
    version: str = Field(pattern=r'^\d+\.\d+$')
    entities: dict[str,Entity] = Field(min_length=1)
    jurisdictions: list[str] = Field(min_length=1)
    @model_validator(mode='after')
    def valid_registry(self):
        names=[]
        for key,entity in self.entities.items():
            if not re.fullmatch(entity.entity_type+r':[a-z][a-z0-9_]*',key):
                raise ValueError('invalid entity id')
            names.extend(x.casefold() for x in [entity.name,*entity.aliases])
        if len(set(names))!=len(names):
            raise ValueError('ambiguous entity alias')
        if len(set(self.jurisdictions))!=len(self.jurisdictions) or any(not re.fullmatch('[A-Z]{2}',j) for j in self.jurisdictions):
            raise ValueError('invalid jurisdiction')
        return self


class Source(StrictModel):
    issuer: str
    jurisdictions: list[str]
    fallback_type: str


class Quality(StrictModel):
    title_min_characters: int = Field(default=8,ge=1,le=4096)
    body_min_characters: int = Field(default=80,ge=1,le=200000)
    high_body_characters: int = Field(default=500,ge=1,le=200000)
    @model_validator(mode='after')
    def thresholds(self):
        if self.high_body_characters<self.body_min_characters:
            raise ValueError('high threshold below meaningful body threshold')
        return self


class Correlation(StrictModel):
    title_jaccard_threshold: float = Field(default=.7,ge=0,le=1)
    time_window_seconds: int = Field(default=604800,ge=0,le=31536000)
    max_candidates: int = Field(default=500,ge=1,le=5000)


class Sources(StrictModel):
    version: str = Field(pattern=r'^\d+\.\d+$')
    sources: dict[str,Source]
    quality: Quality = Quality()
    correlation: Correlation = Correlation()


class Rule(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_.]+$',max_length=100)
    priority: int = Field(ge=0,le=10000)
    source_id: list[str] = Field(min_length=1)
    title_regex: list[str] = []
    url_regex: list[str] = []
    event_type: str
    topics: list[str] = []
    classification_basis: Literal['exact_rule','heuristic_rule']
    speaker_title_regex: str | None = None
    identity_namespace: str | None = Field(default=None,pattern=r'^[a-z][a-z0-9_.]+$',max_length=100)
    identity_title_regex: str | None = None
    @model_validator(mode='after')
    def patterns(self):
        if not self.title_regex and not self.url_regex:
            raise ValueError('rule requires a matcher')
        if bool(self.identity_namespace)!=bool(self.identity_title_regex):
            raise ValueError('identity requires namespace and explicit title matcher')
        for pattern in [*self.title_regex,*self.url_regex,self.speaker_title_regex,self.identity_title_regex]:
            if pattern is not None:
                re.compile(pattern)
        if self.speaker_title_regex and 'name' not in re.compile(self.speaker_title_regex).groupindex:
            raise ValueError('speaker pattern requires named name group')
        return self


class Rules(StrictModel):
    version: str = Field(pattern=r'^\d+\.\d+$')
    rules: list[Rule] = Field(min_length=1)


class Bundle(StrictModel):
    taxonomy: Taxonomy
    registry: Registry
    sources: Sources
    rules: Rules
    @model_validator(mode='after')
    def references(self):
        for key,source in self.sources.sources.items():
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',key):
                raise ValueError('invalid source id')
            if source.issuer not in self.registry.entities or source.fallback_type not in self.taxonomy.event_types:
                raise ValueError('unknown source reference')
            if not set(source.jurisdictions)<=set(self.registry.jurisdictions):
                raise ValueError('unknown jurisdiction')
        ids=set()
        for rule in self.rules.rules:
            if rule.id in ids or rule.event_type not in self.taxonomy.event_types or not set(rule.topics)<=set(self.taxonomy.topics):
                raise ValueError('invalid rule taxonomy or duplicate id')
            if not set(rule.source_id)<=set(self.sources.sources):
                raise ValueError('unknown rule source')
            ids.add(rule.id)
        return self
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.model_dump(),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def load_bundle(directory: Path):
    try:
        rule_files=sorted((directory/'rules').glob('*.yaml'))
        rule_sets=[Rules.model_validate(yaml.safe_load(p.read_text())) for p in rule_files]
        if not rule_sets or len({r.version for r in rule_sets})!=1:
            raise ValueError('one consistent ruleset version required')
        return Bundle(taxonomy=Taxonomy.model_validate(yaml.safe_load((directory/'taxonomy.v1.yaml').read_text())),
            registry=Registry.model_validate(yaml.safe_load((directory/'entities.v1.yaml').read_text())),
            sources=Sources.model_validate(yaml.safe_load((directory/'sources.yaml').read_text())),
            rules=Rules(version=rule_sets[0].version,rules=[rule for rules in rule_sets for rule in rules.rules]))
    except ValidationError as exc:
        raise ValueError('Invalid event configuration: '+ '; '.join('.'.join(map(str,e['loc']))+':'+e['type'] for e in exc.errors())) from None
    except Exception as exc:
        raise ValueError('Cannot load event configuration: '+type(exc).__name__) from None
