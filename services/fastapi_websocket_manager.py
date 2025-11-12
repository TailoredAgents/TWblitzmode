"""
FastAPI WebSocket Connection Manager for Real-Time Link Chat
Provides FastAPI-compatible WebSocket management with tenant isolation and enterprise features.

Features:
- Multi-user WebSocket connection management
- Organization-scoped connection tracking
- Real-time message broadcasting
- Connection lifecycle management
- Integration with existing resilience patterns
"""

import logging
import json
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from fastapi import WebSocket, WebSocketDisconnect
import asyncio

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    FastAPI-compatible WebSocket connection manager
    Manages active connections per user with organization-scoped isolation
    """

    def __init__(self):
        # User ID -> List of active WebSocket connections
        self.active_connections: Dict[int, List[WebSocket]] = {}

        # Organization ID -> Set of connected user IDs (for organization-wide broadcasts)
        self.organization_users: Dict[int, set] = {}

        # Connection metadata for tracking
        self.connection_metadata: Dict[WebSocket, Dict[str, Any]] = {}

        # Session ID -> Active websocket (enforces single active channel per session)
        self.session_connections: Dict[str, WebSocket] = {}

        # Integration with existing services
        self._initialize_services()

        logger.info("FastAPI ConnectionManager initialized for real-time communication")

    def _initialize_services(self):
        """Initialize integration with existing VouchLink services"""
        try:
            # Use existing agent logger for WebSocket events
            from .agent_logger import agent_logger
            self.agent_logger = agent_logger

            # Use existing resilience patterns
            from .resilience_patterns import ResilienceManager, BulkheadConfig, BulkheadType
            self.resilience_manager = ResilienceManager()

            # Register bulkhead for WebSocket operations
            self.resilience_manager.create_bulkhead(BulkheadConfig(
                name="fastapi_websocket_manager",
                bulkhead_type=BulkheadType.THREAD_POOL,
                max_concurrent=50
            ))

        except Exception as e:
            logger.warning(f"Could not initialize all services: {e}")
            self.agent_logger = None
            self.resilience_manager = None

    async def connect(self, user_id: int, organization_id: int, websocket: WebSocket) -> str:
        """
        Accept a new WebSocket connection and track it by user and organization

        Args:
            user_id: User identifier
            organization_id: Organization/tenant identifier
            websocket: FastAPI WebSocket connection
        """
        try:
            await websocket.accept()

            connection_token = str(uuid.uuid4())

            # Track connection by user
            if user_id not in self.active_connections:
                self.active_connections[user_id] = []
            self.active_connections[user_id].append(websocket)

            # Track user in organization
            if organization_id not in self.organization_users:
                self.organization_users[organization_id] = set()
            self.organization_users[organization_id].add(user_id)

            # Store connection metadata
            self.connection_metadata[websocket] = {
                "user_id": user_id,
                "organization_id": organization_id,
                "connected_at": datetime.now(timezone.utc),
                "session_id": None,  # Will be set when chat session starts
                "connection_token": connection_token,
                "last_seen": datetime.now(timezone.utc)
            }

            # Log connection event
            if self.agent_logger:
                await self.agent_logger.log_event(
                    event_type="websocket_connection",
                    user_id=user_id,
                    organization_id=organization_id,
                    metadata={
                        "action": "connected",
                        "connection_count": len(self.active_connections.get(user_id, []))
                    }
                )

            logger.info(f"WebSocket connected: user_id={user_id}, org_id={organization_id}")

            return connection_token

        except Exception as e:
            logger.error(f"Failed to connect WebSocket for user {user_id}: {e}")
            raise

    async def disconnect(self, user_id: int, organization_id: int, websocket: WebSocket) -> None:
        """
        Clean up a WebSocket connection and remove tracking

        Args:
            user_id: User identifier
            organization_id: Organization identifier
            websocket: WebSocket connection to remove
        """
        try:
            # Remove from active connections
            if user_id in self.active_connections:
                if websocket in self.active_connections[user_id]:
                    self.active_connections[user_id].remove(websocket)

                # Clean up empty user connection list
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]

                    # Remove user from organization tracking if no connections
                    if organization_id in self.organization_users:
                        self.organization_users[organization_id].discard(user_id)
                        if not self.organization_users[organization_id]:
                            del self.organization_users[organization_id]

            # Remove connection metadata
            if websocket in self.connection_metadata:
                session_id = self.connection_metadata[websocket].get("session_id")
                if session_id and self.session_connections.get(session_id) is websocket:
                    self.session_connections.pop(session_id, None)
                del self.connection_metadata[websocket]

            # Log disconnection event
            if self.agent_logger:
                await self.agent_logger.log_event(
                    event_type="websocket_disconnection",
                    user_id=user_id,
                    organization_id=organization_id,
                    metadata={
                        "action": "disconnected",
                        "remaining_connections": len(self.active_connections.get(user_id, []))
                    }
                )

            logger.info(f"WebSocket disconnected: user_id={user_id}, org_id={organization_id}")

        except Exception as e:
            logger.error(f"Error during WebSocket disconnect for user {user_id}: {e}")

    async def send_personal_message(self, user_id: int, message: dict) -> bool:
        """
        Send a JSON message to all active connections for a specific user

        Args:
            user_id: Target user identifier
            message: JSON-serializable message dict

        Returns:
            True if message was sent to at least one connection, False otherwise
        """
        if user_id not in self.active_connections:
            logger.warning(f"No active connections for user {user_id}")
            return False

        sent_count = 0
        failed_connections = []

        for connection in self.active_connections[user_id].copy():
            try:
                await connection.send_json(message)
                if connection in self.connection_metadata:
                    self.connection_metadata[connection]["last_seen"] = datetime.now(timezone.utc)
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send message to user {user_id}: {e}")
                failed_connections.append(connection)

        # Clean up failed connections
        for failed_connection in failed_connections:
            try:
                metadata = self.connection_metadata.get(failed_connection, {})
                await self.disconnect(
                    user_id=metadata.get("user_id", user_id),
                    organization_id=metadata.get("organization_id", 0),
                    websocket=failed_connection
                )
            except Exception as e:
                logger.error(f"Error cleaning up failed connection: {e}")

        return sent_count > 0

    async def send_organization_message(self, organization_id: int, message: dict, exclude_user_id: Optional[int] = None) -> int:
        """
        Send a message to all users in an organization

        Args:
            organization_id: Organization identifier
            message: JSON-serializable message dict
            exclude_user_id: Optional user ID to exclude from broadcast

        Returns:
            Number of users who received the message
        """
        if organization_id not in self.organization_users:
            logger.warning(f"No active connections for organization {organization_id}")
            return 0

        sent_count = 0
        for user_id in self.organization_users[organization_id].copy():
            if exclude_user_id and user_id == exclude_user_id:
                continue

            if await self.send_personal_message(user_id, message):
                sent_count += 1

        return sent_count

    def get_connection_stats(self) -> Dict[str, Any]:
        """
        Get current connection statistics for monitoring

        Returns:
            Dict with connection counts and metadata
        """
        total_connections = sum(len(connections) for connections in self.active_connections.values())

        return {
                "total_connections": total_connections,
                "connected_users": len(self.active_connections),
                "organizations": len(self.organization_users),
                "users_by_org": {
                    org_id: len(users) for org_id, users in self.organization_users.items()
                }
            }

    def get_connection_token(self, websocket: WebSocket) -> Optional[str]:
        metadata = self.connection_metadata.get(websocket)
        return metadata.get("connection_token") if metadata else None

    async def update_session_id(self, websocket: WebSocket, session_id: str) -> bool:
        """
        Update the session ID for a WebSocket connection

        Args:
            websocket: WebSocket connection
            session_id: Chat session identifier
        """
        if websocket not in self.connection_metadata:
            return False

        current_metadata = self.connection_metadata[websocket]
        previous_session = current_metadata.get("session_id")

        if previous_session and previous_session != session_id:
            # Release previous session binding
            if self.session_connections.get(previous_session) is websocket:
                self.session_connections.pop(previous_session, None)

        # If another connection owns this session, notify and disconnect it
        existing_connection = self.session_connections.get(session_id)
        if existing_connection and existing_connection is not websocket:
            await self._notify_session_handoff(existing_connection)
            existing_metadata = self.connection_metadata.get(existing_connection)
            if existing_metadata:
                try:
                    await existing_connection.close(code=4001, reason="Session transferred to another connection")
                except Exception as close_exc:  # pragma: no cover - best effort
                    logger.debug(f"Failed to close transferred connection: {close_exc}")
                await self.disconnect(
                    user_id=existing_metadata.get("user_id"),
                    organization_id=existing_metadata.get("organization_id"),
                    websocket=existing_connection
                )

        # Assign session to this connection
        current_metadata["session_id"] = session_id
        current_metadata["last_seen"] = datetime.now(timezone.utc)
        self.session_connections[session_id] = websocket
        logger.debug(f"Assigned session {session_id} to WebSocket connection")
        return True

    async def _notify_session_handoff(self, websocket: WebSocket) -> None:
        """Notify a connection that its session has been transferred elsewhere."""
        try:
            message = {
                "type": "session_transferred",
                "code": "session_handoff",
                "message": "This chat session was opened in another window. I'll pause here.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await websocket.send_json(message)
        except Exception as exc:
            logger.debug(f"Unable to notify session handoff: {exc}")

# Global connection manager instance
connection_manager = ConnectionManager()