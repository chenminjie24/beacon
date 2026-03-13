from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from qmt_gateway.config import ClientSettings
from qmt_gateway.xt_adapter import XtAdapterUnavailable, XtQuantAdapter


@dataclass
class ExecutionResult:
    status: str
    broker_order_id: str | None
    message: str
    filled_quantity: int = 0
    avg_price: float = 0


class QmtExecutor:
    def __init__(self, *, secret_payload: dict, settings: ClientSettings):
        self.secret_payload = secret_payload
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self._broker_order_to_order_id: dict[str, str] = {}

        self._xt_adapter: XtQuantAdapter | None = None
        self._xt_enabled = False
        self._init_xt_adapter()

    @property
    def capabilities(self) -> list[str]:
        return ['ORDER', 'CANCEL']

    def shutdown(self) -> None:
        if self._xt_adapter:
            self._xt_adapter.close()

    def peek_trade_reports(self) -> list[dict[str, Any]]:
        if self._xt_enabled and self._xt_adapter:
            reports: list[dict[str, Any]] = []
            for trade in self._xt_adapter.peek_trades():
                item = dict(trade)
                broker_order_id = str(item.get('broker_order_id') or '').strip()
                if broker_order_id and broker_order_id in self._broker_order_to_order_id:
                    item['order_id'] = self._broker_order_to_order_id[broker_order_id]
                reports.append(item)
            return reports
        return []

    def ack_trade_reports(self, count: int) -> None:
        if self._xt_enabled and self._xt_adapter:
            self._xt_adapter.ack_trades(count)

    def execute(self, task: dict[str, Any]) -> ExecutionResult:
        action = task.get('action')
        payload = dict(task.get('payload', {}) or {})

        if action == 'CANCEL_ORDER':
            return self._cancel_order(payload)
        return self._place_order(payload)

    def _init_xt_adapter(self) -> None:
        mode = self.settings.execution_mode.strip().upper()
        if mode == 'MOCK_ONLY':
            self.logger.warning('execution_mode=MOCK_ONLY，跳过 xtquant 初始化')
            return

        qmt_path = str(self.secret_payload.get('qmt_path') or '').strip()
        account_id = str(self.secret_payload.get('qmt_account_id') or self.settings.account_id).strip()
        account_type = str(self.secret_payload.get('account_type') or self.settings.qmt_account_type).strip() or 'STOCK'
        strategy_name = str(self.secret_payload.get('strategy_name') or self.settings.qmt_strategy_name).strip() or 'qmt_gateway'
        remark_prefix = (
            str(self.secret_payload.get('order_remark_prefix') or self.settings.qmt_order_remark_prefix).strip() or 'qmtgw'
        )
        session_id = int(self.secret_payload.get('session_id') or self.settings.qmt_session_id)

        try:
            self._xt_adapter = XtQuantAdapter(
                qmt_path=qmt_path,
                session_id=session_id,
                account_id=account_id,
                account_type=account_type,
                strategy_name=strategy_name,
                order_remark_prefix=remark_prefix,
                logger=self.logger,
            )
            self._xt_enabled = True
        except XtAdapterUnavailable as exc:
            if mode == 'XT_ONLY':
                raise RuntimeError(f'XT_ONLY 模式下 xtquant 初始化失败: {exc}') from exc
            self._xt_enabled = False
            self._xt_adapter = None
            self.logger.warning('xtquant 不可用，回退 mock 模式: %s', exc)

    def _place_order(self, payload: dict[str, Any]) -> ExecutionResult:
        if self._xt_enabled and self._xt_adapter:
            status, broker_order_id, message = self._xt_adapter.place_order(payload)
            order_id = str(payload.get('order_id') or '').strip()
            if broker_order_id and order_id:
                self._broker_order_to_order_id[str(broker_order_id)] = order_id
            return ExecutionResult(status=status, broker_order_id=broker_order_id, message=message)

        return ExecutionResult(
            status='SUBMITTED',
            broker_order_id=f"mock_{payload.get('symbol', 'UNKNOWN')}",
            message='mock submitted',
        )

    def _cancel_order(self, payload: dict[str, Any]) -> ExecutionResult:
        if self._xt_enabled and self._xt_adapter:
            status, broker_order_id, message = self._xt_adapter.cancel_order(payload)
            return ExecutionResult(status=status, broker_order_id=broker_order_id, message=message)

        return ExecutionResult(
            status='CANCELED',
            broker_order_id=payload.get('broker_order_id'),
            message='mock canceled',
        )
