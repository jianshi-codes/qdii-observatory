"""FastAPI application package."""

from __future__ import annotations

from typing import Any

__all__ = ["app"]


def __getattr__(name: str) -> Any:
    if name == "app":
        from backend.app.main import app

        return app
    raise AttributeError(name)
