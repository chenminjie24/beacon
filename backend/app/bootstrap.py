from sqlalchemy.orm import Session

from app.config import get_settings
from app.id_utils import prefixed_id
from app.models import PlatformSource, RiskRule, Strategy, User
from app.security import get_password_hash

settings = get_settings()


def ensure_seed_data(db: Session) -> None:
    if not db.query(User).filter(User.username == settings.admin_username).first():
        db.add(
            User(
                id=prefixed_id('usr'),
                username=settings.admin_username,
                password_hash=get_password_hash(settings.admin_password),
                is_active=True,
            )
        )

    if not db.query(PlatformSource).filter(PlatformSource.name == 'joinquant').first():
        db.add(
            PlatformSource(
                id=prefixed_id('src'),
                name='joinquant',
                webhook_secret=settings.default_webhook_secret,
                is_active=True,
            )
        )

    if not db.query(Strategy).filter(Strategy.id == 'default_strategy').first():
        db.add(
            Strategy(
                id='default_strategy',
                name='default_strategy',
                account_id='acc_stock_main',
                is_enabled=True,
            )
        )

    if not db.query(RiskRule).filter(RiskRule.strategy_id == 'default_strategy').first():
        db.add(
            RiskRule(
                id=prefixed_id('rrl'),
                strategy_id='default_strategy',
                account_id='acc_stock_main',
                max_single_amount=50000,
                max_single_quantity=100000,
                daily_max_amount=200000,
                min_order_amount=100,
                min_lot_size=100,
                whitelist=[],
                blacklist=[],
                is_active=True,
            )
        )
