"""
API Routes for AI Workflow Approval System

Handles approval requests, workflow status, and WebSocket connections
for the VouchLink AI corporate platform's human-in-the-loop functionality.
"""

import asyncio
import json
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
import asyncpg

from core.settings import settings
from .deps import get_current_user, get_connection
from .websocket_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["approvals"])
security = HTTPBearer()
_agent_lock = asyncio.Lock()
_cached_org_agent: Optional[Any] = None


def _resolve_authorized_tenant(requested_tenant_id: Optional[int], current_user: Dict[str, Any]) -> int:
    """
    Validate tenant scope against the authenticated user to prevent cross-tenant access.
    """
    organization_id = current_user.get("organization_id")
    if organization_id is None:
        tenant_token = current_user.get("tenant_id")
        try:
            organization_id = int(tenant_token)
        except (TypeError, ValueError):
            logger.warning(
                "User %s lacks valid tenant context (tenant=%s)",
                current_user.get("id"),
                tenant_token,
            )
            raise HTTPException(status_code=403, detail="Tenant context is required")

    organization_id = int(organization_id)

    if requested_tenant_id is not None and requested_tenant_id != organization_id:
        logger.warning(
            "Tenant mismatch: user %s attempted scope %s but is limited to %s",
            current_user.get("id"),
            requested_tenant_id,
            organization_id,
        )
        raise HTTPException(status_code=403, detail="Unauthorized tenant scope")

    return organization_id


async def _get_organization_agent() -> Optional[Any]:
    """
    Lazily instantiate and cache the VouchLinkAIOrganizationAgent when configuration allows.
    """
    global _cached_org_agent

    async with _agent_lock:
        if _cached_org_agent is not None:
            return _cached_org_agent

        api_key = settings.OPENAI_API_KEY
        database_url = settings.DATABASE_URL
        if not api_key or not database_url:
            logger.info("Organization agent skipped: missing OPENAI_API_KEY or DATABASE_URL")
            return None

        try:
            from services.vouchlink_ai_organization_agent import VouchLinkAIOrganizationAgent
        except ImportError as exc:
            logger.warning("Organization agent unavailable: %s", exc)
            return None

        try:
            _cached_org_agent = VouchLinkAIOrganizationAgent(
                openai_api_key=api_key,
                database_url=database_url,
            )
        except Exception as exc:
            logger.error("Failed to initialize organization agent: %s", exc)
            _cached_org_agent = None
            return None

        return _cached_org_agent

# Pydantic models for request/response
class ApprovalResponse(BaseModel):
    status: str
    comments: str = ""
    approver_id: str

    @field_validator('status')
    def validate_status(cls, v: str) -> str:
        if v not in ['approved', 'rejected', 'escalated']:
            raise ValueError('Status must be approved, rejected, or escalated')
        return v

class ApprovalRequest(BaseModel):
    approval_id: str
    workflow_id: str
    action: str
    description: str
    risk_score: float
    context: Dict
    priority: str
    status: str
    requested_at: datetime
    timeout_at: datetime

class WorkflowStatus(BaseModel):
    workflow_id: str
    current_action: str
    organization_id: str
    initiated_by: str
    total_prospects: int
    pending_approvals: int
    created_at: datetime
    updated_at: datetime

# WebSocket endpoint for real-time approval updates
@router.websocket("/ws/approvals/{tenant_id}")
async def websocket_approvals(websocket: WebSocket, tenant_id: str):
    """WebSocket endpoint for real-time approval queue updates"""
    await websocket.accept()

    try:
        path = f"/ws/approvals/{tenant_id}"
        await ws_manager.handle_connection(websocket, path)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for tenant {tenant_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"WebSocket error for tenant {tenant_id}: {e}")
        await websocket.close(1011, "Internal server error")

@router.websocket("/ws/approvals/{tenant_id}/{user_id}")
async def websocket_approvals_user(websocket: WebSocket, tenant_id: str, user_id: str):
    """WebSocket endpoint for real-time approval updates for specific user"""
    await websocket.accept()

    try:
        path = f"/ws/approvals/{tenant_id}/{user_id}"
        await ws_manager.handle_connection(websocket, path)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for tenant {tenant_id}, user {user_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"WebSocket error for tenant {tenant_id}, user {user_id}: {e}")
        await websocket.close(1011, "Internal server error")

# REST API endpoints
@router.get("/approvals")
async def get_pending_approvals(
    tenant_id: Optional[int] = Query(None, description="Tenant ID"),
    status: Optional[str] = Query("pending", description="Filter by approval status"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of approvals to return"),
    current_user: Dict = Depends(get_current_user),
):
    """Get approval requests for a tenant"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)
        async with get_connection() as conn:
            # Build query based on filters
            where_conditions = ["tenant_id = $1"]
            params: List[Any] = [tenant_scope]
            param_count = 1

            if status and status != "all":
                param_count += 1
                where_conditions.append(f"status = ${param_count}")
                params.append(status)

            where_clause = " AND ".join(where_conditions)
            filter_params = list(params)

            count_query = f"SELECT COUNT(*) FROM approval_requests WHERE {where_clause}"
            total_records = await conn.fetchval(count_query, *filter_params) or 0

            offset = (page - 1) * limit

            query = f"""
                SELECT
                    approval_id, workflow_id, action, description, risk_score,
                    context, priority, status, requested_at, timeout_at,
                    approver_id, approval_comments, rejection_reason,
                    tenant_id
                FROM approval_requests
                WHERE {where_clause}
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    requested_at ASC
                LIMIT ${param_count + 1}
                OFFSET ${param_count + 2}
            """
            params.extend([limit, offset])

            rows = await conn.fetch(query, *params)

            approvals = []
            for row in rows:
                approval = {
                    "approval_id": row["approval_id"],
                    "workflow_id": row["workflow_id"],
                    "action": row["action"],
                    "description": row["description"],
                    "risk_score": float(row["risk_score"]),
                    "context": row["context"],
                    "priority": row["priority"],
                    "status": row["status"],
                    "requested_at": row["requested_at"].isoformat(),
                    "timeout_at": row["timeout_at"].isoformat(),
                    "approver_id": row["approver_id"],
                    "approval_comments": row["approval_comments"],
                    "rejection_reason": row["rejection_reason"],
                    "tenant_id": row["tenant_id"],
                }
                approvals.append(approval)

            total_pages = math.ceil(total_records / limit) if limit else 1

            return {
                "data": approvals,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total_records,
                    "pages": max(total_pages, 1),
                },
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching approvals: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch approvals")

@router.post("/approvals/{approval_id}/approve", status_code=200)
async def approve_workflow_item(
    approval_id: str,
    request_data: Dict[str, Any],
    current_user: Dict = Depends(get_current_user)
):
    """
    Approve a workflow item.

    Specific endpoint for approval action - delegates to generic respond endpoint.
    """
    feedback = request_data.get("feedback", "")

    # Delegate to respond_to_approval with approved status
    response_obj = ApprovalResponse(
        status="approved",
        comments=feedback,
        approver_id=str(current_user["id"])
    )

    return await respond_to_approval(approval_id, response_obj, current_user)


@router.post("/approvals/{approval_id}/reject", status_code=200)
async def reject_workflow_item(
    approval_id: str,
    request_data: Dict[str, Any],
    current_user: Dict = Depends(get_current_user)
):
    """
    Reject a workflow item.

    Specific endpoint for rejection action - delegates to generic respond endpoint.
    """
    feedback = request_data.get("feedback", "")

    # Delegate to respond_to_approval with rejected status
    response_obj = ApprovalResponse(
        status="rejected",
        comments=feedback,
        approver_id=str(current_user["id"])
    )

    return await respond_to_approval(approval_id, response_obj, current_user)


@router.post("/approvals/{approval_id}/respond")
async def respond_to_approval(
    approval_id: str,
    response: ApprovalResponse,
    current_user: Dict = Depends(get_current_user)
):
    """Respond to an approval request"""

    try:
        tenant_scope = _resolve_authorized_tenant(None, current_user)
        approver_id = str(current_user["id"])

        async with get_connection() as conn:
            # Update approval request
            update_query = """
                UPDATE approval_requests SET
                    status = $2,
                    approver_id = $3,
                    responded_at = $4,
                    approval_comments = $5,
                    rejection_reason = CASE WHEN $2 = 'rejected' THEN $5 ELSE NULL END
                WHERE approval_id = $1
                RETURNING workflow_id, tenant_id, action, description
            """

            row = await conn.fetchrow(
                update_query,
                approval_id,
                response.status,
                approver_id,
                datetime.utcnow(),
                response.comments
            )

            if not row:
                raise HTTPException(status_code=404, detail="Approval request not found")

            workflow_id = row["workflow_id"]
            row_tenant = str(row["tenant_id"])
            expected_tenant = str(tenant_scope)

            if row_tenant != expected_tenant:
                logger.warning(
                    "User %s attempted to respond to approval %s outside tenant scope %s (row tenant %s)",
                    current_user.get("id"),
                    approval_id,
                    expected_tenant,
                    row_tenant,
                )
                raise HTTPException(status_code=403, detail="Unauthorized tenant scope for approval response")

            # Log audit event
            await conn.execute("""
                INSERT INTO audit_events (tenant_id, event_type, details, created_at)
                VALUES ($1, $2, $3, $4)
            """, tenant_scope, "approval_responded", json.dumps({
                "approval_id": approval_id,
                "status": response.status,
                "approver_id": approver_id,
                "comments": response.comments,
                "action": row["action"]
            }), datetime.utcnow())

            # Broadcast update to WebSocket connections
            approval_data = {
                "approval_id": approval_id,
                "workflow_id": workflow_id,
                "action": row["action"],
                "description": row["description"],
                "status": response.status,
                "approver_id": approver_id,
                "approval_comments": response.comments,
                "responded_at": datetime.utcnow().isoformat(),
                "tenant_id": tenant_scope,
            }

            await ws_manager.broadcast_approval_update(str(tenant_scope), approval_data)

            # If approved, trigger workflow continuation
            if response.status == "approved":
                agent = await _get_organization_agent()
                if agent:
                    try:
                        asyncio.create_task(
                            agent.continue_workflow(
                                workflow_id,
                                {
                                    "status": response.status,
                                    "comments": response.comments,
                                    "approver": approver_id,
                                },
                            )
                        )
                    except Exception as e:
                        logger.error(f"Failed to continue workflow {workflow_id}: {e}")

            return {"success": True, "message": f"Approval {response.status} successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error responding to approval {approval_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to process approval response")

@router.get("/workflows/active")
async def get_active_workflows(
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Get active workflows for a tenant"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        async with get_connection() as conn:
            query = """
                SELECT
                    w.workflow_id,
                    w.current_action,
                    w.organization_id,
                    w.initiated_by,
                    w.created_at,
                    w.updated_at,
                    w.context_data,
                    COUNT(DISTINCT p.id) as total_prospects,
                    COUNT(DISTINCT a.approval_id) FILTER (WHERE a.status = 'pending') as pending_approvals
                FROM workflow_contexts w
                LEFT JOIN prospects p ON p.organization_id = w.organization_id
                LEFT JOIN approval_requests a ON a.workflow_id = w.workflow_id AND a.status = 'pending'
                WHERE w.tenant_id = $1 AND w.workflow_state = 'active'
                GROUP BY w.workflow_id, w.current_action, w.organization_id, w.initiated_by,
                         w.created_at, w.updated_at, w.context_data
                ORDER BY w.created_at DESC
            """

            rows = await conn.fetch(query, tenant_scope)

            workflows = []
            for row in rows:
                workflow = {
                    "workflow_id": row["workflow_id"],
                    "current_action": row["current_action"],
                    "organization_id": row["organization_id"],
                    "initiated_by": row["initiated_by"],
                    "total_prospects": row["total_prospects"] or 0,
                    "pending_approvals": row["pending_approvals"] or 0,
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat()
                }
                workflows.append(workflow)

            return {"workflows": workflows}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching active workflows: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch workflows")

@router.get("/workflows/{workflow_id}/status")
async def get_workflow_status(
    workflow_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """Get detailed status of a specific workflow"""

    try:
        tenant_scope = _resolve_authorized_tenant(None, current_user)

        async with get_connection() as conn:
            # Get workflow context
            workflow_query = """
                SELECT * FROM workflow_contexts WHERE workflow_id = $1
            """
            workflow_row = await conn.fetchrow(workflow_query, workflow_id)

            if not workflow_row:
                raise HTTPException(status_code=404, detail="Workflow not found")

            row_tenant = workflow_row.get("tenant_id")
            if row_tenant is not None and str(row_tenant) != str(tenant_scope):
                raise HTTPException(status_code=403, detail="Access denied to this workflow")

            # Get pending approvals
            approvals_query = """
                SELECT approval_id, action, description, risk_score, requested_at, priority
                FROM approval_requests
                WHERE workflow_id = $1 AND status = 'pending'
                ORDER BY requested_at ASC
            """
            approval_rows = await conn.fetch(approvals_query, workflow_id)

            # Get recent agent decisions
            decisions_query = """
                SELECT decision_type, reasoning, confidence_score, decided_at
                FROM agent_decisions
                WHERE workflow_id = $1
                ORDER BY decided_at DESC
                LIMIT 5
            """
            decision_rows = await conn.fetch(decisions_query, workflow_id)

            # Build response
            workflow_status = {
                "workflow_id": workflow_row["workflow_id"],
                "current_action": workflow_row["current_action"],
                "workflow_state": workflow_row["workflow_state"],
                "created_at": workflow_row["created_at"].isoformat(),
                "updated_at": workflow_row["updated_at"].isoformat(),
                "steps_completed": workflow_row["steps_completed"],
                "steps_total": workflow_row["steps_total"],
                "error_count": workflow_row["error_count"],
                "last_error": workflow_row["last_error"],
                "context_data": workflow_row["context_data"],

                "pending_approvals": [
                    {
                        "approval_id": row["approval_id"],
                        "action": row["action"],
                        "description": row["description"],
                        "risk_score": float(row["risk_score"]),
                        "priority": row["priority"],
                        "requested_at": row["requested_at"].isoformat()
                    }
                    for row in approval_rows
                ],

                "recent_decisions": [
                    {
                        "decision_type": row["decision_type"],
                        "reasoning": row["reasoning"],
                        "confidence_score": float(row["confidence_score"]) if row["confidence_score"] else None,
                        "decided_at": row["decided_at"].isoformat()
                    }
                    for row in decision_rows
                ]
            }

            return {"workflow": workflow_status}

    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching workflow status for {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch workflow status")

@router.get("/approvals/stats")
async def get_approval_stats(
    tenant_id: Optional[int] = Query(None, description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Get approval queue statistics"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        async with get_connection() as conn:
            stats_query = """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending') as pending_count,
                    COUNT(*) FILTER (WHERE status = 'approved') as approved_count,
                    COUNT(*) FILTER (WHERE status = 'rejected') as rejected_count,
                    COUNT(*) FILTER (WHERE status = 'timeout') as timeout_count,
                    COUNT(*) FILTER (WHERE risk_score > 0.7 AND status = 'pending') as high_risk_pending,
                    AVG(EXTRACT(EPOCH FROM (responded_at - requested_at))/3600) FILTER (WHERE status IN ('approved', 'rejected')) as avg_response_time_hours
                FROM approval_requests
                WHERE tenant_id = $1 AND requested_at >= NOW() - INTERVAL '30 days'
            """

            row = await conn.fetchrow(stats_query, tenant_scope)

            stats = {
                "pending_count": row["pending_count"] or 0,
                "approved_count": row["approved_count"] or 0,
                "rejected_count": row["rejected_count"] or 0,
                "timeout_count": row["timeout_count"] or 0,
                "high_risk_pending": row["high_risk_pending"] or 0,
                "avg_response_time_hours": round(float(row["avg_response_time_hours"] or 0), 2),
                "total_processed": (row["approved_count"] or 0) + (row["rejected_count"] or 0),
                "approval_rate": round(
                    (row["approved_count"] or 0) / max((row["approved_count"] or 0) + (row["rejected_count"] or 0), 1) * 100,
                    1
                )
            }

            return {"stats": stats}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching approval stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch approval statistics")

# WebSocket connection status endpoint
@router.get("/ws/status")
async def get_websocket_status():
    """Get WebSocket connection statistics"""
    try:
        stats = await ws_manager.get_connection_stats()
        return {"websocket_stats": stats}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching WebSocket stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch WebSocket statistics")

# Initialize WebSocket manager on startup
@router.on_event("startup")
async def startup_event():
    """Initialize WebSocket manager when the API starts"""
    try:
        await ws_manager.initialize()
        logger.info("WebSocket manager initialized successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initialize WebSocket manager: {e}")
        # Don't raise here to allow the API to start without WebSocket support

@router.on_event("shutdown")
async def shutdown_event():
    """Shutdown WebSocket manager when the API stops"""
    try:
        await ws_manager.shutdown()
        logger.info("WebSocket manager shut down successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error shutting down WebSocket manager: {e}")

# Integration point for VouchLinkAIOrganizationAgent
async def publish_approval_request(approval_request: Dict[str, any]):
    """Publish a new approval request to WebSocket connections (called by agent)"""
    tenant_id = str(approval_request.get("tenant_id"))
    await ws_manager.broadcast_approval_update(tenant_id, approval_request)

async def publish_workflow_update(workflow_update: Dict[str, any]):
    """Publish a workflow status update to WebSocket connections (called by agent)"""
    tenant_id = str(workflow_update.get("tenant_id"))
    await ws_manager.broadcast_workflow_update(tenant_id, workflow_update)
