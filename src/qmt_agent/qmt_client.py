"""QMT client interface and dummy implementation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import uuid

from qmt_agent.models import QmtClient, QmtOrderResult
from relay.domain.models import PulledTask


class DummyQmtClient(QmtClient):
    """A placeholder QMT client for tests and local development."""

    def place_order(self, task: PulledTask, *, client_order_id: str, now: datetime) -> QmtOrderResult:
        qty = task.qty or Decimal("0")
        qmt_order_id = f"QMT-{uuid.uuid4()}"
        return QmtOrderResult(
            client_order_id=client_order_id,
            qmt_order_id=qmt_order_id,
            submitted_at=now,
            qty=qty,
        )
