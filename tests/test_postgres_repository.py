from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import unittest

from relay.domain.enums import TaskStatus
from relay.domain.exceptions import ConflictError
from relay.domain.models import TaskRecord
from relay.repository.postgres import PostgresRelayRepository


class PostgresRepositoryTests(unittest.TestCase):
    def test_pull_tasks_uses_skip_locked_and_maps_rows(self) -> None:
        now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)
        row = {
            "task_id": 1,
            "task_signal_id": 11,
            "task_status": "READY",
            "task_priority": 100,
            "task_agent_id": None,
            "task_lease_token": None,
            "task_lease_until": None,
            "task_attempt_count": 0,
            "task_max_attempts": 3,
            "task_next_retry_at": now,
            "task_last_error_code": None,
            "task_last_error_msg": None,
            "task_created_at": now,
            "task_updated_at": now,
            "task_version": 0,
            "signal_id": 11,
            "signal_signal_id": "S1",
            "strategy_id": "stg-1",
            "account_id": "acct-1",
            "ts": now,
            "symbol": "000001.SZ",
            "action": "BUY",
            "order_type": "MARKET",
            "qty": Decimal("100"),
            "amount": None,
            "target_pos": None,
            "limit_price": None,
            "max_slippage_bps": 20,
            "expire_at": None,
            "remark": None,
            "payload_raw": {"signal_id": "S1"},
            "payload_hash": "abc",
            "sig_valid": True,
            "received_at": now,
        }
        conn = _FakeConnection(_FakeCursor(fetchall_rows=[row]))
        repo = PostgresRelayRepository(connection_factory=lambda: conn)

        tasks = repo.list_pullable_tasks(limit=5, now=now)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task.id, 1)
        self.assertEqual(tasks[0].signal.signal_id, "S1")
        sql = conn.cursor_obj.executed[0][0]
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)

    def test_iter_expired_leases_uses_skip_locked(self) -> None:
        now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)
        row = {
            "id": 1,
            "signal_id": 11,
            "status": "ACKED",
            "priority": 100,
            "agent_id": "agent-1",
            "lease_token": "tok",
            "lease_until": now,
            "attempt_count": 0,
            "max_attempts": 3,
            "next_retry_at": now,
            "last_error_code": None,
            "last_error_msg": None,
            "created_at": now,
            "updated_at": now,
            "version": 0,
        }
        conn = _FakeConnection(_FakeCursor(fetchall_rows=[row]))
        repo = PostgresRelayRepository(connection_factory=lambda: conn)

        tasks = repo.iter_expired_leased_tasks(now=now)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].status, TaskStatus.ACKED)
        sql = conn.cursor_obj.executed[0][0]
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)

    def test_update_task_optimistic_lock_conflict(self) -> None:
        now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)
        conn = _FakeConnection(_FakeCursor(rowcount=0))
        repo = PostgresRelayRepository(connection_factory=lambda: conn)
        task = TaskRecord(
            id=1,
            signal_id=10,
            status=TaskStatus.ACKED,
            priority=100,
            agent_id="agent-1",
            lease_token="tok",
            lease_until=now,
            attempt_count=0,
            max_attempts=3,
            next_retry_at=now,
            last_error_code=None,
            last_error_msg=None,
            created_at=now,
            updated_at=now,
            version=1,
        )

        with self.assertRaises(ConflictError):
            repo.update_task(task)

        self.assertTrue(conn.rollback_called)


class _FakeCursor:
    def __init__(self, *, fetchone_row=None, fetchall_rows=None, rowcount: int = 1) -> None:
        self.fetchone_row = fetchone_row
        self.fetchall_rows = fetchall_rows or []
        self.rowcount = rowcount
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []
        self.description = None

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        return self.fetchone_row

    def fetchall(self):
        return list(self.fetchall_rows)

    def close(self) -> None:
        return None


class _FakeConnection:
    def __init__(self, cursor_obj: _FakeCursor) -> None:
        self.cursor_obj = cursor_obj
        self.commit_called = False
        self.rollback_called = False
        self.close_called = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commit_called = True

    def rollback(self) -> None:
        self.rollback_called = True

    def close(self) -> None:
        self.close_called = True


if __name__ == "__main__":
    unittest.main()
