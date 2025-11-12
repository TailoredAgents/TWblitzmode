"""Centralized logging service - stub implementation"""
import logging
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    """Log severity levels"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogCategory(str, Enum):
    """Log categories for structured logging"""
    SYSTEM = "system"
    SECURITY = "security"
    BUSINESS = "business"
    PERFORMANCE = "performance"
    INTEGRATION = "integration"
    WORKFLOW = "workflow"
    DATABASE = "database"


def log_structured(
    level: LogLevel,
    message: str,
    category: LogCategory = LogCategory.SYSTEM,
    **extra: Any
) -> None:
    """Log structured message with metadata."""
    log_data = {
        "message": message,
        "category": category.value,
        **extra
    }

    log_func = getattr(logger, level.value)
    log_func(message, extra=log_data)
