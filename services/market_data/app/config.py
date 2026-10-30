from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='MARKET_DATA_')
    database_url: SecretStr = SecretStr('mysql+pymysql://market_data:local_market_data@db/market_data')
    nats_url: str = 'nats://nats:4222'
    snapshot_interval_seconds: float = Field(1, ge=0.1, le=60)
    max_snapshot_distance_seconds: float = Field(3, ge=0, le=60)
    max_state_age_seconds: float = Field(10, ge=1, le=120)
    rest_interval_seconds: float = Field(1, ge=0.5)
    contract_path: Path = Path('/workspace/contracts/market/snapshot/v1.schema.json')
