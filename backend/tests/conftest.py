import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

DB_PATH = Path('test.db').resolve()
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ['DATABASE_URL'] = f'sqlite+pysqlite:///{DB_PATH}'
os.environ['ADMIN_USERNAME'] = 'admin'
os.environ['ADMIN_PASSWORD'] = 'admin123456'
os.environ['DEFAULT_WEBHOOK_SECRET'] = 'test-webhook-secret'
os.environ['JWT_SECRET'] = 'test-jwt-secret'
os.environ['BYPASS_TRADING_TIME_CHECK'] = 'true'

from app.main import app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c
