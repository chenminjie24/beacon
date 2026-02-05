"""Core data models for relay service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from relay.domain.enums import Action, OrderStatus, OrderType, TaskStatus


@dataclass(frozen=True)
class SignalCommand:
    signal_id: str
    strategy_id: str
    account_id: str
    ts: datetime
    symbol: str
    action: Action
    order_type: OrderType
    qty: Decimal | None = None
    amount: Decimal | None = None
    target_pos: Decimal | None = None
    limit_price: Decimal | None = None
    max_slippage_bps: int = 20
    expire_at: datetime | None = None
    remark: str | None = None
    payload_raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalRecord:
    id: int
    signal_id: str
    strategy_id: str
    account_id: str
    ts: datetime
    symbol: str
    action: Action
    order_type: OrderType
    qty: Decimal | None
    amount: Decimal | None
    target_pos: Decimal | None
    limit_price: Decimal | None
    max_slippage_bps: int
    expire_at: datetime | None
    remark: str | None
    payload_raw: dict[str, Any]
    payload_hash: str
    sig_valid: bool
    received_at: datetime


@dataclass
class TaskRecord:
    id: int
    signal_id: int
    status: TaskStatus
    priority: int
    agent_id: str | None = None
    lease_token: str | None = None
    lease_until: datetime | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    next_retry_at: datetime | None = None
    last_error_code: str | None = None
    last_error_msg: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 0


@dataclass(frozen=True)
class PulledTask:
    task_id: int
    signal_id: str
    strategy_id: str
    account_id: str
    symbol: str
    side: Action
    order_type: OrderType
    qty: Decimal | None
    amount: Decimal | None
    target_pos: Decimal | None
    limit_price: Decimal | None
    expire_at: datetime | None
    priority: int


@dataclass(frozen=True)
class AckResult:
    task_id: int
    lease_token: str
    lease_until: datetime


@dataclass(frozen=True)
class IngestResult:
    http_status: int
    signal_db_id: int
    task_db_id: int | None
    created: bool


@dataclass(frozen=True)
class OrderReportCommand:
    agent_id: str
    task_id: int
    lease_token: str
    client_order_id: str
    status: OrderStatus
    event_time: datetime
    qmt_order_id: str | None = None
    qty: Decimal | None = None
    filled_qty: Decimal | None = None
    avg_price: Decimal | None = None
    reason_code: str | None = None
    reason_msg: str | None = None


@dataclass
class OrderRecord:
    id: int
    client_order_id: str
    signal_id: int
    task_id: int
    account_id: str
    symbol: str
    side: Action
    price: Decimal | None
    qty: Decimal
    qmt_order_id: str | None
    status: OrderStatus
    filled_qty: Decimal
    avg_price: Decimal | None
    reject_code: str | None
    reject_msg: str | None
    submitted_at: datetime | None
    finalized_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class HeartbeatCommand:
    agent_id: str
    host: str
    version: str
    qmt_connected: bool
    now: datetime
    latency_ms: int | None = None


@dataclass
class AgentHeartbeat:
    agent_id: str
    host: str
    version: str
    qmt_connected: bool
    latency_ms: int | None
    status: str
    last_seen_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AuditEvent:
    trace_id: str | None
    entity_type: str
    entity_id: str
    event_type: str
    event_detail: dict[str, Any]
    operator: str = "system"
