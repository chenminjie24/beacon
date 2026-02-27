from __future__ import annotations

from dataclasses import dataclass

import requests


@dataclass
class ServerClient:
    base_url: str
    shared_token: str

    def _headers(self) -> dict[str, str]:
        return {
            'Content-Type': 'application/json',
            'X-Client-Token': self.shared_token,
        }

    def heartbeat(self, *, client_id: str, account_id: str, version: str, capabilities: list[str], last_error: str | None) -> None:
        payload = {
            'client_id': client_id,
            'account_id': account_id,
            'version': version,
            'capabilities': capabilities,
            'last_error': last_error,
        }
        requests.post(f'{self.base_url}/client/heartbeat', headers=self._headers(), json=payload, timeout=8).raise_for_status()

    def claim_tasks(self, *, client_id: str, account_id: str, version: str, capabilities: list[str], max_tasks: int = 20) -> list[dict]:
        payload = {
            'client_id': client_id,
            'account_id': account_id,
            'version': version,
            'capabilities': capabilities,
            'max_tasks': max_tasks,
        }
        resp = requests.post(f'{self.base_url}/client/tasks/claim', headers=self._headers(), json=payload, timeout=12)
        resp.raise_for_status()
        return resp.json().get('tasks', [])

    def report_task(
        self,
        *,
        task_id: str,
        client_id: str,
        status: str,
        broker_order_id: str | None,
        message: str | None,
        filled_quantity: int = 0,
        avg_price: float = 0,
    ) -> None:
        payload = {
            'client_id': client_id,
            'status': status,
            'broker_order_id': broker_order_id,
            'message': message,
            'filled_quantity': filled_quantity,
            'avg_price': avg_price,
        }
        requests.post(f'{self.base_url}/client/tasks/{task_id}/report', headers=self._headers(), json=payload, timeout=10).raise_for_status()

    def report_trade(self, payload: dict) -> None:
        requests.post(f'{self.base_url}/client/trades/report', headers=self._headers(), json=payload, timeout=10).raise_for_status()
