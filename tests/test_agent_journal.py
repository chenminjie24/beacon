from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from qmt_agent.agent import Agent, AgentConfig
from qmt_agent.journal import SqliteJournal
from qmt_agent.qmt_client import DummyQmtClient
from qmt_agent.reporter import JournaledReporter
from qmt_agent.risk import AllowAllRiskChecker
from relay.domain.enums import Action, OrderStatus, OrderType
from relay.domain.models import AckResult, OrderReportCommand, PulledTask


class AgentSkeletonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)

    def test_agent_processes_task_and_reports(self) -> None:
        task = PulledTask(
            task_id=1,
            signal_id="S1",
            strategy_id="stg",
            account_id="acct",
            symbol="000001.SZ",
            side=Action.BUY,
            order_type=OrderType.MARKET,
            qty=Decimal("100"),
            amount=None,
            target_pos=None,
            limit_price=None,
            expire_at=None,
            priority=100,
        )
        relay = _FakeRelayClient(tasks=[task])
        journal = SqliteJournal(":memory:")
        reporter = JournaledReporter(client=relay, journal=journal)
        agent = Agent(
            config=AgentConfig(agent_id="agent-1", lease_seconds=30, poll_limit=10),
            relay_client=relay,
            qmt_client=DummyQmtClient(),
            risk_checker=AllowAllRiskChecker(),
            reporter=reporter,
        )

        processed = agent.run_once(now=self.now)

        self.assertEqual(processed, 1)
        self.assertIsNotNone(relay.last_report)
        assert relay.last_report is not None
        self.assertEqual(relay.last_report.status, OrderStatus.SUBMITTED)
        self.assertEqual(journal.pending_count(), 0)

    def test_report_failure_is_journaled(self) -> None:
        report = OrderReportCommand(
            agent_id="agent-1",
            task_id=1,
            lease_token="lease",
            client_order_id="c1",
            status=OrderStatus.SUBMITTED,
            event_time=self.now,
            qty=Decimal("100"),
        )
        relay = _FakeRelayClient(fail_report=True)
        journal = SqliteJournal(":memory:")
        reporter = JournaledReporter(client=relay, journal=journal)

        ok = reporter.report(report, now=self.now)

        self.assertFalse(ok)
        self.assertEqual(journal.pending_count(), 1)

    def test_retry_succeeds_after_failure(self) -> None:
        report = OrderReportCommand(
            agent_id="agent-1",
            task_id=1,
            lease_token="lease",
            client_order_id="c1",
            status=OrderStatus.SUBMITTED,
            event_time=self.now,
            qty=Decimal("100"),
        )
        relay = _FakeRelayClient(fail_report=True)
        journal = SqliteJournal(":memory:")
        reporter = JournaledReporter(client=relay, journal=journal, retry_schedule=(1,))

        reporter.report(report, now=self.now)
        relay.fail_report = False

        sent = reporter.retry_pending(now=self.now + timedelta(seconds=1))

        self.assertEqual(sent, 1)
        self.assertEqual(journal.pending_count(), 0)


class _FakeRelayClient:
    def __init__(self, *, tasks=None, fail_report: bool = False) -> None:
        self.tasks = tasks or []
        self.fail_report = fail_report
        self.last_report: OrderReportCommand | None = None

    def pull_tasks(self, *, agent_id: str, limit: int):
        return list(self.tasks)

    def ack_task(self, *, task_id: int, agent_id: str, lease_seconds: int) -> AckResult:
        return AckResult(task_id=task_id, lease_token="lease-token", lease_until=datetime.now(tz=UTC))

    def report_order(self, report: OrderReportCommand) -> None:
        if self.fail_report:
            raise RuntimeError("relay down")
        self.last_report = report

    def heartbeat(self, *, agent_id: str, host: str, version: str, qmt_connected: bool, latency_ms: int | None) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
