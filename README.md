# Signal Relay (v0-v1 scaffold)

本仓库实现了 `signal-qmt-architecture-v1.3.md` 设计的 first development slice（第一阶段开发切片）：

- deterministic domain state machines（确定性的领域状态机）
- idempotent signal ingestion with payload conflict protection（具备 payload 冲突保护的幂等信号接收）
- task pull/ack/lease recycle flow（任务拉取/确认/租约回收流程）
- order report processing with task state mapping（带任务状态映射的订单回报处理）
- PostgreSQL repository adapter with `FOR UPDATE SKIP LOCKED`（使用 `FOR UPDATE SKIP LOCKED` 的 PostgreSQL 仓储适配器）
- Alembic bootstrap and baseline migration（Alembic 初始化与基线迁移）
- QMT agent skeleton with local journal + retry logic（带本地日志与重试逻辑的 QMT 代理骨架）
- offline unit tests (no external services, no network)（offline 单元测试，无外部服务、无网络）

## 运行测试（offline，离线）

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## 可选安装（API/DB runtime，API/数据库运行时）

```bash
pip install -e ".[api,db]"
```

## 数据库迁移（database migration）

```bash
alembic upgrade head
```

## 本地 Docker 启动（local Docker bring-up）

```bash
cp deploy/.env.example deploy/.env
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec relay-api alembic upgrade head
# 发送信号
python3 scripts/send_signal.py
```

## 说明（notes）

- Core tests（核心测试）仅依赖 Python standard library（Python 标准库），并可在 offline（离线）环境运行。
- FastAPI adapter（FastAPI 适配器）位于 `relay.api.fastapi_app`。
- PostgreSQL adapter（PostgreSQL 适配器）位于 `relay.repository.postgres`。
- Agent skeleton（代理骨架）位于 `qmt_agent`（journal + retry + HTTP relay client，本地日志 + 重试 + HTTP 中继客户端）。
- API endpoints（API 端点）期望 HMAC signature headers（HMAC 签名头）：
  `X-API-KEY`, `X-TIMESTAMP`, `X-SIGNATURE`, `X-REQUEST-ID`。
