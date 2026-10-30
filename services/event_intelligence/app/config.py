from pathlib import Path
from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='EVENT_INTELLIGENCE_')
    database_url: SecretStr = SecretStr('mysql+pymysql://event_intelligence:local_event_intelligence@db/event_intelligence')
    nats_url: SecretStr = SecretStr('nats://nats:4222')
    events_url: str = 'http://events:8002'
    rules_path: Path = Path('/workspace/config/event_intelligence/rules.v1.1.json')
    contracts_dir: Path = Path('/workspace/contracts')
    workers_enabled: bool = True
    durable_prefix: str = 'EVENT_INTELLIGENCE'
    lease_seconds: int = Field(120, ge=90, le=600)
