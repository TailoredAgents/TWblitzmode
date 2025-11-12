"""`src.services` package with fallback to top-level `services`.

This package exposes shims implemented under `src/services/` while also
searching the repository's top-level `services/` directory for other modules.
"""
from __future__ import annotations

import os
from pathlib import Path

# Extend this package's search path to include the top-level services directory
_pkg_dir = Path(__file__).resolve().parent
_root = _pkg_dir.parent.parent
_services_dir = _root / "services"
if _services_dir.is_dir():
    # This modifies the import search path for this package so that
    # `import src.services.X` will also look in the real `services/` dir.
    __path__.append(str(_services_dir))  # type: ignore[name-defined]

