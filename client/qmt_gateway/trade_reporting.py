from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def report_trade_callbacks(
    *,
    api: Any,
    executor: Any,
    client_id: str,
    last_error: dict[str, str | None],
) -> None:
    acked = 0
    for trade in executor.peek_trade_reports():
        order_id = str(trade.get('order_id') or '').strip()
        broker_order_id = str(trade.get('broker_order_id') or '').strip()
        broker_trade_id = str(trade.get('broker_trade_id') or '').strip()
        quantity = int(trade.get('quantity', 0) or 0)
        price = float(trade.get('price', 0) or 0)
        if not broker_order_id or not broker_trade_id or quantity <= 0:
            logger.warning('skip invalid trade callback: %s', trade)
            acked += 1
            continue
        try:
            api.report_trade(
                {
                    'client_id': client_id,
                    'order_id': order_id or None,
                    'broker_order_id': broker_order_id,
                    'broker_trade_id': broker_trade_id,
                    'quantity': quantity,
                    'price': price,
                }
            )
            last_error['msg'] = None
            acked += 1
        except Exception as exc:
            last_error['msg'] = str(exc)
            logger.exception('trade report failed: %s trade=%s', exc, trade)
            break

    executor.ack_trade_reports(acked)
