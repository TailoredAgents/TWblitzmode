"""
Compatibility shim for application monitoring service imports.

Legacy modules import ``services.application_monitoring_service`` while the
modernized implementation lives under ``src.services``. Importing from this
module keeps both code paths working without duplicating the implementation.
"""

from src.services.application_monitoring_service import (  # noqa: F401
    application_monitoring_service,
    ApplicationMonitoringService,
)

__all__ = ["application_monitoring_service", "ApplicationMonitoringService"]
