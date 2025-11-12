from __future__ import annotations

"""Minimal Config shim used by legacy modules.

Only includes attributes referenced within this repository.
"""

import os


class Config:
    # Primary database DSN; modules may update this at runtime (e.g., after resolve).
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

