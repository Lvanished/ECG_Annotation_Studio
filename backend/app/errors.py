from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    """Domain error translated to an HTTP response by ``main.py``."""

    def __init__(self, status: int, message: str, **details: Any):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details


def not_found(what: str) -> ServiceError:
    return ServiceError(404, f"{what} not found")
