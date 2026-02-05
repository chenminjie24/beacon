from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from relay.domain.enums import Action, OrderType, TaskStatus
from relay.domain.models import SignalCommand
from relay.repository.memory import InMemoryRelayRepository
from relay.services.relay_service import RelayService


class PullExpiredSignalTests(unittest.TestCase):
    def test_expired_signal_is_not_pulled_and_task_failed(self) -> None:
        now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)
        repo = InMemoryRelayRepository()
        service = RelayService(repository=repo)

        service.ingest_signal(
            SignalCommand(
                signal_id="s1",
                strategy_id="stg",
                account_id="acct",
                ts=now,
                symbol="000001.SZ",
                action=Action.BUY,
                order_type=OrderType.MARKET,
                qty=Decimal("100"),
                expire_at=now + timedelta(seconds=1),
            ),
            now=now,
        )

        tasks = service.pull_tasks(agent_id="agent-1", limit=10, now=now + timedelta(seconds=2))
        self.assertEqual(tasks, [])

        task = repo.get_task(1)
        assert task is not None
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.last_error_code, "SIGNAL_EXPIRED")


if __name__ == "__main__":
    unittest.main()
