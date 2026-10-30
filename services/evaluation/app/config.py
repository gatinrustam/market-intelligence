from decimal import Decimal
from pathlib import Path
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='EVALUATION_')
    database_url: SecretStr = SecretStr('mysql+pymysql://evaluation:local_evaluation@db/evaluation')
    nats_url: SecretStr = SecretStr('nats://nats:4222')
    context_url: str = 'http://market-context:8004'
    analysis_url: str = 'http://llm-analysis:8005'
    contracts_dir: Path = Path('/workspace/contracts')
    neutral_threshold_pct: Decimal = Field(Decimal('0.05'), gt=0, allow_inf_nan=False)
    negligible_threshold_pct: Decimal = Field(Decimal('0.10'), gt=0, allow_inf_nan=False)
    small_threshold_pct: Decimal = Field(Decimal('0.50'), gt=0, allow_inf_nan=False)
    moderate_threshold_pct: Decimal = Field(Decimal('1.50'), gt=0, allow_inf_nan=False)
    poll_seconds: int = Field(5, ge=1, le=300)
    unavailable_retry_seconds: int = Field(300, ge=5, le=86400)
    lease_seconds: int = Field(90, ge=60, le=600)
    workers_enabled: bool = True
    fixtures_enabled: bool = False
    durable_name: str = 'EVALUATION_V1'

    @model_validator(mode='after')
    def ordered_thresholds(self):
        if not self.negligible_threshold_pct < self.small_threshold_pct < self.moderate_threshold_pct:
            raise ValueError('Impact thresholds must be strictly increasing')
        return self

    def policy(self):
        return {'version':'movement_buckets_v1', 'neutral_threshold_pct':str(self.neutral_threshold_pct),
                'impact_thresholds_pct':{'negligible':str(self.negligible_threshold_pct),
                    'small':str(self.small_threshold_pct), 'moderate':str(self.moderate_threshold_pct)},
                'return_decimal_places':12, 'rounding':'ROUND_HALF_EVEN'}
