"""Compatibility package for legacy imports (services.*)."""

from __future__ import annotations

import os

_SRC_SERVICES = os.path.join(os.path.dirname(__file__), "..", "src", "services")

if os.path.isdir(_SRC_SERVICES) and _SRC_SERVICES not in __path__:  # type: ignore[name-defined]
    __path__.append(_SRC_SERVICES)  # type: ignore[name-defined]
