from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .models import (
    AlertStatus,
    OrderStatus,
    OrderStyle,
    Side,
    SignalStatus,
    SignalType,
    TaskAction,
)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = 'bearer'


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class SignalPayloadV1(BaseModel):
    source_platform: str
    strategy_id: str
    account_id: str
    signal_type: SignalType
    idempotency_key: str
    symbol: str
    side: Side
    order_style: OrderStyle = OrderStyle.MARKET
    quantity: int | None = None
    amount: float | None = None
    target_position_ratio: float | None = None
    timestamp_ms: int
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator('quantity')
    @classmethod
    def validate_qty(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError('quantity must be positive')
        return v


class SignalWebhookResponse(BaseModel):
    accepted: bool
    signal_id: str
    duplicate: bool


class ClaimTasksRequest(BaseModel):
    client_id: str
    account_id: str
    max_tasks: int = 20
    capabilities: list[str] = Field(default_factory=list)
    version: str = '0.1.0'


class TaskPayload(BaseModel):
    task_id: str
    signal_id: str
    action: TaskAction
    payload: dict[str, Any]
    expire_at: datetime | None = None


class ClaimTasksResponse(BaseModel):
    tasks: list[TaskPayload]


class TaskReportRequest(BaseModel):
    client_id: str
    status: OrderStatus
    broker_order_id: str | None = None
    message: str | None = None
    filled_quantity: int = 0
    avg_price: float = 0


class TradeReportRequest(BaseModel):
    client_id: str
    order_id: str
    broker_trade_id: str
    symbol: str
    side: Side
    quantity: int
    price: float
    traded_at: datetime | None = None


class CancelOrderResponse(BaseModel):
    accepted: bool
    task_id: str


class RiskRuleUpdateRequest(BaseModel):
    max_single_amount: float
    max_single_quantity: int
    daily_max_amount: float
    min_order_amount: float
    min_lot_size: int
    whitelist: list[str]
    blacklist: list[str]
    is_active: bool = True


class SignalOut(BaseModel):
    id: str
    source_platform: str
    strategy_id: str
    account_id: str
    signal_type: SignalType
    symbol: str
    side: Side
    status: SignalStatus
    rejection_reason: str | None
    created_at: datetime


class OrderOut(BaseModel):
    id: str
    signal_id: str
    strategy_id: str
    account_id: str
    symbol: str
    side: Side
    status: OrderStatus
    broker_order_id: str | None
    filled_quantity: int
    avg_price: float
    created_at: datetime


class PositionOut(BaseModel):
    account_id: str
    symbol: str
    quantity: int
    available_quantity: int
    avg_cost: float
    market_value: float
    snapshot_at: datetime


class ClientOut(BaseModel):
    id: str
    account_id: str
    version: str
    status: str
    capabilities: list[str]
    last_heartbeat_at: datetime
    last_error: str | None


class AlertOut(BaseModel):
    id: str
    level: str
    category: str
    message: str
    status: AlertStatus
    created_at: datetime


class AuditLogOut(BaseModel):
    id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    detail: dict[str, Any]
    created_at: datetime


class HeartbeatRequest(BaseModel):
    client_id: str
    account_id: str
    capabilities: list[str] = Field(default_factory=list)
    version: str = '0.1.0'
    last_error: str | None = None


class DashboardMetrics(BaseModel):
    today_signals: int
    success_orders: int
    failed_orders: int
    online_clients: int
    open_alerts: int
