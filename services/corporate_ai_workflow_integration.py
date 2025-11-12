"""
Corporate AI Workflow Integration with OpenAI Agents SDK
Integrates AI agents with the corporate warm-intro workflow and approval system
"""

import asyncio
import logging
import json
from copy import deepcopy
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict
from enum import Enum
import uuid

from .openai_agents_orchestrator import OpenAIAgentsOrchestrator, WorkflowContext, AgentRole, WorkflowStage
from .approval_queue_service import (
    approval_queue_service,
    ApprovalPriority,
    ApprovalRequest,
    ApprovalType,
)
from .audit_logging_service import audit_logger, AuditEventType, AuditSeverity
from .message_queue_orchestrator import message_queue_orchestrator

logger = logging.getLogger(__name__)

class AIWorkflowDecision(Enum):
    """AI decision types requiring human approval"""
    EMAIL_CONTENT_APPROVAL = "email_content_approval"
    CONNECTOR_SELECTION = "connector_selection"
    RISK_OVERRIDE = "risk_override"
    TIMING_ADJUSTMENT = "timing_adjustment"
    CUSTOM_MESSAGE = "custom_message"

@dataclass
class AIDecisionContext:
    """Context for AI decisions requiring approval"""
    workflow_id: str
    organization_id: int
    decision_type: AIWorkflowDecision
    ai_recommendation: Dict[str, Any]
    confidence_score: float
    risk_factors: List[str]
    alternative_options: List[Dict[str, Any]]
    reasoning: str
    metadata: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['decision_type'] = self.decision_type.value
        return data

class CorporateAIWorkflowIntegration:
    """
    Integration layer between AI agents and corporate workflow
    Handles approval flows and human-in-the-loop decision making
    """

    def __init__(self):
        try:
            self.orchestrator = OpenAIAgentsOrchestrator()
        except RuntimeError as exc:
            logger.warning("AI orchestrator disabled: %s", exc)
            self.orchestrator = None
        self.pending_approvals: Dict[str, AIDecisionContext] = {}

    async def initiate_prospect_workflow(
        self,
        organization_id: int,
        prospect_data: Dict[str, Any],
        workflow_type: str = "full_analysis",
        requested_by: int = None,
        priority: str = "normal"
    ) -> str:
        """
        Initiate AI-powered prospect workflow with approval gates

        Args:
            organization_id: Organization/tenant ID
            prospect_data: Prospect information
            workflow_type: Type of workflow to execute
            requested_by: User who initiated the workflow
            priority: Workflow priority level

        Returns:
            workflow_id: Unique identifier for the workflow
        """

        workflow_id = str(uuid.uuid4())

        if not self.orchestrator:
            raise RuntimeError(
                "AI orchestrator not available. Enable the ai_agents_enabled feature flag "
                "and configure OpenAI agents."
            )

        try:
            # Create workflow context
            context = WorkflowContext(
                workflow_id=workflow_id,
                organization_id=organization_id,
                prospect_data=prospect_data,
                requested_by=requested_by or organization_id,
                priority=priority
            )

            # Log workflow initiation
            await audit_logger.log_event(
                organization_id=organization_id,
                actor_type="ai_system",
                action="workflow_initiated",
                target_type="introduction_workflow",
                target_id=workflow_id,
                payload={
                    "prospect_name": prospect_data.get('name', 'Unknown'),
                    "workflow_type": workflow_type,
                    "requested_by": requested_by
                },
                severity=AuditSeverity.INFO
            )

            await self.orchestrator.initialize_agents(organization_id)

            # Start AI workflow
            workflow_result = await self.orchestrator.execute_workflow(
                context=context,
                workflow_type=workflow_type
            )

            # Process workflow result and create approval requests
            approval_requests = await self._process_workflow_result(
                workflow_id, organization_id, workflow_result, context
            )

            return workflow_id

        except Exception as e:
            logger.error(f"Failed to initiate prospect workflow: {e}")

            # Log failure
            await audit_logger.log_event(
                organization_id=organization_id,
                actor_type="ai_system",
                action="workflow_failed",
                target_type="introduction_workflow",
                target_id=workflow_id,
                payload={
                    "error": str(e),
                    "prospect_name": prospect_data.get('name', 'Unknown')
                },
                severity=AuditSeverity.ERROR
            )

            raise

    async def _process_workflow_result(
        self,
        workflow_id: str,
        organization_id: int,
        workflow_result: Dict[str, Any],
        context: WorkflowContext
    ) -> List[str]:
        """Process AI workflow result and create approval requests"""

        approval_ids = []

        # Extract decisions requiring approval
        decisions = workflow_result.get('approval_required', [])

        for decision_data in decisions:
            decision_context = AIDecisionContext(
                workflow_id=workflow_id,
                organization_id=organization_id,
                decision_type=AIWorkflowDecision(decision_data['type']),
                ai_recommendation=decision_data['recommendation'],
                confidence_score=decision_data.get('confidence', 0.5),
                risk_factors=decision_data.get('risks', []),
                alternative_options=decision_data.get('alternatives', []),
                reasoning=decision_data.get('reasoning', ''),
                metadata=decision_data.get('metadata', {})
            )

            # Create approval request
            approval_id = await self._create_approval_request(decision_context, context)
            approval_ids.append(approval_id)

            # Store decision context for later processing
            self.pending_approvals[approval_id] = decision_context

        return approval_ids

    async def _create_approval_request(
        self,
        decision_context: AIDecisionContext,
        workflow_context: WorkflowContext
    ) -> str:
        """Create human approval request for AI decision"""

        # Determine approval priority based on risk and confidence
        priority = self._calculate_approval_priority(
            decision_context.confidence_score,
            decision_context.risk_factors
        )

        # Create descriptive title and description
        title = self._generate_approval_title(decision_context)
        description = self._generate_approval_description(decision_context)

        # Create approval request
        approval_id = await approval_queue_service.create_approval_request(
            organization_id=decision_context.organization_id,
            request_type=ApprovalType.EMAIL_CAMPAIGN,  # Map decision type to approval type
            title=title,
            description=description,
            requested_by=workflow_context.requested_by,
            context_data={
                "workflow_id": decision_context.workflow_id,
                "decision_context": decision_context.to_dict(),
                "ai_recommendation": decision_context.ai_recommendation,
                "confidence_score": decision_context.confidence_score,
                "risk_factors": decision_context.risk_factors,
                "alternative_options": decision_context.alternative_options
            },
            workflow_id=decision_context.workflow_id,
            priority=priority,
            risk_score=self._calculate_risk_score(decision_context.risk_factors)
        )

        # Log approval request creation
        await audit_logger.log_event(
            organization_id=decision_context.organization_id,
            actor_type="ai_system",
            action="approval_request_created",
            target_type="ai_decision",
            target_id=approval_id,
            payload={
                "workflow_id": decision_context.workflow_id,
                "decision_type": decision_context.decision_type.value,
                "confidence_score": decision_context.confidence_score
            },
            severity=AuditSeverity.INFO
        )

        return approval_id

    def _calculate_approval_priority(
        self,
        confidence_score: float,
        risk_factors: List[str]
    ) -> ApprovalPriority:
        """Calculate approval priority based on AI confidence and risk factors"""

        if confidence_score < 0.3 or len(risk_factors) > 3:
            return ApprovalPriority.HIGH
        elif confidence_score < 0.7 or len(risk_factors) > 1:
            return ApprovalPriority.NORMAL
        else:
            return ApprovalPriority.LOW

    def _calculate_risk_score(self, risk_factors: List[str]) -> float:
        """Calculate numeric risk score from risk factors"""
        risk_weights = {
            'high_value_prospect': 0.8,
            'sensitive_industry': 0.6,
            'first_contact': 0.4,
            'complex_message': 0.3,
            'unusual_timing': 0.2
        }

        total_risk = sum(risk_weights.get(factor, 0.1) for factor in risk_factors)
        return min(total_risk, 1.0)

    def _generate_approval_title(self, decision_context: AIDecisionContext) -> str:
        """Generate human-readable approval title"""
        decision_titles = {
            AIWorkflowDecision.EMAIL_CONTENT_APPROVAL: "Email Content Review Required",
            AIWorkflowDecision.CONNECTOR_SELECTION: "Connector Selection Approval",
            AIWorkflowDecision.RISK_OVERRIDE: "Risk Override Request",
            AIWorkflowDecision.TIMING_ADJUSTMENT: "Timing Adjustment Approval",
            AIWorkflowDecision.CUSTOM_MESSAGE: "Custom Message Review"
        }

        base_title = decision_titles.get(
            decision_context.decision_type,
            "AI Decision Approval Required"
        )

        # Add confidence indicator
        confidence_text = f"({decision_context.confidence_score:.0%} confidence)"

        return f"{base_title} {confidence_text}"

    def _generate_approval_description(self, decision_context: AIDecisionContext) -> str:
        """Generate detailed approval description"""

        description = f"""
AI Workflow Decision Review

Decision Type: {decision_context.decision_type.value}
Confidence Score: {decision_context.confidence_score:.1%}

AI Reasoning:
{decision_context.reasoning}

Recommended Action:
{json.dumps(decision_context.ai_recommendation, indent=2)}
"""

        if decision_context.risk_factors:
            description += f"\nRisk Factors:\n"
            for risk in decision_context.risk_factors:
                description += f"• {risk}\n"

        if decision_context.alternative_options:
            description += f"\nAlternative Options:\n"
            for i, option in enumerate(decision_context.alternative_options, 1):
                description += f"{i}. {json.dumps(option, indent=2)}\n"

        return description.strip()

    async def handle_approval_response(
        self,
        approval_id: str,
        organization_id: int,
        decision: str,
        feedback: Dict[str, Any] = None,
        decided_by: int = None
    ) -> Dict[str, Any]:
        """
        Handle human approval response and continue workflow

        Args:
            approval_id: Approval request ID
            organization_id: Organization ID
            decision: 'approved', 'rejected', or 'modified'
            feedback: Human feedback and modifications
            decided_by: User who made the decision

        Returns:
            Result of approval processing
        """

        decision_context = self.pending_approvals.get(approval_id)
        if not decision_context:
            raise ValueError(f"No pending decision found for approval {approval_id}")

        workflow_id = decision_context.workflow_id

        try:
            # Log approval decision
            await audit_logger.log_event(
                organization_id=organization_id,
                actor_type="human",
                action=f"approval_{decision}",
                target_type="ai_decision",
                target_id=approval_id,
                payload={
                    "workflow_id": workflow_id,
                    "decision_type": decision_context.decision_type.value,
                    "decided_by": decided_by,
                    "feedback": feedback
                },
                severity=AuditSeverity.INFO
            )

            # Process decision
            if decision == "approved":
                # Continue workflow with AI recommendation
                result = await self._continue_workflow_approved(
                    workflow_id, organization_id, decision_context
                )

                # Clean up pending approval
                self.pending_approvals.pop(approval_id, None)

                return {
                    "status": "approved",
                    "workflow_id": workflow_id,
                    "continued": True
                }

            elif decision == "rejected":
                # Stop workflow or mark as requiring manual intervention
                await self._handle_workflow_rejection(
                    workflow_id, organization_id, decision_context, feedback
                )

                # Clean up pending approval
                self.pending_approvals.pop(approval_id, None)

                return {
                    "status": "rejected",
                    "workflow_id": workflow_id,
                    "feedback": feedback
                }

            elif decision == "modified":
                # Handle modifications and re-queue if needed
                modified_workflow = await self._apply_human_modifications(
                    workflow_id, organization_id, approval_request.payload, feedback
                )

                return modified_workflow

        except Exception as e:
            logger.error(f"Failed to handle approval response for {approval_id}: {e}")
            raise

    async def _apply_human_modifications(
        self,
        workflow_id: str,
        organization_id: int,
        original_workflow: Dict[str, Any],
        modifications: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply human modifications to AI-generated workflow and re-queue for approval."""

        def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
            for key, value in patch.items():
                if isinstance(value, dict) and isinstance(base.get(key), dict):
                    _deep_merge(base[key], value)
                else:
                    base[key] = value
            return base

        merged_workflow = deepcopy(original_workflow)
        updates = (
            modifications.get("updates")
            or modifications.get("workflow_updates")
            or modifications.get("workflow")
            or {}
        )
        if isinstance(updates, dict) and updates:
            _deep_merge(merged_workflow, updates)

        metadata = modifications.get("metadata") or {}
        reviewer_id = (
            metadata.get("reviewer_id")
            or modifications.get("reviewer_id")
            or metadata.get("user_id")
            or modifications.get("requested_by")
            or original_workflow.get("requested_by")
            or original_workflow.get("approval_decision", {}).get("requested_by")
        )

        try:
            requested_by = int(reviewer_id) if reviewer_id is not None else 0
        except (TypeError, ValueError):
            requested_by = 0

        priority_hint = (
            modifications.get("priority")
            or metadata.get("priority")
            or original_workflow.get("approval_decision", {}).get("approval_urgency")
        )
        priority = (
            ApprovalPriority.HIGH
            if isinstance(priority_hint, str) and priority_hint.lower() in {"high", "urgent"}
            else ApprovalPriority.NORMAL
        )

        risk_score = modifications.get("risk_score")
        if risk_score is None:
            risk_score = (
                original_workflow.get("risk_assessment", {}).get("overall_risk_score")
            )

        merged_workflow.setdefault("human_feedback", {})
        merged_workflow["human_feedback"].update(
            {
                "modifications": modifications,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Persist the revision so downstream services see the updated state
        try:
            from .workflow_persistence_service import (
                workflow_persistence_service,
                WorkflowStatus,
            )

            await workflow_persistence_service.update_workflow_state(
                workflow_id,
                results={
                    "latest_revision": merged_workflow,
                    "human_feedback": modifications,
                },
                is_paused=True,
                pause_reason="Awaiting re-approval after human edits",
                status=WorkflowStatus.PENDING,
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist human modifications for %s: %s",
                workflow_id,
                exc,
            )

        if workflow_id in message_queue_orchestrator.active_workflows:
            active_state = message_queue_orchestrator.active_workflows[workflow_id]
            active_state["latest_revision"] = merged_workflow
            active_state["status"] = "pending_reapproval"

        company_name = (
            merged_workflow.get("prospect_analysis", {})
            .get("company_analysis", {})
            .get("name")
            or merged_workflow.get("prospect_analysis", {}).get("company")
            or "target prospect"
        )

        description = modifications.get(
            "description",
            "Updated workflow requires confirmation after human edits.",
        )
        title = modifications.get(
            "title",
            f"Revised introduction workflow for {company_name}",
        )

        context_payload = {
            "workflow_id": workflow_id,
            "original_workflow": original_workflow,
            "modified_workflow": merged_workflow,
            "modifications": modifications,
        }

        try:
            new_approval_id = await approval_queue_service.create_approval_request(
                organization_id=organization_id,
                request_type=ApprovalType.EMAIL_CAMPAIGN,
                title=title,
                description=description,
                requested_by=requested_by or organization_id,
                context_data=context_payload,
                workflow_id=workflow_id,
                priority=priority,
                risk_score=risk_score,
            )
        except Exception as exc:
            logger.error(
                "Failed to queue revised workflow %s for approval: %s",
                workflow_id,
                exc,
            )
            raise

        await audit_logger.log_event(
            organization_id=organization_id,
            actor_type="human",
            action="workflow_modified",
            target_type="introduction_workflow",
            target_id=workflow_id,
            payload={
                "approval_id": new_approval_id,
                "modifications": modifications,
            },
            severity=AuditSeverity.INFO,
        )

        return {
            "status": "modified_and_pending",
            "workflow_id": workflow_id,
            "approval_id": new_approval_id,
            "modifications_applied": merged_workflow,
            "requires_re_approval": True,
        }

# Global service instance
corporate_ai_workflow = CorporateAIWorkflowIntegration()