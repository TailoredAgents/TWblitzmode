"""Database monitoring utilities - stub implementation"""
import logging

logger = logging.getLogger(__name__)


def log_slow_query(query: str, duration_ms: float, params=None):
    """Log slow database queries for monitoring purposes."""
    logger.warning(
        f"Slow query detected ({duration_ms:.2f}ms): {query[:200]}",
        extra={"duration_ms": duration_ms, "params": params}
    )
