from __future__ import annotations

from datetime import UTC, datetime
import unittest

from relay.domain.exceptions import AuthError, ReplayError
from relay.security.signature import (
    MemoryReplayGuard,
    SignatureConfig,
    SignatureVerifier,
    build_signature,
)


class SignatureVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 2, 4, 10, 0, tzinfo=UTC)
        self.config = SignatureConfig(api_key="k1", hmac_secret="s1", skew_seconds=300)
        self.guard = MemoryReplayGuard()
        self.verifier = SignatureVerifier(self.config, replay_guard=self.guard)

    def test_accepts_valid_signature(self) -> None:
        body = b'{"x":1}'
        headers = self._signed_headers(body=body, request_id="req-1")

        self.verifier.verify(headers=headers, method="POST", path="/api/v1/signals", body=body, now=self.now)

    def test_rejects_replay_request(self) -> None:
        body = b'{"x":1}'
        headers = self._signed_headers(body=body, request_id="req-1")

        self.verifier.verify(headers=headers, method="POST", path="/api/v1/signals", body=body, now=self.now)
        with self.assertRaises(ReplayError):
            self.verifier.verify(headers=headers, method="POST", path="/api/v1/signals", body=body, now=self.now)

    def test_rejects_missing_request_id(self) -> None:
        body = b"{}"
        headers = self._signed_headers(body=body, request_id="")
        headers.pop("X-REQUEST-ID")

        with self.assertRaises(AuthError):
            self.verifier.verify(headers=headers, method="POST", path="/api/v1/signals", body=body, now=self.now)

    def test_rejects_old_timestamp(self) -> None:
        body = b"{}"
        headers = self._signed_headers(body=body, request_id="req-2", timestamp="1738659000")

        with self.assertRaises(AuthError):
            self.verifier.verify(headers=headers, method="POST", path="/api/v1/signals", body=body, now=self.now)

    def _signed_headers(self, *, body: bytes, request_id: str, timestamp: str | None = None) -> dict[str, str]:
        if timestamp is None:
            timestamp = str(int(self.now.timestamp()))
        signature = build_signature(
            secret=self.config.hmac_secret,
            timestamp=timestamp,
            request_id=request_id,
            method="POST",
            path="/api/v1/signals",
            body=body,
        )
        return {
            "X-API-KEY": self.config.api_key,
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": signature,
            "X-REQUEST-ID": request_id,
        }


if __name__ == "__main__":
    unittest.main()
