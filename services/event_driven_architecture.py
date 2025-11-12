#!/usr/bin/env python3
"""
Event-Driven Architecture Service - September 2025 Production Hardening
Enterprise event streaming, messaging, and workflow orchestration

Features:
- Event sourcing for audit trails and state reconstruction
- Pub/Sub messaging for loose coupling
- Event streaming for real-time processing
- Workflow state machines with event triggers
- Dead letter queues for failed message handling
- Event replay and debugging capabilities
"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Set
import weakref
import redis.asyncio as redis

from services.database_pool_manager import get_main_db_connection
from services.error_handling_framework import handle_errors, error_context
from services.monitoring_observability_service import monitoring_service

logger = logging.getLogger(__name__)

class EventType(Enum):
    """System event types"""
    # Workflow events
    WORKFLOW_CREATED = "workflow_created"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_STAGE_COMPLETED = "workflow_stage_completed"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"

    # Service events
    SERVICE_STARTED = "service_started"
    SERVICE_STOPPED = "service_stopped"
    SERVICE_HEALTH_CHANGED = "service_health_changed"
    CIRCUIT_BREAKER_OPENED = "circuit_breaker_opened"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker_closed"

    # Data events
    DATA_CREATED = "data_created"
    DATA_UPDATED = "data_updated"
    DATA_DELETED = "data_deleted"
    DATA_EXPORTED = "data_exported"

    # User events
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_REVOKED = "permission_revoked"

    # Business events
    PROSPECT_DISCOVERED = "prospect_discovered"
    EMAIL_SENT = "email_sent"
    EMAIL_OPENED = "email_opened"
    EMAIL_CLICKED = "email_clicked"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"

    # System events
    ERROR_OCCURRED = "error_occurred"
    ALERT_TRIGGERED = "alert_triggered"
    ALERT_RESOLVED = "alert_resolved"
    BACKUP_COMPLETED = "backup_completed"

class EventPriority(Enum):
    """Event processing priority"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

class EventStatus(Enum):
    """Event processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"

@dataclass
class Event:
    """Core event structure"""
    id: str
    event_type: EventType
    source: str
    data: Dict[str, Any]
    priority: EventPriority = EventPriority.NORMAL
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class EventHandler:
    """Event handler configuration"""
    handler_id: str
    event_types: Set[EventType]
    handler_function: Callable
    retry_attempts: int = 3
    retry_delay: float = 1.0
    dead_letter_threshold: int = 3
    enabled: bool = True

@dataclass
class EventStream:
    """Event stream configuration"""
    stream_name: str
    event_types: Set[EventType]
    batch_size: int = 100
    max_age_seconds: int = 3600
    retention_policy: str = "time_based"

@dataclass
class ProcessedEvent:
    """Processed event with status tracking"""
    event: Event
    status: EventStatus
    handler_id: str
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    processing_duration_ms: Optional[float] = None

class EventStore:
    """Event sourcing store for persistent event history"""

    def __init__(self):
        self.events_cache: deque = deque(maxlen=10000)
        self._cache_lock = asyncio.Lock()

    async def append_event(self, event: Event) -> bool:
        """Append event to store"""

        try:
            # Store in database for persistence
            async with get_main_db_connection() as conn:
                await conn.execute("""
                    INSERT INTO event_store (
                        id, event_type, source, data, priority, correlation_id,
                        causation_id, timestamp, version, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """, event.id, event.event_type.value, event.source,
                json.dumps(event.data), event.priority.value, event.correlation_id,
                event.causation_id, event.timestamp, event.version, json.dumps(event.metadata))

            # Add to cache
            async with self._cache_lock:
                self.events_cache.append(event)

            logger.debug(f"📝 Stored event: {event.event_type.value} from {event.source}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to store event {event.id}: {e}")
            return False

    async def get_events(self,
                        stream_name: Optional[str] = None,
                        event_types: Optional[Set[EventType]] = None,
                        since: Optional[datetime] = None,
                        correlation_id: Optional[str] = None,
                        limit: int = 1000) -> List[Event]:
        """Get events from store with filtering"""

        try:
            conditions = ["1=1"]
            params = []
            param_count = 0

            if stream_name:
                param_count += 1
                conditions.append(f"source = ${param_count}")
                params.append(stream_name)

            if event_types:
                param_count += 1
                event_type_values = [et.value for et in event_types]
                conditions.append(f"event_type = ANY(${param_count})")
                params.append(event_type_values)

            if since:
                param_count += 1
                conditions.append(f"timestamp >= ${param_count}")
                params.append(since)

            if correlation_id:
                param_count += 1
                conditions.append(f"correlation_id = ${param_count}")
                params.append(correlation_id)

            param_count += 1
            params.append(limit)

            query = f"""
                SELECT * FROM event_store
                WHERE {' AND '.join(conditions)}
                ORDER BY timestamp DESC
                LIMIT ${param_count}
            """

            async with get_main_db_connection() as conn:
                rows = await conn.fetch(query, *params)

                events = []
                for row in rows:
                    event = Event(
                        id=row['id'],
                        event_type=EventType(row['event_type']),
                        source=row['source'],
                        data=json.loads(row['data']),
                        priority=EventPriority(row['priority']),
                        correlation_id=row['correlation_id'],
                        causation_id=row['causation_id'],
                        timestamp=row['timestamp'],
                        version=row['version'],
                        metadata=json.loads(row['metadata'])
                    )
                    events.append(event)

                return events

        except Exception as e:
            logger.error(f"❌ Failed to get events: {e}")
            return []

    async def replay_events(self,
                          stream_name: str,
                          since: Optional[datetime] = None,
                          event_handler: Optional[Callable] = None) -> int:
        """Replay events for debugging or state reconstruction"""

        events = await self.get_events(stream_name=stream_name, since=since)
        replayed_count = 0

        for event in reversed(events):  # Replay in chronological order
            try:
                if event_handler:
                    await event_handler(event)

                replayed_count += 1
                logger.debug(f"🔄 Replayed event: {event.event_type.value}")

            except Exception as e:
                logger.error(f"❌ Failed to replay event {event.id}: {e}")

        logger.info(f"🔄 Replayed {replayed_count} events for stream {stream_name}")
        return replayed_count

class EventBus:
    """Central event bus for pub/sub messaging"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.handlers: Dict[str, EventHandler] = {}
        self.processing_queue: asyncio.Queue = asyncio.Queue()
        self.dead_letter_queue: deque = deque(maxlen=1000)
        self._background_tasks: List[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()

    async def initialize(self):
        """Initialize event bus"""

        # Initialize Redis connection
        redis_pool = redis.ConnectionPool.from_url(self.redis_url, decode_responses=True)
        self.redis_client = redis.Redis(connection_pool=redis_pool)

        # Start background processing tasks
        self._background_tasks = [
            asyncio.create_task(self._process_events()),
            asyncio.create_task(self._monitor_dead_letter_queue()),
            asyncio.create_task(self._cleanup_old_events())
        ]

        logger.info("🚌 Event Bus initialized")

    async def publish(self, event: Event) -> bool:
        """Publish event to bus"""

        try:
            # Serialize event
            event_data = {
                'id': event.id,
                'event_type': event.event_type.value,
                'source': event.source,
                'data': event.data,
                'priority': event.priority.value,
                'correlation_id': event.correlation_id,
                'causation_id': event.causation_id,
                'timestamp': event.timestamp.isoformat(),
                'version': event.version,
                'metadata': event.metadata
            }

            # Publish to Redis
            channel = f"events:{event.event_type.value}"
            await self.redis_client.publish(channel, json.dumps(event_data))

            # Add to processing queue based on priority
            await self._enqueue_event(event)

            # Record metrics
            await monitoring_service.record_workflow_event(
                workflow_id=event.correlation_id or 'unknown',
                event_type=event.event_type.value,
                organization_id=event.data.get('organization_id', 0)
            )

            logger.debug(f"📤 Published event: {event.event_type.value}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to publish event {event.id}: {e}")
            return False

    async def subscribe(self, event_handler: EventHandler):
        """Subscribe event handler to specific event types"""

        self.handlers[event_handler.handler_id] = event_handler

        # Subscribe to Redis channels for real-time events
        for event_type in event_handler.event_types:
            channel = f"events:{event_type.value}"
            asyncio.create_task(self._redis_subscriber(channel, event_handler))

        logger.info(f"🔔 Subscribed handler {event_handler.handler_id} to {len(event_handler.event_types)} event types")

    async def _enqueue_event(self, event: Event):
        """Add event to processing queue with priority"""

        # Priority queue implementation
        priority_order = {
            EventPriority.CRITICAL: 0,
            EventPriority.HIGH: 1,
            EventPriority.NORMAL: 2,
            EventPriority.LOW: 3
        }

        event_priority = priority_order.get(event.priority, 2)
        await self.processing_queue.put((event_priority, event))

    async def _process_events(self):
        """Background task to process events"""

        while not self._shutdown_event.is_set():
            try:
                # Get event from queue with priority
                priority, event = await asyncio.wait_for(
                    self.processing_queue.get(),
                    timeout=1.0
                )

                # Process event with all matching handlers
                await self._handle_event(event)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"❌ Event processing error: {e}")

    async def _handle_event(self, event: Event):
        """Handle event with registered handlers"""

        matching_handlers = [
            handler for handler in self.handlers.values()
            if event.event_type in handler.event_types and handler.enabled
        ]

        if not matching_handlers:
            logger.debug(f"No handlers for event type: {event.event_type.value}")
            return

        # Process event with each matching handler
        for handler in matching_handlers:
            processed_event = ProcessedEvent(
                event=event,
                status=EventStatus.PENDING,
                handler_id=handler.handler_id
            )

            await self._execute_handler(handler, processed_event)

    async def _execute_handler(self, handler: EventHandler, processed_event: ProcessedEvent):
        """Execute event handler with retry logic"""

        max_attempts = handler.retry_attempts + 1
        attempt = 0

        while attempt < max_attempts:
            try:
                processed_event.status = EventStatus.PROCESSING
                processed_event.processing_started_at = datetime.now(timezone.utc)
                processed_event.retry_count = attempt

                start_time = datetime.now(timezone.utc)

                # Execute handler
                await handler.handler_function(processed_event.event)

                # Record success
                end_time = datetime.now(timezone.utc)
                processed_event.status = EventStatus.COMPLETED
                processed_event.processing_completed_at = end_time
                processed_event.processing_duration_ms = (end_time - start_time).total_seconds() * 1000

                logger.debug(f"✅ Event {processed_event.event.id} handled by {handler.handler_id}")
                return

            except Exception as e:
                attempt += 1
                processed_event.error_message = str(e)

                if attempt < max_attempts:
                    processed_event.status = EventStatus.RETRYING
                    await asyncio.sleep(handler.retry_delay * (2 ** attempt))  # Exponential backoff
                    logger.warning(f"🔄 Retrying event {processed_event.event.id} with {handler.handler_id} (attempt {attempt})")
                else:
                    processed_event.status = EventStatus.FAILED
                    logger.error(f"❌ Event {processed_event.event.id} failed with {handler.handler_id}: {e}")

        # Move to dead letter queue if all retries failed
        if processed_event.retry_count >= handler.dead_letter_threshold:
            processed_event.status = EventStatus.DEAD_LETTER
            self.dead_letter_queue.append(processed_event)
            logger.error(f"💀 Event {processed_event.event.id} moved to dead letter queue")

    async def _redis_subscriber(self, channel: str, handler: EventHandler):
        """Subscribe to Redis channel for real-time events"""

        try:
            pubsub = self.redis_client.pubsub()
            await pubsub.subscribe(channel)

            async for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        event_data = json.loads(message['data'])
                        event = Event(
                            id=event_data['id'],
                            event_type=EventType(event_data['event_type']),
                            source=event_data['source'],
                            data=event_data['data'],
                            priority=EventPriority(event_data['priority']),
                            correlation_id=event_data.get('correlation_id'),
                            causation_id=event_data.get('causation_id'),
                            timestamp=datetime.fromisoformat(event_data['timestamp']),
                            version=event_data['version'],
                            metadata=event_data['metadata']
                        )

                        # Add to processing queue
                        await self._enqueue_event(event)

                    except Exception as e:
                        logger.error(f"❌ Failed to process Redis message: {e}")

        except Exception as e:
            logger.error(f"❌ Redis subscriber error for {channel}: {e}")

    async def _monitor_dead_letter_queue(self):
        """Monitor and alert on dead letter queue"""

        while not self._shutdown_event.is_set():
            try:
                if len(self.dead_letter_queue) > 0:
                    logger.warning(f"💀 Dead letter queue has {len(self.dead_letter_queue)} failed events")

                    # Trigger alert if too many failed events
                    if len(self.dead_letter_queue) > 50:
                        await monitoring_service.metrics_collector.record_metric(
                            'dead_letter_queue_size',
                            len(self.dead_letter_queue),
                            monitoring_service.MetricType.GAUGE,
                            {'service': 'event_bus'}
                        )

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"❌ Dead letter queue monitoring error: {e}")

    async def _cleanup_old_events(self):
        """Clean up old events from Redis and database"""

        while not self._shutdown_event.is_set():
            try:
                # Clean up events older than 7 days
                cutoff_time = datetime.now(timezone.utc) - timedelta(days=7)

                async with get_main_db_connection() as conn:
                    deleted_count = await conn.fetchval("""
                        DELETE FROM event_store
                        WHERE timestamp < $1
                        RETURNING COUNT(*)
                    """, cutoff_time)

                    if deleted_count > 0:
                        logger.info(f"🧹 Cleaned up {deleted_count} old events")

                await asyncio.sleep(3600)  # Run every hour

            except Exception as e:
                logger.error(f"❌ Event cleanup error: {e}")

    async def get_metrics(self) -> Dict[str, Any]:
        """Get event bus metrics"""

        return {
            "handlers_count": len(self.handlers),
            "processing_queue_size": self.processing_queue.qsize(),
            "dead_letter_queue_size": len(self.dead_letter_queue),
            "active_tasks": len(self._background_tasks),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def close(self):
        """Shutdown event bus"""

        logger.info("🔄 Shutting down Event Bus")

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()

        logger.info("✅ Event Bus shutdown complete")

class WorkflowStateMachine:
    """State machine for workflow orchestration with events"""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.state_transitions: Dict[str, Dict[str, str]] = {}
        self.state_handlers: Dict[str, Callable] = {}

        # Enterprise persistence and resilience
        from .workflow_persistence_service import workflow_persistence_service
        self.persistence_service = workflow_persistence_service

        from .resilience_patterns import ResilienceManager, BulkheadConfig, BulkheadType
        self.resilience_manager = ResilienceManager()

        from .error_handling_framework import ErrorHandler
        self.error_handler = ErrorHandler()

        # Register bulkhead for state machine operations
        self.resilience_manager.create_bulkhead(BulkheadConfig(
            name="workflow_state_machine",
            bulkhead_type=BulkheadType.THREAD_POOL,
            max_concurrent=12
        ))

    def define_state_machine(self,
                           initial_state: str,
                           transitions: Dict[str, Dict[str, str]],
                           handlers: Dict[str, Callable]):
        """Define state machine configuration"""

        self.initial_state = initial_state
        self.state_transitions = transitions
        self.state_handlers = handlers

    async def start_workflow(self, workflow_id: str, initial_data: Dict[str, Any] = None) -> bool:
        """Start workflow state machine"""

        try:
            # Use bulkhead for workflow start operations
            async with self.resilience_manager.get_bulkhead("workflow_state_machine"):
                # Store workflow state in enterprise persistence
                await self.persistence_service.update_workflow_status(
                    workflow_id=workflow_id,
                    status="running",
                    current_stage=self.initial_state
                )

                # Publish workflow started event
                event = Event(
                    id=str(uuid.uuid4()),
                    event_type=EventType.WORKFLOW_STARTED,
                    source="workflow_state_machine",
                    data={
                        "workflow_id": workflow_id,
                        "initial_state": self.initial_state,
                        "initial_data": initial_data or {}
                    },
                    correlation_id=workflow_id
                )

                await self.event_bus.publish(event)

                # Execute initial state handler
                if self.initial_state in self.state_handlers:
                    await self.state_handlers[self.initial_state](workflow_id, initial_data or {})

                logger.info(f"🔄 Started workflow {workflow_id} in state {self.initial_state}")
                return True

        except Exception as e:
            error_context = {
                'workflow_id': workflow_id,
                'initial_state': self.initial_state,
                'initial_data': initial_data
            }
            # Import ErrorCategory and ErrorSeverity from ErrorHandler
            from .error_handling_framework import ErrorCategory, ErrorSeverity

            await self.error_handler.handle_error(
                error=e,
                operation="start_workflow_state_machine",
                context=error_context,
                category=ErrorCategory.WORKFLOW_ERROR,
                severity=ErrorSeverity.HIGH
            )
            logger.error(f"❌ Failed to start workflow {workflow_id}: {e}")
            return False

    async def trigger_transition(self,
                               workflow_id: str,
                               trigger: str,
                               data: Dict[str, Any] = None) -> bool:
        """Trigger state transition"""

        try:
            # Use bulkhead for transition operations
            async with self.resilience_manager.get_bulkhead("workflow_state_machine"):
                # Get current state from enterprise persistence
                workflow_data = await self.persistence_service.get_workflow(workflow_id)
                if not workflow_data:
                    logger.error(f"Workflow {workflow_id} not found in persistence")
                    return False

                current_state = workflow_data.get('current_stage')
                if not current_state:
                    logger.error(f"No current state found for workflow {workflow_id}")
                    return False

                # Check if transition is valid
                if trigger not in self.state_transitions.get(current_state, {}):
                    logger.warning(f"Invalid transition {trigger} from state {current_state}")
                    return False

                # Get next state
                next_state = self.state_transitions[current_state][trigger]

                # Update state in enterprise persistence
                await self.persistence_service.update_workflow_status(
                    workflow_id=workflow_id,
                    status="running",
                    current_stage=next_state
                )

                # Publish state change event
                event = Event(
                    id=str(uuid.uuid4()),
                    event_type=EventType.WORKFLOW_STAGE_COMPLETED,
                    source="workflow_state_machine",
                    data={
                        "workflow_id": workflow_id,
                        "previous_state": current_state,
                        "next_state": next_state,
                        "trigger": trigger,
                        "transition_data": data or {}
                    },
                    correlation_id=workflow_id
                )

                await self.event_bus.publish(event)

                # Execute state handler
                if next_state in self.state_handlers:
                    await self.state_handlers[next_state](workflow_id, data or {})

                logger.info(f"🔄 Workflow {workflow_id}: {current_state} → {next_state} (trigger: {trigger})")
                return True

        except Exception as e:
            error_context = {
                'workflow_id': workflow_id,
                'trigger': trigger,
                'transition_data': data
            }
            # Import ErrorCategory and ErrorSeverity from ErrorHandler
            from .error_handling_framework import ErrorCategory, ErrorSeverity

            await self.error_handler.handle_error(
                error=e,
                operation="trigger_workflow_transition",
                context=error_context,
                category=ErrorCategory.WORKFLOW_ERROR,
                severity=ErrorSeverity.HIGH
            )
            logger.error(f"❌ Failed to transition workflow {workflow_id}: {e}")
            return False

    async def get_workflow_state(self, workflow_id: str) -> Optional[str]:
        """Get current workflow state from enterprise persistence"""
        try:
            workflow_data = await self.persistence_service.get_workflow(workflow_id)
            if workflow_data:
                return workflow_data.get('current_stage')
            return None
        except Exception as e:
            logger.error(f"Failed to get workflow state for {workflow_id}: {e}")
            return None

class EventDrivenArchitectureService:
    """Main event-driven architecture service"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.event_store = EventStore()
        self.event_bus = EventBus(redis_url)
        self.workflow_state_machine = WorkflowStateMachine(self.event_bus)
        self._initialized = False

    async def initialize(self):
        """Initialize event-driven architecture"""

        if self._initialized:
            return

        # Ensure database schema
        await self._ensure_event_schema()

        # Initialize event bus
        await self.event_bus.initialize()

        # Setup default event handlers
        await self._setup_default_handlers()

        # Setup workflow state machine
        await self._setup_workflow_state_machine()

        self._initialized = True
        logger.info("🏗️ Event-Driven Architecture Service initialized")

    async def _ensure_event_schema(self):
        """Ensure event storage schema exists"""

        async with get_main_db_connection() as conn:
            # Event store table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS event_store (
                    id VARCHAR(64) PRIMARY KEY,
                    event_type VARCHAR(100) NOT NULL,
                    source VARCHAR(255) NOT NULL,
                    data JSONB NOT NULL,
                    priority VARCHAR(20) DEFAULT 'normal',
                    correlation_id VARCHAR(64),
                    causation_id VARCHAR(64),
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    version INTEGER DEFAULT 1,
                    metadata JSONB DEFAULT '{}'
                )
            """)

            # Indexes for performance
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_store_type_time
                ON event_store(event_type, timestamp DESC)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_store_correlation
                ON event_store(correlation_id, timestamp DESC)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_store_source
                ON event_store(source, timestamp DESC)
            """)

    async def _setup_default_handlers(self):
        """Setup default event handlers"""

        # Workflow event handler
        workflow_handler = EventHandler(
            handler_id="workflow_events",
            event_types={
                EventType.WORKFLOW_CREATED,
                EventType.WORKFLOW_STARTED,
                EventType.WORKFLOW_STAGE_COMPLETED,
                EventType.WORKFLOW_COMPLETED,
                EventType.WORKFLOW_FAILED
            },
            handler_function=self._handle_workflow_events
        )
        await self.event_bus.subscribe(workflow_handler)

        # System monitoring handler
        monitoring_handler = EventHandler(
            handler_id="system_monitoring",
            event_types={
                EventType.ERROR_OCCURRED,
                EventType.ALERT_TRIGGERED,
                EventType.SERVICE_HEALTH_CHANGED
            },
            handler_function=self._handle_monitoring_events
        )
        await self.event_bus.subscribe(monitoring_handler)

        # Audit logging handler
        audit_handler = EventHandler(
            handler_id="audit_logging",
            event_types={
                EventType.USER_LOGIN,
                EventType.PERMISSION_GRANTED,
                EventType.DATA_CREATED,
                EventType.DATA_UPDATED,
                EventType.DATA_DELETED
            },
            handler_function=self._handle_audit_events
        )
        await self.event_bus.subscribe(audit_handler)

    async def _setup_workflow_state_machine(self):
        """Setup workflow state machine"""

        # Define workflow states and transitions
        transitions = {
            "created": {
                "START": "executive_search",
                "CANCEL": "cancelled"
            },
            "executive_search": {
                "COMPLETE": "linkedin_discovery",
                "FAIL": "failed",
                "PAUSE": "paused"
            },
            "linkedin_discovery": {
                "COMPLETE": "mutual_connections",
                "FAIL": "failed",
                "PAUSE": "paused"
            },
            "mutual_connections": {
                "COMPLETE": "connector_ranking",
                "FAIL": "failed",
                "PAUSE": "paused"
            },
            "connector_ranking": {
                "COMPLETE": "email_enrichment",
                "FAIL": "failed",
                "PAUSE": "paused"
            },
            "email_enrichment": {
                "COMPLETE": "human_approval",
                "FAIL": "failed",
                "PAUSE": "paused"
            },
            "human_approval": {
                "APPROVE": "email_sending",
                "REJECT": "rejected",
                "TIMEOUT": "timeout"
            },
            "email_sending": {
                "COMPLETE": "completed",
                "FAIL": "failed"
            },
            "paused": {
                "RESUME": "executive_search"  # Resume from where paused
            }
        }

        # Define state handlers
        handlers = {
            "created": self._handle_created_state,
            "executive_search": self._handle_executive_search_state,
            "linkedin_discovery": self._handle_linkedin_discovery_state,
            "mutual_connections": self._handle_mutual_connections_state,
            "connector_ranking": self._handle_connector_ranking_state,
            "email_enrichment": self._handle_email_enrichment_state,
            "human_approval": self._handle_human_approval_state,
            "email_sending": self._handle_email_sending_state,
            "completed": self._handle_completed_state,
            "failed": self._handle_failed_state
        }

        self.workflow_state_machine.define_state_machine("created", transitions, handlers)

    # Event handlers
    async def _handle_workflow_events(self, event: Event):
        """Handle workflow events"""

        await self.event_store.append_event(event)

        workflow_id = event.data.get('workflow_id')
        if workflow_id:
            logger.info(f"🔄 Workflow event: {event.event_type.value} for {workflow_id}")

    async def _handle_monitoring_events(self, event: Event):
        """Handle monitoring and alerting events"""

        await self.event_store.append_event(event)

        if event.event_type == EventType.ERROR_OCCURRED:
            # Record error metrics
            await monitoring_service.metrics_collector.record_metric(
                'errors_total',
                1,
                monitoring_service.MetricType.COUNTER,
                {'error_type': event.data.get('error_type', 'unknown')}
            )

    async def _handle_audit_events(self, event: Event):
        """Handle audit events for compliance"""

        await self.event_store.append_event(event)

        # Could integrate with security audit system here
        logger.info(f"📋 Audit event: {event.event_type.value}")

    # State handlers for workflow state machine
    async def _handle_created_state(self, workflow_id: str, data: Dict[str, Any]):
        """Handle workflow created state"""
        logger.info(f"📝 Workflow {workflow_id} created")

    async def _handle_executive_search_state(self, workflow_id: str, data: Dict[str, Any]):
        """Handle executive search state"""
        logger.info(f"🔍 Workflow {workflow_id} starting executive search")

    async def _handle_linkedin_discovery_state(self, workflow_id: str, data: Dict[str, Any]):
        """Handle LinkedIn discovery state"""
        logger.info(f"🔗 Workflow {workflow_id} starting LinkedIn discovery")

    async def _handle_mutual_connections_state(self, workflow_id: str, data: Dict[str, Any]):
        """Handle mutual connections state"""
        logger.info(f"🤝 Workflow {workflow_id} discovering mutual connections")

    async def _handle_connector_ranking_state(self, workflow_id: str, data: Dict[str, Any]):
        """Handle connector ranking state"""
        logger.info(f"🎯 Workflow {workflow_id} ranking connectors")

    async def _handle_email_enrichment_state(self, workflow_id: str, data: Dict[str, Any]):
        """Handle email enrichment state"""
        logger.info(f"📧 Workflow {workflow_id} enriching emails")

    async def _handle_human_approval_state(self, workflow_id: str, data: Dict[str, Any]):
        """Handle human approval state"""
        logger.info(f"👤 Workflow {workflow_id} awaiting human approval")

    async def _handle_email_sending_state(self, workflow_id: str, data: Dict[str, Any]):
        """Handle email sending state"""
        logger.info(f"📤 Workflow {workflow_id} sending emails")

    async def _handle_completed_state(self, workflow_id: str, data: Dict[str, Any]):
        """Handle completed state"""
        logger.info(f"✅ Workflow {workflow_id} completed successfully")

    async def _handle_failed_state(self, workflow_id: str, data: Dict[str, Any]):
        """Handle failed state"""
        logger.error(f"❌ Workflow {workflow_id} failed")

    # Public API methods
    async def publish_event(self, event: Event) -> bool:
        """Publish event to the system"""
        success = await self.event_bus.publish(event)
        if success:
            await self.event_store.append_event(event)
        return success

    async def start_workflow(self, workflow_id: str, initial_data: Dict[str, Any] = None) -> bool:
        """Start workflow with state machine"""
        return await self.workflow_state_machine.start_workflow(workflow_id, initial_data)

    async def trigger_workflow_transition(self, workflow_id: str, trigger: str, data: Dict[str, Any] = None) -> bool:
        """Trigger workflow state transition"""
        return await self.workflow_state_machine.trigger_transition(workflow_id, trigger, data)

    async def get_workflow_state(self, workflow_id: str) -> Optional[str]:
        """Get current workflow state"""
        return self.workflow_state_machine.get_workflow_state(workflow_id)

    async def get_event_history(self, correlation_id: str, limit: int = 100) -> List[Event]:
        """Get event history for a correlation ID"""
        return await self.event_store.get_events(correlation_id=correlation_id, limit=limit)

    async def get_dashboard_data(self) -> Dict[str, Any]:
        """Get event-driven architecture dashboard data"""

        event_bus_metrics = await self.event_bus.get_metrics()

        # Get recent events
        recent_events = await self.event_store.get_events(limit=50)

        # Get workflow states from enterprise persistence
        workflow_states = {}
        try:
            # Get recent workflows and their states
            recent_workflows = await self.event_store.get_events(
                event_types={EventType.WORKFLOW_STARTED, EventType.WORKFLOW_STAGE_COMPLETED},
                limit=100
            )
            for event in recent_workflows:
                workflow_id = event.correlation_id
                if workflow_id:
                    state = await self.workflow_state_machine.get_workflow_state(workflow_id)
                    if state:
                        workflow_states[workflow_id] = state
        except Exception as e:
            logger.error(f"Failed to get workflow states for dashboard: {e}")
            workflow_states = {}

        return {
            "event_bus_metrics": event_bus_metrics,
            "recent_events_count": len(recent_events),
            "active_workflows": len(workflow_states),
            "workflow_states": workflow_states,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def close(self):
        """Shutdown event-driven architecture"""
        logger.info("🔄 Shutting down Event-Driven Architecture Service")

        await self.event_bus.close()

        logger.info("✅ Event-Driven Architecture Service shutdown complete")

# Global event-driven architecture service
eda_service = EventDrivenArchitectureService()

# Utility functions for creating events
def create_workflow_event(event_type: EventType,
                         workflow_id: str,
                         data: Dict[str, Any],
                         source: str = "enterprise_orchestrator") -> Event:
    """Create workflow-related event"""

    return Event(
        id=str(uuid.uuid4()),
        event_type=event_type,
        source=source,
        data=data,
        correlation_id=workflow_id,
        priority=EventPriority.NORMAL
    )

def create_system_event(event_type: EventType,
                       data: Dict[str, Any],
                       source: str,
                       priority: EventPriority = EventPriority.NORMAL) -> Event:
    """Create system event"""

    return Event(
        id=str(uuid.uuid4()),
        event_type=event_type,
        source=source,
        data=data,
        priority=priority
    )

# Context manager for event-driven operations
@asynccontextmanager
async def event_driven_operation(operation_name: str, correlation_id: Optional[str] = None):
    """Context manager for event-driven operations"""

    correlation_id = correlation_id or str(uuid.uuid4())

    # Publish start event
    start_event = create_system_event(
        EventType.SERVICE_STARTED,
        {"operation": operation_name, "correlation_id": correlation_id},
        "event_driven_context"
    )
    start_event.correlation_id = correlation_id

    await eda_service.publish_event(start_event)

    try:
        yield correlation_id

        # Publish success event
        success_event = create_system_event(
            EventType.SERVICE_STOPPED,
            {"operation": operation_name, "correlation_id": correlation_id, "result": "success"},
            "event_driven_context"
        )
        success_event.correlation_id = correlation_id
        await eda_service.publish_event(success_event)

    except Exception as e:
        # Publish error event
        error_event = create_system_event(
            EventType.ERROR_OCCURRED,
            {
                "operation": operation_name,
                "correlation_id": correlation_id,
                "error": str(e),
                "error_type": type(e).__name__
            },
            "event_driven_context",
            EventPriority.HIGH
        )
        error_event.correlation_id = correlation_id
        await eda_service.publish_event(error_event)
        raise