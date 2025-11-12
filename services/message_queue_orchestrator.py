"""
Message Queue Orchestrator for Corporate Workflow
Coordinates message flow between services in the corporate warm-intro workflow
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from .redis_streams_queue import RedisStreamsQueue, QueueMessage, MessagePriority
from .audit_logging_service import audit_logger, AuditEventType, AuditSeverity
from .workflow_persistence_service import WorkflowPersistenceService, WorkflowStatus
from .resilience_patterns import ResilienceManager, BulkheadType
from .error_handling_framework import ErrorHandler, ErrorCategory, ErrorSeverity as ErrorSeverityLevel

# Import agent logger for real-time communication
try:
    from .agent_logger import agent_logger, AgentEventType
    agent_logging_available = True
except ImportError:
    logging.warning("Agent logger not available in message queue orchestrator")
    agent_logging_available = False

# Import Communication Hub integration
try:
    from .communication_client import CommunicationHubClient, MessageType, MessagePriority as CommPriority
    from .message_translator import MessageTranslator, BusinessContext
    from .metadata_enricher import MetadataEnricher
    communication_hub_available = True
except ImportError:
    logging.warning("Communication Hub not available in message queue orchestrator")
    communication_hub_available = False

logger = logging.getLogger(__name__)

@dataclass
class WorkflowStage:
    """Represents a stage in the corporate workflow"""
    name: str
    queue_name: str
    handler_service: str
    max_retries: int = 3
    timeout_seconds: int = 300
    dependencies: List[str] = None

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []

class MessageQueueOrchestrator:
    """Orchestrates the corporate workflow through message queues"""

    # Define the corporate workflow stages (aligned with CorporateWorkflowIntegration)
    WORKFLOW_STAGES = {
        'ingestion': WorkflowStage(
            name='ingestion',
            queue_name='ingestion',
            handler_service='ingestion_service',
            max_retries=2,
            timeout_seconds=180
        ),
        'executive_lookup': WorkflowStage(
            name='executive_lookup',
            queue_name='executive_lookup',
            handler_service='executive_lookup_service',
            dependencies=['ingestion'],
            max_retries=3,
            timeout_seconds=120
        ),
        'linkedin_url_lookup': WorkflowStage(
            name='linkedin_url_lookup',
            queue_name='linkedin_url_lookup',
            handler_service='linkedin_url_lookup_service',
            dependencies=['executive_lookup'],
            max_retries=2,
            timeout_seconds=300  # Allow time for LinkedIn searches
        ),
        'mutuals_orchestrator': WorkflowStage(
            name='mutuals_orchestrator',
            queue_name='mutuals_orchestrator',
            handler_service='mutuals_orchestrator_service',
            dependencies=['linkedin_url_lookup'],
            max_retries=2,
            timeout_seconds=600  # Longer timeout for LinkedIn scraping
        ),
        'scoring': WorkflowStage(
            name='scoring',
            queue_name='scoring',
            handler_service='scoring_service',
            dependencies=['mutuals_orchestrator'],
            max_retries=3,
            timeout_seconds=60
        ),
        'email_enrichment': WorkflowStage(
            name='email_enrichment',
            queue_name='email_enrichment',
            handler_service='email_enrichment_service',
            dependencies=['scoring'],
            max_retries=3,
            timeout_seconds=180
        ),
        'corporate_scheduler': WorkflowStage(
            name='corporate_scheduler',
            queue_name='corporate_scheduler',
            handler_service='corporate_scheduler_service',
            dependencies=['email_enrichment'],
            max_retries=2,
            timeout_seconds=30
        )
    }

    def __init__(self, redis_url: Optional[str] = None):
        self.queue = RedisStreamsQueue(redis_url=redis_url)

        # Maintain state of running workflows {workflow_id: {...}} so that we can resume or cancel them
        self.active_workflows: Dict[str, Dict[str, Any]] = {}

        # Enterprise persistence and resilience
        from .workflow_persistence_service import workflow_persistence_service
        self.persistence_service = workflow_persistence_service
        self.resilience_manager = ResilienceManager()
        self.error_handler = ErrorHandler()

        # Communication Hub integration
        if communication_hub_available:
            self.communication_hub = CommunicationHubClient()
            self.message_translator = MessageTranslator()
            self.metadata_enricher = MetadataEnricher()
        else:
            self.communication_hub = None
            self.message_translator = None
            self.metadata_enricher = None

        # Register bulkhead for message queue operations
        from .resilience_patterns import BulkheadConfig, BulkheadType
        self.resilience_manager.create_bulkhead(BulkheadConfig(
            name="message_queue_orchestrator",
            bulkhead_type=BulkheadType.THREAD_POOL,
            max_concurrent=15
        ))

    async def _ensure_queue_available(self) -> bool:
        """Attempt to ensure the Redis queue is ready."""
        try:
            if hasattr(self.queue, "ensure_initialized"):
                return await self.queue.ensure_initialized()
            if hasattr(self.queue, "initialize"):
                return await self.queue.initialize()
        except Exception as exc:
            logger.error("Queue readiness check failed: %s", exc)
        return False

    async def start_prospect_workflow(
        self,
        organization_id: int,
        prospect_data: Dict[str, Any],
        workflow_id: Optional[str] = None,
        priority: MessagePriority = MessagePriority.NORMAL
    ) -> str:
        """Start a new prospect processing workflow"""

        if not workflow_id:
            workflow_id = f"workflow_{organization_id}_{int(datetime.now().timestamp())}"

        correlation_id = f"corp_workflow_{workflow_id}"

        try:
            user_id_for_audit = prospect_data.get("user_id")

            # Log workflow start
            await audit_logger.log_event(
                tenant_id=str(organization_id),
                user_id=str(user_id_for_audit) if user_id_for_audit is not None else None,
                event_type=AuditEventType.AI_WORKFLOW_STARTED,
                action="workflow_started",
                resource_type="prospect_workflow",
                resource_id=workflow_id,
                details={
                    "correlation_id": correlation_id,
                    "prospect_count": len(prospect_data.get("prospects", [])),
                    "priority": priority.value,
                    "actor_type": "system",
                },
                severity=AuditSeverity.INFO,
            )

            # Log workflow start for real-time communication
            if agent_logging_available:
                user_id = prospect_data.get("user_id", 1)
                await agent_logger.log_event(
                    event_type=AgentEventType.WORKFLOW_START,
                    agent_id="message_queue_orchestrator",
                    message=f"Starting corporate workflow for {len(prospect_data.get('prospects', []))} prospects",
                    tenant_id=str(organization_id),
                    user_id=str(user_id),
                    workflow_id=workflow_id,
                    metadata={
                        "correlation_id": correlation_id,
                        "prospect_count": len(prospect_data.get("prospects", [])),
                        "priority": priority.value,
                        "stages_planned": list(self.WORKFLOW_STAGES.keys())
                    }
                )

            # Store workflow in enterprise persistence - Fix missing user_id parameter
            user_id = prospect_data.get("user_id", 1)  # Default to system user if not provided
            await self.persistence_service.create_workflow(
                organization_id=organization_id,
                user_id=user_id,
                workflow_type="message_queue_orchestrated",
                prospects=prospect_data.get("prospects", []),
                team_members=[]
            )

            queue_ready = await self._ensure_queue_available()
            if not queue_ready:
                warning_payload = {
                    "message": "Redis Streams queue unavailable; automation paused",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    await self.persistence_service.update_workflow_state(
                        workflow_id=workflow_id,
                        status=WorkflowStatus.PAUSED,
                        current_stage="queue_unavailable",
                        errors=[warning_payload],
                        is_paused=True,
                        pause_reason="redis_queue_unavailable"
                    )
                except Exception as exc:  # pragma: no cover - defensive guard
                    logger.error("Failed to persist queue-unavailable status for %s: %s", workflow_id, exc)

                warning_payload["actor_type"] = "system"
                await audit_logger.log_event(
                    tenant_id=str(organization_id),
                    user_id=str(user_id_for_audit) if user_id_for_audit is not None else None,
                    event_type=AuditEventType.ERROR_OCCURRED,
                    action="workflow_queue_unavailable",
                    resource_type="prospect_workflow",
                    resource_id=workflow_id,
                    details=warning_payload,
                    severity=AuditSeverity.WARNING,
                )
                logger.warning(
                    "Workflow %s for organization %s paused because Redis queue is unavailable.",
                    workflow_id,
                    organization_id,
                )
                return workflow_id
            # Update workflow status
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="running",
                current_stage="ingestion"
            )

            # Populate active_workflows dictionary for stage tracking
            # This fixes the issue where active_workflows was never populated,
            # causing workflow progression to fail after the first stage
            workflow_stages = list(self.WORKFLOW_STAGES.keys())
            self.active_workflows[workflow_id] = {
                "organization_id": organization_id,
                "user_id": user_id,
                "priority": priority,
                "current_stage_index": 0,  # Starting with ingestion (index 0)
                "total_stages": len(workflow_stages),
                "stages_completed": [],
                "stages_failed": [],
                "correlation_id": correlation_id,
                "created_at": datetime.now().isoformat(),
                "prospect_count": len(prospect_data.get("prospects", []))
            }

            # Start with ingestion stage
            await self._queue_stage_message(
                stage='ingestion',
                organization_id=organization_id,
                correlation_id=correlation_id,
                payload=prospect_data,
                priority=priority,
                workflow_id=workflow_id
            )

            # Notify user about workflow start via Communication Hub
            await self._notify_user(
                organization_id,
                user_id,
                "workflow_started",
                f"Started corporate workflow for {len(prospect_data.get('prospects', []))} prospects",
                {
                    "workflow_id": workflow_id,
                    "prospect_count": len(prospect_data.get('prospects', [])),
                    "total_stages": len(self.WORKFLOW_STAGES),
                    "stage_names": list(self.WORKFLOW_STAGES.keys())
                }
            )

            logger.info(f"Started prospect workflow {workflow_id} for organization {organization_id}")
            return workflow_id

        except Exception as e:
            logger.error(f"Failed to start prospect workflow: {e}")
            await audit_logger.log_event(
                tenant_id=str(organization_id),
                user_id=str(user_id_for_audit) if user_id_for_audit is not None else None,
                event_type=AuditEventType.ERROR_OCCURRED,
                action="workflow_failed",
                resource_type="prospect_workflow",
                resource_id=workflow_id,
                details={"error": str(e), "actor_type": "system"},
                severity=AuditSeverity.ERROR,
            )
            raise

    async def handle_stage_completion(
        self,
        stage_name: str,
        correlation_id: str,
        organization_id: int,
        result_data: Dict[str, Any],
        success: bool = True
    ):
        """Handle completion of a workflow stage"""

        workflow_id = self._extract_workflow_id(correlation_id)

        try:
            # Get workflow from enterprise persistence
            workflow_data = await self.persistence_service.get_workflow(workflow_id)
            if not workflow_data:
                logger.warning(f"Received completion for unknown workflow: {workflow_id}")
                return

            # Get workflow tracking data from active_workflows or create from persistence
            # This fixes the missing priority issue that caused workflow progression to fail
            if workflow_id in self.active_workflows:
                # Use active workflow tracking data which includes priority
                active_workflow = self.active_workflows[workflow_id]
                workflow = {
                    "stages_completed": active_workflow.get("stages_completed", []),
                    "stages_failed": active_workflow.get("stages_failed", []),
                    "priority": active_workflow.get("priority", MessagePriority.NORMAL),
                    "organization_id": active_workflow.get("organization_id", organization_id),
                    "user_id": active_workflow.get("user_id", 1),
                    "current_stage_index": active_workflow.get("current_stage_index", 0),
                    "total_stages": active_workflow.get("total_stages", len(self.WORKFLOW_STAGES))
                }
            else:
                # Fallback to persistence data if active_workflows is missing
                # (This shouldn't happen but provides safety)
                workflow = {
                    "stages_completed": workflow_data.get('metadata', {}).get('stages_completed', []),
                    "stages_failed": workflow_data.get('metadata', {}).get('stages_failed', []),
                    "priority": MessagePriority.NORMAL,  # Default priority as fallback
                    "organization_id": organization_id,
                    "user_id": workflow_data.get("user_id", 1),
                    "current_stage_index": 0,
                    "total_stages": len(self.WORKFLOW_STAGES)
                }
            if success:
                workflow["stages_completed"].append(stage_name)

                # Update active_workflows tracking if workflow exists
                if workflow_id in self.active_workflows:
                    self.active_workflows[workflow_id]["stages_completed"] = workflow["stages_completed"]
                    self.active_workflows[workflow_id]["current_stage_index"] += 1

                # Log successful stage completion
                await audit_logger.log_event(
                    tenant_id=str(organization_id),
                    user_id=str(workflow.get("user_id")) if workflow.get("user_id") is not None else None,
                    event_type=AuditEventType.AI_ANALYSIS_PERFORMED,
                    action="stage_completed",
                    resource_type="workflow_stage",
                    resource_id=stage_name,
                    details={
                        "workflow_id": workflow_id,
                        "correlation_id": correlation_id,
                        "result_summary": self._summarize_result(result_data),
                        "actor_type": "system",
                    },
                    severity=AuditSeverity.INFO,
                )

                # Log stage completion for real-time communication
                if agent_logging_available:
                    user_id = workflow_data.get("user_id", 1)
                    await agent_logger.log_task_complete(
                        agent_id="message_queue_orchestrator",
                        task_name=f"{stage_name}_stage",
                        result=self._summarize_result(result_data),
                        tenant_id=str(organization_id),
                        user_id=str(user_id),
                        workflow_id=workflow_id,
                        metadata={
                            "stage_name": stage_name,
                            "correlation_id": correlation_id,
                            "stages_completed": len(workflow["stages_completed"]),
                            "total_stages": len(self.WORKFLOW_STAGES)
                        }
                    )

                # Notify user about stage completion via Communication Hub
                user_id = workflow_data.get("user_id", 1)
                await self._notify_user_stage_complete(
                    organization_id,
                    user_id,
                    workflow_id,
                    stage_name,
                    f"Completed {stage_name.replace('_', ' ')} stage",
                    {
                        "result_summary": self._summarize_result(result_data),
                        "stages_completed": len(workflow["stages_completed"]),
                        "total_stages": len(self.WORKFLOW_STAGES)
                    }
                )

                # Determine next stage
                next_stage = self._get_next_stage(stage_name, workflow["stages_completed"])

                if next_stage:
                    # Queue next stage
                    await self._queue_stage_message(
                        stage=next_stage,
                        organization_id=organization_id,
                        correlation_id=correlation_id,
                        payload=result_data,
                        priority=workflow["priority"],
                        workflow_id=workflow_id
                    )

                    # Log stage progression for real-time communication
                    if agent_logging_available:
                        user_id = workflow_data.get("user_id", 1)
                        await agent_logger.log_stage_progress(
                            agent_id="message_queue_orchestrator",
                            stage_name=next_stage,
                            progress_percent=(len(workflow["stages_completed"]) / len(self.WORKFLOW_STAGES)) * 100,
                            current_action=f"Starting {next_stage} stage",
                            tenant_id=str(organization_id),
                            workflow_id=workflow_id,
                            metadata={
                                "previous_stage": stage_name,
                                "next_stage": next_stage,
                                "stages_remaining": len(self.WORKFLOW_STAGES) - len(workflow["stages_completed"])
                            }
                        )

                    # Notify user about next stage start via Communication Hub
                    user_id = workflow_data.get("user_id", 1)
                    await self._notify_user_stage_start(
                        organization_id,
                        user_id,
                        workflow_id,
                        next_stage,
                        f"Starting {next_stage.replace('_', ' ')} stage",
                        {
                            "previous_stage": stage_name,
                            "progress_percent": (len(workflow["stages_completed"]) / len(self.WORKFLOW_STAGES)) * 100,
                            "stages_remaining": len(self.WORKFLOW_STAGES) - len(workflow["stages_completed"])
                        }
                    )

                    logger.info(f"Queued next stage '{next_stage}' for workflow {workflow_id}")
                else:
                    # Workflow complete
                    user_id = workflow_data.get("user_id", 1)
                    await self._complete_workflow(workflow_id, organization_id, user_id, success=True)

            else:
                workflow["stages_failed"].append(stage_name)

                # Log stage failure
                await audit_logger.log_event(
                    tenant_id=str(organization_id),
                    user_id=str(workflow.get("user_id")) if workflow.get("user_id") is not None else None,
                    event_type=AuditEventType.ERROR_OCCURRED,
                    action="stage_failed",
                    resource_type="workflow_stage",
                    resource_id=stage_name,
                    details={
                        "workflow_id": workflow_id,
                        "correlation_id": correlation_id,
                        "error_details": result_data.get("error", "Unknown error"),
                        "actor_type": "system",
                    },
                    severity=AuditSeverity.WARNING,
                )

                # Determine if workflow should continue or fail
                if self._should_fail_workflow(stage_name, workflow):
                    user_id = workflow_data.get("user_id", 1)
                    await self._complete_workflow(workflow_id, organization_id, user_id, success=False)

        except Exception as e:
            logger.error(f"Error handling stage completion for {stage_name}: {e}")

    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a workflow"""
        try:
            # Get workflow from enterprise persistence
            workflow_data = await self.persistence_service.get_workflow(workflow_id)
            if not workflow_data:
                return None

            workflow = {
                'workflow_id': workflow_id,
                'status': workflow_data['status'],
                'current_stage': workflow_data.get('current_stage', 'unknown'),
                'organization_id': workflow_data['organization_id'],
                'user_id': workflow_data['user_id'],
                'created_at': workflow_data['created_at'],
                'updated_at': workflow_data['updated_at'],
                'error_message': workflow_data.get('error_message')
            }

            return workflow

        except Exception as e:
            logger.error(f"Failed to get workflow status for {workflow_id}: {e}")
            return None

    async def cancel_workflow(self, workflow_id: str, reason: str = "User cancelled"):
        """Cancel an active workflow"""
        try:
            # Get workflow from enterprise persistence
            workflow_data = await self.persistence_service.get_workflow(workflow_id)
            if not workflow_data:
                return False

            # Update workflow status to cancelled
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="cancelled",
                error_message=f"Cancelled: {reason}"
            )

            # Log cancellation
            await audit_logger.log_event(
                tenant_id=str(workflow_data["organization_id"]),
                user_id=str(workflow_data.get("user_id")) if workflow_data.get("user_id") is not None else None,
                event_type=AuditEventType.SYSTEM_MAINTENANCE,
                action="workflow_cancelled",
                resource_type="prospect_workflow",
                resource_id=workflow_id,
                details={"reason": reason, "actor_type": "system"},
                severity=AuditSeverity.INFO,
            )

            logger.info(f"Cancelled workflow {workflow_id}: {reason}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel workflow {workflow_id}: {e}")
            return False

    async def _queue_stage_message(
        self,
        stage: str,
        organization_id: int,
        correlation_id: str,
        payload: Dict[str, Any],
        priority: MessagePriority,
        workflow_id: Optional[str] = None
    ):
        """Queue a message for a specific workflow stage"""

        if not await self._ensure_queue_available():
            logger.warning(
                "Skipping queue stage '%s' for correlation %s because Redis queue is unavailable.",
                stage,
                correlation_id,
            )
            if workflow_id:
                warning_payload = {
                    "message": f"Stage {stage} skipped because Redis queue is unavailable",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "stage": stage,
                }
                try:
                    await self.persistence_service.update_workflow_state(
                        workflow_id=workflow_id,
                        status=WorkflowStatus.PAUSED,
                        current_stage="queue_unavailable",
                        errors=[warning_payload],
                        is_paused=True,
                        pause_reason="redis_queue_unavailable"
                    )
                except Exception as exc:  # pragma: no cover - defensive guard
                    logger.error("Failed to record queue-unavailable status for %s: %s", workflow_id, exc)
            return

        stage_config = self.WORKFLOW_STAGES[stage]

        # Queue the message using the enqueue_message method
        await self.queue.enqueue_message(
            queue_type=stage_config.queue_name,
            message_type=f"corporate_{stage}",
            payload=payload,
            organization_id=organization_id,
            priority=priority,
            correlation_id=correlation_id,
            max_retries=stage_config.max_retries,
        )

    def _get_next_stage(self, completed_stage: str, completed_stages: List[str]) -> Optional[str]:
        """Determine the next stage in the workflow"""

        # Define stage order (aligned with WORKFLOW_STAGES)
        stage_order = [
            'ingestion',
            'executive_lookup',
            'linkedin_url_lookup',
            'mutuals_orchestrator',
            'scoring',
            'email_enrichment',
            'corporate_scheduler'
        ]

        try:
            current_index = stage_order.index(completed_stage)
            if current_index + 1 < len(stage_order):
                next_stage = stage_order[current_index + 1]

                # Check if dependencies are met
                stage_config = self.WORKFLOW_STAGES[next_stage]
                for dependency in stage_config.dependencies:
                    if dependency not in completed_stages:
                        logger.warning(f"Dependency {dependency} not completed for stage {next_stage}")
                        return None

                return next_stage

        except ValueError:
            logger.error(f"Unknown stage: {completed_stage}")

        return None

    def _get_current_stage(self, workflow: Dict[str, Any]) -> Optional[str]:
        """Determine the current stage of a workflow"""
        completed = workflow["stages_completed"]
        failed = workflow["stages_failed"]

        if workflow["status"] == "completed":
            return None

        if workflow["status"] == "failed":
            return failed[-1] if failed else None

        # Find the next pending stage
        for stage_name in self.WORKFLOW_STAGES.keys():
            if stage_name not in completed and stage_name not in failed:
                return stage_name

        return None

    def _should_fail_workflow(self, failed_stage: str, workflow: Dict[str, Any]) -> bool:
        """Determine if a workflow should fail based on stage failure"""

        # Critical stages that should fail the entire workflow
        critical_stages = ['ingestion', 'executive_lookup']

        if failed_stage in critical_stages:
            return True

        # Check if too many stages have failed
        failed_count = len(workflow["stages_failed"])
        total_stages = len(self.WORKFLOW_STAGES)

        if failed_count >= total_stages * 0.5:  # More than 50% failed
            return True

        return False

    async def _complete_workflow(self, workflow_id: str, organization_id: int, user_id: int, success: bool):
        """Mark a workflow as completed"""

        if workflow_id not in self.active_workflows:
            return

        workflow = self.active_workflows[workflow_id]
        workflow["status"] = "completed" if success else "failed"
        workflow["completed_at"] = datetime.now()

        # Notify user about workflow completion via Communication Hub
        await self._notify_user(
            organization_id,
            user_id,
            "workflow_completed" if success else "workflow_failed",
            f"Corporate workflow {'completed successfully' if success else 'failed'}",
            {
                "workflow_id": workflow_id,
                "success": success,
                "stages_completed": len(workflow.get("stages_completed", [])),
                "stages_failed": len(workflow.get("stages_failed", [])),
                "total_stages": len(self.WORKFLOW_STAGES)
            }
        )

        # Log workflow completion
        await audit_logger.log_event(
            tenant_id=str(organization_id),
            user_id=str(user_id),
            event_type=AuditEventType.AI_ANALYSIS_PERFORMED if success else AuditEventType.ERROR_OCCURRED,
            action="workflow_completed" if success else "workflow_failed",
            resource_type="prospect_workflow",
            resource_id=workflow_id,
            details={
                "stages_completed": workflow.get("stages_completed", []),
                "stages_failed": workflow.get("stages_failed", []),
                "duration_seconds": (workflow["completed_at"] - workflow.get("started_at", datetime.now())).total_seconds(),
                "actor_type": "system",
            },
            severity=AuditSeverity.INFO if success else AuditSeverity.ERROR,
        )

        logger.info(f"Workflow {workflow_id} {'completed successfully' if success else 'failed'}")

        # Clean up active_workflows to prevent memory leaks
        # Remove completed workflow from tracking dictionary
        if workflow_id in self.active_workflows:
            del self.active_workflows[workflow_id]

    def _extract_workflow_id(self, correlation_id: str) -> str:
        """Extract workflow ID from correlation ID"""
        # Format: corp_workflow_{workflow_id}
        return correlation_id.replace("corp_workflow_", "")

    def _summarize_result(self, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a summary of stage results for logging"""
        summary = {}

        # Common result fields to include in summary
        summary_fields = [
            "prospects_processed", "connectors_found", "emails_enriched",
            "emails_scheduled", "success_count", "error_count"
        ]

        for field in summary_fields:
            if field in result_data:
                summary[field] = result_data[field]

        return summary

    async def _notify_user(self, organization_id: int, user_id: int, event_type: str, message: str, metadata: Dict[str, Any] = None):
        """Send notification to user via Communication Hub"""
        if not self.communication_hub or not self.message_translator:
            return

        try:
            # Translate to business-friendly language
            business_message = await self.message_translator.translate(
                message,
                BusinessContext.CORPORATE_WORKFLOW,
                include_technical_details=False
            )

            # Enrich with organizational context
            enriched_metadata = await self.metadata_enricher.enrich(
                metadata or {},
                organization_id=organization_id,
                user_id=user_id,
                service_name="message_queue_orchestrator"
            )

            # Send notification
            await self.communication_hub.send_message(
                message_type=MessageType.WORKFLOW_UPDATE,
                content=business_message,
                tenant_id=str(organization_id),
                user_id=str(user_id),
                metadata=enriched_metadata,
                priority=CommPriority.HIGH if event_type in ["workflow_started", "workflow_completed", "workflow_failed"] else CommPriority.MEDIUM
            )

        except Exception as e:
            logger.warning(f"Failed to send user notification: {e}")

    async def _notify_user_stage_start(self, organization_id: int, user_id: int, workflow_id: str, stage: str, message: str, metadata: Dict[str, Any] = None):
        """Send stage start notification to user"""
        stage_metadata = {
            "workflow_id": workflow_id,
            "stage": stage,
            "stage_status": "started",
            **(metadata or {})
        }
        await self._notify_user(organization_id, user_id, "stage_started", message, stage_metadata)

    async def _notify_user_stage_complete(self, organization_id: int, user_id: int, workflow_id: str, stage: str, message: str, metadata: Dict[str, Any] = None):
        """Send stage completion notification to user"""
        stage_metadata = {
            "workflow_id": workflow_id,
            "stage": stage,
            "stage_status": "completed",
            **(metadata or {})
        }
        await self._notify_user(organization_id, user_id, "stage_completed", message, stage_metadata)

# Global orchestrator instance
message_queue_orchestrator = MessageQueueOrchestrator()
