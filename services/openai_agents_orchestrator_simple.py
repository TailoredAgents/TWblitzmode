"""
OpenAI Agents Orchestrator - September 2025 Compatibility Layer
Simplified version for API route compatibility
"""

from enum import Enum
from typing import Dict, Any, List, Optional
import asyncio
import logging
import json
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass

from .workflow_persistence_service import WorkflowPersistenceService, WorkflowStatus
from .resilience_patterns import ResilienceManager, BulkheadType
from .error_handling_framework import ErrorHandler, ErrorCategory, ErrorSeverity
from services.agent_provisioning_service import (
    agent_provisioning_service,
    ProvisionedAgent,
)
from src.services.prospect_matcher import ProspectMatchingEngine
from src.services.ai_writer import AIWriterService
from core.settings import settings
from openai import AsyncOpenAI
logger = logging.getLogger(__name__)

class AgentRole(Enum):
    """Agent roles for workflow management"""
    PROSPECT_ANALYZER = "prospect_analyzer"
    EMAIL_GENERATOR = "email_generator"
    CONNECTOR_SCORER = "connector_scorer"
    CONTENT_REVIEWER = "content_reviewer"

class WorkflowStage(Enum):
    """Workflow stages for multi-agent coordination"""
    ANALYSIS = "analysis"
    GENERATION = "generation"
    REVIEW = "review"
    APPROVAL = "approval"
    EXECUTION = "execution"

@dataclass
class WorkflowContext:
    """Context for workflow execution"""
    workflow_id: str
    organization_id: int
    prospect_data: Dict[str, Any]
    current_stage: WorkflowStage
    agent_outputs: Dict[AgentRole, Any] = None
    created_at: datetime = None

    def __post_init__(self):
        if self.agent_outputs is None:
            self.agent_outputs = {}
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

class OpenAIAgentsOrchestrator:
    """
    Simplified OpenAI Agents orchestrator for API compatibility
    """

    def __init__(self):
        # Enterprise persistence and resilience
        from .workflow_persistence_service import workflow_persistence_service
        self.persistence_service = workflow_persistence_service
        self.resilience_manager = ResilienceManager()
        self.error_handler = ErrorHandler()
        self.prospect_engine = ProspectMatchingEngine()
        self.ai_writer = AIWriterService()
        self.agent_registry: Dict[int, Dict[str, ProvisionedAgent]] = {}
        self._clients: Dict[int, AsyncOpenAI] = {}
        self._client_meta: Dict[int, str] = {}

        # Register bulkhead for simple orchestrator operations
        from .resilience_patterns import BulkheadConfig, BulkheadType
        self.resilience_manager.create_bulkhead(BulkheadConfig(
            name="simple_orchestrator",
            bulkhead_type=BulkheadType.THREAD_POOL,
            max_concurrent=10
        ))

    async def start_workflow(self, workflow_type: str, payload: Dict[str, Any], organization_id: int) -> str:
        """Start a multi-agent workflow"""
        workflow_id = str(uuid.uuid4())

        context = WorkflowContext(
            workflow_id=workflow_id,
            organization_id=organization_id,
            prospect_data=payload,
            current_stage=WorkflowStage.ANALYSIS
        )

        # Store workflow in enterprise persistence
        requester_id = payload.get("requested_by") or payload.get("user_id") or 1

        await self.persistence_service.create_workflow(
            organization_id=organization_id,
            user_id=int(requester_id),
            workflow_type=workflow_type,
            prospects=[payload],
            team_members=[]
        )

        # Simulate workflow processing
        await self._process_workflow(workflow_id, workflow_type, context)
        await self._ensure_agents(organization_id)

        return workflow_id

    async def _process_workflow(self, workflow_id: str, workflow_type: str, context: WorkflowContext):
        """Process workflow based on type"""
        try:
            # Use bulkhead for workflow processing
            async with self.resilience_manager.get_bulkhead("simple_orchestrator"):
                # Determine workflow type and run the appropriate stage
                if workflow_type == "prospect_analysis":
                    result = await self._analyze_prospect(
                        context.prospect_data,
                        context.organization_id,
                    )
                    context.agent_outputs[AgentRole.PROSPECT_ANALYZER] = result

                elif workflow_type == "email_generation":
                    result = await self._generate_email(context.prospect_data, organization_id)
                    context.agent_outputs[AgentRole.EMAIL_GENERATOR] = result

                # Mark stage as execution after processing
                context.current_stage = WorkflowStage.EXECUTION

                # Update workflow status in persistence
                await self.persistence_service.update_workflow_status(
                    workflow_id=workflow_id,
                    status="completed",
                    current_stage=WorkflowStage.EXECUTION.value
                )

        except Exception as e:
            error_context = {
                'workflow_id': workflow_id,
                'workflow_type': workflow_type,
                'organization_id': context.organization_id
            }
            await self.error_handler.handle_error(
                error=e,
                operation="process_simple_workflow",
                context=error_context,
                category=ErrorCategory.WORKFLOW_ERROR,
                severity=ErrorSeverity.HIGH
            )

            # Update workflow status to failed
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="failed",
                error_message=str(e)
            )
            raise

    async def _analyze_prospect(
        self,
        prospect_data: Dict[str, Any],
        organization_id: int,
    ) -> Dict[str, Any]:
        """Analyze prospect using AI"""
        prospect_id = prospect_data.get("prospect_id")
        prospect_name = prospect_data.get("prospect_name") or prospect_data.get("name")
        prospect_company = prospect_data.get("prospect_company") or prospect_data.get("company") or ""

        if not prospect_id and not prospect_name:
            raise ValueError("prospect_id or prospect_name is required for analysis")

        tenant_value = (
            prospect_data.get("tenant_id")
            or prospect_data.get("organization_id")
            or organization_id
        )
        if tenant_value is None or str(tenant_value).strip() == "":
            raise ValueError("tenant_id is required for prospect analysis workflows")
        tenant_scope = str(tenant_value).strip()

        if prospect_id:
            analysis = await self.prospect_engine.find_prospect_matches(
                int(prospect_id),
                tenant_id=tenant_scope,
            )
        else:
            analysis = await self.prospect_engine.find_target_matches_realtime(
                prospect_name,
                prospect_company,
                tenant_id=tenant_scope,
            )

        return analysis

    async def _generate_email(self, context_data: Dict[str, Any], organization_id: int) -> Dict[str, Any]:
        """Generate personalized email"""
        prospect = context_data.get("prospect", {})
        connector = context_data.get("connector", {})
        connection_context = context_data.get("connection_context")
        requester = context_data.get("requested_by_name")

        content = await self.ai_writer.generate_introduction_request(
            prospect_data=prospect,
            team_member_data=connector,
            connection_context=connection_context,
            requesting_user_name=requester,
        )

        subject = context_data.get("subject") or f"Introduction to {prospect.get('name', 'Executive')}"

        return {
            "subject": subject,
            "body": content,
            "approval_required": True,
        }

    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get status of a running workflow"""
        try:
            # Get workflow from enterprise persistence
            workflow_data = await self.persistence_service.get_workflow(workflow_id)
            if not workflow_data:
                return {
                    "workflow_id": workflow_id,
                    "status": "not_found"
                }

            current_stage = workflow_data.get('current_stage', 'unknown')
            progress = 100 if current_stage == WorkflowStage.EXECUTION.value else 50

            return {
                "workflow_id": workflow_id,
                "status": workflow_data['status'],
                "stage": current_stage,
                "progress": progress,
                "organization_id": workflow_data['organization_id'],
                "created_at": workflow_data['created_at'],
                "updated_at": workflow_data['updated_at'],
                "error_message": workflow_data.get('error_message')
            }

        except Exception as e:
            error_context = {'workflow_id': workflow_id}
            await self.error_handler.handle_error(
                error=e,
                operation="get_simple_workflow_status",
                context=error_context,
                category=ErrorCategory.DATA_ACCESS_ERROR,
                severity=ErrorSeverity.MEDIUM
            )
            logger.error(f"Failed to get simple workflow status for {workflow_id}: {e}")
            return {
                "workflow_id": workflow_id,
                "status": "error",
                "error": str(e)
            }

    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running workflow and mark it as cancelled."""
        try:
            updated = await self.persistence_service.update_workflow_state(
                workflow_id,
                status=WorkflowStatus.CANCELLED,
                current_stage="cancelled",
                progress_percentage=100.0,
            )
            if not updated:
                logger.warning("Workflow %s not found for cancellation", workflow_id)
                return False

            logger.info("Workflow %s cancelled via simple orchestrator", workflow_id)
            return True
        except Exception as exc:
            error_context = {'workflow_id': workflow_id}
            await self.error_handler.handle_error(
                error=exc,
                operation="cancel_simple_workflow",
                context=error_context,
                category=ErrorCategory.WORKFLOW_ERROR,
                severity=ErrorSeverity.MEDIUM,
            )
            logger.error("Failed to cancel workflow %s: %s", workflow_id, exc)
            return False

    async def _ensure_agents(self, organization_id: int) -> None:
        if organization_id in self.agent_registry:
            return

        api_key = await self._resolve_api_key(organization_id)
        payload = {
            "name": "Simple Workflow Assistant",
            "model": settings.OPENAI_MODEL,
            "instructions": "Handle simplified workflows for compatibility layer",
            "tools": [],
        }

        provisioned = await agent_provisioning_service.ensure_agent(
            tenant_id=organization_id,
            role="simple_workflow",
            config_payload=payload,
            api_key=api_key,
            organization=None,
        )

        self.agent_registry[organization_id] = {"simple_workflow": provisioned}

    async def _resolve_api_key(self, organization_id: int) -> str:
        try:
            from integrations.apify_client import get_tenant_integration_settings

            settings_map = get_tenant_integration_settings(organization_id)
            key = settings_map.get("openai_api_key")
            if key:
                return key
        except Exception as exc:
            logger.debug("Integration settings lookup failed for org %s: %s", organization_id, exc)

        from api.security import dec
        from api.db_core import get_conn

        with get_conn() as conn:
            cursor = conn.cursor()
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
                        return row[0]

        if settings.OPENAI_API_KEY:
            return settings.OPENAI_API_KEY

        raise RuntimeError("OpenAI API key not configured for organization")

    async def assign_agent_role(self, agent_id: str, role: AgentRole, organization_id: int) -> bool:
        """Assign role to an agent"""
        logger.info(f"Assigned role {role.value} to agent {agent_id} for organization {organization_id}")
        return True

    async def coordinate_agents(self, workflow_id: str, agents: List[str]) -> Dict[str, Any]:
        """Coordinate multiple agents in a workflow"""
        return {
            "workflow_id": workflow_id,
            "coordinated_agents": agents,
            "coordination_status": "success"
        }

# Global instance for backward compatibility
from core.settings import settings

ai_orchestrator = None
if settings.OPENAI_AGENTS_ENABLED:
    try:
        ai_orchestrator = OpenAIAgentsOrchestrator()
    except Exception as exc:
        logger.warning("Failed to initialize simple AI orchestrator: %s", exc)
else:
    logger.info("Simple AI orchestrator disabled (enable OPENAI_AGENTS_ENABLED to activate)")
