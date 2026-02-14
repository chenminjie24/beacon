"""Order report sender with local journal retry logic."""

from __future__ import annotations

import logging
from datetime import datetime

from qmt_agent.journal import SqliteJournal
from qmt_agent.models import RelayClient
from relay.domain.models import OrderReportCommand

LOG = logging.getLogger(__name__)


class JournaledReporter:
    """Reporter that persists failed reports for retry."""

    def __init__(
        self,
        client: RelayClient,
        journal: SqliteJournal,
        *,
        retry_schedule: tuple[int, ...] = (5, 15, 30),
        max_attempts: int = 5,
    ) -> None:
        self._client = client
        self._journal = journal
        self._retry_schedule = retry_schedule
        self._max_attempts = max_attempts

    def report(self, report: OrderReportCommand, *, now: datetime) -> bool:
        try:
            self._client.report_order(report)
            return True
        except Exception as exc:  # noqa: BLE001 - relay failures are handled here
            backoff = self._backoff_seconds(attempt=1)
            self._journal.enqueue_failed(
                report,
                now=now,
                error=str(exc),
                backoff_seconds=backoff,
            )
            LOG.warning("report failed; journaled for retry: %s", exc)
            return False

    def retry_pending(self, *, now: datetime, limit: int = 50) -> int:
        pending = self._journal.due(now=now, limit=limit)
        sent = 0
        for entry in pending:
            if entry.attempt_count >= self._max_attempts:
                continue
            try:
                self._client.report_order(entry.report)
                self._journal.mark_sent(entry.id, now=now)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                backoff = self._backoff_seconds(attempt=entry.attempt_count + 1)
                self._journal.record_failure(entry.id, now=now, error=str(exc), backoff_seconds=backoff)
        return sent

    def _backoff_seconds(self, attempt: int) -> int:
        idx = min(max(attempt - 1, 0), len(self._retry_schedule) - 1)
        return self._retry_schedule[idx]
