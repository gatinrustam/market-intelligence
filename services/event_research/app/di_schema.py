from typing import Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Evidence(Strict):
    document_id:UUID;sentence_id:int=Field(ge=0);start_char:int=Field(ge=0);end_char:int=Field(gt=0);text:str=Field(min_length=1)
class Extraction(Strict):
    method:Literal['registry','statistical_ner','rule_based','dependency_rule'];extractor:str;rule_id:str;extractor_version:str
class Explained(Strict):
    evidence:Evidence;extraction:Extraction
class Entity(Explained):
    mention_id:UUID;entity_id:str;canonical_name:str
    type:Literal['organization','person','location','asset','currency','financial_instrument','economic_indicator']
    registry:bool
class Measurement(Explained):
    measurement_id:UUID
    kind:Literal['percentage','percentage_points','basis_points','money','price','quantity','ratio','rate']
    value:str|None;min:str|None;max:str|None;unit:str;currency:str|None
class Date(Explained):
    date_id:UUID;kind:Literal['date','time','date_range','period'];raw:str;normalized:str|None
class Reference(Strict):entity_id:str;mention_id:UUID
class Span(Strict):
    text:str;start_char:int;end_char:int
class Argument(Strict):
    entity_id:str|None;mention_id:UUID|None;text:str;start_char:int;end_char:int
class Relation(Explained):
    relation_id:UUID;subject:Reference;action:str;object:Argument;predicate:Span
    modality:Literal['asserted','forward_looking']
FactType=Literal["monetary_policy.rate_decision","monetary_policy.guidance","economic_data.inflation","economic_data.employment","economic_data.gdp","economic_data.wages","regulation.rule_proposal","regulation.rule_adoption","regulation.enforcement","crypto.exchange_outage","crypto.withdrawal_suspension","crypto.security_incident","crypto.stablecoin_depeg","crypto.treasury_purchase","crypto.etf_action","crypto.exchange_listing","crypto.exchange_delisting","crypto.deposit_suspension","crypto.stablecoin_change","crypto.treasury_sale","crypto.treasury_holdings","crypto.institutional_product"]
class Fact(Explained):
    fact_id:UUID;fact_type:FactType;subject:Reference;action:str;relation_id:UUID
    values:list[Measurement]
    asset:str|None=None
    quantity:str|None=None
    aggregate_value_usd:str|None=None
    average_price_usd:str|None=None
class Topic(Explained):
    topic:Literal["monetary_policy","interest_rates","inflation","employment","wages","economic_growth","financial_stability","regulation","capital_markets","digital_assets","bitcoin","ethereum","crypto_exchange","stablecoin"];fact_ids:list[UUID]=Field(min_length=1)
class Document(Strict):document_id:UUID;source_message_id:UUID;input_message_id:UUID;body_hash:str
class Sentence(Strict):sentence_id:int;start_char:int;end_char:int
class Models(Strict):
    en:str;ru:str
class Versions(Strict):
    pipeline_version:str;entity_registry_version:str;fact_ruleset_version:str;configuration_hash:str
    nlp_models:Models
class Warning(Strict):component:str;code:str
class Processing(Strict):status:Literal['complete','partial','unsupported'];warnings:list[Warning]
class Output(Strict):
    schema_version:Literal['1.0'];message_id:UUID;intelligence_id:UUID;document:Document
    language:Literal['en','ru','unsupported'];language_detector:Literal['langdetect_seed_0_rules_v1']
    sentences:list[Sentence];entities:list[Entity];measurements:list[Measurement];dates:list[Date]
    relations:list[Relation];facts:list[Fact];topics:list[Topic];extraction:Versions;processing:Processing
