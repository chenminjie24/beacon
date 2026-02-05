from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from relay.domain.enums import Action, OrderType
from relay.domain.exceptions import ConflictError
from relay.domain.models import SignalCommand
from relay.repository.memory import InMemoryRelayRepository
from relay.services.relay_service import RelayService


class SignalIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)
        self.repo = InMemoryRelayRepository()
        self.service = RelayService(repository=self.repo)

    def test_new_signal_creates_task(self) -> None:
        result = self.service.ingest_signal(self._signal("s1"), now=self.now)

        self.assertEqual(result.http_status, 202)
        self.assertTrue(result.created)
        self.assertIsNotNone(result.task_db_id)

    def test_duplicate_signal_same_payload_returns_idempotent_hit(self) -> None:
        first = self.service.ingest_signal(self._signal("s1"), now=self.now)
        second = self.service.ingest_signal(self._signal("s1"), now=self.now + timedelta(seconds=2))

        self.assertEqual(first.signal_db_id, second.signal_db_id)
        self.assertEqual(second.http_status, 200)
        self.assertFalse(second.created)

    def test_duplicate_signal_different_payload_is_conflict(self) -> None:
        self.service.ingest_signal(self._signal("s1"), now=self.now)

        with self.assertRaises(ConflictError):
            self.service.ingest_signal(
                self._signal("s1", payload_override={"signal_id": "s1", "qty": "999.0"}),
                now=self.now + timedelta(seconds=1),
            )

    def _signal(self, signal_id: str, payload_override: dict[str, str] | None = None) -> SignalCommand:
        payload = {
            "signal_id": signal_id,
            "strategy_id": "ma_cross",
            "account_id": "acct-1",
            "symbol": "000001.SZ",
            "action": "BUY",
            "order_type": "MARKET",
            "qty": "100",
        }
        if payload_override:
            payload.update(payload_override)

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
            payload_raw=payload,
        )


if __name__ == "__main__":
    unittest.main()
