from pathlib import Path
from pydantic import SecretStr,Field
from pydantic_settings import BaseSettings,SettingsConfigDict
class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_prefix='ARTICLE_SEMANTIC_')
    database_url:SecretStr=SecretStr('mysql+pymysql://article_semantic:local_article_semantic@db/article_semantic')
    nats_url:SecretStr=SecretStr('nats://nats:4222')
    review_token:SecretStr=SecretStr('')
    intelligence_url:str='http://document-intelligence:8009'
    enrichment_url:str='http://enrichment:8001'
    router_url:str='http://article-router:8010'
    configuration_dir:Path=Path('/workspace/config/article_semantic')
    models_dir:Path=Path('/models')
    contracts_dir:Path=Path('/workspace/contracts')
    workers_enabled:bool=True
    durable_prefix:str='ARTICLE_SEMANTIC'
    lease_seconds:int=Field(1800,ge=300,le=7200)
