import hashlib
import hmac
import json
import time

import requests

API = 'http://localhost:8000/api/v1/signals/webhook'
SECRET = 'replace-me'

payload = {
    'source_platform': 'joinquant',
    'strategy_id': 'default_strategy',
    'account_id': 'acc_stock_main',
    'signal_type': 'INCREMENTAL_ORDER',
    'idempotency_key': f'jq_{int(time.time())}',
    'symbol': '600519.SH',
    'side': 'BUY',
    'order_style': 'MARKET',
    'quantity': 100,
    'amount': 20000,
    'target_position_ratio': None,
    'timestamp_ms': int(time.time() * 1000),
    'extra': {'reference_price': 200},
}

body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
ts = str(int(time.time() * 1000))
sig = hmac.new(SECRET.encode('utf-8'), body + ts.encode('utf-8'), hashlib.sha256).hexdigest()

headers = {
    'Content-Type': 'application/json',
    'X-Signature': sig,
    'X-Timestamp': ts,
    'X-Source': 'joinquant',
}

resp = requests.post(API, data=body, headers=headers, timeout=10)
print(resp.status_code, resp.text)
