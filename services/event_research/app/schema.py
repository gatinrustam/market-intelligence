from typing import Literal
from datetime import datetime
from uuid import UUID
from pydantic import Field
from app.di_schema import Strict,Evidence,Extraction,Measurement,Date,Versions
class FactReference(Strict):
    document_id:UUID;fact_id:UUID;fact_type:str;relation_id:UUID;evidence:Evidence;extraction:Extraction
class Actor(Strict):
    entity_id:str;mention_id:UUID;name:str;entity_type:str;resolution:Literal['canonical','unresolved']
class FactMeasurement(Strict):
    fact_ids:list[UUID]=Field(min_length=1);measurement:Measurement
class FactDate(Strict):
    fact_ids:list[UUID]=Field(min_length=1);date:Date
class Signal(Strict):
    kind:Literal['primary_fact','supporting_rule','fallback_rule'];event_type:str;rule_id:str
    fact_ids:list[UUID];reason:str
class Candidate(Strict):
    candidate_id:UUID;document_id:UUID;event_type:str
    primary_fact_ids:list[UUID];supporting_fact_ids:list[UUID];fact_references:list[FactReference]
    actors:list[Actor];topics:list[str];measurements:list[FactMeasurement];dates:list[FactDate]
    event_time:datetime|None;event_time_basis:Literal['explicit_fact_datetime','unavailable']
    classification_basis:Literal['primary_fact','fallback_rule'];signals:list[Signal]
class Alternative(Strict):
    event_type:str;basis:Literal['primary_fact','supporting_rule','fallback_rule','legacy_v1'];rule_ids:list[str];fact_ids:list[UUID]
class Conflict(Strict):
    kind:Literal['classification_conflict'];selected_event_types:list[str];alternatives:list[Alternative];reason:str
class IgnoredFact(Strict):fact_id:UUID;reason:str
class Document(Strict):
    document_id:UUID;intelligence_id:UUID;input_message_id:UUID;source_message_id:UUID;body_hash:str
class Basis(Strict):
    ruleset_version:str;configuration_hash:str;input_hash:str;context_hash:str;extraction:Versions
    warnings:list[str];ignored_facts:list[IgnoredFact]
class Output(Strict):
    schema_version:Literal['2.0'];message_id:UUID;research_id:UUID
    mode:Literal['research'];production_canonical:Literal[False];merge_enabled:Literal[False]
    document:Document;candidates:list[Candidate];conflicts:list[Conflict];basis:Basis;generated_at:datetime
class V1Basis(Strict):event_type:str;classification_basis:str;rule_ids:list[str]
class Flags(Strict):
    same_classification:bool;changed_classification:bool;fallback_used:bool;conflict:bool;multiple_candidates:bool;no_event:bool;fact_based:bool
class HumanSignal(Strict):
    routing_id:UUID;request_id:UUID;revision:int;event_type_correct:bool|None;facts_correct:bool|None
    reviewed_v1_types:list[str];v2_differs_from_v1:bool;v2_conflict_visible:bool
    scope:Literal['evaluation_only_not_ground_truth'];comment:str
class Comparison(Strict):
    document_id:UUID;research_id:UUID;v1_event_types:list[str];v2_event_types:list[str]
    v1_basis:list[V1Basis];v2_basis:list[Literal['primary_fact','fallback_rule']]
    primary_fact_ids:list[UUID];flags:Flags;human_evaluation:list[HumanSignal];warnings:list[str]
