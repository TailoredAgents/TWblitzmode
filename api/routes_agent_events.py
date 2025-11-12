"""
Agent Events API Routes - Communication Hub Enhancement
September 2025 - Real-time agent event tracking with actionable suggestions
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Any
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field
import websockets

from api.database import AgentEventsDatabase
from .deps import get_current_user

# Import friendly names from agent logger
try:
    from services.agent_logger import FRIENDLY_NAMES
    friendly_names_available = True
except ImportError:
    FRIENDLY_NAMES = {}
    friendly_names_available = False

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-events", tags=["agent-events"])

class EventLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class AgentEventCreate(BaseModel):
    event_type: str = Field(..., description="Type of agent event")
    agent_name: str = Field(..., description="Name of the agent (executive_search, etc.)")
    agent_id: Optional[str] = Field(None, description="Unique identifier for the agent (optional)")
    level: EventLevel = Field(EventLevel.INFO, description="Event severity level")
    message: str = Field(..., description="Event message")
    suggestion: Optional[str] = Field(None, description="Actionable suggestion for users")
    tenant_id: Optional[str] = Field(None, description="Tenant identifier")
    user_id: Optional[str] = Field(None, description="User identifier")
    workflow_id: Optional[str] = Field(None, description="Workflow identifier")
    task_id: Optional[str] = Field(None, description="Task identifier")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    organization_id: Optional[int] = Field(None, description="Organization ID")

class AgentEvent(AgentEventCreate):
    id: int
    event_id: str
    session_id: Optional[str]
    created_at: str
    updated_at: str

class EventBroadcaster:
    """Manages WebSocket connections for real-time event broadcasting"""

    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.connection_info: Dict[str, Dict[str, Any]] = {}
        self.organization_subscriptions: Dict[int, Set[str]] = {}

    async def connect(self, websocket: WebSocket, connection_id: str, user_id: str, organization_id: int):
        """Register a new WebSocket connection"""
        await websocket.accept()

        self.connections[connection_id] = websocket
        self.connection_info[connection_id] = {
            "user_id": user_id,
            "organization_id": organization_id,
            "connected_at": datetime.now(timezone.utc)
        }

        # Add to organization subscriptions
        if organization_id not in self.organization_subscriptions:
            self.organization_subscriptions[organization_id] = set()
        self.organization_subscriptions[organization_id].add(connection_id)

        logger.info(f"WebSocket connected: {connection_id} (user: {user_id}, org: {organization_id})")

        # Send welcome message
        await self.send_to_connection(connection_id, {
            "type": "connection_established",
            "message": "Connected to agent events stream",
            "connection_id": connection_id
        })

    async def disconnect(self, connection_id: str):
        """Remove a WebSocket connection"""
        if connection_id in self.connections:
            # Remove from organization subscriptions
            if connection_id in self.connection_info:
                org_id = self.connection_info[connection_id]["organization_id"]
                if org_id in self.organization_subscriptions:
                    self.organization_subscriptions[org_id].discard(connection_id)
                    if not self.organization_subscriptions[org_id]:
                        del self.organization_subscriptions[org_id]

            # Clean up connection
            del self.connections[connection_id]
            if connection_id in self.connection_info:
                del self.connection_info[connection_id]

            logger.info(f"WebSocket disconnected: {connection_id}")

    async def send_to_connection(self, connection_id: str, message: Dict[str, Any]):
        """Send message to specific connection"""
        if connection_id not in self.connections:
            return

        websocket = self.connections[connection_id]
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except (WebSocketDisconnect, RuntimeError) as exc:
            logger.warning(
                "Dropping websocket %s due to transport error: %s",
                connection_id,
                exc,
            )
            await self.disconnect(connection_id)
        except Exception as e:
            logger.error(f"Failed to send message to {connection_id}: {e}")
            await self.disconnect(connection_id)

    async def broadcast_to_organization(self, organization_id: int, message: Dict[str, Any]):
        """Broadcast message to all connections in an organization"""
        if organization_id in self.organization_subscriptions:
            # Create tasks for concurrent sending
            tasks = []
            for connection_id in list(self.organization_subscriptions[organization_id]):
                task = self.send_to_connection(connection_id, message)
                tasks.append(task)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def broadcast_event(self, event_data: Dict[str, Any]):
        """Broadcast new agent event to relevant subscribers"""
        organization_id = event_data.get("organization_id")

        message = {
            "type": "agent_event",
            "data": event_data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        if organization_id:
            await self.broadcast_to_organization(organization_id, message)
        else:
            # If no organization specified, broadcast to all connections
            tasks = []
            for connection_id in list(self.connections.keys()):
                task = self.send_to_connection(connection_id, message)
                tasks.append(task)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

# Global event broadcaster
event_broadcaster = EventBroadcaster()


def _resolve_organization_id(current_user: Dict[str, Any]) -> int:
    organization_id = current_user.get("organization_id")
    if organization_id is None:
        tenant_value = current_user.get("tenant_id")
        if tenant_value is None:
            raise HTTPException(status_code=403, detail="Organization context is required")
        try:
            organization_id = int(str(tenant_value))
        except (TypeError, ValueError):
            raise HTTPException(status_code=403, detail="Invalid tenant context")
    return int(organization_id)


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        return value
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    return str(value)


def _deserialize_metadata(metadata: Any) -> Dict[str, Any]:
    if isinstance(metadata, dict):
        return metadata
    if not metadata:
        return {}
    try:
        return json.loads(metadata)
    except (ValueError, TypeError):
        return {}


def _serialize_event_record(record: Dict[str, Any]) -> Dict[str, Any]:
    metadata = _deserialize_metadata(record.get("metadata"))
    return {
        "id": record.get("id"),
        "event_id": record.get("event_id"),
        "session_id": record.get("session_id"),
        "event_type": record.get("event_type"),
        "agent_name": record.get("agent_name") or record.get("agent_id"),
        "agent_id": record.get("agent_id"),
        "level": record.get("level"),
        "message": record.get("message"),
        "suggestion": record.get("suggestion"),
        "tenant_id": record.get("tenant_id"),
        "user_id": record.get("user_id"),
        "workflow_id": record.get("workflow_id"),
        "task_id": record.get("task_id"),
        "metadata": metadata,
        "organization_id": record.get("organization_id"),
        "created_at": _to_iso(record.get("created_at")),
        "updated_at": _to_iso(record.get("updated_at")),
    }


async def _create_agent_event_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    db = AgentEventsDatabase()
    await asyncio.to_thread(db.create_agent_event, payload)
    stored = await asyncio.to_thread(
        db.get_agent_event_by_id,
        payload["event_id"],
        payload["organization_id"],
    )
    return stored or payload


async def _list_agent_events(organization_id: int, limit: int, offset: int, filters: Dict[str, Any]):
    db = AgentEventsDatabase()
    events = await asyncio.to_thread(
        db.get_agent_events,
        organization_id,
        limit,
        offset,
        filters,
    )
    total = await asyncio.to_thread(
        db.count_agent_events,
        organization_id,
        filters,
    )
    return events, total


async def _summarize_agent_events(organization_id: int) -> Dict[str, Any]:
    db = AgentEventsDatabase()
    return await asyncio.to_thread(db.get_events_summary, organization_id)

@router.post("/", status_code=201)
async def create_agent_event(
    event: AgentEventCreate,
    current_user: Dict = Depends(get_current_user)
):
    """
    Create a new agent event.

    Implements:
    - Tenant isolation
    - Event ID generation
    - XSS prevention (message sanitization)
    - WebSocket broadcasting (future enhancement)
    """
    tenant_id = current_user["tenant_id"]
    organization_id = _resolve_organization_id(current_user)
    organization_id = _resolve_organization_id(current_user)
    organization_id = _resolve_organization_id(current_user)

    logger.info(
        f"Creating agent event: {event.event_type}",
        extra={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "agent_name": event.agent_name,
            "workflow_id": event.workflow_id
        }
    )

    try:
        event_id = f"event_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        agent_id = event.agent_id or event.agent_name
        sanitized_message = (
            event.message
            .replace("<script>", "")
            .replace("</script>", "")
            .replace("<img", "")
            .replace("javascript:", "")
        )

        db_payload = {
            "event_id": event_id,
            "session_id": event.metadata.get("session_id") if event.metadata else None,
            "event_type": event.event_type,
            "agent_id": agent_id,
            "level": event.level.value,
            "message": sanitized_message,
            "suggestion": event.suggestion,
            "tenant_id": tenant_id,
            "user_id": str(user_id),
            "workflow_id": event.workflow_id,
            "task_id": event.task_id,
            "metadata": json.dumps(event.metadata or {}),
            "organization_id": organization_id,
        }

        stored = await _create_agent_event_record(db_payload)
        response_payload = _serialize_event_record(stored)

        await event_broadcaster.broadcast_event(response_payload)

        logger.info(
            "Agent event created successfully: %s",
            event_id,
            extra={"tenant_id": tenant_id, "event_id": event_id},
        )

        return response_payload

    except Exception as e:
        logger.error(f"Failed to create agent event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", status_code=200)
async def get_agent_events(
    current_user: Dict = Depends(get_current_user),
    agent_name: Optional[str] = Query(None, description="Filter by agent name"),
    workflow_id: Optional[str] = Query(None, description="Filter by workflow ID"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID (optional)"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of events to return"),
    offset: int = Query(0, ge=0, description="Number of events to skip")
):
    """
    Get agent events with optional filtering.

    Supports filtering by:
    - agent_name: Filter by agent name
    - workflow_id: Filter by workflow ID
    - event_type: Filter by event type
    - limit/offset: Pagination

    Implements tenant isolation and SQL injection prevention.
    """
    tenant_id = current_user["tenant_id"]
    user_id = current_user["id"]
    organization_id = _resolve_organization_id(current_user)

    logger.info(
        "Retrieving agent events",
        extra={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "filters": {
                "agent_name": agent_name,
                "workflow_id": workflow_id,
                "limit": limit,
                "offset": offset
            }
        }
    )

    try:
        filters = {
            "agent_id": agent_id,
            "event_type": event_type,
            "level": None,
        }
        events, total = await _list_agent_events(organization_id, limit, offset, filters)
        serialized = [_serialize_event_record(event) for event in events]

        logger.info(
            "Found %s agent events",
            len(events),
            extra={"tenant_id": tenant_id, "count": len(events)},
        )

        return {
            "events": serialized,
            "data": serialized,
            "total": total,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(events) < total,
            },
        }

    except Exception as e:
        logger.error(f"Failed to get agent events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats", status_code=200)
async def get_event_statistics(
    current_user: Dict = Depends(get_current_user)
):
    """
    Get agent event statistics for the current tenant.

    Returns:
    - total_events: Total count of events
    - events_by_agent: Breakdown by agent name
    - events_by_type: Breakdown by event type
    """
    tenant_id = current_user["tenant_id"]
    user_id = current_user["id"]

    logger.info(
        "Retrieving agent event statistics",
        extra={"tenant_id": tenant_id, "user_id": user_id}
    )

    try:
        summary = await _summarize_agent_events(organization_id)
        stats = {
            "total_events": sum(summary["level_counts"].values()),
            "events_by_agent": {item["agent_id"]: item["event_count"] for item in summary["active_agents"]},
            "events_by_type": {item["event_type"]: item["count"] for item in summary["top_event_types"]},
            "level_counts": summary["level_counts"],
        }

        logger.info(
            f"Agent event statistics retrieved: {stats['total_events']} total",
            extra={"tenant_id": tenant_id, "stats": stats}
        )

        return stats

    except Exception as e:
        logger.error(f"Error retrieving agent event statistics: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve statistics. Please try again later."
        )


@router.get("/{event_id}", status_code=200)
async def get_agent_event(
    event_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """
    Get a specific agent event by ID.

    Implements tenant isolation.
    """
    tenant_id = current_user["tenant_id"]
    user_id = current_user["id"]

    logger.info(
        f"Retrieving agent event: {event_id}",
        extra={"tenant_id": tenant_id, "user_id": user_id, "event_id": event_id}
    )

    try:
        db = AgentEventsDatabase()
        record = await asyncio.to_thread(db.get_agent_event_by_id, event_id, organization_id)
        if not record:
            logger.warning(
                "Agent event not found: %s",
                event_id,
                extra={"tenant_id": tenant_id, "event_id": event_id},
            )
            raise HTTPException(status_code=404, detail=f"Agent event {event_id} not found")

        return _serialize_event_record(record)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving agent event: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve agent event. Please try again later."
        )

async def stream_agent_events_websocket(websocket: WebSocket, user_id: str, organization_id: int):
    """
    Shared handler for agent event websocket connections.

    This helper allows multiple routes (including compatibility shims) to
    reuse the same connection lifecycle without duplicating logic.
    """
    connection_id = str(uuid.uuid4())

    try:
        await event_broadcaster.connect(websocket, connection_id, user_id, organization_id)

        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "ping":
                    await event_broadcaster.send_to_connection(connection_id, {
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                elif message.get("type") == "subscribe_agent":
                    # Placeholder for future agent-specific subscriptions
                    pass

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await event_broadcaster.send_to_connection(connection_id, {
                    "type": "error",
                    "message": "Invalid JSON message"
                })
            except Exception as e:
                logger.error(f"WebSocket message handling error: {e}")
                await event_broadcaster.send_to_connection(connection_id, {
                    "type": "error",
                    "message": "Message processing error"
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        await event_broadcaster.disconnect(connection_id)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time agent event streaming"""
    query_params = dict(websocket.query_params)
    user_id = query_params.get("user_id", "anonymous")

    try:
        organization_id = int(query_params.get("organization_id", "1"))
    except (TypeError, ValueError):
        organization_id = 1

    await stream_agent_events_websocket(websocket, user_id, organization_id)

@router.get("/stats/summary", response_model=Dict[str, Any])
async def get_agent_events_summary(
    current_user: Dict = Depends(get_current_user)
):
    """Get summary statistics for agent events"""
    try:
        organization_id = _resolve_organization_id(current_user)
        summary = await _summarize_agent_events(organization_id)

        return {
            "success": True,
            "data": {
                "level_counts": summary["level_counts"],
                "top_event_types": summary["top_event_types"],
                "active_agents": summary["active_agents"],
                "connected_clients": len(event_broadcaster.connections),
                "organizations_connected": len(event_broadcaster.organization_subscriptions),
            },
        }

    except Exception as e:
        logger.error(f"Failed to get agent events summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/friendly-names")
async def get_agent_friendly_names(
    current_user: Dict = Depends(get_current_user)
):
    """Get mapping of agent IDs to friendly display names"""
    try:
        return {
            "success": True,
            "data": {
                "friendly_names": FRIENDLY_NAMES,
                "available": friendly_names_available
            }
        }
    except Exception as e:
        logger.error(f"Failed to get friendly names: {e}")
        raise HTTPException(status_code=500, detail=str(e))
