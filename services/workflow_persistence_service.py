#!/usr/bin/env python3
from __future__ import annotations

"""
Workflow Persistence Service - September 2025 Production Hardening
Robust workflow state management with PostgreSQL + Redis for enterprise reliability

Addresses Critical Issues:
- Workflow state loss on service restart
- Memory-only storage limitations
- No workflow recovery mechanisms
- Poor state management under load
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Union, TYPE_CHECKING
from dataclasses import dataclass, asdict
from contextlib import asynccontextmanager
import os

try:
    import asyncpg  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    asyncpg = None  # type: ignore

try:
    import redis.asyncio as redis  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    redis = None  # type: ignore

logger = logging.getLogger(__name__)

class WorkflowStatus(Enum):
    """Enhanced workflow status enum"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERING = "recovering"
    TIMEOUT = "timeout"

class WorkflowPriority(Enum):
    """Workflow execution priority"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

@dataclass
class WorkflowState:
    """Enhanced workflow state with full persistence support"""
    workflow_id: str
    organization_id: int
    user_id: int
    workflow_type: str
    status: WorkflowStatus
    priority: WorkflowPriority
    current_stage: str
    progress_percentage: float

    # Core data
    prospects: List[Dict[str, Any]]
    team_members: List[Dict[str, Any]]
    results: Dict[str, Any]
    errors: List[Dict[str, Any]]  # Enhanced error tracking
    settings: Dict[str, Any]

    # Persistence metadata
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None

    # Recovery and timeout
    timeout_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3

    # Approval workflow integration
    approval_requests: List[str] = None
    is_paused: bool = False
    pause_reason: Optional[str] = None

    # Performance tracking
    steps_completed: int = 0
    steps_total: int = 7
    execution_time_seconds: float = 0.0

    # Recovery data
    recovery_checkpoint: Optional[Dict[str, Any]] = None
    recovery_metadata: Optional[Dict[str, Any]] = None

class WorkflowPersistenceService:
    """
    Enterprise-grade workflow persistence service
    Implements dual storage pattern: PostgreSQL for durability, Redis for performance
    """

    def __init__(self,
                 database_url: str,
                 redis_url: str = "redis://localhost:6379",
                 pool_min_size: int = 10,
                 pool_max_size: int = 50):
        self.database_url = database_url
        self.redis_url = redis_url
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size

        # Connection pools
        self.db_pool: Optional[asyncpg.Pool] = None
        self.redis_pool: Optional[redis.ConnectionPool] = None
        self.redis_client: Optional[redis.Redis] = None

        # Performance optimization
        self.cache_ttl = 3600  # 1 hour default cache
        self.heartbeat_interval = 30  # 30 seconds
        self.cleanup_interval = 300  # 5 minutes

        # Background tasks
        self._background_tasks: List[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()

    async def initialize(self):
        """Initialize the persistence service with proper connection pooling"""
        try:
            # Initialize PostgreSQL connection pool
            self.db_pool = await asyncpg.create_pool(
                self.database_url,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                command_timeout=30,
                server_settings={
                    'application_name': 'workflow_persistence_service',
                    'tcp_keepalives_idle': '600',
                    'tcp_keepalives_interval': '30',
                    'tcp_keepalives_count': '3',
                }
            )

            # Initialize Redis connection pool
            self.redis_pool = redis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=20,
                decode_responses=True
            )
            self.redis_client = redis.Redis(connection_pool=self.redis_pool)

            # Ensure database schema exists
            await self._ensure_database_schema()

            # Start background maintenance tasks
            await self._start_background_tasks()

            logger.info("✅ Workflow Persistence Service initialized with enterprise connection pooling")

        except Exception as e:
            logger.error(f"❌ Failed to initialize Workflow Persistence Service: {e}")
            raise

    async def create_workflow(self,
                            organization_id: int,
                            user_id: int,
                            workflow_type: str,
                            prospects: List[Dict[str, Any]],
                            team_members: List[Dict[str, Any]],
                            settings: Dict[str, Any] = None,
                            priority: WorkflowPriority = WorkflowPriority.NORMAL,
                            timeout_minutes: int = 1440) -> str:
        """Create a new workflow with full persistence"""

        workflow_id = f"wf_{organization_id}_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        workflow_state = WorkflowState(
            workflow_id=workflow_id,
            organization_id=organization_id,
            user_id=user_id,
            workflow_type=workflow_type,
            status=WorkflowStatus.PENDING,
            priority=priority,
            current_stage="initialization",
            progress_percentage=0.0,
            prospects=prospects,
            team_members=team_members,
            results={},
            errors=[],
            settings=settings or {},
            created_at=now,
            updated_at=now,
            timeout_at=now + timedelta(minutes=timeout_minutes),
            approval_requests=[],
            is_paused=False,
            steps_completed=0,
            steps_total=7,
            execution_time_seconds=0.0,
            retry_count=0,
            max_retries=3
        )

        # Store in both PostgreSQL and Redis
        await self._store_workflow_state(workflow_state)
        await self._cache_workflow_state(workflow_state)

        logger.info(f"📝 Created workflow {workflow_id} for organization {organization_id}")
        return workflow_id

    async def update_workflow_state(self,
                                  workflow_id: str,
                                  status: Optional[WorkflowStatus] = None,
                                  current_stage: Optional[str] = None,
                                  progress_percentage: Optional[float] = None,
                                  results: Optional[Dict[str, Any]] = None,
                                  errors: Optional[List[Dict[str, Any]]] = None,
                                  is_paused: Optional[bool] = None,
                                  pause_reason: Optional[str] = None) -> bool:
        """Update workflow state with optimistic locking"""

        try:
            async with self._get_db_connection() as conn:
                # Get current state with row locking
                current_state = await self._get_workflow_state_locked(conn, workflow_id)
                if not current_state:
                    logger.warning(f"Workflow {workflow_id} not found for update")
                    return False

                # Update fields
                now = datetime.now(timezone.utc)
                if status is not None:
                    current_state.status = status
                    if status == WorkflowStatus.RUNNING and not current_state.started_at:
                        current_state.started_at = now
                    elif status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]:
                        current_state.completed_at = now

                if current_stage is not None:
                    current_state.current_stage = current_stage

                if progress_percentage is not None:
                    current_state.progress_percentage = min(100.0, max(0.0, progress_percentage))

                if results is not None:
                    current_state.results.update(results)

                if errors is not None:
                    current_state.errors.extend(errors)

                if is_paused is not None:
                    current_state.is_paused = is_paused
                    current_state.pause_reason = pause_reason

                current_state.updated_at = now
                current_state.last_heartbeat = now

                # Calculate execution time
                if current_state.started_at:
                    current_state.execution_time_seconds = (now - current_state.started_at).total_seconds()

                # Store updates
                await self._update_workflow_state_db(conn, current_state)
                await self._cache_workflow_state(current_state)

                logger.debug(f"🔄 Updated workflow {workflow_id}: {current_stage or 'state'}")
                return True

        except Exception as e:
            logger.error(f"❌ Failed to update workflow {workflow_id}: {e}")
            return False

    async def get_workflow_state(self, workflow_id: str) -> Optional[WorkflowState]:
        """Get workflow state with Redis cache fallback to PostgreSQL"""

        try:
            # Try Redis cache first for performance
            cached_state = await self._get_cached_workflow_state(workflow_id)
            if cached_state:
                return cached_state

            # Fallback to PostgreSQL
            async with self._get_db_connection() as conn:
                state = await self._get_workflow_state_db(conn, workflow_id)
                if state:
                    # Update cache
                    await self._cache_workflow_state(state)
                return state

        except Exception as e:
            logger.error(f"❌ Failed to get workflow state {workflow_id}: {e}")
            return None

    async def list_active_workflows(self,
                                  organization_id: Optional[int] = None,
                                  status_filter: Optional[List[WorkflowStatus]] = None,
                                  limit: int = 100) -> List[WorkflowState]:
        """List active workflows with filtering"""

        try:
            async with self._get_db_connection() as conn:
                # Build query
                conditions = ["status NOT IN ('completed', 'failed', 'cancelled')"]
                params = []
                param_count = 0

                if organization_id:
                    param_count += 1
                    conditions.append(f"organization_id = ${param_count}")
                    params.append(organization_id)

                if status_filter:
                    param_count += 1
                    status_list = [s.value for s in status_filter]
                    conditions.append(f"status = ANY(${param_count})")
                    params.append(status_list)

                param_count += 1
                params.append(limit)

                query = f"""
                    SELECT * FROM workflow_states
                    WHERE {' AND '.join(conditions)}
                    ORDER BY priority DESC, created_at ASC
                    LIMIT ${param_count}
                """

                rows = await conn.fetch(query, *params)
                return [self._row_to_workflow_state(row) for row in rows]

        except Exception as e:
            logger.error(f"❌ Failed to list active workflows: {e}")
            return []

    async def recover_workflows(self) -> List[str]:
        """Recover workflows after service restart"""

        recovered_workflows = []

        try:
            # Find workflows that were running when service stopped
            async with self._get_db_connection() as conn:
                query = """
                    SELECT workflow_id FROM workflow_states
                    WHERE status IN ('running', 'recovering')
                    AND last_heartbeat < $1
                    ORDER BY priority DESC, created_at ASC
                """

                # Find workflows with stale heartbeats (older than 2 minutes)
                stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=2)
                rows = await conn.fetch(query, stale_threshold)

                for row in rows:
                    workflow_id = row['workflow_id']

                    # Mark as recovering
                    await self.update_workflow_state(
                        workflow_id,
                        status=WorkflowStatus.RECOVERING,
                        current_stage="recovery"
                    )

                    recovered_workflows.append(workflow_id)
                    logger.info(f"🔄 Marked workflow {workflow_id} for recovery")

            if recovered_workflows:
                logger.info(f"🔄 Recovered {len(recovered_workflows)} workflows after service restart")

            return recovered_workflows

        except Exception as e:
            logger.error(f"❌ Failed to recover workflows: {e}")
            return []

    async def create_checkpoint(self,
                              workflow_id: str,
                              checkpoint_data: Dict[str, Any]) -> bool:
        """Create a recovery checkpoint for a workflow"""

        try:
            async with self._get_db_connection() as conn:
                checkpoint_id = f"cp_{uuid.uuid4().hex[:8]}"

                await conn.execute("""
                    INSERT INTO workflow_checkpoints
                    (checkpoint_id, workflow_id, checkpoint_data, created_at)
                    VALUES ($1, $2, $3, $4)
                """, checkpoint_id, workflow_id, json.dumps(checkpoint_data), datetime.now(timezone.utc))

                # Also update the workflow state
                current_state = await self.get_workflow_state(workflow_id)
                if current_state:
                    current_state.recovery_checkpoint = checkpoint_data
                    current_state.recovery_metadata = {
                        "checkpoint_id": checkpoint_id,
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
                    await self._cache_workflow_state(current_state)

                logger.debug(f"📍 Created checkpoint {checkpoint_id} for workflow {workflow_id}")
                return True

        except Exception as e:
            logger.error(f"❌ Failed to create checkpoint for workflow {workflow_id}: {e}")
            return False

    async def heartbeat_workflow(self, workflow_id: str) -> bool:
        """Update workflow heartbeat to indicate it's still active"""

        try:
            now = datetime.now(timezone.utc)

            # Quick Redis update for heartbeat
            cache_key = f"workflow:{workflow_id}"
            cached_data = await self.redis_client.get(cache_key)

            if cached_data:
                # Update heartbeat in cache
                workflow_data = json.loads(cached_data)
                workflow_data['last_heartbeat'] = now.isoformat()
                await self.redis_client.setex(cache_key, self.cache_ttl, json.dumps(workflow_data))

            # Periodic database update (every 5 heartbeats)
            heartbeat_count = await self.redis_client.incr(f"heartbeat_count:{workflow_id}")

            if heartbeat_count % 5 == 0 or heartbeat_count == 1:
                async with self._get_db_connection() as conn:
                    await conn.execute("""
                        UPDATE workflow_states
                        SET last_heartbeat = $1, updated_at = $1
                        WHERE workflow_id = $2
                    """, now, workflow_id)

            # Expire heartbeat counter after 5 minutes
            await self.redis_client.expire(f"heartbeat_count:{workflow_id}", 300)

            return True

        except Exception as e:
            logger.error(f"❌ Failed to update heartbeat for workflow {workflow_id}: {e}")
            return False

    @asynccontextmanager
    async def _get_db_connection(self):
        """Get database connection from pool with proper error handling"""
        if not self.db_pool:
            raise RuntimeError("Database pool not initialized")

        async with self.db_pool.acquire() as conn:
            try:
                yield conn
            except Exception as e:
                # Log the error but let it propagate
                logger.error(f"Database operation failed: {e}")
                raise

    async def _store_workflow_state(self, workflow_state: WorkflowState):
        """Store workflow state in PostgreSQL"""
        async with self._get_db_connection() as conn:
            await conn.execute("""
                INSERT INTO workflow_states (
                    workflow_id, organization_id, user_id, workflow_type, status, priority,
                    current_stage, progress_percentage, prospects, team_members, results,
                    errors, settings, created_at, updated_at, started_at, completed_at,
                    last_heartbeat, timeout_at, retry_count, max_retries, approval_requests,
                    is_paused, pause_reason, steps_completed, steps_total, execution_time_seconds,
                    recovery_checkpoint, recovery_metadata
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17,
                    $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29
                )
            """,
                workflow_state.workflow_id, workflow_state.organization_id, workflow_state.user_id,
                workflow_state.workflow_type, workflow_state.status.value, workflow_state.priority.value,
                workflow_state.current_stage, workflow_state.progress_percentage,
                json.dumps(workflow_state.prospects), json.dumps(workflow_state.team_members),
                json.dumps(workflow_state.results), json.dumps(workflow_state.errors),
                json.dumps(workflow_state.settings), workflow_state.created_at, workflow_state.updated_at,
                workflow_state.started_at, workflow_state.completed_at, workflow_state.last_heartbeat,
                workflow_state.timeout_at, workflow_state.retry_count, workflow_state.max_retries,
                json.dumps(workflow_state.approval_requests or []), workflow_state.is_paused,
                workflow_state.pause_reason, workflow_state.steps_completed, workflow_state.steps_total,
                workflow_state.execution_time_seconds, json.dumps(workflow_state.recovery_checkpoint or {}),
                json.dumps(workflow_state.recovery_metadata or {})
            )

    async def _update_workflow_state_db(self, conn: asyncpg.Connection, workflow_state: WorkflowState):
        """Update workflow state in PostgreSQL"""
        await conn.execute("""
            UPDATE workflow_states SET
                status = $2, current_stage = $3, progress_percentage = $4, results = $5,
                errors = $6, updated_at = $7, started_at = $8, completed_at = $9,
                last_heartbeat = $10, retry_count = $11, approval_requests = $12,
                is_paused = $13, pause_reason = $14, steps_completed = $15,
                execution_time_seconds = $16, recovery_checkpoint = $17, recovery_metadata = $18
            WHERE workflow_id = $1
        """,
            workflow_state.workflow_id, workflow_state.status.value, workflow_state.current_stage,
            workflow_state.progress_percentage, json.dumps(workflow_state.results),
            json.dumps(workflow_state.errors), workflow_state.updated_at, workflow_state.started_at,
            workflow_state.completed_at, workflow_state.last_heartbeat, workflow_state.retry_count,
            json.dumps(workflow_state.approval_requests or []), workflow_state.is_paused,
            workflow_state.pause_reason, workflow_state.steps_completed, workflow_state.execution_time_seconds,
            json.dumps(workflow_state.recovery_checkpoint or {}), json.dumps(workflow_state.recovery_metadata or {})
        )

    async def _cache_workflow_state(self, workflow_state: WorkflowState):
        """Cache workflow state in Redis for performance"""
        try:
            cache_key = f"workflow:{workflow_state.workflow_id}"
            workflow_data = asdict(workflow_state)

            # Convert datetime objects to ISO strings for JSON serialization
            for key, value in workflow_data.items():
                if isinstance(value, datetime):
                    workflow_data[key] = value.isoformat() if value else None
                elif isinstance(value, Enum):
                    workflow_data[key] = value.value

            await self.redis_client.setex(
                cache_key,
                self.cache_ttl,
                json.dumps(workflow_data, default=str)
            )

            # Also cache by organization for quick lookups
            org_key = f"org_workflows:{workflow_state.organization_id}"
            await self.redis_client.sadd(org_key, workflow_state.workflow_id)
            await self.redis_client.expire(org_key, self.cache_ttl)

        except Exception as e:
            logger.error(f"Failed to cache workflow state {workflow_state.workflow_id}: {e}")

    async def _get_cached_workflow_state(self, workflow_id: str) -> Optional[WorkflowState]:
        """Get workflow state from Redis cache"""
        try:
            cache_key = f"workflow:{workflow_id}"
            cached_data = await self.redis_client.get(cache_key)

            if cached_data:
                workflow_data = json.loads(cached_data)
                return self._dict_to_workflow_state(workflow_data)

            return None

        except Exception as e:
            logger.error(f"Failed to get cached workflow state {workflow_id}: {e}")
            return None

    async def _get_workflow_state_db(self, conn: asyncpg.Connection, workflow_id: str) -> Optional[WorkflowState]:
        """Get workflow state from PostgreSQL"""
        row = await conn.fetchrow("SELECT * FROM workflow_states WHERE workflow_id = $1", workflow_id)
        return self._row_to_workflow_state(row) if row else None

    async def _get_workflow_state_locked(self, conn: asyncpg.Connection, workflow_id: str) -> Optional[WorkflowState]:
        """Get workflow state with row-level locking for updates"""
        row = await conn.fetchrow(
            "SELECT * FROM workflow_states WHERE workflow_id = $1 FOR UPDATE",
            workflow_id
        )
        return self._row_to_workflow_state(row) if row else None

    def _row_to_workflow_state(self, row) -> WorkflowState:
        """Convert database row to WorkflowState object"""
        return WorkflowState(
            workflow_id=row['workflow_id'],
            organization_id=row['organization_id'],
            user_id=row['user_id'],
            workflow_type=row['workflow_type'],
            status=WorkflowStatus(row['status']),
            priority=WorkflowPriority(row['priority']),
            current_stage=row['current_stage'],
            progress_percentage=row['progress_percentage'],
            prospects=json.loads(row['prospects']),
            team_members=json.loads(row['team_members']),
            results=json.loads(row['results']),
            errors=json.loads(row['errors']),
            settings=json.loads(row['settings']),
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            started_at=row['started_at'],
            completed_at=row['completed_at'],
            last_heartbeat=row['last_heartbeat'],
            timeout_at=row['timeout_at'],
            retry_count=row['retry_count'],
            max_retries=row['max_retries'],
            approval_requests=json.loads(row['approval_requests']),
            is_paused=row['is_paused'],
            pause_reason=row['pause_reason'],
            steps_completed=row['steps_completed'],
            steps_total=row['steps_total'],
            execution_time_seconds=row['execution_time_seconds'],
            recovery_checkpoint=json.loads(row['recovery_checkpoint'] or '{}'),
            recovery_metadata=json.loads(row['recovery_metadata'] or '{}')
        )

    def _dict_to_workflow_state(self, data: Dict[str, Any]) -> WorkflowState:
        """Convert dictionary to WorkflowState object"""
        # Convert ISO strings back to datetime objects
        for key in ['created_at', 'updated_at', 'started_at', 'completed_at', 'last_heartbeat', 'timeout_at']:
            if data.get(key):
                data[key] = datetime.fromisoformat(data[key])

        return WorkflowState(
            workflow_id=data['workflow_id'],
            organization_id=data['organization_id'],
            user_id=data['user_id'],
            workflow_type=data['workflow_type'],
            status=WorkflowStatus(data['status']),
            priority=WorkflowPriority(data['priority']),
            current_stage=data['current_stage'],
            progress_percentage=data['progress_percentage'],
            prospects=data['prospects'],
            team_members=data['team_members'],
            results=data['results'],
            errors=data['errors'],
            settings=data['settings'],
            created_at=data['created_at'],
            updated_at=data['updated_at'],
            started_at=data.get('started_at'),
            completed_at=data.get('completed_at'),
            last_heartbeat=data.get('last_heartbeat'),
            timeout_at=data.get('timeout_at'),
            retry_count=data.get('retry_count', 0),
            max_retries=data.get('max_retries', 3),
            approval_requests=data.get('approval_requests', []),
            is_paused=data.get('is_paused', False),
            pause_reason=data.get('pause_reason'),
            steps_completed=data.get('steps_completed', 0),
            steps_total=data.get('steps_total', 7),
            execution_time_seconds=data.get('execution_time_seconds', 0.0),
            recovery_checkpoint=data.get('recovery_checkpoint', {}),
            recovery_metadata=data.get('recovery_metadata', {})
        )

    async def _ensure_database_schema(self):
        """Ensure database schema exists for workflow persistence"""
        async with self._get_db_connection() as conn:
            # Main workflow states table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_states (
                    workflow_id VARCHAR(64) PRIMARY KEY,
                    organization_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    workflow_type VARCHAR(100) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
                    current_stage VARCHAR(100) NOT NULL,
                    progress_percentage DECIMAL(5,2) DEFAULT 0.0,

                    -- JSON data columns
                    prospects JSONB NOT NULL DEFAULT '[]',
                    team_members JSONB NOT NULL DEFAULT '[]',
                    results JSONB NOT NULL DEFAULT '{}',
                    errors JSONB NOT NULL DEFAULT '[]',
                    settings JSONB NOT NULL DEFAULT '{}',

                    -- Timestamps
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    started_at TIMESTAMP WITH TIME ZONE,
                    completed_at TIMESTAMP WITH TIME ZONE,
                    last_heartbeat TIMESTAMP WITH TIME ZONE,
                    timeout_at TIMESTAMP WITH TIME ZONE,

                    -- Retry and recovery
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,

                    -- Approval integration
                    approval_requests JSONB DEFAULT '[]',
                    is_paused BOOLEAN DEFAULT FALSE,
                    pause_reason TEXT,

                    -- Progress tracking
                    steps_completed INTEGER DEFAULT 0,
                    steps_total INTEGER DEFAULT 7,
                    execution_time_seconds DECIMAL(10,3) DEFAULT 0.0,

                    -- Recovery data
                    recovery_checkpoint JSONB DEFAULT '{}',
                    recovery_metadata JSONB DEFAULT '{}'
                )
            """)

            # Checkpoints table for recovery
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                    checkpoint_id VARCHAR(32) PRIMARY KEY,
                    workflow_id VARCHAR(64) NOT NULL REFERENCES workflow_states(workflow_id),
                    checkpoint_data JSONB NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
            """)

            # Indexes for performance
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workflow_states_org_status
                ON workflow_states(organization_id, status)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workflow_states_heartbeat
                ON workflow_states(last_heartbeat)
                WHERE status IN ('running', 'recovering')
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workflow_states_timeout
                ON workflow_states(timeout_at)
                WHERE status NOT IN ('completed', 'failed', 'cancelled')
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workflow_checkpoints_workflow
                ON workflow_checkpoints(workflow_id, created_at DESC)
            """)

    async def _start_background_tasks(self):
        """Start background maintenance tasks"""
        self._background_tasks = [
            asyncio.create_task(self._heartbeat_monitor()),
            asyncio.create_task(self._timeout_monitor()),
            asyncio.create_task(self._cleanup_task())
        ]

    async def _heartbeat_monitor(self):
        """Monitor workflow heartbeats and mark stale workflows"""
        while not self._shutdown_event.is_set():
            try:
                async with self._get_db_connection() as conn:
                    # Find workflows with stale heartbeats
                    stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)

                    await conn.execute("""
                        UPDATE workflow_states
                        SET status = 'failed',
                            updated_at = NOW(),
                            completed_at = NOW()
                        WHERE status = 'running'
                        AND last_heartbeat < $1
                    """, stale_threshold)

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Heartbeat monitor error: {e}")
                await asyncio.sleep(60)

    async def _timeout_monitor(self):
        """Monitor workflow timeouts"""
        while not self._shutdown_event.is_set():
            try:
                async with self._get_db_connection() as conn:
                    now = datetime.now(timezone.utc)

                    # Timeout workflows that have exceeded their timeout
                    await conn.execute("""
                        UPDATE workflow_states
                        SET status = 'timeout',
                            updated_at = $1,
                            completed_at = $1
                        WHERE status NOT IN ('completed', 'failed', 'cancelled', 'timeout')
                        AND timeout_at < $1
                    """, now)

                await asyncio.sleep(300)  # Check every 5 minutes

            except Exception as e:
                logger.error(f"Timeout monitor error: {e}")
                await asyncio.sleep(300)

    async def _cleanup_task(self):
        """Periodic cleanup of old workflow data"""
        while not self._shutdown_event.is_set():
            try:
                async with self._get_db_connection() as conn:
                    # Clean up old completed workflows (older than 30 days)
                    cleanup_threshold = datetime.now(timezone.utc) - timedelta(days=30)

                    await conn.execute("""
                        DELETE FROM workflow_states
                        WHERE status IN ('completed', 'failed', 'cancelled', 'timeout')
                        AND completed_at < $1
                    """, cleanup_threshold)

                    # Clean up old checkpoints (older than 7 days)
                    checkpoint_threshold = datetime.now(timezone.utc) - timedelta(days=7)
                    await conn.execute("""
                        DELETE FROM workflow_checkpoints
                        WHERE created_at < $1
                    """, checkpoint_threshold)

                await asyncio.sleep(3600)  # Run every hour

            except Exception as e:
                logger.error(f"Cleanup task error: {e}")
                await asyncio.sleep(3600)

    async def close(self):
        """Gracefully shutdown the persistence service"""
        logger.info("🔄 Shutting down Workflow Persistence Service...")

        # Signal background tasks to stop
        self._shutdown_event.set()

        # Wait for background tasks to complete
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

        # Close connections
        if self.redis_client:
            await self.redis_client.close()

        if self.db_pool:
            await self.db_pool.close()

        logger.info("✅ Workflow Persistence Service shutdown complete")

    # Additional methods for enterprise integration
    async def get_workflow_by_approval_id(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow associated with an approval ID"""
        try:
            async with self._get_db_connection() as conn:
                result = await conn.fetchrow("""
                    SELECT w.* FROM workflow_states w
                    JOIN approval_requests ar ON w.workflow_id = ar.workflow_id
                    WHERE ar.approval_id = $1
                """, approval_id)

                if result:
                    return dict(result)
                return None

        except Exception as e:
            logger.error(f"Failed to get workflow by approval ID {approval_id}: {e}")
            return None

    async def get_workflows_by_organization(self, organization_id: int) -> List[Dict[str, Any]]:
        """Get all workflows for an organization"""
        try:
            async with self._get_db_connection() as conn:
                results = await conn.fetch("""
                    SELECT * FROM workflow_states
                    WHERE organization_id = $1
                    ORDER BY created_at DESC
                """, organization_id)

                return [dict(result) for result in results]

        except Exception as e:
            logger.error(f"Failed to get workflows for organization {organization_id}: {e}")
            return []

    async def enqueue_workflow(self, workflow_id: str, queue_id: str, priority: str) -> bool:
        """Add workflow to persistent queue"""
        try:
            async with self._get_db_connection() as conn:
                await conn.execute("""
                    INSERT INTO workflow_queues (workflow_id, queue_id, priority, queued_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (workflow_id) DO UPDATE SET
                        queue_id = EXCLUDED.queue_id,
                        priority = EXCLUDED.priority,
                        queued_at = NOW()
                """, workflow_id, queue_id, priority)

                logger.info(f"Enqueued workflow {workflow_id} to queue {queue_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to enqueue workflow {workflow_id}: {e}")
            return False

    async def initialize_workflow_queue(self, queue_id: str, queue_type: str) -> bool:
        """Initialize a workflow queue"""
        try:
            async with self._get_db_connection() as conn:
                await conn.execute("""
                    INSERT INTO workflow_queue_metadata (queue_id, queue_type, created_at)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (queue_id) DO UPDATE SET
                        queue_type = EXCLUDED.queue_type,
                        updated_at = NOW()
                """, queue_id, queue_type)

                logger.info(f"Initialized workflow queue {queue_id} ({queue_type})")
                return True

        except Exception as e:
            logger.error(f"Failed to initialize workflow queue {queue_id}: {e}")
            return False

    async def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow by ID from persistent storage"""
        try:
            async with self._get_db_connection() as conn:
                result = await conn.fetchrow("""
                    SELECT * FROM workflow_states WHERE workflow_id = $1
                """, workflow_id)

                if result:
                    return dict(result)
                return None

        except Exception as e:
            logger.error(f"Failed to get workflow {workflow_id}: {e}")
            return None

# Global instance
_DEFAULT_WORKFLOW_DB = (
    os.getenv("WORKFLOW_DATABASE_URL")
    or os.getenv("DATABASE_URL")
    or "postgresql://vouchlink_user:G0cKKzLekD8EYygLMkymwoKlU3wdBqhk@dpg-d2f3ne2li9vc73bf5gg0-a.oregon-postgres.render.com/vouchlink"
)
_DEFAULT_WORKFLOW_REDIS = os.getenv("WORKFLOW_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0")

workflow_persistence_service = WorkflowPersistenceService(
    database_url=_DEFAULT_WORKFLOW_DB,
    redis_url=_DEFAULT_WORKFLOW_REDIS
)