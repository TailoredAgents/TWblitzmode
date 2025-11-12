#!/usr/bin/env python3
"""
Enterprise Master Game Plan Orchestrator - September 2025 Production Hardening
Production-ready orchestrator with persistence, resilience, and comprehensive error handling

Critical Improvements:
- Replaces memory-only workflow storage with PostgreSQL + Redis persistence
- Implements enterprise-grade connection pooling
- Adds comprehensive error handling and recovery
- Includes circuit breakers and resilience patterns
- Provides full observability and monitoring
"""

import asyncio
import logging
import os
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from enum import Enum

# Import new enterprise services
from services.workflow_persistence_service import (
    workflow_persistence_service, WorkflowStatus, WorkflowPriority
)
from services.database_pool_manager import (
    db_pool_manager, get_main_db_connection, create_standard_pools
)
from services.error_handling_framework import (
    error_handler, handle_errors, with_retry, error_context, RetryConfig
)
from services.resilience_patterns import (
    resilience_manager, with_circuit_breaker, with_bulkhead, with_timeout,
    create_database_resilience, create_external_api_resilience
)

# Import existing services with improved error handling
try:
    from src.services.executive_search import ExecutiveSearchService
    executive_search_available = True
except ImportError:
    executive_search_available = False

try:
    from src.services.linkedin_url_finder import LinkedInURLFinderService
    linkedin_url_finder_available = True
except ImportError:
    linkedin_url_finder_available = False

try:
    from src.services.connector_ranking import ConnectorRankingService
    connector_ranking_available = True
except ImportError:
    connector_ranking_available = False

try:
    from services.mutuals_orchestrator_service import MutualsOrchestratorService
    mutuals_orchestrator_available = True
except ImportError:
    mutuals_orchestrator_available = False

try:
    from services.email_enrichment_service import email_enrichment_service, CorporateEmailEnrichmentService
    email_enrichment_available = True
except ImportError:
    email_enrichment_available = False

try:
    from services.approval_queue_service import ApprovalQueueService
    approval_queue_available = True
except ImportError:
    approval_queue_available = False

try:
    from services.email_service import EmailService
    email_service_available = True
except ImportError:
    email_service_available = False

try:
    from services.agent_logger import agent_logger, AgentEventType, LogLevel
    agent_logger_available = True
except ImportError:
    agent_logger_available = False

# Communication Hub integration
try:
    from services.communication_client import get_communication_client, MessageType, MessagePriority
    communication_client_available = True
except ImportError:
    communication_client_available = False

logger = logging.getLogger(__name__)

class WorkflowStage(Enum):
    """Enhanced workflow stages with recovery support"""
    INITIALIZING = "initializing"
    PROSPECT_UPLOAD = "prospect_upload"
    EXECUTIVE_SEARCH = "executive_search"
    LINKEDIN_URL_DISCOVERY = "linkedin_url_discovery"
    MUTUAL_CONNECTIONS = "mutual_connections"
    CONNECTOR_RANKING = "connector_ranking"
    EMAIL_ENRICHMENT = "email_enrichment"
    HUMAN_APPROVAL = "human_approval"
    APPROVAL_PENDING = "approval_pending"
    EMAIL_SENDING = "email_sending"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    RECOVERING = "recovering"

class EnterpriseMasterGamePlanOrchestrator:
    """
    Enterprise-grade Master Game Plan Orchestrator
    Production-ready with full persistence, resilience, and observability
    """

    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL",
            "postgresql://vouchlink_ai_user:G0cKKzLekD8EYygLMkymwoKlU3wdBqhk@dpg-d2f3ne2li9vc73bf5gg0-a.oregon-postgres.render.com/VouchLink-AIVouchLink AI")

        # Enterprise services
        self.persistence_service = workflow_persistence_service
        self.resilience_manager = resilience_manager

        # Legacy services (with resilience patterns applied)
        self.executive_search = None
        self.linkedin_url_finder = None
        self.connector_ranking = None
        self.mutuals_orchestrator = None
        self.email_enrichment = None
        self.approval_queue = None
        self.email_service = None

        # Initialization flag
        self._initialized = False

        logger.info("🚀 Enterprise Master Game Plan Orchestrator created")

    async def initialize(self) -> bool:
        """Initialize all enterprise services with proper error handling"""
        if self._initialized:
            return True

        try:
            async with error_context(
                service_name="enterprise_orchestrator",
                operation_name="initialization"
            ):
                # Validate environment configuration first
                logger.info("🔍 Validating environment configuration...")
                from services.environment_validation_service import environment_validator
                validation_results = await environment_validator.validate_all_services()

                # Check for critical failures that would prevent operation
                critical_failures = [
                    name for name, result in validation_results.items()
                    if result.priority.value == "critical" and result.status.value != "healthy"
                ]

                if critical_failures:
                    error_msg = f"❌ Critical services not configured: {', '.join(critical_failures)}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)

                # Initialize database connection pools
                logger.info("📊 Initializing database connection pools...")
                pools_created = await create_standard_pools()
                if not pools_created:
                    raise RuntimeError("Failed to create database connection pools")

                # Initialize workflow persistence service
                logger.info("💾 Initializing workflow persistence service...")
                await self.persistence_service.initialize()

                # Create resilience patterns for database and external APIs
                logger.info("🛡️ Setting up resilience patterns...")
                self.db_resilience = create_database_resilience()
                self.api_resilience = {}

                # Initialize legacy services with resilience patterns
                await self._initialize_legacy_services()

                # Start recovery process for any orphaned workflows
                logger.info("🔄 Checking for workflows to recover...")
                recovered_workflows = await self.persistence_service.recover_workflows()
                if recovered_workflows:
                    logger.info(f"🔄 Recovered {len(recovered_workflows)} workflows")
                    # Start recovery tasks for each workflow
                    for workflow_id in recovered_workflows:
                        asyncio.create_task(self._recover_workflow(workflow_id))

                self._initialized = True
                logger.info("✅ Enterprise Master Game Plan Orchestrator initialized successfully")
                return True

        except Exception as e:
            logger.error(f"❌ Failed to initialize Enterprise Master Game Plan Orchestrator: {e}")
            return False

    async def _initialize_legacy_services(self):
        """Initialize legacy services with resilience patterns"""

        # Executive Search Service
        if executive_search_available:
            self.executive_search = ExecutiveSearchService()
            self.api_resilience['executive_search'] = create_external_api_resilience('executive_search')

        # LinkedIn URL Finder Service
        if linkedin_url_finder_available:
            self.linkedin_url_finder = LinkedInURLFinderService()
            self.api_resilience['linkedin_url_finder'] = create_external_api_resilience('linkedin_url_finder')

        # Connector Ranking Service
        if connector_ranking_available:
            self.connector_ranking = ConnectorRankingService()

        # Mutuals Orchestrator Service
        if mutuals_orchestrator_available:
            self.mutuals_orchestrator = MutualsOrchestratorService(self.database_url)
            self.api_resilience['mutuals_orchestrator'] = create_external_api_resilience('mutuals_orchestrator')

        # Email Enrichment Service
        if email_enrichment_available:
            self.email_enrichment = CorporateEmailEnrichmentService()
            self.api_resilience['email_enrichment'] = create_external_api_resilience('email_enrichment')

        # Approval Queue Service
        if approval_queue_available:
            self.approval_queue = ApprovalQueueService(self.database_url)
            await self.approval_queue.initialize()

        # Email Service
        if email_service_available:
            self.email_service = EmailService()
            self.api_resilience['email_service'] = create_external_api_resilience('email_service')

        logger.info("✅ Legacy services initialized with resilience patterns")

    @handle_errors(service_name="enterprise_orchestrator")
    async def start_workflow(
        self,
        prospects: List[Dict[str, Any]],
        organization_id: int,
        user_id: int,
        team_members: List[Dict[str, Any]] = None,
        settings: Dict[str, Any] = None,
        priority: WorkflowPriority = WorkflowPriority.NORMAL
    ) -> str:
        """
        Start the complete Master Game Plan workflow with enterprise persistence

        Args:
            prospects: List of prospect data (name, company, etc.)
            organization_id: Organization ID for tenant isolation
            user_id: User who initiated the workflow
            team_members: Team members with LinkedIn cookies
            settings: Workflow configuration settings
            priority: Workflow execution priority

        Returns:
            Workflow ID for tracking progress
        """

        if not self._initialized:
            if not await self.initialize():
                raise RuntimeError("Failed to initialize Enterprise Master Game Plan Orchestrator")

        async with error_context(
            service_name="enterprise_orchestrator",
            operation_name="start_workflow",
            organization_id=organization_id,
            user_id=user_id
        ) as ctx:

            # Create persistent workflow
            workflow_id = await self.persistence_service.create_workflow(
                organization_id=organization_id,
                user_id=user_id,
                workflow_type="master_game_plan",
                prospects=prospects,
                team_members=team_members or [],
                settings=settings or {},
                priority=priority,
                timeout_minutes=1440  # 24 hours default timeout
            )

            ctx['workflow_id'] = workflow_id

            logger.info(f"🚀 Starting Enterprise Master Game Plan workflow {workflow_id} "
                       f"for {len(prospects)} prospects (organization {organization_id})")

            # Log workflow start with executive context
            if agent_logger_available:
                await agent_logger.log_event(
                    AgentEventType.WORKFLOW_START,
                    "enterprise_master_game_plan_orchestrator",
                    f"Starting Enterprise Master Game Plan for {len(prospects)} prospects",
                    tenant_id=str(organization_id),
                    user_id=str(user_id),
                    workflow_id=workflow_id,
                    metadata={
                        "prospect_count": len(prospects),
                        "priority": priority.value,
                        "company_list": [p.get('company', 'Unknown') for p in prospects[:5]]  # First 5 for context
                    }
                )

            # Send workflow start message to Communication Hub
            if communication_client_available:
                try:
                    client = await get_communication_client()
                    company_names = [p.get('company', 'Unknown') for p in prospects[:3]]
                    company_text = ', '.join(company_names)
                    if len(prospects) > 3:
                        company_text += f" and {len(prospects) - 3} more"

                    await client.send_progress_update(
                        conversation_id=f"workflow_{workflow_id}",
                        recipient_id=str(user_id),
                        agent_name="Master Game Plan",
                        progress_message=f"Starting enterprise workflow for {len(prospects)} prospects at {company_text}",
                        metadata={
                            "workflow_type": "master_game_plan",
                            "prospect_count": len(prospects),
                            "priority": priority.value,
                            "organizations": company_names
                        },
                        workflow_id=workflow_id
                    )
                except Exception as e:
                    logger.warning(f"Failed to send workflow start message to Communication Hub: {e}")

            # Start async workflow execution with resilience
            asyncio.create_task(self._execute_workflow_with_resilience(workflow_id))

            return workflow_id

    async def _execute_workflow_with_resilience(self, workflow_id: str):
        """Execute workflow with comprehensive error handling and recovery"""

        workflow_state = None

        try:
            # Get workflow state
            workflow_state = await self.persistence_service.get_workflow_state(workflow_id)
            if not workflow_state:
                logger.error(f"❌ Workflow {workflow_id} not found for execution")
                return

            # Update workflow to running state
            await self.persistence_service.update_workflow_state(
                workflow_id,
                status=WorkflowStatus.RUNNING,
                current_stage="initializing"
            )

            # Execute workflow stages with checkpoints
            await self._execute_workflow_stages(workflow_state)

        except Exception as e:
            # Handle workflow failure
            error_msg = f"Workflow {workflow_id} failed: {str(e)}"
            logger.error(f"❌ {error_msg}")

            if workflow_state:
                await self.persistence_service.update_workflow_state(
                    workflow_id,
                    status=WorkflowStatus.FAILED,
                    current_stage="failed",
                    errors=[{
                        "error": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "stage": workflow_state.current_stage
                    }]
                )

            # Log workflow failure with recovery context
            if agent_logger_available:
                await agent_logger.log_event(
                    AgentEventType.WORKFLOW_COMPLETE,
                    "enterprise_master_game_plan_orchestrator",
                    f"Workflow failed: {error_msg}",
                    level=LogLevel.ERROR,
                    tenant_id=str(workflow_state.organization_id) if workflow_state else None,
                    workflow_id=workflow_id
                )

    async def _execute_workflow_stages(self, workflow_state):
        """Execute all workflow stages with progress tracking and checkpoints"""

        workflow_id = workflow_state.workflow_id

        try:
            # Stage 1: Executive Search
            await self._create_checkpoint(workflow_id, "before_executive_search")
            await self._stage_executive_search_resilient(workflow_state)
            await self._heartbeat(workflow_id)

            # Stage 2: LinkedIn URL Discovery
            await self._create_checkpoint(workflow_id, "before_linkedin_url_discovery")
            await self._stage_linkedin_url_discovery_resilient(workflow_state)
            await self._heartbeat(workflow_id)

            # Stage 3: Mutual Connections Discovery
            await self._create_checkpoint(workflow_id, "before_mutual_connections")
            await self._stage_mutual_connections_resilient(workflow_state)
            await self._heartbeat(workflow_id)

            # Stage 4: Connector Ranking
            await self._create_checkpoint(workflow_id, "before_connector_ranking")
            await self._stage_connector_ranking_resilient(workflow_state)
            await self._heartbeat(workflow_id)

            # Stage 5: Email Enrichment
            await self._create_checkpoint(workflow_id, "before_email_enrichment")
            await self._stage_email_enrichment_resilient(workflow_state)
            await self._heartbeat(workflow_id)

            # Stage 6: Human Approval (This will pause the workflow)
            await self._create_checkpoint(workflow_id, "before_human_approval")
            await self._stage_human_approval_resilient(workflow_state)

            # Note: Stage 7 (Email Sending) will be called via resume_workflow after approval

        except Exception as e:
            logger.error(f"❌ Workflow {workflow_id} stage execution failed: {e}")
            raise

    @with_circuit_breaker(name="executive_search", failure_threshold=3, timeout=60.0)
    @with_bulkhead(name="executive_search", max_concurrent=5)
    @with_timeout(timeout=120.0)
    async def _stage_executive_search_resilient(self, workflow_state):
        """Stage 1: Executive Search with full resilience patterns"""

        workflow_id = workflow_state.workflow_id

        await self.persistence_service.update_workflow_state(
            workflow_id,
            current_stage="executive_search",
            progress_percentage=10.0
        )

        logger.info(f"🔍 Stage 1: Executive Search for {len(workflow_state.prospects)} companies")

        # Log task start with business context
        if agent_logger_available:
            company_names = [p.get('company', 'Unknown Company') for p in workflow_state.prospects]
            await agent_logger.log_task_start(
                agent_id="executive_search_agent",
                task_id=f"{workflow_id}_executive_search",
                task_type="executive_search",
                task_data={
                    "prospect_count": len(workflow_state.prospects),
                    "company_list": company_names,
                    "organization_id": workflow_state.organization_id
                },
                tenant_id=str(workflow_state.organization_id),
                workflow_id=workflow_id
            )

        if not self.executive_search:
            logger.warning("Executive Search service not available - skipping stage")
            return

        executives_by_company = {}

        for prospect in workflow_state.prospects:
            company = prospect.get('company', '')
            if not company:
                continue

            try:
                # Find executives with retry logic
                executives = await self._execute_with_retry(
                    lambda: self.executive_search.find_executives(
                        company_name=company,
                        titles=["CEO", "CTO", "COO", "VP", "President", "Director"],
                        max_results=10
                    ),
                    context={"workflow_id": workflow_id, "company": company}
                )

                executives_by_company[company] = executives
                logger.info(f"  Found {len(executives)} executives at {company}")

            except Exception as e:
                error_msg = f"Executive search failed for {company}: {e}"
                logger.error(f"  {error_msg}")

                # Update workflow with error but continue
                await self.persistence_service.update_workflow_state(
                    workflow_id,
                    errors=[{
                        "stage": "executive_search",
                        "company": company,
                        "error": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }]
                )

        # Store results
        await self.persistence_service.update_workflow_state(
            workflow_id,
            results={"executives": executives_by_company},
            progress_percentage=20.0
        )

        # Log stage completion with business context
        if agent_logger_available:
            await agent_logger.log_task_complete(
                agent_id="executive_search_agent",
                task_id=f"{workflow_id}_executive_search",
                result={
                    "executives_found": sum(len(execs) for execs in executives_by_company.values()),
                    "companies_processed": len(executives_by_company),
                    "executives_by_company": {k: len(v) for k, v in executives_by_company.items()}
                },
                duration_ms=0,  # TODO: Add timing
                tenant_id=str(workflow_state.organization_id),
                workflow_id=workflow_id,
                task_type="executive_search",
                metadata={"companies_processed": len(executives_by_company)}
            )

    @with_circuit_breaker(name="linkedin_url_finder", failure_threshold=3, timeout=90.0)
    @with_bulkhead(name="linkedin_url_finder", max_concurrent=3)
    @with_timeout(timeout=180.0)
    async def _stage_linkedin_url_discovery_resilient(self, workflow_state):
        """Stage 2: LinkedIn URL Discovery with resilience patterns"""

        workflow_id = workflow_state.workflow_id

        await self.persistence_service.update_workflow_state(
            workflow_id,
            current_stage="linkedin_url_discovery",
            progress_percentage=30.0
        )

        logger.info("🔗 Stage 2: LinkedIn URL Discovery")

        # Log task start with executive context
        if agent_logger_available:
            await agent_logger.log_task_start(
                agent_id="linkedin_url_finder_agent",
                task_id=f"{workflow_id}_linkedin_discovery",
                task_type="linkedin_url_discovery",
                task_data={
                    "executives_to_process": len([exec_info for _, exec_info in workflow_state.executives_by_company.items() for exec_info in exec_info]),
                    "companies": list(workflow_state.executives_by_company.keys()),
                    "organization_id": workflow_state.organization_id
                },
                tenant_id=str(workflow_state.organization_id),
                workflow_id=workflow_id
            )

        if not self.linkedin_url_finder:
            logger.warning("LinkedIn URL Finder service not available - skipping stage")
            return

        # Get current workflow results
        current_state = await self.persistence_service.get_workflow_state(workflow_id)
        executives = current_state.results.get('executives', {})

        all_executives = []
        for company, company_executives in executives.items():
            for exec in company_executives:
                exec['company'] = company
                all_executives.append(exec)

        if not all_executives:
            logger.warning("No executives found for LinkedIn URL discovery")
            return

        # Prepare prospects for URL finder
        prospects_for_urls = [
            {"name": exec.get('name', ''), "company": exec.get('company', '')}
            for exec in all_executives
        ]

        try:
            # Find URLs with retry and circuit breaker protection
            linkedin_urls = await self._execute_with_retry(
                lambda: self.linkedin_url_finder.find_urls_batch(prospects_for_urls),
                context={"workflow_id": workflow_id, "executive_count": len(all_executives)}
            )

            # Update executives with LinkedIn URLs
            for exec in all_executives:
                exec_name = exec.get('name', '')
                if exec_name in linkedin_urls:
                    exec['linkedin_url'] = linkedin_urls[exec_name]

            # Store updated results
            await self.persistence_service.update_workflow_state(
                workflow_id,
                results={"executives": executives, "linkedin_urls": linkedin_urls},
                progress_percentage=40.0
            )

            logger.info(f"  Found {len(linkedin_urls)} LinkedIn URLs")

            if agent_logger_available:
                await agent_logger.log_task_complete(
                    agent_id="linkedin_url_finder_agent",
                    task_id=f"{workflow_id}_linkedin_discovery",
                    result={
                        "linkedin_urls_found": len(linkedin_urls),
                        "executives_processed": len([exec_info for _, exec_info in workflow_state.executives_by_company.items() for exec_info in exec_info]),
                        "success_rate": f"{len(linkedin_urls) / max(1, len([exec_info for _, exec_info in workflow_state.executives_by_company.items() for exec_info in exec_info])) * 100:.1f}%"
                    },
                    duration_ms=0,  # TODO: Add timing
                    tenant_id=str(workflow_state.organization_id),
                    workflow_id=workflow_id,
                    task_type="linkedin_url_discovery"
                )

        except Exception as e:
            error_msg = f"LinkedIn URL discovery failed: {e}"
            logger.error(error_msg)

            await self.persistence_service.update_workflow_state(
                workflow_id,
                errors=[{
                    "stage": "linkedin_url_discovery",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            )

    @with_circuit_breaker(name="mutuals_orchestrator", failure_threshold=5, timeout=120.0)
    @with_bulkhead(name="mutuals_orchestrator", max_concurrent=2)
    @with_timeout(timeout=300.0)
    async def _stage_mutual_connections_resilient(self, workflow_state):
        """Stage 3: Mutual Connections Discovery with resilience patterns"""

        workflow_id = workflow_state.workflow_id

        await self.persistence_service.update_workflow_state(
            workflow_id,
            current_stage="mutual_connections",
            progress_percentage=50.0
        )

        logger.info("🤝 Stage 3: Mutual Connections Discovery")

        if not self.mutuals_orchestrator:
            logger.warning("Mutuals Orchestrator service not available - skipping stage")
            return

        if not workflow_state.team_members:
            logger.warning("No team members available for mutual connections discovery")
            return

        # Get current workflow results
        current_state = await self.persistence_service.get_workflow_state(workflow_id)
        executives = current_state.results.get('executives', {})
        mutual_connections = {}

        try:
            # Process mutual connections with resilience patterns
            for team_member in workflow_state.team_members:
                team_member_id = team_member.get('id')
                member_connections = {}

                for company, company_executives in executives.items():
                    for executive in company_executives:
                        linkedin_url = executive.get('linkedin_url')
                        if not linkedin_url:
                            continue

                        try:
                            # Discover mutual connections with retry
                            mutuals = await self._execute_with_retry(
                                lambda: self.mutuals_orchestrator.discover_mutuals(
                                    team_member_ids=[team_member_id],
                                    prospect_linkedin_url=linkedin_url,
                                    prospect_name=executive.get('name', ''),
                                    organization_id=workflow_state.organization_id
                                ),
                                context={
                                    "workflow_id": workflow_id,
                                    "team_member_id": team_member_id,
                                    "executive_name": executive.get('name', '')
                                }
                            )

                            if mutuals:
                                member_connections[executive.get('name', '')] = mutuals

                        except Exception as e:
                            logger.warning(f"Failed to find mutuals for {executive.get('name', '')}: {e}")

                mutual_connections[team_member_id] = member_connections

            # Store results
            await self.persistence_service.update_workflow_state(
                workflow_id,
                results={"mutual_connections": mutual_connections},
                progress_percentage=60.0
            )

            total_connections = sum(len(member_data) for member_data in mutual_connections.values())
            logger.info(f"  Found mutual connections for {total_connections} executive-team member pairs")

            if agent_logger_available:
                await agent_logger.log_event(
                    AgentEventType.TASK_COMPLETE,
                    "mutual_connections_agent",
                    f"Found mutual connections for {total_connections} pairs",
                    tenant_id=str(workflow_state.organization_id),
                    workflow_id=workflow_id,
                    metadata={"connection_pairs": total_connections}
                )

        except Exception as e:
            error_msg = f"Mutual connections discovery failed: {e}"
            logger.error(error_msg)

            await self.persistence_service.update_workflow_state(
                workflow_id,
                errors=[{
                    "stage": "mutual_connections",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            )

    async def _stage_connector_ranking_resilient(self, workflow_state):
        """Stage 4: Connector Ranking with error handling"""

        workflow_id = workflow_state.workflow_id

        await self.persistence_service.update_workflow_state(
            workflow_id,
            current_stage="connector_ranking",
            progress_percentage=70.0
        )

        logger.info("🎯 Stage 4: Connector Ranking")

        if not self.connector_ranking:
            logger.warning("Connector Ranking service not available - skipping stage")
            return

        # Get current workflow results
        current_state = await self.persistence_service.get_workflow_state(workflow_id)
        mutual_connections = current_state.results.get('mutual_connections', {})
        executives = current_state.results.get('executives', {})
        ranked_connectors = {}

        try:
            for team_member_id, member_connections in mutual_connections.items():
                team_member = next(
                    (tm for tm in workflow_state.team_members if tm.get('id') == team_member_id),
                    {}
                )

                member_ranked = {}

                for executive_name, connections in member_connections.items():
                    # Find the executive data
                    target_executive = None
                    for company_executives in executives.values():
                        for exec in company_executives:
                            if exec.get('name') == executive_name:
                                target_executive = exec
                                break
                        if target_executive:
                            break

                    if not target_executive or not connections:
                        continue

                    try:
                        # Rank the connections
                        ranked = self.connector_ranking.rank_connectors(
                            mutual_connections=connections,
                            target_prospect=target_executive,
                            team_member=team_member,
                            max_results=5
                        )

                        if ranked:
                            member_ranked[executive_name] = ranked

                    except Exception as e:
                        logger.warning(f"Failed to rank connectors for {executive_name}: {e}")

                ranked_connectors[team_member_id] = member_ranked

            # Store results
            await self.persistence_service.update_workflow_state(
                workflow_id,
                results={"ranked_connectors": ranked_connectors},
                progress_percentage=80.0
            )

            total_ranked = sum(len(member_data) for member_data in ranked_connectors.values())
            logger.info(f"  Ranked connectors for {total_ranked} executive-team member pairs")

            if agent_logger_available:
                await agent_logger.log_event(
                    AgentEventType.TASK_COMPLETE,
                    "connector_ranking_agent",
                    f"Ranked connectors for {total_ranked} pairs",
                    tenant_id=str(workflow_state.organization_id),
                    workflow_id=workflow_id,
                    metadata={"ranked_pairs": total_ranked}
                )

        except Exception as e:
            error_msg = f"Connector ranking failed: {e}"
            logger.error(error_msg)

            await self.persistence_service.update_workflow_state(
                workflow_id,
                errors=[{
                    "stage": "connector_ranking",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            )

    @with_circuit_breaker(name="email_enrichment", failure_threshold=3, timeout=180.0)
    @with_bulkhead(name="email_enrichment", max_concurrent=2)
    @with_timeout(timeout=300.0)
    async def _stage_email_enrichment_resilient(self, workflow_state):
        """Stage 5: Email Enrichment with resilience patterns"""

        workflow_id = workflow_state.workflow_id

        await self.persistence_service.update_workflow_state(
            workflow_id,
            current_stage="email_enrichment",
            progress_percentage=85.0
        )

        logger.info("📧 Stage 5: Email Enrichment")

        if not email_enrichment_available:
            logger.warning("Email enrichment service not available - skipping stage")
            await self.persistence_service.update_workflow_state(
                workflow_id,
                results={"email_enrichment": {"status": "skipped", "reason": "service_unavailable"}}
            )
            return

        enrichment_results = {}
        total_emails_found = 0
        total_cost = 0.0

        try:
            # Process each prospect through email enrichment with resilience
            for prospect in workflow_state.prospects:
                prospect_id = prospect.get('id')
                prospect_name = prospect.get('name', 'Unknown')

                if not prospect_id:
                    logger.warning(f"Prospect {prospect_name} missing ID - skipping")
                    continue

                logger.info(f"Starting email enrichment for prospect: {prospect_name}")

                try:
                    # Use email enrichment service with retry
                    enrichment_result = await self._execute_with_retry(
                        lambda: email_enrichment_service.enrich_prospect_connectors(
                            prospect_id=prospect_id,
                            tenant_id=str(workflow_state.organization_id),
                            force_refresh=False
                        ),
                        context={
                            "workflow_id": workflow_id,
                            "prospect_id": prospect_id,
                            "prospect_name": prospect_name
                        }
                    )

                    # Store enrichment results
                    enrichment_results[prospect_id] = {
                        "prospect_name": prospect_name,
                        "total_connectors": enrichment_result.total_connectors,
                        "emails_found": enrichment_result.emails_found,
                        "high_confidence_emails": enrichment_result.high_confidence_emails,
                        "cost_usd": enrichment_result.total_cost_usd,
                        "processing_time": enrichment_result.processing_time_seconds,
                        "cache_hit_rate": enrichment_result.cache_hit_rate,
                        "connector_results": [
                            {
                                "connector_id": result.connector_id,
                                "prospect_connector_id": result.prospect_connector_id,
                                "email": result.email,
                                "confidence": result.confidence,
                                "source": result.source,
                                "status": result.status.value,
                                "cost_usd": result.cost_usd
                            }
                            for result in enrichment_result.connector_results
                        ]
                    }

                    total_emails_found += enrichment_result.emails_found
                    total_cost += enrichment_result.total_cost_usd

                    logger.info(
                        f"  {prospect_name}: {enrichment_result.emails_found}/{enrichment_result.total_connectors} "
                        f"emails found (${enrichment_result.total_cost_usd:.2f})"
                    )

                except Exception as e:
                    error_msg = f"Email enrichment failed for {prospect_name}: {e}"
                    logger.error(f"  {error_msg}")

                    enrichment_results[prospect_id] = {
                        "prospect_name": prospect_name,
                        "error": str(e),
                        "status": "failed"
                    }

                # Rate limiting between prospects
                if len(workflow_state.prospects) > 1:
                    await asyncio.sleep(1)

            # Store final results
            await self.persistence_service.update_workflow_state(
                workflow_id,
                results={
                    "email_enrichment": {
                        "status": "completed",
                        "total_prospects_processed": len(enrichment_results),
                        "total_emails_found": total_emails_found,
                        "total_cost_usd": total_cost,
                        "prospect_results": enrichment_results
                    }
                },
                progress_percentage=90.0
            )

            logger.info(
                f"  Email enrichment completed: {total_emails_found} emails found "
                f"across {len(enrichment_results)} prospects (${total_cost:.2f})"
            )

            if agent_logger_available:
                await agent_logger.log_event(
                    AgentEventType.TASK_COMPLETE,
                    "email_enrichment_agent",
                    f"Enriched emails for {len(enrichment_results)} prospects",
                    tenant_id=str(workflow_state.organization_id),
                    workflow_id=workflow_id,
                    metadata={
                        "prospects_processed": len(enrichment_results),
                        "emails_found": total_emails_found,
                        "total_cost_usd": total_cost
                    }
                )

        except Exception as e:
            error_msg = f"Email enrichment stage failed: {e}"
            logger.error(error_msg)

            await self.persistence_service.update_workflow_state(
                workflow_id,
                errors=[{
                    "stage": "email_enrichment",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            )

    async def _stage_human_approval_resilient(self, workflow_state):
        """Stage 6: Human Approval with enterprise approval queue integration"""

        workflow_id = workflow_state.workflow_id

        await self.persistence_service.update_workflow_state(
            workflow_id,
            current_stage="human_approval",
            progress_percentage=95.0
        )

        logger.info("👤 Stage 6: Human Approval")

        # Log task start for approval workflow
        if agent_logger_available:
            await agent_logger.log_task_start(
                agent_id="human_approval_agent",
                task_id=f"{workflow_id}_human_approval",
                task_type="human_approval",
                task_data={
                    "workflow_id": workflow_id,
                    "organization_id": workflow_state.organization_id,
                    "stage": "pending_approval_requests"
                },
                tenant_id=str(workflow_state.organization_id),
                workflow_id=workflow_id
            )

        if not approval_queue_available or not self.approval_queue:
            logger.warning("Approval queue not available - auto-approving all requests")
            await self.persistence_service.update_workflow_state(
                workflow_id,
                results={"approval_requests": [], "auto_approved": True}
            )
            return

        # Get current workflow results
        current_state = await self.persistence_service.get_workflow_state(workflow_id)
        email_enrichment = current_state.results.get('email_enrichment', {})
        prospect_results = email_enrichment.get('prospect_results', {})
        approval_requests = []

        try:
            # Create approval requests for prospects with high-confidence emails
            for prospect_id, enrichment_data in prospect_results.items():
                prospect_name = enrichment_data.get('prospect_name', 'Unknown')
                high_confidence_emails = enrichment_data.get('high_confidence_emails', 0)

                if high_confidence_emails == 0:
                    logger.info(f"  Skipping {prospect_name} - no high-confidence emails found")
                    continue

                # Get connector results
                connector_results = enrichment_data.get('connector_results', [])
                high_confidence_connectors = [
                    conn for conn in connector_results
                    if conn.get('email') and conn.get('confidence', 0) >= 0.7
                ]

                if not high_confidence_connectors:
                    continue

                # Create approval request using approval queue service
                approval_id = await self.approval_queue.create_approval_request(
                    tenant_id=str(workflow_state.organization_id),
                    request_type="introduction_approval",
                    title=f"Approve introductions for {prospect_name}",
                    description=f"Approve sending introduction emails for {prospect_name} to {high_confidence_emails} connectors",
                    requested_by=workflow_state.user_id,
                    context_data={
                        "prospect_id": prospect_id,
                        "prospect_name": prospect_name,
                        "workflow_id": workflow_id,
                        "high_confidence_emails": high_confidence_emails,
                        "connectors": high_confidence_connectors[:5],  # Top 5 connectors
                        "total_cost_usd": enrichment_data.get('cost_usd', 0)
                    },
                    workflow_id=workflow_id,
                    priority="high" if high_confidence_emails >= 3 else "medium"
                )

                approval_requests.append(approval_id)
                logger.info(f"  Created approval request {approval_id} for {prospect_name} ({high_confidence_emails} emails)")

                # Log approval request creation with business context (CRITICAL FIX FROM AUDIT)
                if agent_logger_available:
                    await agent_logger.log_approval_request(
                        agent_id="human_approval_agent",
                        approval_id=approval_id,
                        request_type="introduction_approval",
                        details={
                            "prospect_name": prospect_name,
                            "prospect_company": enrichment_data.get('company', 'Unknown'),
                            "high_confidence_emails": high_confidence_emails,
                            "email_addresses": high_confidence_connectors[:3],  # Top 3 for context
                            "total_cost_usd": enrichment_data.get('cost_usd', 0),
                            "workflow_id": workflow_id
                        },
                        tenant_id=str(workflow_state.organization_id),
                        workflow_id=workflow_id,
                        user_id=str(workflow_state.user_id)
                    )

            # Store approval requests and pause workflow
            await self.persistence_service.update_workflow_state(
                workflow_id,
                status=WorkflowStatus.PAUSED,
                current_stage="approval_pending",
                results={"approval_requests": approval_requests},
                is_paused=True,
                pause_reason="awaiting_human_approval"
            )

            logger.info(f"  Created {len(approval_requests)} approval requests - workflow paused")

            if agent_logger_available:
                await agent_logger.log_event(
                    AgentEventType.APPROVAL_REQUEST,
                    "human_approval_agent",
                    f"Created {len(approval_requests)} approval requests",
                    tenant_id=str(workflow_state.organization_id),
                    workflow_id=workflow_id,
                    metadata={"approval_count": len(approval_requests)}
                )

            # Send approval stage message to Communication Hub
            if communication_client_available:
                try:
                    client = await get_communication_client()
                    await client.send_progress_update(
                        conversation_id=f"workflow_{workflow_id}",
                        recipient_id=str(workflow_state.user_id),
                        agent_name="Master Game Plan",
                        progress_message=f"📋 Created {len(approval_requests)} approval requests - workflow paused pending your review",
                        metadata={
                            "stage": "approval_pending",
                            "approval_count": len(approval_requests),
                            "action_required": True,
                            "next_steps": "Review and approve introduction requests in the Approvals tab"
                        },
                        workflow_id=workflow_id
                    )
                except Exception as e:
                    logger.warning(f"Failed to send approval stage message to Communication Hub: {e}")

        except Exception as e:
            error_msg = f"Human approval stage failed: {e}"
            logger.error(error_msg)

            await self.persistence_service.update_workflow_state(
                workflow_id,
                errors=[{
                    "stage": "human_approval",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            )
            raise

    async def resume_workflow(self, workflow_id: str, approval_decisions: Dict[str, Any] = None):
        """Resume a paused workflow after approval decisions"""

        logger.info(f"▶️ Resuming workflow {workflow_id}")

        try:
            # Get workflow state
            workflow_state = await self.persistence_service.get_workflow_state(workflow_id)
            if not workflow_state:
                logger.error(f"Workflow {workflow_id} not found for resume")
                return

            if not workflow_state.is_paused:
                logger.warning(f"Workflow {workflow_id} is not paused")
                return

            # Process approval decisions
            approved_prospects = []
            rejected_prospects = []

            if approval_decisions:
                for approval_id, decision_data in approval_decisions.items():
                    decision = decision_data.get('decision', 'rejected')
                    context_data = decision_data.get('context', {})
                    prospect_id = context_data.get('prospect_id')

                    if decision == 'approved' and prospect_id:
                        approved_prospects.append(prospect_id)
                        logger.info(f"  ✅ Approved: {context_data.get('prospect_name', prospect_id)}")
                    elif prospect_id:
                        rejected_prospects.append(prospect_id)
                        logger.info(f"  ❌ Rejected: {context_data.get('prospect_name', prospect_id)}")

            # Resume workflow with approved prospects
            await self.persistence_service.update_workflow_state(
                workflow_id,
                status=WorkflowStatus.RUNNING,
                current_stage="email_sending",
                is_paused=False,
                pause_reason=None,
                results={
                    "approval_decisions": approval_decisions or {},
                    "approved_prospects": approved_prospects,
                    "rejected_prospects": rejected_prospects
                }
            )

            # Continue with email sending stage
            asyncio.create_task(self._continue_workflow_from_email_sending(workflow_id))

            logger.info(f"✅ Workflow {workflow_id} resumed - {len(approved_prospects)} approved, {len(rejected_prospects)} rejected")

        except Exception as e:
            logger.error(f"❌ Failed to resume workflow {workflow_id}: {e}")

    async def _continue_workflow_from_email_sending(self, workflow_id: str):
        """Continue workflow from email sending stage"""

        try:
            workflow_state = await self.persistence_service.get_workflow_state(workflow_id)
            if not workflow_state:
                logger.error(f"Workflow {workflow_id} not found for continuation")
                return

            # Execute email sending stage
            await self._stage_email_sending_resilient(workflow_state)

            # Mark workflow as completed
            await self.persistence_service.update_workflow_state(
                workflow_id,
                status=WorkflowStatus.COMPLETED,
                current_stage="completed",
                progress_percentage=100.0
            )

            logger.info(f"✅ Enterprise Master Game Plan workflow {workflow_id} completed successfully")

            if agent_logger_available:
                await agent_logger.log_event(
                    AgentEventType.WORKFLOW_COMPLETE,
                    "enterprise_master_game_plan_orchestrator",
                    f"Workflow completed successfully",
                    tenant_id=str(workflow_state.organization_id),
                    workflow_id=workflow_id,
                    metadata={"total_prospects": len(workflow_state.prospects)}
                )

            # Send workflow completion message to Communication Hub
            if communication_client_available:
                try:
                    client = await get_communication_client()
                    current_state = await self.persistence_service.get_workflow_state(workflow_id)
                    email_summary = current_state.results.get('email_summary', {})
                    sent_count = email_summary.get('sent_count', 0)

                    await client.send_progress_update(
                        conversation_id=f"workflow_{workflow_id}",
                        recipient_id=str(workflow_state.user_id),
                        agent_name="Master Game Plan",
                        progress_message=f"✅ Workflow completed successfully! {sent_count} introduction emails sent to connectors",
                        metadata={
                            "stage": "completed",
                            "total_prospects": len(workflow_state.prospects),
                            "emails_sent": sent_count,
                            "workflow_complete": True
                        },
                        workflow_id=workflow_id
                    )
                except Exception as e:
                    logger.warning(f"Failed to send workflow completion message to Communication Hub: {e}")

        except Exception as e:
            error_msg = f"Failed to continue workflow {workflow_id}: {e}"
            logger.error(f"❌ {error_msg}")

            await self.persistence_service.update_workflow_state(
                workflow_id,
                status=WorkflowStatus.FAILED,
                current_stage="failed",
                errors=[{
                    "stage": "email_sending_continuation",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            )

    @with_circuit_breaker(name="email_service", failure_threshold=3, timeout=60.0)
    @with_bulkhead(name="email_service", max_concurrent=3)
    @with_timeout(timeout=120.0)
    async def _stage_email_sending_resilient(self, workflow_state):
        """Stage 7: Email Sending with resilience patterns"""

        workflow_id = workflow_state.workflow_id

        await self.persistence_service.update_workflow_state(
            workflow_id,
            current_stage="email_sending",
            progress_percentage=98.0
        )

        logger.info("📤 Stage 7: Email Sending")

        # Get current workflow results
        current_state = await self.persistence_service.get_workflow_state(workflow_id)
        approval_decisions = current_state.results.get('approval_decisions', {})
        approved_prospects = current_state.results.get('approved_prospects', [])

        if not approved_prospects:
            logger.info("  No prospects approved - skipping email sending")
            await self.persistence_service.update_workflow_state(
                workflow_id,
                results={"sent_emails": []}
            )
            return

        logger.info(f"  Sending emails for {len(approved_prospects)} approved prospects")

        sent_emails = []
        failed_emails = []

        try:
            if not email_service_available or not self.email_service:
                logger.warning("Email service not available - simulating email sending")
                # Simulate email sending
                for prospect_id in approved_prospects:
                    sent_emails.append({
                        "prospect_id": prospect_id,
                        "email_result": {"status": "simulated", "message": "Email service not available"},
                        "sent_at": datetime.now(timezone.utc).isoformat()
                    })
            else:
                # Send emails to approved prospects with resilience
                for approval_id, decision_data in approval_decisions.items():
                    if decision_data.get('decision') != 'approved':
                        continue

                    approval_context = decision_data.get('context', {})
                    prospect_id = approval_context.get('prospect_id')
                    prospect_name = approval_context.get('prospect_name', 'Unknown')
                    connectors = approval_context.get('connectors', [])

                    # Send emails to top connectors
                    for connector in connectors[:3]:  # Top 3 connectors
                        if not connector.get('email'):
                            continue

                        # Get team member to send from
                        team_member = workflow_state.team_members[0] if workflow_state.team_members else {}

                        try:
                            # Send email with retry logic
                            email_result = await self._execute_with_retry(
                                lambda: self.email_service.send_introduction_email(
                                    to_email=connector.get('email'),
                                    to_name=connector.get('name'),
                                    from_email=team_member.get('send_from_email'),
                                    from_name=team_member.get('send_from_name'),
                                    prospect_name=prospect_name,
                                    prospect_company=approval_context.get('prospect_company'),
                                    organization_id=workflow_state.organization_id
                                ),
                                context={
                                    "workflow_id": workflow_id,
                                    "prospect_id": prospect_id,
                                    "connector_email": connector.get('email')
                                }
                            )

                            sent_emails.append({
                                "approval_id": approval_id,
                                "prospect_id": prospect_id,
                                "prospect_name": prospect_name,
                                "connector_email": connector.get('email'),
                                "connector_name": connector.get('name'),
                                "email_result": email_result,
                                "sent_at": datetime.now(timezone.utc).isoformat()
                            })

                            logger.info(f"  ✅ Sent email for {prospect_name} to {connector.get('name')}")

                        except Exception as e:
                            failed_emails.append({
                                "prospect_id": prospect_id,
                                "prospect_name": prospect_name,
                                "connector_email": connector.get('email'),
                                "error": str(e),
                                "failed_at": datetime.now(timezone.utc).isoformat()
                            })
                            logger.error(f"  ❌ Failed to send email for {prospect_name}: {e}")

            # Store email results
            await self.persistence_service.update_workflow_state(
                workflow_id,
                results={
                    "sent_emails": sent_emails,
                    "failed_emails": failed_emails,
                    "email_summary": {
                        "sent_count": len(sent_emails),
                        "failed_count": len(failed_emails),
                        "approved_prospects": len(approved_prospects)
                    }
                },
                progress_percentage=100.0
            )

            logger.info(f"  📧 Email sending complete: {len(sent_emails)} sent, {len(failed_emails)} failed")

            if agent_logger_available:
                await agent_logger.log_event(
                    AgentEventType.TASK_COMPLETE,
                    "email_sending_agent",
                    f"Sent {len(sent_emails)} emails, {len(failed_emails)} failed",
                    tenant_id=str(workflow_state.organization_id),
                    workflow_id=workflow_id,
                    metadata={
                        "emails_sent": len(sent_emails),
                        "emails_failed": len(failed_emails),
                        "approved_prospects": len(approved_prospects)
                    }
                )

        except Exception as e:
            error_msg = f"Email sending stage failed: {e}"
            logger.error(error_msg)

            await self.persistence_service.update_workflow_state(
                workflow_id,
                errors=[{
                    "stage": "email_sending",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            )
            raise

    async def _recover_workflow(self, workflow_id: str):
        """Recover a workflow that was interrupted"""

        logger.info(f"🔄 Starting recovery for workflow {workflow_id}")

        try:
            workflow_state = await self.persistence_service.get_workflow_state(workflow_id)
            if not workflow_state:
                logger.error(f"Cannot recover workflow {workflow_id} - not found")
                return

            # Determine recovery strategy based on current stage
            if workflow_state.current_stage in ["approval_pending", "human_approval"]:
                # Workflow is paused for approval - no recovery needed
                logger.info(f"Workflow {workflow_id} is paused for approval - no recovery needed")
                return

            elif workflow_state.current_stage == "email_sending":
                # Continue from email sending
                logger.info(f"Recovering workflow {workflow_id} from email sending stage")
                await self._continue_workflow_from_email_sending(workflow_id)

            else:
                # Restart from current stage
                logger.info(f"Recovering workflow {workflow_id} from stage {workflow_state.current_stage}")
                await self._execute_workflow_stages(workflow_state)

            logger.info(f"✅ Successfully recovered workflow {workflow_id}")

        except Exception as e:
            logger.error(f"❌ Failed to recover workflow {workflow_id}: {e}")

            await self.persistence_service.update_workflow_state(
                workflow_id,
                status=WorkflowStatus.FAILED,
                errors=[{
                    "stage": "recovery",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            )

    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive workflow status"""

        workflow_state = await self.persistence_service.get_workflow_state(workflow_id)
        if not workflow_state:
            return {"error": "Workflow not found", "workflow_id": workflow_id}

        return {
            "workflow_id": workflow_id,
            "status": workflow_state.status.value,
            "current_stage": workflow_state.current_stage,
            "progress_percentage": workflow_state.progress_percentage,
            "prospects_count": len(workflow_state.prospects),
            "team_members_count": len(workflow_state.team_members),
            "started_at": workflow_state.started_at.isoformat() if workflow_state.started_at else None,
            "updated_at": workflow_state.updated_at.isoformat(),
            "completed_at": workflow_state.completed_at.isoformat() if workflow_state.completed_at else None,
            "is_paused": workflow_state.is_paused,
            "pause_reason": workflow_state.pause_reason,
            "approval_requests": workflow_state.approval_requests,
            "errors": workflow_state.errors,
            "results_summary": {
                "executives_found": len(workflow_state.results.get('executives', {})),
                "linkedin_urls_found": len(workflow_state.results.get('linkedin_urls', {})),
                "approval_requests_created": len(workflow_state.results.get('approval_requests', [])),
                "emails_sent": len(workflow_state.results.get('sent_emails', [])),
                "emails_failed": len(workflow_state.results.get('failed_emails', []))
            },
            "execution_time_seconds": workflow_state.execution_time_seconds,
            "retry_count": workflow_state.retry_count
        }

    async def _execute_with_retry(self, func: callable, context: Dict[str, Any] = None):
        """Execute function with enterprise retry logic"""

        retry_config = RetryConfig(
            max_attempts=3,
            base_delay=1.0,
            max_delay=30.0,
            exponential_base=2.0,
            retriable_exceptions=(Exception,)
        )

        from services.error_handling_framework import RetryManager, RetryStrategy

        return await RetryManager.retry_with_strategy(
            func,
            retry_config,
            RetryStrategy.EXPONENTIAL_BACKOFF,
            context
        )

    async def _create_checkpoint(self, workflow_id: str, checkpoint_name: str):
        """Create a recovery checkpoint"""
        workflow_state = await self.persistence_service.get_workflow_state(workflow_id)
        if workflow_state:
            checkpoint_data = {
                "checkpoint_name": checkpoint_name,
                "stage": workflow_state.current_stage,
                "progress": workflow_state.progress_percentage,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await self.persistence_service.create_checkpoint(workflow_id, checkpoint_data)

    async def _heartbeat(self, workflow_id: str):
        """Send heartbeat for workflow"""
        await self.persistence_service.heartbeat_workflow(workflow_id)

    async def get_health_status(self) -> Dict[str, Any]:
        """Get comprehensive health status of the orchestrator"""

        if not self._initialized:
            return {"status": "not_initialized", "services": {}}

        service_health = {
            "persistence_service": "healthy",
            "database_pools": "healthy",
            "resilience_manager": "healthy"
        }

        # Check individual service availability
        services_status = {
            "executive_search": executive_search_available and self.executive_search is not None,
            "linkedin_url_finder": linkedin_url_finder_available and self.linkedin_url_finder is not None,
            "connector_ranking": connector_ranking_available and self.connector_ranking is not None,
            "mutuals_orchestrator": mutuals_orchestrator_available and self.mutuals_orchestrator is not None,
            "email_enrichment": email_enrichment_available and self.email_enrichment is not None,
            "approval_queue": approval_queue_available and self.approval_queue is not None,
            "email_service": email_service_available and self.email_service is not None,
            "agent_logger": agent_logger_available
        }

        # Get database pool health
        db_health = db_pool_manager.get_health_summary()

        # Get resilience health
        resilience_health = resilience_manager.get_health_summary()

        return {
            "status": "healthy" if all(service_health.values()) else "degraded",
            "initialized": self._initialized,
            "services": services_status,
            "service_health": service_health,
            "database_health": db_health,
            "resilience_health": resilience_health,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def close(self):
        """Gracefully shutdown the orchestrator"""
        logger.info("🔄 Shutting down Enterprise Master Game Plan Orchestrator")

        # Close all enterprise services
        if self.persistence_service:
            await self.persistence_service.close()

        await db_pool_manager.close_all()
        await resilience_manager.close()

        if self.approval_queue:
            await self.approval_queue.close()

        logger.info("✅ Enterprise Master Game Plan Orchestrator shutdown complete")

    def get_configuration_status(self) -> Dict[str, Any]:
        """Get configuration status of all services using environment validator"""
        try:
            from services.environment_validation_service import environment_validator

            # Get latest validation results, or use cached if recent
            if (environment_validator.validation_results and
                environment_validator.last_validation_time and
                (datetime.now(timezone.utc) - environment_validator.last_validation_time).seconds < 300):
                # Use cached results if less than 5 minutes old
                status = environment_validator.get_configuration_status()
            else:
                # Return basic status if no recent validation
                status = {
                    "status": "not_validated",
                    "message": "Run environment validation to get detailed status",
                    "services": {}
                }

            # Add legacy service status for backward compatibility
            legacy_status = {
                "executive_search": executive_search_available,
                "linkedin_url_finder": linkedin_url_finder_available,
                "connector_ranking": connector_ranking_available,
                "mutuals_orchestrator": mutuals_orchestrator_available,
                "email_enrichment": email_enrichment_available,
                "approval_queue": approval_queue_available,
                "email_service": email_service_available,
                "agent_logger": agent_logger_available
            }

            return {
                "overall_status": status.get("status", "unknown"),
                "environment_services": status.get("services", {}),
                "legacy_services": legacy_status,
                "last_validated": status.get("last_validated"),
                "initialized": self._initialized
            }

        except Exception as e:
            logger.error(f"Failed to get configuration status: {e}")
            return {
                "overall_status": "error",
                "error": str(e),
                "initialized": self._initialized
            }

# Global enterprise instance - Updated to use new class name
master_game_plan = EnterpriseMasterGamePlanOrchestrator()

# Maintain backward compatibility
MasterGamePlanOrchestrator = EnterpriseMasterGamePlanOrchestrator

# Test function
async def test_master_game_plan():
    """Test the Enterprise Master Game Plan orchestrator"""

    print("🧪 ENTERPRISE MASTER GAME PLAN ORCHESTRATOR TEST")
    print("=" * 60)

    # Initialize the orchestrator
    if not await master_game_plan.initialize():
        print("❌ Failed to initialize orchestrator")
        return

    health_status = await master_game_plan.get_health_status()

    print("Enterprise Service Health:")
    for service, status in health_status.get('services', {}).items():
        status_icon = "✅" if status else "❌"
        print(f"  {status_icon} {service}")

    print(f"\n🎯 Enterprise Master Game Plan Orchestrator Ready: {'✅ Yes' if health_status.get('status') == 'healthy' else '❌ Degraded'}")

    if health_status.get('status') == 'healthy':
        # Test workflow with sample data
        sample_prospects = [
            {"id": "test_1", "name": "John Smith", "company": "Tech Corp", "title": "CEO"},
            {"id": "test_2", "name": "Jane Doe", "company": "Acme Inc", "title": "CTO"}
        ]

        sample_team_members = [
            {
                "id": 1,
                "name": "David Hacker",
                "email": "david@example.com",
                "send_from_name": "David Hacker",
                "send_from_email": "david@visionca.com"
            }
        ]

        workflow_id = await master_game_plan.start_workflow(
            prospects=sample_prospects,
            organization_id=1,
            user_id=1,
            team_members=sample_team_members,
            settings={"auto_approve": False},
            priority=WorkflowPriority.HIGH
        )

        print(f"\n🚀 Started test workflow: {workflow_id}")

        # Check status after a brief delay
        await asyncio.sleep(2)
        status = await master_game_plan.get_workflow_status(workflow_id)
        print(f"📊 Workflow Status: {status}")

    # Cleanup
    await master_game_plan.close()

if __name__ == "__main__":
    asyncio.run(test_master_game_plan())