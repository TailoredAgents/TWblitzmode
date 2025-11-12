#!/usr/bin/env python3
from __future__ import annotations
"""
Enterprise Error Handling Framework - September 2025 Production Hardening
Centralized error handling with classification, recovery patterns, and observability

Addresses Critical Issues:
- 455+ instances of generic exception handling
- Poor error recovery patterns
- Inadequate error logging and correlation
- No structured error classification
"""

import asyncio
import inspect
import logging
import traceback
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type, Union
import json

# Import agent logger for real-time error communication
try:
    from .agent_logger import agent_logger, AgentEventType, LogLevel
    agent_logging_available = True
except ImportError:
    logging.warning("Agent logger not available in error handling framework")
    agent_logging_available = False

logger = logging.getLogger(__name__)

class ErrorCategory(Enum):
    """Error categories for classification"""
    TRANSIENT = "transient"  # Temporary failures (network, timeout)
    PERMANENT = "permanent"  # Permanent failures (validation, auth)
    CONFIGURATION = "configuration"  # Configuration issues
    DEPENDENCY = "dependency"  # External service failures
    RESOURCE = "resource"  # Resource exhaustion (memory, disk)
    SECURITY = "security"  # Security-related errors
    BUSINESS_LOGIC = "business_logic"  # Business rule violations
    UNKNOWN = "unknown"  # Unclassified errors

class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class RetryStrategy(Enum):
    """Retry strategies for different error types"""
    NO_RETRY = "no_retry"
    IMMEDIATE = "immediate"
    LINEAR_BACKOFF = "linear_backoff"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    FIXED_INTERVAL = "fixed_interval"

@dataclass
class ErrorContext:
    """Comprehensive error context for debugging and recovery"""
    error_id: str
    timestamp: datetime
    category: ErrorCategory
    severity: ErrorSeverity
    retry_strategy: RetryStrategy

    # Error details
    error_type: str
    error_message: str
    error_code: Optional[str] = None
    stack_trace: Optional[str] = None

    # Context information
    service_name: str = "unknown"
    function_name: str = "unknown"
    workflow_id: Optional[str] = None
    organization_id: Optional[int] = None
    user_id: Optional[int] = None

    # Request context
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    request_data: Optional[Dict[str, Any]] = None

    # Recovery information
    retry_count: int = 0
    max_retries: int = 0
    recovery_suggestions: List[str] = field(default_factory=list)

    # Metadata
    environment: str = "production"
    version: str = "unknown"
    additional_data: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RetryConfig:
    """Configuration for retry behavior"""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retriable_exceptions: tuple = (Exception,)

class ErrorClassifier:
    """Classifies errors into categories and determines retry strategies"""

    # Error classification rules
    CLASSIFICATION_RULES = {
        # Transient errors - usually retriable
        "ConnectionError": (ErrorCategory.TRANSIENT, ErrorSeverity.MEDIUM, RetryStrategy.EXPONENTIAL_BACKOFF),
        "TimeoutError": (ErrorCategory.TRANSIENT, ErrorSeverity.MEDIUM, RetryStrategy.EXPONENTIAL_BACKOFF),
        "asyncio.TimeoutError": (ErrorCategory.TRANSIENT, ErrorSeverity.MEDIUM, RetryStrategy.EXPONENTIAL_BACKOFF),
        "ConnectionRefusedError": (ErrorCategory.DEPENDENCY, ErrorSeverity.HIGH, RetryStrategy.EXPONENTIAL_BACKOFF),
        "OSError": (ErrorCategory.TRANSIENT, ErrorSeverity.MEDIUM, RetryStrategy.LINEAR_BACKOFF),

        # Database errors
        "asyncpg.PostgresError": (ErrorCategory.DEPENDENCY, ErrorSeverity.HIGH, RetryStrategy.EXPONENTIAL_BACKOFF),
        "asyncpg.ConnectionDoesNotExistError": (ErrorCategory.TRANSIENT, ErrorSeverity.HIGH, RetryStrategy.EXPONENTIAL_BACKOFF),
        "asyncpg.TooManyConnectionsError": (ErrorCategory.RESOURCE, ErrorSeverity.CRITICAL, RetryStrategy.LINEAR_BACKOFF),
        "asyncpg.InterfaceError": (ErrorCategory.CONFIGURATION, ErrorSeverity.HIGH, RetryStrategy.NO_RETRY),

        # HTTP errors
        "aiohttp.ClientTimeout": (ErrorCategory.TRANSIENT, ErrorSeverity.MEDIUM, RetryStrategy.EXPONENTIAL_BACKOFF),
        "aiohttp.ClientConnectionError": (ErrorCategory.TRANSIENT, ErrorSeverity.MEDIUM, RetryStrategy.EXPONENTIAL_BACKOFF),
        "aiohttp.ServerDisconnectedError": (ErrorCategory.TRANSIENT, ErrorSeverity.MEDIUM, RetryStrategy.EXPONENTIAL_BACKOFF),

        # Redis errors
        "redis.ConnectionError": (ErrorCategory.DEPENDENCY, ErrorSeverity.HIGH, RetryStrategy.EXPONENTIAL_BACKOFF),
        "redis.TimeoutError": (ErrorCategory.TRANSIENT, ErrorSeverity.MEDIUM, RetryStrategy.LINEAR_BACKOFF),

        # Business logic errors - usually not retriable
        "ValueError": (ErrorCategory.BUSINESS_LOGIC, ErrorSeverity.MEDIUM, RetryStrategy.NO_RETRY),
        "TypeError": (ErrorCategory.BUSINESS_LOGIC, ErrorSeverity.MEDIUM, RetryStrategy.NO_RETRY),
        "KeyError": (ErrorCategory.BUSINESS_LOGIC, ErrorSeverity.MEDIUM, RetryStrategy.NO_RETRY),
        "AttributeError": (ErrorCategory.BUSINESS_LOGIC, ErrorSeverity.MEDIUM, RetryStrategy.NO_RETRY),

        # Security errors
        "PermissionError": (ErrorCategory.SECURITY, ErrorSeverity.HIGH, RetryStrategy.NO_RETRY),
        "AuthenticationError": (ErrorCategory.SECURITY, ErrorSeverity.HIGH, RetryStrategy.NO_RETRY),
        "AuthorizationError": (ErrorCategory.SECURITY, ErrorSeverity.HIGH, RetryStrategy.NO_RETRY),

        # Resource errors
        "MemoryError": (ErrorCategory.RESOURCE, ErrorSeverity.CRITICAL, RetryStrategy.NO_RETRY),
        "FileNotFoundError": (ErrorCategory.CONFIGURATION, ErrorSeverity.HIGH, RetryStrategy.NO_RETRY),

        # Configuration errors
        "ImportError": (ErrorCategory.CONFIGURATION, ErrorSeverity.CRITICAL, RetryStrategy.NO_RETRY),
        "ModuleNotFoundError": (ErrorCategory.CONFIGURATION, ErrorSeverity.CRITICAL, RetryStrategy.NO_RETRY),
    }

    @classmethod
    def classify_error(cls, error: Exception) -> tuple[ErrorCategory, ErrorSeverity, RetryStrategy]:
        """Classify an error and determine appropriate handling strategy"""

        error_type = f"{error.__class__.__module__}.{error.__class__.__name__}"
        error_name = error.__class__.__name__

        # Try full module path first
        if error_type in cls.CLASSIFICATION_RULES:
            return cls.CLASSIFICATION_RULES[error_type]

        # Try just the class name
        if error_name in cls.CLASSIFICATION_RULES:
            return cls.CLASSIFICATION_RULES[error_name]

        # Check inheritance hierarchy
        for base_class in inspect.getmro(error.__class__)[1:]:  # Skip the class itself
            base_name = f"{base_class.__module__}.{base_class.__name__}"
            if base_name in cls.CLASSIFICATION_RULES:
                return cls.CLASSIFICATION_RULES[base_name]

            if base_class.__name__ in cls.CLASSIFICATION_RULES:
                return cls.CLASSIFICATION_RULES[base_class.__name__]

        # Default classification
        return ErrorCategory.UNKNOWN, ErrorSeverity.MEDIUM, RetryStrategy.NO_RETRY

class ErrorHandler:
    """Central error handler with recovery strategies"""

    def __init__(self):
        self.error_history: Dict[str, List[ErrorContext]] = {}
        self.circuit_breakers: Dict[str, Dict[str, Any]] = {}

    async def handle_error(self,
                         error: Exception,
                         context: Optional[Dict[str, Any]] = None,
                         service_name: str = "unknown",
                         function_name: str = "unknown") -> ErrorContext:
        """Handle an error with full context and recovery suggestions"""

        # Generate unique error ID for tracking
        error_id = str(uuid.uuid4())

        # Classify the error
        category, severity, retry_strategy = ErrorClassifier.classify_error(error)

        # Create error context
        error_context = ErrorContext(
            error_id=error_id,
            timestamp=datetime.now(timezone.utc),
            category=category,
            severity=severity,
            retry_strategy=retry_strategy,
            error_type=f"{error.__class__.__module__}.{error.__class__.__name__}",
            error_message=str(error),
            stack_trace=traceback.format_exc(),
            service_name=service_name,
            function_name=function_name
        )

        # Add context information if provided
        if context:
            error_context.workflow_id = context.get('workflow_id')
            error_context.organization_id = context.get('organization_id')
            error_context.user_id = context.get('user_id')
            error_context.request_id = context.get('request_id')
            error_context.correlation_id = context.get('correlation_id')
            error_context.request_data = context.get('request_data')
            error_context.additional_data = context.get('additional_data', {})

        # Generate recovery suggestions
        error_context.recovery_suggestions = self._generate_recovery_suggestions(error_context)

        # Log the error
        await self._log_error(error_context)

        # Track error history
        self._track_error_history(error_context)

        # Update circuit breaker if applicable
        self._update_circuit_breaker(error_context)

        return error_context

    def _generate_recovery_suggestions(self, error_context: ErrorContext) -> List[str]:
        """Generate contextual recovery suggestions"""

        suggestions = []

        # Category-specific suggestions
        if error_context.category == ErrorCategory.TRANSIENT:
            suggestions.extend([
                "Retry the operation with exponential backoff",
                "Check network connectivity",
                "Verify service dependencies are available"
            ])

        elif error_context.category == ErrorCategory.DEPENDENCY:
            suggestions.extend([
                "Check external service health",
                "Verify API keys and authentication",
                "Review rate limiting status",
                "Consider fallback mechanisms"
            ])

        elif error_context.category == ErrorCategory.RESOURCE:
            suggestions.extend([
                "Monitor system resources (CPU, memory, disk)",
                "Check connection pool sizes",
                "Review concurrent operation limits",
                "Consider scaling resources"
            ])

        elif error_context.category == ErrorCategory.CONFIGURATION:
            suggestions.extend([
                "Verify configuration files",
                "Check environment variables",
                "Validate service dependencies",
                "Review deployment configuration"
            ])

        elif error_context.category == ErrorCategory.SECURITY:
            suggestions.extend([
                "Verify authentication credentials",
                "Check authorization permissions",
                "Review security policies",
                "Audit access logs"
            ])

        # Error-specific suggestions
        if "timeout" in error_context.error_message.lower():
            suggestions.append("Increase timeout values if appropriate")

        if "connection" in error_context.error_message.lower():
            suggestions.extend([
                "Check database/service availability",
                "Verify network connectivity",
                "Review connection pool configuration"
            ])

        if "rate limit" in error_context.error_message.lower():
            suggestions.extend([
                "Implement request throttling",
                "Review API usage patterns",
                "Consider request batching"
            ])

        return suggestions

    async def _log_error(self, error_context: ErrorContext):
        """Log error with appropriate level and structured format"""

        log_data = {
            "error_id": error_context.error_id,
            "category": error_context.category.value,
            "severity": error_context.severity.value,
            "service": error_context.service_name,
            "function": error_context.function_name,
            "error_type": error_context.error_type,
            "error_message": error_context.error_message,
            "workflow_id": error_context.workflow_id,
            "organization_id": error_context.organization_id,
            "correlation_id": error_context.correlation_id,
            "retry_strategy": error_context.retry_strategy.value,
            "suggestions": error_context.recovery_suggestions
        }

        # Choose log level based on severity
        log_message = f"[{error_context.error_id}] {error_context.error_message}"

        if error_context.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_message, extra=log_data)
        elif error_context.severity == ErrorSeverity.HIGH:
            logger.error(log_message, extra=log_data)
        elif error_context.severity == ErrorSeverity.MEDIUM:
            logger.warning(log_message, extra=log_data)
        else:
            logger.info(log_message, extra=log_data)

        # Also log stack trace for debugging
        if error_context.stack_trace and error_context.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            logger.debug(f"Stack trace for {error_context.error_id}:\n{error_context.stack_trace}")

        # Send real-time error communication via agent logger
        if agent_logging_available and error_context.organization_id and error_context.severity in [ErrorSeverity.MEDIUM, ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            await self._send_agent_error_notification(error_context)

    def _track_error_history(self, error_context: ErrorContext):
        """Track error history for pattern analysis"""

        key = f"{error_context.service_name}:{error_context.function_name}:{error_context.error_type}"

        if key not in self.error_history:
            self.error_history[key] = []

        self.error_history[key].append(error_context)

        # Keep only recent errors (last 100 per key)
        if len(self.error_history[key]) > 100:
            self.error_history[key] = self.error_history[key][-100:]

    async def _send_agent_error_notification(self, error_context: ErrorContext):
        """Send user-friendly error notification via agent logger"""
        try:
            # Create user-friendly error message
            user_friendly_message = self._create_user_friendly_message(error_context)

            # Determine log level based on severity
            if error_context.severity == ErrorSeverity.CRITICAL:
                log_level = LogLevel.CRITICAL
            elif error_context.severity == ErrorSeverity.HIGH:
                log_level = LogLevel.ERROR
            elif error_context.severity == ErrorSeverity.MEDIUM:
                log_level = LogLevel.WARNING
            else:
                log_level = LogLevel.INFO

            # Send recovery attempt notification
            await agent_logger.log_recovery_attempt(
                agent_id=error_context.service_name,
                error_type=error_context.category.value,
                recovery_action=self._get_primary_recovery_action(error_context),
                details={
                    "error_id": error_context.error_id,
                    "user_friendly_message": user_friendly_message,
                    "error_category": error_context.category.value,
                    "retry_strategy": error_context.retry_strategy.value,
                    "recovery_suggestions": error_context.recovery_suggestions[:3],  # Top 3 suggestions
                    "function_context": error_context.function_name
                },
                tenant_id=str(error_context.organization_id),
                user_id=str(error_context.user_id) if error_context.user_id else None,
                workflow_id=error_context.workflow_id
            )

        except Exception as e:
            logger.error(f"Failed to send agent error notification: {e}")

    def _create_user_friendly_message(self, error_context: ErrorContext) -> str:
        """Create executive-friendly error message"""
        service_name = error_context.service_name.replace("_", " ").title()

        if error_context.category == ErrorCategory.TRANSIENT:
            return f"{service_name} experienced a temporary issue. Retrying automatically."
        elif error_context.category == ErrorCategory.DEPENDENCY:
            return f"{service_name} is unable to connect to an external service. Checking alternatives."
        elif error_context.category == ErrorCategory.RESOURCE:
            return f"{service_name} is experiencing high load. Optimizing resource usage."
        elif error_context.category == ErrorCategory.CONFIGURATION:
            return f"{service_name} has a configuration issue. Admin attention required."
        elif error_context.category == ErrorCategory.SECURITY:
            return f"{service_name} encountered a security validation issue. Checking credentials."
        elif error_context.category == ErrorCategory.BUSINESS_LOGIC:
            return f"{service_name} detected an unexpected data condition. Reviewing business rules."
        else:
            return f"{service_name} encountered an issue. Technical team investigating."

    def _get_primary_recovery_action(self, error_context: ErrorContext) -> str:
        """Get the primary recovery action for the error"""
        if error_context.recovery_suggestions:
            return error_context.recovery_suggestions[0]
        elif error_context.retry_strategy != RetryStrategy.NO_RETRY:
            return f"Automatic retry with {error_context.retry_strategy.value} strategy"
        else:
            return "Manual intervention required"

    def _update_circuit_breaker(self, error_context: ErrorContext):
        """Update circuit breaker state for dependency failures"""

        if error_context.category == ErrorCategory.DEPENDENCY:
            service_key = f"{error_context.service_name}:{error_context.function_name}"

            if service_key not in self.circuit_breakers:
                self.circuit_breakers[service_key] = {
                    "failure_count": 0,
                    "last_failure": None,
                    "state": "closed"  # closed, open, half_open
                }

            breaker = self.circuit_breakers[service_key]
            breaker["failure_count"] += 1
            breaker["last_failure"] = error_context.timestamp

            # Open circuit breaker after 5 failures
            if breaker["failure_count"] >= 5 and breaker["state"] == "closed":
                breaker["state"] = "open"
                logger.warning(f"Circuit breaker opened for {service_key}")

    def get_error_stats(self, service_name: Optional[str] = None) -> Dict[str, Any]:
        """Get error statistics for monitoring"""

        stats = {
            "total_errors": 0,
            "errors_by_category": {},
            "errors_by_severity": {},
            "circuit_breakers": {},
            "recent_errors": []
        }

        # Count errors
        for key, errors in self.error_history.items():
            if service_name and not key.startswith(f"{service_name}:"):
                continue

            for error in errors:
                stats["total_errors"] += 1

                # Category stats
                category = error.category.value
                stats["errors_by_category"][category] = stats["errors_by_category"].get(category, 0) + 1

                # Severity stats
                severity = error.severity.value
                stats["errors_by_severity"][severity] = stats["errors_by_severity"].get(severity, 0) + 1

                # Recent errors (last hour)
                if error.timestamp > datetime.now(timezone.utc) - timedelta(hours=1):
                    stats["recent_errors"].append({
                        "error_id": error.error_id,
                        "timestamp": error.timestamp.isoformat(),
                        "category": error.category.value,
                        "severity": error.severity.value,
                        "service": error.service_name,
                        "function": error.function_name,
                        "message": error.error_message
                    })

        # Circuit breaker stats
        stats["circuit_breakers"] = {
            key: {
                "state": breaker["state"],
                "failure_count": breaker["failure_count"],
                "last_failure": breaker["last_failure"].isoformat() if breaker["last_failure"] else None
            }
            for key, breaker in self.circuit_breakers.items()
        }

        return stats

# Global error handler instance
error_handler = ErrorHandler()

class RetryManager:
    """Manages retry logic with different strategies"""

    @staticmethod
    async def retry_with_strategy(
        func: Callable,
        retry_config: RetryConfig,
        retry_strategy: RetryStrategy,
        context: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Execute function with retry strategy"""

        last_exception = None

        for attempt in range(retry_config.max_attempts):
            try:
                # Update context with retry information
                if context:
                    context['retry_attempt'] = attempt + 1
                    context['max_retries'] = retry_config.max_attempts

                # Execute the function
                result = await func() if asyncio.iscoroutinefunction(func) else func()
                return result

            except retry_config.retriable_exceptions as e:
                last_exception = e

                # Log retry attempt
                logger.warning(f"Attempt {attempt + 1} failed: {e}")

                # Don't sleep on the last attempt
                if attempt < retry_config.max_attempts - 1:
                    delay = RetryManager._calculate_delay(attempt, retry_strategy, retry_config)
                    await asyncio.sleep(delay)

            except Exception as e:
                # Non-retriable exception
                await error_handler.handle_error(
                    e,
                    context=context,
                    function_name=func.__name__ if hasattr(func, '__name__') else "unknown"
                )
                raise

        # All retries exhausted
        if last_exception:
            await error_handler.handle_error(
                last_exception,
                context=context,
                function_name=func.__name__ if hasattr(func, '__name__') else "unknown"
            )
            raise last_exception

    @staticmethod
    def _calculate_delay(attempt: int, strategy: RetryStrategy, config: RetryConfig) -> float:
        """Calculate delay based on retry strategy"""

        if strategy == RetryStrategy.NO_RETRY:
            return 0.0

        elif strategy == RetryStrategy.IMMEDIATE:
            return 0.0

        elif strategy == RetryStrategy.FIXED_INTERVAL:
            delay = config.base_delay

        elif strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = config.base_delay * (attempt + 1)

        elif strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = config.base_delay * (config.exponential_base ** attempt)

        else:
            delay = config.base_delay

        # Apply maximum delay limit
        delay = min(delay, config.max_delay)

        # Add jitter to prevent thundering herd
        if config.jitter:
            import random
            delay *= (0.5 + random.random() * 0.5)

        return delay

# Decorators for error handling and retry

def handle_errors(
    service_name: str = None,
    retry_config: RetryConfig = None,
    context_extractor: Callable = None
):
    """Decorator for automatic error handling and retry"""

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Extract context
            context = {}
            if context_extractor:
                try:
                    context = context_extractor(*args, **kwargs)
                except Exception:
                    pass  # Don't fail on context extraction

            # Determine service name
            service = service_name or getattr(func, '__module__', 'unknown').split('.')[-1]

            try:
                # If retry config provided, use retry logic
                if retry_config:
                    category, severity, retry_strategy = ErrorClassifier.classify_error(Exception())

                    async def execute_func():
                        return await func(*args, **kwargs)

                    return await RetryManager.retry_with_strategy(
                        execute_func,
                        retry_config,
                        retry_strategy,
                        context
                    )
                else:
                    # Direct execution without retry
                    return await func(*args, **kwargs)

            except Exception as e:
                # Handle error
                await error_handler.handle_error(
                    e,
                    context=context,
                    service_name=service,
                    function_name=func.__name__
                )
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For synchronous functions, convert to async handling
            import asyncio

            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Create context
                context = {}
                if context_extractor:
                    try:
                        context = context_extractor(*args, **kwargs)
                    except Exception:
                        pass

                service = service_name or getattr(func, '__module__', 'unknown').split('.')[-1]

                # Handle error synchronously
                asyncio.create_task(error_handler.handle_error(
                    e,
                    context=context,
                    service_name=service,
                    function_name=func.__name__
                ))
                raise

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator

def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retriable_exceptions: tuple = (Exception,)
):
    """Decorator for retry logic"""

    retry_config = RetryConfig(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        retriable_exceptions=retriable_exceptions
    )

    return handle_errors(retry_config=retry_config)

@asynccontextmanager
async def error_context(
    service_name: str,
    operation_name: str,
    workflow_id: str = None,
    organization_id: int = None,
    **context_data
):
    """Context manager for error handling"""

    context = {
        'service_name': service_name,
        'operation_name': operation_name,
        'workflow_id': workflow_id,
        'organization_id': organization_id,
        **context_data
    }

    try:
        yield context
    except Exception as e:
        await error_handler.handle_error(
            e,
            context=context,
            service_name=service_name,
            function_name=operation_name
        )
        raise

# Utility functions

async def get_error_dashboard_data() -> Dict[str, Any]:
    """Get comprehensive error data for dashboards"""

    return {
        "error_stats": error_handler.get_error_stats(),
        "circuit_breakers": error_handler.circuit_breakers,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }