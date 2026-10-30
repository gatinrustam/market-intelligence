from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='EVENTS_', extra='ignore')
    database_url: SecretStr = SecretStr('mysql+pymysql://events:local_events@db:3306/events?charset=utf8mb4')
    nats_url: SecretStr = SecretStr('nats://nats:4222')
    config_dir: Path = Path('/workspace/config/events')
    input_schema_path: Path = Path('/workspace/contracts/document/enriched/v1.schema.json')
    output_schema_path: Path = Path('/workspace/contracts/event/canonical/v1.schema.json')
    workers_enabled: bool = True
    durable_name: str = Field(default='EVENTS_V1', pattern=r'^[A-Za-z0-9_-]{1,64}$')
    lease_seconds: int = Field(default=120, ge=60, le=600)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_seconds: float = Field(default=2, ge=1, le=60)
