from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'QMT Gateway'
    api_prefix: str = '/api/v1'
    database_url: str = Field(
        default='postgresql+psycopg2://qmt:qmt@postgres:5432/qmt_gateway',
        alias='DATABASE_URL',
    )
    jwt_secret: str = Field(default='change-me-in-prod', alias='JWT_SECRET')
    jwt_algorithm: str = 'HS256'
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 60 * 24 * 7

    admin_username: str = Field(default='admin', alias='ADMIN_USERNAME')
    admin_password: str = Field(default='admin123456', alias='ADMIN_PASSWORD')

    default_webhook_secret: str = Field(default='replace-me', alias='DEFAULT_WEBHOOK_SECRET')
    webhook_ts_tolerance_ms: int = 5 * 60 * 1000
    bypass_trading_time_check: bool = Field(default=False, alias='BYPASS_TRADING_TIME_CHECK')

    client_shared_token: str = Field(default='client-dev-token', alias='CLIENT_SHARED_TOKEN')
    claim_ttl_seconds: int = 30
    offline_threshold_seconds: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
