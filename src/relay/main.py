"""Entrypoint for optional FastAPI app."""

from relay.api.fastapi_app import create_app

app = create_app()
