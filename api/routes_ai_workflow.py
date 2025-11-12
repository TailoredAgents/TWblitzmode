"""
AI Workflow API Routes
FastAPI endpoints for OpenAI Agents SDK integration with corporate workflows
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from core.roles import is_admin, normalize_role

from .deps import get_current_user
from services.corporate_ai_workflow_integration import corporate_ai_workflow
from services.ai_agent_feature_gate import is_ai_agents_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-workflow", tags=["ai-workflow"])

async def _ensure_ai_workflow_available(tenant_id: Optional[int] = None):
    enabled = await is_ai_agents_enabled(tenant_id)
    if not enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "AI workflow orchestration is disabled. "
                "Enable the ai_agents_enabled feature flag to run multi-agent workflows."
            ),
        )

# Request/Response Models
class StartAIWorkflowRequest(BaseModel):
    prospect_data: Dict[str, Any] = Field(..., description="Prospect information")
    connector_data: List[Dict[str, Any]] = Field(..., description="Available connectors")
    workflow_preferences: Optional[Dict[str, Any]] = Field(default=None, description="User preferences")
    priority: str = Field(default="normal", description="Workflow priority")

class AIWorkflowResponse(BaseModel):
    workflow_id: str
    status: str
    approval_id: Optional[str] = None
    ai_recommendation: Optional[str] = None
    estimated_completion: Optional[str] = None
    next_steps: str

class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., description="approved, rejected, or modified")
    feedback: Optional[Dict[str, Any]] = Field(default=None, description="Human feedback")
    modifications: Optional[Dict[str, Any]] = Field(default=None, description="Requested modifications")

class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    status: str
    created_at: str
    current_stage: Optional[str] = None
    ai_insights: Optional[Dict[str, Any]] = None
    approval_status: Optional[str] = None
    execution_results: Optional[Dict[str, Any]] = None

@router.post("/start", response_model=AIWorkflowResponse)
async def start_ai_workflow(
    request: StartAIWorkflowRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Start a new AI-powered introduction workflow"""

    try:
        organization_id = current_user["tenant_id"]  # Using tenant_id as organization_id
        user_id = current_user["id"]
        await _ensure_ai_workflow_available(organization_id)

        logger.info(f"Starting AI workflow for organization {organization_id}, user {user_id}")

        # Validate request
        if not request.prospect_data:
            raise HTTPException(status_code=400, detail="Prospect data is required")

        if not request.connector_data:
            raise HTTPException(status_code=400, detail="At least one connector is required")

        # Start the AI workflow
        result = await corporate_ai_workflow.process_introduction_workflow(
            organization_id=organization_id,
            prospect_data=request.prospect_data,
            connector_data=request.connector_data,
            user_id=user_id,
            workflow_preferences=request.workflow_preferences
        )

        # Map result to response
        response = AIWorkflowResponse(
            workflow_id=result["workflow_id"],
            status=result["status"],
            approval_id=result.get("approval_id"),
            ai_recommendation=result.get("ai_recommendation"),
            estimated_completion=result.get("estimated_review_time"),
            next_steps=result.get("next_steps", "Workflow in progress")
        )

        logger.info(f"AI workflow {response.workflow_id} started with status: {response.status}")
        return response

    except RuntimeError as exc:
        logger.warning(f"AI workflow unavailable: {exc}")
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as e:
        logger.error(f"Failed to start AI workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start AI workflow: {str(e)}")

@router.get("/status/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get the current status of an AI workflow"""

    try:
        organization_id = current_user["tenant_id"]
        await _ensure_ai_workflow_available(organization_id)

        # Get workflow status from the orchestrator
        status = await corporate_ai_workflow.get_workflow_status(workflow_id)

        if not status:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Verify organization ownership
        if status.get("organization_id") != organization_id:
            raise HTTPException(status_code=403, detail="Access denied to this workflow")

        return WorkflowStatusResponse(
            workflow_id=workflow_id,
            status=status["status"],
            created_at=status["created_at"].isoformat(),
            current_stage=status.get("current_stage"),
            ai_insights=status.get("ai_insights"),
            approval_status=status.get("approval_status"),
            execution_results=status.get("execution_results")
        )

    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.warning(f"AI workflow status unavailable: {exc}")
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as e:
        logger.error(f"Failed to get workflow status for {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve workflow status")

@router.post("/approval/{approval_id}/respond")
async def respond_to_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Respond to an AI workflow approval request"""

    try:
        user_id = current_user["id"]
        organization_id = current_user["tenant_id"]
        await _ensure_ai_workflow_available(organization_id)

        logger.info(f"Processing approval response for {approval_id} by user {user_id}")

        # Validate decision
        if request.decision not in ["approved", "rejected", "modified"]:
            raise HTTPException(
                status_code=400,
                detail="Decision must be 'approved', 'rejected', or 'modified'"
            )

        # Process the approval response
        result = await corporate_ai_workflow.handle_approval_response(
            approval_id=approval_id,
            decision=request.decision,
            feedback={
                "user_id": user_id,
                "organization_id": organization_id,
                "decision_time": datetime.now().isoformat(),
                "feedback": request.feedback,
                "modifications": request.modifications
            }
        )

        logger.info(f"Approval {approval_id} processed with decision: {request.decision}")
        return result

    except RuntimeError as exc:
        logger.warning(f"AI approval handling unavailable: {exc}")
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as e:
        logger.error(f"Failed to process approval response for {approval_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process approval: {str(e)}")

@router.get("/approvals/pending")
async def get_pending_approvals(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get pending approval requests for the organization"""

    try:
        organization_id = current_user["tenant_id"]
        await _ensure_ai_workflow_available(organization_id)

        # Get pending approvals from the approval queue service
        from services.approval_queue_service import approval_queue_service

        pending_approvals = await approval_queue_service.get_pending_approvals(
            organization_id=organization_id,
            approval_type="EMAIL_CAMPAIGN"
        )

        # Format response
        formatted_approvals = []
        for approval in pending_approvals:
            formatted_approvals.append({
                "approval_id": approval.id,
                "title": approval.title,
                "description": approval.description,
                "priority": approval.priority,
                "requested_by": approval.requested_by,
                "created_at": approval.created_at.isoformat(),
                "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
                "ai_recommendation": approval.payload.get("approval_decision", {}).get("recommended_action"),
                "confidence_score": approval.payload.get("analysis", {}).get("confidence_score"),
                "risk_score": approval.payload.get("risk_assessment", {}).get("overall_risk_score"),
                "prospect_info": {
                    "company": approval.payload.get("prospect_analysis", {}).get("company_analysis", {}).get("name"),
                    "connector_count": len(approval.payload.get("connectors", []))
                }
            })

        return {
            "pending_count": len(formatted_approvals),
            "approvals": formatted_approvals
        }

    except RuntimeError as exc:
        logger.warning(f"AI approval queue unavailable: {exc}")
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as e:
        logger.error(f"Failed to get pending approvals: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve pending approvals")

@router.get("/insights/performance")
async def get_ai_performance_insights(
    current_user: Dict[str, Any] = Depends(get_current_user),
    days: int = 30
):
    """Get AI workflow performance insights"""

    try:
        organization_id = current_user["tenant_id"]

        # Metrics pipeline not yet implemented for AI workflows
        raise HTTPException(status_code=503, detail="AI performance insights are not available")

    except Exception as e:
        logger.error(f"Failed to get AI performance insights: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve AI insights")

@router.post("/configure/thresholds")
async def configure_ai_thresholds(
    thresholds: Dict[str, float],
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Configure AI approval thresholds for the organization"""

    try:
        organization_id = current_user["tenant_id"]
        user_role = normalize_role(current_user.get("role"))

        # Verify user has admin permissions
        if not is_admin(user_role):
            raise HTTPException(status_code=403, detail="Admin permissions required")

        # Validate thresholds
        required_thresholds = [
            "high_confidence_auto_approve",
            "medium_confidence_review",
            "low_confidence_reject"
        ]

        for threshold in required_thresholds:
            if threshold not in thresholds:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required threshold: {threshold}"
                )

            if not 0.0 <= thresholds[threshold] <= 1.0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Threshold {threshold} must be between 0.0 and 1.0"
                )

        # Update configuration
        corporate_ai_workflow.approval_thresholds.update(thresholds)

        # Log configuration change
        from services.audit_logging_service import audit_logger, AuditSeverity
        await audit_logger.log_event(
            organization_id=organization_id,
            actor_type="user",
            actor_id=current_user["id"],
            action="ai_thresholds_updated",
            target_type="ai_configuration",
            target_id=f"org_{organization_id}",
            payload={"new_thresholds": thresholds},
            severity=AuditSeverity.INFO
        )

        return {
            "message": "AI thresholds updated successfully",
            "thresholds": corporate_ai_workflow.approval_thresholds
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to configure AI thresholds: {e}")
        raise HTTPException(status_code=500, detail="Failed to update AI configuration")

@router.get("/templates/email")
async def get_ai_email_templates(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get AI-generated email templates for the organization"""

    try:
        organization_id = current_user["tenant_id"]

        # This would retrieve organization-specific email templates
        # For now, return standard templates
        templates = {
            "introduction_templates": [
                {
                    "id": "warm_intro_standard",
                    "name": "Standard Warm Introduction",
                    "description": "Professional warm introduction template",
                    "template": "Hi {connector_name},\n\nI hope this email finds you well...",
                    "ai_optimized": True,
                    "success_rate": 0.85
                },
                {
                    "id": "warm_intro_mutual",
                    "name": "Mutual Connection Focus",
                    "description": "Emphasizes mutual connections",
                    "template": "Hi {connector_name},\n\nI noticed we both know {mutual_names}...",
                    "ai_optimized": True,
                    "success_rate": 0.78
                }
            ],
            "follow_up_templates": [
                {
                    "id": "follow_up_gentle",
                    "name": "Gentle Follow-up",
                    "description": "Soft follow-up for non-responders",
                    "template": "Hi {connector_name},\n\nI wanted to follow up...",
                    "ai_optimized": True,
                    "success_rate": 0.65
                }
            ]
        }

        return templates

    except Exception as e:
        logger.error(f"Failed to get AI email templates: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve email templates")
