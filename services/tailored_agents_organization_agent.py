"""
Tailored Agents Organization Agent - OpenAI Agents SDK Integration with Human-in-the-Loop Approval

This service implements the AI orchestration layer for the corporate warm introduction platform,
providing intelligent workflow coordination with human oversight for sensitive operations.

Features:
- OpenAI Agents SDK integration (September 2025 features)
- Human-in-the-loop approval workflow
- Multi-service orchestration
- Intelligent decision making and escalation
- Real-time approval queue management
- Comprehensive audit logging
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
import traceback

try:
    import openai
    from openai import OpenAI
    # Note: OpenAI Agents SDK features may require latest OpenAI library version (September 2025+)
    from openai.agents import Agent, AgentConfig, Message, Tool, ToolCall
except ImportError as e:
    # Fallback implementation without OpenAI Agents SDK
    OpenAI = None
    Agent = None

import httpx
import asyncpg
from redis import Redis
import boto3
from botocore.exceptions import ClientError

from .ingestion_service import ProspectIngestionService as IngestionService
from .executive_lookup_service import ExecutiveLookupService
from .mutuals_orchestrator_service import MutualsOrchestratorService
from .scoring_service import ConnectorScoringService as ScoringService
from .email_enrichment_service import EmailEnrichmentService
from .corporate_scheduler_service import CorporateSchedulerService
from api.db_core import get_connection, execute_tenant, query_tenant

logger = logging.getLogger(__name__)

class WorkflowAction(Enum):
    PROSPECT_INGESTION = "prospect_ingestion"
    EXECUTIVE_LOOKUP = "executive_lookup"
    MUTUAL_DISCOVERY = "mutual_discovery"
    CONNECTION_SCORING = "connection_scoring"
    EMAIL_ENRICHMENT = "email_enrichment"
    EMAIL_SCHEDULING = "email_scheduling"
    FINAL_APPROVAL = "final_approval"

class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    TIMEOUT = "timeout"

@dataclass
class WorkflowContext:
    workflow_id: str
    tenant_id: str
    organization_id: str
    integration_set_id: str
    initiated_by: str
    current_action: WorkflowAction
    context_data: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

@dataclass
class ApprovalRequest:
    approval_id: str
    workflow_id: str
    tenant_id: str
    action: WorkflowAction
    description: str
    risk_score: float
    context: Dict[str, Any]
    requires_approval: bool
    auto_approve_threshold: float
    timeout_minutes: int
    status: ApprovalStatus
    requested_at: datetime
    responded_at: Optional[datetime] = None
    approver_id: Optional[str] = None
    rejection_reason: Optional[str] = None

class TailoredAgentsOrganizationAgent:
    def __init__(self,
                 openai_api_key: str,
                 database_url: str,
                 redis_url: str = "redis://localhost:6379/0",
                 aws_region: str = "us-west-2"):

        if OpenAI is None or Agent is None:
            raise ImportError("OpenAI Agents SDK is required but not available. Please upgrade OpenAI library.")

        self.openai_client = OpenAI(api_key=openai_api_key)
        self.database_url = database_url
        self.redis = Redis.from_url(redis_url)
        self.aws_region = aws_region

        # Initialize service dependencies
        self.ingestion_service = IngestionService(database_url)
        self.executive_lookup = ExecutiveLookupService(database_url)
        self.mutuals_orchestrator = MutualsOrchestratorService(database_url)
        self.scoring_service = ScoringService(database_url)
        self.email_enrichment = EmailEnrichmentService(database_url)
        self.scheduler_service = CorporateSchedulerService(database_url)

        # Agent configuration
        try:
            # Defer to centralized settings for model lock
            from core.settings import settings as _settings
            _primary_model = _settings.OPENAI_MODEL
        except Exception:
            _primary_model = "gpt-4.1"
        self.agent_config = AgentConfig(
            name="VouchLink AI Organization Agent",
            model=_primary_model,
            instructions=self._get_agent_instructions(),
            tools=self._get_agent_tools(),
            temperature=0.1,
            max_iterations=10
        )

        self.agent = Agent(config=self.agent_config)

        # Risk assessment thresholds
        self.auto_approve_threshold = 0.3  # Auto-approve actions below this risk score
        self.escalation_threshold = 0.8    # Escalate actions above this risk score

    def _get_agent_instructions(self) -> str:
        return """
        You are the VouchLink AI Organization Agent, an AI orchestrator for corporate warm introduction workflows.

        Your responsibilities:
        1. Coordinate multi-service workflows for prospect processing
        2. Make intelligent decisions about workflow progression
        3. Assess risk levels for human approval requirements
        4. Escalate sensitive operations for human oversight
        5. Optimize for efficiency while maintaining security

        Key principles:
        - Always prioritize data security and tenant isolation
        - Request human approval for high-risk operations
        - Provide clear explanations for all recommendations
        - Optimize costs while maintaining quality
        - Handle errors gracefully with fallback strategies

        Available workflow actions:
        - prospect_ingestion: Import and validate prospect data
        - executive_lookup: Enrich prospects with executive data
        - mutual_discovery: Find mutual connections via LinkedIn
        - connection_scoring: Score and rank potential connectors
        - email_enrichment: Find and validate email addresses
        - email_scheduling: Generate and schedule outreach emails
        - final_approval: Request final approval before email sends
        """

    def _get_agent_tools(self) -> List[Tool]:
        return [
            Tool(
                name="assess_workflow_risk",
                description="Assess the risk level of a workflow action",
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": [a.value for a in WorkflowAction]},
                        "context": {"type": "object"},
                        "prospect_count": {"type": "integer"},
                        "organization_tier": {"type": "string"}
                    },
                    "required": ["action", "context"]
                },
                function=self._assess_workflow_risk
            ),
            Tool(
                name="request_human_approval",
                description="Request human approval for high-risk operations",
                parameters={
                    "type": "object",
                    "properties": {
                        "workflow_id": {"type": "string"},
                        "action": {"type": "string"},
                        "description": {"type": "string"},
                        "risk_score": {"type": "number"},
                        "timeout_minutes": {"type": "integer", "default": 60}
                    },
                    "required": ["workflow_id", "action", "description", "risk_score"]
                },
                function=self._request_human_approval
            ),
            Tool(
                name="execute_workflow_action",
                description="Execute a workflow action after approval",
                parameters={
                    "type": "object",
                    "properties": {
                        "workflow_id": {"type": "string"},
                        "action": {"type": "string"},
                        "parameters": {"type": "object"}
                    },
                    "required": ["workflow_id", "action", "parameters"]
                },
                function=self._execute_workflow_action
            )
        ]

    async def start_workflow(self,
                           tenant_id: str,
                           organization_id: str,
                           integration_set_id: str,
                           initiated_by: str,
                           initial_action: WorkflowAction,
                           context_data: Dict[str, Any]) -> str:
        """Start a new corporate workflow with AI orchestration"""

        workflow_id = str(uuid.uuid4())

        workflow_context = WorkflowContext(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            organization_id=organization_id,
            integration_set_id=integration_set_id,
            initiated_by=initiated_by,
            current_action=initial_action,
            context_data=context_data,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        try:
            # Store workflow context
            await self._store_workflow_context(workflow_context)

            # Create agent thread for this workflow
            thread = await self.agent.create_thread()

            # Store thread ID for workflow
            await self._store_workflow_thread(workflow_id, thread.id)

            # Start AI orchestration
            initial_message = f"""
            New corporate warm introduction workflow initiated:

            Workflow ID: {workflow_id}
            Organization: {organization_id}
            Action: {initial_action.value}
            Context: {json.dumps(context_data, indent=2)}

            Please assess this workflow and recommend next steps.
            Consider risk levels and approval requirements.
            """

            response = await self.agent.send_message(
                thread_id=thread.id,
                message=initial_message
            )

            logger.info(f"Workflow {workflow_id} started with AI response: {response.content}")

            # Process AI recommendations
            await self._process_agent_response(workflow_id, response)

            return workflow_id

        except Exception as e:
            logger.error(f"Failed to start workflow {workflow_id}: {e}")
            await self._log_audit_event(
                tenant_id, "workflow_error",
                {"workflow_id": workflow_id, "error": str(e)}
            )
            raise

    async def continue_workflow(self, workflow_id: str, approval_response: Optional[Dict] = None):
        """Continue workflow execution after approval or completion of current step"""

        try:
            workflow_context = await self._get_workflow_context(workflow_id)
            if not workflow_context:
                raise ValueError(f"Workflow {workflow_id} not found")

            thread_id = await self._get_workflow_thread(workflow_id)

            # Prepare continuation message
            if approval_response:
                message = f"""
                Approval response received:
                Status: {approval_response.get('status')}
                Comments: {approval_response.get('comments', 'None')}

                Please proceed with the next workflow step.
                """
            else:
                message = "Current workflow step completed. Please recommend next action."

            response = await self.agent.send_message(thread_id=thread_id, message=message)
            await self._process_agent_response(workflow_id, response)

        except Exception as e:
            logger.error(f"Failed to continue workflow {workflow_id}: {e}")
            raise

    async def _process_agent_response(self, workflow_id: str, response):
        """Process AI agent response and execute recommended actions"""

        try:
            # Handle tool calls from agent
            if hasattr(response, 'tool_calls') and response.tool_calls:
                for tool_call in response.tool_calls:
                    await self._execute_tool_call(workflow_id, tool_call)

            # Log agent decision
            await self._log_audit_event(
                workflow_id, "agent_decision",
                {"response": response.content, "tool_calls": len(response.tool_calls) if response.tool_calls else 0}
            )

        except Exception as e:
            logger.error(f"Error processing agent response for workflow {workflow_id}: {e}")
            raise

    async def _execute_tool_call(self, workflow_id: str, tool_call: ToolCall):
        """Execute a tool call from the AI agent"""

        tool_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        if tool_name == "assess_workflow_risk":
            result = await self._assess_workflow_risk(**arguments)
        elif tool_name == "request_human_approval":
            result = await self._request_human_approval(workflow_id, **arguments)
        elif tool_name == "execute_workflow_action":
            result = await self._execute_workflow_action(**arguments)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Send tool result back to agent
        thread_id = await self._get_workflow_thread(workflow_id)
        await self.agent.send_tool_result(
            thread_id=thread_id,
            tool_call_id=tool_call.id,
            result=json.dumps(result)
        )

    async def _assess_workflow_risk(self, action: str, context: Dict, **kwargs) -> Dict:
        """Assess risk level for a workflow action"""

        risk_factors = {
            "base_action_risk": {
                WorkflowAction.PROSPECT_INGESTION.value: 0.1,
                WorkflowAction.EXECUTIVE_LOOKUP.value: 0.2,
                WorkflowAction.MUTUAL_DISCOVERY.value: 0.4,
                WorkflowAction.CONNECTION_SCORING.value: 0.1,
                WorkflowAction.EMAIL_ENRICHMENT.value: 0.3,
                WorkflowAction.EMAIL_SCHEDULING.value: 0.7,
                WorkflowAction.FINAL_APPROVAL.value: 0.9
            }.get(action, 0.5),

            "volume_multiplier": min(kwargs.get('prospect_count', 1) / 100, 2.0),
            "organization_tier_risk": {
                "enterprise": 0.8,
                "premium": 0.5,
                "standard": 0.2
            }.get(kwargs.get('organization_tier', 'standard'), 0.3),

            "context_risk": 0.1 if context.get('external_apis_required') else 0.0
        }

        # Calculate composite risk score
        base_risk = risk_factors["base_action_risk"]
        volume_adjustment = base_risk * risk_factors["volume_multiplier"] * 0.3
        tier_adjustment = risk_factors["organization_tier_risk"] * 0.2
        context_adjustment = risk_factors["context_risk"]

        total_risk = min(base_risk + volume_adjustment + tier_adjustment + context_adjustment, 1.0)

        return {
            "risk_score": total_risk,
            "requires_approval": total_risk > self.auto_approve_threshold,
            "requires_escalation": total_risk > self.escalation_threshold,
            "risk_factors": risk_factors,
            "recommendation": self._get_risk_recommendation(total_risk)
        }

    def _get_risk_recommendation(self, risk_score: float) -> str:
        if risk_score < 0.3:
            return "Low risk - proceed automatically"
        elif risk_score < 0.6:
            return "Medium risk - request standard approval"
        elif risk_score < 0.8:
            return "High risk - request senior approval with detailed review"
        else:
            return "Critical risk - escalate to executive team with full audit trail"

    async def _request_human_approval(self, workflow_id: str, action: str, description: str,
                                    risk_score: float, timeout_minutes: int = 60) -> Dict:
        """Request human approval for workflow action"""

        approval_id = str(uuid.uuid4())
        workflow_context = await self._get_workflow_context(workflow_id)

        approval_request = ApprovalRequest(
            approval_id=approval_id,
            workflow_id=workflow_id,
            tenant_id=workflow_context.tenant_id,
            action=WorkflowAction(action),
            description=description,
            risk_score=risk_score,
            context=workflow_context.context_data,
            requires_approval=True,
            auto_approve_threshold=self.auto_approve_threshold,
            timeout_minutes=timeout_minutes,
            status=ApprovalStatus.PENDING,
            requested_at=datetime.now(timezone.utc)
        )

        # Store approval request
        await self._store_approval_request(approval_request)

        # Send to approval queue (Redis pub/sub)
        await self._publish_approval_request(approval_request)

        # Log approval request
        await self._log_audit_event(
            workflow_context.tenant_id, "approval_requested",
            {"approval_id": approval_id, "action": action, "risk_score": risk_score}
        )

        return {
            "approval_id": approval_id,
            "status": "pending",
            "timeout_at": (datetime.now(timezone.utc) + timedelta(minutes=timeout_minutes)).isoformat()
        }

    async def _execute_workflow_action(self, workflow_id: str, action: str, parameters: Dict) -> Dict:
        """Execute a workflow action after approval"""

        workflow_context = await self._get_workflow_context(workflow_id)
        action_enum = WorkflowAction(action)

        try:
            result = None

            if action_enum == WorkflowAction.PROSPECT_INGESTION:
                result = await self._execute_prospect_ingestion(workflow_context, parameters)
            elif action_enum == WorkflowAction.EXECUTIVE_LOOKUP:
                result = await self._execute_executive_lookup(workflow_context, parameters)
            elif action_enum == WorkflowAction.MUTUAL_DISCOVERY:
                result = await self._execute_mutual_discovery(workflow_context, parameters)
            elif action_enum == WorkflowAction.CONNECTION_SCORING:
                result = await self._execute_connection_scoring(workflow_context, parameters)
            elif action_enum == WorkflowAction.EMAIL_ENRICHMENT:
                result = await self._execute_email_enrichment(workflow_context, parameters)
            elif action_enum == WorkflowAction.EMAIL_SCHEDULING:
                result = await self._execute_email_scheduling(workflow_context, parameters)
            elif action_enum == WorkflowAction.FINAL_APPROVAL:
                result = await self._execute_final_approval(workflow_context, parameters)

            # Update workflow context
            workflow_context.current_action = action_enum
            workflow_context.updated_at = datetime.now(timezone.utc)
            await self._update_workflow_context(workflow_context)

            # Log successful execution
            await self._log_audit_event(
                workflow_context.tenant_id, "action_executed",
                {"workflow_id": workflow_id, "action": action, "result_summary": str(result)[:200]}
            )

            return {"status": "completed", "result": result}

        except Exception as e:
            logger.error(f"Failed to execute {action} for workflow {workflow_id}: {e}")
            await self._log_audit_event(
                workflow_context.tenant_id, "action_failed",
                {"workflow_id": workflow_id, "action": action, "error": str(e)}
            )
            raise

    async def _execute_prospect_ingestion(self, context: WorkflowContext, params: Dict) -> Dict:
        """Execute prospect data ingestion"""
        return await self.ingestion_service.process_prospects_batch(
            context.tenant_id, context.organization_id, params.get('prospects', [])
        )

    async def _execute_executive_lookup(self, context: WorkflowContext, params: Dict) -> Dict:
        """Execute executive data lookup"""
        return await self.executive_lookup.enrich_prospects_batch(
            context.tenant_id, params.get('prospect_ids', [])
        )

    async def _execute_mutual_discovery(self, context: WorkflowContext, params: Dict) -> Dict:
        """Execute mutual connections discovery"""
        return await self.mutuals_orchestrator.discover_mutuals_batch(
            context.tenant_id,
            context.integration_set_id,
            params.get('prospect_ids', []),
            phantombuster_approval_id=params.get('phantombuster_approval_id'),
        )

    async def _execute_connection_scoring(self, context: WorkflowContext, params: Dict) -> Dict:
        """Execute connection scoring"""
        return await self.scoring_service.score_connections_batch(
            context.tenant_id, params.get('prospect_ids', [])
        )

    async def _execute_email_enrichment(self, context: WorkflowContext, params: Dict) -> Dict:
        """Execute email address enrichment"""
        return await self.email_enrichment.enrich_emails_batch(
            context.tenant_id, params.get('prospect_connector_ids', [])
        )

    async def _execute_email_scheduling(self, context: WorkflowContext, params: Dict) -> Dict:
        """Execute email scheduling"""
        return await self.scheduler_service.schedule_outreach_batch(
            context.tenant_id, context.organization_id, params.get('prospect_connector_ids', [])
        )

    async def _execute_final_approval(self, context: WorkflowContext, params: Dict) -> Dict:
        """Execute final approval before email sends"""
        # This would implement final human review of generated emails
        return {"status": "pending_final_review", "email_jobs": params.get('email_jobs', [])}

    # Database operations
    async def _store_workflow_context(self, context: WorkflowContext):
        """Store workflow context in database"""
        async with get_connection(self.database_url) as conn:
            await conn.execute("""
                INSERT INTO workflow_contexts (
                    workflow_id, tenant_id, organization_id, integration_set_id,
                    initiated_by, current_action, context_data, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """, context.workflow_id, context.tenant_id, context.organization_id,
                context.integration_set_id, context.initiated_by, context.current_action.value,
                json.dumps(context.context_data), context.created_at, context.updated_at)

    async def _get_workflow_context(self, workflow_id: str) -> Optional[WorkflowContext]:
        """Get workflow context from database"""
        async with get_connection(self.database_url) as conn:
            row = await conn.fetchrow("""
                SELECT * FROM workflow_contexts WHERE workflow_id = $1
            """, workflow_id)

            if row:
                return WorkflowContext(
                    workflow_id=row['workflow_id'],
                    tenant_id=row['tenant_id'],
                    organization_id=row['organization_id'],
                    integration_set_id=row['integration_set_id'],
                    initiated_by=row['initiated_by'],
                    current_action=WorkflowAction(row['current_action']),
                    context_data=json.loads(row['context_data']),
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                )
        return None

    async def _update_workflow_context(self, context: WorkflowContext):
        """Update workflow context in database"""
        async with get_connection(self.database_url) as conn:
            await conn.execute("""
                UPDATE workflow_contexts SET
                current_action = $2, context_data = $3, updated_at = $4
                WHERE workflow_id = $1
            """, context.workflow_id, context.current_action.value,
                json.dumps(context.context_data), context.updated_at)

    async def _store_approval_request(self, request: ApprovalRequest):
        """Store approval request in database"""
        async with get_connection(self.database_url) as conn:
            await conn.execute("""
                INSERT INTO approval_requests (
                    approval_id, workflow_id, tenant_id, action, description,
                    risk_score, context, requires_approval, auto_approve_threshold,
                    timeout_minutes, status, requested_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """, request.approval_id, request.workflow_id, request.tenant_id,
                request.action.value, request.description, request.risk_score,
                json.dumps(request.context), request.requires_approval,
                request.auto_approve_threshold, request.timeout_minutes,
                request.status.value, request.requested_at)

    async def _store_workflow_thread(self, workflow_id: str, thread_id: str):
        """Store OpenAI thread ID for workflow"""
        key = f"workflow:thread:{workflow_id}"
        self.redis.setex(key, 86400, thread_id)  # 24 hour TTL

    async def _get_workflow_thread(self, workflow_id: str) -> str:
        """Get OpenAI thread ID for workflow"""
        key = f"workflow:thread:{workflow_id}"
        thread_id = self.redis.get(key)
        if thread_id:
            return thread_id.decode('utf-8')
        raise ValueError(f"Thread not found for workflow {workflow_id}")

    async def _publish_approval_request(self, request: ApprovalRequest):
        """Publish approval request to Redis and WebSocket for real-time UI updates"""
        try:
            # Publish to Redis pub/sub
            channel = f"approvals:{request.tenant_id}"
            message = json.dumps(asdict(request), default=str)
            self.redis.publish(channel, message)

            # Also publish directly via WebSocket manager if available
            try:
                from api.routes_approvals import publish_approval_request
                await publish_approval_request(asdict(request))
            except ImportError:
                # WebSocket manager not available
                pass
        except Exception as e:
            logger.error(f"Failed to publish approval request: {e}")

    async def _log_audit_event(self, tenant_id: str, event_type: str, details: Dict):
        """Log audit event for compliance and monitoring"""
        async with get_connection(self.database_url) as conn:
            await conn.execute("""
                INSERT INTO audit_events (tenant_id, event_type, details, created_at)
                VALUES ($1, $2, $3, $4)
            """, tenant_id, event_type, json.dumps(details), datetime.now(timezone.utc))

    # Public API methods
    async def get_pending_approvals(self, tenant_id: str) -> List[Dict]:
        """Get all pending approval requests for a tenant"""
        async with get_connection(self.database_url) as conn:
            rows = await conn.fetch("""
                SELECT * FROM approval_requests
                WHERE tenant_id = $1 AND status = 'pending'
                ORDER BY requested_at ASC
            """, tenant_id)

            return [dict(row) for row in rows]

    async def respond_to_approval(self, approval_id: str, approver_id: str,
                                status: str, comments: str = None) -> bool:
        """Respond to an approval request"""
        try:
            async with get_connection(self.database_url) as conn:
                # Update approval request
                await conn.execute("""
                    UPDATE approval_requests SET
                    status = $2, approver_id = $3, responded_at = $4, rejection_reason = $5
                    WHERE approval_id = $1
                """, approval_id, status, approver_id, datetime.now(timezone.utc), comments)

                # Get workflow ID to continue workflow
                row = await conn.fetchrow("""
                    SELECT workflow_id, tenant_id FROM approval_requests WHERE approval_id = $1
                """, approval_id)

                if row:
                    workflow_id = row['workflow_id']
                    tenant_id = row['tenant_id']

                    # Log approval response
                    await self._log_audit_event(
                        tenant_id, "approval_responded",
                        {"approval_id": approval_id, "status": status, "approver": approver_id}
                    )

                    # Continue workflow if approved
                    if status == ApprovalStatus.APPROVED.value:
                        await self.continue_workflow(workflow_id, {
                            "status": status,
                            "comments": comments,
                            "approver": approver_id
                        })

                    return True

        except Exception as e:
            logger.error(f"Failed to respond to approval {approval_id}: {e}")

        return False

    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict]:
        """Get current workflow status and progress"""
        context = await self._get_workflow_context(workflow_id)
        if not context:
            return None

        # Get pending approvals for this workflow
        async with get_connection(self.database_url) as conn:
            pending_approvals = await conn.fetch("""
                SELECT approval_id, action, description, risk_score, requested_at
                FROM approval_requests
                WHERE workflow_id = $1 AND status = 'pending'
            """, workflow_id)

        return {
            "workflow_id": workflow_id,
            "current_action": context.current_action.value,
            "created_at": context.created_at.isoformat(),
            "updated_at": context.updated_at.isoformat(),
            "pending_approvals": [dict(row) for row in pending_approvals],
            "context_summary": {
                "organization_id": context.organization_id,
                "initiated_by": context.initiated_by,
                "total_prospects": len(context.context_data.get('prospect_ids', []))
            }
        }
