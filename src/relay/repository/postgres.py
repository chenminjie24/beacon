"""PostgreSQL repository implementation.

This adapter is intentionally lightweight and DB-API compatible. It does not
require importing PostgreSQL drivers unless instantiated with a real connection
factory.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import json
from typing import Any, Callable, Iterator

from relay.domain.enums import Action, OrderStatus, OrderType, TaskStatus
from relay.domain.exceptions import ConflictError
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


class PostgresRelayRepository:
    """Persistence adapter backed by PostgreSQL."""

    _PULL_TASKS_SQL = """
        SELECT
            t.id AS task_id,
            t.signal_id AS task_signal_id,
            t.status AS task_status,
            t.priority AS task_priority,
            t.agent_id AS task_agent_id,
            t.lease_token AS task_lease_token,
            t.lease_until AS task_lease_until,
            t.attempt_count AS task_attempt_count,
            t.max_attempts AS task_max_attempts,
            t.next_retry_at AS task_next_retry_at,
            t.last_error_code AS task_last_error_code,
            t.last_error_msg AS task_last_error_msg,
            t.created_at AS task_created_at,
            t.updated_at AS task_updated_at,
            t.version AS task_version,
            s.id AS signal_id,
            s.signal_id AS signal_signal_id,
            s.strategy_id,
            s.account_id,
            s.ts,
            s.symbol,
            s.action,
            s.order_type,
            s.qty,
            s.amount,
            s.target_pos,
            s.limit_price,
            s.max_slippage_bps,
            s.expire_at,
            s.remark,
            s.payload_raw,
            s.payload_hash,
            s.sig_valid,
            s.received_at
        FROM execution_tasks t
        JOIN signals s ON s.id = t.signal_id
        WHERE t.status = 'READY' AND t.next_retry_at <= %s
        ORDER BY t.priority ASC, t.id ASC
        LIMIT %s
        FOR UPDATE SKIP LOCKED
    """

    _EXPIRED_LEASE_SQL = """
        SELECT
            id,
            signal_id,
            status,
            priority,
            agent_id,
            lease_token,
            lease_until,
            attempt_count,
            max_attempts,
            next_retry_at,
            last_error_code,
            last_error_msg,
            created_at,
            updated_at,
            version
        FROM execution_tasks
        WHERE status IN ('ACKED', 'EXECUTING')
          AND lease_until IS NOT NULL
          AND lease_until <= %s
        ORDER BY lease_until ASC, id ASC
        FOR UPDATE SKIP LOCKED
    """

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def get_signal_by_db_id(self, signal_db_id: int) -> SignalRecord | None:
        sql = """
            SELECT id, signal_id, strategy_id, account_id, ts, symbol, action, order_type,
                   qty, amount, target_pos, limit_price, max_slippage_bps, expire_at,
                   remark, payload_raw, payload_hash, sig_valid, received_at
            FROM signals
            WHERE id = %s
        """
        with self._cursor() as cur:
            cur.execute(sql, (signal_db_id,))
            row = _fetchone_dict(cur)
            return _to_signal(row) if row else None

    def get_signal_by_signal_id(self, signal_id: str) -> SignalRecord | None:
        sql = """
            SELECT id, signal_id, strategy_id, account_id, ts, symbol, action, order_type,
                   qty, amount, target_pos, limit_price, max_slippage_bps, expire_at,
                   remark, payload_raw, payload_hash, sig_valid, received_at
            FROM signals
            WHERE signal_id = %s
        """
        with self._cursor() as cur:
            cur.execute(sql, (signal_id,))
            row = _fetchone_dict(cur)
            return _to_signal(row) if row else None

    def list_signals(
        self,
        *,
        limit: int,
        offset: int,
        query: str | None,
        action: Action | None,
        order_type: OrderType | None,
        since: datetime | None,
        until: datetime | None,
    ) -> list[SignalRecord]:
        sql_parts = [
            """
            SELECT id, signal_id, strategy_id, account_id, ts, symbol, action, order_type,
                   qty, amount, target_pos, limit_price, max_slippage_bps, expire_at,
                   remark, payload_raw, payload_hash, sig_valid, received_at
            FROM signals
            WHERE 1=1
            """
        ]
        params: list[Any] = []

        if query:
            like = f"%{query}%"
            sql_parts.append(
                "AND (signal_id ILIKE %s OR strategy_id ILIKE %s OR account_id ILIKE %s OR symbol ILIKE %s)"
            )
            params.extend([like, like, like, like])
        if action is not None:
            sql_parts.append("AND action = %s")
            params.append(str(action))
        if order_type is not None:
            sql_parts.append("AND order_type = %s")
            params.append(str(order_type))
        if since is not None:
            sql_parts.append("AND ts >= %s")
            params.append(since)
        if until is not None:
            sql_parts.append("AND ts <= %s")
            params.append(until)

        sql_parts.append("ORDER BY id DESC LIMIT %s OFFSET %s")
        params.extend([limit, offset])
        sql = "\n".join(sql_parts)

        with self._cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = _fetchall_dict(cur)
            return [_to_signal(row) for row in rows]

    def create_signal(self, cmd: SignalCommand, payload_hash: str, sig_valid: bool, now: datetime) -> SignalRecord:
        sql = """
            INSERT INTO signals (
                signal_id, strategy_id, account_id, ts, symbol, action, order_type,
                qty, amount, target_pos, limit_price, max_slippage_bps, expire_at,
                remark, payload_raw, payload_hash, sig_valid, received_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id, signal_id, strategy_id, account_id, ts, symbol, action, order_type,
                qty, amount, target_pos, limit_price, max_slippage_bps, expire_at,
                remark, payload_raw, payload_hash, sig_valid, received_at
        """
        with self._cursor(write=True) as cur:
            cur.execute(
                sql,
                (
                    cmd.signal_id,
                    cmd.strategy_id,
                    cmd.account_id,
                    cmd.ts,
                    cmd.symbol,
                    cmd.action,
                    cmd.order_type,
                    cmd.qty,
                    cmd.amount,
                    cmd.target_pos,
                    cmd.limit_price,
                    cmd.max_slippage_bps,
                    cmd.expire_at,
                    cmd.remark,
                    json.dumps(cmd.payload_raw, ensure_ascii=False, sort_keys=True),
                    payload_hash,
                    sig_valid,
                    now,
                ),
            )
            row = _fetchone_dict(cur)
            assert row is not None
            return _to_signal(row)

    def create_task(self, signal_db_id: int, priority: int, now: datetime) -> TaskRecord:
        sql = """
            INSERT INTO execution_tasks (
                signal_id, status, priority, next_retry_at, created_at, updated_at, version
            )
            VALUES (%s, 'READY', %s, %s, %s, %s, 0)
            RETURNING
                id, signal_id, status, priority, agent_id, lease_token, lease_until,
                attempt_count, max_attempts, next_retry_at, last_error_code, last_error_msg,
                created_at, updated_at, version
        """
        with self._cursor(write=True) as cur:
            cur.execute(sql, (signal_db_id, priority, now, now, now))
            row = _fetchone_dict(cur)
            assert row is not None
            return _to_task(row)

    def list_pullable_tasks(self, limit: int, now: datetime) -> list[TaskWithSignal]:
        with self._cursor(write=True) as cur:
            cur.execute(self._PULL_TASKS_SQL, (now, limit))
            rows = _fetchall_dict(cur)
            return [_to_task_with_signal(row) for row in rows]

    def get_task(self, task_id: int) -> TaskRecord | None:
        sql = """
            SELECT id, signal_id, status, priority, agent_id, lease_token, lease_until,
                   attempt_count, max_attempts, next_retry_at, last_error_code, last_error_msg,
                   created_at, updated_at, version
            FROM execution_tasks
            WHERE id = %s
        """
        with self._cursor() as cur:
            cur.execute(sql, (task_id,))
            row = _fetchone_dict(cur)
            return _to_task(row) if row else None

    def get_task_by_signal_db_id(self, signal_db_id: int) -> TaskRecord | None:
        sql = """
            SELECT id, signal_id, status, priority, agent_id, lease_token, lease_until,
                   attempt_count, max_attempts, next_retry_at, last_error_code, last_error_msg,
                   created_at, updated_at, version
            FROM execution_tasks
            WHERE signal_id = %s
        """
        with self._cursor() as cur:
            cur.execute(sql, (signal_db_id,))
            row = _fetchone_dict(cur)
            return _to_task(row) if row else None

    def update_task(self, task: TaskRecord) -> None:
        sql = """
            UPDATE execution_tasks
            SET
              status = %s,
              priority = %s,
              agent_id = %s,
              lease_token = %s,
              lease_until = %s,
              attempt_count = %s,
              max_attempts = %s,
              next_retry_at = %s,
              last_error_code = %s,
              last_error_msg = %s,
              updated_at = %s,
              version = %s
            WHERE id = %s AND version = %s
        """
        expected_version = task.version - 1
        with self._cursor(write=True) as cur:
            cur.execute(
                sql,
                (
                    task.status,
                    task.priority,
                    task.agent_id,
                    task.lease_token,
                    task.lease_until,
                    task.attempt_count,
                    task.max_attempts,
                    task.next_retry_at,
                    task.last_error_code,
                    task.last_error_msg,
                    task.updated_at,
                    task.version,
                    task.id,
                    expected_version,
                ),
            )
            if cur.rowcount != 1:
                raise ConflictError(f"task update conflict for task_id={task.id}")

    def iter_expired_leased_tasks(self, now: datetime) -> list[TaskRecord]:
        with self._cursor(write=True) as cur:
            cur.execute(self._EXPIRED_LEASE_SQL, (now,))
            rows = _fetchall_dict(cur)
            return [_to_task(row) for row in rows]

    def get_order_by_client_order_id(self, client_order_id: str) -> OrderRecord | None:
        sql = """
            SELECT id, client_order_id, signal_id, task_id, account_id, symbol, side,
                   price, qty, qmt_order_id, status, filled_qty, avg_price,
                   reject_code, reject_msg, submitted_at, finalized_at,
                   created_at, updated_at
            FROM orders
            WHERE client_order_id = %s
        """
        with self._cursor() as cur:
            cur.execute(sql, (client_order_id,))
            row = _fetchone_dict(cur)
            return _to_order(row) if row else None

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
        sql = """
            INSERT INTO orders (
                client_order_id, signal_id, task_id, account_id, symbol, side,
                qty, status, filled_qty, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s)
            RETURNING
                id, client_order_id, signal_id, task_id, account_id, symbol, side,
                price, qty, qmt_order_id, status, filled_qty, avg_price,
                reject_code, reject_msg, submitted_at, finalized_at,
                created_at, updated_at
        """
        with self._cursor(write=True) as cur:
            cur.execute(
                sql,
                (client_order_id, signal_id, task_id, account_id, symbol, side, qty, status, now, now),
            )
            row = _fetchone_dict(cur)
            assert row is not None
            return _to_order(row)

    def update_order(self, order: OrderRecord) -> None:
        sql = """
            UPDATE orders
            SET
              price = %s,
              qmt_order_id = %s,
              status = %s,
              filled_qty = %s,
              avg_price = %s,
              reject_code = %s,
              reject_msg = %s,
              submitted_at = %s,
              finalized_at = %s,
              updated_at = %s
            WHERE id = %s
        """
        with self._cursor(write=True) as cur:
            cur.execute(
                sql,
                (
                    order.price,
                    order.qmt_order_id,
                    order.status,
                    order.filled_qty,
                    order.avg_price,
                    order.reject_code,
                    order.reject_msg,
                    order.submitted_at,
                    order.finalized_at,
                    order.updated_at,
                    order.id,
                ),
            )

    def upsert_heartbeat(self, cmd: HeartbeatCommand, status: str, now: datetime) -> AgentHeartbeat:
        sql = """
            INSERT INTO agent_heartbeats (
              agent_id, host, version, qmt_connected, latency_ms, status, last_seen_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (agent_id)
            DO UPDATE SET
              host = EXCLUDED.host,
              version = EXCLUDED.version,
              qmt_connected = EXCLUDED.qmt_connected,
              latency_ms = EXCLUDED.latency_ms,
              status = EXCLUDED.status,
              last_seen_at = EXCLUDED.last_seen_at,
              updated_at = EXCLUDED.updated_at
            RETURNING agent_id, host, version, qmt_connected, latency_ms, status, last_seen_at, updated_at
        """
        with self._cursor(write=True) as cur:
            cur.execute(
                sql,
                (cmd.agent_id, cmd.host, cmd.version, cmd.qmt_connected, cmd.latency_ms, status, cmd.now, now),
            )
            row = _fetchone_dict(cur)
            assert row is not None
            return _to_heartbeat(row)

    def add_audit_event(self, event: AuditEvent, now: datetime) -> None:
        sql = """
            INSERT INTO audit_events (
                trace_id, entity_type, entity_id, event_type, event_detail, operator, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        with self._cursor(write=True) as cur:
            cur.execute(
                sql,
                (
                    event.trace_id,
                    event.entity_type,
                    event.entity_id,
                    event.event_type,
                    json.dumps(event.event_detail, ensure_ascii=False, sort_keys=True),
                    event.operator,
                    now,
                ),
            )

    @contextmanager
    def _cursor(self, *, write: bool = False) -> Iterator[Any]:
        conn = self._connection_factory()
        cur = conn.cursor()
        try:
            yield cur
            if write:
                conn.commit()
        except Exception:
            if write:
                conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()


def _to_task_with_signal(row: dict[str, Any]) -> TaskWithSignal:
    task = TaskRecord(
        id=row["task_id"],
        signal_id=row["task_signal_id"],
        status=TaskStatus(row["task_status"]),
        priority=row["task_priority"],
        agent_id=row.get("task_agent_id"),
        lease_token=_to_string_or_none(row.get("task_lease_token")),
        lease_until=row.get("task_lease_until"),
        attempt_count=row["task_attempt_count"],
        max_attempts=row["task_max_attempts"],
        next_retry_at=row.get("task_next_retry_at"),
        last_error_code=row.get("task_last_error_code"),
        last_error_msg=row.get("task_last_error_msg"),
        created_at=row.get("task_created_at"),
        updated_at=row.get("task_updated_at"),
        version=row["task_version"],
    )
    signal = SignalRecord(
        id=row["signal_id"],
        signal_id=row["signal_signal_id"],
        strategy_id=row["strategy_id"],
        account_id=row["account_id"],
        ts=row["ts"],
        symbol=row["symbol"],
        action=Action(row["action"]),
        order_type=OrderType(row["order_type"]),
        qty=row.get("qty"),
        amount=row.get("amount"),
        target_pos=row.get("target_pos"),
        limit_price=row.get("limit_price"),
        max_slippage_bps=row["max_slippage_bps"],
        expire_at=row.get("expire_at"),
        remark=row.get("remark"),
        payload_raw=_as_json_object(row.get("payload_raw")),
        payload_hash=row["payload_hash"],
        sig_valid=bool(row["sig_valid"]),
        received_at=row["received_at"],
    )
    return TaskWithSignal(task=task, signal=signal)


def _to_signal(row: dict[str, Any]) -> SignalRecord:
    return SignalRecord(
        id=row["id"],
        signal_id=row["signal_id"],
        strategy_id=row["strategy_id"],
        account_id=row["account_id"],
        ts=row["ts"],
        symbol=row["symbol"],
        action=Action(row["action"]),
        order_type=OrderType(row["order_type"]),
        qty=row.get("qty"),
        amount=row.get("amount"),
        target_pos=row.get("target_pos"),
        limit_price=row.get("limit_price"),
        max_slippage_bps=row["max_slippage_bps"],
        expire_at=row.get("expire_at"),
        remark=row.get("remark"),
        payload_raw=_as_json_object(row.get("payload_raw")),
        payload_hash=row["payload_hash"],
        sig_valid=bool(row["sig_valid"]),
        received_at=row["received_at"],
    )


def _to_task(row: dict[str, Any]) -> TaskRecord:
    return TaskRecord(
        id=row["id"],
        signal_id=row["signal_id"],
        status=TaskStatus(row["status"]),
        priority=row["priority"],
        agent_id=row.get("agent_id"),
        lease_token=_to_string_or_none(row.get("lease_token")),
        lease_until=row.get("lease_until"),
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        next_retry_at=row.get("next_retry_at"),
        last_error_code=row.get("last_error_code"),
        last_error_msg=row.get("last_error_msg"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        version=row["version"],
    )


def _to_order(row: dict[str, Any]) -> OrderRecord:
    return OrderRecord(
        id=row["id"],
        client_order_id=row["client_order_id"],
        signal_id=row["signal_id"],
        task_id=row["task_id"],
        account_id=row["account_id"],
        symbol=row["symbol"],
        side=Action(row["side"]),
        price=row.get("price"),
        qty=row["qty"],
        qmt_order_id=row.get("qmt_order_id"),
        status=OrderStatus(row["status"]),
        filled_qty=row["filled_qty"],
        avg_price=row.get("avg_price"),
        reject_code=row.get("reject_code"),
        reject_msg=row.get("reject_msg"),
        submitted_at=row.get("submitted_at"),
        finalized_at=row.get("finalized_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_heartbeat(row: dict[str, Any]) -> AgentHeartbeat:
    return AgentHeartbeat(
        agent_id=row["agent_id"],
        host=row["host"],
        version=row["version"],
        qmt_connected=bool(row["qmt_connected"]),
        latency_ms=row.get("latency_ms"),
        status=row["status"],
        last_seen_at=row["last_seen_at"],
        updated_at=row["updated_at"],
    )


def _fetchone_dict(cur: Any) -> dict[str, Any] | None:
    row = cur.fetchone()
    if row is None:
        return None
    return _normalize_row(cur, row)


def _fetchall_dict(cur: Any) -> list[dict[str, Any]]:
    rows = cur.fetchall()
    return [_normalize_row(cur, row) for row in rows]


def _normalize_row(cur: Any, row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys") and callable(row.keys):
        return {key: row[key] for key in row.keys()}

    if cur.description is None:
        raise TypeError("cursor description is unavailable for tuple row")

    columns = [col[0] for col in cur.description]
    return dict(zip(columns, row, strict=True))


def _as_json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    raise TypeError("payload_raw must be json object")


def _to_string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
