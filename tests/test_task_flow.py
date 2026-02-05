from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from relay.domain.enums import Action, OrderType, TaskStatus
from relay.domain.exceptions import ConflictError
from relay.domain.models import SignalCommand
from relay.repository.memory import InMemoryRelayRepository
from relay.services.relay_service import RelayService


class TaskFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)
        self.repo = InMemoryRelayRepository()
        self.service = RelayService(repository=self.repo)
        self.service.ingest_signal(self._signal("s1"), now=self.now)

    def test_pull_and_ack_happy_path(self) -> None:
        tasks = self.service.pull_tasks(agent_id="agent-1", limit=10, now=self.now)
        self.assertEqual(len(tasks), 1)

        ack = self.service.ack_task(
            task_id=tasks[0].task_id,
            agent_id="agent-1",
            lease_seconds=30,
            now=self.now,
        )
        self.assertEqual(ack.task_id, tasks[0].task_id)

    def test_ack_conflict_when_task_already_acked(self) -> None:
        task_id = self.service.pull_tasks(agent_id="agent-1", limit=10, now=self.now)[0].task_id
        self.service.ack_task(task_id=task_id, agent_id="agent-1", lease_seconds=30, now=self.now)

        with self.assertRaises(ConflictError):
            self.service.ack_task(task_id=task_id, agent_id="agent-2", lease_seconds=30, now=self.now)

    def test_recycle_expired_lease_returns_task_to_ready(self) -> None:
        task_id = self.service.pull_tasks(agent_id="agent-1", limit=10, now=self.now)[0].task_id
        self.service.ack_task(task_id=task_id, agent_id="agent-1", lease_seconds=5, now=self.now)

        recycled = self.service.recycle_expired_leases(now=self.now + timedelta(seconds=6))
        self.assertEqual(recycled, 1)

        task = self.repo.get_task(task_id)
        assert task is not None
        self.assertEqual(task.status, TaskStatus.READY)
        self.assertEqual(task.attempt_count, 1)

    def test_recycle_expired_lease_hits_max_retry(self) -> None:
        task_id = self.service.pull_tasks(agent_id="agent-1", limit=10, now=self.now)[0].task_id
        first_ack = self.service.ack_task(task_id=task_id, agent_id="agent-1", lease_seconds=5, now=self.now)
        self.assertTrue(first_ack.lease_token)
        self.service.recycle_expired_leases(now=self.now + timedelta(seconds=6))

        second_ack = self.service.ack_task(
            task_id=task_id,
            agent_id="agent-1",
            lease_seconds=5,
            now=self.now + timedelta(seconds=11),
        )
        self.assertTrue(second_ack.lease_token)
        self.service.recycle_expired_leases(now=self.now + timedelta(seconds=17))

        third_ack = self.service.ack_task(
            task_id=task_id,
            agent_id="agent-1",
            lease_seconds=5,
            now=self.now + timedelta(seconds=33),
        )
        self.assertTrue(third_ack.lease_token)
        self.service.recycle_expired_leases(now=self.now + timedelta(seconds=39))

        task = self.repo.get_task(task_id)
        assert task is not None
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.attempt_count, 3)

    def _signal(self, signal_id: str) -> SignalCommand:
        return SignalCommand(
            signal_id=signal_id,
            strategy_id="ma_cross",
            account_id="acct-1",
            ts=self.now,
            symbol="000001.SZ",
            action=Action.BUY,
            order_type=OrderType.MARKET,
            qty=Decimal("100"),
            max_slippage_bps=20,
            expire_at=self.now + timedelta(minutes=5),
            payload_raw={"signal_id": signal_id, "qty": "100"},
        )


if __name__ == "__main__":
    unittest.main()
