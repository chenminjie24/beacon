from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.id_utils import prefixed_id
from app.models import (
    AlertLevel,
    DispatchTask,
    Order,
    OrderStatus,
    PlatformSource,
    RiskEvent,
    RiskRule,
    Signal,
    SignalStatus,
    Strategy,
    TaskAction,
)
from app.schemas import SignalPayloadV1, SignalWebhookResponse
from app.services.audit import create_alert, write_audit
from app.services.risk import check_risk
from app.services.signature import verify_webhook_signature

router = APIRouter(prefix='/signals', tags=['signals'])


@router.post('/webhook', response_model=SignalWebhookResponse)
async def receive_signal(
    request: Request,
    x_signature: str = Header(default=''),
    x_timestamp: str = Header(default=''),
    x_source: str = Header(default=''),
    db: Session = Depends(get_db),
) -> SignalWebhookResponse:
    body = await request.body()

    try:
        payload = SignalPayloadV1.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc

    source_name = x_source or payload.source_platform
    source = db.query(PlatformSource).filter(PlatformSource.name == source_name, PlatformSource.is_active.is_(True)).first()
    if not source:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='未知来源平台')

    verify_webhook_signature(body=body, timestamp=x_timestamp, signature=x_signature, secret=source.webhook_secret)

    duplicate = (
        db.query(Signal)
        .filter(Signal.source_platform == payload.source_platform, Signal.idempotency_key == payload.idempotency_key)
        .first()
    )
    if duplicate:
        return SignalWebhookResponse(accepted=True, signal_id=duplicate.id, duplicate=True)

    strategy = db.query(Strategy).filter(Strategy.id == payload.strategy_id).first()
    if not strategy:
        strategy = Strategy(
            id=payload.strategy_id,
            name=payload.strategy_id,
            account_id=payload.account_id,
            is_enabled=True,
        )
        db.add(strategy)
        # Ensure strategy row exists before inserting signal with FK.
        db.flush()

    signal = Signal(
        id=prefixed_id('sig'),
        source_platform=payload.source_platform,
        strategy_id=payload.strategy_id,
        account_id=payload.account_id,
        signal_type=payload.signal_type,
        idempotency_key=payload.idempotency_key,
        symbol=payload.symbol,
        side=payload.side,
        order_style=payload.order_style,
        quantity=payload.quantity,
        amount=payload.amount,
        target_position_ratio=payload.target_position_ratio,
        timestamp_ms=payload.timestamp_ms,
        extra=payload.extra,
        raw_payload=payload.model_dump(),
        status=SignalStatus.VERIFIED,
    )
    db.add(signal)
    db.flush()

    signal.status = SignalStatus.NORMALIZED

    rule = (
        db.query(RiskRule)
        .filter(RiskRule.strategy_id == payload.strategy_id, RiskRule.account_id == payload.account_id)
        .first()
    )

    now_utc = datetime.now(timezone.utc)
    passed, reason_code, reason_detail = check_risk(db, signal, rule, now_utc)
    if not passed:
        signal.status = SignalStatus.REJECTED_RISK
        signal.rejection_reason = reason_detail

        event = RiskEvent(
            id=prefixed_id('rsk'),
            signal_id=signal.id,
            rule_id=rule.id if rule else None,
            reason_code=reason_code or 'RISK_REJECTED',
            reason_detail=reason_detail or 'risk rejected',
        )
        db.add(event)
        create_alert(
            db,
            level=AlertLevel.ERROR,
            category='RISK_REJECTED',
            message=f'信号 {signal.id} 被风控拒绝',
            payload={'reason_code': reason_code, 'reason_detail': reason_detail},
        )
        write_audit(
            db,
            actor=payload.source_platform,
            action='SIGNAL_REJECTED_BY_RISK',
            resource_type='signal',
            resource_id=signal.id,
            detail={'reason_code': reason_code, 'reason_detail': reason_detail},
        )
        db.commit()
        return SignalWebhookResponse(accepted=True, signal_id=signal.id, duplicate=False)

    signal.status = SignalStatus.RISK_PASSED

    order = Order(
        id=prefixed_id('ord'),
        signal_id=signal.id,
        strategy_id=signal.strategy_id,
        account_id=signal.account_id,
        symbol=signal.symbol,
        side=signal.side,
        order_style=signal.order_style,
        quantity=signal.quantity,
        amount=signal.amount,
        status=OrderStatus.PENDING_SUBMIT,
    )
    db.add(order)
    db.flush()

    task_payload = {
        'strategy_id': signal.strategy_id,
        'symbol': signal.symbol,
        'side': signal.side.value,
        'order_style': signal.order_style.value,
        'quantity': signal.quantity,
        'amount': signal.amount,
        'target_position_ratio': signal.target_position_ratio,
        'signal_type': signal.signal_type.value,
        'extra': signal.extra,
    }
    task = DispatchTask(
        id=prefixed_id('tsk'),
        signal_id=signal.id,
        order_id=order.id,
        account_id=signal.account_id,
        action=TaskAction.PLACE_ORDER,
        payload=task_payload,
    )
    db.add(task)

    signal.status = SignalStatus.DISPATCHED
    write_audit(
        db,
        actor=payload.source_platform,
        action='SIGNAL_ACCEPTED',
        resource_type='signal',
        resource_id=signal.id,
        detail={'task_id': task.id, 'order_id': order.id},
    )

    db.commit()
    return SignalWebhookResponse(accepted=True, signal_id=signal.id, duplicate=False)
