from typing import Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel,ConfigDict,Field
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
Route=Literal['critical','important','review','low','archive']
Relevance=Literal['none','low','medium','high','unknown']
class Features(Strict):
    market_relevance:Relevance;crypto_relevance:Relevance;macro_relevance:Relevance
    event_specificity:Literal['specific','general','commentary','unknown']
    information_density:Literal['high','medium','low']
    source_quality:Literal['official_primary','high','medium','low','unknown']
    document_quality:Literal['high','medium','low','unknown']
    novelty:Literal['new','supporting_update','duplicate_like','repeated_source_item','unknown']
    financial_fact_count:int=Field(ge=0);measurement_count:int=Field(ge=0);high_value_fact_count:int=Field(ge=0)
class FeatureBasis(Strict):
    reason:str=Field(min_length=1);input_paths:list[str]=Field(min_length=1);rule_ids:list[str];fact_ids:list[UUID]
class FeatureReasons(Strict):
    market_relevance:FeatureBasis;crypto_relevance:FeatureBasis;macro_relevance:FeatureBasis
    event_specificity:FeatureBasis;information_density:FeatureBasis;source_quality:FeatureBasis;document_quality:FeatureBasis
    novelty:FeatureBasis;financial_fact_count:FeatureBasis;measurement_count:FeatureBasis;high_value_fact_count:FeatureBasis
class Basis(Strict):
    ruleset_version:str;high_value_registry_version:str;configuration_hash:str;input_hash:str;snapshot_hash:str
    matched_rule_ids:list[str];reasons:list[str]=Field(min_length=1);feature_basis:FeatureReasons;metadata_warnings:list[str]
class Document(Strict):
    document_id:UUID;intelligence_id:UUID;pipeline_version:str;fact_ruleset_version:str;entity_registry_version:str
class Classification(Strict):route:Route
class Output(Strict):
    schema_version:Literal['1.0'];message_id:UUID;routing_id:UUID;document:Document
    classification:Classification;features:Features;basis:Basis;generated_at:datetime
class LabelRequest(Strict):
    request_id:UUID;expected_revision:int=Field(ge=0)
    status:Literal['new','reviewed','dismissed','escalated']
    reviewer:str=Field(min_length=1,max_length=200)
    usefulness:Literal['useful','not_useful']|None=None
    priority_override:Route|None=None
    facts_correct:bool|None=None;event_type_correct:bool|None=None;duplicate:bool|None=None
    send_to_llm:bool=False
    comment:str=Field(default='',max_length=2000)
