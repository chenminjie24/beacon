from __future__ import annotations

import logging
import threading
import time

from qmt_gateway.api_client import ServerClient
from qmt_gateway.config import ClientSettings
from qmt_gateway.executor import QmtExecutor
from qmt_gateway.secret_store import load_secret_file
from qmt_gateway.trade_reporting import report_trade_callbacks

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
)
logger = logging.getLogger(__name__)


def run() -> None:
    settings = ClientSettings()
    secrets = load_secret_file(settings.secret_path)

    api = ServerClient(base_url=settings.server_base_url, shared_token=settings.client_token)
    executor = QmtExecutor(secret_payload=secrets, settings=settings)

    stop_event = threading.Event()
    last_error = {'msg': None}

    def heartbeat_loop() -> None:
        while not stop_event.is_set():
            try:
                api.heartbeat(
                    client_id=settings.client_id,
                    account_id=settings.account_id,
                    version=settings.client_version,
                    capabilities=executor.capabilities,
                    last_error=last_error['msg'],
                )
            except Exception as exc:
                logger.exception('heartbeat failed: %s', exc)
            stop_event.wait(settings.heartbeat_interval_seconds)

    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()

    logger.info('QMT client started. client_id=%s account_id=%s', settings.client_id, settings.account_id)

    try:
        while True:
            tasks = api.claim_tasks(
                client_id=settings.client_id,
                account_id=settings.account_id,
                version=settings.client_version,
                capabilities=executor.capabilities,
                max_tasks=20,
            )

            if tasks:
                logger.info('claimed %s tasks', len(tasks))
                for task in tasks:
                    payload = dict(task.get('payload', {}) or {})
                    logger.info(
                        'task claimed. task_id=%s signal_id=%s action=%s strategy_id=%s symbol=%s side=%s quantity=%s',
                        task.get('task_id'),
                        task.get('signal_id'),
                        task.get('action'),
                        payload.get('strategy_id'),
                        payload.get('symbol'),
                        payload.get('side'),
                        payload.get('quantity'),
                    )

            for task in tasks:
                try:
                    result = executor.execute(task)
                    api.report_task(
                        task_id=task['task_id'],
                        client_id=settings.client_id,
                        status=result.status,
                        broker_order_id=result.broker_order_id,
                        message=result.message,
                        filled_quantity=result.filled_quantity,
                        avg_price=result.avg_price,
                    )
                    last_error['msg'] = None
                except Exception as exc:
                    last_error['msg'] = str(exc)
                    logger.exception('task failed: %s', exc)
                    api.report_task(
                        task_id=task['task_id'],
                        client_id=settings.client_id,
                        status='FAILED',
                        broker_order_id=None,
                        message=str(exc),
                    )

            report_trade_callbacks(
                api=api,
                executor=executor,
                client_id=settings.client_id,
                last_error=last_error,
            )

            time.sleep(settings.poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info('stopped by keyboard interrupt')
    finally:
        stop_event.set()
        thread.join(timeout=2)
        executor.shutdown()


if __name__ == '__main__':
    run()
