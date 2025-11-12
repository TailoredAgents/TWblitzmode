"""Compatibility layer exposing the conversational prospects service."""

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.append(str(_SRC_DIR))

from src.services.conversational_prospects import conversational_prospects  # noqa: E402

__all__ = ["conversational_prospects"]