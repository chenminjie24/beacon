"""HTTP relay client using stdlib urllib."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any
from urllib import error, parse, request
import uuid

from relay.domain.models import AckResult, OrderReportCommand, PulledTask
from relay.security.signature import build_signature


class RelayClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class RelayClientConfig:
    base_url: str
    api_key: str
    hmac_secret: str
    timeout_seconds: int = 10


class HttpRelayClient:
    """Minimal relay API client with HMAC signature headers."""

    def __init__(self, config: RelayClientConfig) -> None:
        self._config = config

    def pull_tasks(self, *, agent_id: str, limit: int) -> list[PulledTask]:
        data = self._request(
            method="GET",
            path="/api/v1/tasks/pull",
            query={"agent_id": agent_id, "limit": str(limit)},
            body=None,
        )
        return [PulledTask(**item) for item in data.get("tasks", [])]

    def ack_task(self, *, task_id: int, agent_id: str, lease_seconds: int) -> AckResult:
        payload = {"agent_id": agent_id, "lease_seconds": lease_seconds}
        data = self._request(
            method="POST",
            path=f"/api/v1/tasks/{task_id}/ack",
            query=None,
            body=payload,
        )
        return AckResult(
            task_id=data["task_id"],
            lease_token=data["lease_token"],
            lease_until=datetime.fromisoformat(data["lease_until"]),
        )

    def report_order(self, report: OrderReportCommand) -> None:
        payload = _report_payload(report)
        self._request(method="POST", path="/api/v1/orders/report", query=None, body=payload)

    def heartbeat(self, *, agent_id: str, host: str, version: str, qmt_connected: bool, latency_ms: int | None) -> None:
        payload = {
            "agent_id": agent_id,
            "host": host,
            "version": version,
            "qmt_connected": qmt_connected,
            "latency_ms": latency_ms,
            "now": datetime.now(tz=UTC).isoformat(),
        }
        self._request(method="POST", path="/api/v1/heartbeat", query=None, body=payload)

    def _request(self, *, method: str, path: str, query: dict[str, str] | None, body: dict[str, Any] | None) -> Any:
        url = self._config.base_url.rstrip("/") + path
        if query:
            url += "?" + parse.urlencode(query)
        body_bytes = b""
        if body is not None:
            body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        request_id = str(uuid.uuid4())
        timestamp = str(int(datetime.now(tz=UTC).timestamp()))
        signature = build_signature(
            secret=self._config.hmac_secret,
            timestamp=timestamp,
            request_id=request_id,
            method=method,
            path=path,
            body=body_bytes,
        )

        headers = {
            "X-API-KEY": self._config.api_key,
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": signature,
            "X-REQUEST-ID": request_id,
            "Content-Type": "application/json",
        }

        req = request.Request(url, method=method, data=body_bytes or None, headers=headers)
        try:
            with request.urlopen(req, timeout=self._config.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8") if exc.fp else str(exc)
            raise RelayClientError(f"relay http error {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RelayClientError(f"relay connection error: {exc.reason}") from exc

        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RelayClientError("invalid json response") from exc


def _report_payload(report: OrderReportCommand) -> dict[str, Any]:
    payload = {
        "agent_id": report.agent_id,
        "task_id": report.task_id,
        "lease_token": report.lease_token,
        "client_order_id": report.client_order_id,
        "status": report.status.value,
        "event_time": report.event_time.isoformat(),
        "qmt_order_id": report.qmt_order_id,
        "reason_code": report.reason_code,
        "reason_msg": report.reason_msg,
    }
    if report.qty is not None:
        payload["qty"] = str(report.qty)
    if report.filled_qty is not None:
        payload["filled_qty"] = str(report.filled_qty)
    if report.avg_price is not None:
        payload["avg_price"] = str(report.avg_price)
    return payload
