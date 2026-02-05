"""Application service implementing relay workflows."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib

from relay.domain.enums import EventType, OrderStatus, TaskStatus
from relay.domain.exceptions import ConflictError, NotFoundError, ValidationError
from relay.domain.models import (
    AckResult,
    AuditEvent,
    HeartbeatCommand,
    IngestResult,
    OrderReportCommand,
    PulledTask,
    SignalCommand,
)
from relay.domain.state_machine import (
    is_order_terminal,
    map_order_to_task_status,
    validate_order_transition,
    validate_signal_command,
)
from relay.repository.protocols import RelayRepository

LOG = logging.getLogger(__name__)


class RelayService:
    """High-level domain orchestrator.

    The implementation is storage-agnostic and works with in-memory or SQL backends.
    """

    def __init__(
        self,
        repository: RelayRepository,
        *,
        default_signal_priority: int = 100,
        default_retry_schedule: tuple[int, ...] = (5, 15, 30),
    ) -> None:
        self._repository = repository
        self._default_signal_priority = default_signal_priority
        self._default_retry_schedule = default_retry_schedule

    def ingest_signal(self, cmd: SignalCommand, *, now: datetime, trace_id: str | None = None) -> IngestResult:
        now = _ensure_utc(now)
        validate_signal_command(cmd)
        payload_hash = _payload_hash(cmd)

        existing = self._repository.get_signal_by_signal_id(cmd.signal_id)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                self._repository.add_audit_event(
                    AuditEvent(
                        trace_id=trace_id,
                        entity_type="signal",
                        entity_id=cmd.signal_id,
                        event_type=EventType.SIGNAL_CONFLICT,
                        event_detail={"reason": "payload_mismatch"},
                    ),
                    now=now,
                )
                raise ConflictError("signal_id exists but payload differs")

            task = self._repository.get_task_by_signal_db_id(existing.id)
            self._repository.add_audit_event(
                AuditEvent(
                    trace_id=trace_id,
                    entity_type="signal",
                    entity_id=cmd.signal_id,
                    event_type=EventType.SIGNAL_DUPLICATE,
                    event_detail={"signal_db_id": existing.id},
                ),
                now=now,
            )
            return IngestResult(
                http_status=200,
                signal_db_id=existing.id,
                task_db_id=task.id if task else None,
                created=False,
            )

        signal = self._repository.create_signal(cmd=cmd, payload_hash=payload_hash, sig_valid=True, now=now)
        task = self._repository.create_task(signal_db_id=signal.id, priority=self._default_signal_priority, now=now)
        self._repository.add_audit_event(
            AuditEvent(
                trace_id=trace_id,
                entity_type="signal",
                entity_id=signal.signal_id,
                event_type=EventType.SIGNAL_ACCEPTED,
                event_detail={"signal_db_id": signal.id, "task_id": task.id},
            ),
            now=now,
        )
        LOG.info("signal accepted signal_id=%s task_id=%s", signal.signal_id, task.id)
        return IngestResult(http_status=202, signal_db_id=signal.id, task_db_id=task.id, created=True)

    def pull_tasks(self, *, agent_id: str, limit: int, now: datetime) -> list[PulledTask]:
        now = _ensure_utc(now)
        if limit <= 0:
            raise ValidationError("limit must be positive")

        pulled: list[PulledTask] = []
        candidates = self._repository.list_pullable_tasks(limit=limit, now=now)
        for item in candidates:
            if item.signal.expire_at is not None and item.signal.expire_at <= now:
                failed = replace(
                    item.task,
                    status=TaskStatus.FAILED,
                    last_error_code="SIGNAL_EXPIRED",
                    last_error_msg="signal expired before pull",
                    updated_at=now,
                    version=item.task.version + 1,
                )
                self._repository.update_task(failed)
                continue
            pulled.append(
                PulledTask(
                    task_id=item.task.id,
                    signal_id=item.signal.signal_id,
                    strategy_id=item.signal.strategy_id,
                    account_id=item.signal.account_id,
                    symbol=item.signal.symbol,
                    side=item.signal.action,
                    order_type=item.signal.order_type,
                    qty=item.signal.qty,
                    amount=item.signal.amount,
                    target_pos=item.signal.target_pos,
                    limit_price=item.signal.limit_price,
                    expire_at=item.signal.expire_at,
                    priority=item.task.priority,
                )
            )
        return pulled

    def ack_task(
        self,
        *,
        task_id: int,
        agent_id: str,
        lease_seconds: int,
        now: datetime,
        trace_id: str | None = None,
    ) -> AckResult:
        now = _ensure_utc(now)
        if lease_seconds <= 0 or lease_seconds > 600:
            raise ValidationError("lease_seconds must be in (0, 600]")

        task = self._repository.get_task(task_id)
        if task is None:
            raise NotFoundError("task not found")
        if task.status != TaskStatus.READY:
            raise ConflictError(
                f"task not ackable status={task.status} holder={task.agent_id} lease_until={task.lease_until}"
            )

        lease_token = str(uuid.uuid4())
        lease_until = now + timedelta(seconds=lease_seconds)
        updated = replace(
            task,
            status=TaskStatus.ACKED,
            agent_id=agent_id,
            lease_token=lease_token,
            lease_until=lease_until,
            updated_at=now,
            version=task.version + 1,
        )
        self._repository.update_task(updated)
        self._repository.add_audit_event(
            AuditEvent(
                trace_id=trace_id,
                entity_type="task",
                entity_id=str(task_id),
                event_type=EventType.TASK_ACKED,
                event_detail={"agent_id": agent_id, "lease_until": lease_until.isoformat()},
            ),
            now=now,
        )
        return AckResult(task_id=task_id, lease_token=lease_token, lease_until=lease_until)

    def recycle_expired_leases(self, *, now: datetime) -> int:
        now = _ensure_utc(now)
        expired_tasks = self._repository.iter_expired_leased_tasks(now=now)
        recycled = 0
        for task in expired_tasks:
            next_attempt = task.attempt_count + 1
            if next_attempt >= task.max_attempts:
                updated = replace(
                    task,
                    status=TaskStatus.FAILED,
                    attempt_count=next_attempt,
                    agent_id=None,
                    lease_token=None,
                    lease_until=None,
                    next_retry_at=None,
                    last_error_code="LEASE_EXPIRED_MAX_RETRY",
                    last_error_msg="lease expired and max retry reached",
                    updated_at=now,
                    version=task.version + 1,
                )
            else:
                backoff = self._retry_backoff_seconds(next_attempt)
                updated = replace(
                    task,
                    status=TaskStatus.READY,
                    attempt_count=next_attempt,
                    agent_id=None,
                    lease_token=None,
                    lease_until=None,
                    next_retry_at=now + timedelta(seconds=backoff),
                    last_error_code="LEASE_EXPIRED",
                    last_error_msg="lease expired and task recycled",
                    updated_at=now,
                    version=task.version + 1,
                )

            self._repository.update_task(updated)
            self._repository.add_audit_event(
                AuditEvent(
                    trace_id=None,
                    entity_type="task",
                    entity_id=str(task.id),
                    event_type=EventType.TASK_RECYCLED,
                    event_detail={"attempt_count": updated.attempt_count, "status": updated.status},
                ),
                now=now,
            )
            recycled += 1

        if recycled:
            LOG.warning("recycled expired task leases count=%s", recycled)
        return recycled

    def report_order(self, cmd: OrderReportCommand, *, now: datetime, trace_id: str | None = None) -> OrderStatus:
        now = _ensure_utc(now)
        task = self._repository.get_task(cmd.task_id)
        if task is None:
            raise NotFoundError("task not found")

        existing_order = self._repository.get_order_by_client_order_id(cmd.client_order_id)
        if (
            existing_order is not None
            and existing_order.task_id == task.id
            and task.status in {TaskStatus.DONE, TaskStatus.FAILED}
            and existing_order.status == cmd.status
            and is_order_terminal(existing_order.status)
        ):
            return existing_order.status

        if task.agent_id != cmd.agent_id:
            raise ConflictError("agent_id does not own task lease")
        if task.lease_token != cmd.lease_token:
            raise ConflictError("lease_token mismatch")

        signal = self._repository.get_signal_by_db_id(task.signal_id)
        if signal is None:
            raise NotFoundError("signal not found")

        order = existing_order
        if order is None:
            qty = cmd.qty or signal.qty
            if qty is None:
                raise ValidationError("qty is required for first order report")
            if qty <= 0:
                raise ValidationError("qty must be positive")
            order = self._repository.create_order(
                client_order_id=cmd.client_order_id,
                signal_id=signal.id,
                task_id=task.id,
                account_id=signal.account_id,
                symbol=signal.symbol,
                side=signal.action,
                qty=qty,
                status=OrderStatus.NEW,
                now=now,
            )

        validate_order_transition(order.status, cmd.status)

        if cmd.qmt_order_id and order.qmt_order_id and order.qmt_order_id != cmd.qmt_order_id:
            raise ConflictError("qmt_order_id mismatch for same client_order_id")

        filled_qty = order.filled_qty
        if cmd.filled_qty is not None:
            if cmd.filled_qty < order.filled_qty:
                raise ConflictError("filled_qty cannot decrease")
            if cmd.filled_qty > order.qty:
                raise ValidationError("filled_qty cannot exceed order qty")
            filled_qty = cmd.filled_qty

        finalized_at = order.finalized_at
        if is_order_terminal(cmd.status):
            finalized_at = cmd.event_time

        updated_order = replace(
            order,
            status=cmd.status,
            qmt_order_id=cmd.qmt_order_id or order.qmt_order_id,
            filled_qty=filled_qty,
            avg_price=cmd.avg_price or order.avg_price,
            reject_code=cmd.reason_code or order.reject_code,
            reject_msg=cmd.reason_msg or order.reject_msg,
            submitted_at=order.submitted_at or cmd.event_time,
            finalized_at=finalized_at,
            updated_at=now,
        )
        self._repository.update_order(updated_order)

        mapped_task_status = map_order_to_task_status(cmd.status)
        if task.status in {TaskStatus.DONE, TaskStatus.FAILED} and task.status != mapped_task_status:
            raise ConflictError("task already terminal with different status")

        updated_task = replace(
            task,
            status=mapped_task_status,
            updated_at=now,
            version=task.version + 1,
            lease_token=None if mapped_task_status in {TaskStatus.DONE, TaskStatus.FAILED} else task.lease_token,
            lease_until=None if mapped_task_status in {TaskStatus.DONE, TaskStatus.FAILED} else task.lease_until,
        )
        self._repository.update_task(updated_task)

        self._repository.add_audit_event(
            AuditEvent(
                trace_id=trace_id,
                entity_type="order",
                entity_id=cmd.client_order_id,
                event_type=EventType.ORDER_REPORTED,
                event_detail={
                    "status": cmd.status,
                    "task_status": mapped_task_status,
                    "task_id": task.id,
                },
            ),
            now=now,
        )
        return updated_order.status

    def report_heartbeat(self, cmd: HeartbeatCommand, *, now: datetime) -> str:
        now = _ensure_utc(now)
        status = "ONLINE" if cmd.qmt_connected else "DEGRADED"
        self._repository.upsert_heartbeat(cmd=cmd, status=status, now=now)
        return status

    def _retry_backoff_seconds(self, attempt: int) -> int:
        idx = min(max(attempt - 1, 0), len(self._default_retry_schedule) - 1)
        return self._default_retry_schedule[idx]


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValidationError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def _payload_hash(cmd: SignalCommand) -> str:
    payload = cmd.payload_raw or _signal_payload_snapshot(cmd)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _signal_payload_snapshot(cmd: SignalCommand) -> dict[str, str | int | None]:
    raw = asdict(cmd)
    snapshot: dict[str, str | int | None] = {}
    for key, value in raw.items():
        if key == "payload_raw":
            continue
        if isinstance(value, datetime):
            snapshot[key] = value.isoformat()
        elif isinstance(value, Decimal):
            snapshot[key] = str(value)
        elif value is None:
            snapshot[key] = None
        else:
            snapshot[key] = str(value)
    return snapshot
