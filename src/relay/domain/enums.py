"""Domain enumerations used by the relay service."""

from __future__ import annotations

from enum import StrEnum


class Action(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    TARGET_VALUE = "TARGET_VALUE"
    TARGET_POS = "TARGET_POS"


class TaskStatus(StrEnum):
    READY = "READY"
    ACKED = "ACKED"
    EXECUTING = "EXECUTING"
    DONE = "DONE"
    FAILED = "FAILED"


class OrderStatus(StrEnum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    FAILED_RISK = "FAILED_RISK"


class EventType(StrEnum):
    SIGNAL_ACCEPTED = "SIGNAL_ACCEPTED"
    SIGNAL_DUPLICATE = "SIGNAL_DUPLICATE"
    SIGNAL_CONFLICT = "SIGNAL_CONFLICT"
    TASK_ACKED = "TASK_ACKED"
    TASK_RECYCLED = "TASK_RECYCLED"
    ORDER_REPORTED = "ORDER_REPORTED"
