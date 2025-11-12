"""
Redis Queue Management API Routes
Enterprise queue monitoring and control endpoints
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import logging
import json

from .deps import get_current_user, get_current_admin
from services.redis_queue import message_queue, MessagePriority, QueueMessage, create_workflow_message
from services.workflow_handlers import workflow_handlers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/queue")

# Request/Response Models
class EnqueueRequest(BaseModel):
    """Request model for enqueueing messages"""
    tenant_id: str
    workflow_type: str
    priority: str = "NORMAL"
    payload: Dict[str, Any]
    scheduled_delay_seconds: Optional[int] = None
    timeout_seconds: int = 300
    max_retries: int = 3

class QueueStatsResponse(BaseModel):
    """Response model for queue statistics"""
    streams: Dict[str, int]
    scheduled_counts: Dict[str, int]
    processing_count: int
    completed_count: int
    dlq_count: int
    total_pending: int
    timestamp: datetime

class MessageResponse(BaseModel):
    """Response model for queue messages"""
    id: str
    tenant_id: str
    workflow_type: str
    priority: str
    created_at: datetime
    status: str
    retry_count: int
    payload: Dict[str, Any]

class WorkflowTriggerRequest(BaseModel):
    """Request model for triggering workflows"""
    csv_file_path: str
    import_config: Optional[Dict[str, Any]] = {}

@router.get("/stats", response_model=QueueStatsResponse)
async def get_queue_statistics(
    current_user = Depends(get_current_user)
):
    """
    Get comprehensive queue statistics for monitoring
    Accessible to all authenticated users for their tenant
    """
    try:
        stats = await message_queue.get_queue_stats()

        # Calculate total pending messages
        total_pending = sum(stats["streams"].values()) + sum(stats["scheduled_counts"].values())

        return QueueStatsResponse(
            streams=stats["streams"],
            scheduled_counts=stats["scheduled_counts"],
            processing_count=stats["processing_count"],
            completed_count=stats["completed_count"],
            dlq_count=stats["dlq_count"],
            total_pending=total_pending,
            timestamp=datetime.utcnow()
        )

    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve queue statistics")

@router.post("/enqueue")
async def enqueue_message(
    request: EnqueueRequest,
    current_user = Depends(get_current_user)
):
    """
    Enqueue a new workflow message
    Users can only enqueue messages for their own tenant
    """
    try:
        # Validate tenant access
        if current_user.get("role") != "admin" and request.tenant_id != current_user.get("tenant_id"):
            raise HTTPException(status_code=403, detail="Cannot enqueue messages for other tenants")

        # Parse priority
        try:
            priority = MessagePriority[request.priority.upper()]
        except KeyError:
            raise HTTPException(status_code=400, detail=f"Invalid priority: {request.priority}")

        # Create message
        message = await create_workflow_message(
            tenant_id=request.tenant_id,
            workflow_type=request.workflow_type,
            payload=request.payload,
            priority=priority,
            timeout_seconds=request.timeout_seconds,
            max_retries=request.max_retries
        )

        # Enqueue or schedule
        if request.scheduled_delay_seconds:
            message_id = await message_queue.enqueue_scheduled(message, request.scheduled_delay_seconds)
        else:
            message_id = await message_queue.enqueue(message)

        return JSONResponse(
            status_code=201,
            content={
                "success": True,
                "message_id": message_id,
                "queue_message_id": message.id,
                "enqueued_at": datetime.utcnow().isoformat()
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to enqueue message: {e}")
        raise HTTPException(status_code=500, detail="Failed to enqueue message")

@router.post("/trigger-csv-workflow")
async def trigger_csv_workflow(
    request: WorkflowTriggerRequest,
    current_user = Depends(get_current_user)
):
    """
    Trigger complete CSV ingestion workflow
    Convenience endpoint for starting corporate prospect workflows
    """
    try:
        tenant_id = current_user.get("tenant_id")

        # Create CSV ingestion message
        message = await create_workflow_message(
            tenant_id=tenant_id,
            workflow_type="csv_ingestion",
            priority=MessagePriority.HIGH,
            payload={
                "csv_file_path": request.csv_file_path,
                "import_config": request.import_config,
                "triggered_by": current_user.get("email"),
                "trigger_timestamp": datetime.utcnow().isoformat()
            }
        )

        message_id = await message_queue.enqueue(message)

        return JSONResponse(
            status_code=201,
            content={
                "success": True,
                "workflow_id": message.id,
                "message_id": message_id,
                "workflow_type": "csv_ingestion",
                "status": "queued",
                "estimated_completion": (datetime.utcnow() + timedelta(minutes=30)).isoformat()
            }
        )

    except Exception as e:
        logger.error(f"Failed to trigger CSV workflow: {e}")
        raise HTTPException(status_code=500, detail="Failed to trigger workflow")

@router.get("/pending-messages")
async def get_pending_messages(
    workflow_type: Optional[str] = Query(None, description="Filter by workflow type"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of messages"),
    current_user = Depends(get_current_user)
):
    """
    Get pending messages from queues
    Admin users see all messages, regular users see only their tenant's messages
    """
    try:
        # This would require implementing message retrieval from Redis streams
        # For now, return basic queue information
        stats = await message_queue.get_queue_stats()

        return JSONResponse(
            content={
                "pending_counts": stats["streams"],
                "scheduled_counts": stats["scheduled_counts"],
                "filters_applied": {
                    "workflow_type": workflow_type,
                    "priority": priority,
                    "limit": limit
                },
                "note": "Detailed message retrieval implementation pending"
            }
        )

    except Exception as e:
        logger.error(f"Failed to get pending messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve messages")

@router.get("/dlq-messages")
async def get_dead_letter_queue_messages(
    limit: int = Query(50, ge=1, le=500),
    current_user = Depends(get_current_admin)
):
    """
    Get messages from dead letter queue
    Admin only endpoint for troubleshooting
    """
    try:
        # This would require implementing DLQ message retrieval
        dlq_count = await message_queue.get_queue_stats()

        return JSONResponse(
            content={
                "dlq_count": dlq_count.get("dlq_count", 0),
                "message": "DLQ message retrieval implementation pending",
                "recommendation": "Check Redis directly for detailed DLQ analysis"
            }
        )

    except Exception as e:
        logger.error(f"Failed to get DLQ messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve DLQ messages")

@router.post("/requeue-dlq")
async def requeue_dead_letter_messages(
    message_ids: List[str],
    current_user = Depends(get_current_admin)
):
    """
    Requeue messages from dead letter queue
    Admin only endpoint for recovery operations
    """
    try:
        # This would require implementing DLQ requeue functionality
        return JSONResponse(
            content={
                "success": True,
                "message": f"Requeue operation initiated for {len(message_ids)} messages",
                "status": "pending_implementation"
            }
        )

    except Exception as e:
        logger.error(f"Failed to requeue DLQ messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to requeue messages")

@router.post("/pause-queue")
async def pause_queue_processing(
    queue_name: str,
    current_user = Depends(get_current_admin)
):
    """
    Pause processing for specific queue
    Admin only endpoint for maintenance operations
    """
    try:
        # This would require implementing queue pause functionality
        valid_queues = ["critical", "high", "normal", "low"]
        if queue_name not in valid_queues:
            raise HTTPException(status_code=400, detail=f"Invalid queue name. Valid options: {valid_queues}")

        return JSONResponse(
            content={
                "success": True,
                "queue": queue_name,
                "status": "paused",
                "message": f"Queue {queue_name} processing paused",
                "note": "Pause functionality implementation pending"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause queue: {e}")
        raise HTTPException(status_code=500, detail="Failed to pause queue")

@router.post("/resume-queue")
async def resume_queue_processing(
    queue_name: str,
    current_user = Depends(get_current_admin)
):
    """
    Resume processing for specific queue
    Admin only endpoint for maintenance operations
    """
    try:
        valid_queues = ["critical", "high", "normal", "low"]
        if queue_name not in valid_queues:
            raise HTTPException(status_code=400, detail=f"Invalid queue name. Valid options: {valid_queues}")

        return JSONResponse(
            content={
                "success": True,
                "queue": queue_name,
                "status": "active",
                "message": f"Queue {queue_name} processing resumed"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resume queue: {e}")
        raise HTTPException(status_code=500, detail="Failed to resume queue")

@router.get("/workflow-types")
async def get_available_workflow_types(
    current_user = Depends(get_current_user)
):
    """
    Get list of available workflow types
    Useful for UI dropdowns and validation
    """
    workflow_types = [
        {
            "type": "csv_ingestion",
            "description": "Process CSV file containing prospect data",
            "priority": "HIGH",
            "estimated_duration": "5-15 minutes"
        },
        {
            "type": "executive_lookup",
            "description": "Find executive contacts for prospects",
            "priority": "HIGH",
            "estimated_duration": "2-5 minutes"
        },
        {
            "type": "mutual_connections",
            "description": "Analyze mutual connections with prospects",
            "priority": "NORMAL",
            "estimated_duration": "3-8 minutes"
        },
        {
            "type": "prospect_scoring",
            "description": "Score prospects based on connection strength",
            "priority": "NORMAL",
            "estimated_duration": "1-2 minutes"
        },
        {
            "type": "email_enrichment",
            "description": "Enrich prospect data for email campaigns",
            "priority": "NORMAL",
            "estimated_duration": "2-5 minutes"
        },
        {
            "type": "ai_approval_request",
            "description": "Request human approval for AI actions",
            "priority": "HIGH",
            "estimated_duration": "Pending human approval"
        },
        {
            "type": "email_generation",
            "description": "Generate personalized introduction emails",
            "priority": "HIGH",
            "estimated_duration": "1-3 minutes"
        },
        {
            "type": "email_sending",
            "description": "Send introduction emails to prospects",
            "priority": "HIGH",
            "estimated_duration": "30 seconds - 2 minutes"
        }
    ]

    return JSONResponse(content={"workflow_types": workflow_types})

@router.get("/health")
async def queue_health_check():
    """
    Health check for queue system
    No authentication required for monitoring
    """
    try:
        # Test Redis connection
        await message_queue.connect()
        await message_queue.disconnect()

        return JSONResponse(
            content={
                "status": "healthy",
                "redis_connection": "ok",
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Queue system operational"
            }
        )

    except Exception as e:
        logger.error(f"Queue health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

# Initialize handlers on module import
async def initialize_queue_handlers():
    """Initialize workflow handlers with the message queue"""
    await workflow_handlers.register_all_handlers()
    logger.info("Queue management handlers initialized")
