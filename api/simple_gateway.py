"""Compatibility shim for the archived simple gateway.

The original implementation now lives in ``legacy.apps.api.simple_gateway``.
This module re-exports it so existing imports keep working while callers
transition to the legacy package.
"""
import sys as _sys
from importlib import import_module as _import_module

_module = _import_module("legacy.apps.api.simple_gateway")
_sys.modules[__name__] = _module
