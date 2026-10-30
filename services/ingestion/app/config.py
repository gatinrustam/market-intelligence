from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CorporateFilingSource(StrictModel):
    cik: str = Field(pattern=r'^\d{1,10}$')
    issuer: str = Field(min_length=1, max_length=200)
    forms: list[str] = Field(default_factory=lambda: ['8-K'])


class Connector(StrictModel):
    type: Literal['rss', 'statuspage', 'announcement_page', 'sec_filing']
    format: Literal['incidents', 'scheduled_maintenances', 'binance', 'coinbase', 'circle'] | None = None
    corporate: CorporateFilingSource | None = None
    url: HttpUrl

    @field_validator('url')
    @classmethod
    def no_credentials(cls, value):
        if value.username or value.password:
            raise ValueError('source URL must not contain credentials')
        return value


    @model_validator(mode='after')
    def connector_options(self):
        if self.type == 'statuspage' and self.format not in ('incidents', 'scheduled_maintenances'):
            raise ValueError('statuspage format required')
        if self.type == 'announcement_page' and self.format not in ('binance', 'coinbase', 'circle'):
            raise ValueError('announcement format required')
        if self.type == 'sec_filing' and self.corporate is None:
            raise ValueError('corporate filing configuration required')
        return self


class Poll(StrictModel):
    interval_seconds: int = Field(default=60, ge=10, le=86400)


class Classification(StrictModel):
    categories: list[str] = Field(default_factory=list, max_length=32)

    @field_validator('categories')
    @classmethod
    def valid_categories(cls, value):
        if any(not x.strip() or len(x) > 64 for x in value) or len(set(value)) != len(value):
            raise ValueError('categories must be unique nonempty strings of at most 64 characters')
        return value


class SourceConfig(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    max_items_per_poll: int | None = Field(default=None, ge=1, le=10000)
    domain: str | None = None
    source_class: str | None = None
    source_quality: str | None = None
    source_role: str | None = None
    poll_priority: Literal['fast', 'normal'] = 'normal'
    expected_content_types: list[str] = Field(default_factory=list)
    connector: Connector
    poll: Poll = Field(default_factory=Poll)
    classification: Classification = Field(default_factory=Classification)
    priority: Literal['normal', 'high', 'critical'] = 'normal'
    language: str = Field(default='und', pattern=r'^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$')


def load_sources(directory: Path) -> list[SourceConfig]:
    paths = sorted([*directory.glob('*.yaml'), *directory.glob('*.yml')])
    if not paths:
        raise ValueError(f'No source YAML files in {directory}')
    sources = []
    for path in paths:
        try:
            sources.append(SourceConfig.model_validate(yaml.safe_load(path.read_text())))
        except ValidationError as exc:
            details = '; '.join('.'.join(map(str, e['loc'])) + ': ' + e['type'] for e in exc.errors())
            raise ValueError(f'Invalid source configuration: {path.name}: {details}') from None
        except Exception as exc:
            # Do not echo configuration values, which may contain secrets.
            raise ValueError(f'Invalid source configuration: {path.name} ({type(exc).__name__})') from None
    if len({s.id for s in sources}) != len(sources):
        raise ValueError('Duplicate source IDs in source configuration')
    return sources


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='INGESTION_', extra='ignore')
    database_url: SecretStr = SecretStr('mysql+pymysql://ingestion:local_ingestion@db:3306/ingestion?charset=utf8mb4')
    nats_url: SecretStr = SecretStr('nats://nats:4222')
    sources_dir: Path = Path('/workspace/config/sources')
    schema_path: Path = Path('/workspace/contracts/news/raw/v1.schema.json')
    user_agent: str = 'MarketIntelligencePrototype/0.1 (local research)'
    http_timeout_seconds: float = Field(default=20, gt=0, le=120)
    max_feed_bytes: int = Field(default=5_000_000, ge=1024, le=20_000_000)
    publisher_interval_seconds: float = Field(default=1, ge=0.1, le=60)
    workers_enabled: bool = True
