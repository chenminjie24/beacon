# Implementation Notes (v0)

This codebase applies the six confirmed defaults before full integration:

1. **Signature canonicalization**
   - canonical string: `timestamp\nrequest_id\nmethod\npath\nsha256(body)`
   - timestamp skew: `±300s`
   - replay protection via nonce store (`api_key:timestamp:request_id:signature`)

2. **Idempotency conflict behavior**
   - same `signal_id` + same payload hash => idempotent hit (`200`)
   - same `signal_id` + different payload hash => conflict (`409`)

3. **Order report binding**
   - `task_id` and `lease_token` are required in `OrderReportCommand`
   - lease owner (`agent_id`) must match task lease owner

4. **FAILED_RISK semantics**
   - order terminal status: `FAILED_RISK`
   - mapped task terminal status: `FAILED`

5. **ACK conflict semantics**
   - only `READY` tasks are ackable
   - others raise conflict with holder and lease summary

6. **Task queue indexes in SQL**
   - pull path index: `(status, next_retry_at, priority, id)` partial on `status='READY'`
   - lease recycle index: `(lease_until)` partial on `status in ('ACKED','EXECUTING')`

## Current scope

- Core domain and application logic implemented and tested offline.
- FastAPI adapter supports env-based repository selection (`DB_URL` => PostgreSQL).
- PostgreSQL repository implemented with:
  - pull/recycle query locking (`FOR UPDATE SKIP LOCKED`)
  - task update optimistic lock (`WHERE id=? AND version=?`)
- Alembic baseline is wired to execute `sql/001_init.sql`.

## Next engineering slices

- add QMT agent skeleton and local journal persistence
- add EOD reconciliation module + test fixtures
- replace in-memory replay guard with DB-backed nonce guard (`request_nonces`)
