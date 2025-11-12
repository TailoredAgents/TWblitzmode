"""Compatibility shim for the archived enterprise gateway.

Refer to ``legacy.apps.api.enterprise_gateway`` for the full implementation.
"""
import sys as _sys
from importlib import import_module as _import_module

_module = _import_module("legacy.apps.api.enterprise_gateway")
_sys.modules[__name__] = _module
