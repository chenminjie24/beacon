# 聚宽信号中转到 QMT 实盘系统技术方案（v1.3）

> 版本说明：基于前序讨论整理，保持「无 Redis、无异步任务队列」约束，并将 `Signal Relay API` 部署方式调整为 **Docker 部署**。

---

## 1. 目标与范围

- 目标：将聚宽（JoinQuant）模拟策略信号稳定中转到 QMT 实盘执行。
- 约束：
  - 开发语言：Python
  - 不使用 Redis
  - 不使用 Celery/RQ/Kafka 等异步任务系统
- 范围（v1）：
  - 单账户，多策略接入
  - 实现完整信号接收、任务分发、下单执行、状态回报、审计闭环

---

## 2. 总体架构

### 2.1 组件划分

1. Signal Relay API（服务端）
   - 技术栈：FastAPI + PostgreSQL
   - 职责：信号接收、鉴权、幂等、任务生成、状态管理、审计记录
   - 部署：Docker（建议使用 docker compose）

2. QMT Execution Agent（本地交易机）
   - 技术栈：Python + xtquant/xttrader + APScheduler
   - 职责：主动拉取任务、风控检查、调用 QMT 下单、回传订单状态
   - 部署：Windows 本机进程（通常不容器化）

3. PostgreSQL（中心数据库）
   - 职责：信号、任务、订单、成交、心跳、审计数据存储

4. Monitor/Alert（可与 Relay 同进程）
   - 职责：租约回收、心跳检测、失败重试调度、EOD 对账与告警

### 2.2 部署拓扑

- 云端/机房（Docker）
  - `relay-api` 容器
  - `postgres` 容器（生产可替换为托管 PG）
- 本地 Windows（非 Docker）
  - `qmt client`
  - `qmt-agent`

设计原则：
- QMT 所在机器仅主动出站访问 Relay，不暴露入站端口。
- “队列能力”由 PostgreSQL 任务表 + 行级锁实现。

---

## 3. 核心业务流程

1. 聚宽策略触发信号，调用 `POST /api/v1/signals`。
2. Relay 校验签名、参数和幂等键（`signal_id`），写入 `signals` 并创建 `execution_tasks(READY)`。
3. Agent 每 1~2 秒轮询 `GET /api/v1/tasks/pull` 拉取任务。
4. Agent 通过 `POST /api/v1/tasks/{task_id}/ack` 获取租约（lease）。
5. Agent 本地风控通过后调用 QMT 下单。
6. Agent 调用 `POST /api/v1/orders/report` 回报 `SUBMITTED/PARTIAL/FILLED/CANCELED/REJECTED/FAILED_RISK`。
7. Relay 落库并推进状态机，写入审计日志。
8. 达终态后任务结束；异常时由 lease 超时自动回收并重试。

---

## 4. 可靠性设计（无中间件）

### 4.1 幂等与去重

- 信号幂等：`signals.signal_id` 唯一索引
- 订单幂等：`orders.client_order_id` 唯一索引
- 成交幂等：`fills(order_id, trade_id)` 唯一索引

### 4.2 任务分发

- 任务拉取使用 `SELECT ... FOR UPDATE SKIP LOCKED`
- 通过 `lease_token + lease_until` 控制任务归属和过期回收
- `ACKED/EXECUTING` 超时任务自动回退到 `READY`

### 4.3 状态机

- Task：`READY -> ACKED -> EXECUTING -> DONE/FAILED`
- Order：`NEW -> SUBMITTED -> PARTIAL -> FILLED/CANCELED/REJECTED`
- `FAILED_RISK` 用于本地风控拒单场景

---

## 5. 风控方案（v1 硬规则）

- 交易时段校验（含午休）
- 信号过期校验（`expire_at`）
- 单笔金额上限
- 单标的仓位上限（按净值比例）
- 日内买入总额上限
- 滑点保护（与最新价偏离 bps）
- 黑白名单（symbol/strategy/account）

风控执行点：
- Relay 端：静态规则预校验
- Agent 端：下单前终检（资金、持仓、行情实时约束）

---

## 6. API 字段字典（v1）

### 6.1 通用鉴权头

- `X-API-KEY`：API 密钥
- `X-TIMESTAMP`：Unix 秒时间戳（防重放）
- `X-SIGNATURE`：HMAC-SHA256 签名
- `X-REQUEST-ID`：可选追踪 ID

### 6.2 `POST /api/v1/signals`

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| signal_id | string(64) | Y | 全局幂等键 |
| strategy_id | string(64) | Y | 策略标识 |
| account_id | string(32) | Y | 账户标识 |
| ts | datetime | Y | 信号时间 |
| symbol | string(32) | Y | 证券代码（如 `000001.SZ`） |
| action | enum | Y | `BUY`/`SELL` |
| order_type | enum | Y | `MARKET`/`LIMIT`/`TARGET_VALUE`/`TARGET_POS` |
| qty | number | N | 数量单 |
| amount | number | N | 金额单 |
| target_pos | number | N | 目标仓位 |
| limit_price | number | N | 限价单价格 |
| max_slippage_bps | int | N | 默认 20 |
| expire_at | datetime | N | 过期时间 |
| remark | string(256) | N | 备注 |

响应：
- `202 Accepted`：新信号
- `200 OK`：幂等命中

### 6.3 `GET /api/v1/tasks/pull`

Query:
- `agent_id`（必填）
- `limit`（可选，默认 10，最大 100）

返回：任务数组（task_id, signal_id, symbol, side, order_type, qty/amount/target_pos, expire_at, priority）

### 6.4 `POST /api/v1/tasks/{task_id}/ack`

请求：
- `agent_id`（必填）
- `lease_seconds`（可选，默认 30）

响应：
- `task_id`
- `lease_token`
- `lease_until`

### 6.5 `POST /api/v1/orders/report`

请求：
- `agent_id`
- `client_order_id`
- `qmt_order_id`（可选）
- `status`（`NEW/SUBMITTED/PARTIAL/FILLED/CANCELED/REJECTED/FAILED_RISK`）
- `filled_qty`（可选）
- `avg_price`（可选）
- `reason_code/reason_msg`（可选）
- `event_time`
- `lease_token`（可选）

### 6.6 `POST /api/v1/heartbeat`

请求：
- `agent_id`
- `host`
- `version`
- `qmt_connected`
- `latency_ms`（可选）
- `now`

---

## 7. 数据库 DDL 清单（PostgreSQL）

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE signals (
  id BIGSERIAL PRIMARY KEY,
  signal_id VARCHAR(64) NOT NULL UNIQUE,
  strategy_id VARCHAR(64) NOT NULL,
  account_id VARCHAR(32) NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  action VARCHAR(8) NOT NULL CHECK (action IN ('BUY','SELL')),
  order_type VARCHAR(16) NOT NULL CHECK (order_type IN ('MARKET','LIMIT','TARGET_VALUE','TARGET_POS')),
  qty NUMERIC(20,4),
  amount NUMERIC(20,4),
  target_pos NUMERIC(10,6),
  limit_price NUMERIC(20,6),
  max_slippage_bps INTEGER NOT NULL DEFAULT 20 CHECK (max_slippage_bps >= 0 AND max_slippage_bps <= 10000),
  expire_at TIMESTAMPTZ,
  payload_raw JSONB NOT NULL,
  sig_valid BOOLEAN NOT NULL,
  source VARCHAR(32) NOT NULL DEFAULT 'joinquant',
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    (order_type = 'TARGET_VALUE' AND amount IS NOT NULL AND qty IS NULL AND target_pos IS NULL) OR
    (order_type = 'TARGET_POS' AND target_pos IS NOT NULL AND qty IS NULL AND amount IS NULL) OR
    (order_type IN ('MARKET','LIMIT') AND qty IS NOT NULL AND amount IS NULL AND target_pos IS NULL)
  ),
  CHECK ((order_type <> 'LIMIT') OR (limit_price IS NOT NULL))
);

CREATE TABLE execution_tasks (
  id BIGSERIAL PRIMARY KEY,
  signal_id BIGINT NOT NULL UNIQUE REFERENCES signals(id),
  status VARCHAR(16) NOT NULL CHECK (status IN ('READY','ACKED','EXECUTING','DONE','FAILED')),
  priority SMALLINT NOT NULL DEFAULT 100,
  agent_id VARCHAR(64),
  lease_token UUID,
  lease_until TIMESTAMPTZ,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  next_retry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_error_code VARCHAR(64),
  last_error_msg TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  version INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE orders (
  id BIGSERIAL PRIMARY KEY,
  client_order_id VARCHAR(80) NOT NULL UNIQUE,
  signal_id BIGINT NOT NULL REFERENCES signals(id),
  task_id BIGINT REFERENCES execution_tasks(id),
  account_id VARCHAR(32) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  side VARCHAR(8) NOT NULL CHECK (side IN ('BUY','SELL')),
  price NUMERIC(20,6),
  qty NUMERIC(20,4) NOT NULL,
  qmt_order_id VARCHAR(64),
  status VARCHAR(16) NOT NULL CHECK (status IN ('NEW','SUBMITTED','PARTIAL','FILLED','CANCELED','REJECTED','FAILED_RISK')),
  filled_qty NUMERIC(20,4) NOT NULL DEFAULT 0,
  avg_price NUMERIC(20,6),
  reject_code VARCHAR(64),
  reject_msg VARCHAR(512),
  submitted_at TIMESTAMPTZ,
  finalized_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE fills (
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES orders(id),
  trade_id VARCHAR(64) NOT NULL,
  trade_price NUMERIC(20,6) NOT NULL,
  trade_qty NUMERIC(20,4) NOT NULL,
  trade_time TIMESTAMPTZ NOT NULL,
  fee NUMERIC(20,6) NOT NULL DEFAULT 0,
  tax NUMERIC(20,6) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(order_id, trade_id)
);

CREATE TABLE agent_heartbeats (
  agent_id VARCHAR(64) PRIMARY KEY,
  host VARCHAR(128) NOT NULL,
  version VARCHAR(32) NOT NULL,
  qmt_connected BOOLEAN NOT NULL,
  latency_ms INTEGER,
  status VARCHAR(16) NOT NULL CHECK (status IN ('ONLINE','OFFLINE','DEGRADED')),
  last_seen_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_events (
  id BIGSERIAL PRIMARY KEY,
  trace_id VARCHAR(64),
  entity_type VARCHAR(16) NOT NULL CHECK (entity_type IN ('signal','task','order','agent','system')),
  entity_id VARCHAR(64) NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  event_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  operator VARCHAR(64) NOT NULL DEFAULT 'system',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 8. Docker 部署设计（Signal Relay API）

### 8.1 容器划分

- `relay-api`：FastAPI 应用容器
- `postgres`：数据库容器（开发/测试环境）

生产建议：
- 若已有托管 PostgreSQL，可仅部署 `relay-api` 容器；
- 使用反向代理（Nginx/Traefik）终止 TLS；
- 将 `API_KEY/HMAC_SECRET/DB_URL` 通过环境变量或密钥服务注入。

### 8.2 目录建议

- `deploy/docker-compose.yml`
- `deploy/.env`
- `relay/Dockerfile`

### 8.3 docker-compose 示例（简版）

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16
    container_name: relay-postgres
    restart: always
    environment:
      POSTGRES_DB: relay
      POSTGRES_USER: relay
      POSTGRES_PASSWORD: relay_pwd
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U relay -d relay"]
      interval: 10s
      timeout: 5s
      retries: 5

  relay-api:
    build:
      context: ..
      dockerfile: relay/Dockerfile
    container_name: relay-api
    restart: always
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      APP_ENV: prod
      DB_URL: postgresql+psycopg2://relay:relay_pwd@postgres:5432/relay
      API_KEY: change_me
      HMAC_SECRET: change_me_too
      TZ: Asia/Shanghai
    ports:
      - "8080:8080"

volumes:
  pgdata:
```

### 8.4 Relay Dockerfile 示例（简版）

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY relay/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY relay /app

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 8.5 启动与发布建议

1. 本地/测试环境：`docker compose up -d`
2. 生产环境：
   - 使用镜像仓库（版本标签如 `relay-api:1.0.0`）
   - 灰度发布（先 1 实例）
   - 配置健康检查与自动重启
3. 数据迁移：
   - 使用 Alembic（在发布流程中执行）
   - 严禁手工改表后不留迁移脚本

---

## 9. 异常时序图（Mermaid）

### 9.1 重复信号（幂等）

```mermaid
sequenceDiagram
  participant JQ as JoinQuant
  participant Relay as Relay API
  participant DB as PostgreSQL

  JQ->>Relay: POST /signals (signal_id=S1)
  Relay->>DB: INSERT signals(S1)
  DB-->>Relay: success
  Relay->>DB: INSERT task READY
  DB-->>Relay: success
  Relay-->>JQ: 202 Accepted

  JQ->>Relay: POST /signals (signal_id=S1)
  Relay->>DB: INSERT signals(S1)
  DB-->>Relay: unique violation
  Relay-->>JQ: 200 OK (idempotent hit)
```

### 9.2 ACK 后 Agent 宕机（lease 回收）

```mermaid
sequenceDiagram
  participant Agent as QMT Agent
  participant Relay as Relay API
  participant DB as PostgreSQL
  participant Job as Recycle Job

  Agent->>Relay: pull task
  Relay-->>Agent: task T1
  Agent->>Relay: ack T1 (lease=30s)
  Relay->>DB: T1 -> ACKED
  DB-->>Relay: success
  Note over Agent: crash
  Job->>DB: scan expired lease
  DB-->>Job: T1 expired
  Job->>DB: T1 -> READY, attempt+1
```

### 9.3 下单成功但回报丢失（补报）

```mermaid
sequenceDiagram
  participant Agent as QMT Agent
  participant QMT as QMT
  participant Relay as Relay API
  participant DB as PostgreSQL

  Agent->>QMT: place order (C1)
  QMT-->>Agent: accepted (Q1)
  Agent->>Relay: report SUBMITTED(C1,Q1)
  Relay--xAgent: timeout
  Note over Agent: local journal keeps C1/Q1
  Agent->>Relay: retry report SUBMITTED(C1,Q1)
  Relay->>DB: upsert by client_order_id
  DB-->>Relay: success
  Relay-->>Agent: 200 OK
```

### 9.4 本地风控拒绝（不发单）

```mermaid
sequenceDiagram
  participant Agent as QMT Agent
  participant Risk as Local Risk
  participant Relay as Relay API
  participant DB as PostgreSQL

  Agent->>Risk: pre-trade check
  Risk-->>Agent: reject (position limit)
  Agent->>Relay: report FAILED_RISK
  Relay->>DB: order status -> FAILED_RISK
  DB-->>Relay: success
```

---

## 10. 运维参数建议（默认值）

- Agent 轮询间隔：1s
- lease：30s
- 心跳周期：5s
- Agent 离线阈值：15s
- 最大重试次数：3
- 重试退避：5s / 15s / 30s
- 信号默认过期：5 分钟

---

## 11. 里程碑计划

- Phase 1（1~2 周）：信号接入、任务拉取、QMT 下单、状态回报、基础日志
- Phase 2（2~3 周）：状态机完善、lease 回收、风控规则、告警
- Phase 3（2 周）：EOD 对账、压测、故障演练、发布规范固化

---

## 12. 验收标准

- 重复信号不重复下单（100%）
- Agent 宕机恢复后任务可继续执行
- 订单终态与 QMT 一致，EOD 对账差异为 0
- 关键告警（离线/连续拒单/连续失败）1 分钟内可达

