import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SignalType(str, enum.Enum):
    INCREMENTAL_ORDER = 'INCREMENTAL_ORDER'
    TARGET_POSITION = 'TARGET_POSITION'


class Side(str, enum.Enum):
    BUY = 'BUY'
    SELL = 'SELL'


class OrderStyle(str, enum.Enum):
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'


class SignalStatus(str, enum.Enum):
    RECEIVED = 'RECEIVED'
    VERIFIED = 'VERIFIED'
    NORMALIZED = 'NORMALIZED'
    RISK_PASSED = 'RISK_PASSED'
    DISPATCHED = 'DISPATCHED'
    EXECUTING = 'EXECUTING'
    PARTIAL_FILLED = 'PARTIAL_FILLED'
    COMPLETED = 'COMPLETED'
    REJECTED_SIGNATURE = 'REJECTED_SIGNATURE'
    REJECTED_SCHEMA = 'REJECTED_SCHEMA'
    REJECTED_RISK = 'REJECTED_RISK'
    FAILED_EXECUTION = 'FAILED_EXECUTION'


class TaskStatus(str, enum.Enum):
    PENDING = 'PENDING'
    CLAIMED = 'CLAIMED'
    ACKED = 'ACKED'
    FAILED = 'FAILED'


class TaskAction(str, enum.Enum):
    PLACE_ORDER = 'PLACE_ORDER'
    CANCEL_ORDER = 'CANCEL_ORDER'


class OrderStatus(str, enum.Enum):
    PENDING_SUBMIT = 'PENDING_SUBMIT'
    SUBMITTED = 'SUBMITTED'
    PARTIAL_FILLED = 'PARTIAL_FILLED'
    FILLED = 'FILLED'
    CANCELED = 'CANCELED'
    CANCEL_PENDING = 'CANCEL_PENDING'
    REJECTED = 'REJECTED'
    FAILED = 'FAILED'


class ClientStatus(str, enum.Enum):
    ONLINE = 'ONLINE'
    OFFLINE = 'OFFLINE'


class AlertLevel(str, enum.Enum):
    INFO = 'INFO'
    WARN = 'WARN'
    ERROR = 'ERROR'


class AlertStatus(str, enum.Enum):
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'


class PlatformSource(Base):
    __tablename__ = 'platform_sources'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    webhook_secret: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Strategy(Base):
    __tablename__ = 'strategies'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Signal(Base):
    __tablename__ = 'signals'
    __table_args__ = (UniqueConstraint('source_platform', 'idempotency_key', name='uq_signal_source_idem'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_platform: Mapped[str] = mapped_column(String(64), index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), ForeignKey('strategies.id'))
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    signal_type: Mapped[SignalType] = mapped_column(Enum(SignalType))
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[Side] = mapped_column(Enum(Side))
    order_style: Mapped[OrderStyle] = mapped_column(Enum(OrderStyle), default=OrderStyle.MARKET)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_position_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp_ms: Mapped[int] = mapped_column(BigInteger)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[SignalStatus] = mapped_column(Enum(SignalStatus), default=SignalStatus.RECEIVED, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DispatchTask(Base):
    __tablename__ = 'dispatch_tasks'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), ForeignKey('signals.id'), index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), ForeignKey('orders.id'), nullable=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[TaskAction] = mapped_column(Enum(TaskAction))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING, index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Order(Base):
    __tablename__ = 'orders'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), ForeignKey('signals.id'), index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[Side] = mapped_column(Enum(Side))
    order_style: Mapped[OrderStyle] = mapped_column(Enum(OrderStyle), default=OrderStyle.MARKET)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING_SUBMIT, index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_price: Mapped[float] = mapped_column(Float, default=0)
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Trade(Base):
    __tablename__ = 'trades'
    __table_args__ = (UniqueConstraint('order_id', 'broker_trade_id', name='uq_trade_order_broker_trade'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), ForeignKey('orders.id'), index=True)
    broker_trade_id: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[Side] = mapped_column(Enum(Side))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PositionSnapshot(Base):
    __tablename__ = 'positions_snapshot'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    available_quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0)
    market_value: Mapped[float] = mapped_column(Float, default=0)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class RiskRule(Base):
    __tablename__ = 'risk_rules'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    max_single_amount: Mapped[float] = mapped_column(Float, default=50000)
    max_single_quantity: Mapped[int] = mapped_column(Integer, default=100000)
    daily_max_amount: Mapped[float] = mapped_column(Float, default=200000)
    min_order_amount: Mapped[float] = mapped_column(Float, default=100)
    min_lot_size: Mapped[int] = mapped_column(Integer, default=100)
    whitelist: Mapped[list] = mapped_column(JSON, default=list)
    blacklist: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RiskEvent(Base):
    __tablename__ = 'risk_events'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), ForeignKey('signals.id'), index=True)
    rule_id: Mapped[str | None] = mapped_column(String(64), ForeignKey('risk_rules.id'), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64))
    reason_detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Client(Base):
    __tablename__ = 'clients'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32), default='0.1.0')
    status: Mapped[ClientStatus] = mapped_column(Enum(ClientStatus), default=ClientStatus.ONLINE)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Alert(Base):
    __tablename__ = 'alerts'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    level: Mapped[AlertLevel] = mapped_column(Enum(AlertLevel), default=AlertLevel.WARN)
    category: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = 'users'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
