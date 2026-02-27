# QMT 实盘中台（一期）

本项目实现“服务端信号中台 + 本地 QMT 执行客户端”的一期可运行版本，满足以下目标：
- 接收聚宽/多平台交易信号并入库（Webhook + HMAC）
- 后端 API + 前端管理台
- Windows 本地客户端轮询并通过 `xtquant`（预留适配位）执行
- Docker Compose 单机部署

## 目录结构

- `backend/` FastAPI + PostgreSQL 模型 + 风控 + 调度接口
- `frontend/` Next.js 管理后台
- `client/` Windows 执行客户端（Python）
- `deploy/` Nginx 配置
- `docker-compose.yml` 一键部署

## 快速启动（Docker）

1. 复制环境变量
```bash
cp .env.example .env
```

2. 启动
```bash
docker compose up -d --build
```

3. 访问
- 前端：`http://localhost:8000`
- 后端健康检查：`http://localhost:8000/healthz`

默认后台账号：
- 用户名：`admin`
- 密码：`admin123456`

## 核心 API

- `POST /api/v1/signals/webhook` 接收信号（签名验签 + 幂等）
- `POST /api/v1/client/heartbeat` 客户端心跳
- `POST /api/v1/client/tasks/claim` 客户端领取任务
- `POST /api/v1/client/tasks/{task_id}/report` 执行结果上报
- `POST /api/v1/client/trades/report` 成交回报
- `POST /api/v1/orders/{order_id}/cancel` 前端发起撤单
- `GET /api/v1/signals|orders|positions|clients|alerts|audit-logs` 管理查询
- `PUT /api/v1/risk-rules/{rule_id}` 更新风控

## Webhook 签名

请求头：
- `X-Signature`: `HMAC_SHA256(secret, body + timestamp)`
- `X-Timestamp`: 毫秒时间戳
- `X-Source`: 来源平台，例如 `joinquant`

## 聚宽推送示例

以下示例可直接放到聚宽策略中调用（按当前服务端签名规则）：

```python
# coding: utf-8
import json
import time
import hmac
import hashlib
import requests

WEBHOOK_URL = "https://你的域名/api/v1/signals/webhook"
WEBHOOK_SECRET = "replace-me"   # 与服务端 DEFAULT_WEBHOOK_SECRET 一致
SOURCE = "joinquant"
STRATEGY_ID = "jq_alpha_001"
ACCOUNT_ID = "acc_stock_main"

def send_signal(symbol, side, quantity=None, amount=None, signal_type="INCREMENTAL_ORDER", target_position_ratio=None, extra=None):
    payload = {
        "source_platform": SOURCE,
        "strategy_id": STRATEGY_ID,
        "account_id": ACCOUNT_ID,
        "signal_type": signal_type,  # INCREMENTAL_ORDER / TARGET_POSITION
        "idempotency_key": "jq_%d_%s_%s" % (int(time.time() * 1000), symbol, side),
        "symbol": symbol,            # 例如 600519.SH / 000001.SZ
        "side": side,                # BUY / SELL
        "order_style": "MARKET",     # MARKET / LIMIT
        "quantity": quantity,
        "amount": amount,
        "target_position_ratio": target_position_ratio,
        "timestamp_ms": int(time.time() * 1000),
        "extra": extra or {},
    }

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time() * 1000))
    sig = hmac.new(WEBHOOK_SECRET.encode("utf-8"), body + ts.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Signature": sig,
        "X-Timestamp": ts,
        "X-Source": SOURCE,
    }

    resp = requests.post(WEBHOOK_URL, data=body, headers=headers, timeout=8)
    log.info("signal resp: status=%s body=%s", resp.status_code, resp.text)

def initialize(context):
    run_daily(trade_logic, time='09:35')

def trade_logic(context):
    send_signal(
        symbol="600519.SH",
        side="BUY",
        quantity=100,
        amount=20000,
        signal_type="INCREMENTAL_ORDER",
        extra={"reference_price": 200},
    )
```

注意：
- 签名必须基于“实际发送的 `body` 字节 + `X-Timestamp`”计算（示例使用 `data=body`）。
- `idempotency_key` 需保证每条信号唯一，否则服务端会判重并返回 `duplicate=true`。
- `X-Timestamp` 与服务端时间偏差需在 5 分钟内。

## 本地客户端运行

```bash
cd client
pip install -r requirements.txt
python -m qmt_gateway.main
```

环境变量最少需要：
- `SERVER_BASE_URL`
- `CLIENT_SHARED_TOKEN`
- `CLIENT_ID`
- `ACCOUNT_ID`
- `EXECUTION_MODE`（建议实盘使用 `XT_ONLY`）
- `SECRET_FILE`（需包含 `qmt_path/qmt_account_id/session_id`）

`client/README.md` 提供了完整的 xtquant 实盘配置示例。

## 测试

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

说明：测试默认开启 `BYPASS_TRADING_TIME_CHECK=true`，仅用于测试环境绕过交易时段风控。
