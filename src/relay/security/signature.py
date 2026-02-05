"""HMAC signature verification and replay protection."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from relay.domain.exceptions import AuthError, ReplayError


@dataclass(frozen=True)
class SignatureConfig:
    api_key: str
    hmac_secret: str
    skew_seconds: int = 300
    require_request_id: bool = True


class ReplayGuard:
    """Interface for nonce replay checks."""

    def check_and_store(self, nonce: str, now: datetime, ttl_seconds: int) -> None:
        raise NotImplementedError


class MemoryReplayGuard(ReplayGuard):
    """Simple in-memory nonce store used by tests and local development."""

    def __init__(self) -> None:
        self._nonces: dict[str, datetime] = {}

    def check_and_store(self, nonce: str, now: datetime, ttl_seconds: int) -> None:
        self._prune(now)
        if nonce in self._nonces:
            raise ReplayError("replayed request")
        self._nonces[nonce] = now + timedelta(seconds=ttl_seconds)

    def _prune(self, now: datetime) -> None:
        stale = [k for k, expire in self._nonces.items() if expire <= now]
        for key in stale:
            self._nonces.pop(key, None)


class SignatureVerifier:
    """Validates HMAC request signatures.

    Canonical string format:
      <timestamp>\n<request_id>\n<method>\n<path>\n<body_sha256_hex>
    """

    def __init__(self, config: SignatureConfig, replay_guard: ReplayGuard) -> None:
        self._config = config
        self._replay_guard = replay_guard

    def verify(
        self,
        headers: dict[str, str],
        method: str,
        path: str,
        body: bytes,
        now: datetime,
    ) -> None:
        api_key = _get_header(headers, "X-API-KEY")
        timestamp_raw = _get_header(headers, "X-TIMESTAMP")
        signature = _get_header(headers, "X-SIGNATURE")
        request_id = headers.get("X-REQUEST-ID", "").strip()

        if self._config.require_request_id and not request_id:
            raise AuthError("X-REQUEST-ID is required")
        if api_key != self._config.api_key:
            raise AuthError("invalid api key")

        timestamp = _parse_timestamp(timestamp_raw)
        _check_clock_skew(now, timestamp, self._config.skew_seconds)

        expected = _build_signature(
            secret=self._config.hmac_secret,
            timestamp=timestamp_raw,
            request_id=request_id,
            method=method,
            path=path,
            body=body,
        )
        if not hmac.compare_digest(signature.lower(), expected):
            raise AuthError("invalid signature")

        nonce = f"{api_key}:{timestamp_raw}:{request_id}:{signature.lower()}"
        self._replay_guard.check_and_store(nonce=nonce, now=now, ttl_seconds=self._config.skew_seconds)


def build_signature(
    secret: str,
    timestamp: str,
    request_id: str,
    method: str,
    path: str,
    body: bytes,
) -> str:
    """Public helper for clients/tests."""
    return _build_signature(
        secret=secret,
        timestamp=timestamp,
        request_id=request_id,
        method=method,
        path=path,
        body=body,
    )


def _build_signature(
    secret: str,
    timestamp: str,
    request_id: str,
    method: str,
    path: str,
    body: bytes,
) -> str:
    digest = hashlib.sha256(body).hexdigest()
    payload = "\n".join([timestamp, request_id, method.upper(), path, digest])
    mac = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()


def _parse_timestamp(value: str) -> datetime:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise AuthError("X-TIMESTAMP must be unix seconds") from exc
    return datetime.fromtimestamp(seconds, tz=UTC)


def _check_clock_skew(now: datetime, timestamp: datetime, skew_seconds: int) -> None:
    delta = abs((now - timestamp).total_seconds())
    if delta > skew_seconds:
        raise AuthError("timestamp outside allowed window")


def _get_header(headers: dict[str, str], key: str) -> str:
    value = headers.get(key)
    if value is None or not value.strip():
        raise AuthError(f"missing header: {key}")
    return value.strip()
