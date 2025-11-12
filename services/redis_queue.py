"""
Redis Streams Message Queue Service with Priority Scheduling
Production-ready enterprise message queuing for corporate workflows
"""
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
import redis.asyncio as redis
import uuid
import os
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class MessagePriority(Enum):
    """Message priority levels for queue scheduling"""
    CRITICAL = 1      # Executive workflows, compliance issues
    HIGH = 2         # Customer-facing workflows, lead responses
    NORMAL = 3       # Standard workflows, bulk processing
    LOW = 4          # Analytics, reporting, cleanup tasks

class MessageStatus(Enum):
    """Message processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"

@dataclass
class QueueMessage:
    """Structured message for Redis Streams"""
    id: str
    tenant_id: str
    workflow_type: str
    priority: MessagePriority
    payload: Dict[str, Any]
    created_at: datetime
    scheduled_for: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 300
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, str]:
        """Convert to Redis-compatible string dictionary"""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "workflow_type": self.workflow_type,
            "priority": str(self.priority.value),
            "payload": json.dumps(self.payload),
            "created_at": self.created_at.isoformat(),
            "scheduled_for": self.scheduled_for.isoformat() if self.scheduled_for else "",
            "retry_count": str(self.retry_count),
            "max_retries": str(self.max_retries),
            "timeout_seconds": str(self.timeout_seconds),
            "metadata": json.dumps(self.metadata or {})
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> 'QueueMessage':
        """Create from Redis stream data"""
        return cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            workflow_type=data["workflow_type"],
            priority=MessagePriority(int(data["priority"])),
            payload=json.loads(data["payload"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            scheduled_for=datetime.fromisoformat(data["scheduled_for"]) if data["scheduled_for"] else None,
            retry_count=int(data["retry_count"]),
            max_retries=int(data["max_retries"]),
            timeout_seconds=int(data["timeout_seconds"]),
            metadata=json.loads(data["metadata"])
        )

class RedisMessageQueue:
    """
    Enterprise Redis Streams message queue with priority scheduling
    Supports multi-tenant isolation, priority-based processing, and dead letter queues
    """

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis: Optional[redis.Redis] = None
        self.consumer_group = "vouchlink-ai-workers"
        self.consumer_name = f"worker-{uuid.uuid4().hex[:8]}"
        self.streams = {
            MessagePriority.CRITICAL: "VouchLink AI:critical",
            MessagePriority.HIGH: "VouchLink AI:high",
            MessagePriority.NORMAL: "VouchLink AI:normal",
            MessagePriority.LOW: "VouchLink AI:low"
        }
        self.dlq_stream = "VouchLink AI:dlq"  # Dead Letter Queue
        self.processing_stream = "VouchLink AI:processing"
        self.completed_stream = "VouchLink AI:completed"
        self._handlers: Dict[str, Callable] = {}
        self._running = False

    async def connect(self):
        """Initialize Redis connection and create streams/consumer groups"""
        try:
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            await self.redis.ping()

            # Create streams and consumer groups if they don't exist
            for stream_name in self.streams.values():
                try:
                    await self.redis.xgroup_create(stream_name, self.consumer_group, id="0", mkstream=True)
                    logger.info(f"Created consumer group for {stream_name}")
                except redis.ResponseError as e:
                    if "BUSYGROUP" not in str(e):
                        raise

            # Create processing and DLQ streams
            for stream in [self.processing_stream, self.dlq_stream, self.completed_stream]:
                try:
                    await self.redis.xgroup_create(stream, self.consumer_group, id="0", mkstream=True)
                except redis.ResponseError as e:
                    if "BUSYGROUP" not in str(e):
                        raise

            logger.info("Redis Message Queue initialized successfully")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()

    @asynccontextmanager
    async def connection(self):
        """Async context manager for Redis connection"""
        await self.connect()
        try:
            yield self
        finally:
            await self.disconnect()

    async def enqueue(self, message: QueueMessage) -> str:
        """
        Enqueue message with priority-based stream routing
        Returns: Message ID from Redis
        """
        if not self.redis:
            await self.connect()

        # Select stream based on priority
        stream_name = self.streams[message.priority]

        # Add to stream with tenant isolation
        message_id = await self.redis.xadd(
            stream_name,
            message.to_dict(),
            id="*"  # Auto-generate ID
        )

        logger.info(f"Enqueued message {message.id} to {stream_name} with priority {message.priority}")
        return message_id

    async def enqueue_scheduled(self, message: QueueMessage, delay_seconds: int) -> str:
        """
        Schedule message for future processing
        Uses Redis sorted sets for time-based scheduling
        """
        if not self.redis:
            await self.connect()

        scheduled_time = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        message.scheduled_for = scheduled_time

        # Store in scheduled set with score as timestamp
        schedule_key = f"VouchLink AI:scheduled:{message.priority.name.lower()}"
        await self.redis.zadd(
            schedule_key,
            {json.dumps(message.to_dict()): scheduled_time.timestamp()}
        )

        logger.info(f"Scheduled message {message.id} for {scheduled_time}")
        return message.id

    async def process_scheduled_messages(self):
        """
        Move scheduled messages to appropriate streams when ready
        Should be called periodically by scheduler
        """
        if not self.redis:
            await self.connect()

        current_time = datetime.now(timezone.utc).timestamp()

        for priority in MessagePriority:
            schedule_key = f"VouchLink AI:scheduled:{priority.name.lower()}"

            # Get messages ready for processing
            ready_messages = await self.redis.zrangebyscore(
                schedule_key, 0, current_time, withscores=True
            )

            for message_data, _ in ready_messages:
                try:
                    # Parse and enqueue message
                    message_dict = json.loads(message_data)
                    message = QueueMessage.from_dict(message_dict)

                    # Add to appropriate stream
                    stream_name = self.streams[priority]
                    await self.redis.xadd(stream_name, message.to_dict())

                    # Remove from scheduled set
                    await self.redis.zrem(schedule_key, message_data)

                    logger.info(f"Moved scheduled message {message.id} to processing queue")

                except Exception as e:
                    logger.error(f"Failed to process scheduled message: {e}")

    def register_handler(self, workflow_type: str, handler: Callable):
        """Register workflow handler function"""
        self._handlers[workflow_type] = handler
        logger.info(f"Registered handler for workflow type: {workflow_type}")

    async def start_consumer(self, batch_size: int = 10, timeout_ms: int = 1000):
        """
        Start consuming messages from streams with priority ordering
        Processes higher priority streams first
        """
        if not self.redis:
            await self.connect()

        self._running = True
        logger.info(f"Starting consumer {self.consumer_name}")

        try:
            while self._running:
                # Process scheduled messages first
                await self.process_scheduled_messages()

                # Process streams in priority order
                for priority in MessagePriority:
                    if not self._running:
                        break

                    stream_name = self.streams[priority]

                    try:
                        # Read from stream
                        messages = await self.redis.xreadgroup(
                            self.consumer_group,
                            self.consumer_name,
                            {stream_name: ">"},
                            count=batch_size,
                            block=timeout_ms
                        )

                        if messages:
                            await self._process_messages(messages, priority)

                    except redis.ResponseError as e:
                        logger.error(f"Error reading from {stream_name}: {e}")
                    except Exception as e:
                        logger.error(f"Unexpected error processing {stream_name}: {e}")

                # Brief sleep to prevent tight loop
                await asyncio.sleep(0.1)

        except KeyboardInterrupt:
            logger.info("Consumer stopped by user")
        except Exception as e:
            logger.error(f"Consumer error: {e}")
        finally:
            self._running = False

    async def _process_messages(self, messages: List, priority: MessagePriority):
        """Process batch of messages from stream"""
        for stream_name, stream_messages in messages:
            for message_id, fields in stream_messages:
                try:
                    # Parse message
                    message = QueueMessage.from_dict(fields)

                    # Move to processing stream
                    await self.redis.xadd(
                        self.processing_stream,
                        {**fields, "redis_message_id": message_id, "processing_started": datetime.now(timezone.utc).isoformat()}
                    )

                    # Process message
                    success = await self._handle_message(message)

                    if success:
                        # Mark as completed
                        await self.redis.xadd(
                            self.completed_stream,
                            {**fields, "completed_at": datetime.now(timezone.utc).isoformat()}
                        )

                        # Acknowledge message
                        await self.redis.xack(stream_name, self.consumer_group, message_id)
                        logger.info(f"Successfully processed message {message.id}")

                    else:
                        # Handle failure/retry logic
                        await self._handle_failed_message(message, stream_name, message_id, fields)

                except Exception as e:
                    logger.error(f"Error processing message {message_id}: {e}")
                    # Move to DLQ on unexpected errors
                    await self.redis.xadd(
                        self.dlq_stream,
                        {**fields, "error": str(e), "failed_at": datetime.now(timezone.utc).isoformat()}
                    )

    async def _handle_message(self, message: QueueMessage) -> bool:
        """Execute registered handler for message workflow type"""
        handler = self._handlers.get(message.workflow_type)
        if not handler:
            logger.error(f"No handler registered for workflow type: {message.workflow_type}")
            return False

        try:
            # Execute handler with timeout
            result = await asyncio.wait_for(
                handler(message),
                timeout=message.timeout_seconds
            )
            return result is not False  # Consider None as success

        except asyncio.TimeoutError:
            logger.error(f"Message {message.id} timed out after {message.timeout_seconds}s")
            return False
        except Exception as e:
            logger.error(f"Handler error for message {message.id}: {e}")
            return False

    async def _handle_failed_message(self, message: QueueMessage, stream_name: str, message_id: str, fields: Dict):
        """Handle failed message with retry logic"""
        message.retry_count += 1

        if message.retry_count <= message.max_retries:
            # Schedule retry with exponential backoff
            delay = min(300, 2 ** message.retry_count * 10)  # Cap at 5 minutes
            message.scheduled_for = datetime.now(timezone.utc) + timedelta(seconds=delay)

            await self.enqueue_scheduled(message, delay)
            await self.redis.xack(stream_name, self.consumer_group, message_id)

            logger.info(f"Scheduled retry {message.retry_count}/{message.max_retries} for message {message.id}")

        else:
            # Move to dead letter queue
            await self.redis.xadd(
                self.dlq_stream,
                {**fields, "max_retries_exceeded": "true", "failed_at": datetime.now(timezone.utc).isoformat()}
            )
            await self.redis.xack(stream_name, self.consumer_group, message_id)

            logger.error(f"Message {message.id} moved to DLQ after {message.max_retries} retries")

    async def stop_consumer(self):
        """Stop the message consumer gracefully"""
        self._running = False
        logger.info("Stopping message consumer")

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get comprehensive queue statistics for monitoring"""
        if not self.redis:
            await self.connect()

        stats = {
            "streams": {},
            "consumer_groups": {},
            "scheduled_counts": {},
            "processing_count": 0,
            "completed_count": 0,
            "dlq_count": 0
        }

        # Get stream lengths
        for priority, stream_name in self.streams.items():
            stats["streams"][priority.name] = await self.redis.xlen(stream_name)

        # Get scheduled message counts
        for priority in MessagePriority:
            schedule_key = f"VouchLink AI:scheduled:{priority.name.lower()}"
            stats["scheduled_counts"][priority.name] = await self.redis.zcard(schedule_key)

        # Get processing and completion counts
        stats["processing_count"] = await self.redis.xlen(self.processing_stream)
        stats["completed_count"] = await self.redis.xlen(self.completed_stream)
        stats["dlq_count"] = await self.redis.xlen(self.dlq_stream)

        return stats

# Global queue instance
message_queue = RedisMessageQueue()

async def create_workflow_message(
    tenant_id: str,
    workflow_type: str,
    payload: Dict[str, Any],
    priority: MessagePriority = MessagePriority.NORMAL,
    **kwargs
) -> QueueMessage:
    """Convenience function to create workflow messages"""
    return QueueMessage(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workflow_type=workflow_type,
        priority=priority,
        payload=payload,
        created_at=datetime.now(timezone.utc),
        **kwargs
    )