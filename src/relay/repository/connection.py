"""Connection factory helpers for PostgreSQL adapters."""

from __future__ import annotations

from typing import Any, Callable


def _normalize_psycopg_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+psycopg://"):
        return "postgresql://" + dsn[len("postgresql+psycopg://") :]
    if dsn.startswith("postgresql+psycopg2://"):
        return "postgresql://" + dsn[len("postgresql+psycopg2://") :]
    return dsn


def create_psycopg_connection_factory(dsn: str) -> Callable[[], Any]:
    """Build a lazy psycopg v3 connection factory.

    psycopg is imported lazily so offline tests do not require third-party
    dependencies.
    """

    normalized = _normalize_psycopg_dsn(dsn)

    def _factory() -> Any:
        try:
            import psycopg
        except ModuleNotFoundError as exc:
            raise RuntimeError("psycopg is not installed. Run: pip install '.[db]'") from exc
        return psycopg.connect(normalized)

    return _factory
