"""QMT execution agent core loop (single-iteration skeleton)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from qmt_agent.models import QmtClient, RelayClient, RiskChecker
from qmt_agent.reporter import JournaledReporter
from relay.domain.enums import OrderStatus
from relay.domain.exceptions import ValidationError
from relay.domain.models import OrderReportCommand, PulledTask

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    lease_seconds: int = 30
    poll_limit: int = 10


class Agent:
    """Skeleton agent that pulls tasks and submits order reports."""

    def __init__(
        self,
        *,
        config: AgentConfig,
        relay_client: RelayClient,
        qmt_client: QmtClient,
        risk_checker: RiskChecker,
        reporter: JournaledReporter,
    ) -> None:
        self._config = config
        self._relay = relay_client
        self._qmt = qmt_client
        self._risk = risk_checker
        self._reporter = reporter

    def run_once(self, *, now: datetime | None = None) -> int:
        """Single iteration: pull tasks, process, then retry pending reports."""
        now = now or datetime.now(tz=UTC)
        tasks = self._relay.pull_tasks(agent_id=self._config.agent_id, limit=self._config.poll_limit)
        processed = 0
        for task in tasks:
            try:
                ack = self._relay.ack_task(
                    task_id=task.task_id,
                    agent_id=self._config.agent_id,
                    lease_seconds=self._config.lease_seconds,
                )
                self._process_task(task, ack.lease_token, now=now)
                processed += 1
            except Exception as exc:  # noqa: BLE001
                LOG.warning("task processing failed task_id=%s err=%s", task.task_id, exc)
                continue

        self._reporter.retry_pending(now=now)
        return processed

    def _process_task(self, task: PulledTask, lease_token: str, *, now: datetime) -> None:
        decision = self._risk.check(task, now)
        client_order_id = str(uuid.uuid4())

        if not decision.ok:
            report = self._build_report(
                task=task,
                lease_token=lease_token,
                client_order_id=client_order_id,
                now=now,
                status=OrderStatus.FAILED_RISK,
                reason_code=decision.reason_code,
                reason_msg=decision.reason_msg,
            )
            self._reporter.report(report, now=now)
            return

        result = self._qmt.place_order(task, client_order_id=client_order_id, now=now)
        report = self._build_report(
            task=task,
            lease_token=lease_token,
            client_order_id=result.client_order_id,
            now=result.submitted_at,
            status=OrderStatus.SUBMITTED,
            qmt_order_id=result.qmt_order_id,
            qty=result.qty,
        )
        self._reporter.report(report, now=now)

    def _build_report(
        self,
        *,
        task: PulledTask,
        lease_token: str,
        client_order_id: str,
        now: datetime,
        status: OrderStatus,
        qmt_order_id: str | None = None,
        qty: Decimal | None = None,
        reason_code: str | None = None,
        reason_msg: str | None = None,
    ) -> OrderReportCommand:
        resolved_qty = qty if qty is not None else task.qty
        if resolved_qty is None or resolved_qty <= 0:
            raise ValidationError("qty is required for order report")

        return OrderReportCommand(
            agent_id=self._config.agent_id,
            task_id=task.task_id,
            lease_token=lease_token,
            client_order_id=client_order_id,
            status=status,
            event_time=now,
            qmt_order_id=qmt_order_id,
            qty=resolved_qty,
            reason_code=reason_code,
            reason_msg=reason_msg,
        )
