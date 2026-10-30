from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SourcePolicy(StrictModel):
    mode: Literal['always', 'when_needed', 'never'] = 'when_needed'
    minimum_body_characters: int = Field(default=240, ge=1, le=100000)
    allowed_hosts: list[str] = Field(min_length=1, max_length=32)

    @field_validator('allowed_hosts')
    @classmethod
    def validate_hosts(cls, values):
        import re
        hosts = []
        for value in values:
            host = value.lower()
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '.' not in host or '..' in host or len(host) > 253:
                raise ValueError('expected exact DNS hostname; no wildcards, URLs or internal names')
            hosts.append(host)
        if len(set(hosts)) != len(hosts):
            raise ValueError('duplicate allowed host')
        return hosts


class Policies(StrictModel):
    sources: dict[str, SourcePolicy] = Field(min_length=1)


def load_policies(path: Path) -> Policies:
    try:
        return Policies.model_validate(yaml.safe_load(path.read_text()))
    except ValidationError as exc:
        fields = '; '.join('.'.join(map(str, e['loc'])) + ': ' + e['type'] for e in exc.errors())
        raise ValueError(f'Invalid enrichment policy {path.name}: {fields}') from None
    except Exception as exc:
        raise ValueError(f'Cannot load enrichment policy {path.name}: {type(exc).__name__}') from None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='ENRICHMENT_', extra='ignore')
    database_url: SecretStr = SecretStr('mysql+pymysql://enrichment:local_enrichment@db:3306/enrichment?charset=utf8mb4')
    nats_url: SecretStr = SecretStr('nats://nats:4222')
    policy_path: Path = Path('/workspace/config/enrichment/policies.yaml')
    input_schema_path: Path = Path('/workspace/contracts/news/raw/v1.schema.json')
    output_schema_path: Path = Path('/workspace/contracts/document/enriched/v1.schema.json')
    user_agent: str = 'MarketIntelligenceEnrichment/0.1'
    connect_timeout_seconds: float = Field(default=5, gt=0, le=30)
    read_timeout_seconds: float = Field(default=15, gt=0, le=60)
    request_timeout_seconds: float = Field(default=45, gt=0, le=120)
    max_redirects: int = Field(default=3, ge=0, le=10)
    html_max_bytes: int = Field(default=5_000_000, ge=1024, le=20_000_000)
    pdf_max_bytes: int = Field(default=20_000_000, ge=1024, le=30_000_000)
    max_requests_per_second_per_host: float = Field(default=1, gt=0, le=10)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_seconds: float = Field(default=5, ge=1, le=60)
    lease_seconds: int = Field(default=180, ge=60, le=600)
    extraction_timeout_seconds: int = Field(default=30, ge=1, le=60)
    extraction_memory_mb: int = Field(default=768, ge=256, le=2048)
    max_pdf_pages: int = Field(default=100, ge=1, le=500)
    minimum_extracted_characters: int = Field(default=100, ge=1, le=10000)
    max_output_characters: int = Field(default=200000, ge=1000, le=200000)
    workers_enabled: bool = True
    durable_name: str = Field(default='ENRICHMENT_V1', pattern=r'^[A-Za-z0-9_-]{1,64}$')

    @model_validator(mode='after')
    def lease_exceeds_deadlines(self):
        if self.lease_seconds <= self.request_timeout_seconds + self.extraction_timeout_seconds + 30:
            raise ValueError('lease must exceed request + extraction deadlines by more than 30 seconds')
        return self
