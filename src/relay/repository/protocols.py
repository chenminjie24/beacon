"""Repository interfaces decoupling domain logic from storage details."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from relay.domain.enums import Action, OrderStatus
from relay.domain.models import (
    AgentHeartbeat,
    AuditEvent,
    HeartbeatCommand,
    OrderRecord,
    SignalCommand,
    SignalRecord,
    TaskRecord,
)


@dataclass(frozen=True)
class TaskWithSignal:
    task: TaskRecord
    signal: SignalRecord


class RelayRepository(Protocol):
    def get_signal_by_db_id(self, signal_db_id: int) -> SignalRecord | None:
        ...

    def get_signal_by_signal_id(self, signal_id: str) -> SignalRecord | None:
        ...

    def create_signal(self, cmd: SignalCommand, payload_hash: str, sig_valid: bool, now: datetime) -> SignalRecord:
        ...

    def create_task(self, signal_db_id: int, priority: int, now: datetime) -> TaskRecord:
        ...

    def list_pullable_tasks(self, limit: int, now: datetime) -> list[TaskWithSignal]:
        ...

    def get_task(self, task_id: int) -> TaskRecord | None:
        ...

    def get_task_by_signal_db_id(self, signal_db_id: int) -> TaskRecord | None:
        ...

    def update_task(self, task: TaskRecord) -> None:
        ...

    def iter_expired_leased_tasks(self, now: datetime) -> list[TaskRecord]:
        ...

    def get_order_by_client_order_id(self, client_order_id: str) -> OrderRecord | None:
        ...

    def create_order(
        self,
        *,
        client_order_id: str,
        signal_id: int,
        task_id: int,
        account_id: str,
        symbol: str,
        side: Action,
        qty: Decimal,
        status: OrderStatus,
        now: datetime,
    ) -> OrderRecord:
        ...

    def update_order(self, order: OrderRecord) -> None:
        ...

    def upsert_heartbeat(self, cmd: HeartbeatCommand, status: str, now: datetime) -> AgentHeartbeat:
        ...

    def add_audit_event(self, event: AuditEvent, now: datetime) -> None:
        ...
