from pathlib import Path
from pydantic import SecretStr,Field
from pydantic_settings import BaseSettings,SettingsConfigDict
class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_prefix='ARTICLE_ROUTER_')
    database_url:SecretStr=SecretStr('mysql+pymysql://article_routing:local_article_router@db/article_routing')
    nats_url:SecretStr=SecretStr('nats://nats:4222')
    review_token:SecretStr=SecretStr('')
    intelligence_url:str='http://document-intelligence:8009'
    events_url:str='http://events:8002'
    event_intelligence_url:str='http://event-intelligence:8008'
    rules_path:Path=Path('/workspace/config/article_router/rules.crypto.v1.json')
    contracts_dir:Path=Path('/workspace/contracts')
    workers_enabled:bool=True
    durable_prefix:str='ARTICLE_ROUTER'
    lease_seconds:int=Field(120,ge=90,le=600)
