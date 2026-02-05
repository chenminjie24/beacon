"""Optional FastAPI adapter for RelayService.

This module keeps imports local so core tests run without third-party dependencies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from relay.config import load_settings
from relay.domain.enums import Action, OrderStatus, OrderType
from relay.domain.exceptions import ConflictError, NotFoundError, RelayError, ValidationError
from relay.domain.models import HeartbeatCommand, OrderReportCommand, SignalCommand
from relay.repository.connection import create_psycopg_connection_factory
from relay.repository.memory import InMemoryRelayRepository
from relay.repository.postgres import PostgresRelayRepository
from relay.security.signature import MemoryReplayGuard, SignatureConfig, SignatureVerifier
from relay.services.relay_service import RelayService


def create_app() -> Any:
    try:
        from fastapi import FastAPI, Header, Request
        from fastapi.responses import JSONResponse
        from pydantic import BaseModel
    except ModuleNotFoundError as exc:
        raise RuntimeError("FastAPI extras are not installed. Run: pip install '.[api]'") from exc

    settings = load_settings()
    repository = _build_repository(settings.db_url)
    service = RelayService(repository=repository)
    signature = SignatureVerifier(
        SignatureConfig(api_key=settings.api_key, hmac_secret=settings.hmac_secret),
        replay_guard=MemoryReplayGuard(),
    )

    class SignalPayload(BaseModel):
        signal_id: str
        strategy_id: str
        account_id: str
        ts: datetime
        symbol: str
        action: Action
        order_type: OrderType
        qty: Decimal | None = None
        amount: Decimal | None = None
        target_pos: Decimal | None = None
        limit_price: Decimal | None = None
        max_slippage_bps: int = 20
        expire_at: datetime | None = None
        remark: str | None = None

    class AckPayload(BaseModel):
        agent_id: str
        lease_seconds: int = 30

    class OrderReportPayload(BaseModel):
        agent_id: str
        task_id: int
        lease_token: str
        client_order_id: str
        status: OrderStatus
        event_time: datetime
        qmt_order_id: str | None = None
        qty: Decimal | None = None
        filled_qty: Decimal | None = None
        avg_price: Decimal | None = None
        reason_code: str | None = None
        reason_msg: str | None = None

    class HeartbeatPayload(BaseModel):
        agent_id: str
        host: str
        version: str
        qmt_connected: bool
        now: datetime
        latency_ms: int | None = None

    app = FastAPI(title="Signal Relay API", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/signals")
    async def ingest_signal(
        payload: SignalPayload,
        request: Request,
        x_api_key: str = Header(alias="X-API-KEY"),
        x_timestamp: str = Header(alias="X-TIMESTAMP"),
        x_signature: str = Header(alias="X-SIGNATURE"),
        x_request_id: str = Header(alias="X-REQUEST-ID"),
    ) -> dict[str, Any]:
        raw = await request.body()
        _verify_request(
            signature=signature,
            headers={
                "X-API-KEY": x_api_key,
                "X-TIMESTAMP": x_timestamp,
                "X-SIGNATURE": x_signature,
                "X-REQUEST-ID": x_request_id,
            },
            method=request.method,
            path=str(request.url.path),
            body=raw,
        )

        cmd = SignalCommand(**payload.model_dump(), payload_raw=payload.model_dump(mode="json"))
        result = service.ingest_signal(cmd=cmd, now=datetime.now(tz=UTC), trace_id=x_request_id)
        return {"status": result.http_status, "signal_db_id": result.signal_db_id, "task_db_id": result.task_db_id}

    @app.get("/api/v1/tasks/pull")
    def pull_tasks(agent_id: str, limit: int = 10) -> dict[str, Any]:
        tasks = service.pull_tasks(agent_id=agent_id, limit=limit, now=datetime.now(tz=UTC))
        return {"tasks": [task.__dict__ for task in tasks]}

    @app.post("/api/v1/tasks/{task_id}/ack")
    def ack_task(task_id: int, payload: AckPayload) -> dict[str, Any]:
        result = service.ack_task(
            task_id=task_id,
            agent_id=payload.agent_id,
            lease_seconds=payload.lease_seconds,
            now=datetime.now(tz=UTC),
        )
        return {"task_id": result.task_id, "lease_token": result.lease_token, "lease_until": result.lease_until}

    @app.post("/api/v1/orders/report")
    def report_order(payload: OrderReportPayload) -> dict[str, Any]:
        cmd = OrderReportCommand(**payload.model_dump())
        status = service.report_order(cmd=cmd, now=datetime.now(tz=UTC))
        return {"status": status}

    @app.post("/api/v1/heartbeat")
    def heartbeat(payload: HeartbeatPayload) -> dict[str, str]:
        cmd = HeartbeatCommand(**payload.model_dump())
        status = service.report_heartbeat(cmd=cmd, now=datetime.now(tz=UTC))
        return {"status": status}

    @app.exception_handler(RelayError)
    async def relay_exception_handler(_, exc: RelayError) -> Any:
        if isinstance(exc, ValidationError):
            code = 400
        elif isinstance(exc, ConflictError):
            code = 409
        elif isinstance(exc, NotFoundError):
            code = 404
        else:
            code = 401
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    return app


def _verify_request(
    *,
    signature: SignatureVerifier,
    headers: dict[str, str],
    method: str,
    path: str,
    body: bytes,
) -> None:
    signature.verify(headers=headers, method=method, path=path, body=body, now=datetime.now(tz=UTC))


def _build_repository(db_url: str | None) -> Any:
    if db_url:
        return PostgresRelayRepository(connection_factory=create_psycopg_connection_factory(db_url))
    return InMemoryRelayRepository()
