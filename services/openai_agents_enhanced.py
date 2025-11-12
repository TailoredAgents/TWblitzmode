#!/usr/bin/env python3
"""
Enhanced OpenAI Agents SDK Integration - September 2025
Real integration with human-in-the-loop approval and advanced workflow capabilities
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

logger = logging.getLogger(__name__)

# Provisioning
from services.agent_provisioning_service import (
    agent_provisioning_service,
    ProvisionedAgent,
)
try:
    from services.agent_logger import agent_logger, AgentEventType
except ImportError:  # pragma: no cover - optional dependency
    agent_logger = None
    AgentEventType = None
from services.email_service import email_service
from services.global_analytics_service import global_analytics_service
from src.services.prospect_matcher import ProspectMatchingEngine
from src.services.ai_writer import AIWriterService
from src.services.connector_ranking import ConnectorRankingService
try:
    from src.services.company_exec_search import CompanyExecSearchService
except ImportError:  # pragma: no cover - optional dependency
    CompanyExecSearchService = None

# Import approval queue service for human-in-the-loop workflows
try:
    from .approval_queue_service import approval_queue_service
except ImportError:
    logger.warning("Approval queue service not available - using auto-approval")
    approval_queue_service = None

try:
    import openai
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    logger.warning("OpenAI library not available - Enhanced orchestrator disabled")
    OPENAI_AVAILABLE = False
    AsyncOpenAI = None

class AgentRole(Enum):
    """September 2025 - Enhanced AI Agent Roles"""
    WORKFLOW_ORCHESTRATOR = "workflow_orchestrator"
    PROSPECT_ANALYZER = "prospect_analyzer"
    EXECUTIVE_RESEARCHER = "executive_researcher"
    NETWORK_MAPPER = "network_mapper"
    EMAIL_COMPOSER = "email_composer"
    RISK_ASSESSOR = "risk_assessor"
    COMPLIANCE_AUDITOR = "compliance_auditor"
    PERFORMANCE_OPTIMIZER = "performance_optimizer"

class ToolApprovalLevel(Enum):
    """September 2025 - Tool approval requirements"""
    NONE = "none"              # No approval required
    AUTO_LOW_RISK = "auto_low_risk"  # Auto-approve if risk < threshold
    HUMAN_REQUIRED = "human_required"  # Always require human approval
    ESCALATED = "escalated"    # Require senior approval

@dataclass
class AgentTool:
    """September 2025 - Enhanced agent tool with approval controls"""
    name: str
    description: str
    function: Callable
    parameters: Dict[str, Any]
    approval_level: ToolApprovalLevel = ToolApprovalLevel.NONE
    risk_threshold: float = 0.3
    approval_timeout_minutes: int = 30
    requires_audit: bool = True

@dataclass
class AgentConfiguration:
    """September 2025 - Advanced agent configuration"""
    role: AgentRole
    name: str
    instructions: str
    model: str = "gpt-4-turbo-preview"  # September 2025 model
    temperature: float = 0.2
    tools: List[AgentTool] = None
    max_iterations: int = 10
    human_oversight: bool = True
    audit_all_actions: bool = True
    organization_id: Optional[int] = None

@dataclass
class ToolExecution:
    """September 2025 - Tool execution with approval tracking"""
    execution_id: str
    tool_name: str
    parameters: Dict[str, Any]
    approval_status: str  # pending, approved, rejected, auto_approved
    risk_score: float
    requested_at: datetime
    approved_at: Optional[datetime] = None
    approver_id: Optional[int] = None
    execution_result: Optional[Any] = None
    error_message: Optional[str] = None

class EnhancedOpenAIAgentsOrchestrator:
    """
    September 2025 - Production-ready OpenAI Agents SDK Integration
    Features: Human-in-the-loop approval, risk assessment, audit logging
    """

    def __init__(self, api_key: str = None, organization: str = None):
        self.api_key = api_key or "sk-placeholder"  # Will be set from integration_sets
        self.organization = organization

        if OPENAI_AVAILABLE:
            self.client = None
        else:
            self.client = None

        self.agents: Dict[AgentRole, Any] = {}
        self.agent_registry: Dict[int, Dict[AgentRole, ProvisionedAgent]] = {}
        self.agent_configs: Dict[AgentRole, AgentConfiguration] = {}
        self.pending_approvals: Dict[str, ToolExecution] = {}
        self.active_conversations: Dict[str, Dict[str, Any]] = {}
        self._org_semaphores: Dict[int, asyncio.Semaphore] = {}
        self._clients: Dict[int, AsyncOpenAI] = {}
        self._client_meta: Dict[int, str] = {}

        self._initialize_agent_configurations()
        self._prospect_engine = ProspectMatchingEngine()
        self._ai_writer = AIWriterService()
        self._connector_ranking = ConnectorRankingService()
        self._exec_search = CompanyExecSearchService() if CompanyExecSearchService else None

    def _initialize_agent_configurations(self):
        """Initialize September 2025 agent configurations"""

        # Workflow Orchestrator Agent
        self.agent_configs[AgentRole.WORKFLOW_ORCHESTRATOR] = AgentConfiguration(
            role=AgentRole.WORKFLOW_ORCHESTRATOR,
            name="VouchLink AI Workflow Orchestrator",
            instructions="""You are the central workflow orchestrator for VouchLink AI's corporate warm introduction platform.

Your responsibilities:
1. Coordinate multi-step workflows across specialized agents
2. Make intelligent routing decisions based on context
3. Escalate complex decisions to human operators
4. Optimize workflow efficiency and success rates
5. Ensure compliance with platform policies

Always prioritize data accuracy and relationship authenticity over speed.
Escalate sensitive operations for human approval when risk scores exceed thresholds.""",
            tools=[
                AgentTool(
                    name="start_prospect_analysis",
                    description="Initiate prospect analysis workflow",
                    function=self._start_prospect_analysis,
                    parameters={
                        "type": "object",
                        "properties": {
                            "prospect_data": {"type": "object"},
                            "analysis_depth": {"type": "string", "enum": ["basic", "comprehensive"]}
                        },
                        "required": ["prospect_data"]
                    },
                    approval_level=ToolApprovalLevel.AUTO_LOW_RISK,
                    risk_threshold=0.2
                ),
                AgentTool(
                    name="schedule_email_campaign",
                    description="Schedule email outreach campaign",
                    function=self._schedule_email_campaign,
                    parameters={
                        "type": "object",
                        "properties": {
                            "prospect_ids": {"type": "array", "items": {"type": "integer"}},
                            "email_template_id": {"type": "integer"},
                            "send_timing": {"type": "string"}
                        },
                        "required": ["prospect_ids", "email_template_id"]
                    },
                    approval_level=ToolApprovalLevel.HUMAN_REQUIRED,  # Always require approval for emails
                    approval_timeout_minutes=60
                )
            ]
        )

    def _serialize_agent_config(self, config: AgentConfiguration) -> Dict[str, Any]:
        tools_payload = []
        for tool in config.tools or []:
            tools_payload.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })

        return {
            "name": config.name,
            "model": config.model,
            "instructions": config.instructions,
            "temperature": config.temperature,
            "tools": tools_payload,
            "metadata": {
                "human_oversight": str(config.human_oversight),
                "role": config.role.value,
            },
        }

    async def _get_provisioned_agent(self, organization_id: int, role: AgentRole) -> ProvisionedAgent:
        if organization_id not in self.agent_registry:
            await self.initialize_agents(organization_id)

        registry = self.agent_registry.get(organization_id, {})
        agent = registry.get(role)
        if not agent:
            # Ensure specific agent; this handles rotations without reinitializing all roles
            config = self.agent_configs.get(role)
            if not config:
                raise ValueError(f"Unknown agent role: {role}")

            payload = self._serialize_agent_config(config)
            api_key = (await self._get_organization_api_key(organization_id)) or self.api_key or settings.OPENAI_API_KEY
            provisioned = await agent_provisioning_service.ensure_agent(
                tenant_id=organization_id,
                role=role.value,
                config_payload=payload,
                api_key=api_key,
                organization=self.organization,
            )
            self.agent_registry.setdefault(organization_id, {})[role] = provisioned
            return provisioned
        return agent

    def _get_org_semaphore(self, organization_id: int) -> asyncio.Semaphore:
        if organization_id not in self._org_semaphores:
            max_concurrent = max(settings.MAX_CONCURRENT_JOBS or 2, 1)
            self._org_semaphores[organization_id] = asyncio.Semaphore(max_concurrent)
        return self._org_semaphores[organization_id]

    async def _resolve_api_key(self, organization_id: int) -> str:
        organization_key = await self._get_organization_api_key(organization_id)
        resolved = organization_key or self.api_key or settings.OPENAI_API_KEY
        if not resolved:
            raise RuntimeError("No OpenAI API key configured")
        return resolved

    async def _get_openai_client(self, organization_id: int) -> AsyncOpenAI:
        api_key = await self._resolve_api_key(organization_id)
        client = self._clients.get(organization_id)
        if client and self._client_meta.get(organization_id) == api_key:
            return client

        if client:
            try:
                close_method = getattr(client, "close", None)
                if asyncio.iscoroutinefunction(close_method):
                    await close_method()  # type: ignore[misc]
                elif callable(close_method):
                    close_method()
            except Exception:
                pass

        client = AsyncOpenAI(api_key=api_key, organization=self.organization)
        self._clients[organization_id] = client
        self._client_meta[organization_id] = api_key
        self.client = client
        return client

        # Prospect Analyzer Agent
        self.agent_configs[AgentRole.PROSPECT_ANALYZER] = AgentConfiguration(
            role=AgentRole.PROSPECT_ANALYZER,
            name="Prospect Intelligence Analyst",
            instructions="""You are an expert prospect intelligence analyst specializing in B2B executive research.

Your expertise:
1. Analyze company profiles and growth trajectories
2. Assess executive decision-making authority and influence
3. Identify business context and pain points
4. Score engagement potential and timing
5. Recommend personalized outreach strategies

Always provide confidence scores and reasoning for your assessments.
Focus on genuine business value alignment, not just contact acquisition.""",
            tools=[
                AgentTool(
                    name="analyze_company_profile",
                    description="Deep analysis of company profile and market position",
                    function=self._analyze_company_profile,
                    parameters={
                        "type": "object",
                        "properties": {
                            "company_name": {"type": "string"},
                            "domain": {"type": "string"},
                            "industry": {"type": "string"},
                            "size_estimate": {"type": "string"}
                        },
                        "required": ["company_name"]
                    }
                ),
                AgentTool(
                    name="score_prospect_potential",
                    description="Score prospect engagement potential",
                    function=self._score_prospect_potential,
                    parameters={
                        "type": "object",
                        "properties": {
                            "prospect_profile": {"type": "object"},
                            "team_context": {"type": "object"}
                        },
                        "required": ["prospect_profile"]
                    }
                )
            ]
        )

        # Email Composer Agent
        self.agent_configs[AgentRole.EMAIL_COMPOSER] = AgentConfiguration(
            role=AgentRole.EMAIL_COMPOSER,
            name="Executive Email Composer",
            instructions="""You are a senior executive communication specialist for high-level B2B outreach.

Your craft:
1. Write compelling, personalized introduction emails
2. Incorporate prospect research and mutual connections
3. Create subject lines with high open rates
4. Adapt tone for different executive personalities
5. Ensure compliance with email regulations

Every email should feel genuinely personal and value-driven.
Never use generic templates or automated language patterns.""",
            tools=[
                AgentTool(
                    name="generate_introduction_email",
                    description="Generate personalized introduction email",
                    function=self._generate_introduction_email,
                    parameters={
                        "type": "object",
                        "properties": {
                            "prospect_profile": {"type": "object"},
                            "connector_profile": {"type": "object"},
                            "mutual_context": {"type": "object"},
                            "email_style": {"type": "string", "enum": ["formal", "casual", "industry_specific"]}
                        },
                        "required": ["prospect_profile", "connector_profile"]
                    },
                    approval_level=ToolApprovalLevel.HUMAN_REQUIRED,  # Email content requires approval
                    approval_timeout_minutes=120
                )
            ]
        )

        # Risk Assessor Agent
        self.agent_configs[AgentRole.RISK_ASSESSOR] = AgentConfiguration(
            role=AgentRole.RISK_ASSESSOR,
            name="Corporate Risk Assessment Specialist",
            instructions="""You are a corporate risk assessment specialist for B2B outreach campaigns.

Your analysis covers:
1. Reputation risk for both parties
2. Compliance with regulations (GDPR, CAN-SPAM, industry-specific)
3. Cultural and geographical considerations
4. Potential negative outcomes and mitigation strategies
5. Legal and ethical implications

Provide actionable risk scores and clear mitigation recommendations.
Err on the side of caution for sensitive industries or high-profile prospects.""",
            tools=[
                AgentTool(
                    name="assess_outreach_risk",
                    description="Comprehensive risk assessment for outreach campaign",
                    function=self._assess_outreach_risk,
                    parameters={
                        "type": "object",
                        "properties": {
                            "campaign_data": {"type": "object"},
                            "prospect_profiles": {"type": "array"},
                            "regulatory_context": {"type": "object"}
                        },
                        "required": ["campaign_data"]
                    },
                    approval_level=ToolApprovalLevel.AUTO_LOW_RISK,
                    risk_threshold=0.4
                )
            ]
        )

    async def initialize_agents(self, organization_id: int):
        """Initialize all agents for an organization"""
        if not OPENAI_AVAILABLE:
            raise RuntimeError('OpenAI SDK is not available; cannot initialize agents')

        try:
            # Get organization's OpenAI API key from integration_sets
            api_key = await self._get_organization_api_key(organization_id)
            resolved_key = api_key or self.api_key or settings.OPENAI_API_KEY
            if not resolved_key:
                raise RuntimeError("No OpenAI API key configured for agent provisioning")

            client = await self._get_openai_client(organization_id)

            registry: Dict[AgentRole, ProvisionedAgent] = {}

            for role, config in self.agent_configs.items():
                config.organization_id = organization_id

                payload = self._serialize_agent_config(config)
                provisioned = await agent_provisioning_service.ensure_agent(
                    tenant_id=organization_id,
                    role=role.value,
                    config_payload=payload,
                    api_key=resolved_key,
                    organization=self.organization,
                )
                registry[role] = provisioned
                logger.info(
                    "✅ Provisioned assistant %s for org %s (role=%s)",
                    provisioned.assistant_id,
                    organization_id,
                    role.value,
                )

            self.agent_registry[organization_id] = registry

        except Exception as e:
            logger.error(f"Failed to initialize agents for org {organization_id}: {e}")
            raise

    async def start_conversation(self,
                                agent_role: AgentRole,
                                message: str,
                                context: Dict[str, Any],
                                organization_id: int) -> str:
        """Start a conversation with an agent - September 2025 feature"""
        conversation_id = str(uuid.uuid4())

        if not OPENAI_AVAILABLE:
            raise RuntimeError('OpenAI SDK is not available; cannot start conversations')

        try:
            provisioned = await self._get_provisioned_agent(organization_id, agent_role)
            client = await self._get_openai_client(organization_id)

            async with self._get_org_semaphore(organization_id):
                thread = await client.beta.threads.create(
                    metadata={
                        "conversation_id": conversation_id,
                        "organization_id": str(organization_id),
                        "agent_role": agent_role.value
                    }
                )

                context_message = f"Context: {json.dumps(context, indent=2)}\n\nUser Request: {message}"

                await client.beta.threads.messages.create(
                    thread_id=thread.id,
                    role="user",
                    content=context_message
                )

            self.active_conversations[conversation_id] = {
                "thread_id": getattr(thread, "id", None),
                "assistant_id": provisioned.assistant_id,
                "agent_role": agent_role,
                "organization_id": organization_id,
                "created_at": datetime.now(timezone.utc),
                "status": "active"
            }

            logger.info(f"Started conversation {conversation_id} with {agent_role.value}")
            return conversation_id

        except Exception as e:
            logger.error(f"Failed to start conversation: {e}")
            raise

    async def run_agent_with_approval(self,
                                    conversation_id: str,
                                    max_iterations: int = 10) -> Dict[str, Any]:
        """Run agent with human-in-the-loop approval - September 2025 core feature"""
        conversation = self.active_conversations.get(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")

        if not OPENAI_AVAILABLE:
            raise RuntimeError('OpenAI SDK is not available; cannot run agent workflows')

        organization_id = conversation["organization_id"]
        client = await self._get_openai_client(organization_id)

        try:
            async with self._get_org_semaphore(organization_id):
                run = await client.beta.threads.runs.create(
                    thread_id=conversation["thread_id"],
                    assistant_id=conversation["assistant_id"],
                    instructions="Execute the task with human oversight for sensitive operations."
                )

                iterations = 0
                while iterations < max_iterations:
                    run_status = await client.beta.threads.runs.retrieve(
                        thread_id=conversation["thread_id"],
                        run_id=run.id
                    )

                    if run_status.status == "completed":
                        messages = await client.beta.threads.messages.list(
                            thread_id=conversation["thread_id"],
                            order="desc",
                            limit=1
                        )
                        conversation["status"] = "completed"
                        result_payload = {
                            "status": "completed",
                            "conversation_id": conversation_id,
                            "final_response": messages.data[0].content[0].text.value if messages.data else None,
                            "iterations": iterations
                        }

                        if agent_logger and AgentEventType:
                            await agent_logger.log_event(
                                agent_id="openai_agents_enhanced",
                                event_type=AgentEventType.TASK_COMPLETE,
                                message="Agent run completed",
                                metadata=result_payload,
                            )
                        if global_analytics_service:
                            await global_analytics_service.track_agent_event(
                                conversation["organization_id"],
                                "agent_run_completed",
                                result_payload,
                            )
                        return result_payload

                    if run_status.status == "requires_action":
                        action_result = await self._handle_tool_calls_with_approval(
                            conversation["thread_id"],
                            run.id,
                            run_status.required_action,
                            organization_id
                        )

                        if action_result.get("requires_human_approval"):
                            conversation["status"] = "awaiting_approval"
                            pending_payload = {
                                "status": "pending_approval",
                                "conversation_id": conversation_id,
                                "approval_requests": action_result.get("approval_requests", []),
                                "iterations": iterations
                            }
                            if agent_logger and AgentEventType:
                                await agent_logger.log_event(
                                    agent_id="openai_agents_enhanced",
                                    event_type=AgentEventType.APPROVAL_REQUEST,
                                    message="Agent run awaiting approval",
                                    metadata=pending_payload,
                                )
                            if global_analytics_service:
                                await global_analytics_service.track_agent_event(
                                    conversation["organization_id"],
                                    "agent_run_waiting_approval",
                                    pending_payload,
                                )
                            return pending_payload

                        if action_result.get("status") == "approved" and action_result.get("tool_outputs"):
                            await client.beta.threads.runs.submit_tool_outputs(
                                thread_id=conversation["thread_id"],
                                run_id=run.id,
                                tool_outputs=action_result["tool_outputs"]
                            )

                    elif run_status.status in ("failed", "cancelled"):
                        conversation["status"] = run_status.status
                        failure_payload = {
                            "status": run_status.status,
                            "conversation_id": conversation_id,
                            "error": getattr(run_status, "last_error", None),
                            "iterations": iterations
                        }
                        if agent_logger and AgentEventType:
                            await agent_logger.log_event(
                                agent_id="openai_agents_enhanced",
                                event_type=AgentEventType.TASK_ERROR,
                                message="Agent run ended with error",
                                metadata=failure_payload,
                            )
                        if global_analytics_service:
                            await global_analytics_service.track_agent_event(
                                conversation["organization_id"],
                                "agent_run_error",
                                failure_payload,
                            )
                        return failure_payload

                    await asyncio.sleep(2)
                    iterations += 1

            timeout_payload = {
                "status": "timeout",
                "conversation_id": conversation_id,
                "iterations": iterations
            }
            if agent_logger and AgentEventType:
                await agent_logger.log_event(
                    agent_id="openai_agents_enhanced",
                    event_type=AgentEventType.SYSTEM_EVENT,
                    message="Agent run timed out",
                    metadata=timeout_payload,
                )
            if global_analytics_service:
                await global_analytics_service.track_agent_event(
                    conversation["organization_id"],
                    "agent_run_timeout",
                    timeout_payload,
                )
            return timeout_payload

        except Exception as e:
            logger.error(f"Agent run failed: {e}")
            return {
                "status": "error",
                "conversation_id": conversation_id,
                "error": str(e)
            }

    async def _handle_tool_calls_with_approval(self,
                                             thread_id: str,
                                             run_id: str,
                                             required_action: Any,
                                             organization_id: int) -> Dict[str, Any]:
        """Handle tool calls with September 2025 approval workflow"""
        tool_outputs = []
        approval_requests = []
        requires_human_approval = False

        for tool_call in required_action.submit_tool_outputs.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            # Find tool configuration
            tool_config = self._find_tool_config(tool_name)
            if not tool_config:
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": json.dumps({"error": f"Unknown tool: {tool_name}"})
                })
                continue

            # Assess risk and determine approval needs
            risk_score = await self._assess_tool_risk(tool_name, tool_args, organization_id)

            if tool_config.approval_level == ToolApprovalLevel.HUMAN_REQUIRED:
                # Always require human approval
                approval_id = await self._create_approval_request(
                    tool_call, tool_config, risk_score, organization_id
                )
                approval_requests.append(approval_id)
                requires_human_approval = True

            elif (tool_config.approval_level == ToolApprovalLevel.AUTO_LOW_RISK and
                  risk_score > tool_config.risk_threshold):
                # Require approval if risk exceeds threshold
                approval_id = await self._create_approval_request(
                    tool_call, tool_config, risk_score, organization_id
                )
                approval_requests.append(approval_id)
                requires_human_approval = True

            else:
                # Auto-approve and execute
                try:
                    result = await tool_config.function(tool_args, organization_id)
                    tool_outputs.append({
                        "tool_call_id": tool_call.id,
                        "output": json.dumps(result)
                    })

                    # Log auto-approved execution
                    if tool_config.requires_audit:
                        await self._log_tool_execution(
                            tool_name, tool_args, result, "auto_approved", organization_id
                        )

                except Exception as e:
                    tool_outputs.append({
                        "tool_call_id": tool_call.id,
                        "output": json.dumps({"error": str(e)})
                    })

        # Submit approved tool outputs
        if tool_outputs and not requires_human_approval:
            client = await self._get_openai_client(organization_id)
            await client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run_id,
                tool_outputs=tool_outputs
            )

        return {
            "requires_human_approval": requires_human_approval,
            "approval_requests": approval_requests,
            "auto_executed": len(tool_outputs)
        }

    async def approve_tool_execution(self,
                                   approval_id: str,
                                   approver_id: int,
                                   organization_id: int) -> Dict[str, Any]:
        """Approve tool execution with approval queue service integration"""
        execution = self.pending_approvals.get(approval_id)
        if not execution:
            # Try to fetch from approval queue service if not in local cache
            if approval_queue_service:
                try:
                    approval_details = await approval_queue_service.get_approval_request_details(
                        approval_id, organization_id
                    )
                    if approval_details:
                        # Reconstruct execution object from approval service data
                        execution = ToolExecution(
                            execution_id=approval_id,
                            tool_name=approval_details['details']['tool_name'],
                            parameters=approval_details['details']['parameters'],
                            approval_status=approval_details['status'],
                            risk_score=approval_details['details']['risk_score'],
                            requested_at=datetime.fromisoformat(approval_details['created_at']),
                        )
                        self.pending_approvals[approval_id] = execution
                    else:
                        return {"error": "Approval request not found"}
                except Exception as e:
                    logger.error(f"Failed to fetch approval request from queue service: {e}")
                    return {"error": "Approval request not found"}
            else:
                return {"error": "Approval request not found"}

        try:
            execution.approval_status = "approved"
            execution.approved_at = datetime.now(timezone.utc)
            execution.approver_id = approver_id

            # Update approval status in approval queue service
            if approval_queue_service:
                try:
                    await approval_queue_service.approve_request(
                        approval_id, approver_id, organization_id
                    )
                    logger.info(f"Approval {approval_id} updated in queue service")
                except Exception as e:
                    logger.error(f"Failed to update approval in queue service: {e}")
                    # Continue with execution despite service error

            # Execute the approved tool
            tool_config = self._find_tool_config(execution.tool_name)
            if tool_config:
                result = await tool_config.function(execution.parameters, organization_id)
                execution.execution_result = result

                # Log approved execution
                await self._log_tool_execution(
                    execution.tool_name, execution.parameters, result,
                    "human_approved", organization_id, approver_id
                )

                return {"status": "approved", "result": result}
            else:
                error_msg = f"Tool configuration not found for {execution.tool_name}"
                execution.error_message = error_msg
                return {"error": error_msg}

        except Exception as e:
            execution.error_message = str(e)
            logger.error(f"Approved tool execution failed: {e}")

            # Update error status in approval queue service
            if approval_queue_service:
                try:
                    await approval_queue_service.reject_request(
                        approval_id, approver_id, organization_id, reason=f"Execution failed: {str(e)}"
                    )
                except Exception as service_e:
                    logger.error(f"Failed to update error status in queue service: {service_e}")

            return {"error": str(e)}

    def _find_tool_config(self, tool_name: str) -> Optional[AgentTool]:
        """Find tool configuration by name"""
        for config in self.agent_configs.values():
            for tool in config.tools or []:
                if tool.name == tool_name:
                    return tool
        return None

    async def _assess_tool_risk(self, tool_name: str, parameters: Dict[str, Any], organization_id: int) -> float:
        """Assess risk score for tool execution"""
        # Base risk assessment logic
        base_risk = 0.1

        # Email-related operations are higher risk
        if "email" in tool_name.lower():
            base_risk += 0.4

        # Large batch operations are higher risk
        if "prospect_ids" in parameters:
            prospect_count = len(parameters.get("prospect_ids", []))
            if prospect_count > 50:
                base_risk += 0.3
            elif prospect_count > 10:
                base_risk += 0.2

        # External API calls are medium risk
        if any(keyword in tool_name.lower() for keyword in ["lookup", "search", "enrich"]):
            base_risk += 0.2

        return min(base_risk, 1.0)

    async def _create_approval_request(self,
                                     tool_call: Any,
                                     tool_config: AgentTool,
                                     risk_score: float,
                                     organization_id: int) -> str:
        """Create approval request for tool execution with approval queue integration"""
        approval_id = str(uuid.uuid4())

        execution = ToolExecution(
            execution_id=approval_id,
            tool_name=tool_call.function.name,
            parameters=json.loads(tool_call.function.arguments),
            approval_status="pending",
            risk_score=risk_score,
            requested_at=datetime.now(timezone.utc)
        )

        self.pending_approvals[approval_id] = execution

        # Integrate with approval queue service for persistence and workflow management
        if approval_queue_service:
            try:
                await approval_queue_service.create_approval_request(
                    approval_type="ai_tool_execution",  # Using the new type we added
                    requestor_id=None,  # AI agent initiated
                    organization_id=organization_id,
                    details={
                        "tool_name": tool_call.function.name,
                        "parameters": json.loads(tool_call.function.arguments),
                        "risk_score": risk_score,
                        "execution_id": approval_id,
                        "tool_description": tool_config.description,
                        "approval_level": tool_config.approval_level.value,
                        "timeout_minutes": tool_config.approval_timeout_minutes
                    },
                    metadata={
                        "agent_role": "openai_agent",
                        "tool_call_id": tool_call.id,
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
                )
                logger.info(f"Approval request {approval_id} submitted to approval queue service")
            except Exception as e:
                logger.error(f"Failed to create approval request in queue service: {e}")
                # Continue with local storage as fallback

        # Store in database for persistence (fallback or supplementary storage)
        await self._store_approval_request(execution, organization_id)

        logger.info(f"Created approval request {approval_id} for {tool_call.function.name}")
        return approval_id

    async def _store_approval_request(self, execution: ToolExecution, organization_id: int):
        """Store approval request in database with approval queue integration"""
        try:
            if approval_queue_service:
                # Check if approval request details are available for monitoring
                approval_details = await approval_queue_service.get_approval_request_details(
                    execution.execution_id, organization_id
                )

                if approval_details:
                    logger.info(f"Approval request {execution.execution_id} stored successfully in queue service")
                    # Update local execution with any additional details from the service
                    execution.approval_status = approval_details.get('status', execution.approval_status)
                else:
                    logger.warning(f"Approval request {execution.execution_id} not found in queue service")
            else:
                logger.warning("Approval queue service not available - using local storage only")

        except Exception as e:
            logger.error(f"Failed to integrate with approval queue service: {e}")
            # Continue with local storage as fallback

    async def _log_tool_execution(self,
                                tool_name: str,
                                parameters: Dict[str, Any],
                                result: Any,
                                approval_type: str,
                                organization_id: int,
                                approver_id: Optional[int] = None):
        """Log tool execution for audit trail"""
        try:
            from services.audit_logging_service import AuditLoggingService
            audit_service = AuditLoggingService()

            await audit_service.log_event(
                organization_id=organization_id,
                actor_type="ai_agent",
                actor_id="openai_agent",
                action=f"tool_execution:{tool_name}",
                target_type="tool",
                target_id=tool_name,
                payload={
                    "tool_name": tool_name,
                    "parameters": parameters,
                    "result_summary": str(result)[:500],  # Truncate large results
                    "approval_type": approval_type,
                    "approver_id": approver_id
                }
            )

        except Exception as e:
            logger.error(f"Failed to log tool execution: {e}")

    # Tool function implementations
    async def _start_prospect_analysis(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Start prospect analysis"""
        prospect_id = parameters.get("prospect_id")
        prospect_name = parameters.get("prospect_name")
        prospect_company = parameters.get("prospect_company")

        try:
            if organization_id is None or str(organization_id).strip() == "":
                raise ValueError("organization_id is required for prospect analysis")
            tenant_scope = str(organization_id).strip()
            if prospect_id:
                result = await self._prospect_engine.find_prospect_matches(
                    int(prospect_id),
                    tenant_id=tenant_scope,
                )
            elif prospect_name:
                result = await self._prospect_engine.find_target_matches_realtime(
                    prospect_name,
                    prospect_company or "",
                    tenant_id=tenant_scope,
                )
            else:
                raise ValueError("prospect_id or prospect_name is required")

            return {
                "status": "success" if not result.get("error") else "error",
                "data": result,
            }
        except Exception as exc:
            logger.error("Prospect analysis failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    async def _schedule_email_campaign(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Schedule email campaign"""
        prospect_id = parameters.get("prospect_id")
        introducer_ids = parameters.get("introducer_ids") or []
        user_id = parameters.get("user_id") or parameters.get("requested_by") or 1
        message_type = parameters.get("message_type", "warm_intro")
        channel_preference = parameters.get("channel_preference", "email_first")
        schedule_at = parameters.get("schedule_at")
        use_ai = parameters.get("use_ai", True)
        ab_test = parameters.get("ab_test", False)

        if not prospect_id:
            raise ValueError("prospect_id is required to schedule a campaign")
        if not introducer_ids:
            raise ValueError("introducer_ids cannot be empty")

        schedule_dt = None
        if schedule_at:
            try:
                schedule_dt = datetime.fromisoformat(schedule_at)
            except ValueError as exc:
                raise ValueError(f"Invalid schedule_at timestamp: {schedule_at}") from exc

        result = await email_service.create_campaign(
            prospect_id=int(prospect_id),
            introducer_ids=[int(i) for i in introducer_ids],
            tenant_id=organization_id,
            user_id=int(user_id),
            message_type=message_type,
            use_ai=bool(use_ai),
            channel_preference=channel_preference,
            schedule_send=schedule_dt,
            ab_test=bool(ab_test)
        )

        return {
            "status": "scheduled" if result.get("status") == "scheduled" else "draft",
            "campaign": result,
        }

    async def _analyze_company_profile(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Analyze company profile"""
        prospect_name = parameters.get("prospect_name")
        company = parameters.get("company_name") or parameters.get("company")

        if not prospect_name and not company:
            raise ValueError("prospect_name or company_name required for analysis")

        if organization_id is None or str(organization_id).strip() == "":
            raise ValueError("organization_id is required for company profile analysis")
        tenant_scope = str(organization_id).strip()

        analysis = await self._prospect_engine.find_target_matches_realtime(
            prospect_name or "",
            company or "",
            tenant_id=tenant_scope,
        )

        return {
            "status": "success" if not analysis.get("error") else "error",
            "analysis": analysis
        }

    async def _score_prospect_potential(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Score prospect potential"""
        prospect_id = parameters.get("prospect_id")
        prospect_name = parameters.get("prospect_name") or parameters.get("name")
        prospect_company = parameters.get("prospect_company") or parameters.get("company") or ""

        if not prospect_id and not prospect_name:
            raise ValueError("prospect_id or prospect_name is required")

        # Reuse prospect analysis workflow to gather connection intelligence
        if organization_id is None or str(organization_id).strip() == "":
            raise ValueError("organization_id is required to score prospect potential")
        tenant_scope = str(organization_id).strip()

        if prospect_id:
            analysis = await self._prospect_engine.find_prospect_matches(
                int(prospect_id),
                tenant_id=tenant_scope,
            )
        else:
            analysis = await self._prospect_engine.find_target_matches_realtime(
                prospect_name,
                prospect_company,
                tenant_id=tenant_scope,
            )

        if analysis.get("error"):
            return {"status": "error", "error": analysis.get("error")}

        mutual_connections = analysis.get("mutual_connections") or []

        # Normalise connection data for connector ranking
        normalised_connections = []
        for connection in mutual_connections:
            normalised_connections.append(
                {
                    "name": connection.get("full_name") or connection.get("name", ""),
                    "company": connection.get("company", ""),
                    "title": connection.get("title", ""),
                    "linkedin_url": connection.get("linkedin_url") or connection.get("profileUrl", ""),
                    "mutual_connections_count": connection.get("mutual_connections_count", 1),
                    "relationship_strength": connection.get("relationship_strength", "professional"),
                    "email": connection.get("email"),
                }
            )

        target_prospect = {
            "name": prospect_name or analysis.get("prospect_name") or "",
            "company": prospect_company or analysis.get("prospect_company") or "",
            "industry": parameters.get("industry") or analysis.get("industry"),
            "title": parameters.get("title") or analysis.get("prospect_title"),
        }

        ranked_connectors = self._connector_ranking.rank_connectors(
            normalised_connections,
            target_prospect,
            team_member={},
            max_results=5,
        )

        connection_count = len(normalised_connections)
        high_quality = sum(1 for c in ranked_connectors if c.score >= 100)
        warm_intros = sum(1 for c in ranked_connectors if any("relationship" in r.lower() for r in c.reasons))

        # Weighted composite score (0-100)
        score = 15.0
        score += min(connection_count * 8, 40)
        score += min(high_quality * 10, 25)
        score += min(warm_intros * 5, 15)
        score = min(score, 100)

        insights = []
        if connection_count == 0:
            insights.append("No mutual connections discovered yet")
        if ranked_connectors:
            top = ranked_connectors[0]
            insights.append(f"Top connector {top.name} scored {top.score}")
        if high_quality > 0:
            insights.append(f"{high_quality} strong connections available for warm outreach")

        return {
            "status": "success",
            "prospect": target_prospect,
            "score": round(score, 2),
            "connection_count": connection_count,
            "high_quality_connectors": high_quality,
            "warm_introduction_candidates": warm_intros,
            "top_connectors": [c.__dict__ for c in ranked_connectors],
            "insights": insights,
        }

    async def _research_executive_profile(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Research executive profile"""
        if not self._exec_search:
            raise RuntimeError("Executive search service is not available in this environment")

        company = parameters.get("company") or parameters.get("company_name")
        if not company:
            raise ValueError("company is required for executive research")

        titles = parameters.get("target_titles")
        max_results = parameters.get("max_results", 3)

        executives = await self._exec_search.find_executives_for_company(
            company_name=company,
            titles=titles,
            max_results=max_results,
        )

        if not executives:
            return {
                "status": "no_results",
                "company": company,
                "executives": [],
            }

        serialised = [exec.__dict__ for exec in executives]
        return {
            "status": "success",
            "company": company,
            "executives": serialised,
        }

    async def _generate_introduction_email(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Generate introduction email"""
        # This requires human approval
        prospect = parameters.get("prospect_profile", {})
        connector = parameters.get("connector_profile", {})
        connection_context = parameters.get("connection_context")
        requester = parameters.get("requesting_user_name")

        try:
            content = await self._ai_writer.generate_introduction_request(
                prospect_data=prospect,
                team_member_data=connector,
                connection_context=connection_context,
                requesting_user_name=requester,
            )
            return {
                "status": "success",
                "message": content,
            }
        except Exception as exc:
            logger.error("Introduction generation failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    async def _assess_outreach_risk(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Assess outreach risk"""
        risk_score = await self._assess_tool_risk("assess_outreach_risk", parameters, organization_id)
        mitigations = []
        if risk_score >= 0.7:
            mitigations.append("Require manual approval before sending any outreach.")
        if parameters.get("prospect_role", "").lower().startswith("chief"):
            mitigations.append("Personalize messaging with executive-level context.")

        return {
            "status": "success",
            "risk_score": risk_score,
            "recommendations": mitigations,
        }

    async def _map_mutual_connections(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Map mutual connections between prospect and team."""
        prospect_id = parameters.get("prospect_id")
        prospect_name = parameters.get("prospect_name")
        prospect_company = parameters.get("prospect_company") or parameters.get("company")

        if not prospect_id and not prospect_name:
            raise ValueError("prospect_id or prospect_name is required")

        if organization_id is None or str(organization_id).strip() == "":
            raise ValueError("organization_id is required to map mutual connections")
        tenant_scope = str(organization_id).strip()

        if prospect_id:
            analysis = await self._prospect_engine.find_prospect_matches(
                int(prospect_id),
                tenant_id=tenant_scope,
            )
        else:
            try:
                analysis = await self._prospect_engine.find_target_matches_realtime(
                    prospect_name,
                    prospect_company or "",
                    tenant_id=tenant_scope,
                )
            except TypeError as exc:
                if "tenant_id" not in str(exc):
                    raise
                analysis = await self._prospect_engine.find_target_matches_realtime(
                    prospect_name,
                    prospect_company or "",
                )

        if analysis.get("error"):
            return {"status": "error", "error": analysis.get("error")}

        connections = analysis.get("mutual_connections") or []
        summary = {
            "total_connections": len(connections),
            "high_confidence": sum(1 for c in connections if c.get("confidence", 0) >= 0.8),
            "with_email": sum(1 for c in connections if c.get("email")),
        }

        return {
            "status": "success",
            "prospect": {
                "name": analysis.get("prospect_name") or prospect_name,
                "company": analysis.get("prospect_company") or prospect_company,
            },
            "summary": summary,
            "connections": connections,
        }

    async def _coordinate_agent_handoff(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Coordinate data handoff between agents/workflows."""
        conversation_id = parameters.get("conversation_id")
        workflow_id = parameters.get("workflow_id")
        next_stage = parameters.get("next_stage")
        notes = parameters.get("notes")

        key = conversation_id or workflow_id
        if not key or key not in self.active_conversations:
            return {"status": "error", "error": "Conversation context not found"}

        handoff_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "next_stage": next_stage,
            "notes": notes,
        }
        conversation = self.active_conversations[key]
        conversation.setdefault("handoffs", []).append(handoff_record)

        return {
            "status": "success",
            "handoff": handoff_record,
        }

    async def _audit_compliance(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Audit outreach content for compliance risks."""
        email_content = parameters.get("email_content") or {}
        body = email_content.get("body") or parameters.get("body") or ""
        compliance_flags = []

        if "unsubscribe" not in body.lower():
            compliance_flags.append("missing_unsubscribe_clause")
        if any(term in body.lower() for term in ["guaranteed returns", "act now", "limited time only"]):
            compliance_flags.append("aggressive_language")
        if len(body.split()) > 220:
            compliance_flags.append("length_exceeds_best_practice")

        status = "compliant" if not compliance_flags else "review_needed"
        return {
            "status": status,
            "flags": compliance_flags,
        }

    async def _optimize_performance(self, parameters: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Tool function: Recommend performance optimizations."""
        metrics = parameters.get("performance_metrics") or {}
        recommendations = []

        open_rate = metrics.get("open_rate", 0)
        reply_rate = metrics.get("reply_rate", 0)

        if open_rate < 35:
            recommendations.append("Test alternative subject lines and preheaders.")
        if reply_rate < 10:
            recommendations.append("Introduce stronger call-to-action tailored to recipient role.")
        if metrics.get("recent_failures"):
            recommendations.append("Pause sends to review recent failures before continuing.")

        return {
            "status": "success",
            "recommendations": recommendations or ["Campaign performance meets targets."],
        }

    async def _get_organization_api_key(self, organization_id: int) -> Optional[str]:
        """Get organization's OpenAI API key from integration_sets"""
        # First try tenant integration settings helper (covers tenant_settings/user_integrations).
        try:
            from integrations.apify_client import get_tenant_integration_settings

            integration_settings = get_tenant_integration_settings(organization_id)
            tenant_key = integration_settings.get("openai_api_key")
            if tenant_key:
                return tenant_key
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.debug("Failed to retrieve OpenAI key via integration settings: %s", exc)

        # Fall back to integration_sets table.
        try:
            from api.db_core import get_conn
            from api.security import dec

            with get_conn() as conn:
                cursor = conn.cursor()

                # Determine available columns
                cursor.execute("PRAGMA table_info(integration_sets)")
                columns = {row[1] for row in cursor.fetchall()}

                encrypted_column = None
                if "openai_api_key_encrypted" in columns:
                    encrypted_column = "openai_api_key_encrypted"
                elif "openai_api_key" in columns:
                    encrypted_column = "openai_api_key"

                if encrypted_column:
                    cursor.execute(
                        f"SELECT {encrypted_column} FROM integration_sets WHERE organization_id = ?",
                        (organization_id,),
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        try:
                            return dec(row[0])
                        except Exception:
                            # Value may already be plaintext
                            return row[0]

                # Some datasets store keys inside feature_flags JSON.
                if "feature_flags" in columns:
                    cursor.execute(
                        "SELECT feature_flags FROM integration_sets WHERE organization_id = ?",
                        (organization_id,),
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        import json

                        flags = row[0]
                        if isinstance(flags, str):
                            try:
                                flags = json.loads(flags)
                            except json.JSONDecodeError:
                                flags = {}
                        if isinstance(flags, dict):
                            key = flags.get("openai_api_key")
                            if key:
                                return key
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning(
                "Failed to retrieve OpenAI key from integration_sets for org %s: %s",
                organization_id,
                exc,
            )

        # No tenant-specific key found; fall back to service-level key
        return None

    async def close(self):
        """Close all connections and cleanup"""
        self.active_conversations.clear()
        self.pending_approvals.clear()

# Global instance controlled via configuration
from core.settings import settings

enhanced_ai_orchestrator = None
if settings.OPENAI_AGENTS_ENABLED:
    try:
        enhanced_ai_orchestrator = EnhancedOpenAIAgentsOrchestrator(api_key=settings.OPENAI_API_KEY)
    except Exception as exc:
        logger.warning("Failed to initialize enhanced AI orchestrator: %s", exc)
else:
    logger.info("Enhanced OpenAI agent orchestrator disabled (set OPENAI_AGENTS_ENABLED to true to enable)")
