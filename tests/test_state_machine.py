from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from relay.domain.enums import Action, OrderStatus, OrderType, TaskStatus
from relay.domain.exceptions import ValidationError
from relay.domain.models import SignalCommand
from relay.domain.state_machine import map_order_to_task_status, validate_signal_command


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 2, 4, 9, 0, tzinfo=UTC)

    def test_limit_order_requires_limit_price(self) -> None:
        cmd = SignalCommand(
            signal_id="s1",
            strategy_id="stg",
            account_id="acct",
            ts=self.now,
            symbol="000001.SZ",
            action=Action.BUY,
            order_type=OrderType.LIMIT,
            qty=Decimal("100"),
            limit_price=None,
            expire_at=self.now + timedelta(minutes=1),
        )

        with self.assertRaises(ValidationError):
            validate_signal_command(cmd)

    def test_target_pos_shape(self) -> None:
        cmd = SignalCommand(
            signal_id="s1",
            strategy_id="stg",
            account_id="acct",
            ts=self.now,
            symbol="000001.SZ",
            action=Action.BUY,
            order_type=OrderType.TARGET_POS,
            target_pos=Decimal("0.30"),
            expire_at=self.now + timedelta(minutes=1),
        )
        validate_signal_command(cmd)

    def test_failed_risk_maps_to_failed_task(self) -> None:
        self.assertEqual(map_order_to_task_status(OrderStatus.FAILED_RISK), TaskStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
