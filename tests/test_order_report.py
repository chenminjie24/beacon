from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from relay.domain.enums import Action, OrderStatus, OrderType, TaskStatus
from relay.domain.exceptions import ConflictError
from relay.domain.models import OrderReportCommand, SignalCommand
from relay.repository.memory import InMemoryRelayRepository
from relay.services.relay_service import RelayService


class OrderReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)
        self.repo = InMemoryRelayRepository()
        self.service = RelayService(repository=self.repo)
        self.service.ingest_signal(self._signal("s1"), now=self.now)
        self.task_id = self.service.pull_tasks(agent_id="agent-1", limit=10, now=self.now)[0].task_id
        self.ack = self.service.ack_task(task_id=self.task_id, agent_id="agent-1", lease_seconds=30, now=self.now)

    def test_submitted_then_filled_marks_task_done(self) -> None:
        submitted = OrderReportCommand(
            agent_id="agent-1",
            task_id=self.task_id,
            lease_token=self.ack.lease_token,
            client_order_id="c1",
            status=OrderStatus.SUBMITTED,
            event_time=self.now + timedelta(seconds=1),
            qty=Decimal("100"),
        )
        self.service.report_order(submitted, now=self.now + timedelta(seconds=1))

        filled = OrderReportCommand(
            agent_id="agent-1",
            task_id=self.task_id,
            lease_token=self.ack.lease_token,
            client_order_id="c1",
            status=OrderStatus.FILLED,
            event_time=self.now + timedelta(seconds=2),
            filled_qty=Decimal("100"),
            avg_price=Decimal("10.5"),
        )
        status = self.service.report_order(filled, now=self.now + timedelta(seconds=2))
        self.assertEqual(status, OrderStatus.FILLED)

        task = self.repo.get_task(self.task_id)
        assert task is not None
        self.assertEqual(task.status, TaskStatus.DONE)
        self.assertIsNone(task.lease_token)

    def test_failed_risk_marks_task_failed(self) -> None:
        rejected = OrderReportCommand(
            agent_id="agent-1",
            task_id=self.task_id,
            lease_token=self.ack.lease_token,
            client_order_id="c2",
            status=OrderStatus.FAILED_RISK,
            event_time=self.now + timedelta(seconds=1),
            qty=Decimal("100"),
            reason_code="RISK_POSITION",
            reason_msg="position limit exceeded",
        )
        self.service.report_order(rejected, now=self.now + timedelta(seconds=1))

        task = self.repo.get_task(self.task_id)
        assert task is not None
        self.assertEqual(task.status, TaskStatus.FAILED)

    def test_wrong_lease_token_is_conflict(self) -> None:
        report = OrderReportCommand(
            agent_id="agent-1",
            task_id=self.task_id,
            lease_token="bad-token",
            client_order_id="c3",
            status=OrderStatus.SUBMITTED,
            event_time=self.now,
            qty=Decimal("100"),
        )
        with self.assertRaises(ConflictError):
            self.service.report_order(report, now=self.now)

    def test_terminal_order_rejects_regression(self) -> None:
        filled = OrderReportCommand(
            agent_id="agent-1",
            task_id=self.task_id,
            lease_token=self.ack.lease_token,
            client_order_id="c4",
            status=OrderStatus.FILLED,
            event_time=self.now + timedelta(seconds=1),
            qty=Decimal("100"),
            filled_qty=Decimal("100"),
        )
        self.service.report_order(filled, now=self.now + timedelta(seconds=1))

        with self.assertRaises(ConflictError):
            self.service.report_order(
                OrderReportCommand(
                    agent_id="agent-1",
                    task_id=self.task_id,
                    lease_token=self.ack.lease_token,
                    client_order_id="c4",
                    status=OrderStatus.PARTIAL,
                    event_time=self.now + timedelta(seconds=2),
                    filled_qty=Decimal("90"),
                ),
                now=self.now + timedelta(seconds=2),
            )

    def test_terminal_retry_same_status_is_idempotent(self) -> None:
        filled = OrderReportCommand(
            agent_id="agent-1",
            task_id=self.task_id,
            lease_token=self.ack.lease_token,
            client_order_id="c5",
            status=OrderStatus.FILLED,
            event_time=self.now + timedelta(seconds=1),
            qty=Decimal("100"),
            filled_qty=Decimal("100"),
        )
        self.service.report_order(filled, now=self.now + timedelta(seconds=1))

        retried_status = self.service.report_order(
            OrderReportCommand(
                agent_id="agent-1",
                task_id=self.task_id,
                lease_token=self.ack.lease_token,
                client_order_id="c5",
                status=OrderStatus.FILLED,
                event_time=self.now + timedelta(seconds=2),
                filled_qty=Decimal("100"),
            ),
            now=self.now + timedelta(seconds=2),
        )
        self.assertEqual(retried_status, OrderStatus.FILLED)

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
