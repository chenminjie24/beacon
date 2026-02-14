from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from qmt_agent.journal import SqliteJournal
from relay.domain.enums import OrderStatus
from relay.domain.models import OrderReportCommand


class SqliteJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)
        self.journal = SqliteJournal(":memory:")

    def test_enqueue_and_due(self) -> None:
        report = self._report("c1")
        entry_id = self.journal.enqueue_failed(
            report,
            now=self.now,
            error="net",
            backoff_seconds=5,
        )
        self.assertGreater(entry_id, 0)

        due_now = self.journal.due(now=self.now, limit=10)
        self.assertEqual(due_now, [])

        due_later = self.journal.due(now=self.now + timedelta(seconds=5), limit=10)
        self.assertEqual(len(due_later), 1)
        self.assertEqual(due_later[0].report.client_order_id, "c1")

    def test_record_failure_increments_attempts(self) -> None:
        report = self._report("c2")
        entry_id = self.journal.enqueue_failed(
            report,
            now=self.now,
            error="net",
            backoff_seconds=1,
        )
        self.journal.record_failure(entry_id, now=self.now + timedelta(seconds=1), error="net2", backoff_seconds=2)

        entries = self.journal.due(now=self.now + timedelta(seconds=3), limit=10)
        self.assertEqual(entries[0].attempt_count, 2)

    def test_mark_sent_clears_pending(self) -> None:
        report = self._report("c3")
        entry_id = self.journal.enqueue_failed(
            report,
            now=self.now,
            error="net",
            backoff_seconds=1,
        )
        self.journal.mark_sent(entry_id, now=self.now + timedelta(seconds=2))
        self.assertEqual(self.journal.pending_count(), 0)

    def _report(self, client_order_id: str) -> OrderReportCommand:
        return OrderReportCommand(
            agent_id="agent-1",
            task_id=1,
            lease_token="lease",
            client_order_id=client_order_id,
            status=OrderStatus.SUBMITTED,
            event_time=self.now,
            qty=Decimal("100"),
        )


if __name__ == "__main__":
    unittest.main()
