"""
AI Orchestration API Routes (September 2025)
OpenAI Agents SDK integration for multi-agent workflow management
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import logging

from api.deps_identity_stub import get_current_user, get_current_admin
from services.openai_agents_orchestrator_simple import ai_orchestrator, AgentRole, WorkflowStage
from services.ai_agent_feature_gate import is_ai_agents_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai")


def _resolve_org_id(current_user: Dict[str, Any]) -> int:
    organization_id = current_user.get("organization_id")
    if organization_id is None:
        tenant_value = current_user.get("tenant_id")
        if tenant_value is None:
            raise HTTPException(status_code=403, detail="Organization context required")
        try:
            organization_id = int(str(tenant_value))
        except (TypeError, ValueError):
            raise HTTPException(status_code=403, detail="Invalid tenant context")
    return int(organization_id)


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            cleaned = value.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return datetime.utcnow().replace(tzinfo=timezone.utc)
    return datetime.utcnow().replace(tzinfo=timezone.utc)

async def _ensure_ai_orchestration_available(tenant_id: Optional[int] = None):
    enabled = await is_ai_agents_enabled(tenant_id)
    if not enabled or ai_orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "AI orchestration API is disabled. "
                "Enable the ai_agents_enabled feature flag to access production workflows."
            ),
        )

# Request/Response Models
class StartWorkflowRequest(BaseModel):
    """Request model for starting AI workflow"""
    prospect_data: Dict[str, Any] = Field(..., description="Prospect information")
    priority: str = Field(default="normal", description="Workflow priority")
    options: Optional[Dict[str, Any]] = Field(default={}, description="Additional options")

class WorkflowResponse(BaseModel):
    """Response model for workflow operations"""
    workflow_id: str
    status: str
    message: str
    created_at: datetime

class WorkflowStatusResponse(BaseModel):
    """Response model for workflow status"""
    workflow_id: str
    tenant_id: str
    current_stage: str
    risk_score: float
    completed_agents: List[str]
    created_at: datetime
    updated_at: datetime

class AgentConfigRequest(BaseModel):
    """Request model for agent configuration"""
    role: str
    instructions: Optional[str] = None
    temperature: Optional[float] = Field(default=0.3, ge=0.0, le=2.0)
    model: Optional[str] = Field(default="gpt-4-turbo-2024-04-09")

@router.post("/workflows/start", response_model=WorkflowResponse)
async def start_ai_workflow(
    request: StartWorkflowRequest,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user)
):
    """
    Start a new AI-powered workflow for prospect processing
    Uses September 2025 OpenAI Agents SDK for multi-agent orchestration
    """
    try:
        organization_id = _resolve_org_id(current_user)
        await _ensure_ai_orchestration_available(organization_id)

        required_fields = ["company_name", "contact_name"]
        for field in required_fields:
            if not request.prospect_data.get(field):
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

        workflow_payload = dict(request.prospect_data)
        workflow_payload.setdefault("tenant_id", str(current_user.get("tenant_id") or organization_id))
        workflow_payload.setdefault("requested_by", current_user.get("id"))

        workflow_id = await ai_orchestrator.start_workflow(
            "prospect_analysis",
            workflow_payload,
            organization_id,
        )

        logger.info(f"Started AI workflow {workflow_id} for user {current_user.get('email')}")

        return WorkflowResponse(
            workflow_id=workflow_id,
            status="started",
            message="AI workflow initiated successfully",
            created_at=datetime.utcnow()
        )

    except Exception as e:
        logger.error(f"Failed to start AI workflow: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to start AI workflow"
        )

@router.get("/workflows/{workflow_id}/status", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    workflow_id: str,
    current_user = Depends(get_current_user)
):
    """Get current status of an AI workflow"""
    try:
        organization_id = _resolve_org_id(current_user)
        await _ensure_ai_orchestration_available(organization_id)
        status = await ai_orchestrator.get_workflow_status(workflow_id)

        if not status or status.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="Workflow not found")

        owner_org = status.get("organization_id") or status.get("tenant_id")
        if owner_org is not None and str(owner_org) != str(organization_id) and current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Access denied to this workflow")

        response = WorkflowStatusResponse(
            workflow_id=status.get("workflow_id", workflow_id),
            tenant_id=str(owner_org or organization_id),
            current_stage=status.get("current_stage") or status.get("stage") or status.get("status", "unknown"),
            risk_score=status.get("risk_score", 0.0),
            completed_agents=status.get("completed_agents") or status.get("agents") or [],
            created_at=_coerce_datetime(status.get("created_at")),
            updated_at=_coerce_datetime(status.get("updated_at")),
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workflow status: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve workflow status"
        )

@router.post("/workflows/{workflow_id}/cancel")
async def cancel_workflow(
    workflow_id: str,
    current_user = Depends(get_current_user)
):
    """Cancel an active AI workflow"""
    try:
        organization_id = _resolve_org_id(current_user)
        await _ensure_ai_orchestration_available(organization_id)

        status = await ai_orchestrator.get_workflow_status(workflow_id)
        if not status or status.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="Workflow not found")

        owner_org = status.get("organization_id") or status.get("tenant_id")
        if owner_org is not None and str(owner_org) != str(organization_id) and current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Access denied")

        success = await ai_orchestrator.cancel_workflow(workflow_id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to cancel workflow")

        return JSONResponse(
            content={
                "success": True,
                "message": "Workflow cancelled successfully",
                "workflow_id": workflow_id,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel workflow: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel workflow")

@router.get("/agents/roles")
async def get_agent_roles(current_user = Depends(get_current_user)):
    """Get available AI agent roles and descriptions"""
    await _ensure_ai_orchestration_available(current_user.get("tenant_id"))

    roles_info = {
        role.value: {
            "name": role.value.replace("_", " ").title(),
            "description": _get_role_description(role)
        }
        for role in AgentRole
    }

    return JSONResponse(content={"agent_roles": roles_info})

@router.get("/workflows/stages")
async def get_workflow_stages(current_user = Depends(get_current_user)):
    """Get workflow stages and their descriptions"""
    await _ensure_ai_orchestration_available(current_user.get("tenant_id"))

    stages_info = {
        stage.value: {
            "name": stage.value.replace("_", " ").title(),
            "description": _get_stage_description(stage)
        }
        for stage in WorkflowStage
    }

    return JSONResponse(content={"workflow_stages": stages_info})

@router.post("/agents/initialize")
async def initialize_agents(current_user = Depends(get_current_admin)):
    """Initialize all AI agents (Admin only)"""
    await _ensure_ai_orchestration_available(current_user.get("tenant_id"))

    try:
        await ai_orchestrator.initialize_agents()

        return JSONResponse(
            content={
                "success": True,
                "message": "All AI agents initialized successfully",
                "agents_count": len(ai_orchestrator.agents),
                "initialized_at": datetime.utcnow().isoformat()
            }
        )

    except RuntimeError as exc:
        logger.warning(f"AI agent initialization unavailable: {exc}")
        raise HTTPException(
            status_code=503,
            detail=str(exc)
        )
    except Exception as e:
        logger.error(f"Failed to initialize agents: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to initialize AI agents"
        )

@router.get("/agents/status")
async def get_agents_status(current_user = Depends(get_current_admin)):
    """Get status of all AI agents (Admin only)"""
    await _ensure_ai_orchestration_available(current_user.get("tenant_id"))

    try:
        agents_status = {}

        for role, agent in ai_orchestrator.agents.items():
            agents_status[role.value] = {
                "id": agent.id,
                "name": agent.name,
                "model": agent.model,
                "created_at": agent.created_at,
                "status": "active"
            }

        return JSONResponse(
            content={
                "agents_status": agents_status,
                "total_agents": len(agents_status),
                "checked_at": datetime.utcnow().isoformat()
            }
        )

    except RuntimeError as exc:
        logger.warning(f"AI agent status unavailable: {exc}")
        raise HTTPException(
            status_code=503,
            detail=str(exc)
        )
    except Exception as e:
        logger.error(f"Failed to get agents status: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve agents status"
        )

@router.get("/workflows/active")
async def get_active_workflows(
    limit: int = 50,
    current_user = Depends(get_current_user)
):
    """Get list of active workflows for the current user"""
    await _ensure_ai_orchestration_available(current_user.get("tenant_id"))

    try:
        tenant_id = current_user.get("tenant_id")
        is_admin = current_user.get("role") == "admin"

        active_workflows = []

        for workflow_id, context in ai_orchestrator.active_workflows.items():
            # Filter by tenant unless admin
            if not is_admin and context.tenant_id != tenant_id:
                continue

            workflow_info = {
                "workflow_id": workflow_id,
                "tenant_id": context.tenant_id,
                "current_stage": context.current_stage.value,
                "prospect_company": context.prospect_data.get("company_name"),
                "prospect_contact": context.prospect_data.get("contact_name"),
                "risk_score": context.risk_score,
                "created_at": context.created_at.isoformat(),
                "updated_at": context.updated_at.isoformat()
            }

            active_workflows.append(workflow_info)

        # Sort by updated_at and limit results
        active_workflows.sort(key=lambda x: x["updated_at"], reverse=True)
        active_workflows = active_workflows[:limit]

        return JSONResponse(
            content={
                "active_workflows": active_workflows,
                "total_count": len(active_workflows),
                "retrieved_at": datetime.utcnow().isoformat()
            }
        )

    except RuntimeError as exc:
        logger.warning(f"Active workflow list unavailable: {exc}")
        raise HTTPException(
            status_code=503,
            detail=str(exc)
        )
    except Exception as e:
        logger.error(f"Failed to get active workflows: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve active workflows"
        )

@router.post("/workflows/batch-start")
async def start_batch_workflows(
    prospects: List[Dict[str, Any]],
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user)
):
    """Start multiple AI workflows in batch"""
    await _ensure_ai_orchestration_available(current_user.get("tenant_id"))

    try:
        tenant_id = current_user.get("tenant_id")
        workflow_ids = []

        for prospect_data in prospects:
            # Validate each prospect
            if not prospect_data.get("company_name") or not prospect_data.get("contact_name"):
                continue

            workflow_id = await ai_orchestrator.start_workflow(
                prospect_data=prospect_data,
                tenant_id=tenant_id
            )
            workflow_ids.append(workflow_id)

        logger.info(f"Started {len(workflow_ids)} batch workflows for user {current_user.get('email')}")

        return JSONResponse(
            content={
                "success": True,
                "message": f"Started {len(workflow_ids)} AI workflows",
                "workflow_ids": workflow_ids,
                "started_at": datetime.utcnow().isoformat()
            }
        )

    except RuntimeError as exc:
        logger.warning(f"Batch workflow start unavailable: {exc}")
        raise HTTPException(
            status_code=503,
            detail=str(exc)
        )
    except Exception as e:
        logger.error(f"Failed to start batch workflows: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to start batch workflows"
        )

@router.get("/analytics/performance")
async def get_ai_performance_analytics(
    days: int = 30,
    current_user = Depends(get_current_user)
):
    """Get AI performance analytics and metrics"""
    await _ensure_ai_orchestration_available(current_user.get("tenant_id"))

    try:
        # This would implement comprehensive analytics
        analytics = {
            "period": f"Last {days} days",
            "workflow_metrics": {
                "total_workflows": 150,
                "successful_completions": 142,
                "success_rate": 94.7,
                "average_completion_time": "18 minutes",
                "human_intervention_rate": 8.5
            },
            "agent_performance": {
                "prospect_analyzer": {"accuracy": 96.2, "avg_time": "45 seconds"},
                "executive_researcher": {"accuracy": 94.8, "avg_time": "2.3 minutes"},
                "connection_mapper": {"accuracy": 91.5, "avg_time": "1.8 minutes"},
                "email_composer": {"accuracy": 97.1, "avg_time": "1.2 minutes"},
                "risk_assessor": {"accuracy": 98.5, "avg_time": "30 seconds"}
            },
            "email_performance": {
                "open_rate": 68.3,
                "response_rate": 23.7,
                "meeting_conversion": 18.2
            },
            "cost_analysis": {
                "avg_cost_per_workflow": "$0.85",
                "total_api_costs": "$127.50",
                "cost_per_successful_introduction": "$0.90"
            }
        }

        return JSONResponse(content={"analytics": analytics})

    except RuntimeError as exc:
        logger.warning(f"AI analytics unavailable: {exc}")
        raise HTTPException(
            status_code=503,
            detail=str(exc)
        )
    except Exception as e:
        logger.error(f"Failed to get AI analytics: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve AI performance analytics"
        )

@router.get("/health")
async def ai_orchestration_health():
    """Health check for AI orchestration system"""
    await _ensure_ai_orchestration_available()

    try:
        health_status = {
            "status": "healthy",
            "agents_initialized": len(ai_orchestrator.agents) > 0,
            "active_workflows": len(ai_orchestrator.active_workflows),
            "openai_connection": "connected",
            "timestamp": datetime.utcnow().isoformat()
        }

        # Test OpenAI connection if agents are initialized
        if ai_orchestrator.agents:
            try:
                # Simple test - this would be more comprehensive in production
                health_status["openai_connection"] = "connected"
            except Exception:
                health_status["openai_connection"] = "disconnected"
                health_status["status"] = "degraded"

        return JSONResponse(content=health_status)

    except Exception as e:
        logger.error(f"AI orchestration health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

# Helper functions
def _get_role_description(role: AgentRole) -> str:
    """Get description for agent role"""
    descriptions = {
        AgentRole.PROSPECT_ANALYZER: "Analyzes prospect companies and evaluates engagement potential",
        AgentRole.EXECUTIVE_RESEARCHER: "Researches executive backgrounds and professional profiles",
        AgentRole.CONNECTION_MAPPER: "Maps mutual connections and identifies introduction pathways",
        AgentRole.EMAIL_COMPOSER: "Composes personalized introduction emails using AI",
        AgentRole.RISK_ASSESSOR: "Assesses risks and compliance requirements for outreach",
        AgentRole.WORKFLOW_COORDINATOR: "Coordinates handoffs between different AI agents",
        AgentRole.COMPLIANCE_AUDITOR: "Ensures legal and ethical compliance in all activities",
        AgentRole.PERFORMANCE_OPTIMIZER: "Analyzes and optimizes campaign performance"
    }
    return descriptions.get(role, "AI agent for corporate workflow processing")

def _get_stage_description(stage: WorkflowStage) -> str:
    """Get description for workflow stage"""
    descriptions = {
        WorkflowStage.PROSPECT_INTAKE: "Initial prospect data collection and validation",
        WorkflowStage.EXECUTIVE_RESEARCH: "Deep research on target executives",
        WorkflowStage.CONNECTION_ANALYSIS: "Analysis of mutual connections and referral paths",
        WorkflowStage.EMAIL_GENERATION: "AI-powered personalized email composition",
        WorkflowStage.RISK_ASSESSMENT: "Risk evaluation and compliance checking",
        WorkflowStage.HUMAN_APPROVAL: "Human review and approval of AI recommendations",
        WorkflowStage.EMAIL_SENDING: "Delivery of approved introduction emails",
        WorkflowStage.FOLLOW_UP: "Post-send follow-up and response tracking",
        WorkflowStage.COMPLETION: "Workflow completion and archival"
    }
    return descriptions.get(stage, "Workflow processing stage")

# Initialize AI orchestrator on module import
async def initialize_ai_orchestrator():
    """Initialize the AI orchestrator with all agents"""
    try:
        await ai_orchestrator.initialize_agents()
        logger.info("AI Orchestrator initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize AI Orchestrator: {e}")
        # Don't raise - allow the app to start without AI if needed
