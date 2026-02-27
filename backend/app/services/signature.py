import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.config import get_settings


def verify_webhook_signature(*, body: bytes, timestamp: str, signature: str, secret: str) -> None:
    settings = get_settings()
    try:
        ts_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='X-Timestamp 非法') from exc

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if abs(now_ms - ts_int) > settings.webhook_ts_tolerance_ms:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='请求时间戳过期')

    digest = hmac.new(secret.encode('utf-8'), body + timestamp.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='签名校验失败')
