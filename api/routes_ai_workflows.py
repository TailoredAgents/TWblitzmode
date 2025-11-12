"""
AI Workflow Management API Routes - September 2025 AI Integration
Backend endpoints for autonomous AI workflow system with zero-click automation
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field, field_validator

from .deps import get_current_user, get_connection, get_connection_dependency
from .websocket_manager import ws_manager
from services.agent_logger import agent_logger, AgentEventType, LogLevel as AgentLogLevel
from services.centralized_logging_service import LogCategory, LogLevel, log_structured

logger = logging.getLogger(__name__)


def _workflow_log(level: LogLevel, message: str, current_user: Dict[str, Any], **extra) -> None:
    log_structured(
        level,
        message,
        category=LogCategory.BUSINESS,
        tenant_id=str(current_user.get("tenant_id")) if current_user else None,
        user_id=str(current_user.get("id")) if current_user else None,
        **extra,
    )

router = APIRouter(prefix="/api/ai", tags=["ai_workflows"])
security = HTTPBearer()

# Pydantic models for AI Workflows
class WorkflowInput(BaseModel):
    workflow_type: str
    input_data: Dict[str, Any]
    priority: str = "normal"
    autonomous: bool = True
    approval_required: bool = False

    @field_validator('workflow_type')
    def validate_workflow_type(cls, v: str) -> str:
        allowed_types = [
            'prospecting', 'outreach', 'qualification', 'research', 'follow_up',
            'prospect_analysis', 'email_generation', 'network_mapping'
        ]
        if v not in allowed_types:
            raise ValueError(f'Workflow type must be one of: {", ".join(allowed_types)}')
        return v

    @field_validator('priority')
    def validate_priority(cls, v: str) -> str:
        if v not in ['low', 'normal', 'high', 'urgent']:
            raise ValueError('Priority must be low, normal, high, or urgent')
        return v

class WorkflowResponse(BaseModel):
    workflow_id: str
    type: str
    status: str
    organization_id: int
    user_id: int
    input_data: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    pending_approvals: List[str] = Field(default_factory=list)
    autonomous: bool
    created_at: datetime
    updated_at: datetime

class WorkflowListResponse(BaseModel):
    workflows: List[WorkflowResponse]
    total: int
    page: int
    limit: int

class ApprovalDecision(BaseModel):
    decision: str
    feedback: Optional[str] = None

    @field_validator('decision')
    def validate_decision(cls, v: str) -> str:
        if v not in ['approve', 'reject']:
            raise ValueError('Decision must be approve or reject')
        return v

# Database table initialization
async def ensure_ai_workflows_table(connection: asyncpg.Connection):
    """Ensure the ai_workflows table exists"""
    try:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS ai_workflows (
                workflow_id VARCHAR(36) PRIMARY KEY,
                type VARCHAR(50) NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'initiated',
                organization_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                input_data JSONB NOT NULL,
                result JSONB DEFAULT NULL,
                pending_approvals JSONB DEFAULT '[]'::jsonb,
                autonomous BOOLEAN DEFAULT true,
                priority VARCHAR(20) DEFAULT 'normal',
                approval_required BOOLEAN DEFAULT false,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        # Create indexes for better performance
        await connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_workflows_org_id ON ai_workflows(organization_id);
        """)
        await connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_workflows_user_id ON ai_workflows(user_id);
        """)
        await connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_workflows_status ON ai_workflows(status);
        """)
        await connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_workflows_type ON ai_workflows(type);
        """)

    except Exception as e:
        logger.error(f"Failed to create ai_workflows table: {e}")
        raise

@router.post("/workflows", response_model=Dict[str, str])
async def start_ai_workflow(
    workflow_input: WorkflowInput,
    connection: asyncpg.Connection = Depends(get_connection_dependency),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Start a new AI workflow"""
    _workflow_log(
        LogLevel.INFO,
        "AI workflow requested",
        current_user,
        workflow_type=workflow_input.workflow_type,
        approval_required=workflow_input.approval_required,
        autonomous=workflow_input.autonomous,
    )

    _workflow_log(
        LogLevel.INFO,
        "Listing AI workflows",
        current_user,
        page=page,
        limit=limit,
        status_filter=status,
        workflow_type=workflow_type,
    )

    try:
        # Ensure table exists
        await ensure_ai_workflows_table(connection)

        workflow_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # Determine initial status based on approval requirement
        initial_status = 'pending_approval' if workflow_input.approval_required else 'initiated'

        # Enhanced input data with organization context
        enhanced_input_data = {
            **workflow_input.input_data,
            "organization_id": current_user["tenant_id"],
            "user_id": current_user["id"],
            "priority": workflow_input.priority,
            "autonomous": workflow_input.autonomous,
            "started_by": current_user.get("email"),
            "workflow_template": workflow_input.workflow_type
        }

        # Insert workflow into database
        await connection.execute("""
            INSERT INTO ai_workflows (
                workflow_id, type, status, organization_id, user_id,
                input_data, autonomous, priority, approval_required,
                created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
            workflow_id, workflow_input.workflow_type, initial_status,
            current_user["tenant_id"], current_user["id"],
            json.dumps(enhanced_input_data), workflow_input.autonomous,
            workflow_input.priority, workflow_input.approval_required,
            now, now
        )

        # Log workflow start
        await agent_logger.log_workflow_start(
            agent_id=f"workflow-{workflow_id}",
            workflow_id=workflow_id,
            workflow_type=workflow_input.workflow_type,
            tenant_id=str(current_user["tenant_id"]),
            user_id=str(current_user["id"])
        )

        # Send WebSocket notification
        await ws_manager.send_to_organization(
            current_user["tenant_id"],
            {
                "type": "workflow_started",
                "workflow_id": workflow_id,
                "workflow_type": workflow_input.workflow_type,
                "status": initial_status,
                "autonomous": workflow_input.autonomous
            }
        )

        # If autonomous and no approval required, start processing immediately
        if workflow_input.autonomous and not workflow_input.approval_required:
            # Start background processing
            asyncio.create_task(process_autonomous_workflow(workflow_id))

        _workflow_log(
            LogLevel.INFO,
            "AI workflow queued",
            current_user,
            workflow_id=workflow_id,
            workflow_type=workflow_input.workflow_type,
            status=initial_status,
        )

        return {"workflow_id": workflow_id, "status": initial_status}

    except Exception as e:
        logger.error(f"Failed to start AI workflow: {e}")
        _workflow_log(
            LogLevel.ERROR,
            "Failed to start AI workflow",
            current_user,
            exc_info=e,
            workflow_type=workflow_input.workflow_type,
        )
        await agent_logger.log_event(
            event_type=AgentEventType.SYSTEM_EVENT,
            agent_id=f"workflow-system",
            message=f"Failed to start workflow: {str(e)}",
            level=AgentLogLevel.ERROR,
            tenant_id=str(current_user.get("tenant_id"))
        )
        raise HTTPException(status_code=500, detail="Failed to start workflow")

@router.get("/workflows", response_model=WorkflowListResponse)
async def list_ai_workflows(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None),
    workflow_type: Optional[str] = Query(None),
    connection: asyncpg.Connection = Depends(get_connection_dependency),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """List AI workflows for the current user's organization"""
    try:
        # Ensure table exists
        await ensure_ai_workflows_table(connection)

        # Build query with filters
        where_conditions = ["organization_id = $1"]
        params = [current_user["tenant_id"]]
        param_count = 1

        if status:
            param_count += 1
            where_conditions.append(f"status = ${param_count}")
            params.append(status)

        if workflow_type:
            param_count += 1
            where_conditions.append(f"type = ${param_count}")
            params.append(workflow_type)

        where_clause = " AND ".join(where_conditions)

        # Get total count
        count_query = f"SELECT COUNT(*) FROM ai_workflows WHERE {where_clause}"
        total = await connection.fetchval(count_query, *params)

        # Get workflows with pagination
        offset = (page - 1) * limit
        param_count += 1
        params.append(limit)
        param_count += 1
        params.append(offset)

        workflows_query = f"""
            SELECT workflow_id, type, status, organization_id, user_id,
                   input_data, result, pending_approvals, autonomous,
                   created_at, updated_at
            FROM ai_workflows
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_count-1} OFFSET ${param_count}
        """

        rows = await connection.fetch(workflows_query, *params)

        workflows = []
        for row in rows:
            workflows.append(WorkflowResponse(
                workflow_id=row['workflow_id'],
                type=row['type'],
                status=row['status'],
                organization_id=row['organization_id'],
                user_id=row['user_id'],
                input_data=_normalize_json(row['input_data']) or {},
                result=_normalize_json(row['result']),
                pending_approvals=_normalize_list(row['pending_approvals']),
                autonomous=row['autonomous'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            ))

        response_payload = WorkflowListResponse(
            workflows=workflows,
            total=total,
            page=page,
            limit=limit
        )

        _workflow_log(
            LogLevel.INFO,
            "AI workflows listed",
            current_user,
            total=total,
            returned=len(workflows),
            page=page,
            limit=limit,
        )

        return response_payload

    except Exception as e:
        logger.error(f"Failed to list AI workflows: {e}")
        _workflow_log(
            LogLevel.ERROR,
            "Failed to list AI workflows",
            current_user,
            exc_info=e,
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve workflows")

@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_ai_workflow(
    workflow_id: str,
    connection: asyncpg.Connection = Depends(get_connection_dependency),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get a specific AI workflow by ID"""
    _workflow_log(
        LogLevel.INFO,
        "Fetching AI workflow",
        current_user,
        workflow_id=workflow_id,
    )

    try:
        # Ensure table exists
        await ensure_ai_workflows_table(connection)

        row = await connection.fetchrow("""
            SELECT workflow_id, type, status, organization_id, user_id,
                   input_data, result, pending_approvals, autonomous,
                   created_at, updated_at
            FROM ai_workflows
            WHERE workflow_id = $1 AND organization_id = $2
        """, workflow_id, current_user["tenant_id"])

        if not row:
            raise HTTPException(status_code=404, detail="Workflow not found")

        response_payload = WorkflowResponse(
            workflow_id=row['workflow_id'],
            type=row['type'],
            status=row['status'],
            organization_id=row['organization_id'],
            user_id=row['user_id'],
            input_data=_normalize_json(row['input_data']) or {},
            result=_normalize_json(row['result']),
            pending_approvals=_normalize_list(row['pending_approvals']),
            autonomous=row['autonomous'],
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )

        _workflow_log(
            LogLevel.INFO,
            "AI workflow fetched",
            current_user,
            workflow_id=workflow_id,
            status=response_payload.status,
        )

        return response_payload

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get AI workflow {workflow_id}: {e}")
        _workflow_log(
            LogLevel.ERROR,
            "Failed to fetch AI workflow",
            current_user,
            workflow_id=workflow_id,
            exc_info=e,
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve workflow")

@router.post("/workflows/{workflow_id}/approve")
async def approve_workflow_step(
    workflow_id: str,
    decision: ApprovalDecision,
    approval_id: str = Query(...),
    connection: asyncpg.Connection = Depends(get_connection_dependency),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Approve or reject a workflow step"""
    try:
        # Ensure table exists
        await ensure_ai_workflows_table(connection)

        # Get current workflow
        workflow = await connection.fetchrow("""
            SELECT workflow_id, status, pending_approvals, type
            FROM ai_workflows
            WHERE workflow_id = $1 AND organization_id = $2
        """, workflow_id, current_user["tenant_id"])

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if workflow['status'] != 'pending_approval':
            raise HTTPException(status_code=400, detail="Workflow is not pending approval")

        # Update workflow status based on decision
        new_status = 'approved' if decision.decision == 'approve' else 'rejected'
        now = datetime.utcnow()

        await connection.execute("""
            UPDATE ai_workflows
            SET status = $1, updated_at = $2
            WHERE workflow_id = $3
        """, new_status, now, workflow_id)

        # Log approval decision
        await agent_logger.log_approval_decision(
            agent_id=f"workflow-{workflow_id}",
            approval_id=approval_id,
            decision=decision.decision,
            feedback=decision.feedback,
            tenant_id=str(current_user["tenant_id"]),
            user_id=str(current_user["id"])
        )

        # Send WebSocket notification
        await ws_manager.send_to_organization(
            current_user["tenant_id"],
            {
                "type": "workflow_decision",
                "workflow_id": workflow_id,
                "decision": decision.decision,
                "approver": current_user.get("email"),
                "status": new_status
            }
        )

        # If approved, continue processing
        if decision.decision == 'approve':
            asyncio.create_task(process_autonomous_workflow(workflow_id))

        return {"status": "success", "workflow_status": new_status}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to process approval")

async def process_autonomous_workflow(workflow_id: str) -> None:
    """Background task to process autonomous workflows"""
    start_time = time.perf_counter()
    try:
        async with get_connection() as connection:
            await ensure_ai_workflows_table(connection)

            workflow = await connection.fetchrow("""
                SELECT workflow_id, type, input_data, organization_id, user_id
                FROM ai_workflows
                WHERE workflow_id = $1
            """, workflow_id)

            if not workflow:
                logger.error(f"Workflow {workflow_id} not found for processing")
                return

            # Perform asynchronous processing placeholder
            result = await generate_workflow_result(
                workflow['type'],
                _normalize_json(workflow['input_data']) or {},
            )

            now = datetime.utcnow()
            await connection.execute("""
                UPDATE ai_workflows
                SET status = 'completed', result = $1, updated_at = $2
                WHERE workflow_id = $3
            """, json.dumps(result), now, workflow_id)

            await agent_logger.log_workflow_complete(
                agent_id=f"workflow-{workflow_id}",
                workflow_id=workflow_id,
                result=result,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                tenant_id=str(workflow['organization_id']),
            )

            await ws_manager.send_to_organization(
                workflow['organization_id'],
                {
                    "type": "workflow_completed",
                    "workflow_id": workflow_id,
                    "result": result
                }
            )

    except Exception as e:
        logger.error(f"Failed to process autonomous workflow {workflow_id}: {e}")

        # Mark workflow as failed
        try:
            async with get_connection() as connection:
                await connection.execute("""
                    UPDATE ai_workflows
                    SET status = 'failed', updated_at = $1
                    WHERE workflow_id = $2
                """, datetime.utcnow(), workflow_id)
        except Exception as update_error:
            logger.error(f"Failed to update failed workflow status: {update_error}")

async def generate_workflow_result(workflow_type: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a minimal result payload."""

    return {
        "workflow_type": workflow_type,
        "input_snapshot": input_data or None,
        "details": None,
        "completed_at": datetime.utcnow().isoformat(),
    }


def _normalize_json(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            logger.warning("Unable to decode JSON field: %s", value[:100])
            return None
    try:
        return dict(value)
    except Exception:
        logger.warning("Unable to coerce value to dict: %s", value)
        return None


def _normalize_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            logger.warning("Unable to decode list field: %s", value[:100])
    return [str(value)]

@router.get("/workflows/health")
async def workflow_health_check():
    """Health check for AI workflows service"""
    return {
        "status": "healthy",
        "service": "ai_workflows",
        "timestamp": datetime.utcnow().isoformat(),
        "features": {
            "autonomous_execution": True,
            "approval_workflows": True,
            "real_time_notifications": True,
            "advanced_logging": True
        }
    }
