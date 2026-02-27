# coding: utf-8
import json
import time
import hmac
import hashlib
import requests

WEBHOOK_URL = "http://localhost:8000/api/v1/signals/webhook"
WEBHOOK_SECRET = "replace-me"   # 和服务端 DEFAULT_WEBHOOK_SECRET 保持一致
SOURCE = "joinquant"
STRATEGY_ID = "jq_alpha_001"
ACCOUNT_ID = "acc_stock_main"


def send_signal(symbol, side, quantity=None, amount=None, signal_type="INCREMENTAL_ORDER", target_position_ratio=None, extra=None):
    payload = {
        "source_platform": SOURCE,
        "strategy_id": STRATEGY_ID,
        "account_id": ACCOUNT_ID,
        "signal_type": signal_type,                 # INCREMENTAL_ORDER / TARGET_POSITION
        "idempotency_key": "jq_%d_%s_%s" % (int(time.time() * 1000), symbol, side),
        "symbol": symbol,                           # 例如 600519.SH / 000001.SZ
        "side": side,                               # BUY / SELL
        "order_style": "MARKET",                    # MARKET / LIMIT
        "quantity": quantity,
        "amount": amount,
        "target_position_ratio": target_position_ratio,
        "timestamp_ms": int(time.time() * 1000),
        "extra": extra or {}
    }

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time() * 1000))
    sig = hmac.new(WEBHOOK_SECRET.encode("utf-8"), body + ts.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Signature": sig,
        "X-Timestamp": ts,
        "X-Source": SOURCE
    }

    resp = requests.post(WEBHOOK_URL, data=body, headers=headers, timeout=8)
    print("signal resp: status=%s body=%s", resp.status_code, resp.text)

def trade_logic():
    # 示例1：增量买入 100 股
    send_signal(
        symbol="600519.SH",
        side="BUY",
        quantity=100,
        amount=20000,
        signal_type="INCREMENTAL_ORDER",
        extra={"reference_price": 200}
    )

    # 示例2：目标仓位到 30%
    # send_signal(
    #     symbol="510300.SH",
    #     side="BUY",
    #     signal_type="TARGET_POSITION",
    #     target_position_ratio=0.30,
    #     extra={"reference_price": 4.2}
    # )


if __name__ == '__main__':
    trade_logic()
