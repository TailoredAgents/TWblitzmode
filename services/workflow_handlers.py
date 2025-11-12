"""
Workflow Handlers for Corporate Introduction Pipeline
Production-ready handlers for Redis message queue processing
"""
import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import json
import uuid
from functools import wraps

# Import our services
from .redis_streams_queue import QueueMessage, MessagePriority, redis_queue
from .email_enrichment_service import email_enrichment_service
from .executive_lookup_service import executive_lookup_service
from .mutuals_orchestrator_service import mutuals_orchestrator_service
from .cookie_vault_service import cookie_vault as cookie_vault_service
from .corporate_scheduler_service import corporate_scheduler_service
from .scoring_service import scoring_service
from .database_logging import scoped_query_context


def attach_db_context(stage: str):
    """Decorator that binds queue metadata to database logs during handler execution."""

    def decorator(func):
        @wraps(func)
        async def wrapper(self, message: QueueMessage, *args, **kwargs):
            with self._db_query_context(message, stage):
                return await func(self, message, *args, **kwargs)

        return wrapper

    return decorator

try:  # pragma: no cover - optional dependency path
    from .vouchlink_ai_organization_agent import VouchLinkAIOrganizationAgent  # type: ignore
except Exception:  # noqa: BLE001
    VouchLinkAIOrganizationAgent = None  # type: ignore

logger = logging.getLogger(__name__)

class WorkflowHandlers:
    """
    Enterprise workflow handlers for corporate introduction pipeline
    Each handler processes specific workflow types from Redis queue
    """

    def __init__(self):
        # Initialize once the queue system is ready
        self.queue = redis_queue

        # Initialize service instances
        self.email_service = email_enrichment_service
        self.executive_service = executive_lookup_service
        self.mutuals_service = mutuals_orchestrator_service
        self.vault_service = cookie_vault_service
        self.scheduler_service = corporate_scheduler_service
        self.scoring_service = scoring_service

        # Initialize organization agent if available
        if VouchLinkAIOrganizationAgent is not None:
            try:
                self.org_agent = VouchLinkAIOrganizationAgent()
            except Exception as e:  # pragma: no cover - defensive guard
                logger.warning(f"VouchLinkAIOrganizationAgent not available: {e}")
                self.org_agent = None
        else:
            self.org_agent = None

    def _db_query_context(self, message: QueueMessage, stage: str):
        """Return a scoped query context populated with queue metadata."""
        priority_value = None
        if getattr(message, "priority", None) is not None:
            priority_value = getattr(message.priority, "value", message.priority)

        metadata = {
            "queue_stream": getattr(message, "stream", "unknown"),
            "queue_message_id": getattr(message, "id", "unknown"),
            "queue_message_type": getattr(message, "message_type", "unknown"),
            "correlation_id": getattr(message, "correlation_id", None),
            "organization_id": getattr(message, "organization_id", None),
            "tenant_id": getattr(message, "tenant_id", None),
            "queue_priority": priority_value,
            "retry_count": getattr(message, "retry_count", 0),
        }

        label = f"{stage}:{metadata['queue_stream']}:{metadata['queue_message_type']}"
        return scoped_query_context(label=label, metadata=metadata)

    async def register_all_handlers(self):
        """Register all workflow handlers with the Redis Streams queue"""

        if not self.queue:
            logger.error("Redis queue not available - cannot register handlers")
            return

        # Register consumers for each queue type
        queue_handlers = {
            "ingestion": self.handle_ingestion_messages,
            "executive_lookup": self.handle_executive_lookup,
            "mutuals_discovery": self.handle_mutual_connections,
            "connector_scoring": self.handle_prospect_scoring,
            "email_enrichment": self.handle_email_enrichment,
            "email_scheduling": self.handle_workflow_scheduling,
            "email_sending": self.handle_email_sending,
            "analytics": self.handle_workflow_completion,
            "notifications": self.handle_notifications,
            "audit_events": self.handle_audit_events
        }

        for queue_type, handler in queue_handlers.items():
            await self.queue.register_consumer(
                queue_type=queue_type,
                consumer_name=f"worker_{queue_type}",
                handler=handler
            )
            logger.info(f"Registered consumer for {queue_type} queue")

    @attach_db_context("handler.ingestion")
    async def handle_ingestion_messages(self, message: QueueMessage) -> bool:
        """
        Process CSV file ingestion for corporate prospects
        Input: CSV file path, tenant configuration
        Output: Parsed prospect records, executive lookup tasks
        """
        try:
            payload = message.payload
            tenant_id = message.tenant_id
            csv_file_path = payload.get("csv_file_path")
            import_config = payload.get("import_config", {})

            logger.info(f"Processing CSV ingestion for tenant {tenant_id}: {csv_file_path}")

            # Import CSV using existing service
            import csv
            prospects = []

            with open(csv_file_path, 'r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file)
                for row_num, row in enumerate(reader, 1):
                    try:
                        # Map CSV columns to prospect fields
                        prospect_data = {
                            "company_name": row.get("Company", "").strip(),
                            "contact_name": row.get("Contact Name", "").strip(),
                            "contact_email": row.get("Email", "").strip(),
                            "contact_title": row.get("Title", "").strip(),
                            "linkedin_url": row.get("LinkedIn", "").strip(),
                            "company_domain": row.get("Domain", "").strip(),
                            "notes": row.get("Notes", "").strip(),
                            "source": f"CSV Import - {csv_file_path}",
                            "row_number": row_num
                        }

                        # Validate required fields
                        if not prospect_data["company_name"]:
                            logger.warning(f"Row {row_num}: Missing company name, skipping")
                            continue

                        prospects.append(prospect_data)

                    except Exception as e:
                        logger.error(f"Row {row_num}: Error processing - {e}")

            logger.info(f"Parsed {len(prospects)} prospects from CSV")

            # Create executive lookup tasks for each prospect
            for prospect in prospects:
                await self.queue.enqueue_message(
                    queue_type="executive_lookup",
                    message_type="prospect_lookup",
                    payload={
                        "prospect_data": prospect,
                        "original_import_id": message.id,
                        "lookup_config": import_config.get("executive_lookup", {})
                    },
                    organization_id=message.organization_id,
                    priority=MessagePriority.HIGH,
                    correlation_id=message.correlation_id,
                    tenant_id=getattr(message, "tenant_id", None),
                )

            # Store import summary in metadata
            import_summary = {
                "total_rows": len(prospects),
                "successful_imports": len(prospects),
                "import_timestamp": datetime.now(timezone.utc).isoformat(),
                "file_path": csv_file_path
            }

            # Trigger next workflow step
            await self._trigger_batch_processing(
                message.organization_id,
                message.id,
                import_summary,
                tenant_id=getattr(message, "tenant_id", None),
            )

            return True

        except Exception as e:
            logger.error(f"CSV ingestion failed for message {message.id}: {e}")
            return False

    @attach_db_context("handler.executive_lookup")
    async def handle_executive_lookup(self, message: QueueMessage) -> bool:
        """
        Execute executive lookup for prospect using LinkedIn/Apollo APIs
        Input: Prospect data, lookup configuration
        Output: Executive contacts, enriched prospect data
        """
        try:
            payload = message.payload
            prospect_data = payload["prospect_data"]
            lookup_config = payload.get("lookup_config", {})

            logger.info(f"Executive lookup for {prospect_data['company_name']}")

            # Use executive lookup service
            executives = await self.executive_service.find_executives(
                company_name=prospect_data["company_name"],
                company_domain=prospect_data.get("company_domain"),
                target_titles=lookup_config.get("target_titles", ["CEO", "CTO", "VP"]),
                max_results=lookup_config.get("max_executives", 5)
            )

            if executives:
                # Create mutual connections lookup for each executive
                for executive in executives:
                    mutual_message = await create_workflow_message(
                        tenant_id=message.tenant_id,
                        workflow_type="mutual_connections",
                        priority=MessagePriority.HIGH,
                        payload={
                            "prospect_data": prospect_data,
                            "executive_data": executive,
                            "original_import_id": payload.get("original_import_id")
                        }
                    )
                    await message_queue.enqueue(mutual_message)

            return True

        except Exception as e:
            logger.error(f"Executive lookup failed for message {message.id}: {e}")
            return False

    @attach_db_context("handler.mutual_connections")
    async def handle_mutual_connections(self, message: QueueMessage) -> bool:
        """
        Find mutual connections between executive and team members
        Input: Executive data, team member LinkedIn profiles
        Output: Mutual connection analysis, introduction paths
        """
        try:
            payload = message.payload
            executive_data = payload["executive_data"]
            prospect_data = payload["prospect_data"]

            logger.info(f"Finding mutual connections for {executive_data['name']} at {prospect_data['company_name']}")

            # Use mutuals orchestrator service
            mutual_analysis = await self.mutuals_service.find_mutual_connections(
                target_linkedin=executive_data.get("linkedin_url"),
                company_domain=prospect_data.get("company_domain")
            )

            if mutual_analysis.get("connections"):
                # Create prospect scoring task
                scoring_message = await create_workflow_message(
                    tenant_id=message.tenant_id,
                    workflow_type="prospect_scoring",
                    priority=MessagePriority.NORMAL,
                    payload={
                        "prospect_data": prospect_data,
                        "executive_data": executive_data,
                        "mutual_analysis": mutual_analysis,
                        "original_import_id": payload.get("original_import_id")
                    }
                )
                await message_queue.enqueue(scoring_message)

            return True

        except Exception as e:
            logger.error(f"Mutual connections lookup failed for message {message.id}: {e}")
            return False

    @attach_db_context("handler.prospect_scoring")
    async def handle_prospect_scoring(self, message: QueueMessage) -> bool:
        """
        Score prospect based on mutual connections and company data
        Input: Prospect data, mutual connections, executive info
        Output: Scored prospect, email enrichment tasks
        """
        try:
            payload = message.payload
            prospect_data = payload["prospect_data"]
            mutual_analysis = payload["mutual_analysis"]

            logger.info(f"Scoring prospect {prospect_data['company_name']}")

            # Calculate prospect score based on multiple factors
            score = 0
            scoring_factors = []

            # Mutual connections weight (40%)
            connection_count = len(mutual_analysis.get("connections", []))
            connection_score = min(40, connection_count * 8)  # Max 40 points
            score += connection_score
            scoring_factors.append(f"Mutual connections: {connection_count} ({connection_score} pts)")

            # Executive seniority weight (20%)
            executive_data = payload.get("executive_data", {})
            title = executive_data.get("title", "").lower()
            if any(senior_title in title for senior_title in ["ceo", "cto", "president", "founder"]):
                score += 20
                scoring_factors.append("Senior executive contact (20 pts)")
            elif any(mid_title in title for mid_title in ["vp", "director", "head"]):
                score += 15
                scoring_factors.append("Mid-level executive contact (15 pts)")

            # Company size/domain weight (20%)
            if prospect_data.get("company_domain"):
                score += 10
                scoring_factors.append("Company domain verified (10 pts)")

            # LinkedIn presence weight (10%)
            if executive_data.get("linkedin_url"):
                score += 10
                scoring_factors.append("LinkedIn profile available (10 pts)")

            # Response likelihood (10%)
            if connection_count >= 2:
                score += 10
                scoring_factors.append("Multiple mutual connections (10 pts)")

            # Create enrichment task if score meets threshold
            if score >= 30:  # Minimum viable prospect score
                enrichment_message = await create_workflow_message(
                    tenant_id=message.tenant_id,
                    workflow_type="email_enrichment",
                    priority=MessagePriority.HIGH if score >= 60 else MessagePriority.NORMAL,
                    payload={
                        "prospect_data": prospect_data,
                        "executive_data": executive_data,
                        "mutual_analysis": mutual_analysis,
                        "prospect_score": score,
                        "scoring_factors": scoring_factors,
                        "original_import_id": payload.get("original_import_id")
                    }
                )
                await message_queue.enqueue(enrichment_message)

            logger.info(f"Prospect scored {score}/100: {prospect_data['company_name']}")
            return True

        except Exception as e:
            logger.error(f"Prospect scoring failed for message {message.id}: {e}")
            return False

    @attach_db_context("handler.email_enrichment")
    async def handle_email_enrichment(self, message: QueueMessage) -> bool:
        """
        Enrich prospect email data and prepare for AI approval
        Input: Scored prospect data
        Output: AI approval request with enriched context
        """
        try:
            payload = message.payload
            prospect_data = payload["prospect_data"]
            executive_data = payload["executive_data"]

            logger.info(f"Email enrichment for {prospect_data['company_name']}")

            # Enrich email data using service
            enriched_data = await self.email_service.enrich_prospect_email(
                company_name=prospect_data["company_name"],
                executive_name=executive_data.get("name"),
                executive_email=executive_data.get("email"),
                company_domain=prospect_data.get("company_domain")
            )

            # Create AI approval request
            approval_message = await create_workflow_message(
                tenant_id=message.tenant_id,
                workflow_type="ai_approval_request",
                priority=MessagePriority.HIGH,  # Approvals are high priority
                payload={
                    "prospect_data": prospect_data,
                    "executive_data": executive_data,
                    "mutual_analysis": payload["mutual_analysis"],
                    "prospect_score": payload["prospect_score"],
                    "enriched_email_data": enriched_data,
                    "approval_type": "introduction_email",
                    "original_import_id": payload.get("original_import_id")
                }
            )
            await message_queue.enqueue(approval_message)

            return True

        except Exception as e:
            logger.error(f"Email enrichment failed for message {message.id}: {e}")
            return False

    @attach_db_context("handler.ai_approval")
    async def handle_ai_approval_request(self, message: QueueMessage) -> bool:
        """
        Submit workflow for human-in-the-loop AI approval
        Input: Complete prospect workflow data
        Output: Approval request in queue
        """
        try:
            payload = message.payload

            logger.info(f"Creating AI approval request for {payload['prospect_data']['company_name']}")

            # Use organization agent to request approval
            approval_result = await self.org_agent.request_approval(
                tenant_id=message.tenant_id,
                workflow_data=payload,
                approval_type=payload.get("approval_type", "introduction_email")
            )

            if approval_result.get("approved"):
                # Auto-approved, proceed to email generation
                email_message = await create_workflow_message(
                    tenant_id=message.tenant_id,
                    workflow_type="email_generation",
                    priority=MessagePriority.HIGH,
                    payload={**payload, "approval_id": approval_result["approval_id"]}
                )
                await message_queue.enqueue(email_message)

            # If not auto-approved, it will wait for human approval via WebSocket

            return True

        except Exception as e:
            logger.error(f"AI approval request failed for message {message.id}: {e}")
            return False

    @attach_db_context("handler.email_generation")
    async def handle_email_generation(self, message: QueueMessage) -> bool:
        """
        Generate personalized introduction email using GPT-4
        Input: Approved prospect data
        Output: Generated email content
        """
        try:
            payload = message.payload
            prospect_data = payload["prospect_data"]
            executive_data = payload["executive_data"]

            logger.info(f"Generating email for {prospect_data['company_name']}")

            # Use organization agent to generate email
            email_content = await self.org_agent.generate_introduction_email(
                tenant_id=message.tenant_id,
                prospect_data=prospect_data,
                executive_data=executive_data,
                mutual_analysis=payload["mutual_analysis"],
                enriched_data=payload.get("enriched_email_data", {})
            )

            # Schedule email sending
            sending_message = await create_workflow_message(
                tenant_id=message.tenant_id,
                workflow_type="email_sending",
                priority=MessagePriority.HIGH,
                payload={
                    **payload,
                    "email_content": email_content,
                    "scheduled_send_time": datetime.now(timezone.utc).isoformat()
                }
            )
            await message_queue.enqueue(sending_message)

            return True

        except Exception as e:
            logger.error(f"Email generation failed for message {message.id}: {e}")
            return False

    @attach_db_context("handler.email_sending")
    async def handle_email_sending(self, message: QueueMessage) -> bool:
        """
        Send introduction email via configured email service
        Input: Generated email content
        Output: Email delivery confirmation
        """
        try:
            payload = message.payload
            email_content = payload["email_content"]

            logger.info(f"Sending email for {payload['prospect_data']['company_name']}")

            # Use scheduler service to send email
            send_result = await self.scheduler_service.send_introduction_email(
                tenant_id=message.tenant_id,
                email_content=email_content,
                recipient_data=payload["executive_data"]
            )

            if send_result.get("success"):
                # Create completion message
                completion_message = await create_workflow_message(
                    tenant_id=message.tenant_id,
                    workflow_type="workflow_completion",
                    priority=MessagePriority.LOW,
                    payload={
                        **payload,
                        "email_send_result": send_result,
                        "workflow_completed_at": datetime.now(timezone.utc).isoformat()
                    }
                )
                await message_queue.enqueue(completion_message)

            return True

        except Exception as e:
            logger.error(f"Email sending failed for message {message.id}: {e}")
            return False

    @attach_db_context("handler.workflow_completion")
    async def handle_workflow_completion(self, message: QueueMessage) -> bool:
        """
        Complete workflow and update metrics
        Input: Complete workflow results
        Output: Updated analytics and cleanup
        """
        try:
            payload = message.payload

            logger.info(f"Completing workflow for {payload['prospect_data']['company_name']}")

            # Update organization metrics
            # This would typically update database with completion stats
            completion_data = {
                "tenant_id": message.tenant_id,
                "prospect_company": payload["prospect_data"]["company_name"],
                "workflow_duration": "calculated_duration",
                "success": True,
                "email_sent": payload.get("email_send_result", {}).get("success", False)
            }

            logger.info(f"Workflow completed successfully: {completion_data}")
            return True

        except Exception as e:
            logger.error(f"Workflow completion failed for message {message.id}: {e}")
            return False

    @attach_db_context("handler.batch_processing")
    async def handle_batch_processing(self, message: QueueMessage) -> bool:
        """Handle batch processing coordination"""
        try:
            payload = message.payload
            logger.info(f"Batch processing for import {payload.get('import_id')}")
            return True
        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            return False

    @attach_db_context("handler.error_recovery")
    async def handle_error_recovery(self, message: QueueMessage) -> bool:
        """Handle error recovery and retry logic"""
        try:
            payload = message.payload
            logger.info(f"Error recovery for workflow {payload.get('workflow_id')}")
            return True
        except Exception as e:
            logger.error(f"Error recovery failed: {e}")
            return False

    @attach_db_context("handler.tenant_onboarding")
    async def handle_tenant_onboarding(self, message: QueueMessage) -> bool:
        """Handle new tenant onboarding workflow"""
        try:
            payload = message.payload
            logger.info(f"Tenant onboarding for {payload.get('tenant_id')}")
            return True
        except Exception as e:
            logger.error(f"Tenant onboarding failed: {e}")
            return False

    @attach_db_context("handler.compliance_audit")
    async def handle_compliance_audit(self, message: QueueMessage) -> bool:
        """Handle compliance audit workflow"""
        try:
            payload = message.payload
            logger.info(f"Compliance audit for tenant {payload.get('tenant_id')}")
            return True
        except Exception as e:
            logger.error(f"Compliance audit failed: {e}")
            return False

    @attach_db_context("handler.notifications")
    async def handle_notifications(self, message: QueueMessage) -> bool:
        """Handle notification messages"""
        try:
            payload = message.payload
            notification_type = payload.get("notification_type", "info")

            logger.info(f"Processing notification: {notification_type}")

            # Implement notification logic here
            # Could send emails, push notifications, etc.

            return True
        except Exception as e:
            logger.error(f"Notification handling failed: {e}")
            return False

    @attach_db_context("handler.audit_events")
    async def handle_audit_events(self, message: QueueMessage) -> bool:
        """Handle audit event messages"""
        try:
            payload = message.payload
            event_type = payload.get("event_type", "unknown")

            logger.info(f"Processing audit event: {event_type}")

            # Store audit event in database
            # Implement audit logging here

            return True
        except Exception as e:
            logger.error(f"Audit event handling failed: {e}")
            return False

    async def _trigger_batch_processing(
        self,
        organization_id: int,
        import_id: str,
        summary: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ):
        """Trigger batch processing coordination"""
        await self.queue.enqueue_message(
            queue_type="analytics",
            message_type="batch_processing",
            payload={
                "import_id": import_id,
                "import_summary": summary,
                "batch_type": "csv_import"
            },
            organization_id=organization_id,
            priority=MessagePriority.LOW,
            tenant_id=tenant_id,
        )

# Global handlers instance
workflow_handlers = WorkflowHandlers()
