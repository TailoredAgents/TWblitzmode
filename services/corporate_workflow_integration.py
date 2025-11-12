"""
Corporate Workflow Integration Service
Connects all services through Redis message queue for the complete end-to-end workflow
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict, is_dataclass
from pathlib import Path

from .message_queue_orchestrator import MessageQueueOrchestrator
from .ingestion_service import ProspectIngestionService as IngestionService
from .executive_lookup_service import ExecutiveLookupService
from .linkedin_url_lookup_service import linkedin_url_lookup_service
from .mutuals_orchestrator_service import MutualsOrchestratorService
from .scoring_service import ScoringService
from .email_enrichment_service import EmailEnrichmentService
from .corporate_scheduler_service import CorporateSchedulerService
from .audit_logging_service import audit_logger, AuditEventType
from .redis_streams_queue import RedisStreamsQueue, QueueMessage, MessagePriority
from .openai_agents_2025_integration import openai_agents_integration, AgentRole
from .correlation_id_middleware import (
    workflow_tracer, create_child_span, trace_async_operation,
    add_tracing_to_message, extract_tracing_from_message
)

try:  # pragma: no cover - optional during certain test suites
    from monitoring.prometheus_metrics import metrics as prometheus_metrics
except Exception:  # pragma: no cover
    prometheus_metrics = None

logger = logging.getLogger(__name__)

@dataclass
class WorkflowContext:
    """Context passed through the workflow stages"""
    organization_id: str
    tenant_id: str
    user_id: int
    correlation_id: str
    workflow_id: str
    stage: str
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

class CorporateWorkflowIntegration:
    """Integrates all services for the corporate warm-intro workflow"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        # Initialize message queue orchestrator
        self.orchestrator = MessageQueueOrchestrator(redis_url)

        # Initialize all services
        self.ingestion = IngestionService()
        self.executive_lookup = ExecutiveLookupService()
        self.linkedin_url_lookup = linkedin_url_lookup_service
        self.mutuals_orchestrator = MutualsOrchestratorService()
        self.scoring = ScoringService()
        self.email_enrichment = EmailEnrichmentService()
        self.scheduler = CorporateSchedulerService()

        # Initialize Redis queue for direct messaging
        self.queue = RedisStreamsQueue()

        # Service registry for handler routing
        self.service_handlers = {
            'ingestion_service': self._handle_ingestion,
            'executive_lookup_service': self._handle_executive_lookup,
            'linkedin_url_lookup_service': self._handle_linkedin_url_lookup,
            'mutuals_orchestrator_service': self._handle_mutuals_search,
            'scoring_service': self._handle_scoring,
            'email_enrichment_service': self._handle_enrichment,
            'corporate_scheduler_service': self._handle_scheduling
        }

    async def ensure_queue_ready(self) -> bool:
        """Ensure the Redis queue is ready before attempting to enqueue messages."""
        try:
            if hasattr(self.queue, "ensure_initialized"):
                return await self.queue.ensure_initialized()
            if hasattr(self.queue, "initialize"):
                return await self.queue.initialize()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error("Failed to ensure Redis queue readiness: %s", exc)
            return False
        return True

    @trace_async_operation("start_corporate_workflow", "workflow_service")
    async def start_workflow(
        self,
        organization_id: str,
        tenant_id: str,
        user_id: int,
        file_path: str
    ) -> str:
        """Start a new corporate workflow from file upload"""

        # Generate workflow identifiers
        workflow_id = str(uuid.uuid4())
        correlation_id = f"workflow-{workflow_id}"

        # Create workflow context
        current_ts = datetime.now(timezone.utc)
        context = WorkflowContext(
            organization_id=organization_id,
            tenant_id=tenant_id,
            user_id=user_id,
            correlation_id=correlation_id,
            workflow_id=workflow_id,
            stage='ingestion',
            metadata={'file_path': file_path},
            created_at=current_ts,
            updated_at=current_ts
        )

        # Log workflow start
        await audit_logger.log_event(
            tenant_id=tenant_id,
            event_type=AuditEventType.AI_WORKFLOW_STARTED,
            action='workflow_started',
            resource_type='workflow',
            user_id=str(user_id),
            resource_id=workflow_id,
            details={
                'organization_id': organization_id,
                'user_id': user_id,
                'file_path': file_path
            },
            correlation_id=correlation_id
        )

        try:
            organization_id_int = int(str(organization_id))
        except (TypeError, ValueError):
            organization_id_int = None

        # Queue ingestion job with tracing
        payload = {
            'context': asdict(context),
            'file_path': file_path
        }

        # Add tracing information to message payload
        payload = add_tracing_to_message(payload)

        if self.queue.redis_client is None:
            await self.queue.initialize()

        target_org_id = organization_id_int or context.organization_id

        if hasattr(self.queue, 'send_message'):
            try:
                org_id_for_message = int(str(target_org_id))
            except (TypeError, ValueError):
                org_id_for_message = 0

            queue_message_fields = getattr(QueueMessage, "__annotations__", {})
            message_kwargs = {
                "id": str(uuid.uuid4()),
                "stream": self.queue.STREAM_NAMES.get("ingestion", "ingestion"),
                "message_type": "corporate_ingestion",
                "payload": payload,
                "organization_id": org_id_for_message,
                "correlation_id": correlation_id,
                "priority": MessagePriority.HIGH,
                "created_at": datetime.now(timezone.utc),
            }

            metadata: Dict[str, Any] = {}
            if "metadata" in queue_message_fields:
                metadata = message_kwargs.get("metadata") or {}

            if "tenant_id" in queue_message_fields:
                message_kwargs["tenant_id"] = context.tenant_id
            else:
                metadata = dict(metadata)
                metadata["tenant_id"] = context.tenant_id
                if metadata:
                    message_kwargs["metadata"] = metadata

            message = QueueMessage(**message_kwargs)
            message.queue = 'ingestion'

            await self.queue.send_message('ingestion', message)
        else:
            await self.queue.enqueue_message(
                queue_type='ingestion',
                message_type='corporate_ingestion',
                organization_id=target_org_id,
                payload=payload,
                priority=MessagePriority.HIGH,
                correlation_id=correlation_id,
                tenant_id=context.tenant_id,
            )

        logger.info(f"Started workflow {workflow_id} for organization {organization_id}")
        return workflow_id

    async def _handle_ingestion(self, message: QueueMessage) -> None:
        """Handle prospect ingestion stage"""
        stage_start = datetime.now(timezone.utc)
        tenant_id = message.payload.get('context', {}).get('tenant_id', 'unknown')

        # Extract tracing context from message
        extract_tracing_from_message(message.payload)

        # Create span for ingestion processing
        span = create_child_span("prospect_ingestion", "ingestion_service")

        context = WorkflowContext(**message.payload['context'])
        file_path = message.payload['file_path']

        workflow_tracer.add_span_tag(span, "workflow_id", context.workflow_id)
        workflow_tracer.add_span_tag(span, "organization_id", context.organization_id)
        workflow_tracer.add_span_tag(span, "file_path", file_path)

        try:
            try:
                organization_id_int = int(str(context.organization_id))
            except (TypeError, ValueError):
                organization_id_int = 0

            # Process file through ingestion service
            result = await self.ingestion.process_file(
                file_path=file_path,
                organization_id=organization_id_int,
                uploaded_by=context.user_id,
                tags=context.metadata.get('tags') if isinstance(context.metadata.get('tags'), list) else []
            )

            # Use AI agents to analyze prospects for optimal engagement strategy
            ai_decisions = await openai_agents_integration.analyze_prospects(
                prospects_data=[asdict(p) for p in result.prospects],
                workflow_id=context.workflow_id,
                organization_id=context.organization_id,
                tenant_id=context.tenant_id
            )

            # Filter prospects based on AI recommendations
            approved_prospects = []
            for i, prospect in enumerate(result.prospects):
                if i < len(ai_decisions):
                    decision = ai_decisions[i]
                    if not decision.requires_approval and decision.confidence_score > 0.6:
                        approved_prospects.append(prospect)
                        logger.info(f"AI approved prospect {prospect.id} with confidence {decision.confidence_score}")
                    else:
                        logger.info(f"AI flagged prospect {prospect.id} for human review")
                else:
                    approved_prospects.append(prospect)  # Fallback to include all if AI analysis fails

            # Queue executive lookup for AI-approved prospects
            for prospect in approved_prospects:
                context.stage = 'executive_lookup'
                context.metadata['prospect_id'] = prospect.id
                # Store human-readable details for downstream enrichment/scheduling
                context.metadata['prospect_name'] = prospect.full_name
                context.metadata['prospect_company'] = prospect.company
                context.metadata['prospect_role'] = getattr(prospect, "role", "executive")

                await self.queue.enqueue_message(
                    queue_type='executive_lookup',
                    message_type='corporate_executive_lookup',
                    organization_id=organization_id_int or context.organization_id,
                    payload={
                        'context': asdict(context),
                        'prospect': asdict(prospect)
                    },
                    priority=MessagePriority.MEDIUM,
                    correlation_id=context.correlation_id,
                    tenant_id=context.tenant_id,
                )

            try:
                path_obj = Path(file_path)
                if path_obj.exists() and path_obj.is_file():
                    path_obj.unlink()
            except Exception as cleanup_error:
                logger.debug(f"Could not remove temporary ingestion file %s: %s", file_path, cleanup_error)

            # Complete span with success metrics
            workflow_tracer.add_span_tag(span, "prospects_processed", len(approved_prospects))
            workflow_tracer.add_span_tag(span, "total_prospects", len(result.prospects))
            workflow_tracer.finish_span(span, status="completed")

            self._record_stage_metrics(tenant_id, "ingestion", stage_start, status="success")

        except Exception as e:
            # Complete span with error
            workflow_tracer.add_span_tag(span, "error", True)
            workflow_tracer.finish_span(span, status="failed", error=e)
            logger.error(f"Ingestion failed for workflow {context.workflow_id}: {e}")
            self._record_stage_metrics(tenant_id, "ingestion", stage_start, status="error", reason=str(e))
            raise

    async def _handle_executive_lookup(self, message: QueueMessage) -> None:
        """Handle executive lookup stage"""
        context = WorkflowContext(**message.payload['context'])
        prospect = message.payload['prospect']
        stage_start = datetime.now(timezone.utc)
        tenant_id = context.tenant_id

        try:
            # Lookup executive LinkedIn profile
            result = await self.executive_lookup.lookup_executive(
                company=prospect['company'],
                executive_name=prospect['full_name'],
                organization_id=context.organization_id
            )

            if result.linkedin_url:
                # Queue mutuals search
                context.stage = 'mutuals_search'
                context.metadata['linkedin_url'] = result.linkedin_url

                await self.queue.enqueue_message(
                    queue_type='mutuals_discovery',
                    message_type='corporate_mutuals_search',
                    organization_id=context.organization_id,
                    payload={
                        'context': asdict(context),
                        'prospect_id': prospect['id'],
                        'linkedin_url': result.linkedin_url
                    },
                    priority=MessagePriority.MEDIUM,
                    correlation_id=context.correlation_id,
                    tenant_id=context.tenant_id,
                )

            self._record_stage_metrics(tenant_id, "executive_lookup", stage_start, status="success")
        except Exception as e:
            logger.error(f"Executive lookup failed for prospect {prospect['id']}: {e}")
            self._record_stage_metrics(tenant_id, "executive_lookup", stage_start, status="error", reason=str(e))
            raise

    async def _handle_linkedin_url_lookup(self, message: QueueMessage) -> None:
        """Handle LinkedIn URL lookup stage for prospects missing URLs"""
        context = WorkflowContext(**message.payload['context'])
        prospect = message.payload['prospect']
        stage_start = datetime.now(timezone.utc)
        tenant_id = context.tenant_id

        try:
            # Check if prospect already has LinkedIn URL
            if prospect.get('linkedin_url'):
                logger.info(f"Prospect {prospect['id']} already has LinkedIn URL, skipping lookup")

                # Proceed directly to next stage
                context.stage = 'mutuals_search'
                context.metadata['linkedin_url'] = prospect['linkedin_url']

                await self.queue.enqueue_message(
                    queue_type='mutuals_discovery',
                    message_type='corporate_mutuals_search',
                    organization_id=context.organization_id,
                    payload={
                        'context': asdict(context),
                        'prospect_id': prospect['id'],
                        'linkedin_url': prospect['linkedin_url']
                    },
                    priority=MessagePriority.MEDIUM,
                    correlation_id=context.correlation_id,
                    tenant_id=context.tenant_id,
                )
                self._record_stage_metrics(tenant_id, "linkedin_url_lookup", stage_start, status="success")
                return

            # Perform LinkedIn URL lookup
            lookup_result = await self.linkedin_url_lookup.lookup_linkedin_url(
                prospect_id=prospect['id'],
                full_name=prospect['full_name'],
                company_name=prospect['company'],
                title=prospect.get('role'),
                location=prospect.get('location'),
                tenant_id=int(context.tenant_id),
                user_id=context.user_id
            )

            if lookup_result.status.value == "found" and lookup_result.linkedin_url:
                # Success - proceed to mutuals search
                context.stage = 'mutuals_search'
                context.metadata['linkedin_url'] = lookup_result.linkedin_url
                context.metadata['linkedin_url_confidence'] = lookup_result.confidence_score

                await self.queue.enqueue_message(
                    queue_type='mutuals_discovery',
                    message_type='corporate_mutuals_search',
                    organization_id=context.organization_id,
                    payload={
                        'context': asdict(context),
                        'prospect_id': prospect['id'],
                        'linkedin_url': lookup_result.linkedin_url
                    },
                    priority=MessagePriority.MEDIUM,
                    correlation_id=context.correlation_id,
                    tenant_id=context.tenant_id,
                )

                logger.info(f"✅ Found LinkedIn URL for prospect {prospect['id']}: {lookup_result.linkedin_url}")

                self._record_stage_metrics(tenant_id, "linkedin_url_lookup", stage_start, status="success")

            else:
                # No LinkedIn URL found - mark prospect as failed
                logger.warning(f"❌ No LinkedIn URL found for prospect {prospect['id']}: {lookup_result.error_message}")

                # Update prospect status to indicate LinkedIn URL lookup failed
                context.stage = 'linkedin_url_failed'
                context.metadata['lookup_failure_reason'] = lookup_result.error_message or "LinkedIn profile not found"

                # Could implement alternative handling here:
                # 1. Queue for manual review
                # 2. Skip to email enrichment without LinkedIn data
                # 3. Mark as completed with partial data
                # For now, we'll mark as failed and stop the workflow for this prospect
                self._record_stage_metrics(
                    tenant_id,
                    "linkedin_url_lookup",
                    stage_start,
                    status="error",
                    reason=lookup_result.error_message or "linkedin_not_found"
                )

        except Exception as e:
            logger.error(f"LinkedIn URL lookup failed for prospect {prospect['id']}: {e}")
            self._record_stage_metrics(tenant_id, "linkedin_url_lookup", stage_start, status="error", reason=str(e))
            raise

    async def _handle_mutuals_search(self, message: QueueMessage) -> None:
        """Handle mutual connections search"""
        context = WorkflowContext(**message.payload['context'])
        prospect_id = message.payload['prospect_id']
        linkedin_url = message.payload['linkedin_url']
        stage_start = datetime.now(timezone.utc)
        tenant_id = context.tenant_id

        try:
            # Search for mutual connections
            result = await self.mutuals_orchestrator.find_mutuals(
                prospect_id=prospect_id,
                linkedin_url=linkedin_url,
                organization_id=context.organization_id,
                tenant_id=context.tenant_id
            )

            if result.connectors:
                # Use AI to evaluate connection quality and recommend best introduction strategy
                normalized_connectors: List[Dict[str, Any]] = []
                for connector in result.connectors:
                    if is_dataclass(connector):
                        connector_dict = asdict(connector)
                        connector_metadata = getattr(connector, "metadata", {}) or {}
                    elif isinstance(connector, dict):
                        connector_dict = dict(connector)
                        connector_metadata = connector_dict.get("metadata", {}) or {}
                    else:
                        connector_dict = dict(connector)  # type: ignore[arg-type]
                        connector_metadata = connector_dict.get("metadata", {}) or {}

                    try:
                        ai_decision = await openai_agents_integration.evaluate_connections(
                            connector_data=connector_dict,
                            target_data={"id": prospect_id, "linkedin_url": linkedin_url},
                            workflow_id=context.workflow_id,
                            organization_id=context.organization_id,
                            tenant_id=context.tenant_id
                        )

                        # Store AI evaluation in connector metadata
                        connector_metadata.update({
                            "ai_evaluation": {
                                "confidence": ai_decision.confidence_score,
                                "recommendation": ai_decision.recommended_action,
                                "reasoning": ai_decision.reasoning,
                                "requires_approval": ai_decision.requires_approval
                            }
                        })

                        connector_label = connector_dict.get("id") or connector_dict.get("connector_id") or connector_dict.get("full_name") or connector_dict.get("linkedin_url") or "unknown"
                        logger.info(f"AI evaluated connector {connector_label} with confidence {ai_decision.confidence_score}")

                    except Exception as e:
                        connector_label = connector_dict.get("id") or connector_dict.get("connector_id") or connector_dict.get("full_name") or connector_dict.get("linkedin_url") or "unknown"
                        logger.warning(f"AI evaluation failed for connector {connector_label}: {e}")
                        # Continue without AI evaluation
                    connector_dict["metadata"] = connector_metadata
                    normalized_connectors.append(connector_dict)
                # Queue scoring
                context.stage = 'scoring'
                context.metadata['connector_count'] = len(normalized_connectors)

                queue_kwargs = {
                    'queue_type': 'connector_scoring',
                    'message_type': 'corporate_connector_scoring',
                    'organization_id': context.organization_id,
                    'payload': {
                        'context': asdict(context),
                        'prospect_id': prospect_id,
                        'connectors': normalized_connectors
                    },
                    'priority': MessagePriority.LOW,
                    'correlation_id': context.correlation_id,
                    'tenant_id': context.tenant_id,
                }

                if hasattr(self.queue, "send_message"):
                    await self.queue.send_message(**queue_kwargs)
                else:
                    await self.queue.enqueue_message(**queue_kwargs)

            self._record_stage_metrics(tenant_id, "mutuals_search", stage_start, status="success")
        except Exception as e:
            logger.error(f"Mutuals search failed for prospect {prospect_id}: {e}")
            self._record_stage_metrics(tenant_id, "mutuals_search", stage_start, status="error", reason=str(e))
            raise

    async def _handle_scoring(self, message: QueueMessage) -> None:
        """Handle connector scoring and ranking"""
        context = WorkflowContext(**message.payload['context'])
        prospect_id = message.payload['prospect_id']
        connectors = message.payload['connectors']
        stage_start = datetime.now(timezone.utc)
        tenant_id = context.tenant_id

        try:
            # Score and rank connectors
            result = await self.scoring.score_connectors(
                prospect_id=prospect_id,
                connectors=connectors,
                organization_id=context.organization_id
            )

            # Queue enrichment for top 5
            context.stage = 'email_enrichment'
            context.metadata['top_connectors'] = len(result.top_connectors)

            for connector in result.top_connectors[:5]:
                await self.queue.enqueue_message(
                    queue_type='email_enrichment',
                    message_type='corporate_email_enrichment',
                    organization_id=context.organization_id,
                    payload={
                        'context': asdict(context),
                        'connector': connector
                    },
                    priority=MessagePriority.LOW,
                    correlation_id=context.correlation_id,
                    tenant_id=context.tenant_id,
                )

            self._record_stage_metrics(tenant_id, "scoring", stage_start, status="success")
        except Exception as e:
            logger.error(f"Scoring failed for prospect {prospect_id}: {e}")
            self._record_stage_metrics(tenant_id, "scoring", stage_start, status="error", reason=str(e))
            raise

    async def _handle_enrichment(self, message: QueueMessage) -> None:
        """Handle email enrichment"""
        context = WorkflowContext(**message.payload['context'])
        connector = message.payload['connector']
        stage_start = datetime.now(timezone.utc)
        tenant_id = context.tenant_id

        try:
            # Enrich connector with email
            result = await self.email_enrichment.enrich_connector(
                connector=connector,
                organization_id=context.organization_id
            )

            if result.email:
                # Use AI to compose personalized introduction email
                try:
                    email_context = {
                        "recipient_name": connector.get("name"),
                        "recipient_company": connector.get("company"),
                        "recipient_id": connector.get("id"),
                        "connector_name": connector.get("name"),
                        "target_name": context.metadata.get("prospect_name"),
                        "requester_name": context.metadata.get("requester_name"),
                        "business_context": context.metadata.get("business_context", "Professional introduction"),
                        "value_proposition": "Valuable business connection opportunity",
                        "email_address": result.email
                    }

                    ai_email_decision = await openai_agents_integration.compose_introduction_email(
                        email_context=email_context,
                        workflow_id=context.workflow_id,
                        organization_id=context.organization_id,
                        tenant_id=context.tenant_id
                    )

                    # Store AI-composed email in result metadata
                    result.metadata = result.metadata or {}
                    result.metadata.update({
                        "ai_composed_email": {
                            "subject": ai_email_decision.metadata.get("email_subject"),
                            "body": ai_email_decision.metadata.get("email_body"),
                            "confidence": ai_email_decision.confidence_score,
                            "requires_approval": ai_email_decision.requires_approval,
                            "reasoning": ai_email_decision.reasoning
                        }
                    })

                    logger.info(f"AI composed email for connector {connector['id']} with confidence {ai_email_decision.confidence_score}")

                except Exception as e:
                    logger.warning(f"AI email composition failed for connector {connector['id']}: {e}")
                    # Continue with standard email enrichment
                # Queue for scheduling
                context.stage = 'scheduling'
                context.metadata['has_email'] = True

                await self.queue.enqueue_message(
                    queue_type='email_scheduling',
                    message_type='corporate_email_scheduling',
                    organization_id=context.organization_id,
                    payload={
                        'context': asdict(context),
                        'connector': asdict(result)
                    },
                    priority=MessagePriority.LOW,
                    correlation_id=context.correlation_id,
                    tenant_id=context.tenant_id,
                )

            self._record_stage_metrics(tenant_id, "email_enrichment", stage_start, status="success")
        except Exception as e:
            logger.error(f"Email enrichment failed for connector {connector['id']}: {e}")
            self._record_stage_metrics(tenant_id, "email_enrichment", stage_start, status="error", reason=str(e))
            raise

    async def _handle_scheduling(self, message: QueueMessage) -> None:
        """Handle email scheduling"""
        context = WorkflowContext(**message.payload['context'])
        connector = message.payload['connector']
        stage_start = datetime.now(timezone.utc)
        tenant_id = context.tenant_id

        try:
            # Schedule introduction email
            result = await self.scheduler.schedule_introduction(
                connector=connector,
                organization_id=context.organization_id,
                tenant_id=context.tenant_id
            )

            # Log completion
            await audit_logger.log_event(
                tenant_id=context.tenant_id,
                event_type=AuditEventType.EMAIL_CAMPAIGN_CREATED,
                action='email_job_scheduled',
                resource_type='email_job',
                user_id='workflow_integration',
                resource_id=result.job_id,
                details={
                    'workflow_id': context.workflow_id,
                    'connector_id': connector['id'],
                    'scheduled_at': result.scheduled_at.isoformat()
                },
                correlation_id=context.correlation_id
            )

            logger.info(f"Workflow {context.workflow_id} completed scheduling for connector {connector['id']}")
            self._record_stage_metrics(tenant_id, "scheduling", stage_start, status="success")

        except Exception as e:
            logger.error(f"Scheduling failed for connector {connector['id']}: {e}")
            self._record_stage_metrics(tenant_id, "scheduling", stage_start, status="error", reason=str(e))
            raise

    async def register_handlers(self) -> None:
        """Register message handlers with the Redis queue system"""
        if self.queue.redis_client is None:
            await self.queue.initialize()

        # Register handlers for each stage
        await self.queue.register_consumer(
            queue_type='ingestion',
            consumer_name='ingestion_handler',
            handler=self._handle_ingestion_message
        )

        await self.queue.register_consumer(
            queue_type='executive_lookup',
            consumer_name='executive_lookup_handler',
            handler=self._handle_executive_lookup_message
        )

        await self.queue.register_consumer(
            queue_type='linkedin_url_lookup',
            consumer_name='linkedin_url_lookup_handler',
            handler=self._handle_linkedin_url_lookup_message
        )

        await self.queue.register_consumer(
            queue_type='mutuals_discovery',
            consumer_name='mutuals_handler',
            handler=self._handle_mutuals_message
        )

        await self.queue.register_consumer(
            queue_type='connector_scoring',
            consumer_name='scoring_handler',
            handler=self._handle_scoring_message
        )

        await self.queue.register_consumer(
            queue_type='email_enrichment',
            consumer_name='enrichment_handler',
            handler=self._handle_enrichment_message
        )

        await self.queue.register_consumer(
            queue_type='email_scheduling',
            consumer_name='scheduler_handler',
            handler=self._handle_scheduling_message
        )

    async def _handle_ingestion_message(self, message) -> bool:
        """Handle ingestion message from Redis queue"""
        try:
            await self._handle_ingestion(message)
            return True
        except Exception as e:
            logger.error(f"Ingestion handler failed: {e}")
            return False

    async def _handle_executive_lookup_message(self, message) -> bool:
        """Handle executive lookup message from Redis queue"""
        try:
            await self._handle_executive_lookup(message)
            return True
        except Exception as e:
            logger.error(f"Executive lookup handler failed: {e}")
            return False

    async def _handle_linkedin_url_lookup_message(self, message) -> bool:
        """Handle LinkedIn URL lookup message from Redis queue"""
        try:
            await self._handle_linkedin_url_lookup(message)
            return True
        except Exception as e:
            logger.error(f"LinkedIn URL lookup handler failed: {e}")
            return False

    async def _handle_mutuals_message(self, message) -> bool:
        """Handle mutuals search message from Redis queue"""
        try:
            await self._handle_mutuals_search(message)
            return True
        except Exception as e:
            logger.error(f"Mutuals search handler failed: {e}")
            return False

    async def _handle_scoring_message(self, message) -> bool:
        """Handle scoring message from Redis queue"""
        try:
            await self._handle_scoring(message)
            return True
        except Exception as e:
            logger.error(f"Scoring handler failed: {e}")
            return False

    async def _handle_enrichment_message(self, message) -> bool:
        """Handle enrichment message from Redis queue"""
        try:
            await self._handle_enrichment(message)
            return True
        except Exception as e:
            logger.error(f"Enrichment handler failed: {e}")
            return False

    async def _handle_scheduling_message(self, message) -> bool:
        """Handle scheduling message from Redis queue"""
        try:
            await self._handle_scheduling(message)
            return True
        except Exception as e:
            logger.error(f"Scheduling handler failed: {e}")
            return False

    def _record_stage_metrics(
        self,
        tenant_id: str,
        stage: str,
        start_time: datetime,
        status: str,
        reason: Optional[str] = None
    ) -> None:
        """Record stage metrics if Prometheus is available."""

        if not prometheus_metrics:
            return

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        prometheus_metrics.record_corporate_stage_duration(tenant_id, stage, duration, status=status)

        if status == "error" and reason:
            prometheus_metrics.record_corporate_stage_failure(tenant_id, stage, reason)

    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get status of a workflow"""
        # This would query the database for workflow status
        # Implementation depends on your status tracking approach
        return {
            'workflow_id': workflow_id,
            'status': 'in_progress',
            'stages_completed': [],
            'current_stage': 'unknown',
            'created_at': datetime.now(timezone.utc).isoformat()
        }

# Global instance
workflow_integration = CorporateWorkflowIntegration()

# Example usage
async def main():
    """Example of starting a workflow"""
    workflow_id = await workflow_integration.start_workflow(
        organization_id='org-123',
        tenant_id='tenant-456',
        user_id=789,
        file_path='/path/to/prospects.csv'
    )

    print(f"Started workflow: {workflow_id}")

    # Register message handlers
    await workflow_integration.register_handlers()

    # Keep the service running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
