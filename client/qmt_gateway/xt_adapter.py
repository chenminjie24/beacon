from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any


class XtAdapterUnavailable(RuntimeError):
    pass


class XtExecutionError(RuntimeError):
    pass


class XtNoopOrder(RuntimeError):
    pass


@dataclass
class XtInstruction:
    symbol: str
    side: str
    quantity: int
    price_type: int
    price: float


class _CallbackState:
    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._order_errors: deque[dict[str, Any]] = deque(maxlen=200)
        self._cancel_errors: deque[dict[str, Any]] = deque(maxlen=200)
        self._trades: deque[dict[str, Any]] = deque(maxlen=2000)
        self._lock = Lock()

    def push_order_error(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._order_errors.appendleft(data)

    def push_cancel_error(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._cancel_errors.appendleft(data)

    def push_trade(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._trades.append(data)

    def latest_order_error(self) -> dict[str, Any] | None:
        with self._lock:
            return self._order_errors[0] if self._order_errors else None

    def latest_cancel_error(self) -> dict[str, Any] | None:
        with self._lock:
            return self._cancel_errors[0] if self._cancel_errors else None

    def peek_trades(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._trades)

    def ack_trades(self, count: int) -> None:
        if count <= 0:
            return
        with self._lock:
            for _ in range(min(count, len(self._trades))):
                self._trades.popleft()


class XtQuantAdapter:
    def __init__(
        self,
        *,
        qmt_path: str,
        session_id: int,
        account_id: str,
        account_type: str,
        strategy_name: str,
        order_remark_prefix: str,
        logger: logging.Logger | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._strategy_name = strategy_name
        self._order_remark_prefix = order_remark_prefix[:16] if order_remark_prefix else 'qmt-gateway'

        if not qmt_path:
            raise XtAdapterUnavailable('缺少 qmt_path，无法连接 xtquant')
        if not account_id:
            raise XtAdapterUnavailable('缺少资金账号 account_id，无法连接 xtquant')

        try:
            from xtquant import xtconstant  # type: ignore
            from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback  # type: ignore
            from xtquant.xttype import StockAccount  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise XtAdapterUnavailable(f'xtquant 导入失败: {exc}') from exc

        self._xtconstant = xtconstant
        self._StockAccount = StockAccount

        callback_state = _CallbackState(self._logger)
        self._callback_state = callback_state

        class _TraderCallback(XtQuantTraderCallback):
            def on_disconnected(self):
                callback_state._logger.error('xtquant disconnected')

            def on_account_status(self, status):
                callback_state._logger.info(
                    'xtquant account status account=%s status=%s',
                    getattr(status, 'account_id', None),
                    getattr(status, 'status', None),
                )

            def on_stock_order(self, order):
                callback_state._logger.debug(
                    'xtquant on_stock_order id=%s status=%s msg=%s',
                    getattr(order, 'order_id', None),
                    getattr(order, 'order_status', None),
                    getattr(order, 'status_msg', None),
                )

            def on_stock_trade(self, trade):
                data = {
                    'broker_order_id': str(getattr(trade, 'order_id', '') or ''),
                    'broker_trade_id': str(getattr(trade, 'traded_id', '') or ''),
                    'price': float(getattr(trade, 'traded_price', 0) or 0),
                    'quantity': int(getattr(trade, 'traded_volume', 0) or 0),
                }
                callback_state.push_trade(data)
                callback_state._logger.info(
                    'xtquant on_stock_trade order_id=%s trade_id=%s price=%s volume=%s',
                    data['broker_order_id'],
                    data['broker_trade_id'],
                    data['price'],
                    data['quantity'],
                )

            def on_order_error(self, order_error):
                data = {
                    'order_id': getattr(order_error, 'order_id', None),
                    'error_id': getattr(order_error, 'error_id', None),
                    'error_msg': getattr(order_error, 'error_msg', None),
                }
                callback_state.push_order_error(data)
                callback_state._logger.error('xtquant on_order_error: %s', data)

            def on_cancel_error(self, cancel_error):
                data = {
                    'order_id': getattr(cancel_error, 'order_id', None),
                    'error_id': getattr(cancel_error, 'error_id', None),
                    'error_msg': getattr(cancel_error, 'error_msg', None),
                }
                callback_state.push_cancel_error(data)
                callback_state._logger.error('xtquant on_cancel_error: %s', data)

        self._callback = _TraderCallback()
        self._trader = XtQuantTrader(qmt_path, int(session_id))
        self._trader.register_callback(self._callback)
        self._trader.start()

        connect_result = self._trader.connect()
        if connect_result != 0:
            raise XtAdapterUnavailable(f'xtquant connect 失败，返回码: {connect_result}')

        self._account = self._StockAccount(account_id, account_type)
        subscribe_result = self._trader.subscribe(self._account)
        if subscribe_result != 0:
            raise XtAdapterUnavailable(f'xtquant subscribe 失败，返回码: {subscribe_result}')

        self._logger.info('xtquant connected. account_id=%s account_type=%s', account_id, account_type)

    def close(self) -> None:
        shutdown = getattr(self._trader, 'stop', None)
        if callable(shutdown):
            shutdown()

    def peek_trades(self) -> list[dict[str, Any]]:
        return self._callback_state.peek_trades()

    def ack_trades(self, count: int) -> None:
        self._callback_state.ack_trades(count)

    def place_order(self, payload: dict[str, Any]) -> tuple[str, str | None, str]:
        try:
            instruction = self._build_instruction(payload)
        except XtNoopOrder as exc:
            return 'CANCELED', None, str(exc)
        except XtExecutionError as exc:
            return 'REJECTED', None, str(exc)

        remark = self._make_order_remark(payload)

        order_type = self._order_type_from_side(instruction.side)
        if order_type is None:
            return 'REJECTED', None, f'不支持的 side: {instruction.side}'

        try:
            order_id = self._trader.order_stock(
                self._account,
                instruction.symbol,
                order_type,
                instruction.quantity,
                instruction.price_type,
                instruction.price,
                self._strategy_name,
                remark,
            )
        except Exception as exc:  # noqa: BLE001
            return 'FAILED', None, f'xtquant 下单异常: {exc}'

        if isinstance(order_id, int) and order_id > 0:
            return 'SUBMITTED', str(order_id), 'xtquant 下单成功'

        last_error = self._callback_state.latest_order_error()
        if last_error:
            msg = f"xtquant 下单失败: {last_error.get('error_id')} {last_error.get('error_msg')}"
        else:
            msg = f'xtquant 下单失败，返回 order_id={order_id}'
        return 'REJECTED', None, msg

    def cancel_order(self, payload: dict[str, Any]) -> tuple[str, str | None, str]:
        broker_order_id = payload.get('broker_order_id')
        symbol = str(payload.get('symbol') or '')
        if not broker_order_id:
            return 'FAILED', None, '缺少 broker_order_id，无法撤单'

        try:
            numeric_order_id = int(str(broker_order_id))
            result = self._trader.cancel_order_stock(self._account, numeric_order_id)
            if result == 0:
                return 'CANCELED', str(broker_order_id), 'xtquant 撤单成功'
            last_error = self._callback_state.latest_cancel_error()
            if last_error:
                return (
                    'FAILED',
                    str(broker_order_id),
                    f"xtquant 撤单失败: {last_error.get('error_id')} {last_error.get('error_msg')}",
                )
            return 'FAILED', str(broker_order_id), f'xtquant 撤单失败，返回码: {result}'
        except ValueError:
            market = self._market_from_symbol(symbol)
            if market is None:
                return 'FAILED', str(broker_order_id), f'无法从 symbol={symbol} 推断 market'
            try:
                result = self._trader.cancel_order_stock_sysid(self._account, market, str(broker_order_id))
            except Exception as exc:  # noqa: BLE001
                return 'FAILED', str(broker_order_id), f'xtquant 合同号撤单异常: {exc}'
            if result == 0:
                return 'CANCELED', str(broker_order_id), 'xtquant 撤单成功'
            return 'FAILED', str(broker_order_id), f'xtquant 合同号撤单失败，返回码: {result}'

    def _build_instruction(self, payload: dict[str, Any]) -> XtInstruction:
        signal_type = str(payload.get('signal_type') or 'INCREMENTAL_ORDER').upper()
        symbol = str(payload.get('symbol') or '').upper()
        if not symbol:
            raise XtExecutionError('缺少 symbol')

        if signal_type == 'TARGET_POSITION':
            side, quantity = self._resolve_target_position_delta(payload)
        else:
            side = str(payload.get('side') or 'BUY').upper()
            quantity = self._resolve_quantity(payload, side)

        order_style = str(payload.get('order_style') or 'MARKET').upper()
        price_type, price = self._resolve_price(order_style, payload)

        return XtInstruction(symbol=symbol, side=side, quantity=quantity, price_type=price_type, price=price)

    def _resolve_target_position_delta(self, payload: dict[str, Any]) -> tuple[str, int]:
        symbol = str(payload.get('symbol') or '').upper()
        target_ratio = payload.get('target_position_ratio')
        if target_ratio is None:
            raise XtExecutionError('TARGET_POSITION 缺少 target_position_ratio')

        ratio = float(target_ratio)
        if ratio < 0 or ratio > 1:
            raise XtExecutionError('target_position_ratio 必须在 [0, 1]')

        reference_price = self._reference_price(payload)
        if reference_price <= 0:
            raise XtExecutionError('TARGET_POSITION 需要 extra.reference_price > 0')

        asset = self._trader.query_stock_asset(self._account)
        if asset is None:
            raise XtExecutionError('无法查询账户资产，TARGET_POSITION 计算失败')

        total_asset = float(getattr(asset, 'total_asset', 0) or 0)
        if total_asset <= 0:
            raise XtExecutionError('账户 total_asset 无效，TARGET_POSITION 计算失败')

        current_qty = 0
        positions = self._trader.query_stock_positions(self._account) or []
        for pos in positions:
            if str(getattr(pos, 'stock_code', '')).upper() == symbol:
                current_qty = int(getattr(pos, 'volume', 0) or 0)
                break

        target_qty = int((total_asset * ratio) // reference_price)
        if target_qty < 0:
            target_qty = 0

        delta = target_qty - current_qty
        if delta == 0:
            raise XtNoopOrder(f'TARGET_POSITION 无需调仓，symbol={symbol} target={target_qty} current={current_qty}')

        if delta > 0:
            qty = self._normalize_buy_lot(delta)
            if qty <= 0:
                raise XtNoopOrder(f'TARGET_POSITION 买入股数不足一手，symbol={symbol} delta={delta}')
            return 'BUY', qty

        return 'SELL', abs(delta)

    def _resolve_quantity(self, payload: dict[str, Any], side: str) -> int:
        quantity = payload.get('quantity')
        if quantity is None:
            amount = payload.get('amount')
            reference_price = self._reference_price(payload)
            if amount is not None and reference_price > 0:
                quantity = int(float(amount) // reference_price)

        if quantity is None:
            raise XtExecutionError('缺少 quantity，且无法通过 amount/reference_price 推导')

        qty = int(quantity)
        if qty <= 0:
            raise XtExecutionError('quantity 必须 > 0')

        if side == 'BUY':
            qty = self._normalize_buy_lot(qty)
            if qty <= 0:
                raise XtExecutionError('买入数量不足一手（100）')

        return qty

    def _reference_price(self, payload: dict[str, Any]) -> float:
        extra = payload.get('extra', {}) or {}
        reference_price = extra.get('reference_price') or payload.get('price')
        try:
            return float(reference_price or 0)
        except Exception:  # noqa: BLE001
            return 0.0

    def _resolve_price(self, order_style: str, payload: dict[str, Any]) -> tuple[int, float]:
        market_price_type = getattr(self._xtconstant, 'LATEST_PRICE', None)
        fix_price_type = getattr(self._xtconstant, 'FIX_PRICE', 11)

        if order_style == 'LIMIT':
            limit_price = payload.get('price')
            if limit_price is None:
                limit_price = self._reference_price(payload)
            if limit_price is None or float(limit_price) <= 0:
                raise XtExecutionError('LIMIT 订单缺少有效价格（price/reference_price）')
            return fix_price_type, float(limit_price)

        if market_price_type is None:
            return fix_price_type, 0.0
        return market_price_type, 0.0

    def _order_type_from_side(self, side: str) -> int | None:
        side = side.upper()
        if side == 'BUY':
            return getattr(self._xtconstant, 'STOCK_BUY', None)
        if side == 'SELL':
            return getattr(self._xtconstant, 'STOCK_SELL', None)
        return None

    def _market_from_symbol(self, symbol: str) -> int | None:
        symbol = symbol.upper()
        if symbol.endswith('.SH'):
            return getattr(self._xtconstant, 'SH_MARKET', None)
        if symbol.endswith('.SZ'):
            return getattr(self._xtconstant, 'SZ_MARKET', None)
        if symbol.endswith('.BJ'):
            return getattr(self._xtconstant, 'MARKET_ENUM_BEIJING', None)
        return None

    def _normalize_buy_lot(self, qty: int) -> int:
        return (qty // 100) * 100

    def _make_order_remark(self, payload: dict[str, Any]) -> str:
        strategy = str(payload.get('strategy_id') or 'strategy')
        signal_type = str(payload.get('signal_type') or 'SIG')
        text = f'{self._order_remark_prefix}:{strategy}:{signal_type}'
        return text[:24]
