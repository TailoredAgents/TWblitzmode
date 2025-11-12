"""
End-to-End Workflow Coordinator
Manages complete corporate introduction workflows with status tracking and API integration
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

from .corporate_workflow_integration import CorporateWorkflowIntegration, WorkflowContext
from .message_queue_orchestrator import MessageQueueOrchestrator
from .audit_logging_service import audit_logger, AuditEventType, AuditSeverity
from .redis_streams_queue import MessagePriority
from .workflow_persistence_service import WorkflowPersistenceService
from .resilience_patterns import ResilienceManager, BulkheadType
from .error_handling_framework import ErrorHandler, ErrorCategory, ErrorSeverity

try:  # pragma: no cover - optional during offline tests
    from monitoring.prometheus_metrics import metrics as prometheus_metrics
except Exception:  # pragma: no cover
    prometheus_metrics = None

logger = logging.getLogger(__name__)

class WorkflowStatus(Enum):
    """Workflow status enumeration"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class WorkflowSummary:
    """Summary of workflow execution"""
    workflow_id: str
    organization_id: str
    tenant_id: str
    user_id: int
    status: WorkflowStatus
    stage: str
    prospects_processed: int
    connectors_found: int
    emails_scheduled: int
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

class WorkflowCoordinator:
    """Coordinates complete end-to-end workflows with status tracking"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        # Initialize core components
        self.workflow_integration = CorporateWorkflowIntegration(redis_url)
        self.message_orchestrator = MessageQueueOrchestrator()

        # Maintain state of running workflows {workflow_id: {...}} so that we can resume or cancel them
        self.active_workflows: Dict[str, Dict[str, Any]] = {}

        # Enterprise persistence and resilience
        from .workflow_persistence_service import workflow_persistence_service
        self.persistence_service = workflow_persistence_service
        self.resilience_manager = ResilienceManager()
        self.error_handler = ErrorHandler()

        # Register bulkhead for workflow coordination
        from .resilience_patterns import BulkheadConfig, BulkheadType
        self.resilience_manager.create_bulkhead(BulkheadConfig(
            name="workflow_coordinator",
            bulkhead_type=BulkheadType.THREAD_POOL,
            max_concurrent=10
        ))

    async def start_corporate_workflow(
        self,
        organization_id: str,
        tenant_id: str,
        user_id: int,
        file_path: str,
        priority: MessagePriority = MessagePriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None
    ) -> WorkflowSummary:
        """Start a complete corporate introduction workflow"""

        # Generate workflow ID
        workflow_id = f"corp_{organization_id}_{int(datetime.now(timezone.utc).timestamp())}"

        try:
            if getattr(self.persistence_service, "db_pool", None) is None:
                await self.persistence_service.initialize()

            # Use bulkhead for workflow creation
            async with self.resilience_manager.get_bulkhead("workflow_coordinator"):
                # Create workflow summary
                workflow = WorkflowSummary(
                    workflow_id=workflow_id,
                    organization_id=organization_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    status=WorkflowStatus.PENDING,
                    stage="initialization",
                    prospects_processed=0,
                    connectors_found=0,
                    emails_scheduled=0,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    metadata=metadata.copy() if metadata else {}
                )
                workflow.metadata.setdefault('file_path', file_path)
                workflow.metadata.setdefault('priority', priority.value)

                # Store workflow in enterprise persistence
                await self.persistence_service.create_workflow(
                    organization_id=int(organization_id.split('-')[-1]) if '-' in organization_id else hash(organization_id) % 1000000,
                    user_id=user_id,
                    workflow_type="corporate_introduction",
                    prospects=[],  # Will be populated during workflow execution
                    team_members=[]  # Will be populated during workflow execution
                )

            # Log workflow initiation
            await audit_logger.log_event(
                event_type=AuditEventType.AI_WORKFLOW_STARTED,
                actor_type='user',
                actor_id=str(user_id),
                target_type='corporate_workflow',
                target_id=workflow_id,
                tenant_id=tenant_id,
                metadata={
                    'organization_id': organization_id,
                    'file_path': file_path,
                    'priority': priority.value
                }
            )

            # Start the workflow through the integration service
            integration_workflow_id = await self.workflow_integration.start_workflow(
                organization_id=organization_id,
                tenant_id=tenant_id,
                user_id=user_id,
                file_path=file_path
            )

            # Update workflow status
            workflow.status = WorkflowStatus.RUNNING
            workflow.stage = "ingestion"
            workflow.updated_at = datetime.now(timezone.utc)
            workflow.metadata['integration_workflow_id'] = integration_workflow_id
            self.active_workflows[workflow_id] = workflow

            if prometheus_metrics:
                prometheus_metrics.corporate_workflow_started(tenant_id)

            logger.info(f"Started corporate workflow {workflow_id} for organization {organization_id}")
            return workflow

        except Exception as e:
            # Handle workflow start failure with enterprise error handling
            error_context = {
                'workflow_id': workflow_id,
                'organization_id': organization_id,
                'tenant_id': tenant_id,
                'user_id': user_id,
                'file_path': file_path
            }

            handled_error = await self.error_handler.handle_error(
                error=e,
                operation="start_corporate_workflow",
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

            await audit_logger.log_event(
                event_type=AuditEventType.AI_WORKFLOW_FAILED,
                actor_type='system',
                actor_id='workflow_coordinator',
                target_type='corporate_workflow',
                target_id=workflow_id,
                tenant_id=tenant_id,
                metadata={'error': str(e), 'error_id': handled_error.error_id},
                severity=AuditSeverity.ERROR
            )

            logger.error(f"Failed to start workflow {workflow_id}: {e}")
            raise

    async def get_workflow_status(self, workflow_id: str) -> Optional[WorkflowSummary]:
        """Get current status of a workflow"""
        try:
            if getattr(self.persistence_service, "db_pool", None) is None:
                await self.persistence_service.initialize()

            # First try to get from enterprise persistence
            workflow_data = await self.persistence_service.get_workflow(workflow_id)

            if workflow_data:
                # Convert persistence data to WorkflowSummary
                workflow = WorkflowSummary(
                    workflow_id=workflow_data['workflow_id'],
                    organization_id=str(workflow_data['organization_id']),
                    tenant_id=workflow_data.get('tenant_id', 'default'),
                    user_id=workflow_data['user_id'],
                    status=WorkflowStatus(workflow_data['status']),
                    stage=workflow_data.get('current_stage', 'unknown'),
                    prospects_processed=len(workflow_data.get('prospects', [])),
                    connectors_found=workflow_data.get('metrics', {}).get('connectors_found', 0),
                    emails_scheduled=workflow_data.get('metrics', {}).get('emails_scheduled', 0),
                    created_at=datetime.fromisoformat(workflow_data['created_at'].replace('Z', '+00:00')),
                    updated_at=datetime.fromisoformat(workflow_data['updated_at'].replace('Z', '+00:00')),
                    completed_at=datetime.fromisoformat(workflow_data['completed_at'].replace('Z', '+00:00')) if workflow_data.get('completed_at') else None,
                    error_message=workflow_data.get('error_message'),
                    metadata=workflow_data.get('metadata', {})
                )

                self.active_workflows.setdefault(workflow.workflow_id, workflow)

                # Try to get updated status from message orchestrator
                try:
                    orchestrator_status = await self.message_orchestrator.get_workflow_status(
                        workflow.metadata.get('integration_workflow_id', workflow_id)
                    )

                    if orchestrator_status:
                        # Update workflow with latest status
                        workflow.stage = orchestrator_status.get('current_stage', workflow.stage)
                        workflow.updated_at = datetime.now(timezone.utc)

                        # Update completion status
                        if orchestrator_status.get('status') == 'completed':
                            workflow.status = WorkflowStatus.COMPLETED
                            workflow.completed_at = datetime.now(timezone.utc)
                            if workflow.workflow_id in self.active_workflows:
                                await self._finalize_workflow(
                                    workflow,
                                    WorkflowStatus.COMPLETED
                                )
                            return workflow
                        elif orchestrator_status.get('status') == 'failed':
                            workflow.status = WorkflowStatus.FAILED
                            workflow.error_message = "Workflow failed during execution"
                            if workflow.workflow_id in self.active_workflows:
                                await self._finalize_workflow(
                                    workflow,
                                    WorkflowStatus.FAILED,
                                    workflow.error_message
                                )
                            return workflow

                        # Update persistence with latest status
                        await self.persistence_service.update_workflow_status(
                            workflow_id=workflow_id,
                            status=workflow.status.value,
                            current_stage=workflow.stage,
                            error_message=workflow.error_message
                        )

                except Exception as e:
                    logger.warning(f"Could not get orchestrator status for {workflow_id}: {e}")

                return workflow

        except Exception as e:
            error_context = {'workflow_id': workflow_id}
            await self.error_handler.handle_error(
                error=e,
                operation="get_workflow_status",
                context=error_context,
                category=ErrorCategory.DATA_ACCESS_ERROR,
                severity=ErrorSeverity.MEDIUM
            )
            logger.warning(f"Could not get workflow status from persistence for {workflow_id}: {e}")

        return None

    async def list_workflows(
        self,
        organization_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        status: Optional[WorkflowStatus] = None,
        limit: int = 50
    ) -> List[WorkflowSummary]:
        """List workflows with optional filtering"""

        try:
            if getattr(self.persistence_service, "db_pool", None) is None:
                await self.persistence_service.initialize()

            # Get workflows from enterprise persistence
            org_id_int = None
            if organization_id:
                org_id_int = int(organization_id.split('-')[-1]) if '-' in organization_id else hash(organization_id) % 1000000

            workflows_data = await self.persistence_service.list_workflows(
                organization_id=org_id_int,
                status=status.value if status else None,
                limit=limit
            )

            # Convert to WorkflowSummary objects
            workflows = []
            for workflow_data in workflows_data:
                try:
                    workflow = WorkflowSummary(
                        workflow_id=workflow_data['workflow_id'],
                        organization_id=str(workflow_data['organization_id']),
                        tenant_id=workflow_data.get('tenant_id', 'default'),
                        user_id=workflow_data['user_id'],
                        status=WorkflowStatus(workflow_data['status']),
                        stage=workflow_data.get('current_stage', 'unknown'),
                        prospects_processed=len(workflow_data.get('prospects', [])),
                        connectors_found=workflow_data.get('metrics', {}).get('connectors_found', 0),
                        emails_scheduled=workflow_data.get('metrics', {}).get('emails_scheduled', 0),
                        created_at=datetime.fromisoformat(workflow_data['created_at'].replace('Z', '+00:00')),
                        updated_at=datetime.fromisoformat(workflow_data['updated_at'].replace('Z', '+00:00')),
                        completed_at=datetime.fromisoformat(workflow_data['completed_at'].replace('Z', '+00:00')) if workflow_data.get('completed_at') else None,
                        error_message=workflow_data.get('error_message'),
                        metadata=workflow_data.get('metadata', {})
                    )

                    # Apply additional filters
                    if tenant_id and workflow.tenant_id != tenant_id:
                        continue

                    workflows.append(workflow)

                except Exception as e:
                    logger.warning(f"Could not parse workflow data: {e}")
                    continue

            return workflows

        except Exception as e:
            error_context = {
                'organization_id': organization_id,
                'tenant_id': tenant_id,
                'status': status.value if status else None,
                'limit': limit
            }
            await self.error_handler.handle_error(
                error=e,
                operation="list_workflows",
                context=error_context,
                category=ErrorCategory.DATA_ACCESS_ERROR,
                severity=ErrorSeverity.MEDIUM
            )
            logger.error(f"Failed to list workflows: {e}")
            return []

    async def cancel_workflow(
        self,
        workflow_id: str,
        user_id: int,
        reason: str = "Cancelled by user"
    ) -> bool:
        """Cancel an active workflow"""

        if workflow_id not in self.active_workflows:
            return False

        workflow = self.active_workflows[workflow_id]

        try:
            # Cancel through message orchestrator if possible
            integration_workflow_id = workflow.metadata.get('integration_workflow_id')
            if integration_workflow_id:
                await self.message_orchestrator.cancel_workflow(integration_workflow_id, reason)

            # Log cancellation
            await audit_logger.log_event(
                event_type=AuditEventType.AI_WORKFLOW_CANCELLED,
                actor_type='user',
                actor_id=str(user_id),
                target_type='corporate_workflow',
                target_id=workflow_id,
                tenant_id=workflow.tenant_id,
                metadata={'reason': reason}
            )

            await self._finalize_workflow(workflow, WorkflowStatus.CANCELLED, reason)

            logger.info(f"Cancelled workflow {workflow_id}: {reason}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel workflow {workflow_id}: {e}")
            return False

    async def retry_failed_workflow(
        self,
        workflow_id: str,
        user_id: int
    ) -> Optional[WorkflowSummary]:
        """Retry a failed workflow from the last successful stage"""

        workflow = await self.get_workflow_status(workflow_id)
        if not workflow or workflow.status != WorkflowStatus.FAILED:
            return None

        try:
            # Create new workflow with same parameters
            new_workflow = await self.start_corporate_workflow(
                organization_id=workflow.organization_id,
                tenant_id=workflow.tenant_id,
                user_id=user_id,
                file_path=workflow.metadata.get('file_path', ''),
                priority=MessagePriority.NORMAL,
                metadata={
                    **workflow.metadata,
                    'retry_of': workflow_id,
                    'retry_attempt': workflow.metadata.get('retry_attempt', 0) + 1
                }
            )

            # Log retry
            await audit_logger.log_event(
                event_type=AuditEventType.AI_WORKFLOW_RETRIED,
                actor_type='user',
                actor_id=str(user_id),
                target_type='corporate_workflow',
                target_id=new_workflow.workflow_id,
                tenant_id=workflow.tenant_id,
                metadata={
                    'original_workflow_id': workflow_id,
                    'retry_attempt': new_workflow.metadata.get('retry_attempt', 1)
                }
            )

            return new_workflow

        except Exception as e:
            logger.error(f"Failed to retry workflow {workflow_id}: {e}")
            return None

    async def get_workflow_metrics(
        self,
        organization_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get workflow execution metrics"""

        try:
            # Get metrics from enterprise persistence service
            org_id_int = None
            if organization_id:
                org_id_int = int(organization_id.split('-')[-1]) if '-' in organization_id else hash(organization_id) % 1000000

            since_date = datetime.now(timezone.utc) - timedelta(days=days)

            # Get workflows from persistence
            all_workflows_data = await self.persistence_service.list_workflows(
                organization_id=org_id_int,
                limit=10000  # Get all workflows for metrics
            )

            # Filter by date and convert to WorkflowSummary
            filtered_workflows = []
            for workflow_data in all_workflows_data:
                try:
                    created_at = datetime.fromisoformat(workflow_data['created_at'].replace('Z', '+00:00'))
                    if created_at < since_date:
                        continue

                    workflow = WorkflowSummary(
                        workflow_id=workflow_data['workflow_id'],
                        organization_id=str(workflow_data['organization_id']),
                        tenant_id=workflow_data.get('tenant_id', 'default'),
                        user_id=workflow_data['user_id'],
                        status=WorkflowStatus(workflow_data['status']),
                        stage=workflow_data.get('current_stage', 'unknown'),
                        prospects_processed=len(workflow_data.get('prospects', [])),
                        connectors_found=workflow_data.get('metrics', {}).get('connectors_found', 0),
                        emails_scheduled=workflow_data.get('metrics', {}).get('emails_scheduled', 0),
                        created_at=created_at,
                        updated_at=datetime.fromisoformat(workflow_data['updated_at'].replace('Z', '+00:00')),
                        completed_at=datetime.fromisoformat(workflow_data['completed_at'].replace('Z', '+00:00')) if workflow_data.get('completed_at') else None,
                        error_message=workflow_data.get('error_message'),
                        metadata=workflow_data.get('metadata', {})
                    )

                    if tenant_id and workflow.tenant_id != tenant_id:
                        continue

                    filtered_workflows.append(workflow)

                except Exception as e:
                    logger.warning(f"Could not parse workflow data for metrics: {e}")
                    continue

            # Calculate metrics
            total_workflows = len(filtered_workflows)
            completed_workflows = len([w for w in filtered_workflows if w.status == WorkflowStatus.COMPLETED])
            failed_workflows = len([w for w in filtered_workflows if w.status == WorkflowStatus.FAILED])
            active_workflows = len([w for w in filtered_workflows if w.status == WorkflowStatus.RUNNING])

            total_prospects = sum(w.prospects_processed for w in filtered_workflows)
            total_connectors = sum(w.connectors_found for w in filtered_workflows)
            total_emails = sum(w.emails_scheduled for w in filtered_workflows)

            # Calculate completion rates
            completion_rate = (completed_workflows / total_workflows * 100) if total_workflows > 0 else 0
            failure_rate = (failed_workflows / total_workflows * 100) if total_workflows > 0 else 0

            return {
                'period_days': days,
                'total_workflows': total_workflows,
                'completed_workflows': completed_workflows,
                'failed_workflows': failed_workflows,
                'active_workflows': active_workflows,
                'completion_rate_percent': round(completion_rate, 2),
                'failure_rate_percent': round(failure_rate, 2),
                'total_prospects_processed': total_prospects,
                'total_connectors_found': total_connectors,
                'total_emails_scheduled': total_emails,
                'average_prospects_per_workflow': round(total_prospects / total_workflows, 2) if total_workflows > 0 else 0,
                'average_connectors_per_workflow': round(total_connectors / total_workflows, 2) if total_workflows > 0 else 0
            }

        except Exception as e:
            error_context = {
                'organization_id': organization_id,
                'tenant_id': tenant_id,
                'days': days
            }
            await self.error_handler.handle_error(
                error=e,
                operation="get_workflow_metrics",
                context=error_context,
                category=ErrorCategory.DATA_ACCESS_ERROR,
                severity=ErrorSeverity.MEDIUM
            )
            logger.error(f"Failed to get workflow metrics: {e}")
            return {
                'period_days': days,
                'total_workflows': 0,
                'completed_workflows': 0,
                'failed_workflows': 0,
                'active_workflows': 0,
                'completion_rate_percent': 0,
                'failure_rate_percent': 0,
                'total_prospects_processed': 0,
                'total_connectors_found': 0,
                'total_emails_scheduled': 0,
                'average_prospects_per_workflow': 0,
                'average_connectors_per_workflow': 0
            }

    async def _finalize_workflow(
        self,
        workflow: WorkflowSummary,
        status: WorkflowStatus,
        reason: Optional[str] = None,
        archive: bool = True
    ) -> None:
        """Finalize workflow bookkeeping and record metrics."""

        workflow.status = status
        if reason:
            workflow.error_message = reason
        workflow.completed_at = datetime.now(timezone.utc)
        workflow.updated_at = datetime.now(timezone.utc)

        tenant_id = workflow.tenant_id

        if prometheus_metrics:
            try:
                prometheus_metrics.corporate_workflow_finished(tenant_id, status.value)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug(f"Failed to publish workflow metrics for {workflow.workflow_id}: {exc}")

        self.active_workflows.pop(workflow.workflow_id, None)

        try:
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow.workflow_id,
                status=status.value,
                current_stage=workflow.stage,
                error_message=workflow.error_message
            )
        except Exception as exc:
            logger.warning(f"Could not update workflow status for {workflow.workflow_id}: {exc}")

        if archive:
            await self._archive_workflow(workflow.workflow_id)

    async def _archive_workflow(self, workflow_id: str) -> None:
        """Archive workflow in enterprise persistence"""
        try:
            # Update workflow status to archived in persistence
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="archived"
            )
            logger.info(f"Archived workflow {workflow_id} in enterprise persistence")
        except Exception as e:
            logger.warning(f"Could not archive workflow {workflow_id}: {e}")

    async def cleanup_completed_workflows(self, older_than_hours: int = 24) -> int:
        """Clean up completed workflows older than specified hours"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        archived_count = 0

        for workflow_id in list(self.active_workflows.keys()):
            workflow = self.active_workflows[workflow_id]

            if (workflow.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]
                and workflow.updated_at < cutoff_time):

                await self._archive_workflow(workflow_id)
                archived_count += 1

        logger.info(f"Archived {archived_count} completed workflows older than {older_than_hours} hours")
        return archived_count

# Global coordinator instance
workflow_coordinator = WorkflowCoordinator()

# Example usage and testing
async def main():
    """Example workflow coordination"""
    coordinator = WorkflowCoordinator()

    # Start a workflow
    workflow = await coordinator.start_corporate_workflow(
        organization_id="org-123",
        tenant_id="tenant-456",
        user_id=789,
        file_path="/path/to/prospects.csv",
        priority=MessagePriority.HIGH,
        metadata={"source": "api_upload"}
    )

    print(f"Started workflow: {workflow.workflow_id}")

    # Check status
    status = await coordinator.get_workflow_status(workflow.workflow_id)
    print(f"Workflow status: {status.status.value} - Stage: {status.stage}")

    # Get metrics
    metrics = await coordinator.get_workflow_metrics(organization_id="org-123")
    print(f"Metrics: {json.dumps(metrics, indent=2)}")

if __name__ == "__main__":
    asyncio.run(main())