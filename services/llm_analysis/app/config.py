from pathlib import Path
from typing import Literal
from pydantic import Field,SecretStr
from pydantic_settings import BaseSettings,SettingsConfigDict
class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_prefix='LLM_ANALYSIS_')
    database_url:SecretStr=SecretStr('mysql+pymysql://llm_analysis:local_llm_analysis@db/llm_analysis')
    nats_url:SecretStr=SecretStr('nats://nats:4222')
    context_url:str='http://market-context:8004'
    intelligence_url:str='http://event-intelligence:8008'
    api_key:SecretStr=Field(default=SecretStr(''),validation_alias='OPENAI_API_KEY')
    model:str='gpt-6-astra'
    reasoning_effort:Literal['low','medium','high','xhigh','max','ultra']='medium'
    prompt_version:str='btc_event_analysis_v1'
    max_output_tokens:int=Field(6000,ge=1000,le=20000)
    request_timeout_seconds:int=Field(120,ge=1,le=300)
    max_attempts:int=Field(4,ge=1,le=8)
    max_invalid_attempts:int=Field(2,ge=1,le=3)
    auto_live_enabled:bool=False
    workers_enabled:bool=True
    durable_name:str='LLM_ANALYSIS_V1'
    contracts_dir:Path=Path('/workspace/contracts')
    def configuration(self):
        return {'provider':'openai','model':self.model,'reasoning_effort':self.reasoning_effort,
                'max_output_tokens':self.max_output_tokens,'prompt_version':self.prompt_version}
