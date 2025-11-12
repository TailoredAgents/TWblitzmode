"""Compat shim for legacy imports of :mod:`services.observability`."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_module = import_module("src.services.observability")

configure_observability = getattr(_module, "configure_observability")
instrument_fastapi_app = getattr(_module, "instrument_fastapi_app")
traced = getattr(_module, "traced")

__all__ = [
    "configure_observability",
    "instrument_fastapi_app",
    "traced",
]
