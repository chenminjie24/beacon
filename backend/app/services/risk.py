from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Order, RiskRule, Side, Signal

SH_TZ = ZoneInfo('Asia/Shanghai')
settings = get_settings()


def is_cn_stock_trading_time(now_utc: datetime) -> bool:
    local = now_utc.astimezone(SH_TZ)
    if local.weekday() >= 5:
        return False
    t = local.time()
    morning = time(9, 30) <= t <= time(11, 30)
    afternoon = time(13, 0) <= t <= time(15, 0)
    return morning or afternoon


def estimate_amount(signal: Signal) -> float:
    if signal.amount is not None:
        return float(signal.amount)
    if signal.quantity is not None and signal.extra.get('reference_price'):
        return signal.quantity * float(signal.extra['reference_price'])
    return 0.0


def check_risk(db: Session, signal: Signal, rule: RiskRule | None, now_utc: datetime) -> tuple[bool, str | None, str | None]:
    if not settings.bypass_trading_time_check and not is_cn_stock_trading_time(now_utc):
        return False, 'TRADING_TIME', '不在交易时段内'

    if not rule or not rule.is_active:
        return True, None, None

    if rule.blacklist and signal.symbol in rule.blacklist:
        return False, 'BLACKLIST', f'{signal.symbol} 在黑名单内'

    if rule.whitelist and signal.symbol not in rule.whitelist:
        return False, 'WHITELIST', f'{signal.symbol} 不在白名单内'

    if signal.quantity is not None:
        if signal.quantity > rule.max_single_quantity:
            return False, 'MAX_SINGLE_QTY', f'数量 {signal.quantity} 超过上限 {rule.max_single_quantity}'
        if signal.side == Side.BUY and signal.quantity % max(rule.min_lot_size, 1) != 0:
            return False, 'LOT_SIZE', f'买入数量必须为 {rule.min_lot_size} 的整数倍'

    amount = estimate_amount(signal)
    if amount > 0 and amount < rule.min_order_amount:
        return False, 'MIN_ORDER_AMOUNT', f'金额 {amount} 小于最小金额 {rule.min_order_amount}'

    if amount > rule.max_single_amount:
        return False, 'MAX_SINGLE_AMOUNT', f'金额 {amount} 超过单笔上限 {rule.max_single_amount}'

    if amount > 0:
        local_day = now_utc.astimezone(SH_TZ).date()
        start = datetime.combine(local_day, time.min, tzinfo=SH_TZ).astimezone(now_utc.tzinfo)
        end = datetime.combine(local_day, time.max, tzinfo=SH_TZ).astimezone(now_utc.tzinfo)
        day_sum = (
            db.query(func.coalesce(func.sum(Order.amount), 0.0))
            .filter(
                Order.account_id == signal.account_id,
                Order.strategy_id == signal.strategy_id,
                Order.created_at >= start,
                Order.created_at <= end,
            )
            .scalar()
        )
        if float(day_sum or 0.0) + amount > rule.daily_max_amount:
            return (
                False,
                'DAILY_MAX_AMOUNT',
                f'当日累计 {(float(day_sum or 0.0) + amount):.2f} 超过上限 {rule.daily_max_amount}',
            )

    return True, None, None
