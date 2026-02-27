from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.id_utils import prefixed_id
from app.models import (
    Alert,
    AlertLevel,
    AlertStatus,
    AuditLog,
    Client,
    ClientStatus,
    DispatchTask,
    Order,
    OrderStatus,
    PositionSnapshot,
    RiskRule,
    Signal,
    TaskAction,
    TaskStatus,
    User,
)
from app.schemas import (
    AlertOut,
    AuditLogOut,
    CancelOrderResponse,
    ClientOut,
    DashboardMetrics,
    OrderOut,
    PositionOut,
    RiskRuleUpdateRequest,
    SignalOut,
)
from app.services.audit import create_alert, write_audit

router = APIRouter(tags=['admin'])
settings = get_settings()


def _mark_offline_clients(db: Session) -> None:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.offline_threshold_seconds)
    stale = db.query(Client).filter(Client.last_heartbeat_at < threshold).all()
    for client in stale:
        if client.status != ClientStatus.OFFLINE:
            client.status = ClientStatus.OFFLINE
            create_alert(
                db,
                level=AlertLevel.WARN,
                category='CLIENT_OFFLINE',
                message=f'客户端 {client.id} 离线',
                payload={'client_id': client.id},
            )


@router.get('/signals', response_model=list[SignalOut])
def list_signals(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SignalOut]:
    rows = db.query(Signal).order_by(Signal.created_at.desc()).limit(limit).all()
    return [SignalOut.model_validate(r, from_attributes=True) for r in rows]


@router.get('/orders', response_model=list[OrderOut])
def list_orders(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[OrderOut]:
    rows = db.query(Order).order_by(Order.created_at.desc()).limit(limit).all()
    return [OrderOut.model_validate(r, from_attributes=True) for r in rows]


@router.get('/positions', response_model=list[PositionOut])
def list_positions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PositionOut]:
    rows = db.query(PositionSnapshot).order_by(PositionSnapshot.snapshot_at.desc()).limit(500).all()
    return [PositionOut.model_validate(r, from_attributes=True) for r in rows]


@router.get('/clients', response_model=list[ClientOut])
def list_clients(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ClientOut]:
    _mark_offline_clients(db)
    db.commit()
    rows = db.query(Client).order_by(Client.last_heartbeat_at.desc()).all()
    return [ClientOut.model_validate(r, from_attributes=True) for r in rows]


@router.get('/alerts', response_model=list[AlertOut])
def list_alerts(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AlertOut]:
    rows = db.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()
    return [AlertOut.model_validate(r, from_attributes=True) for r in rows]


@router.get('/audit-logs', response_model=list[AuditLogOut])
def list_audit_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AuditLogOut]:
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [AuditLogOut.model_validate(r, from_attributes=True) for r in rows]


@router.get('/risk-rules')
def list_risk_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    rows = db.query(RiskRule).all()
    return [
        {
            'id': r.id,
            'strategy_id': r.strategy_id,
            'account_id': r.account_id,
            'max_single_amount': r.max_single_amount,
            'max_single_quantity': r.max_single_quantity,
            'daily_max_amount': r.daily_max_amount,
            'min_order_amount': r.min_order_amount,
            'min_lot_size': r.min_lot_size,
            'whitelist': r.whitelist,
            'blacklist': r.blacklist,
            'is_active': r.is_active,
        }
        for r in rows
    ]


@router.put('/risk-rules/{rule_id}')
def update_risk_rule(
    rule_id: str,
    payload: RiskRuleUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    rule = db.query(RiskRule).filter(RiskRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='风控规则不存在')

    for field, value in payload.model_dump().items():
        setattr(rule, field, value)

    write_audit(
        db,
        actor=user.username,
        action='RISK_RULE_UPDATED',
        resource_type='risk_rule',
        resource_id=rule.id,
        detail=payload.model_dump(),
    )
    db.commit()
    return {'ok': True}


@router.post('/orders/{order_id}/cancel', response_model=CancelOrderResponse)
def cancel_order(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CancelOrderResponse:
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='订单不存在')
    if order.status in {OrderStatus.FILLED, OrderStatus.CANCELED}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='当前状态不可撤单')

    task = DispatchTask(
        id=prefixed_id('tsk'),
        signal_id=order.signal_id,
        order_id=order.id,
        account_id=order.account_id,
        action=TaskAction.CANCEL_ORDER,
        payload={
            'order_id': order.id,
            'broker_order_id': order.broker_order_id,
            'symbol': order.symbol,
        },
        status=TaskStatus.PENDING,
    )
    db.add(task)
    order.status = OrderStatus.CANCEL_PENDING

    write_audit(
        db,
        actor=user.username,
        action='ORDER_CANCEL_REQUESTED',
        resource_type='order',
        resource_id=order.id,
        detail={'task_id': task.id},
    )

    db.commit()
    return CancelOrderResponse(accepted=True, task_id=task.id)


@router.get('/dashboard/metrics', response_model=DashboardMetrics)
def dashboard_metrics(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DashboardMetrics:
    _mark_offline_clients(db)
    db.commit()

    now = datetime.now(timezone.utc)
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    today_signals = db.query(func.count(Signal.id)).filter(Signal.created_at >= day_start).scalar() or 0
    success_orders = (
        db.query(func.count(Order.id))
        .filter(Order.created_at >= day_start, Order.status.in_([OrderStatus.FILLED, OrderStatus.SUBMITTED]))
        .scalar()
        or 0
    )
    failed_orders = (
        db.query(func.count(Order.id))
        .filter(Order.created_at >= day_start, Order.status.in_([OrderStatus.FAILED, OrderStatus.REJECTED]))
        .scalar()
        or 0
    )
    online_clients = db.query(func.count(Client.id)).filter(Client.status == ClientStatus.ONLINE).scalar() or 0
    open_alerts = db.query(func.count(Alert.id)).filter(Alert.status == AlertStatus.OPEN).scalar() or 0

    return DashboardMetrics(
        today_signals=today_signals,
        success_orders=success_orders,
        failed_orders=failed_orders,
        online_clients=online_clients,
        open_alerts=open_alerts,
    )
