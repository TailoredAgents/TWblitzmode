"""Compatibility shim for the archived unified route orchestrator.

Original module relocated to ``legacy.apps.api.unified_route_orchestrator``.
"""
import sys as _sys
from importlib import import_module as _import_module

_module = _import_module("legacy.apps.api.unified_route_orchestrator")
_sys.modules[__name__] = _module
