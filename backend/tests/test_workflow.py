import hashlib
import hmac
import json
import time


def sign_body(body: bytes, timestamp: str, secret: str) -> str:
    return hmac.new(secret.encode('utf-8'), body + timestamp.encode('utf-8'), hashlib.sha256).hexdigest()


def login(client) -> str:
    resp = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'admin123456'})
    assert resp.status_code == 200
    return resp.json()['access_token']


def send_signal(client, *, idempotency_key: str, symbol: str, quantity: int, amount: int):
    payload = {
        'source_platform': 'joinquant',
        'strategy_id': 'default_strategy',
        'account_id': 'acc_stock_main',
        'signal_type': 'INCREMENTAL_ORDER',
        'idempotency_key': idempotency_key,
        'symbol': symbol,
        'side': 'BUY',
        'order_style': 'MARKET',
        'quantity': quantity,
        'amount': amount,
        'target_position_ratio': None,
        'timestamp_ms': int(time.time() * 1000),
        'extra': {'reference_price': amount / max(quantity, 1)},
    }
    body = json.dumps(payload).encode('utf-8')
    ts = str(int(time.time() * 1000))
    signature = sign_body(body, ts, 'test-webhook-secret')
    resp = client.post(
        '/api/v1/signals/webhook',
        content=body,
        headers={'X-Signature': signature, 'X-Timestamp': ts, 'X-Source': 'joinquant', 'Content-Type': 'application/json'},
    )
    assert resp.status_code == 200
    return resp.json()


def test_webhook_idempotency(client):
    payload = {
        'source_platform': 'joinquant',
        'strategy_id': 'default_strategy',
        'account_id': 'acc_stock_main',
        'signal_type': 'INCREMENTAL_ORDER',
        'idempotency_key': 'idem_001',
        'symbol': '600519.SH',
        'side': 'BUY',
        'order_style': 'MARKET',
        'quantity': 100,
        'amount': 20000,
        'target_position_ratio': None,
        'timestamp_ms': int(time.time() * 1000),
        'extra': {'reference_price': 200},
    }
    body = json.dumps(payload).encode('utf-8')
    ts = str(int(time.time() * 1000))
    signature = sign_body(body, ts, 'test-webhook-secret')

    resp1 = client.post(
        '/api/v1/signals/webhook',
        content=body,
        headers={'X-Signature': signature, 'X-Timestamp': ts, 'X-Source': 'joinquant', 'Content-Type': 'application/json'},
    )
    assert resp1.status_code == 200
    assert resp1.json()['duplicate'] is False

    resp2 = client.post(
        '/api/v1/signals/webhook',
        content=body,
        headers={'X-Signature': signature, 'X-Timestamp': ts, 'X-Source': 'joinquant', 'Content-Type': 'application/json'},
    )
    assert resp2.status_code == 200
    assert resp2.json()['duplicate'] is True


def test_claim_and_report(client):
    payload = {
        'source_platform': 'joinquant',
        'strategy_id': 'default_strategy',
        'account_id': 'acc_stock_main',
        'signal_type': 'INCREMENTAL_ORDER',
        'idempotency_key': 'idem_002',
        'symbol': '000001.SZ',
        'side': 'BUY',
        'order_style': 'MARKET',
        'quantity': 100,
        'amount': 15000,
        'target_position_ratio': None,
        'timestamp_ms': int(time.time() * 1000),
        'extra': {'reference_price': 150},
    }
    body = json.dumps(payload).encode('utf-8')
    ts = str(int(time.time() * 1000))
    signature = sign_body(body, ts, 'test-webhook-secret')

    resp = client.post(
        '/api/v1/signals/webhook',
        content=body,
        headers={'X-Signature': signature, 'X-Timestamp': ts, 'X-Source': 'joinquant', 'Content-Type': 'application/json'},
    )
    assert resp.status_code == 200

    claim = client.post(
        '/api/v1/client/tasks/claim',
        json={
            'client_id': 'client_win_001',
            'account_id': 'acc_stock_main',
            'max_tasks': 20,
            'capabilities': ['ORDER', 'CANCEL'],
            'version': '0.1.0',
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert claim.status_code == 200
    tasks = claim.json()['tasks']
    assert len(tasks) >= 1

    task = tasks[0]
    assert task['payload']['order_id'].startswith('ord_')
    report = client.post(
        f"/api/v1/client/tasks/{task['task_id']}/report",
        json={
            'client_id': 'client_win_001',
            'status': 'SUBMITTED',
            'broker_order_id': 'mock_001',
            'message': 'ok',
            'filled_quantity': 0,
            'avg_price': 0,
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert report.status_code == 200


def test_admin_api(client):
    token = login(client)
    resp = client.get('/api/v1/dashboard/metrics', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 200
    data = resp.json()
    assert 'today_signals' in data


def test_report_task_rejects_non_owner_client(client):
    idem = f'idem_owner_{int(time.time() * 1000)}'
    send_signal(client, idempotency_key=idem, symbol='300750.SZ', quantity=100, amount=18000)

    claim = client.post(
        '/api/v1/client/tasks/claim',
        json={
            'client_id': 'client_a',
            'account_id': 'acc_stock_main',
            'max_tasks': 1,
            'capabilities': ['ORDER', 'CANCEL'],
            'version': '0.1.0',
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert claim.status_code == 200
    tasks = claim.json()['tasks']
    assert len(tasks) >= 1
    task_id = tasks[0]['task_id']

    hacked_report = client.post(
        f'/api/v1/client/tasks/{task_id}/report',
        json={
            'client_id': 'client_b',
            'status': 'SUBMITTED',
            'broker_order_id': 'mock_hijack_1',
            'message': 'hijack',
            'filled_quantity': 0,
            'avg_price': 0,
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert hacked_report.status_code == 409


def test_report_trade_returns_404_for_missing_order(client):
    resp = client.post(
        '/api/v1/client/trades/report',
        json={
            'client_id': 'client_win_001',
            'order_id': 'ord_not_exists',
            'broker_trade_id': f'trd_missing_{int(time.time() * 1000)}',
            'symbol': '600519.SH',
            'side': 'BUY',
            'quantity': 100,
            'price': 100,
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert resp.status_code == 404


def test_report_trade_is_idempotent(client):
    idem = f'idem_trade_{int(time.time() * 1000)}'
    signal_resp = send_signal(client, idempotency_key=idem, symbol='600519.SH', quantity=100, amount=20000)
    signal_id = signal_resp['signal_id']

    token = login(client)
    orders = client.get('/api/v1/orders?limit=200', headers={'Authorization': f'Bearer {token}'}).json()
    order = next((o for o in orders if o['signal_id'] == signal_id), None)
    assert order is not None

    trade_payload = {
        'client_id': 'client_win_001',
        'order_id': order['id'],
        'broker_trade_id': f'trd_dup_{int(time.time() * 1000)}',
        'symbol': order['symbol'],
        'side': order['side'],
        'quantity': 100,
        'price': 200,
    }

    first = client.post('/api/v1/client/trades/report', json=trade_payload, headers={'X-Client-Token': 'client-dev-token'})
    assert first.status_code == 200
    second = client.post('/api/v1/client/trades/report', json=trade_payload, headers={'X-Client-Token': 'client-dev-token'})
    assert second.status_code == 200

    orders_after = client.get('/api/v1/orders?limit=200', headers={'Authorization': f'Bearer {token}'}).json()
    order_after = next((o for o in orders_after if o['id'] == order['id']), None)
    assert order_after is not None
    assert order_after['filled_quantity'] == 100


def test_report_trade_accepts_broker_order_id(client):
    idem = f'idem_trade_broker_{int(time.time() * 1000)}'
    signal_resp = send_signal(client, idempotency_key=idem, symbol='000001.SZ', quantity=100, amount=12000)
    signal_id = signal_resp['signal_id']

    claim = client.post(
        '/api/v1/client/tasks/claim',
        json={
            'client_id': 'client_win_001',
            'account_id': 'acc_stock_main',
            'max_tasks': 20,
            'capabilities': ['ORDER', 'CANCEL'],
            'version': '0.1.0',
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert claim.status_code == 200
    task = next((item for item in claim.json()['tasks'] if item['signal_id'] == signal_id), None)
    assert task is not None

    report = client.post(
        f"/api/v1/client/tasks/{task['task_id']}/report",
        json={
            'client_id': 'client_win_001',
            'status': 'SUBMITTED',
            'broker_order_id': 'broker_10001',
            'message': 'ok',
            'filled_quantity': 0,
            'avg_price': 0,
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert report.status_code == 200

    trade_report = client.post(
        '/api/v1/client/trades/report',
        json={
            'client_id': 'client_win_001',
            'broker_order_id': 'broker_10001',
            'broker_trade_id': f'trd_broker_{int(time.time() * 1000)}',
            'quantity': 100,
            'price': 12,
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert trade_report.status_code == 200

    token = login(client)
    orders_after = client.get('/api/v1/orders?limit=200', headers={'Authorization': f'Bearer {token}'}).json()
    order_after = next((o for o in orders_after if o['signal_id'] == signal_id), None)
    assert order_after is not None
    assert order_after['filled_quantity'] == 100
    assert order_after['status'] == 'FILLED'


def test_report_trade_rejects_broker_order_id_from_other_client_account(client):
    idem = f'idem_trade_broker_scope_{int(time.time() * 1000)}'
    signal_resp = send_signal(client, idempotency_key=idem, symbol='000001.SZ', quantity=100, amount=12000)
    signal_id = signal_resp['signal_id']

    claim = client.post(
        '/api/v1/client/tasks/claim',
        json={
            'client_id': 'client_win_001',
            'account_id': 'acc_stock_main',
            'max_tasks': 20,
            'capabilities': ['ORDER', 'CANCEL'],
            'version': '0.1.0',
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert claim.status_code == 200
    task = next((item for item in claim.json()['tasks'] if item['signal_id'] == signal_id), None)
    assert task is not None

    report = client.post(
        f"/api/v1/client/tasks/{task['task_id']}/report",
        json={
            'client_id': 'client_win_001',
            'status': 'SUBMITTED',
            'broker_order_id': 'broker_20001',
            'message': 'ok',
            'filled_quantity': 0,
            'avg_price': 0,
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert report.status_code == 200

    heartbeat = client.post(
        '/api/v1/client/heartbeat',
        json={
            'client_id': 'client_other_account',
            'account_id': 'acc_stock_other',
            'version': '0.1.0',
            'capabilities': ['ORDER', 'CANCEL'],
            'last_error': None,
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert heartbeat.status_code == 200

    trade_report = client.post(
        '/api/v1/client/trades/report',
        json={
            'client_id': 'client_other_account',
            'broker_order_id': 'broker_20001',
            'broker_trade_id': f'trd_broker_scope_{int(time.time() * 1000)}',
            'quantity': 100,
            'price': 12,
        },
        headers={'X-Client-Token': 'client-dev-token'},
    )
    assert trade_report.status_code == 404
