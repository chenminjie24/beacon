# Signal Relay (v0-v1 scaffold)

This repository implements the first development slice of the `signal-qmt-architecture-v1.3.md` design:

- deterministic domain state machines
- idempotent signal ingestion with payload conflict protection
- task pull/ack/lease recycle flow
- order report processing with task state mapping
- PostgreSQL repository adapter with `FOR UPDATE SKIP LOCKED`
- Alembic bootstrap and baseline migration
- offline unit tests (no external services, no network)

## Run tests (offline)

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Optional install for API/DB runtime

```bash
pip install -e ".[api,db]"
```

## Database migration

```bash
alembic upgrade head
```

## Local Docker bring-up

```bash
cp deploy/.env.example deploy/.env
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

## Notes

- Core tests only depend on Python standard library and run offline.
- FastAPI adapter lives at `relay.api.fastapi_app`.
- PostgreSQL adapter lives at `relay.repository.postgres`.
