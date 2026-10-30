from pathlib import Path
from pydantic import SecretStr,Field
from pydantic_settings import BaseSettings,SettingsConfigDict
class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_prefix='DOCUMENT_INTELLIGENCE_')
    database_url:SecretStr=SecretStr('mysql+pymysql://document_intelligence:local_document_intelligence@db/document_intelligence')
    nats_url:SecretStr=SecretStr('nats://nats:4222')
    config_dir:Path=Path('/workspace/config/document_intelligence')
    rules_path:Path=Path('/workspace/config/document_intelligence/rules.crypto.v1.1.json')
    contracts_dir:Path=Path('/workspace/contracts')
    workers_enabled:bool=True
    lease_seconds:int=Field(300,ge=120,le=600)
    durable_prefix:str='DOCUMENT_INTELLIGENCE'
