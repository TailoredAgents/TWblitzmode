#!/usr/bin/env python3
"""
Enterprise Database Pool Manager - September 2025 Production Hardening
Centralized connection pool management with health monitoring and auto-recovery

Addresses Critical Issues:
- Poor connection pool management across services
- Connection exhaustion under load
- No connection health monitoring
- Lack of connection pool metrics
"""

import asyncio
import os
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any, List, Callable
from enum import Enum
import asyncpg
import asyncpg.pool
try:
    from api.tenant_context import get_tenant  # type: ignore
except Exception:  # pragma: no cover
    def get_tenant():
        return None

logger = logging.getLogger(__name__)

class PoolStatus(Enum):
    """Connection pool status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    RECOVERING = "recovering"

@dataclass
class PoolMetrics:
    """Connection pool performance metrics"""
    pool_name: str
    status: PoolStatus

    # Connection counts
    size: int = 0
    max_size: int = 0
    min_size: int = 0
    free_connections: int = 0
    used_connections: int = 0

    # Performance metrics
    total_connections_created: int = 0
    total_connections_closed: int = 0
    total_queries_executed: int = 0
    avg_query_time_ms: float = 0.0

    # Health metrics
    last_health_check: Optional[datetime] = None
    consecutive_failures: int = 0
    uptime_seconds: float = 0.0

    # Error tracking
    connection_errors: int = 0
    query_errors: int = 0
    timeout_errors: int = 0

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used: Optional[datetime] = None

@dataclass
class PoolConfig:
    """Connection pool configuration"""
    name: str
    database_url: str
    min_size: int = 10
    max_size: int = 50
    command_timeout: float = 30.0
    query_timeout: float = 60.0
    max_inactive_time: float = 300.0
    max_queries: int = 50000
    health_check_interval: int = 30
    retry_attempts: int = 3
    retry_delay: float = 1.0

    # PostgreSQL specific settings
    server_settings: Dict[str, str] = field(default_factory=lambda: {
        'application_name': 'enterprise_pool_manager',
        'tcp_keepalives_idle': '600',
        'tcp_keepalives_interval': '30',
        'tcp_keepalives_count': '3',
        'statement_timeout': '60000',  # 60 seconds
        'idle_in_transaction_session_timeout': '300000',  # 5 minutes
    })

class ConnectionWrapper:
    """Wrapper for asyncpg connections with metrics tracking"""

    def __init__(self, connection: asyncpg.Connection, pool_name: str, metrics_callback: Callable):
        self.connection = connection
        self.pool_name = pool_name
        self.metrics_callback = metrics_callback
        self.acquired_at = time.time()
        self.query_count = 0

    async def execute(self, query: str, *args, timeout: float = None) -> str:
        """Execute query with metrics tracking"""
        start_time = time.time()
        try:
            result = await self.connection.execute(query, *args, timeout=timeout)
            self.query_count += 1

            # Track metrics
            execution_time = (time.time() - start_time) * 1000  # Convert to ms
            await self.metrics_callback('query_executed', execution_time)

            return result
        except Exception as e:
            await self.metrics_callback('query_error', str(e))
            raise

    async def fetch(self, query: str, *args, timeout: float = None) -> List[asyncpg.Record]:
        """Fetch query results with metrics tracking"""
        start_time = time.time()
        try:
            result = await self.connection.fetch(query, *args, timeout=timeout)
            self.query_count += 1

            # Track metrics
            execution_time = (time.time() - start_time) * 1000
            await self.metrics_callback('query_executed', execution_time)

            return result
        except Exception as e:
            await self.metrics_callback('query_error', str(e))
            raise

    async def fetchrow(self, query: str, *args, timeout: float = None) -> Optional[asyncpg.Record]:
        """Fetch single row with metrics tracking"""
        start_time = time.time()
        try:
            result = await self.connection.fetchrow(query, *args, timeout=timeout)
            self.query_count += 1

            # Track metrics
            execution_time = (time.time() - start_time) * 1000
            await self.metrics_callback('query_executed', execution_time)

            return result
        except Exception as e:
            await self.metrics_callback('query_error', str(e))
            raise

    def __getattr__(self, name):
        """Delegate other method calls to the underlying connection"""
        return getattr(self.connection, name)

class EnterpriseConnectionPool:
    """Enterprise-grade connection pool with monitoring and auto-recovery"""

    def __init__(self, config: PoolConfig):
        self.config = config
        self.pool: Optional[asyncpg.pool.Pool] = None
        self.metrics = PoolMetrics(pool_name=config.name, status=PoolStatus.FAILED)

        # Health monitoring
        self._health_check_task: Optional[asyncio.Task] = None
        self._recovery_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Query metrics tracking
        self._query_times: List[float] = []
        self._max_query_history = 1000

        logger.info(f"🏊 Initializing enterprise connection pool: {config.name}")

    async def initialize(self) -> bool:
        """Initialize the connection pool with retry logic"""
        for attempt in range(self.config.retry_attempts):
            try:
                logger.info(f"🔄 Attempting to create pool {self.config.name} (attempt {attempt + 1})")

                self.pool = await asyncpg.create_pool(
                    self.config.database_url,
                    min_size=self.config.min_size,
                    max_size=self.config.max_size,
                    command_timeout=self.config.command_timeout,
                    max_inactive_connection_lifetime=self.config.max_inactive_time,
                    max_queries=self.config.max_queries,
                    server_settings=self.config.server_settings,
                    init=self._init_connection
                )

                # Update metrics
                self.metrics.status = PoolStatus.HEALTHY
                self.metrics.min_size = self.config.min_size
                self.metrics.max_size = self.config.max_size
                self.metrics.size = self.pool.get_size()
                self.metrics.created_at = datetime.now(timezone.utc)

                # Start health monitoring
                self._health_check_task = asyncio.create_task(self._health_monitor())

                logger.info(f"✅ Pool {self.config.name} initialized successfully")
                return True

            except Exception as e:
                logger.error(f"❌ Failed to create pool {self.config.name} (attempt {attempt + 1}): {e}")
                self.metrics.connection_errors += 1

                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(self.config.retry_delay * (2 ** attempt))  # Exponential backoff

        self.metrics.status = PoolStatus.FAILED
        return False

    async def _init_connection(self, conn: asyncpg.Connection):
        """Initialize new connections with custom settings"""
        # Set connection-specific parameters
        await conn.execute("SET statement_timeout = '60s'")
        await conn.execute("SET idle_in_transaction_session_timeout = '300s'")

        # Track connection creation
        self.metrics.total_connections_created += 1

        logger.debug(f"🔗 Initialized new connection for pool {self.config.name}")

    @asynccontextmanager
    async def acquire_connection(self, timeout: float = None):
        """Acquire connection with automatic metrics tracking and error handling"""
        if not self.pool:
            raise RuntimeError(f"Pool {self.config.name} not initialized")

        if self.metrics.status == PoolStatus.FAILED:
            raise RuntimeError(f"Pool {self.config.name} is in failed state")

        connection = None
        acquisition_time = time.time()

        try:
            # Acquire connection from pool
            timeout = timeout or self.config.command_timeout
            connection = await asyncio.wait_for(self.pool.acquire(), timeout=timeout)

            # Set tenant GUCs if context present
            try:
                tenant = get_tenant()
                if tenant:
                    await connection.execute("SELECT set_config('app.current_tenant_id', $1, true)", tenant)
                    await connection.execute("SELECT set_config('app.current_organization_id', $1, true)", tenant)
            except Exception:
                logger.debug("Failed to set tenant GUCs on pooled connection", exc_info=True)

            # Update metrics
            self.metrics.used_connections += 1
            self.metrics.last_used = datetime.now(timezone.utc)

            # Wrap connection for metrics tracking
            wrapped_connection = ConnectionWrapper(
                connection,
                self.config.name,
                self._track_query_metrics
            )

            logger.debug(f"🔗 Acquired connection from pool {self.config.name}")
            yield wrapped_connection

        except asyncio.TimeoutError:
            self.metrics.timeout_errors += 1
            logger.error(f"⏰ Connection acquisition timeout for pool {self.config.name}")
            raise

        except Exception as e:
            self.metrics.connection_errors += 1
            logger.error(f"❌ Failed to acquire connection from pool {self.config.name}: {e}")
            raise

        finally:
            # Release connection back to pool
            if connection:
                try:
                    await self.pool.release(connection)
                    self.metrics.used_connections = max(0, self.metrics.used_connections - 1)

                    # Track connection usage time
                    usage_time = time.time() - acquisition_time
                    logger.debug(f"🔗 Released connection to pool {self.config.name} (used for {usage_time:.2f}s)")

                except Exception as e:
                    logger.error(f"❌ Failed to release connection to pool {self.config.name}: {e}")

    async def _track_query_metrics(self, event_type: str, data: Any):
        """Track query performance metrics"""
        if event_type == 'query_executed':
            execution_time = float(data)
            self._query_times.append(execution_time)

            # Keep only recent query times
            if len(self._query_times) > self._max_query_history:
                self._query_times = self._query_times[-self._max_query_history:]

            # Update metrics
            self.metrics.total_queries_executed += 1
            if self._query_times:
                self.metrics.avg_query_time_ms = sum(self._query_times) / len(self._query_times)

        elif event_type == 'query_error':
            self.metrics.query_errors += 1
            logger.warning(f"Query error in pool {self.config.name}: {data}")

    async def _health_monitor(self):
        """Background health monitoring task"""
        while not self._shutdown_event.is_set():
            try:
                await self._perform_health_check()
                await asyncio.sleep(self.config.health_check_interval)

            except Exception as e:
                logger.error(f"Health monitor error for pool {self.config.name}: {e}")
                await asyncio.sleep(self.config.health_check_interval)

    async def _perform_health_check(self):
        """Perform health check on the connection pool"""
        try:
            # Basic connectivity test
            async with self.acquire_connection(timeout=5.0) as conn:
                await conn.fetchval("SELECT 1")

            # Update pool metrics
            if self.pool:
                self.metrics.size = self.pool.get_size()
                self.metrics.free_connections = self.pool.get_idle_size()
                self.metrics.used_connections = self.metrics.size - self.metrics.free_connections

            # Reset failure counter on successful health check
            if self.metrics.status != PoolStatus.HEALTHY:
                logger.info(f"🏥 Pool {self.config.name} health restored")

            self.metrics.status = PoolStatus.HEALTHY
            self.metrics.consecutive_failures = 0
            self.metrics.last_health_check = datetime.now(timezone.utc)
            self.metrics.uptime_seconds = (datetime.now(timezone.utc) - self.metrics.created_at).total_seconds()

        except Exception as e:
            self.metrics.consecutive_failures += 1
            logger.warning(f"🏥 Health check failed for pool {self.config.name}: {e}")

            # Update status based on failure count
            if self.metrics.consecutive_failures >= 3:
                self.metrics.status = PoolStatus.FAILED

                # Start recovery process
                if not self._recovery_task or self._recovery_task.done():
                    self._recovery_task = asyncio.create_task(self._recover_pool())

            elif self.metrics.consecutive_failures >= 1:
                self.metrics.status = PoolStatus.DEGRADED

    async def _recover_pool(self):
        """Attempt to recover a failed connection pool"""
        logger.info(f"🔄 Starting recovery for pool {self.config.name}")
        self.metrics.status = PoolStatus.RECOVERING

        try:
            # Close existing pool
            if self.pool:
                await self.pool.close()
                self.pool = None

            # Wait before attempting recovery
            await asyncio.sleep(5.0)

            # Attempt to reinitialize
            success = await self.initialize()

            if success:
                logger.info(f"✅ Pool {self.config.name} recovered successfully")
            else:
                logger.error(f"❌ Failed to recover pool {self.config.name}")

        except Exception as e:
            logger.error(f"❌ Recovery failed for pool {self.config.name}: {e}")
            self.metrics.status = PoolStatus.FAILED

    def get_metrics(self) -> PoolMetrics:
        """Get current pool metrics"""
        # Update real-time metrics if pool is available
        if self.pool:
            self.metrics.size = self.pool.get_size()
            self.metrics.free_connections = self.pool.get_idle_size()
            self.metrics.used_connections = self.metrics.size - self.metrics.free_connections

        return self.metrics

    async def close(self):
        """Gracefully close the connection pool"""
        logger.info(f"🔄 Closing pool {self.config.name}")

        # Signal shutdown to background tasks
        self._shutdown_event.set()

        # Cancel background tasks
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        if self._recovery_task and not self._recovery_task.done():
            self._recovery_task.cancel()
            try:
                await self._recovery_task
            except asyncio.CancelledError:
                pass

        # Close the pool
        if self.pool:
            await self.pool.close()
            self.pool = None

        self.metrics.status = PoolStatus.FAILED
        logger.info(f"✅ Pool {self.config.name} closed")

class DatabasePoolManager:
    """Centralized manager for all database connection pools"""

    def __init__(self):
        self.pools: Dict[str, EnterpriseConnectionPool] = {}
        self._monitoring_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        logger.info("🏊‍♂️ Database Pool Manager initialized")

    async def create_pool(self, config: PoolConfig) -> bool:
        """Create and initialize a new connection pool"""
        if config.name in self.pools:
            logger.warning(f"Pool {config.name} already exists")
            return True

        pool = EnterpriseConnectionPool(config)
        success = await pool.initialize()

        if success:
            self.pools[config.name] = pool
            logger.info(f"✅ Created pool {config.name}")

            # Start monitoring if this is the first pool
            if len(self.pools) == 1:
                self._monitoring_task = asyncio.create_task(self._monitor_pools())

        return success

    def get_pool(self, name: str) -> Optional[EnterpriseConnectionPool]:
        """Get a connection pool by name"""
        return self.pools.get(name)

    @asynccontextmanager
    async def get_connection(self, pool_name: str, timeout: float = None):
        """Get a connection from the specified pool"""
        pool = self.get_pool(pool_name)
        if not pool:
            raise ValueError(f"Pool {pool_name} not found")

        async with pool.acquire_connection(timeout=timeout) as conn:
            yield conn

    def get_all_metrics(self) -> Dict[str, PoolMetrics]:
        """Get metrics for all pools"""
        return {name: pool.get_metrics() for name, pool in self.pools.items()}

    def get_health_summary(self) -> Dict[str, Any]:
        """Get overall health summary of all pools"""
        total_pools = len(self.pools)
        healthy_pools = sum(1 for pool in self.pools.values()
                          if pool.get_metrics().status == PoolStatus.HEALTHY)

        return {
            "total_pools": total_pools,
            "healthy_pools": healthy_pools,
            "degraded_pools": sum(1 for pool in self.pools.values()
                                if pool.get_metrics().status == PoolStatus.DEGRADED),
            "failed_pools": sum(1 for pool in self.pools.values()
                              if pool.get_metrics().status == PoolStatus.FAILED),
            "overall_health": "healthy" if healthy_pools == total_pools else
                            "degraded" if healthy_pools > 0 else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def _monitor_pools(self):
        """Background monitoring for all pools"""
        while not self._shutdown_event.is_set():
            try:
                # Log pool statistics every 5 minutes
                health_summary = self.get_health_summary()
                logger.info(f"🏊‍♂️ Pool Health Summary: {health_summary}")

                # Check for any failed pools
                failed_pools = [name for name, pool in self.pools.items()
                              if pool.get_metrics().status == PoolStatus.FAILED]

                if failed_pools:
                    logger.warning(f"🚨 Failed pools detected: {failed_pools}")

                await asyncio.sleep(300)  # Check every 5 minutes

            except Exception as e:
                logger.error(f"Pool monitoring error: {e}")
                await asyncio.sleep(300)

    async def close_all(self):
        """Close all connection pools"""
        logger.info("🔄 Closing all database pools")

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel monitoring task
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        # Close all pools
        for name, pool in self.pools.items():
            try:
                await pool.close()
                logger.info(f"✅ Closed pool {name}")
            except Exception as e:
                logger.error(f"❌ Failed to close pool {name}: {e}")

        self.pools.clear()
        logger.info("✅ All database pools closed")

# Global pool manager instance
db_pool_manager = DatabasePoolManager()

# Convenience function for creating standard pools
async def create_standard_pools():
    """Create standard connection pools for the application"""

    # Main database pool
    import os
    main_pool_config = PoolConfig(
        name="main",
        database_url=os.getenv("DATABASE_URL"),
        min_size=10,
        max_size=50,
        command_timeout=30.0,
        query_timeout=60.0
    )

    # Analytics read-replica pool (using same DB for now)
    analytics_pool_config = PoolConfig(
        name="analytics",
        database_url=os.getenv("DATABASE_URL"),
        min_size=5,
        max_size=20,
        command_timeout=60.0,
        query_timeout=300.0,
        server_settings={
            'application_name': 'analytics_pool',
            'default_transaction_read_only': 'on',  # Read-only for analytics
            'tcp_keepalives_idle': '600',
            'tcp_keepalives_interval': '30',
            'tcp_keepalives_count': '3',
        }
    )

    # Create pools
    success1 = await db_pool_manager.create_pool(main_pool_config)
    success2 = await db_pool_manager.create_pool(analytics_pool_config)

    if success1 and success2:
        logger.info("✅ All standard database pools created successfully")
        return True
    else:
        logger.error("❌ Failed to create some database pools")
        return False

# Convenience function for getting connections
@asynccontextmanager
async def get_main_db_connection():
    """Get connection from main database pool"""
    async with db_pool_manager.get_connection("main") as conn:
        yield conn

@asynccontextmanager
async def get_analytics_db_connection():
    """Get connection from analytics database pool"""
    async with db_pool_manager.get_connection("analytics") as conn:
        yield conn
