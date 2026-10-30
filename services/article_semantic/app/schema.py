from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from app.di_schema import Fact,Measurement
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
Level=Literal['none','low','medium','high']
ArticleType=Literal['primary_announcement','data_release','regulatory_action','incident','analysis','commentary','interview','speech','personnel','administrative','unknown']
Route=Literal['critical','important','review','low','archive']
class Span(Strict):
    document_id:UUID;chunk_id:UUID;start_char:int=Field(ge=0);end_char:int=Field(gt=0);text:str
class ChunkReference(Strict):
    chunk_id:UUID;document_id:UUID;start_char:int;end_char:int;sentence_ids:list[int];token_count:int
class Match(Strict):
    positive_similarity:float|None=None;negative_similarity:float|None=None;semantic_margin:float|None=None
    concept_id:str;similarity:float=Field(ge=-1,le=1);chunk_id:UUID;evidence:Span
    model_version:str;ontology_version:str
class Concept(Strict):
    concept_id:str;strength:Level;max_similarity:float;matches:list[Match]
class Entity(Strict):
    entity_id:str;name:str;type:str;extractor:Literal['di','gliner'];confidence:float|None=Field(default=None,ge=0,le=1)
    evidence:list[Span];status:Literal['deterministic','candidate']
class Relation(Strict):
    relation_id:str;subject:str|None;predicate:str;object:str|None
    extractor:Literal['di','gliner'];confidence:float|None=Field(default=None,ge=0,le=1)
    support_method:str;status:Literal['deterministic','candidate'];evidence:Span;supporting_fact_ids:list[UUID]
class Claim(Strict):
    claim_id:UUID;type:str;subject:str|None;action:str|None;object_value:str|None
    evidence:Span;extractor:Literal['di','gliner','semantic'];supporting_fact_ids:list[UUID]
    status:Literal['deterministic','supported_candidate','semantic_candidate'];reason:str
class Asset(Strict):
    asset:Literal['BTC','ETH','crypto_market','USD','EUR','US_equities','specific_company','rates','gold','RUB','RU_equities','fx_market']
    relevance:Level;basis:list[str];evidence:list[Span];direct:bool
class Feature(Strict):
    level:Level;reasons:list[str]=Field(min_length=1);evidence:list[Span]
class InformationValue(Strict):
    market_relevance:Feature;crypto_relevance:Feature;macro_relevance:Feature
    event_specificity:Feature;information_density:Feature;actionability:Feature
    source_quality:Feature;document_quality:Feature;semantic_strength:Feature;fact_support:Feature
class Conflict(Strict):
    status:Literal['conflict'];deterministic_fact_ids:list[UUID];semantic_concept_ids:list[str];reason:str;evidence:list[Span]
class Document(Strict):
    document_id:UUID;intelligence_id:UUID;input_message_id:UUID;source_message_id:UUID;body_hash:str
    title:str;source_id:str;source_url:str|None;language:str;published_at:datetime|None
    body_characters:int;document_status:str
class Provenance(Strict):
    semantic_runtime_hash:str|None=None
    semantic_model:str;semantic_model_revision:str;semantic_model_hash:str
    gliner_model:str;gliner_model_revision:str;gliner_model_hash:str
    gliner_backbone_revision:str;ontology_version:str;threshold_version:str;pipeline_version:str
    chunking_version:str;configuration_hash:str;input_hash:str;runtime_versions:dict[str,str];dtype:str
class Routing(Strict):
    old_route:Route|None;old_routing_id:UUID|None;semantic_suggested_route:Route
    disagreement:bool|None;reasons:list[str];production_switch:Literal[False]
class Performance(Strict):
    latency_seconds:float;embedding_seconds:float;gliner_seconds:float;chunks_per_second:float
    documents_per_second:float;rss_bytes:int;peak_rss_bytes:int;chunks:int
class EvidenceSummary(Strict):
    semantic_evidence_count:int;independent_evidence_count:int;max_similarity:float;mean_supporting_similarity:float
    di_fact_support:list[str];entity_support:list[str];relation_support:list[str];article_section_support:list[str]
    negative_evidence:list[Match];supporting_spans:list[Span]
class ConceptDecision(Strict):
    concept_id:str;decision:Literal['accepted','rejected','review'];reasons:list[str];summary:EvidenceSummary
class ClaimDecision(Strict):
    start_char:int;end_char:int;decision:Literal['accepted','rejected'];reasons:list[str]
class Comparison(Strict):
    baseline_id:UUID;baseline_hash:str;concepts_removed:list[str];concepts_added:list[str]
    assets_removed:list[str];assets_added:list[str];claims_removed:list[str];claims_added:list[str]
    importance_before:str;importance_after:str;routing_before:str;routing_after:str
class Reranking(Strict):
    policy_version:str;status:Literal['complete','failed'];decisions:list[ConceptDecision]
    claim_decisions:list[ClaimDecision];importance_components:dict[str,Feature];latency_seconds:float
class Output(Strict):
    reranking:Reranking|None=None;comparison:Comparison|None=None
    schema_version:Literal['1.0'];message_id:UUID;semantic_id:UUID;document:Document
    status:Literal['complete','partial','failed'];mode:Literal['research'];domains:list[str]
    chunks:list[ChunkReference];semantic_concepts:list[Concept];top_matches:list[Match]
    entities:list[Entity];relations:list[Relation];facts:list[Fact];claims:list[Claim]
    affected_assets:list[Asset];article_type:ArticleType;article_type_basis:list[str]
    information_value:InformationValue;important_numbers:list[Measurement];conflicts:list[Conflict]
    routing:Routing;provenance:Provenance;warnings:list[str];performance:Performance;generated_at:datetime
class LabelRequest(Strict):
    request_id:UUID;expected_revision:int=Field(ge=0);status:Literal['new','reviewed'];reviewer:str=Field(min_length=1,max_length=200)
    concepts_correct:bool|None=None;false_positives:list[str]=[];gold_concepts:list[str]=[]
    semantic_correct:bool|None=None;claims_correct:bool|None=None;assets_correct:bool|None=None
    importance_correct:bool|None=None;missing_context:bool|None=None
    gold_important:bool|None=None;gold_assets:list[str]=[];correct_claim_ids:list[UUID]=[]
    comment:str=Field(default='',max_length=4000)
