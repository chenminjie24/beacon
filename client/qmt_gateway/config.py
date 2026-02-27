from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClientSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    server_base_url: str = Field(default='http://localhost:8000/api/v1', alias='SERVER_BASE_URL')
    client_id: str = Field(default='client_win_001', alias='CLIENT_ID')
    account_id: str = Field(default='acc_stock_main', alias='ACCOUNT_ID')
    client_token: str = Field(default='client-dev-token', alias='CLIENT_SHARED_TOKEN')
    poll_interval_seconds: int = Field(default=2, alias='POLL_INTERVAL_SECONDS')
    heartbeat_interval_seconds: int = Field(default=10, alias='HEARTBEAT_INTERVAL_SECONDS')
    client_version: str = Field(default='0.1.0', alias='CLIENT_VERSION')
    secret_file: str = Field(default='secrets.enc.json', alias='SECRET_FILE')
    execution_mode: str = Field(default='AUTO', alias='EXECUTION_MODE')
    qmt_account_type: str = Field(default='STOCK', alias='QMT_ACCOUNT_TYPE')
    qmt_strategy_name: str = Field(default='qmt_gateway', alias='QMT_STRATEGY_NAME')
    qmt_order_remark_prefix: str = Field(default='qmtgw', alias='QMT_ORDER_REMARK_PREFIX')
    qmt_session_id: int = Field(default=10001, alias='QMT_SESSION_ID')

    @property
    def secret_path(self) -> Path:
        return Path(self.secret_file).resolve()
