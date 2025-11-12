"""
Performance Optimizer - Phase 14: Performance Optimization

Optimizes real-time message handling for high-throughput Communication Hub
operations. Includes message batching, connection pooling, caching, and
performance monitoring for enterprise-scale deployment.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Tuple, Callable
from datetime import datetime, timedelta, timezone
from collections import deque, defaultdict
from dataclasses import dataclass
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
import aiohttp
from enum import Enum

logger = logging.getLogger(__name__)

class OptimizationLevel(Enum):
    """Performance optimization levels"""
    BASIC = "basic"
    STANDARD = "standard"
    AGGRESSIVE = "aggressive"
    ENTERPRISE = "enterprise"

@dataclass
class PerformanceMetrics:
    """Performance tracking metrics"""
    total_messages: int = 0
    batched_messages: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    average_response_time: float = 0.0
    peak_messages_per_second: float = 0.0
    current_connections: int = 0
    failed_operations: int = 0
    memory_usage_mb: float = 0.0
    queue_depth: int = 0

@dataclass
class MessageBatch:
    """Batch of messages for bulk processing"""
    messages: List[Dict[str, Any]]
    organization_id: int
    batch_id: str
    created_at: datetime
    priority: str = "normal"

class MessageCache:
    """High-performance message caching system"""

    def __init__(self, max_size: int = 10000, ttl_seconds: int = 3600):
        self.cache: Dict[str, Tuple[Any, datetime]] = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.access_order = deque()

    def get(self, key: str) -> Optional[Any]:
        """Get cached value with LRU eviction"""
        if key in self.cache:
            value, timestamp = self.cache[key]

            # Check TTL expiration
            if datetime.now(timezone.utc) - timestamp > timedelta(seconds=self.ttl_seconds):
                del self.cache[key]
                return None

            # Update access order for LRU
            if key in self.access_order:
                self.access_order.remove(key)
            self.access_order.append(key)

            return value
        return None

    def set(self, key: str, value: Any):
        """Set cached value with automatic eviction"""
        # Evict expired entries
        self._evict_expired()

        # Evict LRU if at capacity
        if len(self.cache) >= self.max_size and key not in self.cache:
            if self.access_order:
                lru_key = self.access_order.popleft()
                if lru_key in self.cache:
                    del self.cache[lru_key]

        self.cache[key] = (value, datetime.now(timezone.utc))
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)

    def _evict_expired(self):
        """Remove expired cache entries"""
        current_time = datetime.now(timezone.utc)
        expired_keys = []

        for key, (value, timestamp) in self.cache.items():
            if current_time - timestamp > timedelta(seconds=self.ttl_seconds):
                expired_keys.append(key)

        for key in expired_keys:
            del self.cache[key]
            if key in self.access_order:
                self.access_order.remove(key)

class ConnectionPool:
    """High-performance HTTP connection pool"""

    def __init__(self, max_connections: int = 100, max_per_host: int = 30):
        self.connector = None
        self.session = None

        try:
            self.connector = aiohttp.TCPConnector(
                limit=max_connections,
                limit_per_host=max_per_host,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=60,
                enable_cleanup_closed=True,
            )
            self.session = aiohttp.ClientSession(connector=self.connector)
        except RuntimeError:
            # No running event loop (e.g., during import-time initialization in tests).
            # Defer connector/session creation until an event loop is available.
            self.connector = None
            self.session = None

    async def close(self):
        """Clean up connection pool"""
        if self.session is not None:
            await self.session.close()
        if self.connector is not None:
            await self.connector.close()

class PerformanceOptimizer:
    """
    Optimizes Communication Hub performance for enterprise-scale operations

    Features:
    - Message batching for bulk operations
    - Intelligent caching with TTL and LRU eviction
    - Connection pooling for HTTP requests
    - Rate limiting and throttling
    - Performance monitoring and metrics
    - Memory usage optimization
    """

    def __init__(self, optimization_level: OptimizationLevel = OptimizationLevel.STANDARD):
        self.optimization_level = optimization_level
        self.metrics = PerformanceMetrics()
        self.message_cache = MessageCache(
            max_size=self._get_cache_size(),
            ttl_seconds=self._get_cache_ttl()
        )
        self.connection_pool = ConnectionPool(
            max_connections=self._get_max_connections(),
            max_per_host=self._get_max_per_host()
        )

        # Message batching configuration
        self.batch_size = self._get_batch_size()
        self.batch_timeout = self._get_batch_timeout()
        self.pending_batches: Dict[int, MessageBatch] = {}
        self.batch_timers: Dict[int, asyncio.Task] = {}

        # Rate limiting
        self.rate_limiter: Dict[str, deque] = defaultdict(deque)
        self.rate_limits = self._get_rate_limits()

        # Performance monitoring
        self.response_times = deque(maxlen=1000)
        self.message_timestamps = deque(maxlen=1000)

        logger.info(f"Performance optimizer initialized with {optimization_level.value} level")

    def _get_cache_size(self) -> int:
        """Get cache size based on optimization level"""
        sizes = {
            OptimizationLevel.BASIC: 1000,
            OptimizationLevel.STANDARD: 5000,
            OptimizationLevel.AGGRESSIVE: 15000,
            OptimizationLevel.ENTERPRISE: 50000
        }
        return sizes[self.optimization_level]

    def _get_cache_ttl(self) -> int:
        """Get cache TTL based on optimization level"""
        ttls = {
            OptimizationLevel.BASIC: 1800,     # 30 minutes
            OptimizationLevel.STANDARD: 3600,  # 1 hour
            OptimizationLevel.AGGRESSIVE: 7200,  # 2 hours
            OptimizationLevel.ENTERPRISE: 14400  # 4 hours
        }
        return ttls[self.optimization_level]

    def _get_max_connections(self) -> int:
        """Get max connections based on optimization level"""
        connections = {
            OptimizationLevel.BASIC: 20,
            OptimizationLevel.STANDARD: 50,
            OptimizationLevel.AGGRESSIVE: 100,
            OptimizationLevel.ENTERPRISE: 200
        }
        return connections[self.optimization_level]

    def _get_max_per_host(self) -> int:
        """Get max connections per host based on optimization level"""
        per_host = {
            OptimizationLevel.BASIC: 5,
            OptimizationLevel.STANDARD: 15,
            OptimizationLevel.AGGRESSIVE: 30,
            OptimizationLevel.ENTERPRISE: 50
        }
        return per_host[self.optimization_level]

    def _get_batch_size(self) -> int:
        """Get batch size based on optimization level"""
        sizes = {
            OptimizationLevel.BASIC: 5,
            OptimizationLevel.STANDARD: 10,
            OptimizationLevel.AGGRESSIVE: 25,
            OptimizationLevel.ENTERPRISE: 50
        }
        return sizes[self.optimization_level]

    def _get_batch_timeout(self) -> float:
        """Get batch timeout based on optimization level"""
        timeouts = {
            OptimizationLevel.BASIC: 5.0,     # 5 seconds
            OptimizationLevel.STANDARD: 3.0,  # 3 seconds
            OptimizationLevel.AGGRESSIVE: 1.0,  # 1 second
            OptimizationLevel.ENTERPRISE: 0.5   # 500ms
        }
        return timeouts[self.optimization_level]

    def _get_rate_limits(self) -> Dict[str, int]:
        """Get rate limits based on optimization level"""
        limits = {
            OptimizationLevel.BASIC: {'messages_per_minute': 100, 'api_calls_per_minute': 60},
            OptimizationLevel.STANDARD: {'messages_per_minute': 500, 'api_calls_per_minute': 300},
            OptimizationLevel.AGGRESSIVE: {'messages_per_minute': 1000, 'api_calls_per_minute': 600},
            OptimizationLevel.ENTERPRISE: {'messages_per_minute': 5000, 'api_calls_per_minute': 3000}
        }
        return limits[self.optimization_level]

    async def optimize_message_send(
        self,
        message_data: Dict[str, Any],
        organization_id: int,
        priority: str = "normal"
    ) -> Dict[str, Any]:
        """
        Optimize message sending with batching and caching
        """
        start_time = time.time()

        try:
            # Check rate limiting
            if not self._check_rate_limit("messages_per_minute", organization_id):
                return {"success": False, "error": "Rate limit exceeded"}

            # Check cache for duplicate prevention
            message_hash = self._hash_message(message_data)
            cache_key = f"msg:{organization_id}:{message_hash}"

            cached_result = self.message_cache.get(cache_key)
            if cached_result:
                self.metrics.cache_hits += 1
                logger.debug(f"Cache hit for message {cache_key}")
                return cached_result

            self.metrics.cache_misses += 1

            # Add to batch for bulk processing
            if priority == "urgent" or self.optimization_level == OptimizationLevel.BASIC:
                # Send immediately for urgent messages or basic optimization
                result = await self._send_single_message(message_data)
            else:
                # Add to batch for optimized sending
                result = await self._add_to_batch(message_data, organization_id, priority)

            # Cache successful results
            if result.get("success", False):
                self.message_cache.set(cache_key, result)

            # Update metrics
            response_time = time.time() - start_time
            self._update_metrics(response_time, success=result.get("success", False))

            return result

        except Exception as e:
            logger.error(f"Performance optimization error: {e}")
            self.metrics.failed_operations += 1
            return {"success": False, "error": str(e)}

    async def _add_to_batch(
        self,
        message_data: Dict[str, Any],
        organization_id: int,
        priority: str
    ) -> Dict[str, Any]:
        """Add message to batch for bulk processing"""

        # Create or get existing batch for organization
        if organization_id not in self.pending_batches:
            batch_id = f"batch_{organization_id}_{int(time.time())}"
            self.pending_batches[organization_id] = MessageBatch(
                messages=[],
                organization_id=organization_id,
                batch_id=batch_id,
                created_at=datetime.now(timezone.utc),
                priority=priority
            )

            # Set timer to flush batch
            self.batch_timers[organization_id] = asyncio.create_task(
                self._batch_timer(organization_id)
            )

        batch = self.pending_batches[organization_id]
        batch.messages.append(message_data)

        # Flush batch if it reaches size limit
        if len(batch.messages) >= self.batch_size:
            return await self._flush_batch(organization_id)

        # Return pending status
        return {
            "success": True,
            "batched": True,
            "batch_id": batch.batch_id,
            "batch_size": len(batch.messages)
        }

    async def _batch_timer(self, organization_id: int):
        """Timer to flush batch after timeout"""
        await asyncio.sleep(self.batch_timeout)
        if organization_id in self.pending_batches:
            await self._flush_batch(organization_id)

    async def _flush_batch(self, organization_id: int) -> Dict[str, Any]:
        """Flush pending batch for organization"""
        if organization_id not in self.pending_batches:
            return {"success": False, "error": "No pending batch"}

        batch = self.pending_batches[organization_id]
        del self.pending_batches[organization_id]

        # Cancel timer if exists
        if organization_id in self.batch_timers:
            self.batch_timers[organization_id].cancel()
            del self.batch_timers[organization_id]

        # Send batch
        try:
            result = await self._send_message_batch(batch)
            self.metrics.batched_messages += len(batch.messages)
            logger.info(f"Flushed batch {batch.batch_id} with {len(batch.messages)} messages")
            return result
        except Exception as e:
            logger.error(f"Batch flush error: {e}")
            return {"success": False, "error": str(e)}

    async def _send_message_batch(self, batch: MessageBatch) -> Dict[str, Any]:
        """Send a batch of messages efficiently"""

        # Prepare batch payload
        batch_payload = {
            "batch_id": batch.batch_id,
            "organization_id": batch.organization_id,
            "messages": batch.messages,
            "batch_size": len(batch.messages),
            "priority": batch.priority,
            "timestamp": batch.created_at.isoformat()
        }

        # Use connection pool for efficient HTTP request
        async with self.connection_pool.session.post(
            f"http://localhost:8081/api/v1/communication-hub/messages/batch",
            json=batch_payload,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status == 200:
                result = await response.json()
                return {
                    "success": True,
                    "batch_id": batch.batch_id,
                    "messages_sent": len(batch.messages),
                    "result": result
                }
            else:
                error_text = await response.text()
                return {
                    "success": False,
                    "error": f"Batch send failed: {response.status} - {error_text}"
                }

    async def _send_single_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send single message using connection pool"""
        async with self.connection_pool.session.post(
            f"http://localhost:8081/api/v1/communication-hub/messages",
            json=message_data,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status == 200:
                result = await response.json()
                return {"success": True, "result": result}
            else:
                error_text = await response.text()
                return {"success": False, "error": f"HTTP {response.status}: {error_text}"}

    def _check_rate_limit(self, limit_type: str, organization_id: int) -> bool:
        """Check rate limiting for organization"""
        rate_limit = self.rate_limits.get(limit_type, float('inf'))
        rate_key = f"{limit_type}:{organization_id}"
        current_time = time.time()

        # Clean old entries (older than 1 minute)
        while self.rate_limiter[rate_key] and current_time - self.rate_limiter[rate_key][0] > 60:
            self.rate_limiter[rate_key].popleft()

        # Check if under limit
        if len(self.rate_limiter[rate_key]) < rate_limit:
            self.rate_limiter[rate_key].append(current_time)
            return True

        return False

    def _hash_message(self, message_data: Dict[str, Any]) -> str:
        """Create hash for message deduplication"""
        # Use content and recipient for hash
        hash_data = {
            'content': message_data.get('content', ''),
            'recipient_id': message_data.get('recipient_id', ''),
            'message_type': message_data.get('message_type', '')
        }
        hash_string = json.dumps(hash_data, sort_keys=True)
        return hashlib.md5(hash_string.encode()).hexdigest()[:16]

    def _update_metrics(self, response_time: float, success: bool):
        """Update performance metrics"""
        self.metrics.total_messages += 1

        if success:
            self.response_times.append(response_time)
            if self.response_times:
                self.metrics.average_response_time = sum(self.response_times) / len(self.response_times)
        else:
            self.metrics.failed_operations += 1

        # Update message rate tracking
        current_time = time.time()
        self.message_timestamps.append(current_time)

        # Calculate messages per second (last 10 seconds)
        recent_messages = [ts for ts in self.message_timestamps if current_time - ts <= 10]
        if recent_messages:
            messages_per_second = len(recent_messages) / 10
            self.metrics.peak_messages_per_second = max(
                self.metrics.peak_messages_per_second,
                messages_per_second
            )

        # Update queue depth
        self.metrics.queue_depth = sum(len(batch.messages) for batch in self.pending_batches.values())

    def get_performance_report(self) -> Dict[str, Any]:
        """Get comprehensive performance report"""
        return {
            "optimization_level": self.optimization_level.value,
            "metrics": {
                "total_messages": self.metrics.total_messages,
                "batched_messages": self.metrics.batched_messages,
                "cache_hit_rate": (
                    self.metrics.cache_hits / max(1, self.metrics.cache_hits + self.metrics.cache_misses) * 100
                ),
                "average_response_time_ms": self.metrics.average_response_time * 1000,
                "peak_messages_per_second": self.metrics.peak_messages_per_second,
                "current_queue_depth": self.metrics.queue_depth,
                "failed_operations": self.metrics.failed_operations,
                "success_rate": (
                    (self.metrics.total_messages - self.metrics.failed_operations) /
                    max(1, self.metrics.total_messages) * 100
                )
            },
            "configuration": {
                "batch_size": self.batch_size,
                "batch_timeout_seconds": self.batch_timeout,
                "cache_size": self.message_cache.max_size,
                "cache_ttl_seconds": self.message_cache.ttl_seconds,
                "rate_limits": self.rate_limits
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def flush_all_batches(self) -> Dict[str, Any]:
        """Flush all pending batches (useful for shutdown)"""
        results = []

        for org_id in list(self.pending_batches.keys()):
            result = await self._flush_batch(org_id)
            results.append(result)

        return {
            "batches_flushed": len(results),
            "results": results
        }

    async def cleanup(self):
        """Clean up resources"""
        # Flush all pending batches
        await self.flush_all_batches()

        # Close connection pool
        await self.connection_pool.close()

        logger.info("Performance optimizer cleanup completed")

# Global performance optimizer instance
global_performance_optimizer: Optional[PerformanceOptimizer] = None

def get_global_performance_optimizer(
    optimization_level: OptimizationLevel = OptimizationLevel.STANDARD
) -> PerformanceOptimizer:
    """Get or create the global performance optimizer instance"""
    global global_performance_optimizer

    if global_performance_optimizer is None:
        global_performance_optimizer = PerformanceOptimizer(optimization_level)
        logger.info("Global performance optimizer initialized")

    return global_performance_optimizer

async def optimize_message_delivery(
    message_data: Dict[str, Any],
    organization_id: int,
    priority: str = "normal"
) -> Dict[str, Any]:
    """Convenience function for optimized message delivery"""
    optimizer = get_global_performance_optimizer()
    return await optimizer.optimize_message_send(message_data, organization_id, priority)

def get_performance_metrics() -> Dict[str, Any]:
    """Convenience function to get performance metrics"""
    optimizer = get_global_performance_optimizer()
    return optimizer.get_performance_report()