"""Domain errors that map cleanly to API error responses."""

from __future__ import annotations


class RelayError(Exception):
    """Base class for relay domain errors."""


class AuthError(RelayError):
    pass


class ReplayError(RelayError):
    pass


class ValidationError(RelayError):
    pass


class ConflictError(RelayError):
    pass


class NotFoundError(RelayError):
    pass
