from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import verify_client_token
from app.id_utils import prefixed_id
from app.models import (
    AlertLevel,
    Client,
    ClientStatus,
    DispatchTask,
    Order,
    OrderStatus,
    PositionSnapshot,
    Signal,
    SignalStatus,
    TaskStatus,
    Trade,
)
from app.schemas import (
    ClaimTasksRequest,
    ClaimTasksResponse,
    HeartbeatRequest,
    TaskPayload,
    TaskReportRequest,
    TradeReportRequest,
)
from app.services.audit import create_alert

router = APIRouter(prefix='/client', tags=['client'])
settings = get_settings()


def _to_signal_status(order_status: OrderStatus) -> SignalStatus:
    mapping = {
        OrderStatus.SUBMITTED: SignalStatus.EXECUTING,
        OrderStatus.PARTIAL_FILLED: SignalStatus.PARTIAL_FILLED,
        OrderStatus.FILLED: SignalStatus.COMPLETED,
        OrderStatus.CANCELED: SignalStatus.COMPLETED,
        OrderStatus.REJECTED: SignalStatus.FAILED_EXECUTION,
        OrderStatus.FAILED: SignalStatus.FAILED_EXECUTION,
        OrderStatus.CANCEL_PENDING: SignalStatus.EXECUTING,
    }
    return mapping.get(order_status, SignalStatus.EXECUTING)


def _refresh_client_status(db: Session) -> None:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.offline_threshold_seconds)
    stale_clients = db.query(Client).filter(Client.last_heartbeat_at < threshold).all()
    for cli in stale_clients:
        if cli.status != ClientStatus.OFFLINE:
            cli.status = ClientStatus.OFFLINE
            create_alert(
                db,
                level=AlertLevel.WARN,
                category='CLIENT_OFFLINE',
                message=f'客户端 {cli.id} 离线',
                payload={'client_id': cli.id, 'last_heartbeat_at': cli.last_heartbeat_at.isoformat()},
            )


@router.post('/heartbeat', dependencies=[Depends(verify_client_token)])
def heartbeat(payload: HeartbeatRequest, db: Session = Depends(get_db)) -> dict:
    client = db.query(Client).filter(Client.id == payload.client_id).first()
    now = datetime.now(timezone.utc)
    if not client:
        client = Client(
            id=payload.client_id,
            account_id=payload.account_id,
            capabilities=payload.capabilities,
            version=payload.version,
            status=ClientStatus.ONLINE,
            last_heartbeat_at=now,
            last_error=payload.last_error,
        )
        db.add(client)
    else:
        client.account_id = payload.account_id
        client.capabilities = payload.capabilities
        client.version = payload.version
        client.status = ClientStatus.ONLINE
        client.last_heartbeat_at = now
        client.last_error = payload.last_error

    _refresh_client_status(db)
    db.commit()
    return {'ok': True}


@router.post('/tasks/claim', response_model=ClaimTasksResponse, dependencies=[Depends(verify_client_token)])
def claim_tasks(payload: ClaimTasksRequest, db: Session = Depends(get_db)) -> ClaimTasksResponse:
    now = datetime.now(timezone.utc)
    expired = db.query(DispatchTask).filter(
        DispatchTask.status == TaskStatus.CLAIMED,
        DispatchTask.expire_at.is_not(None),
        DispatchTask.expire_at < now,
    )
    expired.update(
        {
            DispatchTask.status: TaskStatus.PENDING,
            DispatchTask.claimed_by: None,
            DispatchTask.claimed_at: None,
            DispatchTask.expire_at: None,
        },
        synchronize_session=False,
    )

    tasks_query = (
        db.query(DispatchTask)
        .filter(
            and_(
                DispatchTask.status == TaskStatus.PENDING,
                DispatchTask.account_id == payload.account_id,
                DispatchTask.available_at <= now,
            )
        )
        .order_by(DispatchTask.created_at.asc())
        .limit(max(min(payload.max_tasks, 100), 1))
    )
    if db.bind is not None and db.bind.dialect.name == 'postgresql':
        tasks_query = tasks_query.with_for_update(skip_locked=True)
    tasks = tasks_query.all()

    claimed_tasks: list[TaskPayload] = []
    expire_at = now + timedelta(seconds=settings.claim_ttl_seconds)
    for task in tasks:
        task.status = TaskStatus.CLAIMED
        task.claimed_by = payload.client_id
        task.claimed_at = now
        task.expire_at = expire_at

        signal = db.query(Signal).filter(Signal.id == task.signal_id).first()
        if signal and signal.status == SignalStatus.DISPATCHED:
            signal.status = SignalStatus.EXECUTING

        claimed_tasks.append(
            TaskPayload(
                task_id=task.id,
                signal_id=task.signal_id,
                action=task.action,
                payload=task.payload,
                expire_at=task.expire_at,
            )
        )

    client = db.query(Client).filter(Client.id == payload.client_id).first()
    if not client:
        client = Client(
            id=payload.client_id,
            account_id=payload.account_id,
            status=ClientStatus.ONLINE,
            capabilities=payload.capabilities,
            version=payload.version,
            last_heartbeat_at=now,
        )
        db.add(client)
    else:
        client.last_heartbeat_at = now
        client.status = ClientStatus.ONLINE

    _refresh_client_status(db)
    db.commit()
    return ClaimTasksResponse(tasks=claimed_tasks)


@router.post('/tasks/{task_id}/report', dependencies=[Depends(verify_client_token)])
def report_task(task_id: str, payload: TaskReportRequest, db: Session = Depends(get_db)) -> dict:
    task = db.query(DispatchTask).filter(DispatchTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='任务不存在')
    if task.claimed_by != payload.client_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='任务不属于当前客户端')
    if task.status != TaskStatus.CLAIMED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='任务当前状态不可回报')

    order = db.query(Order).filter(Order.id == task.order_id).first()
    signal = db.query(Signal).filter(Signal.id == task.signal_id).first()

    task.status = TaskStatus.ACKED if payload.status not in {OrderStatus.FAILED, OrderStatus.REJECTED} else TaskStatus.FAILED
    task.updated_at = datetime.now(timezone.utc)

    if order:
        order.status = payload.status
        order.broker_order_id = payload.broker_order_id
        order.last_message = payload.message
        order.filled_quantity = payload.filled_quantity
        order.avg_price = payload.avg_price

    if signal:
        signal.status = _to_signal_status(payload.status)

    if payload.status in {OrderStatus.FAILED, OrderStatus.REJECTED}:
        create_alert(
            db,
            level=AlertLevel.ERROR,
            category='ORDER_FAILED',
            message=f'任务 {task_id} 下单失败',
            payload={'task_id': task_id, 'order_id': task.order_id, 'message': payload.message},
        )

    db.commit()
    return {'ok': True}


@router.post('/trades/report', dependencies=[Depends(verify_client_token)])
def report_trade(payload: TradeReportRequest, db: Session = Depends(get_db)) -> dict:
    order = None
    if payload.order_id:
        order = db.query(Order).filter(Order.id == payload.order_id).first()
    elif payload.broker_order_id:
        client = db.query(Client).filter(Client.id == payload.client_id).first()
        if not client:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='客户端不存在')
        order = (
            db.query(Order)
            .filter(
                Order.account_id == client.account_id,
                Order.broker_order_id == payload.broker_order_id,
            )
            .first()
        )
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='订单不存在')

    duplicated = (
        db.query(Trade)
        .filter(
            Trade.order_id == order.id,
            Trade.broker_trade_id == payload.broker_trade_id,
        )
        .first()
    )
    if duplicated:
        return {'ok': True}

    trade = Trade(
        id=prefixed_id('trd'),
        order_id=order.id,
        broker_trade_id=payload.broker_trade_id,
        symbol=payload.symbol or order.symbol,
        side=payload.side or order.side,
        quantity=payload.quantity,
        price=payload.price,
        traded_at=payload.traded_at or datetime.now(timezone.utc),
    )
    db.add(trade)

    order.filled_quantity += payload.quantity
    if order.quantity and order.filled_quantity >= order.quantity:
        order.status = OrderStatus.FILLED
    else:
        order.status = OrderStatus.PARTIAL_FILLED

    signal = db.query(Signal).filter(Signal.id == order.signal_id).first()
    if signal:
        signal.status = _to_signal_status(order.status)

    latest_position = (
        db.query(PositionSnapshot)
        .filter(PositionSnapshot.account_id == order.account_id, PositionSnapshot.symbol == trade.symbol)
        .order_by(PositionSnapshot.snapshot_at.desc())
        .first()
    )
    base_qty = latest_position.quantity if latest_position else 0
    delta = payload.quantity if trade.side.value == 'BUY' else -payload.quantity
    new_qty = max(base_qty + delta, 0)
    position = PositionSnapshot(
        id=prefixed_id('pos'),
        account_id=order.account_id,
        symbol=trade.symbol,
        quantity=new_qty,
        available_quantity=new_qty,
        avg_cost=payload.price if new_qty > 0 else 0,
        market_value=payload.price * new_qty,
    )
    db.add(position)

    db.commit()
    return {'ok': True}
