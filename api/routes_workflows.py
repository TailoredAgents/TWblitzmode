"""
Workflow Management API Routes

Provides APIs for visual workflow builder, template management,
and workflow execution orchestration.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.security import HTTPBearer
from pydantic import BaseModel, field_validator
import asyncpg

from .deps import get_current_user, get_connection
from .websocket_manager import ws_manager
from services.workflow_coordinator import workflow_coordinator, WorkflowStatus
from services.redis_streams_queue import MessagePriority
from services.openai_agents_2025_integration import openai_agents_integration, AgentRole
from services.subscription_feature_service import subscription_feature_service
from services.company_list_parser import create_company_csv, parse_company_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])
security = HTTPBearer()


def _require_corporate_connect(tenant_id: int) -> None:
    """Ensure the requesting tenant has access to Corporate Connect."""

    if not subscription_feature_service.is_feature_enabled(tenant_id, "corporate_connect"):
        raise HTTPException(
            status_code=403,
            detail="Corporate Connect is not available for the current subscription tier."
        )


def _resolve_authorized_tenant(requested_tenant_id: Optional[int], current_user: Dict[str, Any]) -> int:
    """
    Confirm the tenant/organization context aligns with the authenticated user.

    Workflow APIs historically allowed tenant_id to be supplied via query string,
    which opened tenant-impersonation risks. This helper enforces that the
    caller can only act within their assigned organization scope.
    """
    organization_id = current_user.get("organization_id")
    if organization_id is None:
        tenant_token = current_user.get("tenant_id")
        try:
            organization_id = int(tenant_token)
        except (TypeError, ValueError):
            logger.warning(
                "User %s lacks a resolvable organization context (tenant=%s)",
                current_user.get("id"),
                tenant_token,
            )
            raise HTTPException(status_code=403, detail="No organization context available for user")

    organization_id = int(organization_id)

    if requested_tenant_id is not None and requested_tenant_id != organization_id:
        logger.warning(
            "Tenant scope mismatch: user %s attempted %s but is bound to %s",
            current_user.get("id"),
            requested_tenant_id,
            organization_id,
        )
        raise HTTPException(status_code=403, detail="Unauthorized tenant scope")

    return organization_id

class WorkflowNode(BaseModel):
    id: str
    type: str  # 'start', 'action', 'decision', 'end'
    title: str
    description: str
    position: Dict[str, float]
    config: Dict[str, Any]
    connections: List[str]
    status: str = 'pending'
    metrics: Optional[Dict[str, int]] = None

    @field_validator('type')
    def validate_type(cls, v: str) -> str:
        if v not in ['start', 'action', 'decision', 'end']:
            raise ValueError('Invalid node type')
        return v

class WorkflowTemplate(BaseModel):
    id: Optional[str] = None
    name: str
    description: str
    category: str
    nodes: List[WorkflowNode]
    is_default: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class WorkflowExecution(BaseModel):
    id: Optional[str] = None
    name: str
    template_id: str
    status: str = 'created'
    current_node: Optional[str] = None
    context_data: Dict[str, Any] = {}
    created_at: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None

@router.get("/templates")
async def get_workflow_templates(
    tenant_id: int = Query(..., description="Tenant ID"),
    category: Optional[str] = Query(None, description="Filter by category"),
    current_user: Dict = Depends(get_current_user)
):
    """Get workflow templates for a tenant"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        async with get_connection() as conn:
            # Build query with optional category filter
            where_conditions = ["tenant_id = $1"]
            params = [tenant_scope]
            param_count = 1

            if category:
                param_count += 1
                where_conditions.append(f"category = ${param_count}")
                params.append(category)

            where_clause = " AND ".join(where_conditions)

            query = f"""
                SELECT
                    id, name, description, category, nodes_config,
                    is_default, created_at, updated_at
                FROM workflow_templates
                WHERE {where_clause}
                ORDER BY is_default DESC, created_at DESC
            """

            rows = await conn.fetch(query, *params)

            templates = []
            for row in rows:
                template = {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "category": row["category"],
                    "nodes": json.loads(row["nodes_config"]) if row["nodes_config"] else [],
                    "isDefault": row["is_default"],
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat()
                }
                templates.append(template)

            # If no templates exist, return default templates
            if not templates:
                templates = _get_default_templates()

            return {"templates": templates}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching workflow templates: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch workflow templates")

@router.post("/templates")
async def create_workflow_template(
    template: WorkflowTemplate,
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Create or update a workflow template"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        async with get_connection() as conn:
            template_id = template.id or str(uuid.uuid4())
            now = datetime.utcnow()

            # Validate nodes configuration
            _validate_workflow_nodes(template.nodes)

            # Serialize nodes to JSON
            nodes_json = json.dumps([node.dict() for node in template.nodes])

            if template.id:
                # Update existing template
                await conn.execute("""
                    UPDATE workflow_templates SET
                        name = $3, description = $4, category = $5,
                        nodes_config = $6, updated_at = $7
                    WHERE id = $1 AND tenant_id = $2
                """, template.id, tenant_scope, template.name, template.description,
                    template.category, nodes_json, now)
            else:
                # Create new template
                await conn.execute("""
                    INSERT INTO workflow_templates (
                        id, tenant_id, name, description, category,
                        nodes_config, is_default, created_at, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """, template_id, tenant_scope, template.name, template.description,
                    template.category, nodes_json, template.is_default, now, now)

            # Log audit event
            await conn.execute("""
                INSERT INTO audit_events (tenant_id, event_type, details, created_at)
                VALUES ($1, $2, $3, $4)
            """, tenant_scope, "workflow_template_saved", json.dumps({
                "template_id": template_id,
                "name": template.name,
                "action": "update" if template.id else "create"
            }), now)

            return {"success": True, "template_id": template_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving workflow template: {e}")
        raise HTTPException(status_code=500, detail="Failed to save workflow template")

@router.delete("/templates/{template_id}")
async def delete_workflow_template(
    template_id: str,
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Delete a workflow template"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        async with get_connection() as conn:
            # Check if template exists and is not default
            template_row = await conn.fetchrow("""
                SELECT is_default FROM workflow_templates
                WHERE id = $1 AND tenant_id = $2
            """, template_id, tenant_scope)

            if not template_row:
                raise HTTPException(status_code=404, detail="Template not found")

            if template_row["is_default"]:
                raise HTTPException(status_code=400, detail="Cannot delete default template")

            # Delete template
            await conn.execute("""
                DELETE FROM workflow_templates
                WHERE id = $1 AND tenant_id = $2
            """, template_id, tenant_scope)

            # Log audit event
            await conn.execute("""
                INSERT INTO audit_events (tenant_id, event_type, details, created_at)
                VALUES ($1, $2, $3, $4)
            """, tenant_scope, "workflow_template_deleted", json.dumps({
                "template_id": template_id
            }), datetime.utcnow())

            return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting workflow template: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete workflow template")

@router.get("/active")
async def get_active_workflows(
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Get active workflow executions for a tenant"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        async with get_connection() as conn:
            query = """
                SELECT
                    we.id, we.name, we.template_id, we.status,
                    we.current_node, we.created_at, we.context_data,
                    wt.name as template_name,
                    COUNT(DISTINCT p.id) as total_prospects
                FROM workflow_executions we
                LEFT JOIN workflow_templates wt ON wt.id = we.template_id
                LEFT JOIN workflow_contexts wc ON wc.workflow_id::text = we.id
                LEFT JOIN prospects p ON p.organization_id = wc.organization_id
                WHERE we.tenant_id = $1 AND we.status IN ('running', 'paused')
                GROUP BY we.id, we.name, we.template_id, we.status,
                         we.current_node, we.created_at, we.context_data, wt.name
                ORDER BY we.created_at DESC
            """

            rows = await conn.fetch(query, tenant_scope)

            workflows = []
            for row in rows:
                # Calculate metrics
                completion_rate = _calculate_completion_rate(
                    row["status"], row["current_node"]
                )

                workflow = {
                    "id": row["id"],
                    "name": row["name"],
                    "template_id": row["template_id"],
                    "status": row["status"],
                    "current_node": row["current_node"],
                    "created_at": row["created_at"].isoformat(),
                    "metrics": {
                        "total_prospects": row["total_prospects"] or 0,
                        "current_stage": _get_stage_name(row["current_node"]),
                        "completion_rate": completion_rate,
                        "estimated_completion": _estimate_completion(
                            completion_rate, row["created_at"]
                        )
                    }
                }
                workflows.append(workflow)

            return {"workflows": workflows}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching active workflows: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch active workflows")

@router.post("/start")
async def start_workflow(
    execution: WorkflowExecution,
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Start a new workflow execution"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        async with get_connection() as conn:
            # Get template
            template_row = await conn.fetchrow("""
                SELECT nodes_config FROM workflow_templates
                WHERE id = $1 AND tenant_id = $2
            """, execution.template_id, tenant_scope)

            if not template_row:
                raise HTTPException(status_code=404, detail="Template not found")

            execution_id = str(uuid.uuid4())
            now = datetime.utcnow()

            # Create workflow execution record
            await conn.execute("""
                INSERT INTO workflow_executions (
                    id, tenant_id, name, template_id, status,
                    current_node, context_data, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """, execution_id, tenant_scope, execution.name, execution.template_id,
                'running', 'start', json.dumps(execution.context_data), now, now)

            # Create workflow context for VouchLinkAIOrganizationAgent
            workflow_context_id = str(uuid.uuid4())
            await conn.execute("""
                INSERT INTO workflow_contexts (
                    workflow_id, tenant_id, organization_id, integration_set_id,
                    initiated_by, current_action, context_data, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """, workflow_context_id, tenant_scope,
                current_user.get("organization_id", tenant_scope),
                current_user.get("integration_set_id", 1),  # Default integration set
                current_user["id"], 'prospect_ingestion',
                json.dumps(execution.context_data), now, now)

            # Start AI orchestration (if VouchLinkAIOrganizationAgent is available)
            try:
                from services.vouchlink_ai_organization_agent import VouchLinkAIOrganizationAgent

                # This would be configured with proper credentials in production
                agent = VouchLinkAIOrganizationAgent(
                    openai_api_key="your_openai_key",  # From config
                    database_url="your_db_url"  # From config
                )

                # Start workflow asynchronously
                asyncio.create_task(
                    agent.start_workflow(
                        tenant_id=str(tenant_scope),
                        organization_id=str(current_user.get("organization_id", tenant_scope)),
                        integration_set_id=str(current_user.get("integration_set_id", 1)),
                        initiated_by=str(current_user["id"]),
                        initial_action="prospect_ingestion",
                        context_data=execution.context_data
                    )
                )
            except Exception as e:
                logger.warning(f"Could not start AI orchestration: {e}")

            # Log audit event
            await conn.execute("""
                INSERT INTO audit_events (tenant_id, event_type, details, created_at)
                VALUES ($1, $2, $3, $4)
            """, tenant_scope, "workflow_started", json.dumps({
                "execution_id": execution_id,
                "template_id": execution.template_id,
                "name": execution.name
            }), now)

            # Broadcast workflow update
            try:
                await ws_manager.broadcast_approval_update(str(tenant_scope), {
                    "type": "workflow_started",
                    "execution_id": execution_id,
                    "template_id": execution.template_id,
                    "name": execution.name,
                    "timestamp": now.isoformat()
                })
            except Exception as e:
                logger.warning(f"Failed to broadcast workflow start: {e}")

            return {"success": True, "execution_id": execution_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting workflow: {e}")
        raise HTTPException(status_code=500, detail="Failed to start workflow")

@router.post("/executions/{execution_id}/pause")
async def pause_workflow(
    execution_id: str,
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Pause a running workflow"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        async with get_connection() as conn:
            # Update execution status
            result = await conn.execute("""
                UPDATE workflow_executions SET
                    status = 'paused', updated_at = $3
                WHERE id = $1 AND tenant_id = $2 AND status = 'running'
            """, execution_id, tenant_scope, datetime.utcnow())

            if result == "UPDATE 0":
                raise HTTPException(status_code=404, detail="Workflow not found or not running")

            return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pausing workflow: {e}")
        raise HTTPException(status_code=500, detail="Failed to pause workflow")

@router.post("/executions/{execution_id}/resume")
async def resume_workflow(
    execution_id: str,
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Resume a paused workflow"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        async with get_connection() as conn:
            # Update execution status
            result = await conn.execute("""
                UPDATE workflow_executions SET
                    status = 'running', updated_at = $3
                WHERE id = $1 AND tenant_id = $2 AND status = 'paused'
            """, execution_id, tenant_scope, datetime.utcnow())

            if result == "UPDATE 0":
                raise HTTPException(status_code=404, detail="Workflow not found or not paused")

            return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming workflow: {e}")
        raise HTTPException(status_code=500, detail="Failed to resume workflow")

@router.get("/executions/{execution_id}/status")
async def get_workflow_status(
    execution_id: str,
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Get detailed status of a workflow execution"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        async with get_connection() as conn:
            # Get execution details
            execution_row = await conn.fetchrow("""
                SELECT * FROM workflow_executions
                WHERE id = $1 AND tenant_id = $2
            """, execution_id, tenant_scope)

            if not execution_row:
                raise HTTPException(status_code=404, detail="Workflow execution not found")

            # Get template nodes for progress calculation
            template_row = await conn.fetchrow("""
                SELECT nodes_config FROM workflow_templates
                WHERE id = $1
            """, execution_row["template_id"])

            nodes = json.loads(template_row["nodes_config"]) if template_row else []

            # Get node statuses (would be updated by actual execution)
            node_statuses = _get_node_statuses(execution_row["current_node"], nodes)

            return {
                "execution": {
                    "id": execution_row["id"],
                    "name": execution_row["name"],
                    "status": execution_row["status"],
                    "current_node": execution_row["current_node"],
                    "created_at": execution_row["created_at"].isoformat(),
                    "updated_at": execution_row["updated_at"].isoformat()
                },
                "nodes": node_statuses,
                "progress": {
                    "completed_nodes": len([n for n in node_statuses if n["status"] == "completed"]),
                    "total_nodes": len(nodes),
                    "percentage": _calculate_completion_rate(
                        execution_row["status"], execution_row["current_node"]
                    )
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching workflow status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch workflow status")

# Helper functions
def _validate_workflow_nodes(nodes: List[WorkflowNode]):
    """Validate workflow node configuration"""
    if not nodes:
        raise HTTPException(status_code=400, detail="Workflow must have at least one node")

    # Check for start and end nodes
    start_nodes = [n for n in nodes if n.type == 'start']
    end_nodes = [n for n in nodes if n.type == 'end']

    if len(start_nodes) != 1:
        raise HTTPException(status_code=400, detail="Workflow must have exactly one start node")

    if len(end_nodes) < 1:
        raise HTTPException(status_code=400, detail="Workflow must have at least one end node")

    # Check for orphaned nodes
    node_ids = {n.id for n in nodes}
    for node in nodes:
        for connection in node.connections:
            if connection not in node_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Node {node.id} has invalid connection: {connection}"
                )

def _get_default_templates() -> List[Dict]:
    """Return default workflow templates"""
    return [
        {
            "id": "standard-prospect-flow",
            "name": "Standard Prospect Flow",
            "description": "Complete end-to-end prospect processing with AI optimization",
            "category": "prospecting",
            "isDefault": True,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "title": "Start",
                    "description": "Workflow initiation",
                    "position": {"x": 100, "y": 100},
                    "config": {},
                    "connections": ["ingestion"],
                    "status": "completed",
                    "metrics": {"processed": 1, "successful": 1, "failed": 0}
                },
                {
                    "id": "ingestion",
                    "type": "action",
                    "title": "Prospect Ingestion",
                    "description": "Import and validate prospect data",
                    "position": {"x": 100, "y": 200},
                    "config": {"batch_size": 100},
                    "connections": ["lookup"],
                    "status": "active",
                    "metrics": {"processed": 247, "successful": 242, "failed": 5}
                }
            ]
        }
    ]

def _calculate_completion_rate(status: str, current_node: str) -> int:
    """Calculate workflow completion percentage"""
    if status == 'completed':
        return 100
    elif status == 'failed':
        return 0
    elif current_node == 'start':
        return 10
    else:
        # Simple mapping - in production would be more sophisticated
        node_progress = {
            'ingestion': 20,
            'lookup': 35,
            'mutuals': 50,
            'scoring': 65,
            'approval': 75,
            'enrichment': 85,
            'scheduling': 95,
            'end': 100
        }
        return node_progress.get(current_node, 50)

def _get_stage_name(node_id: str) -> str:
    """Convert node ID to friendly stage name"""
    stage_names = {
        'start': 'Initializing',
        'ingestion': 'Importing Prospects',
        'lookup': 'Finding Executives',
        'mutuals': 'Discovering Connections',
        'scoring': 'Ranking Connectors',
        'approval': 'Awaiting Approval',
        'enrichment': 'Finding Emails',
        'scheduling': 'Scheduling Outreach',
        'end': 'Completed'
    }
    return stage_names.get(node_id, 'Processing')

def _estimate_completion(completion_rate: int, created_at: datetime) -> str:
    """Estimate workflow completion time"""
    if completion_rate >= 100:
        return "Completed"

    elapsed = datetime.utcnow() - created_at
    if completion_rate > 0:
        total_estimated = elapsed.total_seconds() * (100 / completion_rate)
        remaining_seconds = total_estimated - elapsed.total_seconds()

        if remaining_seconds <= 3600:  # Less than 1 hour
            return f"{int(remaining_seconds / 60)} minutes"
        elif remaining_seconds <= 86400:  # Less than 1 day
            return f"{int(remaining_seconds / 3600)} hours"
        else:
            return f"{int(remaining_seconds / 86400)} days"

    return "Estimating..."

def _get_node_statuses(current_node: str, nodes: List[Dict]) -> List[Dict]:
    """Get status for each node in the workflow"""
    node_order = ['start', 'ingestion', 'lookup', 'mutuals', 'scoring', 'approval', 'enrichment', 'scheduling', 'end']
    current_index = node_order.index(current_node) if current_node in node_order else 0

    result = []
    for i, node in enumerate(nodes):
        if i < current_index:
            status = 'completed'
        elif i == current_index:
            status = 'active'
        else:
            status = 'pending'

        result.append({
            **node,
            "status": status
        })

    return result

# =============================================================================
# CORPORATE WORKFLOW ENDPOINTS
# =============================================================================

class CorporateWorkflowResponse(BaseModel):
    """Response model for corporate workflow information"""
    workflow_id: str
    organization_id: str
    tenant_id: str
    user_id: int
    status: str
    stage: str
    prospects_processed: int
    connectors_found: int
    emails_scheduled: int
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class CorporateWorkflowMetrics(BaseModel):
    """Response model for corporate workflow metrics"""
    period_days: int
    total_workflows: int
    completed_workflows: int
    failed_workflows: int
    active_workflows: int
    completion_rate_percent: float
    failure_rate_percent: float
    total_prospects_processed: int
    total_connectors_found: int
    total_emails_scheduled: int
    average_prospects_per_workflow: float
    average_connectors_per_workflow: float

@router.post("/corporate/start")
async def start_corporate_workflow(
    file: Optional[UploadFile] = File(
        default=None,
        description="Company list file (CSV, XLSX, DOCX)"
    ),
    company_list: str = Form(
        default="",
        description="Inline company list (one company per line)"
    ),
    priority: str = Form(default="normal", description="Workflow priority"),
    metadata: str = Form(default="{}", description="JSON metadata string"),
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """
    Start a new corporate introduction workflow

    Upload a CSV file with prospect data and start the complete workflow:
    1. Prospect ingestion and validation
    2. Executive LinkedIn profile lookup
    3. Mutual connections discovery
    4. Connector scoring and ranking
    5. Email enrichment
    6. Introduction email scheduling
    """

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)
        _require_corporate_connect(int(tenant_scope))

        if file is None and not company_list.strip():
            raise HTTPException(
                status_code=400,
                detail="Provide either a company list file or an inline company_list payload."
            )

        # Parse metadata payload
        try:
            parsed_metadata = json.loads(metadata) if metadata != "{}" else {}
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in metadata field")

        generated_file = None
        inline_count = 0

        if file is not None:
            filename = (file.filename or "prospects.csv").lower()
            suffix = Path(filename).suffix or ".csv"

            if suffix not in {".csv", ".xlsx", ".xls", ".docx"}:
                raise HTTPException(status_code=400, detail="Unsupported file type. Upload CSV, XLSX, XLS, or DOCX files.")

            import tempfile

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix='corporate_workflow_') as temp_file:
                content = await file.read()
                temp_file.write(content)
                temp_file_path = temp_file.name

            parsed_metadata.setdefault('file_name', file.filename)
            parsed_metadata['file_size'] = len(content)
        else:
            temp_file_path, inline_count = create_company_csv(company_list)
            generated_file = temp_file_path
            parsed_metadata.setdefault('file_name', 'inline_company_list.csv')
        if file is not None and company_list.strip():
            inline_count = len(parse_company_list(company_list))

        # Parse priority
        priority_map = {
            "low": MessagePriority.LOW,
            "normal": MessagePriority.NORMAL,
            "high": MessagePriority.HIGH,
            "critical": MessagePriority.CRITICAL
        }
        workflow_priority = priority_map.get(priority.lower(), MessagePriority.NORMAL)

        parsed_metadata.update({
            'uploaded_by': current_user.get('email', 'unknown'),
            'upload_timestamp': datetime.utcnow().isoformat(),
            'input_source': 'inline_company_list' if generated_file else 'file_upload',
            'inline_company_count': inline_count if inline_count else None,
            'company_list': company_list if company_list.strip() else None,
            'file_path': temp_file_path
        })

        parsed_metadata = {key: value for key, value in parsed_metadata.items() if value is not None}

        # Start workflow
        workflow = await workflow_coordinator.start_corporate_workflow(
            organization_id=str(current_user.get("organization_id", tenant_scope)),
            tenant_id=str(tenant_scope),
            user_id=current_user["id"],
            file_path=temp_file_path,
            priority=workflow_priority,
            metadata=parsed_metadata
        )

        logger.info(f"Started corporate workflow {workflow.workflow_id} for tenant {tenant_scope}")

        return CorporateWorkflowResponse(
            workflow_id=workflow.workflow_id,
            organization_id=workflow.organization_id,
            tenant_id=workflow.tenant_id,
            user_id=workflow.user_id,
            status=workflow.status.value,
            stage=workflow.stage,
            prospects_processed=workflow.prospects_processed,
            connectors_found=workflow.connectors_found,
            emails_scheduled=workflow.emails_scheduled,
            created_at=workflow.created_at.isoformat(),
            updated_at=workflow.updated_at.isoformat(),
            completed_at=workflow.completed_at.isoformat() if workflow.completed_at else None,
            error_message=workflow.error_message,
            metadata=workflow.metadata
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start corporate workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start corporate workflow: {str(e)}")

@router.get("/corporate/{workflow_id}")
async def get_corporate_workflow_status(
    workflow_id: str,
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Get the current status of a corporate workflow"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)
        _require_corporate_connect(int(tenant_scope))

        workflow = await workflow_coordinator.get_workflow_status(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Corporate workflow not found")

        # Check access permissions
        if workflow.tenant_id != str(tenant_scope):
            raise HTTPException(status_code=403, detail="Access denied to this workflow")

        return CorporateWorkflowResponse(
            workflow_id=workflow.workflow_id,
            organization_id=workflow.organization_id,
            tenant_id=workflow.tenant_id,
            user_id=workflow.user_id,
            status=workflow.status.value,
            stage=workflow.stage,
            prospects_processed=workflow.prospects_processed,
            connectors_found=workflow.connectors_found,
            emails_scheduled=workflow.emails_scheduled,
            created_at=workflow.created_at.isoformat(),
            updated_at=workflow.updated_at.isoformat(),
            completed_at=workflow.completed_at.isoformat() if workflow.completed_at else None,
            error_message=workflow.error_message,
            metadata=workflow.metadata
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get corporate workflow status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get corporate workflow status: {str(e)}")

@router.get("/corporate")
async def list_corporate_workflows(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, description="Maximum number of workflows to return"),
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """List corporate workflows for the current organization"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)
        _require_corporate_connect(int(tenant_scope))

        # Parse status filter
        status_filter = None
        if status:
            try:
                status_filter = WorkflowStatus(status.lower())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

        workflows = await workflow_coordinator.list_workflows(
            organization_id=str(current_user.get("organization_id", tenant_scope)),
            tenant_id=str(tenant_scope),
            status=status_filter,
            limit=min(limit, 100)  # Cap at 100
        )

        workflow_responses = []
        for w in workflows:
            workflow_responses.append(CorporateWorkflowResponse(
                workflow_id=w.workflow_id,
                organization_id=w.organization_id,
                tenant_id=w.tenant_id,
                user_id=w.user_id,
                status=w.status.value,
                stage=w.stage,
                prospects_processed=w.prospects_processed,
                connectors_found=w.connectors_found,
                emails_scheduled=w.emails_scheduled,
                created_at=w.created_at.isoformat(),
                updated_at=w.updated_at.isoformat(),
                completed_at=w.completed_at.isoformat() if w.completed_at else None,
                error_message=w.error_message,
                metadata=w.metadata
            ))

        return {
            "workflows": workflow_responses,
            "total_count": len(workflow_responses)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list corporate workflows: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list corporate workflows: {str(e)}")

@router.post("/corporate/{workflow_id}/cancel")
async def cancel_corporate_workflow(
    workflow_id: str,
    reason: str = Form(default="Cancelled by user", description="Reason for cancellation"),
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Cancel an active corporate workflow"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)
        _require_corporate_connect(int(tenant_scope))

        # Verify workflow exists and user has access
        workflow = await workflow_coordinator.get_workflow_status(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Corporate workflow not found")

        if workflow.tenant_id != str(tenant_scope):
            raise HTTPException(status_code=403, detail="Access denied to this workflow")

        # Cancel workflow
        success = await workflow_coordinator.cancel_workflow(
            workflow_id=workflow_id,
            user_id=current_user["id"],
            reason=reason
        )

        if not success:
            raise HTTPException(status_code=400, detail="Corporate workflow could not be cancelled")

        # Get updated status
        updated_workflow = await workflow_coordinator.get_workflow_status(workflow_id)
        return CorporateWorkflowResponse(
            workflow_id=updated_workflow.workflow_id,
            organization_id=updated_workflow.organization_id,
            tenant_id=updated_workflow.tenant_id,
            user_id=updated_workflow.user_id,
            status=updated_workflow.status.value,
            stage=updated_workflow.stage,
            prospects_processed=updated_workflow.prospects_processed,
            connectors_found=updated_workflow.connectors_found,
            emails_scheduled=updated_workflow.emails_scheduled,
            created_at=updated_workflow.created_at.isoformat(),
            updated_at=updated_workflow.updated_at.isoformat(),
            completed_at=updated_workflow.completed_at.isoformat() if updated_workflow.completed_at else None,
            error_message=updated_workflow.error_message,
            metadata=updated_workflow.metadata
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel corporate workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel corporate workflow: {str(e)}")

@router.post("/corporate/{workflow_id}/retry")
async def retry_corporate_workflow(
    workflow_id: str,
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Retry a failed corporate workflow"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)
        _require_corporate_connect(int(tenant_scope))

        # Verify workflow exists and user has access
        workflow = await workflow_coordinator.get_workflow_status(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Corporate workflow not found")

        if workflow.tenant_id != str(tenant_scope):
            raise HTTPException(status_code=403, detail="Access denied to this workflow")

        if workflow.status != WorkflowStatus.FAILED:
            raise HTTPException(status_code=400, detail="Only failed workflows can be retried")

        # Retry workflow
        new_workflow = await workflow_coordinator.retry_failed_workflow(
            workflow_id=workflow_id,
            user_id=current_user["id"]
        )

        if not new_workflow:
            raise HTTPException(status_code=400, detail="Corporate workflow could not be retried")

        return CorporateWorkflowResponse(
            workflow_id=new_workflow.workflow_id,
            organization_id=new_workflow.organization_id,
            tenant_id=new_workflow.tenant_id,
            user_id=new_workflow.user_id,
            status=new_workflow.status.value,
            stage=new_workflow.stage,
            prospects_processed=new_workflow.prospects_processed,
            connectors_found=new_workflow.connectors_found,
            emails_scheduled=new_workflow.emails_scheduled,
            created_at=new_workflow.created_at.isoformat(),
            updated_at=new_workflow.updated_at.isoformat(),
            completed_at=new_workflow.completed_at.isoformat() if new_workflow.completed_at else None,
            error_message=new_workflow.error_message,
            metadata=new_workflow.metadata
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retry corporate workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retry corporate workflow: {str(e)}")

@router.get("/corporate/metrics/summary")
async def get_corporate_workflow_metrics(
    days: int = Query(30, description="Number of days for metrics"),
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Get corporate workflow execution metrics for the organization"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)
        _require_corporate_connect(int(tenant_scope))

        if days < 1 or days > 365:
            raise HTTPException(status_code=400, detail="Days must be between 1 and 365")

        metrics = await workflow_coordinator.get_workflow_metrics(
            organization_id=str(current_user.get("organization_id", tenant_scope)),
            tenant_id=str(tenant_scope),
            days=days
        )

        return CorporateWorkflowMetrics(**metrics)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get corporate workflow metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get corporate workflow metrics: {str(e)}")

# =============================================================================
# AI AGENT APPROVAL ENDPOINTS (September 2025)
# =============================================================================

class AIApprovalRequest(BaseModel):
    """AI approval request model"""
    request_id: str
    workflow_id: str
    agent_role: str
    decision_type: str
    confidence_score: float
    recommended_action: str
    reasoning: List[str]
    context: Dict[str, Any]
    urgency: str
    expires_at: str
    status: str

class AIApprovalResponse(BaseModel):
    """AI approval response model"""
    approved: bool
    reviewer_notes: Optional[str] = None

@router.get("/ai/approvals/pending")
async def get_pending_ai_approvals(
    workflow_id: Optional[str] = Query(None, description="Filter by workflow ID"),
    agent_role: Optional[str] = Query(None, description="Filter by agent role"),
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Get pending AI agent approval requests"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)
        _require_corporate_connect(int(tenant_scope))

        # Parse agent role filter
        role_filter = None
        if agent_role:
            try:
                role_filter = AgentRole(agent_role.lower())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid agent role: {agent_role}")

        # Get pending approvals
        pending_approvals = openai_agents_integration.get_pending_approvals(
            workflow_id=workflow_id,
            agent_role=role_filter
        )

        expected_tenant = str(tenant_scope)
        filtered_approvals = []
        for approval in pending_approvals:
            context_tenant = approval.context.get("tenant_id") if isinstance(approval.context, dict) else None
            metadata_tenant = None
            if hasattr(approval.decision, "metadata"):
                metadata_tenant = approval.decision.metadata.get("tenant_id") if isinstance(approval.decision.metadata, dict) else None

            context_tenant = str(context_tenant) if context_tenant is not None else None
            metadata_tenant = str(metadata_tenant) if metadata_tenant is not None else None

            if (
                context_tenant is not None and context_tenant == expected_tenant
            ) or (
                metadata_tenant is not None and metadata_tenant == expected_tenant
            ):
                filtered_approvals.append(approval)
            else:
                logger.debug(
                    "Skipping approval %s due to tenant scope mismatch (context=%s metadata=%s expected=%s)",
                    getattr(approval, "request_id", "unknown"),
                    context_tenant,
                    metadata_tenant,
                    expected_tenant,
                )

        # Convert to response format
        approval_responses = []
        for approval in filtered_approvals:
            approval_responses.append(AIApprovalRequest(
                request_id=approval.request_id,
                workflow_id=approval.workflow_id,
                agent_role=approval.agent_role.value,
                decision_type=approval.decision.decision_type.value,
                confidence_score=approval.decision.confidence_score,
                recommended_action=approval.decision.recommended_action,
                reasoning=approval.decision.reasoning,
                context=approval.context,
                urgency=approval.urgency,
                expires_at=approval.expires_at.isoformat(),
                status=approval.status
            ))

        return {
            "pending_approvals": approval_responses,
            "total_count": len(approval_responses)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get pending AI approvals: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get pending AI approvals: {str(e)}")

@router.post("/ai/approvals/{request_id}/approve")
async def approve_ai_decision(
    request_id: str,
    response: AIApprovalResponse,
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Approve or reject an AI agent decision"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        approval = openai_agents_integration.pending_approvals.get(request_id)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval request not found")

        expected_tenant = str(tenant_scope)
        context_tenant = approval.context.get("tenant_id") if isinstance(approval.context, dict) else None
        metadata_tenant = None
        if hasattr(approval.decision, "metadata"):
            metadata_tenant = approval.decision.metadata.get("tenant_id") if isinstance(approval.decision.metadata, dict) else None

        context_tenant = str(context_tenant) if context_tenant is not None else None
        metadata_tenant = str(metadata_tenant) if metadata_tenant is not None else None

        if expected_tenant not in {context_tenant, metadata_tenant}:
            logger.warning(
                "User %s attempted to process approval %s outside tenant scope %s (context=%s metadata=%s)",
                current_user.get("id"),
                request_id,
                expected_tenant,
                context_tenant,
                metadata_tenant,
            )
            raise HTTPException(status_code=403, detail="Access denied to this approval request")

        # Process the approval
        success = await openai_agents_integration.process_human_approval(
            request_id=request_id,
            approved=response.approved,
            reviewer_id=str(current_user["id"]),
            reviewer_notes=response.reviewer_notes
        )

        if not success:
            raise HTTPException(status_code=400, detail="Failed to process approval (may be expired or not found)")

        return {
            "success": True,
            "approved": response.approved,
            "processed_at": datetime.utcnow().isoformat(),
            "reviewer_id": current_user["id"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process AI approval: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process AI approval: {str(e)}")

@router.get("/ai/approvals/{request_id}")
async def get_ai_approval_details(
    request_id: str,
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Get detailed information about an AI approval request"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)

        # Find the approval request
        all_approvals = openai_agents_integration.get_pending_approvals()
        approval = next((a for a in all_approvals if a.request_id == request_id), None)

        if not approval:
            raise HTTPException(status_code=404, detail="Approval request not found")

        expected_tenant = str(tenant_scope)
        context_tenant = approval.context.get("tenant_id") if isinstance(approval.context, dict) else None
        metadata_tenant = None
        if hasattr(approval.decision, "metadata"):
            metadata_tenant = approval.decision.metadata.get("tenant_id") if isinstance(approval.decision.metadata, dict) else None

        context_tenant = str(context_tenant) if context_tenant is not None else None
        metadata_tenant = str(metadata_tenant) if metadata_tenant is not None else None

        if expected_tenant not in {context_tenant, metadata_tenant}:
            raise HTTPException(status_code=403, detail="Access denied to this approval request")

        # Return detailed approval information
        return AIApprovalRequest(
            request_id=approval.request_id,
            workflow_id=approval.workflow_id,
            agent_role=approval.agent_role.value,
            decision_type=approval.decision.decision_type.value,
            confidence_score=approval.decision.confidence_score,
            recommended_action=approval.decision.recommended_action,
            reasoning=approval.decision.reasoning,
            context=approval.context,
            urgency=approval.urgency,
            expires_at=approval.expires_at.isoformat(),
            status=approval.status
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get AI approval details: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get AI approval details: {str(e)}")

@router.get("/ai/agents/status")
async def get_ai_agents_status(
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Get status and availability of AI agents"""

    try:
        tenant_scope = _resolve_authorized_tenant(tenant_id, current_user)
        _require_corporate_connect(int(tenant_scope))
        # Check if OpenAI Agents SDK is available
        from ..services.openai_agents_2025_integration import OPENAI_AGENTS_AVAILABLE

        agent_status = {
            "sdk_available": OPENAI_AGENTS_AVAILABLE,
            "agents_initialized": len(openai_agents_integration.agents) > 0,
            "available_agents": [role.value for role in AgentRole],
            "pending_approvals_count": len(openai_agents_integration.pending_approvals),
            "integration_mode": "production" if OPENAI_AGENTS_AVAILABLE else "simulation"
        }

        if OPENAI_AGENTS_AVAILABLE:
            agent_status.update({
                "active_agents": list(openai_agents_integration.agents.keys()),
                "agent_models": "gpt-4o-2025-09-15",
                "reasoning_enabled": True,
                "human_approval_enabled": True
            })

        return agent_status

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get AI agents status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get AI agents status: {str(e)}")
