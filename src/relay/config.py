"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    api_key: str
    hmac_secret: str
    db_url: str | None
    app_env: str


def load_settings() -> Settings:
    return Settings(
        api_key=os.getenv("API_KEY", "change_me"),
        hmac_secret=os.getenv("HMAC_SECRET", "change_me_too"),
        db_url=_empty_to_none(os.getenv("DB_URL")),
        app_env=os.getenv("APP_ENV", "dev"),
    )


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
