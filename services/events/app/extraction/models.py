from typing import Literal, Protocol
from pydantic import Field
from app.taxonomy.configuration import StrictModel


class Actor(StrictModel):
    entity_id: str | None
    entity_type: Literal['person','company','organization','government','exchange','protocol']
    name: str = Field(min_length=1,max_length=200)
    role: Literal['issuer','speaker','subject']
    resolution: Literal['canonical','unresolved']


class InputQuality(StrictModel):
    usable: bool
    quality: Literal['high','medium','low']
    reason: Literal['ready_substantial','partial_meaningful','limited_evidence','no_usable_content']
    document_status: Literal['ready','partial','failed','rejected']
    title_characters: int
    body_characters: int


class EventCandidate(StrictModel):
    candidate_id: str
    document_id: str
    event_type: str
    canonical_title: str = Field(min_length=0,max_length=4096)
    topics: list[str]
    actors: list[Actor]
    jurisdictions: list[str]
    classification_basis: Literal['exact_rule','heuristic_rule','fallback']
    event_time: str | None
    event_time_precision: Literal['exact','minute','hour','date','date_range','unknown']
    event_time_source: Literal['title','body','not_extracted']
    exact_event_key: str | None
    correlation_features: dict
    extractor_name: str
    extractor_version: str
    ruleset_version: str
    taxonomy_version: str
    entity_registry_version: str
    matched_rule_ids: list[str]
    input_quality: InputQuality


class EventExtractor(Protocol):
    name: str
    version: str
    def extract(self, document: dict) -> list[EventCandidate]: ...
