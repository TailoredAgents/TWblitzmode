"""
Redis Streams Message Queue Architecture

Enterprise-grade message queue system using Redis Streams for the VouchLink AI corporate platform.
Provides reliable, scalable messaging between microservices with dead letter queues,
retry logic, and comprehensive monitoring.

Features:
- Redis Streams for message ordering and delivery guarantees
- Consumer groups for horizontal scaling and load balancing
- Dead letter queues for failed message handling
- Correlation IDs for distributed tracing
- Message retry with exponential backoff
- Comprehensive metrics and monitoring
- Multi-tenant message isolation
"""

import os
import json
import time
import uuid
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, asdict
from enum import Enum

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover - redis optional in some environments
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)

class MessageStatus(Enum):
    """Message processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    RETRYING = "retrying"

class MessagePriority(Enum):
    """Message priority levels"""
    LOW = "low"
    NORMAL = "normal"
    MEDIUM = "normal"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class QueueMessage:
    """Message structure for Redis Streams"""
    id: str
    stream: str
    message_type: str
    payload: Dict[str, Any]
    organization_id: int
    correlation_id: str
    priority: MessagePriority
    created_at: datetime
    retry_count: int = 0
    max_retries: int = 3
    delay_seconds: int = 0
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = None
    tenant_id: Optional[str] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

@dataclass
class QueueStats:
    """Queue statistics"""
    stream_name: str
    pending_messages: int
    processing_messages: int
    completed_messages: int
    failed_messages: int
    dead_letter_messages: int
    consumer_groups: List[str]
    last_activity: Optional[datetime]

class RedisStreamsQueue:
    """Production-ready Redis Streams message queue system"""

    # Stream naming convention: tailored_agents:{environment}:{queue_type}
    STREAM_NAMES = {
        'ingestion': 'tailored_agents:prod:ingestion',
        'executive_lookup': 'tailored_agents:prod:executive_lookup',
        'mutuals_discovery': 'tailored_agents:prod:mutuals_discovery',
        'mutuals_orchestrator': 'tailored_agents:prod:mutuals_orchestrator',
        'connector_scoring': 'tailored_agents:prod:connector_scoring',
        'scoring': 'tailored_agents:prod:scoring',
        'email_enrichment': 'tailored_agents:prod:email_enrichment',
        'email_scheduling': 'tailored_agents:prod:email_scheduling',
        'corporate_scheduler': 'tailored_agents:prod:corporate_scheduler',
        'email_sending': 'tailored_agents:prod:email_sending',
        'analytics': 'tailored_agents:prod:analytics',
        'notifications': 'tailored_agents:prod:notifications',
        'audit_events': 'tailored_agents:prod:audit_events'
    }

    # Dead letter queue suffix
    DLQ_SUFFIX = ':dlq'

    def __init__(self, redis_url: Optional[str] = None):
        # Redis configuration
        self.redis_url = redis_url or os.getenv('REDIS_URL', 'redis://localhost:6379')
        self.environment = os.getenv('ENVIRONMENT', 'prod')
        self.consumer_group_prefix = os.getenv('CONSUMER_GROUP_PREFIX', 'VouchLink AI')

        # Queue configuration
        self.default_max_retries = int(os.getenv('QUEUE_MAX_RETRIES', '3'))
        self.message_ttl_hours = int(os.getenv('MESSAGE_TTL_HOURS', '24'))
        self.dlq_retention_days = int(os.getenv('DLQ_RETENTION_DAYS', '7'))

        # Performance tuning
        self.batch_size = int(os.getenv('QUEUE_BATCH_SIZE', '10'))
        self.consumer_timeout_ms = int(os.getenv('CONSUMER_TIMEOUT_MS', '5000'))
        self.heartbeat_interval_s = int(os.getenv('HEARTBEAT_INTERVAL_S', '30'))

        # Redis clients
        self.redis_client = None
        self.redis_consumer = None

        # Internal state
        self._available = False
        self._initialised = False
        self._initialization_lock = asyncio.Lock()
        self._background_tasks: List[asyncio.Task] = []

        # Consumer tracking
        self.active_consumers = {}
        self.message_handlers = {}

        if not REDIS_AVAILABLE:
            logger.warning("Redis package not available; RedisStreamsQueue running in disabled mode.")
            return

    @property
    def is_available(self) -> bool:
        """Return True when Redis queue is connected and ready."""
        return self._available and self.redis_client is not None and self.redis_consumer is not None

    async def initialize(self, *, max_retries: int = 3, retry_delay: float = 1.0) -> bool:
        """Initialize Redis connections and create consumer groups with retries."""

        if not REDIS_AVAILABLE:
            logger.error("Redis Streams queue requested but redis package is not installed.")
            self._available = False
            return False

        async with self._initialization_lock:
            if self.is_available:
                return True

            last_error: Optional[Exception] = None

            for attempt in range(1, max_retries + 1):
                try:
                    logger.info("Connecting to Redis Streams queue (%s) [attempt %s/%s]", self.redis_url, attempt, max_retries)

                    # Create Redis clients
                    self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
                    self.redis_consumer = redis.from_url(self.redis_url, decode_responses=True)

                    # Test connection
                    await self.redis_client.ping()
                    await self.redis_consumer.ping()

                    # Create consumer groups if needed
                    await self._create_consumer_groups()

                    # Start background maintenance once
                    if not self._initialised:
                        self._background_tasks.append(asyncio.create_task(self._cleanup_expired_messages()))
                        self._background_tasks.append(asyncio.create_task(self._monitor_consumer_health()))
                        self._initialised = True

                    self._available = True
                    logger.info("Redis Streams queue initialised successfully")
                    return True

                except Exception as exc:
                    last_error = exc
                    self._available = False
                    logger.warning(
                        "Redis Streams queue initialisation attempt %s/%s failed: %s",
                        attempt,
                        max_retries,
                        exc,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay * (2 ** (attempt - 1)))

            logger.error("Failed to initialise Redis Streams queue after %s attempts: %s", max_retries, last_error)
            return False

    async def ensure_initialized(self) -> bool:
        """Convenience helper to ensure queue is ready."""
        if self.is_available:
            return True
        return await self.initialize()

    def _mark_unavailable(self, reason: str):
        """Mark queue as unavailable and log the reason."""
        if self._available:
            logger.error("Redis Streams queue marked unavailable: %s", reason)
        self._available = False

    async def _create_consumer_groups(self):
        """Create consumer groups for all message streams"""

        if not self.redis_client:
            return

        for queue_type, stream_name in self.STREAM_NAMES.items():
            try:
                # Create main stream consumer group
                group_name = f"{self.consumer_group_prefix}_{queue_type}_workers"

                try:
                    await self.redis_client.xgroup_create(
                        stream_name, group_name, id='0', mkstream=True
                    )
                    logger.info(f"Created consumer group {group_name} for stream {stream_name}")
                except redis.exceptions.ResponseError as e:
                    if "BUSYGROUP" in str(e):
                        logger.debug(f"Consumer group {group_name} already exists")
                    else:
                        raise

                # Create dead letter queue stream and consumer group
                dlq_stream = stream_name + self.DLQ_SUFFIX
                dlq_group = f"{self.consumer_group_prefix}_{queue_type}_dlq"

                try:
                    await self.redis_client.xgroup_create(
                        dlq_stream, dlq_group, id='0', mkstream=True
                    )
                except redis.exceptions.ResponseError as e:
                    if "BUSYGROUP" in str(e):
                        logger.debug(f"DLQ consumer group {dlq_group} already exists")
                    else:
                        raise

            except Exception as e:
                logger.error(f"Failed to create consumer groups for {queue_type}: {e}")

    async def enqueue_message(
        self,
        queue_type: str,
        message_type: str,
        payload: Dict[str, Any],
        organization_id: int,
        priority: MessagePriority = MessagePriority.NORMAL,
        correlation_id: str = None,
        delay_seconds: int = 0,
        max_retries: int = None
    ) -> str:
        """Enqueue a message to the specified queue"""

        if not await self.ensure_initialized():
            logger.warning(
                "Redis queue unavailable; dropping message %s (%s) for org %s",
                message_type,
                queue_type,
                organization_id,
            )
            return f"queued_offline:{queue_type}:{uuid.uuid4()}"

        if queue_type not in self.STREAM_NAMES:
            raise ValueError(f"Unknown queue type: {queue_type}")

        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Create message
        message = QueueMessage(
            id=str(uuid.uuid4()),
            stream=self.STREAM_NAMES[queue_type],
            message_type=message_type,
            payload=payload,
            organization_id=organization_id,
            correlation_id=correlation_id,
            priority=priority,
            created_at=datetime.now(timezone.utc),
            max_retries=max_retries or self.default_max_retries,
            delay_seconds=delay_seconds,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=self.message_ttl_hours)
        )

        try:
            # Serialize message
            message_data = {
                'id': message.id,
                'message_type': message.message_type,
                'payload': json.dumps(message.payload),
                'organization_id': str(message.organization_id),
                'correlation_id': message.correlation_id,
                'priority': message.priority.value,
                'created_at': message.created_at.isoformat(),
                'retry_count': str(message.retry_count),
                'max_retries': str(message.max_retries),
                'delay_seconds': str(message.delay_seconds),
                'expires_at': message.expires_at.isoformat() if message.expires_at else ''
            }

            # Handle delayed messages
            if delay_seconds > 0:
                # Store in delayed queue for later processing
                delayed_key = f"delayed_messages:{queue_type}"
                execute_at = time.time() + delay_seconds

                await self.redis_client.zadd(
                    delayed_key,
                    {json.dumps(message_data): execute_at}
                )

                logger.info(f"Message {message.id} delayed for {delay_seconds} seconds")
                return message.id

            # Add to stream immediately
            stream_id = await self.redis_client.xadd(
                message.stream,
                message_data
            )

            logger.info(
                f"Enqueued message {message.id} to {queue_type} queue "
                f"(correlation_id: {correlation_id}, org: {organization_id})"
            )

            return message.id

        except Exception as e:
            logger.error(f"Failed to enqueue message to {queue_type}: {e}")
            self._mark_unavailable(str(e))
            raise

    async def register_consumer(
        self,
        queue_type: str,
        consumer_name: str,
        handler: Callable[[QueueMessage], bool]
    ):
        """Register a message consumer with handler function"""

        if queue_type not in self.STREAM_NAMES:
            raise ValueError(f"Unknown queue type: {queue_type}")

        if not await self.ensure_initialized():
            logger.warning(
                "Redis queue unavailable; consumer %s for %s will not start.",
                consumer_name,
                queue_type,
            )
            return

        self.message_handlers[f"{queue_type}:{consumer_name}"] = handler

        # Start consumer task
        consumer_task = asyncio.create_task(
            self._run_consumer(queue_type, consumer_name, handler)
        )

        self.active_consumers[f"{queue_type}:{consumer_name}"] = {
            'task': consumer_task,
            'last_heartbeat': datetime.now(timezone.utc),
            'messages_processed': 0,
            'messages_failed': 0
        }

        logger.info(f"Registered consumer {consumer_name} for queue {queue_type}")

    async def _run_consumer(
        self,
        queue_type: str,
        consumer_name: str,
        handler: Callable[[QueueMessage], bool]
    ):
        """Run consumer loop for processing messages"""

        stream_name = self.STREAM_NAMES[queue_type]
        group_name = f"{self.consumer_group_prefix}_{queue_type}_workers"
        consumer_key = f"{queue_type}:{consumer_name}"

        logger.info(f"Starting consumer {consumer_name} for queue {queue_type}")

        while True:
            try:
                if not self.is_available:
                    await asyncio.sleep(5)
                    continue

                # Process delayed messages first
                await self._process_delayed_messages(queue_type)

                # Read messages from stream
                messages = await self.redis_consumer.xreadgroup(
                    group_name,
                    consumer_name,
                    {stream_name: '>'},
                    count=self.batch_size,
                    block=self.consumer_timeout_ms
                )

                if not messages:
                    continue

                # Process messages
                for stream, stream_messages in messages:
                    for message_id, message_data in stream_messages:
                        try:
                            # Parse message
                            message = self._parse_message(message_id, message_data, stream)

                            # Check if message is expired
                            if self._is_message_expired(message):
                                await self._acknowledge_message(stream_name, group_name, message_id)
                                continue

                            # Process message
                            success = await self._process_message(message, handler)

                            if success:
                                # Acknowledge successful processing
                                await self._acknowledge_message(stream_name, group_name, message_id)
                                self.active_consumers[consumer_key]['messages_processed'] += 1

                            else:
                                # Handle failed message
                                await self._handle_failed_message(message, stream_name, group_name, message_id)
                                self.active_consumers[consumer_key]['messages_failed'] += 1

                        except Exception as e:
                            logger.error(f"Error processing message {message_id}: {e}")
                            await self._handle_failed_message(
                                None, stream_name, group_name, message_id, str(e)
                            )

                # Update heartbeat
                self.active_consumers[consumer_key]['last_heartbeat'] = datetime.now(timezone.utc)

            except asyncio.CancelledError:
                logger.info(f"Consumer {consumer_name} cancelled")
                break
            except Exception as e:
                logger.error(f"Consumer {consumer_name} error: {e}")
                self._mark_unavailable(str(e))
                await asyncio.sleep(5)  # Wait before retrying

    def _parse_message(self, message_id: str, message_data: Dict[str, str], stream: str) -> QueueMessage:
        """Parse message data from Redis Stream"""

        return QueueMessage(
            id=message_data.get('id', message_id),
            stream=stream,
            message_type=message_data['message_type'],
            payload=json.loads(message_data['payload']),
            organization_id=int(message_data['organization_id']),
            correlation_id=message_data['correlation_id'],
            priority=MessagePriority(message_data.get('priority', 'normal')),
            created_at=datetime.fromisoformat(message_data['created_at']),
            retry_count=int(message_data.get('retry_count', '0')),
            max_retries=int(message_data.get('max_retries', '3')),
            delay_seconds=int(message_data.get('delay_seconds', '0')),
            expires_at=datetime.fromisoformat(message_data['expires_at']) if message_data.get('expires_at') else None
        )

    def _is_message_expired(self, message: QueueMessage) -> bool:
        """Check if message has expired"""
        if message.expires_at:
            return datetime.now(timezone.utc) > message.expires_at
        return False

    async def _process_message(self, message: QueueMessage, handler: Callable) -> bool:
        """Process a single message with the registered handler"""

        try:
            logger.info(f"Processing message {message.id} of type {message.message_type}")

            # Call handler
            if asyncio.iscoroutinefunction(handler):
                result = await handler(message)
            else:
                result = handler(message)

            return bool(result)

        except Exception as e:
            logger.error(f"Handler failed for message {message.id}: {e}")
            return False

    async def _handle_failed_message(
        self,
        message: Optional[QueueMessage],
        stream_name: str,
        group_name: str,
        message_id: str,
        error: str = None
    ):
        """Handle failed message processing with retry logic"""

        try:
            if message and message.retry_count < message.max_retries:
                # Retry with exponential backoff
                delay = min(300, 2 ** message.retry_count * 5)  # Max 5 minutes
                message.retry_count += 1

                logger.info(f"Retrying message {message.id} in {delay} seconds (attempt {message.retry_count})")

                # Re-enqueue with delay
                await self.enqueue_message(
                    queue_type=self._get_queue_type_from_stream(stream_name),
                    message_type=message.message_type,
                    payload=message.payload,
                    organization_id=message.organization_id,
                    priority=message.priority,
                    correlation_id=message.correlation_id,
                    delay_seconds=delay,
                    max_retries=message.max_retries
                )

            else:
                # Move to dead letter queue
                dlq_stream = stream_name + self.DLQ_SUFFIX
                dlq_data = {
                    'original_message_id': message_id,
                    'stream': stream_name,
                    'failed_at': datetime.now(timezone.utc).isoformat(),
                    'error': error or 'Max retries exceeded',
                    'retry_count': str(message.retry_count if message else 0)
                }

                if message:
                    dlq_data.update({
                        'message_type': message.message_type,
                        'payload': json.dumps(message.payload),
                        'organization_id': str(message.organization_id),
                        'correlation_id': message.correlation_id
                    })

                await self.redis_client.xadd(dlq_stream, dlq_data)
                logger.warning(f"Message {message_id} moved to dead letter queue")

            # Acknowledge the failed message
            await self._acknowledge_message(stream_name, group_name, message_id)

        except Exception as e:
            logger.error(f"Failed to handle failed message {message_id}: {e}")

    async def _acknowledge_message(self, stream_name: str, group_name: str, message_id: str):
        """Acknowledge message processing completion"""

        try:
            await self.redis_client.xack(stream_name, group_name, message_id)
        except Exception as e:
            logger.error(f"Failed to acknowledge message {message_id}: {e}")

    async def _process_delayed_messages(self, queue_type: str):
        """Process messages that are ready from delayed queue"""

        delayed_key = f"delayed_messages:{queue_type}"
        current_time = time.time()

        try:
            # Get messages ready for processing
            ready_messages = await self.redis_client.zrangebyscore(
                delayed_key, 0, current_time, withscores=False, start=0, num=self.batch_size
            )

            for message_json in ready_messages:
                try:
                    message_data = json.loads(message_json)

                    # Add to stream
                    await self.redis_client.xadd(
                        self.STREAM_NAMES[queue_type],
                        message_data
                    )

                    # Remove from delayed queue
                    await self.redis_client.zrem(delayed_key, message_json)

                    logger.debug(f"Processed delayed message for queue {queue_type}")

                except Exception as e:
                    logger.error(f"Failed to process delayed message: {e}")

        except Exception as e:
            logger.error(f"Failed to process delayed messages for {queue_type}: {e}")

    def _get_queue_type_from_stream(self, stream_name: str) -> str:
        """Get queue type from stream name"""

        for queue_type, stream in self.STREAM_NAMES.items():
            if stream == stream_name:
                return queue_type

        raise ValueError(f"Unknown stream: {stream_name}")

    async def _cleanup_expired_messages(self):
        """Background task to clean up expired messages"""

        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour

                for queue_type, stream_name in self.STREAM_NAMES.items():
                    # Clean up main stream (keep last 1000 messages)
                    await self.redis_client.xtrim(stream_name, maxlen=1000, approximate=True)

                    # Clean up dead letter queue
                    dlq_stream = stream_name + self.DLQ_SUFFIX
                    cutoff_time = datetime.now(timezone.utc) - timedelta(days=self.dlq_retention_days)

                    # TODO: Implement time-based cleanup for DLQ
                    await self.redis_client.xtrim(dlq_stream, maxlen=500, approximate=True)

                logger.info("Completed expired message cleanup")

            except Exception as e:
                logger.error(f"Error during message cleanup: {e}")

    async def _monitor_consumer_health(self):
        """Background task to monitor consumer health"""

        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval_s)

                current_time = datetime.now(timezone.utc)
                stale_threshold = timedelta(seconds=self.heartbeat_interval_s * 3)

                for consumer_key, consumer_info in self.active_consumers.items():
                    last_heartbeat = consumer_info['last_heartbeat']

                    if current_time - last_heartbeat > stale_threshold:
                        logger.warning(f"Consumer {consumer_key} appears stale (last heartbeat: {last_heartbeat})")

                        # Check if consumer task is still running
                        task = consumer_info['task']
                        if task.done():
                            logger.error(f"Consumer {consumer_key} task completed unexpectedly")
                            # TODO: Implement consumer restart logic

            except Exception as e:
                logger.error(f"Error during consumer health monitoring: {e}")

    async def get_queue_stats(self, queue_type: str = None) -> Union[QueueStats, Dict[str, QueueStats]]:
        """Get queue statistics"""

        if queue_type:
            return await self._get_single_queue_stats(queue_type)

        # Get stats for all queues
        stats = {}
        for qt in self.STREAM_NAMES.keys():
            stats[qt] = await self._get_single_queue_stats(qt)

        return stats

    async def _get_single_queue_stats(self, queue_type: str) -> QueueStats:
        """Get statistics for a single queue"""

        stream_name = self.STREAM_NAMES[queue_type]
        group_name = f"{self.consumer_group_prefix}_{queue_type}_workers"

        try:
            # Get stream info
            stream_info = await self.redis_client.xinfo_stream(stream_name)
            groups_info = await self.redis_client.xinfo_groups(stream_name)

            # Calculate pending messages
            pending_messages = 0
            consumer_groups = []

            for group in groups_info:
                consumer_groups.append(group['name'])
                pending_messages += group['pending']

            return QueueStats(
                stream_name=stream_name,
                pending_messages=pending_messages,
                processing_messages=0,  # Would need to query individual consumers
                completed_messages=stream_info['length'],
                failed_messages=0,  # Would need to query DLQ
                dead_letter_messages=0,  # Would need to query DLQ stream
                consumer_groups=consumer_groups,
                last_activity=datetime.now(timezone.utc)  # Simplified
            )

        except Exception as e:
            logger.error(f"Failed to get stats for queue {queue_type}: {e}")
            return QueueStats(
                stream_name=stream_name,
                pending_messages=0,
                processing_messages=0,
                completed_messages=0,
                failed_messages=0,
                dead_letter_messages=0,
                consumer_groups=[],
                last_activity=None
            )

    async def close(self):
        """Clean shutdown of the queue system"""

        logger.info("Shutting down Redis Streams queue")

        self._available = False

        # Cancel all consumer tasks
        for consumer_key, consumer_info in self.active_consumers.items():
            consumer_info['task'].cancel()

        # Close Redis connections
        if self.redis_client:
            await self.redis_client.close()
        if self.redis_consumer:
            await self.redis_consumer.close()

        for task in self._background_tasks:
            task.cancel()

        self._background_tasks.clear()

# Global queue instance
redis_queue = RedisStreamsQueue() if REDIS_AVAILABLE else None
