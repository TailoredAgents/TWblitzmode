#!/usr/bin/env python3
"""
AI-Approval Integration Service - September 2025
Connects enhanced OpenAI agents with human-in-the-loop approval workflows
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
import os
from enum import Enum
from .workflow_persistence_service import WorkflowPersistenceService
from .resilience_patterns import ResilienceManager, BulkheadType
from .error_handling_framework import ErrorHandler, ErrorCategory, ErrorSeverity

# Import communication client for Communication Hub integration
try:
    from .communication_client import get_communication_client, MessageType, MessagePriority
    communication_client_available = True
except ImportError:
    communication_client_available = False
    logger.warning("Communication client not available in AI approval integration")

logger = logging.getLogger(__name__)

try:
    from services.openai_agents_enhanced import (
        EnhancedOpenAIAgentsOrchestrator,
        AgentRole,
        ToolApprovalLevel,
        ToolExecution
    )
    from services.approval_queue_service import (
        ApprovalQueueService,
        ApprovalType,
        ApprovalPriority
    )
    from services.workflow_state_machine import (
        WorkflowStateMachine,
        WorkflowState
    )
    DEPENDENCIES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI integration dependencies not available: {e}")
    DEPENDENCIES_AVAILABLE = False

    # Fallback enums when dependencies aren't available
    from enum import Enum

    class ApprovalPriority(Enum):
        LOW = "low"
        NORMAL = "normal"
        HIGH = "high"
        CRITICAL = "critical"

    class ApprovalType(Enum):
        AI_TOOL_EXECUTION = "ai_tool_execution"
        EMAIL_SEND = "email_send"
        DATA_EXPORT = "data_export"
        SYSTEM_CHANGE = "system_change"

    class AgentRole(Enum):
        WORKFLOW_ORCHESTRATOR = "workflow_orchestrator"
        PROSPECT_ANALYZER = "prospect_analyzer"
        EMAIL_COMPOSER = "email_composer"

    class WorkflowState(Enum):
        INITIATED = "initiated"
        PROSPECT_ANALYSIS = "prospect_analysis"
        ANALYSIS_COMPLETE = "analysis_complete"
        EMAIL_GENERATION = "email_generation"

class AIWorkflowType(Enum):
    """Types of AI workflows that require human oversight"""
    PROSPECT_ANALYSIS = "prospect_analysis"
    EMAIL_GENERATION = "email_generation"
    NETWORK_MAPPING = "network_mapping"
    RISK_ASSESSMENT = "risk_assessment"
    COMPLIANCE_AUDIT = "compliance_audit"

class AIApprovalIntegrationService:
    """
    September 2025 - Integration layer between AI agents and approval workflows
    Ensures all AI actions go through proper human oversight when required
    """

    def __init__(self, database_url: str, openai_api_key: str = None, redis_url: str = "redis://localhost:6379"):
        self.database_url = database_url
        self.openai_api_key = openai_api_key
        self.redis_url = redis_url

        # Enterprise persistence and resilience
        from .workflow_persistence_service import workflow_persistence_service
        self.persistence_service = workflow_persistence_service
        self.resilience_manager = ResilienceManager()
        self.error_handler = ErrorHandler()

        # Register bulkhead for AI approval operations
        from .resilience_patterns import BulkheadConfig, BulkheadType
        self.resilience_manager.create_bulkhead(BulkheadConfig(
            name="ai_approval_integration",
            bulkhead_type=BulkheadType.THREAD_POOL,
            max_concurrent=8
        ))

        if DEPENDENCIES_AVAILABLE:
            try:
                self.ai_orchestrator = EnhancedOpenAIAgentsOrchestrator(
                    api_key=openai_api_key
                )
            except RuntimeError as exc:
                logger.warning("AI orchestrator disabled: %s", exc)
                self.ai_orchestrator = None
            self.approval_service = ApprovalQueueService(database_url)
            self.workflow_service = WorkflowStateMachine(redis_url, database_url)
        else:
            self.ai_orchestrator = None
            self.approval_service = None
            self.workflow_service = None

    async def initialize(self):
        """Initialize all services"""
        if DEPENDENCIES_AVAILABLE:
            if not self.ai_orchestrator:
                raise RuntimeError(
                    "AI orchestrator disabled. Enable the ai_agents_enabled feature flag "
                    "and provision OpenAI agents before initializing."
                )
            try:
                await self.approval_service.initialize()
                await self.workflow_service.initialize()
                logger.info("✅ AI-Approval integration initialized")
            except Exception as e:
                logger.error(f"Failed to initialize AI integration: {e}")
                raise
        else:
            raise RuntimeError("AI integration cannot initialize: Missing dependencies or configuration. Please ensure all API keys are configured.")

    async def start_ai_workflow(self,
                               workflow_type: AIWorkflowType,
                               organization_id: int,
                               user_id: int,
                               input_data: Dict[str, Any],
                               priority: ApprovalPriority = ApprovalPriority.NORMAL) -> str:
        """
        Start an AI workflow with integrated approval management
        Returns workflow_id for tracking
        """
        workflow_id = str(uuid.uuid4())

        try:
            # Use bulkhead for workflow creation
            async with self.resilience_manager.get_bulkhead("ai_approval_integration"):
                # Create workflow in enterprise persistence
                await self.persistence_service.create_workflow(
                    organization_id=organization_id,
                    user_id=user_id,
                    workflow_type=f"ai_{workflow_type.value}",
                    prospects=[input_data.get('prospect', {})],
                    team_members=[]
                )

                if self.workflow_service:
                    # Initialize workflow state machine
                    await self.workflow_service.start_workflow(
                        workflow_id=workflow_id,
                        organization_id=organization_id,
                        workflow_type="ai_" + workflow_type.value,
                        input_data=input_data,
                        initiated_by=user_id
                    )

                # Update workflow status in persistence
                await self.persistence_service.update_workflow_status(
                    workflow_id=workflow_id,
                    status="initiated",
                    current_stage=workflow_type.value
                )

            # Start AI processing
            if workflow_type == AIWorkflowType.PROSPECT_ANALYSIS:
                await self._handle_prospect_analysis(workflow_id, input_data, organization_id, user_id)
            elif workflow_type == AIWorkflowType.EMAIL_GENERATION:
                await self._handle_email_generation(workflow_id, input_data, organization_id, user_id)
            elif workflow_type == AIWorkflowType.NETWORK_MAPPING:
                await self._handle_network_mapping(workflow_id, input_data, organization_id, user_id)
            else:
                raise ValueError(f"Unsupported workflow type: {workflow_type}")

            logger.info(f"Started AI workflow {workflow_id} for org {organization_id}")
            return workflow_id

        except Exception as e:
            error_context = {
                'workflow_id': workflow_id,
                'workflow_type': workflow_type.value,
                'organization_id': organization_id,
                'user_id': user_id,
                'input_data': input_data
            }

            await self.error_handler.handle_error(
                error=e,
                operation="start_ai_approval_workflow",
                context=error_context,
                category=ErrorCategory.WORKFLOW_ERROR,
                severity=ErrorSeverity.HIGH
            )

            # Update workflow status in persistence if it exists
            try:
                await self.persistence_service.update_workflow_status(
                    workflow_id=workflow_id,
                    status="failed",
                    error_message=str(e)
                )
            except Exception as persistence_error:
                logger.warning(f"Could not update workflow status in persistence: {persistence_error}")

            logger.error(f"Failed to start AI workflow: {e}")
            raise

    async def _handle_prospect_analysis(self, workflow_id: str, input_data: Dict[str, Any],
                                      organization_id: int, user_id: int):
        """Handle prospect analysis workflow with AI agents"""

        if not self.ai_orchestrator:
            raise RuntimeError(
                "AI orchestrator not available. Enable the ai_agents_enabled feature flag "
                "and configure OpenAI agents."
            )

        try:
            # Update workflow status
            if self.workflow_service:
                await self.workflow_service.transition_to(
                    workflow_id, WorkflowState.PROSPECT_ANALYSIS
                )

            # Run AI analysis (this would be auto-approved if risk is low)
            analysis_result = await self._execute_ai_tool(
                workflow_id=workflow_id,
                agent_role=AgentRole.PROSPECT_ANALYZER,
                tool_name="analyze_company_profile",
                parameters={
                    "company_name": input_data.get("company"),
                    "domain": input_data.get("domain"),
                    "industry": input_data.get("industry")
                },
                organization_id=organization_id,
                user_id=user_id
            )

            # Score prospect potential
            scoring_result = await self._execute_ai_tool(
                workflow_id=workflow_id,
                agent_role=AgentRole.PROSPECT_ANALYZER,
                tool_name="score_prospect_potential",
                parameters={
                    "prospect_profile": input_data,
                    "team_context": {"organization_id": organization_id}
                },
                organization_id=organization_id,
                user_id=user_id
            )

            # Update workflow status in persistence
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="completed",
                current_stage="analysis_complete"
            )

            if self.workflow_service:
                await self.workflow_service.transition_to(
                    workflow_id, WorkflowState.ANALYSIS_COMPLETE
                )

        except Exception as e:
            error_context = {
                'workflow_id': workflow_id,
                'stage': 'prospect_analysis',
                'input_data': input_data
            }
            await self.error_handler.handle_error(
                error=e,
                operation="ai_prospect_analysis",
                context=error_context,
                category=ErrorCategory.AI_API_ERROR,
                severity=ErrorSeverity.HIGH
            )

            logger.error(f"Prospect analysis failed for workflow {workflow_id}: {e}")
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="failed",
                error_message=str(e)
            )

    async def _handle_email_generation(self, workflow_id: str, input_data: Dict[str, Any],
                                     organization_id: int, user_id: int):
        """Handle email generation workflow - always requires human approval"""

        try:
            if self.workflow_service:
                await self.workflow_service.transition_to(
                    workflow_id, WorkflowState.EMAIL_GENERATION
                )

            # Generate email content (requires approval)
            email_result = await self._execute_ai_tool(
                workflow_id=workflow_id,
                agent_role=AgentRole.EMAIL_COMPOSER,
                tool_name="generate_introduction_email",
                parameters={
                    "prospect_profile": input_data.get("prospect"),
                    "connector_profile": input_data.get("connector"),
                    "mutual_context": input_data.get("context", {}),
                    "email_style": input_data.get("style", "formal")
                },
                organization_id=organization_id,
                user_id=user_id,
                force_approval=True  # Always require approval for emails
            )

            # Update workflow status in persistence
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="pending_approval",
                current_stage="email_generation"
            )

        except Exception as e:
            error_context = {
                'workflow_id': workflow_id,
                'stage': 'email_generation',
                'input_data': input_data
            }
            await self.error_handler.handle_error(
                error=e,
                operation="ai_email_generation",
                context=error_context,
                category=ErrorCategory.AI_API_ERROR,
                severity=ErrorSeverity.HIGH
            )

            logger.error(f"Email generation failed for workflow {workflow_id}: {e}")
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="failed",
                error_message=str(e)
            )

    async def _handle_network_mapping(self, workflow_id: str, input_data: Dict[str, Any],
                                    organization_id: int, user_id: int):
        """Handle network mapping workflow"""

        raise RuntimeError("Network mapping not implemented. Please ensure all AI dependencies are available.")

    async def _execute_ai_tool(self,
                              workflow_id: str,
                              agent_role: AgentRole,
                              tool_name: str,
                              parameters: Dict[str, Any],
                              organization_id: int,
                              user_id: int,
                              force_approval: bool = False) -> Any:
        """
        Execute AI tool with approval workflow integration
        """

        if not self.ai_orchestrator:
            raise RuntimeError("AI orchestrator not available. Please ensure OpenAI API key is configured and dependencies are installed.")

        try:
            # Get agent configuration
            agent_config = self.ai_orchestrator.agent_configs.get(agent_role)
            if not agent_config:
                raise ValueError(f"No configuration found for agent role: {agent_role}")

            # Find the tool
            tool = None
            for agent_tool in agent_config.tools or []:
                if agent_tool.name == tool_name:
                    tool = agent_tool
                    break

            if not tool:
                raise ValueError(f"Tool {tool_name} not found for agent {agent_role}")

            # Assess if approval is needed
            requires_approval = (
                force_approval or
                tool.approval_level in [ToolApprovalLevel.HUMAN_REQUIRED, ToolApprovalLevel.ESCALATED]
            )

            if requires_approval and self.approval_service:
                # Create approval request
                approval_id = await self.approval_service.create_approval_request(
                    organization_id=organization_id,
                    request_type=ApprovalType.AI_TOOL_EXECUTION,
                    title=f"AI Tool Execution: {tool_name}",
                    description=f"Agent {agent_role.value} requests to execute {tool_name}",
                    requested_by=user_id,
                    context_data={
                        "workflow_id": workflow_id,
                        "agent_role": agent_role.value,
                        "tool_name": tool_name,
                        "parameters": parameters
                    },
                    priority=ApprovalPriority.HIGH if tool.approval_level == ToolApprovalLevel.ESCALATED else ApprovalPriority.NORMAL
                )

                # Update workflow status in persistence
                await self.persistence_service.update_workflow_status(
                    workflow_id=workflow_id,
                    status="pending_approval",
                    current_stage=f"approval_{tool_name}"
                )

                logger.info(f"Created approval request {approval_id} for AI tool {tool_name}")

                # Send Communication Hub message for user visibility
                if communication_client_available:
                    try:
                        client = await get_communication_client()

                        # Create executive-friendly approval request message
                        agent_name = agent_role.value.replace("_", " ").title()
                        action_description = tool_name.replace("_", " ")

                        # Build context for approval
                        approval_context = {
                            "approval_id": approval_id,
                            "workflow_id": workflow_id,
                            "tool_name": tool_name,
                            "agent_role": agent_role.value
                        }

                        # Add prospect/company context if available
                        if "company_name" in parameters:
                            approval_context["company"] = parameters["company_name"]
                        if "prospect_profile" in parameters:
                            prospect = parameters["prospect_profile"]
                            if isinstance(prospect, dict):
                                approval_context["prospect_name"] = prospect.get("name", prospect.get("full_name"))
                                approval_context["company"] = prospect.get("company")

                        await client.send_approval_request(
                            conversation_id=f"workflow_{workflow_id}",
                            recipient_id=str(user_id),
                            agent_name=agent_name,
                            action_description=action_description,
                            context=approval_context,
                            priority=MessagePriority.HIGH if tool.approval_level == ToolApprovalLevel.ESCALATED else MessagePriority.NORMAL,
                            workflow_id=workflow_id
                        )

                        logger.info(f"Sent approval request to Communication Hub for approval {approval_id}")

                    except Exception as e:
                        logger.error(f"Failed to send approval request to Communication Hub: {e}")

                # Return pending approval status
                return {
                    "status": "pending_approval",
                    "approval_id": approval_id,
                    "message": f"Tool execution pending human approval"
                }

            else:
                # Execute directly (auto-approved or no approval needed)
                result = await tool.function(**parameters)

                # Log execution
                logger.info(f"AI tool {tool_name} executed successfully for workflow {workflow_id}")

                return result

        except Exception as e:
            logger.error(f"AI tool execution failed: {e}")
            raise

    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get current status of AI workflow"""
        try:
            # Get workflow from enterprise persistence
            workflow_data = await self.persistence_service.get_workflow(workflow_id)
            if not workflow_data:
                raise ValueError(f"Workflow {workflow_id} not found")

            workflow = {
                "workflow_id": workflow_id,
                "organization_id": workflow_data['organization_id'],
                "user_id": workflow_data['user_id'],
                "workflow_type": workflow_data['workflow_type'],
                "status": workflow_data['status'],
                "current_stage": workflow_data.get('current_stage', 'unknown'),
                "created_at": workflow_data['created_at'],
                "updated_at": workflow_data['updated_at'],
                "error_message": workflow_data.get('error_message')
            }

            # Add current workflow state if available
            if self.workflow_service:
                try:
                    state_info = await self.workflow_service.get_workflow_state(workflow_id)
                    workflow["workflow_state"] = state_info
                except Exception as e:
                    logger.warning(f"Could not get workflow state: {e}")

            return workflow

        except Exception as e:
            error_context = {'workflow_id': workflow_id}
            await self.error_handler.handle_error(
                error=e,
                operation="get_ai_workflow_status",
                context=error_context,
                category=ErrorCategory.DATA_ACCESS_ERROR,
                severity=ErrorSeverity.MEDIUM
            )
            logger.error(f"Failed to get AI workflow status for {workflow_id}: {e}")
            raise

    async def handle_approval_decision(self, approval_id: str, decision: str,
                                     approved_by: int, notes: str = None) -> Dict[str, Any]:
        """
        Handle approval decision and continue AI workflow if approved
        """

        if not self.approval_service:
            raise RuntimeError("Approval service not available. Please ensure database connection is configured.")

        try:
            # Process approval decision
            if decision == "approve":
                result = await self.approval_service.approve_request(
                    approval_id=approval_id,
                    approved_by=approved_by,
                    notes=notes
                )
            else:
                result = await self.approval_service.reject_request(
                    approval_id=approval_id,
                    rejected_by=approved_by,
                    reason=notes or "Rejected by user"
                )

            # Get approval context to find the workflow
            approval_info = await self.approval_service.get_approval_request(approval_id)
            context_data = approval_info.get("context_data", {})
            workflow_id = context_data.get("workflow_id")

            if workflow_id:
                if decision == "approve":
                    # Continue workflow execution
                    await self.persistence_service.update_workflow_status(
                        workflow_id=workflow_id,
                        status="approved"
                    )
                    await self._continue_workflow_after_approval(workflow_id, approval_id)
                else:
                    # Mark workflow as rejected
                    await self.persistence_service.update_workflow_status(
                        workflow_id=workflow_id,
                        status="rejected",
                        error_message=f"Approval rejected: {notes}"
                    )

            return result

        except Exception as e:
            logger.error(f"Failed to handle approval decision: {e}")
            raise

    async def _continue_workflow_after_approval(self, workflow_id: str, approval_id: str):
        """Continue workflow execution after approval is granted"""

        try:
            workflow = self.active_workflows.get(workflow_id)
            if not workflow:
                return

            # Get approval context to understand what was approved
            if self.approval_service:
                approval_info = await self.approval_service.get_approval_request(approval_id)
                context_data = approval_info.get("context_data", {})

                tool_name = context_data.get("tool_name")
                agent_role = context_data.get("agent_role")
                parameters = context_data.get("parameters", {})

                # Execute the approved tool
                if tool_name and agent_role:
                    # This time bypass approval since it's already approved
                    result = await self._execute_approved_tool(
                        workflow_id, agent_role, tool_name, parameters
                    )

                    # Update workflow status in persistence
                    await self.persistence_service.update_workflow_status(
                        workflow_id=workflow_id,
                        status="completed"
                    )

            logger.info(f"Workflow {workflow_id} continued after approval {approval_id}")

        except Exception as e:
            logger.error(f"Failed to continue workflow after approval: {e}")
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="failed",
                error_message=f"Post-approval execution failed: {str(e)}"
            )

    async def _execute_approved_tool(self, workflow_id: str, agent_role: str,
                                   tool_name: str, parameters: Dict[str, Any]) -> Any:
        """Execute a tool that has already been approved"""

        raise RuntimeError("AI tool execution not available. Please ensure OpenAI API key is configured and dependencies are installed.")

    async def list_active_workflows(self, organization_id: int) -> List[Dict[str, Any]]:
        """List all active AI workflows for an organization"""
        try:
            workflows_data = await self.persistence_service.list_workflows(
                organization_id=organization_id,
                status=None,  # Get all statuses
                limit=100
            )

            workflows = []
            for workflow_data in workflows_data:
                if workflow_data['workflow_type'].startswith('ai_'):
                    workflows.append({
                        "workflow_id": workflow_data['workflow_id'],
                        "organization_id": workflow_data['organization_id'],
                        "user_id": workflow_data['user_id'],
                        "workflow_type": workflow_data['workflow_type'],
                        "status": workflow_data['status'],
                        "current_stage": workflow_data.get('current_stage', 'unknown'),
                        "created_at": workflow_data['created_at'],
                        "updated_at": workflow_data['updated_at']
                    })

            return workflows

        except Exception as e:
            error_context = {'organization_id': organization_id}
            await self.error_handler.handle_error(
                error=e,
                operation="list_ai_workflows",
                context=error_context,
                category=ErrorCategory.DATA_ACCESS_ERROR,
                severity=ErrorSeverity.MEDIUM
            )
            logger.error(f"Failed to list AI workflows for org {organization_id}: {e}")
            return []

    async def close(self):
        """Close all services"""
        if self.approval_service:
            await self.approval_service.close()
        if self.workflow_service:
            await self.workflow_service.close()

# Global instance
ai_approval_integration = AIApprovalIntegrationService(
    database_url=os.getenv("DATABASE_URL")
)
