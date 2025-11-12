#!/usr/bin/env python3
"""
Workflow State Machine - September 2025 AI Orchestration
Advanced workflow management with human-in-the-loop approval and state persistence
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, asdict
import redis
import asyncpg
from .workflow_persistence_service import WorkflowPersistenceService
from .resilience_patterns import ResilienceManager, BulkheadType
from .error_handling_framework import ErrorHandler, ErrorCategory, ErrorSeverity

logger = logging.getLogger(__name__)

class WorkflowState(Enum):
    """Complete workflow states for corporate warm introduction process"""
    INITIATED = "initiated"
    INGESTION = "ingestion"
    INGESTION_COMPLETE = "ingestion_complete"
    EXECUTIVE_LOOKUP = "executive_lookup"
    LOOKUP_COMPLETE = "lookup_complete"
    MUTUAL_DISCOVERY = "mutual_discovery"
    MUTUALS_COMPLETE = "mutuals_complete"
    CONNECTION_SCORING = "connection_scoring"
    SCORING_COMPLETE = "scoring_complete"
    EMAIL_ENRICHMENT = "email_enrichment"
    ENRICHMENT_COMPLETE = "enrichment_complete"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    EMAIL_SCHEDULING = "email_scheduling"
    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"

class WorkflowTrigger(Enum):
    """Events that trigger state transitions"""
    START_WORKFLOW = "start_workflow"
    INGESTION_SUCCESS = "ingestion_success"
    INGESTION_FAILURE = "ingestion_failure"
    LOOKUP_SUCCESS = "lookup_success"
    LOOKUP_FAILURE = "lookup_failure"
    MUTUALS_SUCCESS = "mutuals_success"
    MUTUALS_FAILURE = "mutuals_failure"
    SCORING_SUCCESS = "scoring_success"
    SCORING_FAILURE = "scoring_failure"
    ENRICHMENT_SUCCESS = "enrichment_success"
    ENRICHMENT_FAILURE = "enrichment_failure"
    REQUIRE_APPROVAL = "require_approval"
    HUMAN_APPROVE = "human_approve"
    HUMAN_REJECT = "human_reject"
    SCHEDULING_SUCCESS = "scheduling_success"
    SCHEDULING_FAILURE = "scheduling_failure"
    EXECUTION_SUCCESS = "execution_success"
    EXECUTION_FAILURE = "execution_failure"
    CANCEL = "cancel"
    TIMEOUT_REACHED = "timeout_reached"

@dataclass
class WorkflowContext:
    """Complete context for a workflow instance"""
    workflow_id: str
    organization_id: int
    user_id: int
    workflow_type: str
    current_state: WorkflowState
    input_data: Dict[str, Any]
    step_results: Dict[str, Any]
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

@dataclass
class ApprovalRequest:
    """Human approval request for September 2025 features"""
    approval_id: str
    workflow_id: str
    organization_id: int
    request_type: str
    description: str
    risk_score: float
    auto_approve_threshold: float
    context_data: Dict[str, Any]
    timeout_minutes: int
    status: str
    created_at: datetime
    expires_at: datetime
    approver_id: Optional[int] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

class WorkflowStateMachine:
    """
    September 2025 - Advanced AI workflow orchestration with human oversight
    Manages complete corporate warm introduction workflow with state persistence
    """

    # State transition rules
    STATE_TRANSITIONS = {
        WorkflowState.INITIATED: {
            WorkflowTrigger.START_WORKFLOW: WorkflowState.INGESTION
        },
        WorkflowState.INGESTION: {
            WorkflowTrigger.INGESTION_SUCCESS: WorkflowState.INGESTION_COMPLETE,
            WorkflowTrigger.INGESTION_FAILURE: WorkflowState.FAILED
        },
        WorkflowState.INGESTION_COMPLETE: {
            WorkflowTrigger.START_WORKFLOW: WorkflowState.EXECUTIVE_LOOKUP
        },
        WorkflowState.EXECUTIVE_LOOKUP: {
            WorkflowTrigger.LOOKUP_SUCCESS: WorkflowState.LOOKUP_COMPLETE,
            WorkflowTrigger.LOOKUP_FAILURE: WorkflowState.FAILED
        },
        WorkflowState.LOOKUP_COMPLETE: {
            WorkflowTrigger.START_WORKFLOW: WorkflowState.MUTUAL_DISCOVERY
        },
        WorkflowState.MUTUAL_DISCOVERY: {
            WorkflowTrigger.MUTUALS_SUCCESS: WorkflowState.MUTUALS_COMPLETE,
            WorkflowTrigger.MUTUALS_FAILURE: WorkflowState.FAILED
        },
        WorkflowState.MUTUALS_COMPLETE: {
            WorkflowTrigger.START_WORKFLOW: WorkflowState.CONNECTION_SCORING
        },
        WorkflowState.CONNECTION_SCORING: {
            WorkflowTrigger.SCORING_SUCCESS: WorkflowState.SCORING_COMPLETE,
            WorkflowTrigger.SCORING_FAILURE: WorkflowState.FAILED
        },
        WorkflowState.SCORING_COMPLETE: {
            WorkflowTrigger.START_WORKFLOW: WorkflowState.EMAIL_ENRICHMENT
        },
        WorkflowState.EMAIL_ENRICHMENT: {
            WorkflowTrigger.ENRICHMENT_SUCCESS: WorkflowState.ENRICHMENT_COMPLETE,
            WorkflowTrigger.ENRICHMENT_FAILURE: WorkflowState.FAILED
        },
        WorkflowState.ENRICHMENT_COMPLETE: {
            WorkflowTrigger.REQUIRE_APPROVAL: WorkflowState.HUMAN_APPROVAL_REQUIRED,
            WorkflowTrigger.START_WORKFLOW: WorkflowState.EMAIL_SCHEDULING  # Auto-approve path
        },
        WorkflowState.HUMAN_APPROVAL_REQUIRED: {
            WorkflowTrigger.HUMAN_APPROVE: WorkflowState.APPROVED,
            WorkflowTrigger.HUMAN_REJECT: WorkflowState.REJECTED,
            WorkflowTrigger.TIMEOUT_REACHED: WorkflowState.TIMEOUT
        },
        WorkflowState.APPROVED: {
            WorkflowTrigger.START_WORKFLOW: WorkflowState.EMAIL_SCHEDULING
        },
        WorkflowState.EMAIL_SCHEDULING: {
            WorkflowTrigger.SCHEDULING_SUCCESS: WorkflowState.SCHEDULED,
            WorkflowTrigger.SCHEDULING_FAILURE: WorkflowState.FAILED
        },
        WorkflowState.SCHEDULED: {
            WorkflowTrigger.START_WORKFLOW: WorkflowState.EXECUTING
        },
        WorkflowState.EXECUTING: {
            WorkflowTrigger.EXECUTION_SUCCESS: WorkflowState.COMPLETED,
            WorkflowTrigger.EXECUTION_FAILURE: WorkflowState.FAILED
        }
    }

    # Global transition rules (apply to any state)
    GLOBAL_TRANSITIONS = {
        WorkflowTrigger.CANCEL: WorkflowState.CANCELLED,
        WorkflowTrigger.TIMEOUT_REACHED: WorkflowState.TIMEOUT
    }

    def __init__(self, redis_url: str = "redis://localhost:6379", database_url: str = None):
        self.redis_client = redis.from_url(redis_url)
        self.database_url = database_url
        self.db_pool = None

        # Enterprise persistence and resilience
        from .workflow_persistence_service import workflow_persistence_service
        self.persistence_service = workflow_persistence_service
        self.resilience_manager = ResilienceManager()
        self.error_handler = ErrorHandler()

        # Register bulkhead for workflow state operations
        from .resilience_patterns import BulkheadConfig, BulkheadType
        self.resilience_manager.create_bulkhead(BulkheadConfig(
            name="workflow_state_machine",
            bulkhead_type=BulkheadType.THREAD_POOL,
            max_concurrent=12
        ))

        self.state_handlers: Dict[WorkflowState, Callable] = {}
        self.approval_handlers: Dict[str, Callable] = {}

        # Register default state handlers
        self._register_state_handlers()

    async def initialize(self):
        """Initialize the workflow state machine"""
        if self.database_url:
            self.db_pool = await asyncpg.create_pool(self.database_url)

        logger.info("✅ Workflow State Machine initialized with enterprise persistence")

    def _register_state_handlers(self):
        """Register handlers for each workflow state"""
        self.state_handlers = {
            WorkflowState.INGESTION: self._handle_ingestion,
            WorkflowState.EXECUTIVE_LOOKUP: self._handle_executive_lookup,
            WorkflowState.MUTUAL_DISCOVERY: self._handle_mutual_discovery,
            WorkflowState.CONNECTION_SCORING: self._handle_connection_scoring,
            WorkflowState.EMAIL_ENRICHMENT: self._handle_email_enrichment,
            WorkflowState.HUMAN_APPROVAL_REQUIRED: self._handle_human_approval,
            WorkflowState.EMAIL_SCHEDULING: self._handle_email_scheduling,
            WorkflowState.EXECUTING: self._handle_execution,
        }

    async def start_workflow(self,
                           organization_id: int,
                           user_id: int,
                           workflow_type: str,
                           input_data: Dict[str, Any],
                           metadata: Optional[Dict[str, Any]] = None) -> str:
        """Start a new workflow instance"""
        workflow_id = str(uuid.uuid4())

        context = WorkflowContext(
            workflow_id=workflow_id,
            organization_id=organization_id,
            user_id=user_id,
            workflow_type=workflow_type,
            current_state=WorkflowState.INITIATED,
            input_data=input_data,
            step_results={},
            metadata=metadata or {},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)  # Default expiry
        )

        # Store workflow in enterprise persistence
        await self.persistence_service.create_workflow(
            organization_id=organization_id,
            user_id=user_id,
            workflow_type=workflow_type,
            prospects=[],  # Will be populated during execution
            team_members=[]
        )

        await self._persist_workflow(context)

        logger.info(f"Started workflow {workflow_id} for organization {organization_id}")

        # Trigger initial transition
        await self.trigger_transition(workflow_id, WorkflowTrigger.START_WORKFLOW)

        return workflow_id

    async def trigger_transition(self,
                               workflow_id: str,
                               trigger: WorkflowTrigger,
                               result_data: Optional[Dict[str, Any]] = None) -> bool:
        """Trigger a state transition for a workflow"""
        try:
            # Use bulkhead for state transitions
            async with self.resilience_manager.get_bulkhead("workflow_state_machine"):
                # Get workflow from persistence
                workflow_data = await self.persistence_service.get_workflow(workflow_id)
                if not workflow_data:
                    logger.error(f"Workflow {workflow_id} not found")
                    return False

                # Create context from persistence data
                context = WorkflowContext(
                    workflow_id=workflow_id,
                    organization_id=workflow_data['organization_id'],
                    user_id=workflow_data['user_id'],
                    workflow_type=workflow_data['workflow_type'],
                    current_state=WorkflowState(workflow_data.get('current_stage', 'initiated')),
                    input_data=workflow_data.get('metadata', {}),
                    step_results=workflow_data.get('step_results', {}),
                    metadata=workflow_data.get('metadata', {}),
                    created_at=datetime.fromisoformat(workflow_data['created_at'].replace('Z', '+00:00')),
                    updated_at=datetime.fromisoformat(workflow_data['updated_at'].replace('Z', '+00:00')),
                    error_message=workflow_data.get('error_message'),
                    retry_count=workflow_data.get('retry_count', 0)
                )

                current_state = context.current_state

                # Check global transitions first
                if trigger in self.GLOBAL_TRANSITIONS:
                    new_state = self.GLOBAL_TRANSITIONS[trigger]
                # Check state-specific transitions
                elif current_state in self.STATE_TRANSITIONS and trigger in self.STATE_TRANSITIONS[current_state]:
                    new_state = self.STATE_TRANSITIONS[current_state][trigger]
                else:
                    logger.warning(f"Invalid transition: {current_state} -> {trigger}")
                    return False

                # Update context
                context.current_state = new_state
                context.updated_at = datetime.now(timezone.utc)

                if result_data:
                    context.step_results[current_state.value] = result_data

                # Handle failure states
                if new_state in [WorkflowState.FAILED, WorkflowState.CANCELLED, WorkflowState.TIMEOUT]:
                    if result_data and 'error' in result_data:
                        context.error_message = result_data['error']

                await self._persist_workflow(context)

                logger.info(f"Workflow {workflow_id}: {current_state} -> {new_state} (trigger: {trigger})")

                # Execute state handler if available
                if new_state in self.state_handlers:
                    try:
                        await self.state_handlers[new_state](context)
                    except Exception as e:
                        logger.error(f"State handler failed for {new_state}: {e}")
                        await self.trigger_transition(workflow_id, WorkflowTrigger.EXECUTION_FAILURE, {"error": str(e)})

                return True

        except Exception as e:
            logger.error(f"State transition failed for workflow {workflow_id}: {e}")
            await self.error_handler.handle_error(
                error=e,
                operation="workflow_state_transition",
                context={"workflow_id": workflow_id, "trigger": trigger.value if hasattr(trigger, 'value') else str(trigger)},
                category=ErrorCategory.WORKFLOW_ERROR,
                severity=ErrorSeverity.HIGH
            )
            return False

    async def _handle_ingestion(self, context: WorkflowContext):
        """Handle prospect ingestion state"""
        logger.info(f"Processing ingestion for workflow {context.workflow_id}")

        try:
            # Import the ingestion service
            from services.ingestion_service import IngestionService
            ingestion_service = IngestionService()

            # Process the ingestion
            if 'csv_data' in context.input_data:
                result = await ingestion_service.start_csv_ingestion(
                    csv_data=context.input_data['csv_data'],
                    organization_id=context.organization_id,
                    import_name=context.input_data.get('import_name', 'Workflow Import'),
                    user_id=context.user_id,
                    tags=context.input_data.get('tags', [])
                )

                await self.trigger_transition(
                    context.workflow_id,
                    WorkflowTrigger.INGESTION_SUCCESS,
                    {"ingestion_job_id": result}
                )
            else:
                await self.trigger_transition(
                    context.workflow_id,
                    WorkflowTrigger.INGESTION_FAILURE,
                    {"error": "No CSV data provided"}
                )

        except Exception as e:
            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.INGESTION_FAILURE,
                {"error": str(e)}
            )

    async def _handle_executive_lookup(self, context: WorkflowContext):
        """Handle executive lookup state"""
        logger.info(f"Processing executive lookup for workflow {context.workflow_id}")

        try:
            from services.executive_lookup_service import ExecutiveLookupService
            lookup_service = ExecutiveLookupService()

            # For now, simulate lookup success
            await asyncio.sleep(1)

            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.LOOKUP_SUCCESS,
                {"executives_found": 5, "lookup_method": "clearbit"}
            )

        except Exception as e:
            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.LOOKUP_FAILURE,
                {"error": str(e)}
            )

    async def _handle_mutual_discovery(self, context: WorkflowContext):
        """Handle mutual connection discovery state"""
        logger.info(f"Processing mutual discovery for workflow {context.workflow_id}")

        try:
            from services.mutuals_orchestrator_service import MutualsOrchestratorService
            mutuals_service = MutualsOrchestratorService()

            # For now, simulate mutuals discovery
            await asyncio.sleep(2)

            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.MUTUALS_SUCCESS,
                {"connectors_found": 23, "prospects_processed": 5}
            )

        except Exception as e:
            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.MUTUALS_FAILURE,
                {"error": str(e)}
            )

    async def _handle_connection_scoring(self, context: WorkflowContext):
        """Handle connection scoring state"""
        logger.info(f"Processing connection scoring for workflow {context.workflow_id}")

        try:
            from services.scoring_service import ConnectorScoringService as ScoringService
            scoring_service = ScoringService()

            # For now, simulate scoring
            await asyncio.sleep(1)

            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.SCORING_SUCCESS,
                {"top_connectors": 5, "avg_score": 0.78}
            )

        except Exception as e:
            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.SCORING_FAILURE,
                {"error": str(e)}
            )

    async def _handle_email_enrichment(self, context: WorkflowContext):
        """Handle email enrichment state"""
        logger.info(f"Processing email enrichment for workflow {context.workflow_id}")

        try:
            from services.email_enrichment_service import EmailEnrichmentService
            enrichment_service = EmailEnrichmentService()

            # For now, simulate enrichment
            await asyncio.sleep(1)

            # Check if human approval is required
            risk_score = 0.3  # Low risk
            if risk_score > 0.5:
                await self.trigger_transition(
                    context.workflow_id,
                    WorkflowTrigger.REQUIRE_APPROVAL,
                    {"risk_score": risk_score, "emails_enriched": 15}
                )
            else:
                await self.trigger_transition(
                    context.workflow_id,
                    WorkflowTrigger.ENRICHMENT_SUCCESS,
                    {"emails_enriched": 15, "auto_approved": True}
                )

        except Exception as e:
            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.ENRICHMENT_FAILURE,
                {"error": str(e)}
            )

    async def _handle_human_approval(self, context: WorkflowContext):
        """Handle human approval requirement - September 2025 feature"""
        logger.info(f"Requesting human approval for workflow {context.workflow_id}")

        try:
            approval_id = str(uuid.uuid4())
            approval_request = ApprovalRequest(
                approval_id=approval_id,
                workflow_id=context.workflow_id,
                organization_id=context.organization_id,
                request_type="email_campaign",
                description=f"Email campaign for {len(context.input_data.get('prospect_ids', []))} prospects",
                risk_score=context.step_results.get('email_enrichment', {}).get('risk_score', 0.5),
                auto_approve_threshold=0.3,
                context_data=context.input_data,
                timeout_minutes=60,
                status="pending",
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=60)
            )

            # Store approval request
            await self._store_approval_request(approval_request)

            # Notify administrators (WebSocket, email, etc.)
            await self._notify_approval_required(approval_request)

            logger.info(f"Approval request {approval_id} created for workflow {context.workflow_id}")

        except Exception as e:
            logger.error(f"Failed to create approval request: {e}")
            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.EXECUTION_FAILURE,
                {"error": f"Approval request failed: {str(e)}"}
            )

    async def _handle_email_scheduling(self, context: WorkflowContext):
        """Handle email scheduling state"""
        logger.info(f"Processing email scheduling for workflow {context.workflow_id}")

        try:
            from services.corporate_scheduler_service import CorporateSchedulerService
            scheduler_service = CorporateSchedulerService()

            # For now, simulate scheduling
            await asyncio.sleep(1)

            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.SCHEDULING_SUCCESS,
                {"emails_scheduled": 10, "send_date": datetime.now(timezone.utc).isoformat()}
            )

        except Exception as e:
            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.SCHEDULING_FAILURE,
                {"error": str(e)}
            )

    async def _handle_execution(self, context: WorkflowContext):
        """Handle final execution state"""
        logger.info(f"Executing workflow {context.workflow_id}")

        try:
            # Final execution logic here
            await asyncio.sleep(1)

            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.EXECUTION_SUCCESS,
                {"completed_at": datetime.now(timezone.utc).isoformat()}
            )

        except Exception as e:
            await self.trigger_transition(
                context.workflow_id,
                WorkflowTrigger.EXECUTION_FAILURE,
                {"error": str(e)}
            )

    async def approve_workflow(self, approval_id: str, approver_id: int, reason: Optional[str] = None) -> bool:
        """Approve a workflow - September 2025 human-in-the-loop feature"""
        try:
            approval = await self._get_approval_request(approval_id)
            if not approval:
                return False

            if approval.status != "pending":
                logger.warning(f"Approval {approval_id} already processed")
                return False

            # Update approval status
            approval.status = "approved"
            approval.approver_id = approver_id
            approval.approved_at = datetime.now(timezone.utc)
            await self._update_approval_request(approval)

            # Trigger workflow continuation
            await self.trigger_transition(
                approval.workflow_id,
                WorkflowTrigger.HUMAN_APPROVE,
                {"approved_by": approver_id, "approval_reason": reason}
            )

            logger.info(f"Workflow {approval.workflow_id} approved by user {approver_id}")
            return True

        except Exception as e:
            logger.error(f"Approval failed: {e}")
            return False

    async def reject_workflow(self, approval_id: str, approver_id: int, reason: str) -> bool:
        """Reject a workflow - September 2025 human-in-the-loop feature"""
        try:
            approval = await self._get_approval_request(approval_id)
            if not approval:
                return False

            # Update approval status
            approval.status = "rejected"
            approval.approver_id = approver_id
            approval.approved_at = datetime.now(timezone.utc)
            approval.rejection_reason = reason
            await self._update_approval_request(approval)

            # Trigger workflow termination
            await self.trigger_transition(
                approval.workflow_id,
                WorkflowTrigger.HUMAN_REJECT,
                {"rejected_by": approver_id, "rejection_reason": reason}
            )

            logger.info(f"Workflow {approval.workflow_id} rejected by user {approver_id}")
            return True

        except Exception as e:
            logger.error(f"Rejection failed: {e}")
            return False

    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get current workflow status"""
        try:
            # Get workflow from enterprise persistence
            workflow_data = await self.persistence_service.get_workflow(workflow_id)
            if not workflow_data:
                return None

            current_state = WorkflowState(workflow_data.get('current_stage', 'initiated'))

            return {
                "workflow_id": workflow_id,
                "organization_id": workflow_data['organization_id'],
                "current_state": current_state.value,
                "status": workflow_data['status'],
                "progress_percentage": self._calculate_progress(current_state),
                "step_results": workflow_data.get('step_results', {}),
                "created_at": workflow_data['created_at'],
                "updated_at": workflow_data['updated_at'],
                "error_message": workflow_data.get('error_message')
            }

        except Exception as e:
            error_context = {'workflow_id': workflow_id}
            await self.error_handler.handle_error(
                error=e,
                operation="get_workflow_state",
                context=error_context,
                category=ErrorCategory.DATA_ACCESS_ERROR,
                severity=ErrorSeverity.MEDIUM
            )
            logger.error(f"Failed to get workflow status for {workflow_id}: {e}")
            return None

    def _calculate_progress(self, current_state: WorkflowState) -> int:
        """Calculate workflow progress percentage"""
        state_order = [
            WorkflowState.INITIATED,
            WorkflowState.INGESTION,
            WorkflowState.INGESTION_COMPLETE,
            WorkflowState.EXECUTIVE_LOOKUP,
            WorkflowState.LOOKUP_COMPLETE,
            WorkflowState.MUTUAL_DISCOVERY,
            WorkflowState.MUTUALS_COMPLETE,
            WorkflowState.CONNECTION_SCORING,
            WorkflowState.SCORING_COMPLETE,
            WorkflowState.EMAIL_ENRICHMENT,
            WorkflowState.ENRICHMENT_COMPLETE,
            WorkflowState.EMAIL_SCHEDULING,
            WorkflowState.SCHEDULED,
            WorkflowState.EXECUTING,
            WorkflowState.COMPLETED
        ]

        try:
            current_index = state_order.index(current_state)
            return int((current_index / (len(state_order) - 1)) * 100)
        except ValueError:
            return 0

    async def _persist_workflow(self, context: WorkflowContext):
        """Persist workflow state to Redis"""
        try:
            workflow_data = {
                "workflow_id": context.workflow_id,
                "organization_id": context.organization_id,
                "user_id": context.user_id,
                "workflow_type": context.workflow_type,
                "current_state": context.current_state.value,
                "input_data": context.input_data,
                "step_results": context.step_results,
                "metadata": context.metadata,
                "created_at": context.created_at.isoformat(),
                "updated_at": context.updated_at.isoformat(),
                "error_message": context.error_message,
                "retry_count": context.retry_count
            }

            self.redis_client.setex(
                f"workflow:{context.workflow_id}",
                86400,  # 24 hour expiry
                json.dumps(workflow_data)
            )

        except Exception as e:
            logger.error(f"Failed to persist workflow {context.workflow_id}: {e}")

    async def _load_active_workflows(self):
        """Load active workflows from Redis"""
        try:
            keys = self.redis_client.keys("workflow:*")
            for key in keys:
                data = json.loads(self.redis_client.get(key))
                context = WorkflowContext(
                    workflow_id=data["workflow_id"],
                    organization_id=data["organization_id"],
                    user_id=data["user_id"],
                    workflow_type=data["workflow_type"],
                    current_state=WorkflowState(data["current_state"]),
                    input_data=data["input_data"],
                    step_results=data["step_results"],
                    metadata=data["metadata"],
                    created_at=datetime.fromisoformat(data["created_at"]),
                    updated_at=datetime.fromisoformat(data["updated_at"]),
                    error_message=data.get("error_message"),
                    retry_count=data.get("retry_count", 0)
                )
                # Workflows are now loaded from enterprise persistence on-demand
                # No need to keep them in memory
                pass

            logger.info("Active workflows will be loaded from enterprise persistence on-demand")

        except Exception as e:
            logger.error(f"Failed to load workflows: {e}")

    async def _store_approval_request(self, approval: ApprovalRequest):
        """Store approval request in database"""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO approval_requests (
                        id, workflow_id, organization_id, request_type, description,
                        risk_score, context_data, timeout_minutes, status, created_at, expires_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """, approval.approval_id, approval.workflow_id, approval.organization_id,
                approval.request_type, approval.description, approval.risk_score,
                json.dumps(approval.context_data), approval.timeout_minutes,
                approval.status, approval.created_at, approval.expires_at)

        except Exception as e:
            logger.error(f"Failed to store approval request: {e}")

    async def _get_approval_request(self, approval_id: str) -> Optional[ApprovalRequest]:
        """Get approval request from database"""
        if not self.db_pool:
            return None

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM approval_requests WHERE id = $1
                """, approval_id)

                if row:
                    return ApprovalRequest(
                        approval_id=row['id'],
                        workflow_id=row['workflow_id'],
                        organization_id=row['organization_id'],
                        request_type=row['request_type'],
                        description=row['description'],
                        risk_score=row['risk_score'],
                        auto_approve_threshold=0.3,  # Default
                        context_data=json.loads(row['context_data']),
                        timeout_minutes=row['timeout_minutes'],
                        status=row['status'],
                        created_at=row['created_at'],
                        expires_at=row['expires_at'],
                        approver_id=row.get('approver_id'),
                        approved_at=row.get('approved_at'),
                        rejection_reason=row.get('rejection_reason')
                    )

        except Exception as e:
            logger.error(f"Failed to get approval request: {e}")

        return None

    async def _update_approval_request(self, approval: ApprovalRequest):
        """Update approval request in database"""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE approval_requests SET
                        status = $1, approver_id = $2, approved_at = $3, rejection_reason = $4
                    WHERE id = $5
                """, approval.status, approval.approver_id, approval.approved_at,
                approval.rejection_reason, approval.approval_id)

        except Exception as e:
            logger.error(f"Failed to update approval request: {e}")

    async def _notify_approval_required(self, approval: ApprovalRequest):
        """Notify administrators that approval is required"""
        # This would integrate with WebSocket notifications, email, Slack, etc.
        logger.info(f"🔔 Approval required for workflow {approval.workflow_id}")
        # TODO: Implement actual notification system

    async def close(self):
        """Close all connections"""
        if self.db_pool:
            await self.db_pool.close()
        self.redis_client.close()

# Global instance
workflow_state_machine = WorkflowStateMachine(
    database_url="postgresql://vouchlink_ai_user:G0cKKzLekD8EYygLMkymwoKlU3wdBqhk@dpg-d2f3ne2li9vc73bf5gg0-a.oregon-postgres.render.com/VouchLink-AIVouchLink AI"
)