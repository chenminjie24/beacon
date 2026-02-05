-- Initial schema aligned with signal-qmt-architecture-v1.3 + confirmed defaults.

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
  remark VARCHAR(256),
  payload_raw JSONB NOT NULL,
  payload_hash CHAR(64) NOT NULL,
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

CREATE INDEX idx_execution_tasks_ready
  ON execution_tasks(status, next_retry_at, priority, id)
  WHERE status = 'READY';

CREATE INDEX idx_execution_tasks_lease
  ON execution_tasks(lease_until)
  WHERE status IN ('ACKED', 'EXECUTING');

CREATE TABLE orders (
  id BIGSERIAL PRIMARY KEY,
  client_order_id VARCHAR(80) NOT NULL UNIQUE,
  signal_id BIGINT NOT NULL REFERENCES signals(id),
  task_id BIGINT NOT NULL REFERENCES execution_tasks(id),
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

-- Replay-protection nonce table for API requests.
CREATE TABLE request_nonces (
  nonce VARCHAR(256) PRIMARY KEY,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_request_nonces_expiry ON request_nonces(expires_at);
