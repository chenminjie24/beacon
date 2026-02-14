#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
from urllib import error, request
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from relay.security.signature import build_signature  # noqa: E402


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"env file not found: {path}")
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'").strip('"')
    return env


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    now = datetime.now(tz=UTC)
    expire_at = now + timedelta(seconds=args.expire_seconds)
    payload: dict[str, object] = {
        "signal_id": args.signal_id,
        "strategy_id": args.strategy_id,
        "account_id": args.account_id,
        "ts": now.isoformat(),
        "symbol": args.symbol,
        "action": args.action,
        "order_type": args.order_type,
        "max_slippage_bps": args.max_slippage_bps,
        "expire_at": expire_at.isoformat(),
    }
    if args.qty is not None:
        payload["qty"] = args.qty
    if args.amount is not None:
        payload["amount"] = args.amount
    if args.target_pos is not None:
        payload["target_pos"] = args.target_pos
    if args.limit_price is not None:
        payload["limit_price"] = args.limit_price
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send signed signal to relay API")
    parser.add_argument("--env-file", default="deploy/.env", help="Path to env file")
    parser.add_argument("--base-url", default=None, help="Override relay base URL")
    parser.add_argument("--api-key", default=None, help="Override API key")
    parser.add_argument("--hmac-secret", default=None, help="Override HMAC secret")

    parser.add_argument("--signal-id", default="S1")
    parser.add_argument("--strategy-id", default="stg-1")
    parser.add_argument("--account-id", default="acct-1")
    parser.add_argument("--symbol", default="000001.SZ")
    parser.add_argument("--action", default="BUY", choices=["BUY", "SELL"])
    parser.add_argument(
        "--order-type",
        default="MARKET",
        choices=["MARKET", "LIMIT", "TARGET_VALUE", "TARGET_POS"],
    )
    parser.add_argument("--qty", default="100")
    parser.add_argument("--amount", default=None)
    parser.add_argument("--target-pos", default=None)
    parser.add_argument("--limit-price", default=None)
    parser.add_argument("--max-slippage-bps", default=20, type=int)
    parser.add_argument("--expire-seconds", default=300, type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = load_env(REPO_ROOT / args.env_file)

    relay_port = env.get("RELAY_PORT", "8080")
    base_url = args.base_url or env.get("RELAY_BASE_URL") or f"http://localhost:{relay_port}"
    api_key = args.api_key or env.get("API_KEY")
    hmac_secret = args.hmac_secret or env.get("HMAC_SECRET")
    if not api_key or not hmac_secret:
        raise RuntimeError("API_KEY/HMAC_SECRET missing in env or args")

    payload = build_payload(args)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    timestamp = str(int(datetime.now(tz=UTC).timestamp()))
    request_id = str(uuid.uuid4())
    signature = build_signature(
        secret=hmac_secret,
        timestamp=timestamp,
        request_id=request_id,
        method="POST",
        path="/api/v1/signals",
        body=body,
    )

    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": api_key,
        "X-TIMESTAMP": timestamp,
        "X-REQUEST-ID": request_id,
        "X-SIGNATURE": signature,
    }

    url = base_url.rstrip("/") + "/api/v1/signals"
    req = request.Request(url, method="POST", data=body, headers=headers)
    try:
        with request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode("utf-8")
            print(resp_body)
            return 0
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        print(f"HTTP {exc.code}: {detail}")
        return 1
    except error.URLError as exc:
        print(f"Connection error: {exc.reason}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
