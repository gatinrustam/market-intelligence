from pathlib import Path
from pydantic import SecretStr,Field
from pydantic_settings import BaseSettings,SettingsConfigDict
class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_prefix='EVENT_RESEARCH_')
    database_url:SecretStr=SecretStr('mysql+pymysql://event_research:local_event_research@db/event_research')
    nats_url:SecretStr=SecretStr('nats://nats:4222')
    intelligence_url:str='http://document-intelligence:8009'
    events_url:str='http://events:8002'
    article_router_url:str='http://article-router:8010'
    rules_path:Path=Path('/workspace/config/event_research/rules.v2.json')
    correlation_rules_path:Path=Path('/workspace/config/event_research/correlation.v1.json')
    contracts_dir:Path=Path('/workspace/contracts')
    workers_enabled:bool=True
    durable_prefix:str='EVENT_RESEARCH'
    lease_seconds:int=Field(120,ge=90,le=600)
