"""
WebSocket Manager for Real-time Updates

Handles WebSocket connections for approval queue updates, workflow progress,
and other real-time features in the VouchLink AI corporate platform.
"""

import os
import asyncio
import json
import logging
import weakref
from typing import Dict, Set, Optional, Any, List
from datetime import datetime
from dataclasses import dataclass, asdict
import uuid

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError
import redis.asyncio as redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

@dataclass
class WebSocketConnection:
    websocket: Any
    connection_id: str
    tenant_id: str
    user_id: Optional[str]
    connected_at: datetime
    last_ping: datetime

class WebSocketManager:
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.connections: Dict[str, WebSocketConnection] = {}
        self.tenant_connections: Dict[str, Set[str]] = {}  # tenant_id -> connection_ids
        self.channel_subscriptions: Dict[str, Set[str]] = {}
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub_task: Optional[asyncio.Task] = None

        # Connection management
        self.connection_cleanup_interval = 30  # seconds
        self.ping_interval = 25  # seconds
        self.max_connections_per_tenant = 10

    async def initialize(self):
        """Initialize Redis connection and pubsub listener"""
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            await self.redis_client.ping()

            # Start pubsub listener for cross-instance communication
            self.pubsub_task = asyncio.create_task(self._listen_redis_messages())

            # Start connection cleanup task
            asyncio.create_task(self._connection_cleanup_loop())

            logger.info("WebSocket manager initialized successfully")
        except RedisError as e:
            logger.error(f"Failed to initialize Redis connection: {e}")
            raise

    async def register_connection(self, websocket, tenant_id: str, user_id: Optional[str] = None) -> str:
        """Register a new WebSocket connection"""
        connection_id = str(uuid.uuid4())

        # Check connection limits per tenant
        tenant_connections = self.tenant_connections.get(tenant_id, set())
        if len(tenant_connections) >= self.max_connections_per_tenant:
            logger.warning(f"Connection limit reached for tenant {tenant_id}")
            raise websockets.exceptions.ConnectionClosed(1013, "Too many connections")

        connection = WebSocketConnection(
            websocket=websocket,
            connection_id=connection_id,
            tenant_id=tenant_id,
            user_id=user_id,
            connected_at=datetime.utcnow(),
            last_ping=datetime.utcnow()
        )

        self.connections[connection_id] = connection

        if tenant_id not in self.tenant_connections:
            self.tenant_connections[tenant_id] = set()
        self.tenant_connections[tenant_id].add(connection_id)

        self.channel_subscriptions[connection_id] = set()

        logger.info(f"WebSocket connection registered: {connection_id} (tenant: {tenant_id}, user: {user_id})")

        # Send initial connection acknowledgment
        await self._send_to_connection(connection_id, {
            "type": "connection_ack",
            "connection_id": connection_id,
            "timestamp": datetime.utcnow().isoformat()
        })

        return connection_id

    async def unregister_connection(self, connection_id: str):
        """Unregister a WebSocket connection"""
        if connection_id in self.connections:
            connection = self.connections[connection_id]
            tenant_id = connection.tenant_id

            # Remove from connections
            del self.connections[connection_id]
            self.channel_subscriptions.pop(connection_id, None)

            # Remove from tenant connections
            if tenant_id in self.tenant_connections:
                self.tenant_connections[tenant_id].discard(connection_id)
                if not self.tenant_connections[tenant_id]:
                    del self.tenant_connections[tenant_id]

            logger.info(f"WebSocket connection unregistered: {connection_id}")

    async def handle_connection(self, websocket, path: str):
        """Handle a WebSocket connection for the duration of its lifetime"""
        connection_id = None
        try:
            # Parse tenant_id from path (e.g., /ws/approvals/123)
            path_parts = path.strip('/').split('/')
            if len(path_parts) >= 3 and path_parts[0] == 'ws' and path_parts[1] == 'approvals':
                tenant_id = path_parts[2]
                user_id = path_parts[3] if len(path_parts) > 3 else None
            else:
                await websocket.close(1002, "Invalid path")
                return

            connection_id = await self.register_connection(websocket, tenant_id, user_id)

            # Handle incoming messages
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_client_message(connection_id, data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from connection {connection_id}")
                except Exception as e:
                    logger.error(f"Error handling message from {connection_id}: {e}")

        except ConnectionClosed:
            logger.info(f"WebSocket connection {connection_id} closed normally")
        except ConnectionClosedError as e:
            logger.info(f"WebSocket connection {connection_id} closed with error: {e}")
        except Exception as e:
            logger.error(f"Error in WebSocket handler: {e}")
        finally:
            if connection_id:
                await self.unregister_connection(connection_id)

    async def _handle_client_message(self, connection_id: str, data: Dict[str, Any]):
        """Handle messages from clients"""
        message_type = data.get('type')

        if message_type == 'ping':
            # Update last ping time
            if connection_id in self.connections:
                self.connections[connection_id].last_ping = datetime.utcnow()

            # Send pong response
            await self._send_to_connection(connection_id, {
                "type": "pong",
                "timestamp": datetime.utcnow().isoformat()
            })

        elif message_type == 'subscribe':
            # Handle subscription to specific channels
            channels = data.get('channels', [])
            registered = self.channel_subscriptions.setdefault(connection_id, set())
            if isinstance(channels, list):
                for channel in channels:
                    if isinstance(channel, str) and channel:
                        registered.add(channel)
            single_channel = data.get('channel')
            if isinstance(single_channel, str) and single_channel:
                registered.add(single_channel)

        elif message_type == 'unsubscribe':
            channels = data.get('channels', [])
            registered = self.channel_subscriptions.get(connection_id)
            if not registered:
                return
            if isinstance(channels, list) and channels:
                for channel in channels:
                    if isinstance(channel, str):
                        registered.discard(channel)
            single_channel = data.get('channel')
            if isinstance(single_channel, str) and single_channel:
                registered.discard(single_channel)

        else:
            logger.warning(f"Unknown message type '{message_type}' from connection {connection_id}")

    async def broadcast_approval_update(self, tenant_id: str, approval_data: Dict[str, Any]):
        """Broadcast approval update to all connections for a tenant"""
        message = {
            "type": "approval_request",
            "approval": approval_data,
            "timestamp": datetime.utcnow().isoformat()
        }

        channel_name = f"approval:{tenant_id}"
        await self._broadcast_to_tenant(tenant_id, message, channel=channel_name)

        # Also publish to Redis for cross-instance communication
        if self.redis_client:
            try:
                await self.redis_client.publish(f"approvals:{tenant_id}", json.dumps(message))
            except RedisError as e:
                logger.error(f"Failed to publish to Redis: {e}")

    async def broadcast_workflow_update(self, tenant_id: str, workflow_data: Dict[str, Any]):
        """Broadcast workflow update to all connections for a tenant"""
        message = {
            "type": "workflow_update",
            "workflow": workflow_data,
            "timestamp": datetime.utcnow().isoformat()
        }

        await self._broadcast_to_tenant(tenant_id, message)

        # Also publish to Redis for cross-instance communication
        if self.redis_client:
            try:
                await self.redis_client.publish(f"workflows:{tenant_id}", json.dumps(message))
            except RedisError as e:
                logger.error(f"Failed to publish to Redis: {e}")

    async def broadcast_cookie_update(self, tenant_id: str, cookie_data: Dict[str, Any]):
        """Broadcast cookie jar updates to interested dashboards."""

        message = {
            "type": "cookie_update",
            "cookie": cookie_data,
            "timestamp": datetime.utcnow().isoformat(),
        }

        channel_name = f"cookie:{tenant_id}"
        await self._broadcast_to_tenant(tenant_id, message, channel=channel_name)

        if self.redis_client:
            try:
                await self.redis_client.publish(f"cookies:{tenant_id}", json.dumps(message))
            except RedisError as exc:
                logger.error("Failed to publish cookie update to Redis: %s", exc)

    async def send_notification(self, tenant_id: str, user_id: Optional[str], notification: Dict[str, Any]):
        """Send notification to specific user or all users in tenant"""
        message = {
            "type": "notification",
            "notification": notification,
            "timestamp": datetime.utcnow().isoformat()
        }

        if user_id:
            # Send to specific user
            await self._send_to_user(tenant_id, user_id, message)
        else:
            # Send to all users in tenant
            await self._broadcast_to_tenant(tenant_id, message)

    async def send_to_organization(self, tenant_id: str, event: str, payload: Dict[str, Any]):
        """
        Broadcast an event to all users within an organization (tenant).
        This is syntactic sugar around broadcast_workflow_update and broadcast_approval_update
        depending on event type; other events use emit.
        """
        # Determine which broadcast channel to use
        if event == "workflow_update":
            await self.broadcast_workflow_update(tenant_id, payload)
        elif event == "approval_update":
            await self.broadcast_approval_update(tenant_id, payload)
        else:
            await self.emit(event, payload, tenant_id=tenant_id)

    async def _broadcast_to_tenant(
        self,
        tenant_id: str,
        message: Dict[str, Any],
        channel: Optional[str] = None,
    ):
        """Broadcast message to all connections for a tenant"""
        if tenant_id not in self.tenant_connections:
            return

        connection_ids = list(self.tenant_connections[tenant_id])

        # Send to all connections concurrently
        tasks = []
        for connection_id in connection_ids:
            if channel:
                subscriptions = self.channel_subscriptions.get(connection_id)
                if not subscriptions:
                    continue
                channel_base = channel.split(":", 1)[0]
                allowed = {channel}
                if channel_base:
                    allowed.add(channel_base)
                    allowed.add(f"{channel_base}:*")
                if subscriptions.isdisjoint(allowed):
                    continue
            task = self._send_to_connection(connection_id, message)
            tasks.append(task)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log any failures
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to send message to connection {connection_ids[i]}: {result}")

    async def _send_to_user(self, tenant_id: str, user_id: str, message: Dict[str, Any]):
        """Send message to all connections for a specific user"""
        if tenant_id not in self.tenant_connections:
            return

        # Find connections for the specific user
        user_connections = []
        for connection_id in self.tenant_connections[tenant_id]:
            connection = self.connections.get(connection_id)
            if connection and connection.user_id == user_id:
                user_connections.append(connection_id)

        # Send to user's connections
        tasks = []
        for connection_id in user_connections:
            task = self._send_to_connection(connection_id, message)
            tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def emit(self, event_type: str, data: Dict[str, Any], room: Optional[str] = None, tenant_id: Optional[str] = None):
        """
        Emit a message to WebSocket connections

        Args:
            event_type: Type of event (e.g., 'communication_message', 'approval_request')
            data: Data payload to send
            room: Room identifier (conversation:ID, org:ID) or None for tenant-wide
            tenant_id: Tenant ID if room is None
        """
        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }

        if room:
            # Parse room format: conversation:ID or org:ID
            if room.startswith("conversation:"):
                # For conversation rooms, broadcast to all participants' organizations
                # In real implementation, you'd lookup conversation participants
                # For now, extract tenant from data if available
                if "organization_id" in data:
                    await self._broadcast_to_tenant(str(data["organization_id"]), message)
            elif room.startswith("approval:"):
                tenant_room = room.split(":", 1)[1]
                await self._broadcast_to_tenant(tenant_room, message, channel=room)
            elif room == "approval":
                tenant_room = str(data.get("tenant_id") or data.get("organization_id") or "")
                if tenant_room:
                    namespaced_room = f"approval:{tenant_room}"
                    await self._broadcast_to_tenant(tenant_room, message, channel=namespaced_room)
            elif room.startswith("org:"):
                org_id = room.replace("org:", "")
                await self._broadcast_to_tenant(org_id, message)
        elif tenant_id:
            await self._broadcast_to_tenant(tenant_id, message)

    async def _send_to_connection(self, connection_id: str, message: Dict[str, Any]):
        """Send message to a specific connection"""
        if connection_id not in self.connections:
            return

        connection = self.connections[connection_id]

        try:
            message_json = json.dumps(message)
            await connection.websocket.send(message_json)
        except ConnectionClosed:
            # Connection was closed, remove it
            await self.unregister_connection(connection_id)
        except Exception as e:
            logger.error(f"Error sending message to connection {connection_id}: {e}")
            await self.unregister_connection(connection_id)

    async def _listen_redis_messages(self):
        """Listen for Redis pub/sub messages for cross-instance communication"""
        if not self.redis_client:
            return

        try:
            pubsub = self.redis_client.pubsub()

            # Subscribe to all tenant approval and workflow channels
            # In practice, you might want to be more selective
            await pubsub.psubscribe("approvals:*", "workflows:*", "cookies:*", "notifications:*")

            logger.info("Started listening for Redis pub/sub messages")

            async for message in pubsub.listen():
                if message['type'] == 'pmessage':
                    try:
                        channel = message['channel']
                        data = json.loads(message['data'])

                        # Extract tenant_id from channel
                        if ':' in channel:
                            _, tenant_id = channel.split(':', 1)

                            # Forward to local connections
                            if channel.startswith("approvals:"):
                                target_channel = f"approval:{tenant_id}"
                            elif channel.startswith("workflows:"):
                                target_channel = f"workflow:{tenant_id}"
                            elif channel.startswith("cookies:"):
                                target_channel = f"cookie:{tenant_id}"
                            else:
                                target_channel = None

                            await self._broadcast_to_tenant(
                                tenant_id,
                                data,
                                channel=target_channel,
                            )

                    except Exception as e:
                        logger.error(f"Error processing Redis message: {e}")

        except Exception as e:
            logger.error(f"Redis pub/sub listener error: {e}")
        finally:
            if self.redis_client:
                await pubsub.unsubscribe()

    async def _connection_cleanup_loop(self):
        """Periodic cleanup of dead connections"""
        while True:
            try:
                await asyncio.sleep(self.connection_cleanup_interval)
                await self._cleanup_dead_connections()
            except Exception as e:
                logger.error(f"Error in connection cleanup loop: {e}")

    async def _cleanup_dead_connections(self):
        """Remove connections that haven't responded to pings"""
        now = datetime.utcnow()
        dead_connections = []

        for connection_id, connection in self.connections.items():
            # Check if connection hasn't pinged in too long
            time_since_ping = (now - connection.last_ping).total_seconds()

            if time_since_ping > self.ping_interval * 2:  # 2x ping interval
                dead_connections.append(connection_id)

        # Remove dead connections
        for connection_id in dead_connections:
            logger.info(f"Removing dead connection: {connection_id}")
            await self.unregister_connection(connection_id)

    async def get_connection_stats(self) -> Dict[str, Any]:
        """Get statistics about current connections"""
        return {
            "total_connections": len(self.connections),
            "connections_by_tenant": {
                tenant_id: len(connection_ids)
                for tenant_id, connection_ids in self.tenant_connections.items()
            },
            "redis_connected": self.redis_client is not None
        }

    async def shutdown(self):
        """Shutdown the WebSocket manager"""
        # Close all connections
        for connection in self.connections.values():
            try:
                await connection.websocket.close()
            except:
                pass

        # Stop pubsub task
        if self.pubsub_task:
            self.pubsub_task.cancel()
            try:
                await self.pubsub_task
            except asyncio.CancelledError:
                pass

        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()

        logger.info("WebSocket manager shut down successfully")

# Global WebSocket manager instance
ws_manager = WebSocketManager(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
