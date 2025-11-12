"""
Progress Notifier Service for Real-Time Workflow Updates
Provides real-time progress notifications for long-running workflows via WebSocket.

Features:
- Real-time progress broadcasting to WebSocket clients
- Workflow step tracking with percentage completion
- Organization-scoped notifications for team collaboration
- Integration with existing orchestrators and agent workflows
- Structured progress events with metadata
"""

import logging
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)

class ProgressStatus(Enum):
    """Status states for workflow progress"""
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ProgressNotifier:
    """
    Service for sending real-time progress notifications via WebSocket
    Integrates with FastAPI WebSocket manager for live updates
    """

    def __init__(self):
        self.connection_manager = None
        self._initialize_services()
        logger.info("ProgressNotifier service initialized")

    def _initialize_services(self):
        """Initialize integration with WebSocket manager and logging"""
        try:
            # Integration with FastAPI WebSocket manager
            from .fastapi_websocket_manager import connection_manager
            self.connection_manager = connection_manager

            # Integration with agent logging
            from .agent_logger import agent_logger
            self.agent_logger = agent_logger

        except Exception as e:
            logger.warning(f"Could not initialize all services for ProgressNotifier: {e}")
            self.connection_manager = None
            self.agent_logger = None

    async def notify_workflow_started(
        self,
        user_id: int,
        organization_id: int,
        workflow_type: str,
        workflow_id: str,
        total_steps: int = None,
        metadata: Dict[str, Any] = None
    ) -> None:
        """
        Notify that a workflow has started

        Args:
            user_id: User who initiated the workflow
            organization_id: Organization/tenant ID
            workflow_type: Type of workflow (e.g., "prospect_discovery", "email_enrichment")
            workflow_id: Unique identifier for this workflow instance
            total_steps: Optional total number of steps in workflow
            metadata: Additional workflow metadata
        """
        try:
            progress_data = {
                "type": "workflow_progress",
                "status": ProgressStatus.STARTED.value,
                "workflow_type": workflow_type,
                "workflow_id": workflow_id,
                "progress_percentage": 0,
                "current_step": 0,
                "total_steps": total_steps,
                "message": f"Starting {workflow_type.replace('_', ' ').title()}...",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {}
            }

            # Send to specific user
            if self.connection_manager:
                await self.connection_manager.send_personal_message(user_id, progress_data)

            # Log the event
            if self.agent_logger:
                await self.agent_logger.log_event(
                    event_type="workflow_started",
                    user_id=user_id,
                    organization_id=organization_id,
                    metadata={
                        "workflow_type": workflow_type,
                        "workflow_id": workflow_id,
                        **progress_data
                    }
                )

            logger.info(f"Workflow started notification sent: {workflow_type} for user {user_id}")

        except Exception as e:
            logger.error(f"Failed to send workflow started notification: {e}")

    async def notify_progress_update(
        self,
        user_id: int,
        organization_id: int,
        workflow_type: str,
        workflow_id: str,
        current_step: int,
        total_steps: int,
        step_message: str,
        metadata: Dict[str, Any] = None
    ) -> None:
        """
        Send progress update during workflow execution

        Args:
            user_id: User receiving the update
            organization_id: Organization/tenant ID
            workflow_type: Type of workflow
            workflow_id: Workflow instance identifier
            current_step: Current step number (1-based)
            total_steps: Total number of steps
            step_message: Description of current step
            metadata: Additional step metadata
        """
        try:
            progress_percentage = int((current_step / total_steps) * 100) if total_steps > 0 else 0

            progress_data = {
                "type": "workflow_progress",
                "status": ProgressStatus.IN_PROGRESS.value,
                "workflow_type": workflow_type,
                "workflow_id": workflow_id,
                "progress_percentage": progress_percentage,
                "current_step": current_step,
                "total_steps": total_steps,
                "message": step_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {}
            }

            # Send to specific user
            if self.connection_manager:
                await self.connection_manager.send_personal_message(user_id, progress_data)

            # Optionally broadcast to organization for collaborative workflows
            if metadata and metadata.get("broadcast_to_org"):
                if self.connection_manager:
                    await self.connection_manager.send_organization_message(
                        organization_id, progress_data, exclude_user_id=user_id
                    )

            logger.debug(f"Progress update sent: {workflow_type} step {current_step}/{total_steps}")

        except Exception as e:
            logger.error(f"Failed to send progress update: {e}")

    async def notify_workflow_completed(
        self,
        user_id: int,
        organization_id: int,
        workflow_type: str,
        workflow_id: str,
        success_message: str,
        results: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None
    ) -> None:
        """
        Notify that a workflow has completed successfully

        Args:
            user_id: User receiving the notification
            organization_id: Organization/tenant ID
            workflow_type: Type of workflow
            workflow_id: Workflow instance identifier
            success_message: Success message to display
            results: Workflow results data
            metadata: Additional completion metadata
        """
        try:
            progress_data = {
                "type": "workflow_progress",
                "status": ProgressStatus.COMPLETED.value,
                "workflow_type": workflow_type,
                "workflow_id": workflow_id,
                "progress_percentage": 100,
                "current_step": "completed",
                "total_steps": "completed",
                "message": success_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "results": results or {},
                "metadata": metadata or {}
            }

            # Send to specific user
            if self.connection_manager:
                await self.connection_manager.send_personal_message(user_id, progress_data)

            # Log completion event
            if self.agent_logger:
                await self.agent_logger.log_event(
                    event_type="workflow_completed",
                    user_id=user_id,
                    organization_id=organization_id,
                    metadata={
                        "workflow_type": workflow_type,
                        "workflow_id": workflow_id,
                        "success": True,
                        **progress_data
                    }
                )

            logger.info(f"Workflow completed notification sent: {workflow_type} for user {user_id}")

        except Exception as e:
            logger.error(f"Failed to send workflow completion notification: {e}")

    async def notify_workflow_failed(
        self,
        user_id: int,
        organization_id: int,
        workflow_type: str,
        workflow_id: str,
        error_message: str,
        error_details: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None
    ) -> None:
        """
        Notify that a workflow has failed

        Args:
            user_id: User receiving the notification
            organization_id: Organization/tenant ID
            workflow_type: Type of workflow
            workflow_id: Workflow instance identifier
            error_message: Error message to display
            error_details: Detailed error information
            metadata: Additional failure metadata
        """
        try:
            progress_data = {
                "type": "workflow_progress",
                "status": ProgressStatus.FAILED.value,
                "workflow_type": workflow_type,
                "workflow_id": workflow_id,
                "progress_percentage": "failed",
                "current_step": "failed",
                "total_steps": "failed",
                "message": error_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error_details": error_details or {},
                "metadata": metadata or {}
            }

            # Send to specific user
            if self.connection_manager:
                await self.connection_manager.send_personal_message(user_id, progress_data)

            # Log failure event
            if self.agent_logger:
                await self.agent_logger.log_event(
                    event_type="workflow_failed",
                    user_id=user_id,
                    organization_id=organization_id,
                    metadata={
                        "workflow_type": workflow_type,
                        "workflow_id": workflow_id,
                        "success": False,
                        "error": error_message,
                        **progress_data
                    }
                )

            logger.error(f"Workflow failed notification sent: {workflow_type} for user {user_id}: {error_message}")

        except Exception as e:
            logger.error(f"Failed to send workflow failure notification: {e}")

    async def notify_custom_message(
        self,
        user_id: int,
        organization_id: int,
        message_type: str,
        message: str,
        metadata: Dict[str, Any] = None,
        broadcast_to_org: bool = False
    ) -> None:
        """
        Send a custom notification message

        Args:
            user_id: Target user ID
            organization_id: Organization/tenant ID
            message_type: Type of message (e.g., "info", "warning", "success")
            message: Message content
            metadata: Additional message metadata
            broadcast_to_org: Whether to broadcast to entire organization
        """
        try:
            notification_data = {
                "type": "custom_notification",
                "message_type": message_type,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {}
            }

            if broadcast_to_org:
                # Send to entire organization
                if self.connection_manager:
                    await self.connection_manager.send_organization_message(
                        organization_id, notification_data
                    )
            else:
                # Send to specific user
                if self.connection_manager:
                    await self.connection_manager.send_personal_message(user_id, notification_data)

            logger.info(f"Custom notification sent: {message_type} for user {user_id}")

        except Exception as e:
            logger.error(f"Failed to send custom notification: {e}")

# Global progress notifier instance
progress_notifier = ProgressNotifier()