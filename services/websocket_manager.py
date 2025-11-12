"""
WebSocket Manager Service - September 2025
Real-time communication for VouchLink AI Corporate Dashboard
"""

import asyncio
import logging
import json
from typing import Dict, List, Set, Optional, Any
from datetime import datetime, timezone
import websockets
from websockets.server import WebSocketServerProtocol
import uuid

logger = logging.getLogger(__name__)

class WebSocketManager:
    """
    Manages WebSocket connections for real-time communication
    """

    def __init__(self):
        self.connections: Dict[str, WebSocketServerProtocol] = {}
        self.organization_rooms: Dict[int, Set[str]] = {}
        self.approval_rooms: Set[str] = set()

        # Enterprise persistence and resilience for workflow room management
        from .workflow_persistence_service import workflow_persistence_service
        self.persistence_service = workflow_persistence_service

        from .resilience_patterns import ResilienceManager, BulkheadConfig, BulkheadType
        self.resilience_manager = ResilienceManager()

        from .error_handling_framework import ErrorHandler
        self.error_handler = ErrorHandler()

        # Redis for real-time workflow room management
        import redis.asyncio as redis
        self.redis_client: Optional[redis.Redis] = None

        # Register bulkhead for WebSocket operations
        self.resilience_manager.create_bulkhead(BulkheadConfig(
            name="websocket_manager",
            bulkhead_type=BulkheadType.THREAD_POOL,
            max_concurrent=20
        ))

    async def initialize(self):
        """Initialize Redis connection for workflow room management"""
        try:
            import redis.asyncio as redis
            redis_pool = redis.ConnectionPool.from_url("redis://localhost:6379", decode_responses=True)
            self.redis_client = redis.Redis(connection_pool=redis_pool)
            logger.info("✅ WebSocket Manager initialized with Redis")
        except Exception as e:
            logger.warning(f"Failed to initialize Redis for WebSocket Manager: {e}")
            self.redis_client = None

    async def connect(self, websocket: WebSocketServerProtocol, user_id: str, organization_id: int = None):
        """Register a new WebSocket connection"""
        connection_id = str(uuid.uuid4())
        self.connections[connection_id] = websocket

        if organization_id:
            if organization_id not in self.organization_rooms:
                self.organization_rooms[organization_id] = set()
            self.organization_rooms[organization_id].add(connection_id)

        logger.info(f"WebSocket connected: {connection_id} (user: {user_id}, org: {organization_id})")
        return connection_id

    async def disconnect(self, connection_id: str):
        """Remove a WebSocket connection"""
        if connection_id in self.connections:
            del self.connections[connection_id]

        # Remove from all rooms
        for org_connections in self.organization_rooms.values():
            org_connections.discard(connection_id)

        self.approval_rooms.discard(connection_id)

        # Remove from workflow rooms in Redis
        if self.redis_client:
            try:
                # Find and remove from all workflow rooms
                workflow_keys = await self.redis_client.keys("workflow_room:*")
                for key in workflow_keys:
                    await self.redis_client.srem(key, connection_id)
            except Exception as e:
                logger.error(f"Failed to remove connection from Redis workflow rooms: {e}")

        logger.info(f"WebSocket disconnected: {connection_id}")

    async def join_organization_room(self, organization_id: int, connection_id: str = None):
        """Join an organization-specific room"""
        if organization_id not in self.organization_rooms:
            self.organization_rooms[organization_id] = set()

        if connection_id:
            self.organization_rooms[organization_id].add(connection_id)

    async def join_approval_room(self, connection_id: str = None):
        """Join the approval queue room"""
        if connection_id:
            self.approval_rooms.add(connection_id)

    async def join_workflow_room(self, workflow_id: str, connection_id: str = None):
        """Join a workflow-specific room using Redis for persistence"""
        if connection_id and self.redis_client:
            try:
                # Use bulkhead for Redis operations
                async with self.resilience_manager.get_bulkhead("websocket_manager"):
                    # Store workflow room membership in Redis
                    redis_key = f"workflow_room:{workflow_id}"
                    await self.redis_client.sadd(redis_key, connection_id)

                    # Set expiration for cleanup (24 hours)
                    await self.redis_client.expire(redis_key, 86400)

                    logger.debug(f"Connection {connection_id} joined workflow room {workflow_id}")
            except Exception as e:
                logger.error(f"Failed to join workflow room in Redis: {e}")
                # Fallback to memory-based storage
                if workflow_id not in getattr(self, '_fallback_workflow_rooms', {}):
                    if not hasattr(self, '_fallback_workflow_rooms'):
                        self._fallback_workflow_rooms = {}
                    self._fallback_workflow_rooms[workflow_id] = set()
                self._fallback_workflow_rooms[workflow_id].add(connection_id)

    async def send_to_connection(self, connection_id: str, message: Dict[str, Any]):
        """Send a message to a specific connection"""
        if connection_id in self.connections:
            try:
                websocket = self.connections[connection_id]
                await websocket.send(json.dumps(message))
            except Exception as e:
                logger.error(f"Failed to send message to {connection_id}: {e}")
                await self.disconnect(connection_id)

    async def broadcast_to_organization(self, organization_id: int, message: Dict[str, Any]):
        """Broadcast a message to all connections in an organization"""
        if organization_id in self.organization_rooms:
            for connection_id in self.organization_rooms[organization_id].copy():
                await self.send_to_connection(connection_id, message)

    async def broadcast_to_approval_room(self, message: Dict[str, Any]):
        """Broadcast a message to all approval queue subscribers"""
        for connection_id in self.approval_rooms.copy():
            await self.send_to_connection(connection_id, message)

    async def broadcast_to_workflow(self, workflow_id: str, message: Dict[str, Any]):
        """Broadcast a message to all workflow subscribers using Redis persistence"""
        connection_ids = set()

        # Get connections from Redis
        if self.redis_client:
            try:
                redis_key = f"workflow_room:{workflow_id}"
                redis_connections = await self.redis_client.smembers(redis_key)
                connection_ids.update(redis_connections)
            except Exception as e:
                logger.error(f"Failed to get workflow room from Redis: {e}")

        # Fallback to memory-based storage
        fallback_rooms = getattr(self, '_fallback_workflow_rooms', {})
        if workflow_id in fallback_rooms:
            connection_ids.update(fallback_rooms[workflow_id])

        # Send message to all connections
        for connection_id in connection_ids.copy():
            await self.send_to_connection(connection_id, message)

    async def emit(self, event: str, data: Dict[str, Any], room: str = None):
        """Emit an event to specified room or globally"""
        message = {
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        if room == "approval":
            await self.broadcast_to_approval_room(message)
        elif room and room.startswith("org:"):
            org_id = int(room.split(":")[1])
            await self.broadcast_to_organization(org_id, message)
        elif room and room.startswith("workflow:"):
            workflow_id = room.split(":", 1)[1]
            await self.broadcast_to_workflow(workflow_id, message)
        else:
            # Broadcast to all connections
            for connection_id in list(self.connections.keys()):
                await self.send_to_connection(connection_id, message)

    def on(self, event: str, handler):
        """Register an event handler (placeholder for compatibility)"""
        pass

    def off(self, event: str, handler):
        """Remove an event handler (placeholder for compatibility)"""
        pass

    async def send_to_organization(self, tenant_id: str, event: str, payload: Dict[str, Any]):
        """
        Broadcast an event to all users within an organization (tenant).
        This is syntactic sugar around the emit method using org:tenant_id room format.
        """
        await self.emit(event, payload, room=f"org:{tenant_id}")

# Global WebSocket manager instance
websocket_manager = WebSocketManager()