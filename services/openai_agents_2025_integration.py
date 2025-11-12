"""
OpenAI Agents SDK Integration (September 2025)
Advanced AI agents with reasoning, function calling, and human-in-the-loop workflows
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, asdict
from enum import Enum

try:
    # October 2025 OpenAI Agents SDK - correct import structure
    from agents import (
        Agent, Tool, FunctionTool, RunResult, OpenAIProvider
    )
    OPENAI_AGENTS_AVAILABLE = True
except ImportError:
    # Fallback for development environments
    OPENAI_AGENTS_AVAILABLE = False
    class Agent: pass
    class Tool: pass
    class FunctionTool: pass
    class RunResult: pass
    class OpenAIProvider: pass

from .audit_logging_service import audit_logger, AuditEventType, AuditSeverity

logger = logging.getLogger(__name__)

class AgentRole(Enum):
    """AI Agent roles for corporate workflow"""
    PROSPECT_ANALYZER = "prospect_analyzer"
    LINKEDIN_STRATEGIST = "linkedin_strategist"
    CONNECTION_EVALUATOR = "connection_evaluator"
    EMAIL_COMPOSER = "email_composer"
    WORKFLOW_COORDINATOR = "workflow_coordinator"

class AgentDecisionType(Enum):
    """Types of decisions agents can make"""
    AUTOMATIC = "automatic"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required"
    CONFIDENCE_THRESHOLD = "confidence_threshold"

@dataclass
class AgentDecision:
    """Represents an AI agent decision"""
    agent_role: AgentRole
    decision_type: AgentDecisionType
    reasoning: List[str]
    confidence_score: float
    recommended_action: str
    alternatives: List[str]
    requires_approval: bool
    metadata: Dict[str, Any]
    created_at: datetime

@dataclass
class ApprovalRequest:
    """Human approval request from AI agent"""
    request_id: str
    workflow_id: str
    agent_role: AgentRole
    decision: AgentDecision
    context: Dict[str, Any]
    urgency: str  # low, medium, high, critical
    requested_by: str
    expires_at: datetime
    status: str = "pending"  # pending, approved, rejected, expired

class OpenAIAgents2025Integration:
    """Integration with September 2025 OpenAI Agents SDK for corporate workflows"""

    def __init__(self, openai_api_key: Optional[str], organization_id: Optional[str] = None):
        self.openai_api_key = openai_api_key
        self.organization_id = organization_id
        # Enforce primary model selection (default to GPT-4.1)
        self.primary_model = os.getenv("PRIMARY_MODEL", "gpt-4.1").strip() or "gpt-4.1"

        if not OPENAI_AGENTS_AVAILABLE:
            logger.warning("OpenAI Agents SDK not available. Running in simulation mode.")
            self.client = None
            self.agents = {}
            return

        if not openai_api_key:
            logger.warning("OPENAI_API_KEY not configured for Agents SDK. Running in simulation mode.")
            self.client = None
            self.agents = {}
            return

        # Initialize OpenAI Agents provider
        self.client = OpenAIProvider(
            api_key=openai_api_key,
            organization=organization_id
        )

        # Initialize corporate workflow agents
        self.agents = {}
        self._initialize_corporate_agents()

        # Approval tracking
        self.pending_approvals: Dict[str, ApprovalRequest] = {}

    def _initialize_corporate_agents(self):
        """Initialize specialized AI agents for corporate workflow"""

        if not OPENAI_AGENTS_AVAILABLE:
            logger.info("Simulating agent initialization")
            return

        # For now, just create basic agent placeholders
        # TODO: Implement full agent configuration when needed
        try:
            # Create simple tools for prospect analysis
            def analyze_company_profile(company_name: str, industry: str, employee_count: int) -> str:
                return f"Analysis for {company_name} in {industry} with {employee_count} employees"

            def identify_decision_makers(company_name: str, department: str) -> str:
                return f"Decision makers identified for {company_name} in {department}"

            # Create basic agents with minimal configuration
            prospect_analyzer = Agent(
                name="ProspectAnalyzer",
                instructions="You are an expert prospect analyzer for B2B corporate introductions.",
                tools=[
                    FunctionTool(analyze_company_profile, description="Analyze company profile data"),
                    FunctionTool(identify_decision_makers, description="Identify key decision makers")
                ]
            )

            linkedin_strategist = Agent(
                name="LinkedInStrategist",
                instructions="You are a LinkedIn networking strategist specializing in warm introductions."
            )

            email_composer = Agent(
                name="EmailComposer",
                instructions="You are an expert email composer for B2B introductions and corporate outreach."
            )

            self.agents[AgentRole.PROSPECT_ANALYZER] = prospect_analyzer
            self.agents[AgentRole.LINKEDIN_STRATEGIST] = linkedin_strategist
            self.agents[AgentRole.EMAIL_COMPOSER] = email_composer

            logger.info("Successfully initialized OpenAI Agents 2025 for corporate workflow")

        except Exception as e:
            logger.error(f"Failed to initialize OpenAI Agents: {e}")
            self.agents = {}

    async def analyze_prospects(
        self,
        prospects_data: List[Dict[str, Any]],
        workflow_id: str,
        organization_id: str,
        tenant_id: str
    ) -> List[AgentDecision]:
        """Use AI to analyze prospects and recommend engagement strategies"""

        if not OPENAI_AGENTS_AVAILABLE:
            return self._simulate_prospect_analysis(prospects_data)

        agent = self.agents.get(AgentRole.PROSPECT_ANALYZER)
        if not agent:
            raise Exception("Prospect Analyzer agent not available")

        decisions = []

        for prospect in prospects_data:
            try:
                # Call agent with prospect data
                response = await agent.process_async(
                    message=f"Analyze this prospect for B2B engagement strategy: {json.dumps(prospect)}",
                    context={
                        "workflow_id": workflow_id,
                        "organization_id": organization_id,
                        "prospect_data": prospect
                    }
                )

                # Extract reasoning and decision
                decision = AgentDecision(
                    agent_role=AgentRole.PROSPECT_ANALYZER,
                    decision_type=AgentDecisionType.CONFIDENCE_THRESHOLD,
                    reasoning=response.reasoning_steps,
                    confidence_score=response.confidence,
                    recommended_action=response.recommendation,
                    alternatives=response.alternatives or [],
                    requires_approval=response.confidence < 0.6,
                    metadata={
                        "prospect_id": prospect.get("id"),
                        "company": prospect.get("company"),
                        "processing_time": response.processing_time
                    },
                    created_at=datetime.now(timezone.utc)
                )

                decisions.append(decision)

                # Log decision for audit
                await audit_logger.log_event(
                    event_type=AuditEventType.AI_DECISION_MADE,
                    actor_type='ai_agent',
                    actor_id='prospect_analyzer',
                    target_type='prospect',
                    target_id=prospect.get("id", "unknown"),
                    tenant_id=tenant_id,
                    metadata={
                        "model_id": self.primary_model,
                        "confidence": response.confidence,
                        "recommendation": response.recommendation,
                        "requires_approval": decision.requires_approval
                    }
                )

                # Request human approval if needed
                if decision.requires_approval:
                    await self._request_human_approval(
                        workflow_id=workflow_id,
                        agent_role=AgentRole.PROSPECT_ANALYZER,
                        decision=decision,
                        context={"prospect": prospect},
                        urgency="medium"
                    )

            except Exception as e:
                logger.error(f"Error analyzing prospect {prospect.get('id')}: {e}")
                continue

        return decisions

    async def evaluate_connections(
        self,
        connector_data: Dict[str, Any],
        target_data: Dict[str, Any],
        workflow_id: str,
        organization_id: str,
        tenant_id: str
    ) -> AgentDecision:
        """Use AI to evaluate mutual connections and recommend introduction strategy"""

        if not OPENAI_AGENTS_AVAILABLE:
            return self._simulate_connection_evaluation(connector_data, target_data)

        agent = self.agents.get(AgentRole.LINKEDIN_STRATEGIST)
        if not agent:
            raise Exception("LinkedIn Strategist agent not available")

        try:
            response = await agent.process_async(
                message=f"""
                Evaluate this mutual connection for a warm introduction:
                Connector: {json.dumps(connector_data)}
                Target: {json.dumps(target_data)}

                Provide a detailed strategy for leveraging this connection.
                """,
                context={
                    "workflow_id": workflow_id,
                    "organization_id": organization_id,
                    "connector_data": connector_data,
                    "target_data": target_data
                }
            )

            decision = AgentDecision(
                agent_role=AgentRole.LINKEDIN_STRATEGIST,
                decision_type=AgentDecisionType.CONFIDENCE_THRESHOLD,
                reasoning=response.reasoning_steps,
                confidence_score=response.confidence,
                recommended_action=response.recommendation,
                alternatives=response.alternatives or [],
                requires_approval=response.confidence < 0.7,
                metadata={
                    "connector_id": connector_data.get("id"),
                    "target_id": target_data.get("id"),
                    "connection_strength": response.metadata.get("connection_strength"),
                    "introduction_angle": response.metadata.get("introduction_angle")
                },
                created_at=datetime.now(timezone.utc)
            )

            # Log decision
            await audit_logger.log_event(
                event_type=AuditEventType.AI_DECISION_MADE,
                actor_type='ai_agent',
                actor_id='linkedin_strategist',
                target_type='connection_evaluation',
                target_id=f"{connector_data.get('id')}_{target_data.get('id')}",
                tenant_id=tenant_id,
                metadata={
                    "model_id": self.primary_model,
                    "confidence": response.confidence,
                    "recommendation": response.recommendation,
                    "connection_strength": response.metadata.get("connection_strength")
                }
            )

            return decision

        except Exception as e:
            logger.error(f"Error evaluating connection: {e}")
            raise

    async def compose_introduction_email(
        self,
        email_context: Dict[str, Any],
        workflow_id: str,
        organization_id: str,
        tenant_id: str
    ) -> AgentDecision:
        """Use AI to compose personalized introduction email"""

        if not OPENAI_AGENTS_AVAILABLE:
            return self._simulate_email_composition(email_context)

        agent = self.agents.get(AgentRole.EMAIL_COMPOSER)
        if not agent:
            raise Exception("Email Composer agent not available")

        try:
            response = await agent.process_async(
                message=f"""
                Compose a personalized introduction email with this context:
                {json.dumps(email_context)}

                Include:
                - Compelling subject line
                - Personalized greeting
                - Clear value proposition
                - Professional call-to-action
                """,
                context={
                    "workflow_id": workflow_id,
                    "organization_id": organization_id,
                    "email_context": email_context
                }
            )

            decision = AgentDecision(
                agent_role=AgentRole.EMAIL_COMPOSER,
                decision_type=AgentDecisionType.HUMAN_APPROVAL_REQUIRED,  # Always require approval for emails
                reasoning=response.reasoning_steps,
                confidence_score=response.confidence,
                recommended_action=response.recommendation,
                alternatives=response.alternatives or [],
                requires_approval=True,  # Always require human approval for emails
                metadata={
                    "email_subject": response.metadata.get("subject_line"),
                    "email_body": response.metadata.get("email_body"),
                    "tone_analysis": response.metadata.get("tone_analysis"),
                    "personalization_elements": response.metadata.get("personalization_elements")
                },
                created_at=datetime.now(timezone.utc)
            )

            # Always request approval for email content
            await self._request_human_approval(
                workflow_id=workflow_id,
                agent_role=AgentRole.EMAIL_COMPOSER,
                decision=decision,
                context=email_context,
                urgency="high"
            )

            # Log decision
            await audit_logger.log_event(
                event_type=AuditEventType.AI_DECISION_MADE,
                actor_type='ai_agent',
                actor_id='email_composer',
                target_type='email_composition',
                target_id=email_context.get("recipient_id", "unknown"),
                tenant_id=tenant_id,
                metadata={
                    "model_id": self.primary_model,
                    "confidence": response.confidence,
                    "requires_approval": True,
                    "subject_line": decision.metadata.get("email_subject", "")[:50] + "..."
                }
            )

            return decision

        except Exception as e:
            logger.error(f"Error composing email: {e}")
            raise

    async def _request_human_approval(
        self,
        workflow_id: str,
        agent_role: AgentRole,
        decision: AgentDecision,
        context: Dict[str, Any],
        urgency: str = "medium"
    ) -> str:
        """Request human approval for AI agent decision"""

        request_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)  # 24-hour expiry

        approval_request = ApprovalRequest(
            request_id=request_id,
            workflow_id=workflow_id,
            agent_role=agent_role,
            decision=decision,
            context=context,
            urgency=urgency,
            requested_by=f"ai_agent_{agent_role.value}",
            expires_at=expires_at
        )

        # Store approval request
        self.pending_approvals[request_id] = approval_request

        logger.info(f"Human approval requested for {agent_role.value} decision in workflow {workflow_id}")

        # In a real implementation, you would:
        # 1. Send notification to human reviewers
        # 2. Create dashboard entry for approval
        # 3. Set up webhook for approval response

        return request_id

    async def process_human_approval(
        self,
        request_id: str,
        approved: bool,
        reviewer_id: str,
        reviewer_notes: str = None
    ) -> bool:
        """Process human approval response"""

        if request_id not in self.pending_approvals:
            raise ValueError(f"Approval request {request_id} not found")

        approval_request = self.pending_approvals[request_id]

        # Check if expired
        if datetime.now(timezone.utc) > approval_request.expires_at:
            approval_request.status = "expired"
            return False

        # Update approval status
        approval_request.status = "approved" if approved else "rejected"

        # Log approval decision
        await audit_logger.log_event(
            event_type=AuditEventType.AI_APPROVAL_PROCESSED,
            actor_type='human',
            actor_id=reviewer_id,
            target_type='approval_request',
            target_id=request_id,
            tenant_id=approval_request.decision.metadata.get("tenant_id"),
            metadata={
                "model_id": getattr(self, "primary_model", None),
                "approved": approved,
                "agent_role": approval_request.agent_role.value,
                "workflow_id": approval_request.workflow_id,
                "reviewer_notes": reviewer_notes,
                "original_confidence": approval_request.decision.confidence_score
            }
        )

        logger.info(f"Approval request {request_id} {'approved' if approved else 'rejected'} by {reviewer_id}")

        # Remove from pending approvals
        del self.pending_approvals[request_id]

        return True

    def get_pending_approvals(
        self,
        workflow_id: str = None,
        agent_role: AgentRole = None
    ) -> List[ApprovalRequest]:
        """Get pending approval requests"""

        approvals = list(self.pending_approvals.values())

        if workflow_id:
            approvals = [a for a in approvals if a.workflow_id == workflow_id]

        if agent_role:
            approvals = [a for a in approvals if a.agent_role == agent_role]

        return approvals

    # Simulation methods for development/testing
    def _simulate_prospect_analysis(self, prospects_data: List[Dict[str, Any]]) -> List[AgentDecision]:
        """Simulate prospect analysis for development"""
        decisions = []

        for prospect in prospects_data:
            decision = AgentDecision(
                agent_role=AgentRole.PROSPECT_ANALYZER,
                decision_type=AgentDecisionType.CONFIDENCE_THRESHOLD,
                reasoning=[
                    f"Analyzed company size: {prospect.get('company', 'Unknown')}",
                    "High growth potential identified based on industry trends",
                    "Decision maker likely receptive to new partnerships"
                ],
                confidence_score=0.75,
                recommended_action="Proceed with warm introduction via mutual connection",
                alternatives=["Direct outreach", "Social media engagement"],
                requires_approval=False,
                metadata={
                    "prospect_id": prospect.get("id"),
                    "company": prospect.get("company"),
                    "simulated": True
                },
                created_at=datetime.now(timezone.utc)
            )
            decisions.append(decision)

        return decisions

    def _simulate_connection_evaluation(self, connector_data: Dict, target_data: Dict) -> AgentDecision:
        """Simulate connection evaluation for development"""
        return AgentDecision(
            agent_role=AgentRole.LINKEDIN_STRATEGIST,
            decision_type=AgentDecisionType.CONFIDENCE_THRESHOLD,
            reasoning=[
                "Strong mutual connection with shared professional background",
                "Recent interaction history suggests active relationship",
                "Connector well-positioned to make valuable introduction"
            ],
            confidence_score=0.82,
            recommended_action="Request warm introduction emphasizing mutual business interests",
            alternatives=["Wait for industry conference introduction", "LinkedIn message first"],
            requires_approval=False,
            metadata={
                "connector_id": connector_data.get("id"),
                "target_id": target_data.get("id"),
                "connection_strength": "strong",
                "simulated": True
            },
            created_at=datetime.now(timezone.utc)
        )

    def _simulate_email_composition(self, email_context: Dict) -> AgentDecision:
        """Simulate email composition for development"""
        return AgentDecision(
            agent_role=AgentRole.EMAIL_COMPOSER,
            decision_type=AgentDecisionType.HUMAN_APPROVAL_REQUIRED,
            reasoning=[
                "Crafted personalized subject line referencing mutual connection",
                "Emphasized clear value proposition for recipient",
                "Included specific call-to-action with easy next steps"
            ],
            confidence_score=0.88,
            recommended_action="Send personalized introduction email",
            alternatives=["Phone introduction", "Video message"],
            requires_approval=True,
            metadata={
                "email_subject": f"Introduction: {email_context.get('target_name', 'Prospect')} <> {email_context.get('requester_name', 'Team')}",
                "email_body": "Personalized email content would be generated here...",
                "tone_analysis": "Professional, warm, value-focused",
                "simulated": True
            },
            created_at=datetime.now(timezone.utc)
        )

# Global instance
from core.settings import settings  # Late import to avoid circular dependency

default_agent_key = (
    os.getenv("OPENAI_AGENTS_API_KEY")
    or settings.OPENAI_API_KEY
)
default_agent_org = os.getenv("OPENAI_AGENTS_ORG_ID") or os.getenv("OPENAI_ORGANIZATION")

openai_agents_integration = OpenAIAgents2025Integration(
    openai_api_key=default_agent_key,
    organization_id=default_agent_org
)

# Example usage
async def main():
    """Example usage of OpenAI Agents 2025 integration"""

    # Initialize with API key
    integration = OpenAIAgents2025Integration(
        openai_api_key="your-openai-api-key",
        organization_id="your-org-id"
    )

    # Analyze prospects
    prospects = [
        {
            "id": "prospect-1",
            "company": "TechStartup Inc",
            "industry": "SaaS",
            "employee_count": 50,
            "revenue": "$5M ARR"
        }
    ]

    decisions = await integration.analyze_prospects(
        prospects_data=prospects,
        workflow_id="workflow-123",
        organization_id="org-456",
        tenant_id="tenant-789"
    )

    print(f"AI analyzed {len(decisions)} prospects")
    for decision in decisions:
        print(f"Decision: {decision.recommended_action} (confidence: {decision.confidence_score})")

if __name__ == "__main__":
    asyncio.run(main())
