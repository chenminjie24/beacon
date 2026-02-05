"""Validation and state transition helpers for relay entities."""

from __future__ import annotations

from decimal import Decimal

from relay.domain.enums import OrderStatus, OrderType, TaskStatus
from relay.domain.exceptions import ConflictError, ValidationError
from relay.domain.models import SignalCommand

_ALLOWED_ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {
        OrderStatus.NEW,
        OrderStatus.SUBMITTED,
        OrderStatus.PARTIAL,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.FAILED_RISK,
    },
    OrderStatus.SUBMITTED: {
        OrderStatus.SUBMITTED,
        OrderStatus.PARTIAL,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
    },
    OrderStatus.PARTIAL: {
        OrderStatus.PARTIAL,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
    },
    OrderStatus.FILLED: {OrderStatus.FILLED},
    OrderStatus.CANCELED: {OrderStatus.CANCELED},
    OrderStatus.REJECTED: {OrderStatus.REJECTED},
    OrderStatus.FAILED_RISK: {OrderStatus.FAILED_RISK},
}

_TERMINAL_SUCCESS = {OrderStatus.FILLED, OrderStatus.CANCELED}
_TERMINAL_FAILURE = {OrderStatus.REJECTED, OrderStatus.FAILED_RISK}


def validate_signal_command(cmd: SignalCommand) -> None:
    """Validate signal payload according to v1.3 defaults."""
    if cmd.max_slippage_bps < 0 or cmd.max_slippage_bps > 10_000:
        raise ValidationError("max_slippage_bps must be between 0 and 10000")
    if cmd.expire_at is not None and cmd.expire_at <= cmd.ts:
        raise ValidationError("expire_at must be later than ts")

    _validate_order_shape(cmd.order_type, cmd.qty, cmd.amount, cmd.target_pos, cmd.limit_price)


def validate_order_transition(current: OrderStatus, incoming: OrderStatus) -> None:
    """Reject order state regressions and illegal jumps."""
    allowed = _ALLOWED_ORDER_TRANSITIONS[current]
    if incoming not in allowed:
        raise ConflictError(f"illegal order transition: {current} -> {incoming}")


def map_order_to_task_status(status: OrderStatus) -> TaskStatus:
    """Map order status to task status with FAILED_RISK as task failure."""
    if status in _TERMINAL_SUCCESS:
        return TaskStatus.DONE
    if status in _TERMINAL_FAILURE:
        return TaskStatus.FAILED
    return TaskStatus.EXECUTING


def is_order_terminal(status: OrderStatus) -> bool:
    return status in _TERMINAL_SUCCESS | _TERMINAL_FAILURE


def _validate_order_shape(
    order_type: OrderType,
    qty: Decimal | None,
    amount: Decimal | None,
    target_pos: Decimal | None,
    limit_price: Decimal | None,
) -> None:
    if order_type == OrderType.TARGET_VALUE:
        if amount is None or qty is not None or target_pos is not None:
            raise ValidationError("TARGET_VALUE requires amount only")
    elif order_type == OrderType.TARGET_POS:
        if target_pos is None or qty is not None or amount is not None:
            raise ValidationError("TARGET_POS requires target_pos only")
    else:
        if qty is None or amount is not None or target_pos is not None:
            raise ValidationError("MARKET/LIMIT requires qty only")

    if qty is not None and qty <= 0:
        raise ValidationError("qty must be positive")
    if amount is not None and amount <= 0:
        raise ValidationError("amount must be positive")
    if target_pos is not None and (target_pos < 0 or target_pos > 1):
        raise ValidationError("target_pos must be between 0 and 1")

    if order_type == OrderType.LIMIT and (limit_price is None or limit_price <= 0):
        raise ValidationError("LIMIT requires positive limit_price")
