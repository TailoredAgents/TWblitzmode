"""
Agent Logging API Routes - September 2025 AI Integration
Backend endpoints for centralized agent logging system
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import logging
import asyncio

from api.auth import get_current_user
from services.agent_logger import agent_logger, AgentEventType, LogLevel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs")


def _get_user_value(user: Any, *keys: str) -> Optional[Any]:
    if not user:
        return None

    if isinstance(user, dict):
        for key in keys:
            value = user.get(key)
            if value is not None:
                return value
        organization = user.get("organization")
        if isinstance(organization, dict):
            for key in keys:
                value = organization.get(key)
                if value is not None:
                    return value
        return None

    for key in keys:
        value = getattr(user, key, None)
        if value is not None:
            return value

    organization = getattr(user, "organization", None)
    if isinstance(organization, dict):
        for key in keys:
            value = organization.get(key)
            if value is not None:
                return value
    elif organization is not None:
        for key in keys:
            value = getattr(organization, key, None)
            if value is not None:
                return value

    return None

# Request/Response Models
class FrontendLogEvent(BaseModel):
    """Frontend log event model"""
    timestamp: str
    eventId: str
    sessionId: str
    eventType: str
    agentId: Optional[str] = None
    level: str
    message: str
    tenantId: Optional[str] = None
    userId: Optional[str] = None
    workflowId: Optional[str] = None
    taskId: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}
    url: Optional[str] = None
    userAgent: Optional[str] = None

class FrontendLogBatch(BaseModel):
    """Batch of frontend log events"""
    session_id: str
    events: List[FrontendLogEvent]

class LogQueryRequest(BaseModel):
    """Log query request model"""
    agent_id: Optional[str] = None
    event_type: Optional[str] = None
    level: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = Field(default=100, le=1000)
    tenant_id: Optional[str] = None

class AgentSummaryResponse(BaseModel):
    """Agent activity summary response"""
    agent_id: str
    start_time: datetime
    last_activity: datetime
    events_count: int
    status: str
    current_task: Optional[str] = None
    error_count: int

@router.post("/agent-events")
async def receive_frontend_logs(
    batch: FrontendLogBatch,
    request: Request,
    current_user = Depends(get_current_user)
):
    """Receive and process frontend agent log events"""
    try:
        client_ip = request.client.host
        processed_count = 0

        for event in batch.events:
            try:
                # Map frontend event type to backend enum
                try:
                    event_type = AgentEventType(event.eventType)
                except ValueError:
                    logger.warning(f"Unknown event type: {event.eventType}")
                    continue

                # Map frontend log level to backend enum
                try:
                    log_level = LogLevel(event.level)
                except ValueError:
                    log_level = LogLevel.INFO

                # Enhance metadata with request context
                enhanced_metadata = {
                    **(event.metadata or {}),
                    "client_ip": client_ip,
                    "session_id": event.sessionId,
                    "event_id": event.eventId,
                    "url": event.url,
                    "user_agent": event.userAgent,
                    "source": "frontend"
                }

                # Use current user's tenant_id if not provided in event
                tenant_value = event.tenantId or _get_user_value(current_user, "tenant_id", "organization_id")
                user_value = event.userId or _get_user_value(current_user, "user_id", "id")

                # Log the event using the centralized agent logger
                await agent_logger.log_event(
                    event_type=event_type,
                    agent_id=event.agentId,
                    message=event.message,
                    level=log_level,
                    metadata=enhanced_metadata,
                    tenant_id=str(tenant_value) if tenant_value else None,
                    user_id=str(user_value) if user_value else None,
                    workflow_id=event.workflowId,
                    task_id=event.taskId
                )

                processed_count += 1

            except Exception as e:
                logger.error(f"Failed to process log event {event.eventId}: {e}")
                continue

        logger.info(f"Processed {processed_count}/{len(batch.events)} frontend log events from session {batch.session_id}")

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "processed": processed_count,
                "total": len(batch.events),
                "session_id": batch.session_id
            }
        )

    except Exception as e:
        logger.error(f"Failed to process frontend log batch: {e}")
        raise HTTPException(status_code=500, detail="Failed to process log events")

@router.post("/query-events")
async def query_agent_events(
    query: LogQueryRequest,
    current_user = Depends(get_current_user)
):
    """Query agent log events with filters"""
    try:
        # Convert string event type to enum if provided
        event_type_enum = None
        if query.event_type:
            try:
                event_type_enum = AgentEventType(query.event_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid event type: {query.event_type}")

        # Use current user's tenant_id if not provided and user is not admin
        tenant_filter = query.tenant_id
        user_role = _get_user_value(current_user, "role")
        if not tenant_filter and user_role != 'admin':
            tenant_candidate = _get_user_value(current_user, "tenant_id", "organization_id")
            tenant_filter = str(tenant_candidate) if tenant_candidate is not None else None

        # Get events from agent logger
        events = await agent_logger.get_recent_events(
            agent_id=query.agent_id,
            limit=query.limit,
            event_type=event_type_enum
        )

        # Apply additional filters
        filtered_events = []
        for event in events:
            # Tenant filter
            if tenant_filter and event.get("tenant_id") != tenant_filter:
                continue

            # Level filter
            if query.level and event.get("level") != query.level:
                continue

            # Time range filter
            if query.start_time or query.end_time:
                try:
                    event_time = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
                    if query.start_time and event_time < query.start_time:
                        continue
                    if query.end_time and event_time > query.end_time:
                        continue
                except (ValueError, KeyError):
                    continue

            filtered_events.append(event)

        return JSONResponse(
            status_code=200,
            content={
                "events": filtered_events[:query.limit],
                "total": len(filtered_events),
                "filters": {
                    "agent_id": query.agent_id,
                    "event_type": query.event_type,
                    "level": query.level,
                    "tenant_id": tenant_filter
                }
            }
        )

    except Exception as e:
        logger.error(f"Failed to query agent events: {e}")
        raise HTTPException(status_code=500, detail="Failed to query events")

@router.get("/agent-summary/{agent_id}", response_model=AgentSummaryResponse)
async def get_agent_summary(
    agent_id: str,
    current_user = Depends(get_current_user)
):
    """Get activity summary for a specific agent"""
    try:
        summary = agent_logger.get_agent_summary(agent_id)

        if not summary:
            raise HTTPException(status_code=404, detail="Agent not found")

        return AgentSummaryResponse(
            agent_id=summary["agent_id"],
            start_time=summary["start_time"],
            last_activity=summary["last_activity"],
            events_count=summary["events_count"],
            status=summary["status"],
            current_task=summary.get("current_task"),
            error_count=summary["error_count"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get agent summary for {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get agent summary")

@router.get("/agents-summary", response_model=List[AgentSummaryResponse])
async def get_all_agents_summary(
    current_user = Depends(get_current_user)
):
    """Get activity summary for all agents"""
    try:
        summaries = agent_logger.get_all_agents_summary()

        return [
            AgentSummaryResponse(
                agent_id=summary["agent_id"],
                start_time=summary["start_time"],
                last_activity=summary["last_activity"],
                events_count=summary["events_count"],
                status=summary["status"],
                current_task=summary.get("current_task"),
                error_count=summary["error_count"]
            )
            for summary in summaries
        ]

    except Exception as e:
        logger.error(f"Failed to get agents summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to get agents summary")

@router.post("/agent/{agent_id}/start")
async def log_agent_start(
    agent_id: str,
    agent_type: str,
    config: Dict[str, Any] = {},
    current_user = Depends(get_current_user)
):
    """Log agent startup event"""
    try:
        tenant_candidate = _get_user_value(current_user, "tenant_id", "organization_id")
        tenant_id = str(tenant_candidate) if tenant_candidate is not None else None

        await agent_logger.log_agent_start(
            agent_id=agent_id,
            agent_type=agent_type,
            config=config,
            tenant_id=tenant_id
        )

        return JSONResponse(
            status_code=200,
            content={"success": True, "message": f"Agent {agent_id} start logged"}
        )

    except Exception as e:
        logger.error(f"Failed to log agent start for {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to log agent start")

@router.post("/agent/{agent_id}/stop")
async def log_agent_stop(
    agent_id: str,
    reason: str = "normal",
    current_user = Depends(get_current_user)
):
    """Log agent stop event"""
    try:
        tenant_candidate = _get_user_value(current_user, "tenant_id", "organization_id")
        tenant_id = str(tenant_candidate) if tenant_candidate is not None else None

        await agent_logger.log_agent_stop(
            agent_id=agent_id,
            reason=reason,
            tenant_id=tenant_id
        )

        return JSONResponse(
            status_code=200,
            content={"success": True, "message": f"Agent {agent_id} stop logged"}
        )

    except Exception as e:
        logger.error(f"Failed to log agent stop for {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to log agent stop")

@router.post("/workflow/{workflow_id}/start")
async def log_workflow_start(
    workflow_id: str,
    agent_id: str,
    workflow_type: str,
    current_user = Depends(get_current_user)
):
    """Log workflow start event"""
    try:
        tenant_candidate = _get_user_value(current_user, "tenant_id", "organization_id")
        user_candidate = _get_user_value(current_user, "user_id", "id")
        tenant_id = str(tenant_candidate) if tenant_candidate is not None else None
        user_id = str(user_candidate) if user_candidate is not None else None

        await agent_logger.log_workflow_start(
            agent_id=agent_id,
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            tenant_id=tenant_id,
            user_id=user_id
        )

        return JSONResponse(
            status_code=200,
            content={"success": True, "message": f"Workflow {workflow_id} start logged"}
        )

    except Exception as e:
        logger.error(f"Failed to log workflow start for {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to log workflow start")

@router.post("/approval/{approval_id}/request")
async def log_approval_request(
    approval_id: str,
    agent_id: str,
    request_type: str,
    details: Dict[str, Any],
    current_user = Depends(get_current_user)
):
    """Log approval request event"""
    try:
        tenant_candidate = _get_user_value(current_user, "tenant_id", "organization_id")
        tenant_id = str(tenant_candidate) if tenant_candidate is not None else None

        await agent_logger.log_approval_request(
            agent_id=agent_id,
            approval_id=approval_id,
            request_type=request_type,
            details=details,
            tenant_id=tenant_id
        )

        return JSONResponse(
            status_code=200,
            content={"success": True, "message": f"Approval request {approval_id} logged"}
        )

    except Exception as e:
        logger.error(f"Failed to log approval request for {approval_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to log approval request")

@router.post("/approval/{approval_id}/decision")
async def log_approval_decision(
    approval_id: str,
    agent_id: str,
    decision: str,
    feedback: Optional[str] = None,
    current_user = Depends(get_current_user)
):
    """Log approval decision event"""
    try:
        tenant_candidate = _get_user_value(current_user, "tenant_id", "organization_id")
        user_candidate = _get_user_value(current_user, "user_id", "id")
        tenant_id = str(tenant_candidate) if tenant_candidate is not None else None
        user_id = str(user_candidate) if user_candidate is not None else None

        await agent_logger.log_approval_decision(
            agent_id=agent_id,
            approval_id=approval_id,
            decision=decision,
            feedback=feedback,
            tenant_id=tenant_id,
            user_id=user_id
        )

        return JSONResponse(
            status_code=200,
            content={"success": True, "message": f"Approval decision {approval_id} logged"}
        )

    except Exception as e:
        logger.error(f"Failed to log approval decision for {approval_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to log approval decision")

@router.get("/health")
async def logging_health():
    """Health check for logging service"""
    try:
        # Test agent logger functionality
        test_summary = agent_logger.get_all_agents_summary()

        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "service": "agent_logging",
                "active_agents": len(test_summary),
                "timestamp": datetime.now().isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Logging health check failed: {e}")
        raise HTTPException(status_code=500, detail="Logging service unhealthy")
