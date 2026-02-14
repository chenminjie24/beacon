from __future__ import annotations

from datetime import UTC, datetime
import unittest

from relay.domain.exceptions import ReplayError
from relay.security.signature import PostgresReplayGuard


class PostgresReplayGuardTests(unittest.TestCase):
    def test_store_nonce_commits(self) -> None:
        now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)
        conn = _FakeConnection(_FakeCursor(rowcount=1))
        guard = PostgresReplayGuard(connection_factory=lambda: conn)

        guard.check_and_store(nonce="n1", now=now, ttl_seconds=300)

        self.assertTrue(conn.commit_called)
        self.assertFalse(conn.rollback_called)
        self.assertIn("DELETE FROM request_nonces", conn.cursor_obj.executed[0])
        self.assertIn("INSERT INTO request_nonces", conn.cursor_obj.executed[1])

    def test_replay_raises_and_rolls_back(self) -> None:
        now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)
        conn = _FakeConnection(_FakeCursor(rowcount=0))
        guard = PostgresReplayGuard(connection_factory=lambda: conn)

        with self.assertRaises(ReplayError):
            guard.check_and_store(nonce="n1", now=now, ttl_seconds=300)

        self.assertTrue(conn.rollback_called)


class _FakeCursor:
    def __init__(self, *, rowcount: int) -> None:
        self.rowcount = rowcount
        self.executed: list[str] = []

    def execute(self, sql: str, params=None) -> None:
        self.executed.append(sql)

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
