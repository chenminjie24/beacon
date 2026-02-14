"""Agent-side data models and protocol definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from relay.domain.enums import Action, OrderStatus, OrderType
from relay.domain.models import AckResult, OrderReportCommand, PulledTask


@dataclass(frozen=True)
class QmtOrderResult:
    client_order_id: str
    qmt_order_id: str
    submitted_at: datetime
    qty: Decimal


class QmtClient(Protocol):
    def place_order(self, task: PulledTask, *, client_order_id: str, now: datetime) -> QmtOrderResult:
        ...


@dataclass(frozen=True)
class RiskDecision:
    ok: bool
    reason_code: str | None = None
    reason_msg: str | None = None


class RiskChecker(Protocol):
    def check(self, task: PulledTask, now: datetime) -> RiskDecision:
        ...


class RelayClient(Protocol):
    def pull_tasks(self, *, agent_id: str, limit: int) -> list[PulledTask]:
        ...

    def ack_task(self, *, task_id: int, agent_id: str, lease_seconds: int) -> AckResult:
        ...

    def report_order(self, report: OrderReportCommand) -> None:
        ...

    def heartbeat(self, *, agent_id: str, host: str, version: str, qmt_connected: bool, latency_ms: int | None) -> None:
        ...
