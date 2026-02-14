"""SQLite-backed local journal for pending order reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import sqlite3
import threading

from relay.domain.enums import OrderStatus
from relay.domain.models import OrderReportCommand


@dataclass(frozen=True)
class JournalEntry:
    id: int
    report: OrderReportCommand
    attempt_count: int
    next_retry_at: datetime
    status: str
    last_error: str | None


class SqliteJournal:
    """Persistent journal for order reports with retry metadata."""

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init_schema()

    def enqueue_failed(
        self,
        report: OrderReportCommand,
        *,
        now: datetime,
        error: str,
        backoff_seconds: int,
    ) -> int:
        payload = _serialize_report(report)
        now_ts = int(now.timestamp())
        next_retry = now_ts + backoff_seconds
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO order_reports (
                    payload_json, status, attempt_count, next_retry_at, last_error, created_at, updated_at
                )
                VALUES (?, 'FAILED', 1, ?, ?, ?, ?)
                """,
                (payload, next_retry, error, now_ts, now_ts),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def due(self, *, now: datetime, limit: int) -> list[JournalEntry]:
        now_ts = int(now.timestamp())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, payload_json, status, attempt_count, next_retry_at, last_error
                FROM order_reports
                WHERE status IN ('PENDING', 'FAILED') AND next_retry_at <= ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (now_ts, limit),
            )
            rows = cur.fetchall()
            return [_row_to_entry(row) for row in rows]

    def mark_sent(self, entry_id: int, *, now: datetime) -> None:
        now_ts = int(now.timestamp())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE order_reports
                SET status = 'SENT', updated_at = ?
                WHERE id = ?
                """,
                (now_ts, entry_id),
            )
            self._conn.commit()

    def record_failure(
        self,
        entry_id: int,
        *,
        now: datetime,
        error: str,
        backoff_seconds: int,
    ) -> None:
        now_ts = int(now.timestamp())
        next_retry = now_ts + backoff_seconds
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE order_reports
                SET status = 'FAILED',
                    attempt_count = attempt_count + 1,
                    next_retry_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (next_retry, error, now_ts, entry_id),
            )
            self._conn.commit()

    def pending_count(self) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT COUNT(1) FROM order_reports
                WHERE status IN ('PENDING', 'FAILED')
                """,
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS order_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at INTEGER NOT NULL,
                    last_error TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            self._conn.commit()


def _serialize_report(report: OrderReportCommand) -> str:
    payload = {
        "agent_id": report.agent_id,
        "task_id": report.task_id,
        "lease_token": report.lease_token,
        "client_order_id": report.client_order_id,
        "status": report.status.value,
        "event_time": report.event_time.isoformat(),
        "qmt_order_id": report.qmt_order_id,
        "qty": str(report.qty) if report.qty is not None else None,
        "filled_qty": str(report.filled_qty) if report.filled_qty is not None else None,
        "avg_price": str(report.avg_price) if report.avg_price is not None else None,
        "reason_code": report.reason_code,
        "reason_msg": report.reason_msg,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _deserialize_report(payload_json: str) -> OrderReportCommand:
    data = json.loads(payload_json)
    return OrderReportCommand(
        agent_id=data["agent_id"],
        task_id=int(data["task_id"]),
        lease_token=data["lease_token"],
        client_order_id=data["client_order_id"],
        status=OrderStatus(data["status"]),
        event_time=datetime.fromisoformat(data["event_time"]),
        qmt_order_id=data.get("qmt_order_id"),
        qty=_to_decimal_or_none(data.get("qty")),
        filled_qty=_to_decimal_or_none(data.get("filled_qty")),
        avg_price=_to_decimal_or_none(data.get("avg_price")),
        reason_code=data.get("reason_code"),
        reason_msg=data.get("reason_msg"),
    )


def _row_to_entry(row: sqlite3.Row) -> JournalEntry:
    return JournalEntry(
        id=int(row["id"]),
        report=_deserialize_report(row["payload_json"]),
        attempt_count=int(row["attempt_count"]),
        next_retry_at=datetime.fromtimestamp(int(row["next_retry_at"]), tz=UTC),
        status=row["status"],
        last_error=row["last_error"],
    )


def _to_decimal_or_none(value: str | None):
    if value is None:
        return None
    from decimal import Decimal

    return Decimal(value)
