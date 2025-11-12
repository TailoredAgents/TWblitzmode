#!/usr/bin/env python3
"""
AI Workflow Integration Service - September 2025
Connects OpenAI Agents Orchestrator with API Gateway and Approval Queue
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)

try:
    from services.openai_agents_orchestrator import OpenAIAgentsOrchestrator, ai_orchestrator
    from services.approval_queue_service import ApprovalQueueService, ApprovalType, ApprovalPriority
    from services.websocket_manager import websocket_manager
    from openai import AsyncOpenAI
    DEPENDENCIES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI workflow dependencies not available: {e}")
    DEPENDENCIES_AVAILABLE = False

class AIWorkflowService:
    """
    Service that integrates AI workflows with the broader platform
    """

    def __init__(self, database_url: str, openai_api_key: str = None):
        self.database_url = database_url
        self.openai_api_key = openai_api_key

        if DEPENDENCIES_AVAILABLE:
            self.orchestrator = ai_orchestrator
            if self.orchestrator is None:
                logger.warning(
                    "AI orchestrator disabled. Enable the ai_agents_enabled feature flag "
                    "and configure OpenAI credentials to activate workflows."
                )
            elif openai_api_key:
                self.orchestrator.client = AsyncOpenAI(api_key=openai_api_key)
        else:
            self.orchestrator = None

        # Enterprise persistence and resilience
        from .workflow_persistence_service import workflow_persistence_service
        self.persistence_service = workflow_persistence_service

        from .resilience_patterns import ResilienceManager, BulkheadConfig, BulkheadType
        self.resilience_manager = ResilienceManager()

        from .error_handling_framework import ErrorHandler
        self.error_handler = ErrorHandler()

        # Register bulkhead for AI workflow operations
        self.resilience_manager.create_bulkhead(BulkheadConfig(
            name="ai_workflow_integration",
            bulkhead_type=BulkheadType.THREAD_POOL,
            max_concurrent=8
        ))

    async def initialize(self):
        """Initialize the AI workflow service"""
        if self.orchestrator:
            try:
                logger.info("✅ AI Workflow Service ready (agents provisioned on-demand)")
            except Exception as e:
                logger.error(f"Failed to initialize AI workflow service: {e}")
                raise
        else:
            raise RuntimeError(
                "AI Workflow Service cannot initialize: AI orchestrator unavailable. "
                "Enable the ai_agents_enabled feature flag and configure OpenAI agents."
            )

    async def start_prospect_analysis_workflow(self,
                                             organization_id: int,
                                             user_id: int,
                                             prospect_data: Dict[str, Any]) -> str:
        """Start an AI-powered prospect analysis workflow"""

        if not self.orchestrator:
            raise RuntimeError(
                "AI orchestrator not available. Enable the ai_agents_enabled feature flag "
                "and configure OpenAI agents."
            )

        try:
            # Convert organization_id to string for tenant_id
            tenant_id = str(organization_id)

            await self.orchestrator.initialize_agents(organization_id)

            # Start the AI orchestration workflow
            workflow_id = await self.orchestrator.start_workflow(
                prospect_data=prospect_data,
                tenant_id=tenant_id
            )

            logger.info(f"Started AI prospect analysis workflow {workflow_id} for org {organization_id}")
            return workflow_id

        except Exception as e:
            logger.error(f"Failed to start prospect analysis workflow: {e}")
            raise

    async def start_email_generation_workflow(self,
                                            organization_id: int,
                                            user_id: int,
                                            prospect_data: Dict[str, Any],
                                            connection_context: Dict[str, Any] = None) -> str:
        """Start an AI-powered email generation workflow"""

        workflow_id = str(uuid.uuid4())

        if not self.orchestrator:
            raise RuntimeError(
                "AI orchestrator not available. Enable the ai_agents_enabled feature flag "
                "and configure OpenAI agents."
            )

        try:
            await self.orchestrator.initialize_agents(organization_id)

            # Enhance prospect data with connection context
            enriched_data = prospect_data.copy()
            if connection_context:
                enriched_data["connection_context"] = connection_context

            # Start workflow at email generation stage
            tenant_id = str(organization_id)
            context = {
                "workflow_id": workflow_id,
                "tenant_id": tenant_id,
                "prospect_data": enriched_data,
                "current_stage": "email_generation"
            }

            self.orchestrator.active_workflows[workflow_id] = context

            # Jump directly to email composition
            await self.orchestrator._execute_stage(workflow_id, self.orchestrator.WorkflowStage.EMAIL_GENERATION)

            logger.info(f"Started AI email generation workflow {workflow_id} for org {organization_id}")
            return workflow_id

        except Exception as e:
            logger.error(f"Failed to start email generation workflow: {e}")
            raise

    async def handle_approval_decision(self,
                                     approval_id: str,
                                     decision: str,
                                     approved_by: int,
                                     notes: str = None) -> Dict[str, Any]:
        """Handle approval decision and continue AI workflow"""

        try:
            # Use bulkhead for approval decision handling
            async with self.resilience_manager.get_bulkhead("ai_workflow_integration"):
                # Find workflow associated with this approval from enterprise persistence
                workflow_data = await self.persistence_service.get_workflow_by_approval_id(approval_id)
                workflow_id = workflow_data.get('workflow_id') if workflow_data else None

                if not workflow_id:
                    logger.warning(f"No workflow found for approval {approval_id}")
                    return {"status": "error", "message": "Workflow not found"}

                if self.orchestrator:
                    # Continue the AI workflow based on decision
                    await self.orchestrator.handle_approval_decision(
                        workflow_id=workflow_id,
                        approval_id=approval_id,
                        decision=decision,
                        notes=notes
                    )

                logger.info(f"Handled approval decision {decision} for workflow {workflow_id}")

                return {
                    "status": "success",
                    "workflow_id": workflow_id,
                    "decision": decision
                }

        except Exception as e:
            error_context = {
                'approval_id': approval_id,
                'decision': decision,
                'approved_by': approved_by
            }

            # Import ErrorCategory and ErrorSeverity from ErrorHandler
            from .error_handling_framework import ErrorCategory, ErrorSeverity

            await self.error_handler.handle_error(
                error=e,
                operation="handle_approval_decision",
                context=error_context,
                category=ErrorCategory.WORKFLOW_ERROR,
                severity=ErrorSeverity.HIGH
            )
            logger.error(f"Failed to handle approval decision: {e}")
            return {"status": "error", "message": str(e)}

    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get the current status of an AI workflow"""

        if not self.orchestrator:
            raise RuntimeError("AI orchestrator not available. Please ensure OpenAI API key is configured and dependencies are installed.")

        try:
            return await self.orchestrator.get_workflow_status(workflow_id)
        except Exception as e:
            logger.error(f"Failed to get workflow status: {e}")
            return None

    async def list_active_workflows(self, organization_id: int) -> List[Dict[str, Any]]:
        """List all active AI workflows for an organization"""

        if not self.orchestrator:
            raise RuntimeError("AI orchestrator not available. Please ensure OpenAI API key is configured and dependencies are installed.")

        try:
            # Get workflows from enterprise persistence instead of memory
            workflows = await self.persistence_service.get_workflows_by_organization(organization_id)
            active_workflows = []

            for workflow_data in workflows:
                if workflow_data.get('status') in ['running', 'paused', 'pending']:
                    workflow_info = await self.get_workflow_status(workflow_data['workflow_id'])
                    if workflow_info:
                        active_workflows.append(workflow_info)

            return active_workflows

        except Exception as e:
            logger.error(f"Failed to list active workflows: {e}")
            return []

    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel an active AI workflow"""

        if not self.orchestrator:
            raise RuntimeError("AI orchestrator not available. Please ensure OpenAI API key is configured and dependencies are installed.")

        try:
            result = await self.orchestrator.cancel_workflow(workflow_id)

            # Update workflow status in enterprise persistence
            if result:
                await self.persistence_service.update_workflow_status(
                    workflow_id=workflow_id,
                    status="cancelled",
                    error_message="Cancelled by user request"
                )

            return result

        except Exception as e:
            logger.error(f"Failed to cancel workflow: {e}")
            return False

    async def analyze_prospect_with_ai(self,
                                     organization_id: int,
                                     prospect_data: Dict[str, Any]) -> Dict[str, Any]:
        """Direct AI analysis of a prospect (without full workflow)"""

        if not self.orchestrator:
            raise RuntimeError("AI orchestrator not available. Please ensure OpenAI API key is configured and dependencies are installed.")

        try:
            # Use the prospect analyzer directly
            analysis = await self.orchestrator._analyze_company_profile({
                "company_name": prospect_data.get("company"),
                "domain": prospect_data.get("domain"),
                "industry": prospect_data.get("industry")
            })

            return analysis

        except Exception as e:
            logger.error(f"Direct prospect analysis failed: {e}")
            return {
                "error": str(e),
                "engagement_score": 50,
                "business_fit": "unknown"
            }

    async def generate_introduction_email(self,
                                        organization_id: int,
                                        prospect_data: Dict[str, Any],
                                        context_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Generate an introduction email using AI (without full workflow)"""

        if not self.orchestrator:
            raise RuntimeError("AI orchestrator not available. Please ensure OpenAI API key is configured and dependencies are installed.")

        try:
            # Use the email composer directly
            email_content = await self.orchestrator._compose_introduction_email({
                "prospect_profile": prospect_data,
                "business_context": context_data or {},
                "email_style": "professional"
            })

            return email_content

        except Exception as e:
            logger.error(f"Direct email generation failed: {e}")
            return {
                "error": str(e),
                "subject": "Introduction",
                "body": "AI email generation unavailable"
            }

    async def get_ai_insights(self, organization_id: int, data_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Get AI insights for various data types"""

        insights_handlers = {
            "prospect": self.analyze_prospect_with_ai,
            "email": self.generate_introduction_email,
            "network": self._analyze_network_connections,
            "risk": self._assess_communication_risk
        }

        handler = insights_handlers.get(data_type)
        if handler:
            try:
                return await handler(organization_id, data)
            except Exception as e:
                logger.error(f"AI insights generation failed for {data_type}: {e}")
                return {"error": str(e)}
        else:
            return {"error": f"Unknown insight type: {data_type}"}

    async def _analyze_network_connections(self, organization_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze network connections between prospect and team"""
        return {
            "connection_strength": 0,
            "mutual_connections": 0,
            "introduction_paths": [],
            "relationship_quality": "unknown"
        }

    async def _assess_communication_risk(self, organization_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """Assess risk of communication approach"""
        return {
            "risk_score": 0,
            "risk_factors": [],
            "compliance_status": "unknown",
            "recommendations": []
        }

# Global service instance
ai_workflow_service = AIWorkflowService(
    database_url="postgresql://vouchlink_ai_user:G0cKKzLekD8EYygLMkymwoKlU3wdBqhk@dpg-d2f3ne2li9vc73bf5gg0-a.oregon-postgres.render.com/VouchLink-AIVouchLink AI"
)
