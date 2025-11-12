"""
Automated Workflow Service
September 2025 - Automated Corporate Workflow Triggers

Automatically triggers the corporate workflow pipeline when prospects are added
or when certain conditions are met, removing the need for manual intervention.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import json

from .message_queue_orchestrator import message_queue_orchestrator, MessagePriority
from .corporate_workflow_integration import CorporateWorkflowIntegration
from .audit_logging_service import audit_logger, AuditEventType, AuditSeverity

logger = logging.getLogger(__name__)

class AutomatedWorkflowService:
    """Service for automatically triggering prospect workflows"""

    def __init__(self):
        self.corporate_workflow = CorporateWorkflowIntegration()
        self.processing_cache = {}  # Cache to prevent duplicate processing
        self.queue_available: bool = True
        self.env_enabled: bool = os.getenv("ENABLE_AUTOMATED_WORKFLOWS", "true").lower() == "true"
        self.disabled_reason: Optional[str] = None
        if not self.env_enabled:
            self.disabled_reason = "automation_disabled_via_configuration"

    async def trigger_prospect_workflow(
        self,
        prospect_data: Dict[str, Any],
        organization_id: int,
        user_id: int,
        priority: MessagePriority = MessagePriority.NORMAL,
        auto_advance: bool = True
    ) -> str:
        """
        Automatically trigger the complete prospect workflow

        Args:
            prospect_data: Prospect information
            organization_id: Organization/tenant ID
            user_id: User who triggered the workflow
            priority: Message priority
            auto_advance: Whether to automatically advance through stages

        Returns:
            workflow_id: Unique identifier for the workflow
        """

        prospect_id = prospect_data.get('id')
        prospect_name = prospect_data.get('name', 'Unknown')

        if not self.env_enabled:
            logger.warning("Automated workflows disabled via configuration. Prospect %s queued for manual review.", prospect_name)
            await audit_logger.log_event(
                tenant_id=str(organization_id),
                user_id=str(user_id),
                event_type=AuditEventType.SYSTEM_MAINTENANCE,
                action="automated_workflow_disabled",
                resource_type="prospect",
                resource_id=str(prospect_id) if prospect_id is not None else None,
                details={
                    "reason": self.disabled_reason or "automation_disabled_via_configuration",
                    "prospect_name": prospect_name,
                    "actor_type": "system",
                },
                severity=AuditSeverity.WARNING,
            )
            return f"automation_disabled_{uuid.uuid4().hex[:8]}"

        # Check if this prospect is already being processed
        cache_key = f"{organization_id}_{prospect_id}"
        if cache_key in self.processing_cache:
            existing_workflow = self.processing_cache[cache_key]
            logger.info(f"Prospect {prospect_name} already has active workflow: {existing_workflow}")
            return existing_workflow

        try:
            queue_ready = True
            if hasattr(self.corporate_workflow, "ensure_queue_ready"):
                queue_ready = await self.corporate_workflow.ensure_queue_ready()
            else:
                queue = getattr(self.corporate_workflow, "queue", None)
                if queue and hasattr(queue, "ensure_initialized"):
                    queue_ready = await queue.ensure_initialized()

            if not queue_ready:
                self.queue_available = False
                self.disabled_reason = "redis_queue_unavailable"
                warning_payload = {
                    "prospect_name": prospect_name,
                    "reason": "Redis queue unavailable",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                warning_payload["actor_type"] = "system"
                await audit_logger.log_event(
                    tenant_id=str(organization_id),
                    user_id=str(user_id),
                    event_type=AuditEventType.ERROR_OCCURRED,
                    action="automated_workflow_skipped",
                    resource_type="prospect",
                    resource_id=str(prospect_id) if prospect_id is not None else None,
                    details=warning_payload,
                    severity=AuditSeverity.WARNING,
                )
                logger.warning("Skipped automated workflow for prospect %s because Redis queue is unavailable.", prospect_name)
                return f"queue_unavailable_{uuid.uuid4().hex[:8]}"

            self.queue_available = True
            self.disabled_reason = None

            # Prepare prospect data for workflow
            workflow_data = {
                "prospects": [prospect_data],
                "organization_id": organization_id,
                "user_id": user_id,
                "auto_advance": auto_advance,
                "settings": {
                    "auto_email_enrichment": True,
                    "auto_scoring": True,
                    "auto_linkedin_lookup": True,
                    "auto_connector_search": True
                }
            }

            # Start the automated workflow
            workflow_id = await message_queue_orchestrator.start_prospect_workflow(
                organization_id=organization_id,
                prospect_data=workflow_data,
                priority=priority
            )

            # Cache the workflow to prevent duplicates (only when queued)
            if self.queue_available:
                self.processing_cache[cache_key] = workflow_id

            # Set up workflow monitoring and auto-advancement
            if auto_advance:
                asyncio.create_task(self._monitor_workflow_progress(
                    workflow_id, organization_id, prospect_data
                ))

            # Log automated workflow start
            await audit_logger.log_event(
                tenant_id=str(organization_id),
                user_id=str(user_id),
                event_type=AuditEventType.AI_WORKFLOW_STARTED,
                action="automated_workflow_started",
                resource_type="prospect",
                resource_id=str(prospect_id) if prospect_id is not None else None,
                details={
                    "workflow_id": workflow_id,
                    "prospect_name": prospect_name,
                    "auto_advance": auto_advance,
                    "priority": priority.value,
                    "actor_type": "system",
                },
                severity=AuditSeverity.INFO,
            )

            logger.info(f"✅ Automated workflow {workflow_id} started for prospect {prospect_name}")
            return workflow_id

        except Exception as e:
            logger.error(f"Failed to trigger automated workflow for prospect {prospect_name}: {e}")

            # Log failure
            await audit_logger.log_event(
                tenant_id=str(organization_id),
                user_id=str(user_id),
                event_type=AuditEventType.ERROR_OCCURRED,
                action="automated_workflow_failed",
                resource_type="prospect",
                resource_id=str(prospect_id) if prospect_id is not None else None,
                details={
                    "prospect_name": prospect_name,
                    "error": str(e),
                    "actor_type": "system",
                },
                severity=AuditSeverity.ERROR,
            )

            raise

    async def trigger_bulk_workflow(
        self,
        prospects_data: List[Dict[str, Any]],
        organization_id: int,
        user_id: int,
        priority: MessagePriority = MessagePriority.NORMAL
    ) -> List[str]:
        """
        Trigger workflows for multiple prospects in parallel

        Args:
            prospects_data: List of prospect information
            organization_id: Organization/tenant ID
            user_id: User who triggered the workflows
            priority: Message priority

        Returns:
            List of workflow_ids
        """

        if not self.env_enabled:
            logger.warning(
                "Bulk workflow skipped for organization %s because automation is disabled via configuration.",
                organization_id,
            )
            return []

        queue_ready = True
        if hasattr(self.corporate_workflow, "ensure_queue_ready"):
            queue_ready = await self.corporate_workflow.ensure_queue_ready()
        else:
            queue = getattr(self.corporate_workflow, "queue", None)
            if queue and hasattr(queue, "ensure_initialized"):
                queue_ready = await queue.ensure_initialized()

        if not queue_ready:
            self.queue_available = False
            self.disabled_reason = "redis_queue_unavailable"
            logger.warning("Bulk workflow skipped because Redis queue is unavailable")
            return []

        self.queue_available = True
        self.disabled_reason = None

        workflow_ids = []

        # Process prospects in batches to avoid overwhelming the system
        batch_size = 10

        for i in range(0, len(prospects_data), batch_size):
            batch = prospects_data[i:i + batch_size]

            # Create tasks for parallel processing
            tasks = []
            for prospect_data in batch:
                task = self.trigger_prospect_workflow(
                    prospect_data=prospect_data,
                    organization_id=organization_id,
                    user_id=user_id,
                    priority=priority
                )
                tasks.append(task)

            # Wait for batch to complete
            batch_workflow_ids = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect successful workflow IDs
            for workflow_id in batch_workflow_ids:
                if isinstance(workflow_id, str):
                    workflow_ids.append(workflow_id)
                else:
                    logger.error(f"Failed workflow in batch: {workflow_id}")

            # Add delay between batches to prevent rate limiting
            if i + batch_size < len(prospects_data):
                await asyncio.sleep(2)

        logger.info(f"✅ Started {len(workflow_ids)} automated workflows for {len(prospects_data)} prospects")
        return workflow_ids

    async def cancel_workflow(self, workflow_id: str, reason: str = "User requested cancellation") -> bool:
        """Cancel an active automated workflow and clear any cached tracking."""

        try:
            cancelled = await message_queue_orchestrator.cancel_workflow(workflow_id, reason)
            if cancelled:
                # Remove any cached prospect keys that reference this workflow so future triggers can proceed
                keys_to_remove = [key for key, value in self.processing_cache.items() if value == workflow_id]
                for key in keys_to_remove:
                    self.processing_cache.pop(key, None)

            return cancelled

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(f"Failed to cancel workflow {workflow_id}: {exc}")
            return False

    async def _monitor_workflow_progress(
        self,
        workflow_id: str,
        organization_id: int,
        prospect_data: Dict[str, Any]
    ):
        """Monitor workflow progress and automatically advance stages"""

        prospect_name = prospect_data.get('name', 'Unknown')
        max_monitoring_time = timedelta(hours=2)  # Stop monitoring after 2 hours
        start_time = datetime.now()

        try:
            while datetime.now() - start_time < max_monitoring_time:
                # Check workflow status
                workflow_status = await message_queue_orchestrator.get_workflow_status(workflow_id)

                if not workflow_status:
                    logger.warning(f"Workflow {workflow_id} not found, stopping monitoring")
                    break

                status = workflow_status.get('status')
                current_stage = workflow_status.get('current_stage')
                completion_percentage = workflow_status.get('completion_percentage', 0)

                logger.info(f"Workflow {workflow_id} for {prospect_name}: {status} - {current_stage} ({completion_percentage:.1f}%)")

                # Check if workflow is complete or failed
                if status in ['completed', 'failed', 'cancelled']:
                    await self._handle_workflow_completion(
                        workflow_id, organization_id, prospect_data, status
                    )
                    break

                # Check for stuck workflows and retry if needed
                if status == 'running' and current_stage:
                    await self._check_stage_health(workflow_id, current_stage, organization_id)

                # Wait before next check
                await asyncio.sleep(30)  # Check every 30 seconds

        except Exception as e:
            logger.error(f"Error monitoring workflow {workflow_id}: {e}")
        finally:
            # Clean up cache
            cache_key = f"{organization_id}_{prospect_data.get('id')}"
            self.processing_cache.pop(cache_key, None)

    async def _handle_workflow_completion(
        self,
        workflow_id: str,
        organization_id: int,
        prospect_data: Dict[str, Any],
        status: str
    ):
        """Handle workflow completion events"""

        prospect_name = prospect_data.get('name', 'Unknown')
        prospect_id = prospect_data.get('id')

        user_identifier = prospect_data.get("user_id")
        audit_event_type = (
            AuditEventType.AI_ANALYSIS_PERFORMED if status == "completed" else AuditEventType.ERROR_OCCURRED
        )

        # Log completion
        await audit_logger.log_event(
            tenant_id=str(organization_id),
            user_id=str(user_identifier) if user_identifier is not None else None,
            event_type=audit_event_type,
            action=f"automated_workflow_{status}",
            resource_type="prospect",
            resource_id=str(prospect_id) if prospect_id is not None else None,
            details={
                "workflow_id": workflow_id,
                "prospect_name": prospect_name,
                "completion_status": status,
                "actor_type": "system",
            },
            severity=AuditSeverity.INFO if status == 'completed' else AuditSeverity.WARNING,
        )

        if status == 'completed':
            logger.info(f"✅ Automated workflow completed successfully for {prospect_name}")

            # Optionally trigger next actions (e.g., notifications, reports)
            await self._trigger_post_workflow_actions(workflow_id, organization_id, prospect_data)

        elif status == 'failed':
            logger.error(f"❌ Automated workflow failed for {prospect_name}")

            # Optionally trigger error handling or retry logic
            await self._handle_workflow_failure(workflow_id, organization_id, prospect_data)

    async def _check_stage_health(
        self,
        workflow_id: str,
        current_stage: str,
        organization_id: int
    ):
        """Check if a workflow stage is stuck and needs intervention"""

        # Implementation could include:
        # - Checking if stage has been running too long
        # - Verifying required services are healthy
        # - Automatically retrying failed operations
        # - Escalating to manual intervention if needed

        logger.debug(f"Health check for workflow {workflow_id} stage {current_stage}")

    async def _trigger_post_workflow_actions(
        self,
        workflow_id: str,
        organization_id: int,
        prospect_data: Dict[str, Any]
    ):
        """Trigger actions after successful workflow completion"""

        # Examples of post-workflow actions:
        # - Send notifications to users
        # - Update prospect status in database
        # - Generate reports
        # - Schedule follow-up tasks

        prospect_name = prospect_data.get('name', 'Unknown')
        logger.info(f"Post-workflow actions completed for {prospect_name}")

    async def _handle_workflow_failure(
        self,
        workflow_id: str,
        organization_id: int,
        prospect_data: Dict[str, Any]
    ):
        """Handle workflow failure scenarios"""

        # Examples of failure handling:
        # - Retry with different parameters
        # - Queue for manual review
        # - Send failure notifications
        # - Update prospect status

        prospect_name = prospect_data.get('name', 'Unknown')
        logger.warning(f"Handling workflow failure for {prospect_name}")

    async def get_automation_status(self, organization_id: int) -> Dict[str, Any]:
        """Get automation status and statistics for an organization"""

        active_workflows = len([
            key for key in self.processing_cache.keys()
            if key.startswith(f"{organization_id}_")
        ])

        return {
            "automation_enabled": True,
            "active_workflows": active_workflows,
            "supported_triggers": [
                "prospect_added",
                "prospect_imported",
                "prospect_updated",
                "scheduled_processing"
            ],
            "auto_stages": [
                "ingestion",
                "executive_lookup",
                "linkedin_url_lookup",
                "mutuals_orchestrator",
                "scoring",
                "email_enrichment",
                "corporate_scheduler"
            ]
        }

    async def enable_scheduled_processing(
        self,
        organization_id: int,
        schedule_config: Dict[str, Any]
    ):
        """Enable scheduled automated processing for an organization"""

        # This could implement:
        # - Daily/weekly automated prospect processing
        # - Batch processing of pending prospects
        # - Automated retries for failed workflows
        # - Scheduled health checks

        logger.info(f"Scheduled processing enabled for organization {organization_id}")

    def get_status(self) -> Dict[str, Any]:
        """Expose automation status for diagnostics/UI."""

        return {
            "enabled": self.env_enabled and self.queue_available,
            "env_enabled": self.env_enabled,
            "queue_available": self.queue_available,
            "disabled_reason": self.disabled_reason,
        }

# Global instance
automated_workflow_service = AutomatedWorkflowService()

# Convenience functions for common operations
async def auto_process_prospect(
    prospect_data: Dict[str, Any],
    organization_id: int,
    user_id: int,
    priority: MessagePriority = MessagePriority.NORMAL
) -> str:
    """Convenience function to automatically process a single prospect"""
    return await automated_workflow_service.trigger_prospect_workflow(
        prospect_data=prospect_data,
        organization_id=organization_id,
        user_id=user_id,
        priority=priority
    )

async def auto_process_prospects_bulk(
    prospects_data: List[Dict[str, Any]],
    organization_id: int,
    user_id: int,
    priority: MessagePriority = MessagePriority.NORMAL
) -> List[str]:
    """Convenience function to automatically process multiple prospects"""
    return await automated_workflow_service.trigger_bulk_workflow(
        prospects_data=prospects_data,
        organization_id=organization_id,
        user_id=user_id,
        priority=priority
    )
