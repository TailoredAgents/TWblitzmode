#!/usr/bin/env python3
"""
Enterprise Resilience Patterns - September 2025 Production Hardening
Implements circuit breakers, bulkheads, timeouts, and other resilience patterns

Addresses Critical Issues:
- No circuit breaker protection for external services
- Missing timeout controls for network operations
- No bulkhead isolation for different operation types
- Poor failure cascade prevention
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
from functools import wraps
import threading
import weakref

logger = logging.getLogger(__name__)

class CircuitBreakerState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered

class BulkheadType(Enum):
    """Types of bulkhead isolation"""
    THREAD_POOL = "thread_pool"
    SEMAPHORE = "semaphore"
    QUEUE = "queue"

@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    expected_exception: type = Exception
    success_threshold: int = 3  # Successes needed to close from half-open
    timeout: float = 30.0

@dataclass
class CircuitBreakerMetrics:
    """Circuit breaker metrics"""
    name: str
    state: CircuitBreakerState
    failure_count: int = 0
    success_count: int = 0
    total_requests: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    state_changed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class CircuitBreaker:
    """Circuit breaker implementation with full metrics and monitoring"""

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.metrics = CircuitBreakerMetrics(name=config.name, state=CircuitBreakerState.CLOSED)
        self._lock = threading.RLock()

        logger.info(f"🔌 Created circuit breaker: {config.name}")

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""

        with self._lock:
            self.metrics.total_requests += 1

            # Check if circuit is open
            if self.metrics.state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                else:
                    raise CircuitBreakerOpenError(f"Circuit breaker {self.config.name} is OPEN")

        try:
            # Execute the function with timeout
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.config.timeout)
            else:
                result = func(*args, **kwargs)

            # Record success
            self._record_success()
            return result

        except asyncio.TimeoutError:
            self._record_failure(TimeoutError(f"Operation timed out after {self.config.timeout}s"))
            raise

        except self.config.expected_exception as e:
            self._record_failure(e)
            raise

        except Exception as e:
            # Unexpected exceptions also count as failures
            self._record_failure(e)
            raise

    def _record_success(self):
        """Record successful operation"""
        with self._lock:
            self.metrics.success_count += 1
            self.metrics.last_success_time = datetime.now(timezone.utc)

            if self.metrics.state == CircuitBreakerState.HALF_OPEN:
                if self.metrics.success_count >= self.config.success_threshold:
                    self._transition_to_closed()

    def _record_failure(self, exception: Exception):
        """Record failed operation"""
        with self._lock:
            self.metrics.failure_count += 1
            self.metrics.last_failure_time = datetime.now(timezone.utc)

            if self.metrics.state == CircuitBreakerState.CLOSED:
                if self.metrics.failure_count >= self.config.failure_threshold:
                    self._transition_to_open()

            elif self.metrics.state == CircuitBreakerState.HALF_OPEN:
                self._transition_to_open()

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        if not self.metrics.last_failure_time:
            return True

        time_since_failure = datetime.now(timezone.utc) - self.metrics.last_failure_time
        return time_since_failure.total_seconds() >= self.config.recovery_timeout

    def _transition_to_open(self):
        """Transition circuit breaker to OPEN state"""
        if self.metrics.state != CircuitBreakerState.OPEN:
            logger.warning(f"🔌 Circuit breaker {self.config.name} opened - rejecting requests")
            self.metrics.state = CircuitBreakerState.OPEN
            self.metrics.state_changed_at = datetime.now(timezone.utc)

    def _transition_to_half_open(self):
        """Transition circuit breaker to HALF_OPEN state"""
        logger.info(f"🔌 Circuit breaker {self.config.name} half-open - testing recovery")
        self.metrics.state = CircuitBreakerState.HALF_OPEN
        self.metrics.state_changed_at = datetime.now(timezone.utc)
        self.metrics.success_count = 0  # Reset success counter

    def _transition_to_closed(self):
        """Transition circuit breaker to CLOSED state"""
        logger.info(f"🔌 Circuit breaker {self.config.name} closed - normal operation resumed")
        self.metrics.state = CircuitBreakerState.CLOSED
        self.metrics.state_changed_at = datetime.now(timezone.utc)
        self.metrics.failure_count = 0  # Reset failure counter

    def get_metrics(self) -> CircuitBreakerMetrics:
        """Get current circuit breaker metrics"""
        with self._lock:
            return self.metrics

    def force_open(self):
        """Manually force circuit breaker open"""
        with self._lock:
            self._transition_to_open()
            logger.warning(f"🔌 Circuit breaker {self.config.name} manually forced open")

    def force_close(self):
        """Manually force circuit breaker closed"""
        with self._lock:
            self._transition_to_closed()
            logger.info(f"🔌 Circuit breaker {self.config.name} manually forced closed")

class CircuitBreakerOpenError(Exception):
    """Exception raised when circuit breaker is open"""
    pass

@dataclass
class BulkheadConfig:
    """Configuration for bulkhead isolation"""
    name: str
    bulkhead_type: BulkheadType
    max_concurrent: int = 10
    queue_size: Optional[int] = None
    timeout: float = 30.0

class Bulkhead:
    """Bulkhead implementation for resource isolation"""

    def __init__(self, config: BulkheadConfig):
        self.config = config
        self.active_operations = 0
        self.total_operations = 0
        self.rejected_operations = 0

        if config.bulkhead_type == BulkheadType.SEMAPHORE:
            self.semaphore = asyncio.Semaphore(config.max_concurrent)
        elif config.bulkhead_type == BulkheadType.QUEUE:
            max_size = config.queue_size or config.max_concurrent * 2
            self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)

        logger.info(f"🛡️ Created bulkhead: {config.name} ({config.bulkhead_type.value})")

    @asynccontextmanager
    async def acquire(self):
        """Acquire bulkhead resource"""
        self.total_operations += 1

        if self.config.bulkhead_type == BulkheadType.SEMAPHORE:
            async with self._acquire_semaphore():
                yield

        elif self.config.bulkhead_type == BulkheadType.QUEUE:
            async with self._acquire_queue():
                yield

        else:
            # Thread pool bulkhead would be implemented here
            raise NotImplementedError(f"Bulkhead type {self.config.bulkhead_type} not implemented")

    @asynccontextmanager
    async def _acquire_semaphore(self):
        """Acquire semaphore-based bulkhead"""
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=self.config.timeout)
            self.active_operations += 1
            yield
        except asyncio.TimeoutError:
            self.rejected_operations += 1
            raise BulkheadRejectionError(f"Bulkhead {self.config.name} timeout")
        finally:
            if self.active_operations > 0:
                self.active_operations -= 1
                self.semaphore.release()

    @asynccontextmanager
    async def _acquire_queue(self):
        """Acquire queue-based bulkhead"""
        token = object()  # Unique token for this operation

        try:
            # Try to add to queue
            await asyncio.wait_for(self.queue.put(token), timeout=self.config.timeout)
            self.active_operations += 1

            # Process the operation
            yield

        except asyncio.TimeoutError:
            self.rejected_operations += 1
            raise BulkheadRejectionError(f"Bulkhead {self.config.name} queue full")

        finally:
            if self.active_operations > 0:
                self.active_operations -= 1
                try:
                    self.queue.get_nowait()  # Remove our token
                    self.queue.task_done()
                except asyncio.QueueEmpty:
                    pass

    def get_metrics(self) -> Dict[str, Any]:
        """Get bulkhead metrics"""
        return {
            "name": self.config.name,
            "type": self.config.bulkhead_type.value,
            "max_concurrent": self.config.max_concurrent,
            "active_operations": self.active_operations,
            "total_operations": self.total_operations,
            "rejected_operations": self.rejected_operations,
            "rejection_rate": (self.rejected_operations / max(self.total_operations, 1)) * 100
        }

class BulkheadRejectionError(Exception):
    """Exception raised when bulkhead rejects operation"""
    pass

class TimeoutManager:
    """Centralized timeout management with different strategies"""

    @staticmethod
    async def with_timeout(
        coro_or_func: Union[Callable, Any],
        timeout: float,
        timeout_exception: type = asyncio.TimeoutError,
        *args,
        **kwargs
    ) -> Any:
        """Execute coroutine or function with timeout"""

        if asyncio.iscoroutine(coro_or_func):
            # Already a coroutine
            try:
                return await asyncio.wait_for(coro_or_func, timeout=timeout)
            except asyncio.TimeoutError:
                raise timeout_exception(f"Operation timed out after {timeout}s")

        elif asyncio.iscoroutinefunction(coro_or_func):
            # Coroutine function
            try:
                return await asyncio.wait_for(coro_or_func(*args, **kwargs), timeout=timeout)
            except asyncio.TimeoutError:
                raise timeout_exception(f"Operation timed out after {timeout}s")

        else:
            # Regular function - run in executor
            loop = asyncio.get_event_loop()
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(None, coro_or_func, *args, **kwargs),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                raise timeout_exception(f"Operation timed out after {timeout}s")

class ResilienceManager:
    """Central manager for all resilience patterns"""

    def __init__(self):
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.bulkheads: Dict[str, Bulkhead] = {}
        self._monitoring_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        logger.info("🛡️ Resilience Manager initialized")

    def create_circuit_breaker(self, config: CircuitBreakerConfig) -> CircuitBreaker:
        """Create and register a circuit breaker"""
        if config.name in self.circuit_breakers:
            logger.warning(f"Circuit breaker {config.name} already exists")
            return self.circuit_breakers[config.name]

        circuit_breaker = CircuitBreaker(config)
        self.circuit_breakers[config.name] = circuit_breaker

        # Start monitoring if this is the first circuit breaker
        if len(self.circuit_breakers) == 1:
            self._ensure_monitoring_task()

        return circuit_breaker

    def create_bulkhead(self, config: BulkheadConfig) -> Bulkhead:
        """Create and register a bulkhead"""
        if config.name in self.bulkheads:
            logger.warning(f"Bulkhead {config.name} already exists")
            return self.bulkheads[config.name]

        bulkhead = Bulkhead(config)
        self.bulkheads[config.name] = bulkhead
        self._ensure_monitoring_task()
        return bulkhead

    def get_circuit_breaker(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name"""
        return self.circuit_breakers.get(name)

    def get_bulkhead(self, name: str) -> Optional[Bulkhead]:
        """Get bulkhead by name"""
        return self.bulkheads.get(name)

    def _ensure_monitoring_task(self) -> None:
        """Start the monitoring task when an event loop is available."""
        if self._monitoring_task is not None or not self.circuit_breakers:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("No running event loop; circuit breaker monitoring deferred")
            return

        self._monitoring_task = loop.create_task(self._monitor_circuit_breakers())

    async def _monitor_circuit_breakers(self):
        """Monitor circuit breaker health"""
        while not self._shutdown_event.is_set():
            try:
                for name, cb in self.circuit_breakers.items():
                    metrics = cb.get_metrics()

                    # Log circuit breaker state changes
                    if metrics.state == CircuitBreakerState.OPEN:
                        logger.warning(f"🔌 Circuit breaker {name} is OPEN - {metrics.failure_count} failures")

                await asyncio.sleep(30)  # Check every 30 seconds

            except Exception as e:
                logger.error(f"Circuit breaker monitoring error: {e}")
                await asyncio.sleep(30)

    def get_health_summary(self) -> Dict[str, Any]:
        """Get overall resilience health summary"""
        circuit_breaker_health = {}
        for name, cb in self.circuit_breakers.items():
            metrics = cb.get_metrics()
            circuit_breaker_health[name] = {
                "state": metrics.state.value,
                "failure_count": metrics.failure_count,
                "success_count": metrics.success_count,
                "total_requests": metrics.total_requests,
                "last_failure": metrics.last_failure_time.isoformat() if metrics.last_failure_time else None,
                "last_success": metrics.last_success_time.isoformat() if metrics.last_success_time else None
            }

        bulkhead_health = {}
        for name, bulkhead in self.bulkheads.items():
            bulkhead_health[name] = bulkhead.get_metrics()

        return {
            "circuit_breakers": circuit_breaker_health,
            "bulkheads": bulkhead_health,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def close(self):
        """Shutdown resilience manager"""
        logger.info("🔄 Shutting down Resilience Manager")

        self._shutdown_event.set()

        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        logger.info("✅ Resilience Manager shutdown complete")

# Global resilience manager
resilience_manager = ResilienceManager()

# Decorator functions for easy application of resilience patterns

def with_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    timeout: float = 30.0,
    expected_exception: type = Exception
):
    """Decorator to apply circuit breaker pattern"""

    def decorator(func):
        # Create circuit breaker configuration
        config = CircuitBreakerConfig(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            timeout=timeout,
            expected_exception=expected_exception
        )

        # Get or create circuit breaker
        circuit_breaker = resilience_manager.create_circuit_breaker(config)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await circuit_breaker.call(func, *args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions, we need to run them in async context
            async def async_call():
                return func(*args, **kwargs)

            return asyncio.run(circuit_breaker.call(async_call))

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator

def with_bulkhead(
    name: str,
    max_concurrent: int = 10,
    bulkhead_type: BulkheadType = BulkheadType.SEMAPHORE,
    timeout: float = 30.0
):
    """Decorator to apply bulkhead pattern"""

    def decorator(func):
        # Create bulkhead configuration
        config = BulkheadConfig(
            name=name,
            bulkhead_type=bulkhead_type,
            max_concurrent=max_concurrent,
            timeout=timeout
        )

        # Get or create bulkhead
        bulkhead = resilience_manager.create_bulkhead(config)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            async with bulkhead.acquire():
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions
            async def async_call():
                async with bulkhead.acquire():
                    return func(*args, **kwargs)

            return asyncio.run(async_call())

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator

def with_timeout(timeout: float, exception_type: type = asyncio.TimeoutError):
    """Decorator to apply timeout pattern"""

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await TimeoutManager.with_timeout(func, timeout, exception_type, *args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions
            return asyncio.run(TimeoutManager.with_timeout(func, timeout, exception_type, *args, **kwargs))

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator

def with_full_resilience(
    circuit_breaker_name: str,
    bulkhead_name: str,
    timeout: float = 30.0,
    max_concurrent: int = 10,
    failure_threshold: int = 5
):
    """Decorator to apply full resilience patterns (circuit breaker + bulkhead + timeout)"""

    def decorator(func):
        # Apply all patterns
        func = with_timeout(timeout)(func)
        func = with_bulkhead(bulkhead_name, max_concurrent)(func)
        func = with_circuit_breaker(circuit_breaker_name, failure_threshold, timeout=timeout)(func)
        return func

    return decorator

# Context managers for direct use

@asynccontextmanager
async def circuit_breaker_protection(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    timeout: float = 30.0
):
    """Context manager for circuit breaker protection"""

    config = CircuitBreakerConfig(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        timeout=timeout
    )

    circuit_breaker = resilience_manager.create_circuit_breaker(config)

    # Context manager doesn't execute anything, just provides access
    yield circuit_breaker

@asynccontextmanager
async def bulkhead_protection(
    name: str,
    max_concurrent: int = 10,
    bulkhead_type: BulkheadType = BulkheadType.SEMAPHORE,
    timeout: float = 30.0
):
    """Context manager for bulkhead protection"""

    config = BulkheadConfig(
        name=name,
        bulkhead_type=bulkhead_type,
        max_concurrent=max_concurrent,
        timeout=timeout
    )

    bulkhead = resilience_manager.create_bulkhead(config)

    async with bulkhead.acquire():
        yield

# Factory functions for creating standard resilience configurations

def create_database_resilience() -> Dict[str, Any]:
    """Create standard resilience patterns for database operations"""

    # Database circuit breaker
    db_circuit_breaker = resilience_manager.create_circuit_breaker(
        CircuitBreakerConfig(
            name="database",
            failure_threshold=3,
            recovery_timeout=30.0,
            timeout=10.0,
            expected_exception=Exception
        )
    )

    # Database bulkhead
    db_bulkhead = resilience_manager.create_bulkhead(
        BulkheadConfig(
            name="database",
            bulkhead_type=BulkheadType.SEMAPHORE,
            max_concurrent=20,
            timeout=10.0
        )
    )

    return {
        "circuit_breaker": db_circuit_breaker,
        "bulkhead": db_bulkhead
    }

def create_external_api_resilience(service_name: str) -> Dict[str, Any]:
    """Create standard resilience patterns for external API calls"""

    # API circuit breaker
    api_circuit_breaker = resilience_manager.create_circuit_breaker(
        CircuitBreakerConfig(
            name=f"api_{service_name}",
            failure_threshold=5,
            recovery_timeout=60.0,
            timeout=30.0,
            expected_exception=Exception
        )
    )

    # API bulkhead
    api_bulkhead = resilience_manager.create_bulkhead(
        BulkheadConfig(
            name=f"api_{service_name}",
            bulkhead_type=BulkheadType.SEMAPHORE,
            max_concurrent=10,
            timeout=30.0
        )
    )

    return {
        "circuit_breaker": api_circuit_breaker,
        "bulkhead": api_bulkhead
    }

# Health check functions

async def get_resilience_health() -> Dict[str, Any]:
    """Get comprehensive resilience health information"""
    return resilience_manager.get_health_summary()

async def get_resilience_metrics() -> Dict[str, Any]:
    """Get detailed resilience metrics for monitoring"""

    metrics = {
        "circuit_breakers": {},
        "bulkheads": {},
        "summary": {
            "total_circuit_breakers": len(resilience_manager.circuit_breakers),
            "open_circuit_breakers": 0,
            "total_bulkheads": len(resilience_manager.bulkheads),
            "active_operations": 0
        }
    }

    # Circuit breaker metrics
    for name, cb in resilience_manager.circuit_breakers.items():
        cb_metrics = cb.get_metrics()
        metrics["circuit_breakers"][name] = {
            "state": cb_metrics.state.value,
            "failure_count": cb_metrics.failure_count,
            "success_count": cb_metrics.success_count,
            "total_requests": cb_metrics.total_requests,
            "failure_rate": (cb_metrics.failure_count / max(cb_metrics.total_requests, 1)) * 100,
            "last_failure": cb_metrics.last_failure_time.isoformat() if cb_metrics.last_failure_time else None,
            "last_success": cb_metrics.last_success_time.isoformat() if cb_metrics.last_success_time else None,
            "state_duration": (datetime.now(timezone.utc) - cb_metrics.state_changed_at).total_seconds()
        }

        if cb_metrics.state == CircuitBreakerState.OPEN:
            metrics["summary"]["open_circuit_breakers"] += 1

    # Bulkhead metrics
    for name, bulkhead in resilience_manager.bulkheads.items():
        bulkhead_metrics = bulkhead.get_metrics()
        metrics["bulkheads"][name] = bulkhead_metrics
        metrics["summary"]["active_operations"] += bulkhead_metrics["active_operations"]

    return metrics