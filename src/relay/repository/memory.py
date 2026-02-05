"""In-memory repository for deterministic offline tests."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from relay.domain.enums import Action, OrderStatus, TaskStatus
from relay.domain.models import (
    AgentHeartbeat,
    AuditEvent,
    HeartbeatCommand,
    OrderRecord,
    SignalCommand,
    SignalRecord,
    TaskRecord,
)
from relay.repository.protocols import TaskWithSignal


class InMemoryRelayRepository:
    """Thread-safe storage backend with predictable ordering semantics."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._signal_seq = 0
        self._task_seq = 0
        self._order_seq = 0

        self._signals_by_id: dict[int, SignalRecord] = {}
        self._signals_by_signal_id: dict[str, int] = {}

        self._tasks_by_id: dict[int, TaskRecord] = {}

        self._orders_by_id: dict[int, OrderRecord] = {}
        self._orders_by_client_id: dict[str, int] = {}

        self._heartbeats: dict[str, AgentHeartbeat] = {}
        self._audit_events: list[tuple[datetime, AuditEvent]] = []

    def get_signal_by_signal_id(self, signal_id: str) -> SignalRecord | None:
        with self._lock:
            internal_id = self._signals_by_signal_id.get(signal_id)
            if internal_id is None:
                return None
            return self._signals_by_id[internal_id]

    def get_signal_by_db_id(self, signal_db_id: int) -> SignalRecord | None:
        with self._lock:
            return self._signals_by_id.get(signal_db_id)

    def create_signal(self, cmd: SignalCommand, payload_hash: str, sig_valid: bool, now: datetime) -> SignalRecord:
        with self._lock:
            self._signal_seq += 1
            record = SignalRecord(
                id=self._signal_seq,
                signal_id=cmd.signal_id,
                strategy_id=cmd.strategy_id,
                account_id=cmd.account_id,
                ts=cmd.ts,
                symbol=cmd.symbol,
                action=cmd.action,
                order_type=cmd.order_type,
                qty=cmd.qty,
                amount=cmd.amount,
                target_pos=cmd.target_pos,
                limit_price=cmd.limit_price,
                max_slippage_bps=cmd.max_slippage_bps,
                expire_at=cmd.expire_at,
                remark=cmd.remark,
                payload_raw=dict(cmd.payload_raw),
                payload_hash=payload_hash,
                sig_valid=sig_valid,
                received_at=now,
            )
            self._signals_by_id[record.id] = record
            self._signals_by_signal_id[record.signal_id] = record.id
            return record

    def create_task(self, signal_db_id: int, priority: int, now: datetime) -> TaskRecord:
        with self._lock:
            self._task_seq += 1
            task = TaskRecord(
                id=self._task_seq,
                signal_id=signal_db_id,
                status=TaskStatus.READY,
                priority=priority,
                next_retry_at=now,
                created_at=now,
                updated_at=now,
            )
            self._tasks_by_id[task.id] = task
            return task

    def list_pullable_tasks(self, limit: int, now: datetime) -> list[TaskWithSignal]:
        with self._lock:
            candidates: list[TaskWithSignal] = []
            for task in self._tasks_by_id.values():
                if task.status != TaskStatus.READY:
                    continue
                if task.next_retry_at and task.next_retry_at > now:
                    continue
                signal = self._signals_by_id[task.signal_id]
                candidates.append(TaskWithSignal(task=task, signal=signal))
            candidates.sort(key=lambda item: (item.task.priority, item.task.id))
            return candidates[:limit]

    def get_task(self, task_id: int) -> TaskRecord | None:
        with self._lock:
            return self._tasks_by_id.get(task_id)

    def get_task_by_signal_db_id(self, signal_db_id: int) -> TaskRecord | None:
        with self._lock:
            for task in self._tasks_by_id.values():
                if task.signal_id == signal_db_id:
                    return task
            return None

    def update_task(self, task: TaskRecord) -> None:
        with self._lock:
            self._tasks_by_id[task.id] = task

    def iter_expired_leased_tasks(self, now: datetime) -> list[TaskRecord]:
        with self._lock:
            expired: list[TaskRecord] = []
            for task in self._tasks_by_id.values():
                if task.status not in {TaskStatus.ACKED, TaskStatus.EXECUTING}:
                    continue
                if task.lease_until and task.lease_until <= now:
                    expired.append(task)
            expired.sort(key=lambda task: task.id)
            return expired

    def get_order_by_client_order_id(self, client_order_id: str) -> OrderRecord | None:
        with self._lock:
            internal_id = self._orders_by_client_id.get(client_order_id)
            if internal_id is None:
                return None
            return self._orders_by_id[internal_id]

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
        with self._lock:
            self._order_seq += 1
            order = OrderRecord(
                id=self._order_seq,
                client_order_id=client_order_id,
                signal_id=signal_id,
                task_id=task_id,
                account_id=account_id,
                symbol=symbol,
                side=side,
                price=None,
                qty=qty,
                qmt_order_id=None,
                status=status,
                filled_qty=Decimal("0"),
                avg_price=None,
                reject_code=None,
                reject_msg=None,
                submitted_at=None,
                finalized_at=None,
                created_at=now,
                updated_at=now,
            )
            self._orders_by_id[order.id] = order
            self._orders_by_client_id[order.client_order_id] = order.id
            return order

    def update_order(self, order: OrderRecord) -> None:
        with self._lock:
            self._orders_by_id[order.id] = order

    def upsert_heartbeat(self, cmd: HeartbeatCommand, status: str, now: datetime) -> AgentHeartbeat:
        with self._lock:
            existing = self._heartbeats.get(cmd.agent_id)
            if existing is None:
                record = AgentHeartbeat(
                    agent_id=cmd.agent_id,
                    host=cmd.host,
                    version=cmd.version,
                    qmt_connected=cmd.qmt_connected,
                    latency_ms=cmd.latency_ms,
                    status=status,
                    last_seen_at=cmd.now,
                    updated_at=now,
                )
            else:
                record = replace(
                    existing,
                    host=cmd.host,
                    version=cmd.version,
                    qmt_connected=cmd.qmt_connected,
                    latency_ms=cmd.latency_ms,
                    status=status,
                    last_seen_at=cmd.now,
                    updated_at=now,
                )
            self._heartbeats[cmd.agent_id] = record
            return record

    def add_audit_event(self, event: AuditEvent, now: datetime) -> None:
        with self._lock:
            self._audit_events.append((now, event))

    # Helpers for tests
    def snapshot_tasks(self) -> dict[int, TaskRecord]:
        with self._lock:
            return dict(self._tasks_by_id)

    def snapshot_orders(self) -> dict[int, OrderRecord]:
        with self._lock:
            return dict(self._orders_by_id)
