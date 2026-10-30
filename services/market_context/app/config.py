from pathlib import Path
from pydantic import Field,SecretStr
from pydantic_settings import BaseSettings,SettingsConfigDict
class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_prefix='MARKET_CONTEXT_')
    database_url: SecretStr=SecretStr('mysql+pymysql://market_context:local_market_context@db/market_context')
    nats_url: SecretStr=SecretStr('nats://nats:4222')
    market_data_url: str='http://market-data:8003'
    events_url: str='http://events:8002'
    enriched_schema_path: Path=Path('/workspace/contracts/document/enriched/v1.schema.json')
    late_enrichment_seconds: int=Field(300,ge=0)
    realtime_max_age_seconds: float=Field(3,gt=0,allow_inf_nan=False)
    candle_max_age_seconds: float=Field(60,gt=0,allow_inf_nan=False)
    durable_name: str='MARKET_CONTEXT_V1'
    input_schema_path: Path=Path('/workspace/contracts/event/canonical/v1.schema.json')
    output_schema_path: Path=Path('/workspace/contracts/market/context/v1.schema.json')
    unavailable_retry_seconds: int=Field(300,ge=5,le=86400)
    data_grace_seconds: int=Field(10,ge=0,le=300)
    lease_seconds: int=Field(90,ge=60,le=600)
    workers_enabled: bool=True
