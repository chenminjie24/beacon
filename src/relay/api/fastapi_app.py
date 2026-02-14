"""Optional FastAPI adapter for RelayService.

This module keeps imports local so core tests run without third-party dependencies.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from relay.config import load_settings
from relay.domain.enums import Action, OrderStatus, OrderType
from relay.domain.exceptions import ConflictError, NotFoundError, RelayError, ValidationError
from relay.domain.models import HeartbeatCommand, OrderReportCommand, SignalCommand, SignalRecord
from relay.repository.connection import create_psycopg_connection_factory
from relay.repository.memory import InMemoryRelayRepository
from relay.repository.postgres import PostgresRelayRepository
from relay.security.signature import MemoryReplayGuard, SignatureConfig, SignatureVerifier
from relay.services.relay_service import RelayService


def create_app() -> Any:
    try:
        from fastapi import Depends, FastAPI, Header, Request
        from fastapi.responses import JSONResponse
        from pydantic import BaseModel
    except ModuleNotFoundError as exc:
        raise RuntimeError("FastAPI extras are not installed. Run: pip install '.[api]'") from exc

    settings = load_settings()
    repository = _build_repository(settings.db_url)
    service = RelayService(repository=repository)
    signature = SignatureVerifier(
        SignatureConfig(api_key=settings.api_key, hmac_secret=settings.hmac_secret),
        replay_guard=_build_replay_guard(settings.db_url),
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

    @app.get("/admin")
    def admin_page() -> Any:
        return _render_admin_page()

    @app.get("/admin/api/signals")
    def admin_signals(
        q: str | None = None,
        action: Action | None = None,
        order_type: OrderType | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        items = repository.list_signals(
            limit=limit,
            offset=offset,
            query=q,
            action=action,
            order_type=order_type,
            since=since,
            until=until,
        )
        return {
            "items": [_signal_to_dict(item) for item in items],
            "count": len(items),
            "limit": limit,
            "offset": offset,
        }

    async def require_signature(
        request: Request,
        x_api_key: str = Header(alias="X-API-KEY"),
        x_timestamp: str = Header(alias="X-TIMESTAMP"),
        x_signature: str = Header(alias="X-SIGNATURE"),
        x_request_id: str = Header(alias="X-REQUEST-ID"),
    ) -> None:
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

    @app.post("/api/v1/signals")
    async def ingest_signal(
        payload: SignalPayload,
        x_request_id: str = Header(alias="X-REQUEST-ID"),
        _: None = Depends(require_signature),
    ) -> dict[str, Any]:
        cmd = SignalCommand(**payload.model_dump(), payload_raw=payload.model_dump(mode="json"))
        result = service.ingest_signal(cmd=cmd, now=datetime.now(tz=UTC), trace_id=x_request_id)
        return {"status": result.http_status, "signal_db_id": result.signal_db_id, "task_db_id": result.task_db_id}

    @app.get("/api/v1/tasks/pull")
    def pull_tasks(agent_id: str, limit: int = 10, _: None = Depends(require_signature)) -> dict[str, Any]:
        tasks = service.pull_tasks(agent_id=agent_id, limit=limit, now=datetime.now(tz=UTC))
        return {"tasks": [task.__dict__ for task in tasks]}

    @app.post("/api/v1/tasks/{task_id}/ack")
    def ack_task(task_id: int, payload: AckPayload, _: None = Depends(require_signature)) -> dict[str, Any]:
        result = service.ack_task(
            task_id=task_id,
            agent_id=payload.agent_id,
            lease_seconds=payload.lease_seconds,
            now=datetime.now(tz=UTC),
        )
        return {"task_id": result.task_id, "lease_token": result.lease_token, "lease_until": result.lease_until}

    @app.post("/api/v1/orders/report")
    def report_order(payload: OrderReportPayload, _: None = Depends(require_signature)) -> dict[str, Any]:
        cmd = OrderReportCommand(**payload.model_dump())
        status = service.report_order(cmd=cmd, now=datetime.now(tz=UTC))
        return {"status": status}

    @app.post("/api/v1/heartbeat")
    def heartbeat(payload: HeartbeatPayload, _: None = Depends(require_signature)) -> dict[str, str]:
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


def _build_replay_guard(db_url: str | None) -> Any:
    if db_url:
        from relay.security.signature import PostgresReplayGuard

        return PostgresReplayGuard(connection_factory=create_psycopg_connection_factory(db_url))
    return MemoryReplayGuard()


def _signal_to_dict(record: SignalRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "signal_id": record.signal_id,
        "strategy_id": record.strategy_id,
        "account_id": record.account_id,
        "ts": record.ts.isoformat(),
        "symbol": record.symbol,
        "action": record.action.value,
        "order_type": record.order_type.value,
        "qty": str(record.qty) if record.qty is not None else None,
        "amount": str(record.amount) if record.amount is not None else None,
        "target_pos": str(record.target_pos) if record.target_pos is not None else None,
        "limit_price": str(record.limit_price) if record.limit_price is not None else None,
        "max_slippage_bps": record.max_slippage_bps,
        "expire_at": record.expire_at.isoformat() if record.expire_at else None,
        "remark": record.remark,
        "received_at": record.received_at.isoformat(),
    }


def _render_admin_page() -> Any:
    from fastapi.responses import HTMLResponse

    html = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Signal Relay Admin</title>
    <style>
      @import url("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=IBM+Plex+Sans:wght@300;400;600&family=IBM+Plex+Mono:wght@400;600&display=swap");
      :root {
        --bg: #f4efe7;
        --ink: #1f1f1f;
        --muted: #6b6356;
        --accent: #c54a2f;
        --accent-2: #1f4d4a;
        --panel: #fbf7ef;
        --grid: #e2d8c7;
        --line: rgba(31, 31, 31, 0.1);
        --shadow: 0 24px 60px rgba(31, 31, 31, 0.12);
      }

      * {
        box-sizing: border-box;
      }

      body {
        margin: 0;
        font-family: "IBM Plex Sans", sans-serif;
        color: var(--ink);
        background: radial-gradient(circle at 20% 10%, rgba(197, 74, 47, 0.08), transparent 40%),
          radial-gradient(circle at 80% 0%, rgba(31, 77, 74, 0.08), transparent 45%),
          linear-gradient(135deg, #f8f3eb 0%, #f1eadf 45%, #efe6d9 100%);
        min-height: 100vh;
      }

      body::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background-image: repeating-linear-gradient(
          120deg,
          rgba(31, 31, 31, 0.04),
          rgba(31, 31, 31, 0.04) 1px,
          transparent 1px,
          transparent 6px
        );
        opacity: 0.2;
        mix-blend-mode: multiply;
      }

      .page {
        max-width: 1200px;
        margin: 0 auto;
        padding: 32px 24px 64px;
        position: relative;
        z-index: 1;
        animation: fadeIn 0.6s ease-out both;
      }

      header {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-bottom: 28px;
      }

      h1 {
        margin: 0;
        font-family: "Fraunces", serif;
        font-weight: 700;
        font-size: clamp(2.2rem, 4vw, 3.4rem);
        letter-spacing: 0.5px;
      }

      .subtitle {
        color: var(--muted);
        font-size: 0.98rem;
        max-width: 720px;
      }

      .filters {
        background: var(--panel);
        border: 1px solid var(--grid);
        border-radius: 18px;
        padding: 18px;
        display: grid;
        gap: 14px;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        box-shadow: var(--shadow);
      }

      .filters label {
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
        display: block;
        margin-bottom: 6px;
      }

      .filters input,
      .filters select {
        width: 100%;
        padding: 10px 12px;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: white;
        font-family: "IBM Plex Sans", sans-serif;
        font-size: 0.92rem;
      }

      .actions {
        display: flex;
        gap: 10px;
        align-items: end;
      }

      .button {
        border: none;
        padding: 10px 16px;
        border-radius: 999px;
        font-weight: 600;
        cursor: pointer;
        font-family: "IBM Plex Sans", sans-serif;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
      }

      .button.primary {
        background: var(--accent);
        color: white;
        box-shadow: 0 10px 24px rgba(197, 74, 47, 0.25);
      }

      .button.secondary {
        background: transparent;
        color: var(--accent);
        border: 1px solid rgba(197, 74, 47, 0.4);
      }

      .button:hover {
        transform: translateY(-1px);
      }

      .status-bar {
        margin: 16px 0 10px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        color: var(--muted);
        font-size: 0.9rem;
      }

      .ledger {
        background: var(--panel);
        border-radius: 18px;
        border: 1px solid var(--grid);
        overflow: hidden;
        box-shadow: var(--shadow);
      }

      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.9rem;
      }

      thead {
        background: rgba(31, 77, 74, 0.08);
        font-family: "IBM Plex Mono", monospace;
        font-size: 0.78rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }

      th, td {
        padding: 12px 14px;
        border-bottom: 1px solid var(--line);
        text-align: left;
        vertical-align: top;
      }

      tbody tr:hover {
        background: rgba(197, 74, 47, 0.04);
      }

      .pill {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 600;
        background: rgba(31, 77, 74, 0.12);
        color: var(--accent-2);
      }

      .empty {
        padding: 36px;
        text-align: center;
        color: var(--muted);
      }

      @media (max-width: 900px) {
        .status-bar {
          flex-direction: column;
          align-items: flex-start;
          gap: 6px;
        }
        table, thead, tbody, th, td, tr {
          display: block;
        }
        thead {
          display: none;
        }
        tbody tr {
          padding: 10px 0;
        }
        td {
          border: none;
          padding: 8px 16px;
        }
        td::before {
          content: attr(data-label);
          display: block;
          font-size: 0.7rem;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: var(--muted);
          margin-bottom: 4px;
        }
      }

      @keyframes fadeIn {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
      }
    </style>
  </head>
  <body>
    <main class="page">
      <header>
        <h1>Signal Ledger</h1>
        <div class="subtitle">只读查询聚宽信号落库情况。支持关键字检索与基础过滤，用于快速核对当前信号流转。</div>
      </header>

      <form class="filters" id="filters">
        <div>
          <label>关键字</label>
          <input type="text" name="q" placeholder="signal_id / strategy_id / account_id / symbol" />
        </div>
        <div>
          <label>Action</label>
          <select name="action">
            <option value="">全部</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </div>
        <div>
          <label>Order Type</label>
          <select name="order_type">
            <option value="">全部</option>
            <option value="MARKET">MARKET</option>
            <option value="LIMIT">LIMIT</option>
            <option value="TARGET_VALUE">TARGET_VALUE</option>
            <option value="TARGET_POS">TARGET_POS</option>
          </select>
        </div>
        <div>
          <label>开始时间</label>
          <input type="datetime-local" name="since" />
        </div>
        <div>
          <label>结束时间</label>
          <input type="datetime-local" name="until" />
        </div>
        <div>
          <label>Limit</label>
          <input type="number" name="limit" value="200" min="1" max="500" />
        </div>
        <div class="actions">
          <button class="button primary" type="submit">查询</button>
          <button class="button secondary" type="button" id="resetBtn">重置</button>
        </div>
      </form>

      <div class="status-bar">
        <div id="statusText">准备就绪</div>
        <div id="countText"></div>
      </div>

      <section class="ledger" id="ledger">
        <div class="empty">暂无数据</div>
      </section>
    </main>

    <script>
      const form = document.getElementById("filters");
      const ledger = document.getElementById("ledger");
      const statusText = document.getElementById("statusText");
      const countText = document.getElementById("countText");
      const resetBtn = document.getElementById("resetBtn");

      function buildParams() {
        const data = new FormData(form);
        const params = new URLSearchParams();
        for (const [key, value] of data.entries()) {
          if (!value) continue;
          if (key === "since" || key === "until") {
            const iso = new Date(value).toISOString();
            params.set(key, iso);
          } else {
            params.set(key, value.toString());
          }
        }
        return params.toString();
      }

      function renderTable(items) {
        if (!items.length) {
          ledger.innerHTML = '<div class="empty">暂无数据</div>';
          return;
        }
        const rows = items.map((item) => {
          return `
            <tr>
              <td data-label="Signal ID">${item.signal_id}</td>
              <td data-label="Strategy">${item.strategy_id}</td>
              <td data-label="Account">${item.account_id}</td>
              <td data-label="Symbol"><span class="pill">${item.symbol}</span></td>
              <td data-label="Action">${item.action}</td>
              <td data-label="Type">${item.order_type}</td>
              <td data-label="Qty">${item.qty ?? "-"}</td>
              <td data-label="Time">${item.ts}</td>
            </tr>
          `;
        }).join("");

        ledger.innerHTML = `
          <table>
            <thead>
              <tr>
                <th>Signal ID</th>
                <th>Strategy</th>
                <th>Account</th>
                <th>Symbol</th>
                <th>Action</th>
                <th>Type</th>
                <th>Qty</th>
                <th>Signal Time</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        `;
      }

      async function loadSignals() {
        statusText.textContent = "加载中...";
        const params = buildParams();
        const url = params ? `/admin/api/signals?${params}` : "/admin/api/signals";
        try {
          const resp = await fetch(url);
          if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
          }
          const data = await resp.json();
          renderTable(data.items || []);
          countText.textContent = `当前显示 ${data.count} 条`;
          statusText.textContent = "已更新";
        } catch (err) {
          statusText.textContent = "加载失败";
          countText.textContent = "";
          ledger.innerHTML = '<div class="empty">加载失败，请稍后重试</div>';
        }
      }

      form.addEventListener("submit", (event) => {
        event.preventDefault();
        loadSignals();
      });

      resetBtn.addEventListener("click", () => {
        form.reset();
        loadSignals();
      });

      loadSignals();
    </script>
  </body>
</html>
"""
    return HTMLResponse(content=html)
