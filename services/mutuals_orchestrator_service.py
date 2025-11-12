"""
Mutuals Orchestrator Service - LinkedIn Mutual Connections Discovery
September 2025 - Enterprise-Grade Network Analysis

This service discovers mutual connections between prospects and team members using
LinkedIn automation with Apify integration, concurrent processing, and intelligent
cookie management.

Features:
- Apify LinkedIn Mutual Connections actor integration
- PhantomBuster fallback for enterprise clients
- Concurrent job processing with rate limiting
- Intelligent cookie vault integration
- Automated session validation and rotation
- Real-time progress tracking
- Comprehensive error handling and retry logic
"""

import asyncio
import json
import logging
import secrets
import random
import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict
from urllib.parse import urlparse
import traceback

import httpx
import asyncpg
from redis import Redis
import backoff

from api.db_core import get_conn as portal_get_conn, query as portal_query
from api.cookie_service import (
    load_cookie_payload,
    acquire_cookie_lock,
    release_cookie_lock,
    increment_cookie_usage,
    mark_cookie_status,
)

from core.settings import settings
from scripts.utils.postgres import DEFAULT_TEST_DSN, resolve_required_dsn
from services.cookie_vault_service import cookie_vault, VaultItemType
from services.audit_logging_service import audit_logger, AuditEventType, AuditSeverity

# Backwards compatibility alias for legacy Apify client patching in tests
try:  # pragma: no cover - optional dependency
    from integrations import apify_client as _apify_client_module
except ImportError:  # Legacy fallback when integrations module unavailable
    _apify_client_module = None

apify_client = _apify_client_module

# Import agent logger for real-time communication and cost tracking
try:
    from services.agent_logger import agent_logger, AgentEventType
    agent_logging_available = True
except ImportError:
    logging.warning("Agent logger not available in mutuals orchestrator service")
    agent_logging_available = False

# Communication Hub integration
try:
    from services.communication_client import get_communication_client, MessageType, MessagePriority
    communication_client_available = True
except ImportError:
    communication_client_available = False

logger = logging.getLogger(__name__)

class MutualsProvider(Enum):
    APIFY = "apify"
    PHANTOMBUSTER = "phantombuster"
    MANUAL = "manual"

class MutualsJobStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIALLY_COMPLETED = "partially_completed"
    RATE_LIMITED = "rate_limited"
    COOKIE_EXPIRED = "cookie_expired"

class SessionStatus(Enum):
    VALID = "valid"
    EXPIRED = "expired"
    RATE_LIMITED = "rate_limited"
    INVALID = "invalid"

@dataclass
class MutualConnection:
    linkedin_url: str
    full_name: str
    headline: Optional[str] = None
    current_company: Optional[str] = None
    current_title: Optional[str] = None
    location: Optional[str] = None
    profile_picture_url: Optional[str] = None
    connection_degree: int = 2  # Default to 2nd degree
    shared_connections_count: int = 0

@dataclass
class MutualsResult:
    """Wrapper returned to the workflow coordinator."""
    connectors: List[MutualConnection]
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
@dataclass
class MutualsDiscoveryJob:
    job_id: str
    tenant_id: str
    integration_set_id: str
    prospect_ids: List[str]
    team_member_ids: List[str]
    status: MutualsJobStatus
    total_prospects: int
    completed_prospects: int = 0
    failed_prospects: int = 0
    total_mutuals_found: int = 0
    apify_runs: List[Dict] = None
    results: List[Dict] = None
    error_details: List[Dict] = None
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.apify_runs is None:
            self.apify_runs = []
        if self.results is None:
            self.results = []
        if self.error_details is None:
            self.error_details = []
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = datetime.now(timezone.utc)

class MutualsOrchestratorService:
    def __init__(self,
                 database_url: Optional[str] = None,
                 redis_url: str = "redis://localhost:6379/0",
                 apify_api_token: Optional[str] = None,
                 phantombuster_api_key: Optional[str] = None):

        resolved_db = (
            database_url
            or getattr(settings, "DATABASE_URL", None)
            or os.getenv("DATABASE_URL")
        )
        if resolved_db and resolved_db.startswith("sqlite"):
            raise RuntimeError(
                "Mutuals orchestrator requires a PostgreSQL DATABASE_URL; received sqlite DSN."
            )
        if not resolved_db:
            resolved_db = resolve_required_dsn(
                "DATABASE_URL",
                "TEST_DATABASE_URL",
                default=DEFAULT_TEST_DSN,
            )

        self.database_url = resolved_db

        resolved_redis = redis_url or os.getenv("REDIS_URL")
        self.redis = Redis.from_url(resolved_redis) if resolved_redis else None

        # API Configuration
        self.apify_api_token = (apify_api_token or settings.APIFY_TOKEN or os.getenv("APIFY_TOKEN"))
        self.phantombuster_api_key = (
            phantombuster_api_key
            or settings.PHANTOMBUSTER_API_KEY
            or os.getenv("PHANTOMBUSTER_API_KEY")
        )

        # Apify Configuration
        self.apify_base_url = "https://api.apify.com/v2"
        self.linkedin_mutuals_actor_id = "6781579182695196"  # LinkedIn Mutual Connections actor

        # PhantomBuster Configuration
        self.phantombuster_base_url = "https://api.phantombuster.com/api/v2"

        # Rate limiting and concurrency
        self.max_concurrent_sessions = 3  # Per organization
        self.delay_between_requests = (15, 25)  # Random delay in seconds
        self.session_cooldown_minutes = 30  # Cooldown after rate limit

        # Retry configuration
        self.max_retries = 3
        self.retry_delay_base = 60  # Base delay for exponential backoff

        # Session validation
        self.session_validation_interval = 6 * 3600  # 6 hours

        # Approval + metrics cache
        self._phantombuster_approvals: Dict[str, Optional[str]] = {}

    async def discover_mutuals_batch(
        self,
        tenant_id: str,
        integration_set_id: str,
        prospect_ids: List[str],
        phantombuster_approval_id: Optional[str] = None,
    ) -> str:
        """
        Discover mutual connections for a batch of prospects
        Returns job_id for tracking progress
        """
        job_id = f"mutuals_{secrets.token_urlsafe(16)}"

        try:
            # Get active team members for this organization
            team_member_ids = await self._get_active_team_members(tenant_id)
            if not team_member_ids:
                raise ValueError("No active team members found with valid LinkedIn sessions")

            # Create discovery job
            discovery_job = MutualsDiscoveryJob(
                job_id=job_id,
                tenant_id=tenant_id,
                integration_set_id=integration_set_id,
                prospect_ids=prospect_ids,
                team_member_ids=team_member_ids,
                status=MutualsJobStatus.PENDING,
                total_prospects=len(prospect_ids)
            )

            self._register_phantombuster_approval(discovery_job.job_id, phantombuster_approval_id)

            # Store job in database
            await self._store_discovery_job(discovery_job)

            # Start async processing
            asyncio.create_task(self._process_discovery_batch(discovery_job))

            await audit_logger.log_event(
                tenant_id=tenant_id,
                event_type=AuditEventType.EXTERNAL_API_CALL,
                action="mutuals_discovery_batch_started",
                resource_type="prospect",
                details={
                    "job_id": job_id,
                    "prospect_count": len(prospect_ids),
                    "team_member_count": len(team_member_ids)
                },
                severity=AuditSeverity.MEDIUM
            )

            # Log job start for real-time communication
            if agent_logging_available:
                await agent_logger.log_event(
                    event_type=AgentEventType.TASK_START,
                    agent_id="mutuals_orchestrator",
                    message=f"Starting LinkedIn mutual connections discovery for {len(prospect_ids)} prospects",
                    tenant_id=tenant_id,
                    workflow_id=integration_set_id,
                    metadata={
                        "job_id": job_id,
                        "prospect_count": len(prospect_ids),
                        "team_member_count": len(team_member_ids),
                        "estimated_apify_cost": len(prospect_ids) * 0.05,  # Estimated $0.05 per prospect
                        "provider": "apify"
                    }
                )

            # Send job start message to Communication Hub
            if communication_client_available:
                try:
                    client = await get_communication_client()
                    # Get user_id for the message (would need to be passed in or derived from tenant)
                    # For now, we'll create the conversation but may need user context
                    await client.send_progress_update(
                        conversation_id=f"mutuals_discovery_{job_id}",
                        recipient_id="1",  # Default user - this should be parameterized
                        agent_name="LinkedIn Connections",
                        progress_message=f"🤝 Starting mutual connections discovery for {len(prospect_ids)} prospects using {len(team_member_ids)} team members",
                        metadata={
                            "job_id": job_id,
                            "prospect_count": len(prospect_ids),
                            "team_member_count": len(team_member_ids),
                            "estimated_cost": len(prospect_ids) * 0.05,
                            "provider": "Apify LinkedIn API",
                            "stage": "starting"
                        },
                        workflow_id=integration_set_id
                    )
                except Exception as e:
                    logger.warning(f"Failed to send mutuals discovery start message to Communication Hub: {e}")

            logger.info(f"Started mutuals discovery job {job_id} for {len(prospect_ids)} prospects")
            return job_id

        except Exception as e:
            logger.error(f"Failed to start mutuals discovery batch: {e}")
            await audit_logger.log_event(
                tenant_id=tenant_id,
                event_type=AuditEventType.SYSTEM_ERROR,
                action="mutuals_discovery_batch_failed",
                resource_type="prospect",
                details={"error": str(e), "prospect_ids": prospect_ids},
                severity=AuditSeverity.HIGH
            )
            raise

    async def _process_discovery_batch(self, discovery_job: MutualsDiscoveryJob):
        """Process mutual connections discovery for a batch of prospects"""

        try:
            # Update job status
            discovery_job.status = MutualsJobStatus.IN_PROGRESS
            await self._update_discovery_job(discovery_job)

            # Check concurrent session limit
            concurrent_semaphore = asyncio.Semaphore(self.max_concurrent_sessions)

            # Process each prospect
            for prospect_id in discovery_job.prospect_ids:
                try:
                    await self._process_single_prospect_mutuals(
                        concurrent_semaphore, discovery_job, prospect_id
                    )

                    discovery_job.completed_prospects += 1

                    # Add random delay between prospects
                    delay = random.randint(*self.delay_between_requests)
                    await asyncio.sleep(delay)

                except Exception as e:
                    discovery_job.failed_prospects += 1
                    discovery_job.error_details.append({
                        "prospect_id": prospect_id,
                        "error": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    logger.error(f"Failed to process prospect {prospect_id}: {e}")

                # Update progress
                await self._update_discovery_job(discovery_job)

            # Determine final status
            if discovery_job.failed_prospects == 0:
                discovery_job.status = MutualsJobStatus.COMPLETED
            elif discovery_job.completed_prospects == 0:
                discovery_job.status = MutualsJobStatus.FAILED
            else:
                discovery_job.status = MutualsJobStatus.PARTIALLY_COMPLETED

            discovery_job.updated_at = datetime.now(timezone.utc)
            await self._update_discovery_job(discovery_job)

            # Log completion
            await audit_logger.log_event(
                tenant_id=discovery_job.tenant_id,
                event_type=AuditEventType.EXTERNAL_API_CALL,
                action="mutuals_discovery_batch_completed",
                resource_type="prospect",
                details={
                    "job_id": discovery_job.job_id,
                    "total_prospects": discovery_job.total_prospects,
                    "completed": discovery_job.completed_prospects,
                    "failed": discovery_job.failed_prospects,
                    "total_mutuals": discovery_job.total_mutuals_found,
                    "status": discovery_job.status.value
                },
                severity=AuditSeverity.MEDIUM if discovery_job.failed_prospects > 0 else AuditSeverity.LOW
            )

            # Log completion and final costs for real-time communication
            if agent_logging_available:
                total_cost = discovery_job.completed_prospects * 0.05  # $0.05 per successful prospect

                await agent_logger.log_task_complete(
                    agent_id="mutuals_orchestrator",
                    task_name="LinkedIn Mutual Connections Discovery",
                    result=f"Found {discovery_job.total_mutuals_found} mutual connections across {discovery_job.completed_prospects} prospects",
                    tenant_id=discovery_job.tenant_id,
                    workflow_id=discovery_job.integration_set_id,
                    metadata={
                        "job_id": discovery_job.job_id,
                        "prospects_processed": discovery_job.completed_prospects,
                        "total_mutuals_found": discovery_job.total_mutuals_found,
                        "success_rate": (discovery_job.completed_prospects / discovery_job.total_prospects) * 100,
                        "final_status": discovery_job.status.value
                    }
                )

                # Log final cost transparency
                await agent_logger.log_cost_incurred(
                    agent_id="mutuals_orchestrator",
                    service_name="Apify LinkedIn Mutual Connections",
                    cost_amount=total_cost,
                    cost_currency="USD",
                    cost_details={
                        "prospects_processed": discovery_job.completed_prospects,
                        "cost_per_prospect": 0.05,
                        "provider": "apify",
                        "job_id": discovery_job.job_id,
                        "date": datetime.now(timezone.utc).isoformat()
                    },
                    tenant_id=discovery_job.tenant_id,
                    workflow_id=discovery_job.integration_set_id
                )

            # Send completion message to Communication Hub
            if communication_client_available:
                try:
                    client = await get_communication_client()
                    success_rate = (discovery_job.completed_prospects / discovery_job.total_prospects * 100) if discovery_job.total_prospects > 0 else 0

                    if discovery_job.total_mutuals_found > 0:
                        await client.send_progress_update(
                            conversation_id=f"mutuals_discovery_{discovery_job.job_id}",
                            recipient_id="1",  # Default user - this should be parameterized
                            agent_name="LinkedIn Connections",
                            progress_message=f"✅ Discovery completed: Found {discovery_job.total_mutuals_found} mutual connections across {discovery_job.completed_prospects}/{discovery_job.total_prospects} prospects",
                            metadata={
                                "job_id": discovery_job.job_id,
                                "total_mutuals_found": discovery_job.total_mutuals_found,
                                "prospects_processed": discovery_job.completed_prospects,
                                "total_prospects": discovery_job.total_prospects,
                                "success_rate": f"{success_rate:.1f}%",
                                "cost_incurred": discovery_job.completed_prospects * 0.05,
                                "stage": "completed"
                            },
                            workflow_id=discovery_job.integration_set_id
                        )
                    else:
                        await client.send_progress_update(
                            conversation_id=f"mutuals_discovery_{discovery_job.job_id}",
                            recipient_id="1",  # Default user - this should be parameterized
                            agent_name="LinkedIn Connections",
                            progress_message=f"⚠️ Discovery completed with no mutual connections found across {discovery_job.completed_prospects}/{discovery_job.total_prospects} prospects",
                            metadata={
                                "job_id": discovery_job.job_id,
                                "total_mutuals_found": 0,
                                "prospects_processed": discovery_job.completed_prospects,
                                "total_prospects": discovery_job.total_prospects,
                                "success_rate": f"{success_rate:.1f}%",
                                "issue": "No mutual connections discovered - consider expanding network or checking team member connections",
                                "stage": "completed"
                            },
                            workflow_id=discovery_job.integration_set_id
                        )
                except Exception as e:
                    logger.warning(f"Failed to send mutuals discovery completion message to Communication Hub: {e}")

            logger.info(f"Completed mutuals discovery job {discovery_job.job_id}: "
                       f"{discovery_job.completed_prospects}/{discovery_job.total_prospects} successful, "
                       f"{discovery_job.total_mutuals_found} mutuals found")

        except Exception as e:
            discovery_job.status = MutualsJobStatus.FAILED
            discovery_job.updated_at = datetime.now(timezone.utc)
            await self._update_discovery_job(discovery_job)

            logger.error(f"Mutuals discovery batch job {discovery_job.job_id} failed: {e}")
            raise
        finally:
            self._clear_phantombuster_approval(discovery_job.job_id)

    async def _process_single_prospect_mutuals(self,
                                             semaphore: asyncio.Semaphore,
                                             discovery_job: MutualsDiscoveryJob,
                                             prospect_id: str):
        """Process mutual connections discovery for a single prospect"""

        async with semaphore:
            # Get prospect data
            prospect = await self._get_prospect_data(discovery_job.tenant_id, prospect_id)
            if not prospect or not prospect.get('linkedin_url'):
                raise ValueError(f"Prospect {prospect_id} missing LinkedIn URL")

            linkedin_url = prospect['linkedin_url']
            mutuals_found = []

            # Try each team member for mutual connections
            for team_member_id in discovery_job.team_member_ids:
                try:
                    # Get valid session for team member
                    lock_owner = f"mutuals:{discovery_job.job_id}:{team_member_id}"
                    session_info = await self._get_valid_session(
                        discovery_job.tenant_id,
                        team_member_id,
                        lock_owner=lock_owner,
                    )

                    if not session_info:
                        logger.warning(f"No valid session for team member {team_member_id}")
                        continue

                    session_data, jar_id, jar_user_id = session_info
                    cookie_used = False

                    async def apify_runner():
                        last_error: Optional[Exception] = None
                        for attempt in range(1, self.max_retries + 1):
                            try:
                                result = await self._discover_mutuals_apify(
                                    linkedin_url, session_data, team_member_id
                                )
                                if result:
                                    return result
                            except Exception as attempt_error:
                                last_error = attempt_error
                                logger.warning(
                                    "Apify mutual discovery attempt %s failed for prospect %s / team member %s: %s",
                                    attempt,
                                    prospect_id,
                                    team_member_id,
                                    attempt_error,
                                )
                                await asyncio.sleep(min(self.retry_delay_base, 30) * attempt)
                        if last_error:
                            raise last_error
                        return []

                    async def phantom_runner():
                        return await self._discover_mutuals_phantombuster(
                            discovery_job.tenant_id,
                            prospect,
                            team_member_id,
                        )

                    mutual_connections, provider_used = await self._run_mutual_provider_pipeline(
                        apify_runner=apify_runner,
                        phantom_runner=phantom_runner,
                        discovery_job=discovery_job,
                        context={
                            "prospect_id": prospect_id,
                            "team_member_id": team_member_id,
                            "linkedin_url": linkedin_url,
                        },
                    )

                    if mutual_connections:
                        mutuals_found.extend(mutual_connections)

                        await self._store_mutual_connections(
                            discovery_job.tenant_id,
                            prospect_id,
                            team_member_id,
                            mutual_connections
                        )

                        if provider_used == "apify":
                            with portal_get_conn() as conn:
                                await increment_cookie_usage(
                                    conn,
                                    organization_id=int(discovery_job.tenant_id),
                                    jar_id=jar_id,
                                    lock_owner=lock_owner,
                                )
                            cookie_used = True

                    self._record_provider_usage(provider_used or "unknown", discovery_job.tenant_id)

                except Exception as e:
                    logger.error(
                        f"Failed to discover mutuals for prospect {prospect_id} "
                        f"with team member {team_member_id}: {e}"
                    )
                    with portal_get_conn() as conn:
                        await mark_cookie_status(
                            conn,
                            organization_id=int(discovery_job.tenant_id),
                            user_id=jar_user_id,
                            jar_id=jar_id,
                            status="invalid",
                            status_detail="discovery_failure",
                            error_message=str(e),
                        )
                        release_cookie_lock(conn, jar_id, lock_owner)
                    continue
                finally:
                    if not cookie_used:
                        with portal_get_conn() as conn:
                            release_cookie_lock(conn, jar_id, lock_owner)

            discovery_job.total_mutuals_found += len(mutuals_found)

            # Store result summary
            discovery_job.results.append({
                "prospect_id": prospect_id,
                "linkedin_url": linkedin_url,
                "mutuals_count": len(mutuals_found),
                "team_members_processed": len(discovery_job.team_member_ids),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            logger.info(f"Found {len(mutuals_found)} mutual connections for prospect {prospect_id}")

    async def _run_mutual_provider_pipeline(
        self,
        *,
        apify_runner,
        phantom_runner,
        discovery_job: MutualsDiscoveryJob,
        context: Dict[str, Any],
    ) -> Tuple[List[MutualConnection], Optional[str]]:
        """Execute Apify first and optionally PhantomBuster with approval."""
        mutual_connections: List[MutualConnection] = []
        provider_used: Optional[str] = None
        apify_error: Optional[Exception] = None

        if self.apify_api_token:
            try:
                mutual_connections = await apify_runner()
                if mutual_connections:
                    provider_used = "apify"
                    return mutual_connections, provider_used
            except Exception as attempt_error:
                apify_error = attempt_error

        if self.phantombuster_api_key:
            approval_id = self._ensure_phantombuster_approval(discovery_job.job_id, discovery_job.tenant_id)
            await self._record_phantombuster_event("requested", discovery_job, context, approval_id)
            try:
                phantom_results = await phantom_runner()
            except Exception as fallback_error:
                await self._record_phantombuster_event(
                    "error", discovery_job, {**context, "error": str(fallback_error)}, approval_id
                )
                raise

            if phantom_results:
                await audit_logger.log_event(
                    tenant_id=discovery_job.tenant_id,
                    event_type=AuditEventType.EXTERNAL_API_CALL,
                    action="run_phantombuster_enrichment",
                    resource_type="prospect",
                    details={
                        "job_id": discovery_job.job_id,
                        "approval_id": approval_id,
                        "prospect_id": context.get("prospect_id"),
                        "team_member_id": context.get("team_member_id"),
                        "provider": "phantombuster",
                    },
                    severity=AuditSeverity.MEDIUM,
                )
                await self._record_phantombuster_event("success", discovery_job, context, approval_id)
                return phantom_results, "phantombuster"

            await self._record_phantombuster_event("empty", discovery_job, context, approval_id)

        if apify_error:
            raise apify_error

        return [], provider_used

    def _register_phantombuster_approval(self, job_id: str, approval_id: Optional[str]) -> None:
        self._phantombuster_approvals[job_id] = approval_id

    def _clear_phantombuster_approval(self, job_id: str) -> None:
        self._phantombuster_approvals.pop(job_id, None)

    def _ensure_phantombuster_approval(self, job_id: str, tenant_id: str) -> str:
        approval_id = self._phantombuster_approvals.get(job_id)
        if not approval_id:
            raise PermissionError(
                f"PhantomBuster enrichment requires recorded approval for job {job_id} (tenant {tenant_id})."
            )
        return approval_id

    async def _record_phantombuster_event(
        self,
        outcome: str,
        discovery_job: MutualsDiscoveryJob,
        context: Dict[str, Any],
        approval_id: Optional[str] = None,
    ) -> None:
        metadata = {
            "job_id": discovery_job.job_id,
            "tenant_id": discovery_job.tenant_id,
            "prospect_id": context.get("prospect_id"),
            "team_member_id": context.get("team_member_id"),
            "approval_id": approval_id,
        }
        logger.info("run_phantombuster_enrichment.%s %s", outcome, metadata)
        if self.redis:
            try:
                key = f"mutuals:phantombuster:{outcome}"
                self.redis.incr(key, 1)
                self.redis.expire(key, 24 * 3600)
            except Exception as exc:  # pragma: no cover - observability only
                logger.debug("Unable to record PhantomBuster metric: %s", exc)
        return

    async def _discover_mutuals_apify(self,
                                    linkedin_url: str,
                                    session_data: Dict,
                                    team_member_id: str) -> List[MutualConnection]:
        """Discover mutual connections using Apify LinkedIn actor"""

        try:
            # Prepare Apify actor input
            actor_input = {
                "profileUrl": linkedin_url,
                "maxConnections": 500,
                "includeProfileDetails": True,
                "cookies": [
                    {
                        "name": "li_at",
                        "value": session_data.get("li_at", ""),
                        "domain": ".linkedin.com"
                    }
                ]
            }

            if session_data.get("jsessionid"):
                actor_input["cookies"].append({
                    "name": "JSESSIONID",
                    "value": session_data["jsessionid"],
                    "domain": ".linkedin.com"
                })

            # Start Apify actor run
            run_result = await self._start_apify_actor_run(actor_input)
            run_id = run_result.get("id")

            if not run_id:
                raise ValueError("Failed to start Apify actor run")

            # Log individual Apify run cost
            if agent_logging_available:
                await agent_logger.log_cost_incurred(
                    agent_id="mutuals_orchestrator",
                    service_name="Apify LinkedIn Mutual Connections (Single Run)",
                    cost_amount=0.05,  # $0.05 per prospect
                    cost_currency="USD",
                    cost_details={
                        "apify_run_id": run_id,
                        "prospect_linkedin_url": linkedin_url,
                        "team_member_id": team_member_id,
                        "provider": "apify",
                        "actor_id": self.linkedin_mutuals_actor_id
                    },
                    tenant_id="",  # Will be filled by calling context
                    workflow_id=""  # Will be filled by calling context
                )

            # Wait for completion and get results
            run_status = await self._wait_for_apify_completion(run_id)

            if run_status.get("status") == "SUCCEEDED":
                # Get dataset items (mutual connections)
                connections = await self._get_apify_dataset_items(run_id)
                return self._parse_apify_connections(connections)
            else:
                error_msg = run_status.get("statusMessage", "Unknown error")
                raise ValueError(f"Apify run failed: {error_msg}")

        except Exception as e:
            logger.error(f"Apify mutuals discovery failed for {linkedin_url}: {e}")

            # Check for rate limiting or session issues
            if "rate" in str(e).lower() or "429" in str(e):
                await self._handle_rate_limit(team_member_id)
            elif "session" in str(e).lower() or "401" in str(e):
                await self._mark_session_invalid(team_member_id)

            raise

    def _sanitize_url(self, url: str) -> Optional[str]:
        if not url:
            return None

        candidate = url.strip()
        if not candidate:
            return None

        try:
            parsed = urlparse(candidate)
        except ValueError:
            return None

        if parsed.scheme.lower() not in {"http", "https"}:
            return None

        host = (parsed.hostname or "").lower()
        if not host:
            return None

        if host.startswith("localhost") or host.startswith("127.") or host.startswith("169.254."):
            return None

        if host in {"localhost"}:
            return None

        return parsed.geturl()

    def _record_provider_usage(self, provider: str, tenant_id: str) -> None:
        """Record provider usage metrics in Redis for rate tracking."""

        if not self.redis:
            return

        try:
            key = f"mutuals:usage:{provider}:{tenant_id}"
            self.redis.incr(key, 1)
            self.redis.expire(key, 86400)
        except Exception as exc:
            logger.debug("Failed to record provider usage: %s", exc)

    async def _discover_mutuals_phantombuster(
        self,
        tenant_id: str,
        prospect: Dict[str, Any],
        team_member_id: str,
    ) -> List[MutualConnection]:
        """Discover mutual connections using PhantomBuster search as a fallback."""

        if not self.phantombuster_api_key:
            return []

        try:
            from src.services.phantombuster import PhantomBusterService
        except ImportError:
            logger.warning("PhantomBuster service not available in runtime environment")
            return []

        prospect_name = (prospect.get("full_name") or prospect.get("name") or "").strip()
        prospect_company = (prospect.get("company") or "").strip() or None

        if not prospect_name:
            return []

        service = PhantomBusterService(api_key=self.phantombuster_api_key)

        try:
            search_results = await service.search_prospect_network(prospect_name, prospect_company)
        except Exception as exc:
            logger.error(
                "PhantomBuster search failed for prospect %s (team member %s): %s",
                prospect_name,
                team_member_id,
                exc,
            )
            return []

        mutuals: List[MutualConnection] = []

        for item in search_results or []:
            url = (
                item.get("profileUrl")
                or item.get("linkedin_url")
                or item.get("linkedinUrl")
                or item.get("url")
                or ""
            )
            sanitized_url = self._sanitize_url(url)
            full_name = (item.get("fullName") or item.get("name") or "").strip()

            if not sanitized_url or not full_name:
                continue

            headline = item.get("headline") or item.get("jobTitle") or item.get("title")
            company = item.get("company") or item.get("companyName") or prospect_company
            current_title = item.get("title") or item.get("jobTitle")
            location = item.get("location")
            profile_image = item.get("profileImageUrl") or item.get("pictureUrl")

            try:
                connection_degree = int(item.get("connectionDegree") or 2)
            except (TypeError, ValueError):
                connection_degree = 2

            try:
                shared_count = int(item.get("mutualConnectionsCount") or 0)
            except (TypeError, ValueError):
                shared_count = 0

            mutuals.append(
                MutualConnection(
                    linkedin_url=sanitized_url,
                    full_name=full_name,
                    headline=headline,
                    current_company=company,
                    current_title=current_title,
                    location=location,
                    profile_picture_url=profile_image,
                    connection_degree=connection_degree,
                    shared_connections_count=shared_count,
                )
            )

        if mutuals:
            logger.info(
                "PhantomBuster fallback discovered %s potential connectors for prospect %s",
                len(mutuals),
                prospect_name,
            )

        return mutuals

    @backoff.on_exception(backoff.expo, httpx.HTTPError, max_tries=3)
    async def _start_apify_actor_run(self, actor_input: Dict) -> Dict:
        """Start an Apify actor run"""

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.apify_base_url}/acts/{self.linkedin_mutuals_actor_id}/runs",
                headers={
                    "Authorization": f"Bearer {self.apify_api_token}",
                    "Content-Type": "application/json"
                },
                json=actor_input
            )

            if response.status_code == 201:
                return response.json()["data"]
            elif response.status_code == 429:
                raise ValueError("Apify rate limit exceeded")
            else:
                raise ValueError(f"Apify API error {response.status_code}: {response.text}")

    async def _wait_for_apify_completion(self, run_id: str, max_wait_minutes: int = 15) -> Dict:
        """Wait for Apify actor run to complete"""

        start_time = datetime.now(timezone.utc)
        max_wait_time = start_time + timedelta(minutes=max_wait_minutes)

        while datetime.now(timezone.utc) < max_wait_time:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(
                        f"{self.apify_base_url}/actor-runs/{run_id}",
                        headers={"Authorization": f"Bearer {self.apify_api_token}"}
                    )

                    if response.status_code == 200:
                        run_data = response.json()["data"]
                        status = run_data.get("status")

                        if status in ["SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"]:
                            return run_data

                        # Continue waiting for running/ready states
                        await asyncio.sleep(30)  # Check every 30 seconds
                    else:
                        raise ValueError(f"Failed to get run status: {response.status_code}")

            except Exception as e:
                logger.warning(f"Error checking Apify run status: {e}")
                await asyncio.sleep(30)

        raise TimeoutError(f"Apify run {run_id} timed out after {max_wait_minutes} minutes")

    async def _get_apify_dataset_items(self, run_id: str) -> List[Dict]:
        """Get dataset items from completed Apify run"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    f"{self.apify_base_url}/actor-runs/{run_id}/dataset/items",
                    headers={"Authorization": f"Bearer {self.apify_api_token}"}
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    raise ValueError(f"Failed to get dataset items: {response.status_code}")

        except Exception as e:
            logger.error(f"Error getting Apify dataset items: {e}")
            return []

    def _parse_apify_connections(self, connections_data: List[Dict]) -> List[MutualConnection]:
        """Parse Apify response into MutualConnection objects"""

        mutual_connections = []

        for conn_data in connections_data:
            try:
                # Extract connection information
                linkedin_url = conn_data.get("profileUrl", "")
                full_name = conn_data.get("fullName", "")

                if not linkedin_url or not full_name:
                    continue

                mutual_connection = MutualConnection(
                    linkedin_url=linkedin_url,
                    full_name=full_name,
                    headline=conn_data.get("headline"),
                    current_company=conn_data.get("company"),
                    current_title=conn_data.get("title"),
                    location=conn_data.get("location"),
                    profile_picture_url=conn_data.get("profilePictureUrl"),
                    connection_degree=conn_data.get("connectionDegree", 2),
                    shared_connections_count=conn_data.get("mutualConnectionsCount", 0)
                )

                mutual_connections.append(mutual_connection)

            except Exception as e:
                logger.warning(f"Error parsing connection data: {e}")
                continue

        return mutual_connections

    async def _get_valid_session(
        self,
        tenant_id: str,
        team_member_id: str,
        *,
        lock_owner: str,
    ) -> Optional[Tuple[Dict[str, Any], int, int]]:
        """Get a valid LinkedIn session for team member and reserve the cookie jar."""

        try:
            organization_id = int(tenant_id)
            member_id = int(team_member_id)

            with portal_get_conn() as conn:
                member_rows = portal_query(
                    conn,
                    "SELECT user_id FROM team_members WHERE id = ?",
                    (member_id,),
                )
                if not member_rows:
                    return None

                user_id = int(member_rows[0]["user_id"])
                jar_rows = portal_query(
                    conn,
                    """
                    SELECT id, status, expires_at, vault_item_id
                    FROM cookie_jars
                    WHERE organization_id = ? AND user_id = ?
                    ORDER BY CASE status WHEN 'valid' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                             COALESCE(expires_at, '9999-12-31') ASC
                    """,
                    (organization_id, user_id),
                )

                for jar in jar_rows:
                    jar_id = int(jar["id"])
                    status = jar.get("status")
                    expires_at_raw = jar.get("expires_at")
                    expires_at = None
                    if expires_at_raw:
                        try:
                            expires_at = datetime.fromisoformat(str(expires_at_raw))
                        except ValueError:
                            expires_at = None

                    if status not in {"valid", "pending"}:
                        continue

                    if expires_at and expires_at < datetime.now(timezone.utc):
                        await mark_cookie_status(
                            conn,
                            organization_id=organization_id,
                            user_id=user_id,
                            jar_id=jar_id,
                            status="expired",
                            status_detail="ttl_expired",
                        )
                        continue

                    if not acquire_cookie_lock(conn, jar_id, lock_owner):
                        continue

                    session_data: Optional[Dict[str, Any]] = None
                    vault_item_id = jar.get("vault_item_id")

                    if vault_item_id:
                        try:
                            vault_item = await cookie_vault.retrieve_vault_item(
                                vault_item_id,
                                tenant_id=str(organization_id),
                                user_id=str(user_id),
                            )
                            payload_data = vault_item.get("data") if vault_item else None
                            if isinstance(payload_data, dict):
                                session_data = payload_data
                        except Exception as vault_error:
                            logger.warning(
                                "Failed to load cookie from vault for jar %s: %s",
                                jar_id,
                                vault_error,
                            )

                    if session_data is None:
                        payload = await load_cookie_payload(conn, jar_id)
                        session_data = payload.get("payload")

                    if not session_data or not session_data.get("li_at"):
                        await mark_cookie_status(
                            conn,
                            organization_id=organization_id,
                            user_id=user_id,
                            jar_id=jar_id,
                            status="invalid",
                            status_detail="missing_payload",
                            error_message="No LinkedIn cookie payload available",
                        )
                        release_cookie_lock(conn, jar_id, lock_owner)
                        continue

                    return session_data, jar_id, user_id

            return None

        except Exception as e:
            logger.error(f"Error getting valid session for team member {team_member_id}: {e}")
            return None

    async def _is_session_valid(self, session_data: Dict) -> bool:
        """Validate LinkedIn session by making a test request"""

        try:
            cookies = {
                "li_at": session_data.get("li_at", "")
            }

            if session_data.get("jsessionid"):
                cookies["JSESSIONID"] = session_data["jsessionid"]

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://www.linkedin.com/feed/",
                    cookies=cookies,
                    headers={
                        "User-Agent": session_data.get("user_agent",
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
                    }
                )

                # Check if we're redirected to login (session expired)
                if "login" in response.url.path or response.status_code == 401:
                    return False

                return response.status_code == 200

        except Exception as e:
            logger.warning(f"Session validation failed: {e}")
            return False

    async def _handle_rate_limit(self, team_member_id: str):
        """Handle rate limiting by marking session as temporarily unavailable"""

        try:
            # Store rate limit timestamp in Redis
            if self.redis:
                rate_limit_key = f"rate_limit:{team_member_id}"
                rate_limit_until = datetime.now(timezone.utc) + timedelta(minutes=self.session_cooldown_minutes)
                self.redis.setex(rate_limit_key, self.session_cooldown_minutes * 60,
                               rate_limit_until.isoformat())

            logger.warning(f"Rate limit applied to team member {team_member_id} "
                         f"for {self.session_cooldown_minutes} minutes")

        except Exception as e:
            logger.error(f"Error handling rate limit: {e}")

    async def _mark_session_invalid(self, team_member_id: str):
        """Mark session as invalid for rotation"""

        try:
            # This would trigger cookie rotation in production
            logger.warning(f"Session marked as invalid for team member {team_member_id}")

            # In production, this would:
            # 1. Mark cookie jar as expired in vault
            # 2. Trigger notification for new cookie upload
            # 3. Temporarily disable team member from discovery

        except Exception as e:
            logger.error(f"Error marking session invalid: {e}")

    # Database operations
    def _require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError(
                "MutualsOrchestratorService requires DATABASE_URL to be configured with a PostgreSQL DSN."
            )
        return self.database_url

    async def _get_active_team_members(self, tenant_id: str) -> List[str]:
        """Get list of active team members with valid LinkedIn sessions"""

        async with asyncpg.connect(self._require_database_url()) as conn:
            rows = await conn.fetch("""
                SELECT id FROM team_members
                WHERE organization_id = $1 AND is_active = true
                AND network_scan_status = 'completed'
            """, tenant_id)

            return [str(row['id']) for row in rows]

    async def _get_prospect_data(self, tenant_id: str, prospect_id: str) -> Optional[Dict]:
        """Get prospect data from database"""

        async with asyncpg.connect(self._require_database_url()) as conn:
            row = await conn.fetchrow("""
                SELECT id, company, full_name, linkedin_url, title
                FROM prospects
                WHERE id = $1 AND organization_id = $2
            """, prospect_id, tenant_id)

            return dict(row) if row else None

    async def _ensure_team_member_connector(
        self,
        conn: asyncpg.Connection,
        organization_id: int,
        team_member_id: int,
        connector_id: int,
        source: str,
    ) -> Optional[int]:
        """Ensure a team-member ↔ connector link exists and return its id."""

        return await conn.fetchval(
            """
            INSERT INTO team_member_connectors (
                organization_id,
                team_member_id,
                connector_id,
                relationship_type,
                source,
                is_primary,
                created_at,
                updated_at,
                last_seen_at
            ) VALUES ($1, $2, $3, 'mutual_connection', $4, TRUE, NOW(), NOW(), NOW())
            ON CONFLICT (organization_id, team_member_id, connector_id)
            DO UPDATE SET
                updated_at = NOW(),
                last_seen_at = NOW(),
                source = CASE
                    WHEN team_member_connectors.source IN ('unknown', 'legacy_backfill', 'manual_seed')
                        THEN EXCLUDED.source
                    ELSE team_member_connectors.source
                END
            RETURNING id
            """,
            organization_id,
            team_member_id,
            connector_id,
            source,
        )

    async def _store_mutual_connections(self,
                                      tenant_id: str,
                                      prospect_id: str,
                                      team_member_id: str,
                                      mutual_connections: List[MutualConnection]):
        """Store mutual connections in database"""

        async with asyncpg.connect(self._require_database_url()) as conn:
            try:
                organization_id_int = int(tenant_id)
            except (TypeError, ValueError):
                organization_id_int = tenant_id

            for mutual_conn in mutual_connections:
                try:
                    name_parts = (mutual_conn.full_name or "").strip().split()
                    first_name = name_parts[0] if name_parts else None
                    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else None
                    shared_connections = mutual_conn.shared_connections_count or 0
                    try:
                        team_member_numeric = int(team_member_id) if team_member_id is not None else None
                    except (TypeError, ValueError):
                        team_member_numeric = team_member_id

                    connector_id = await conn.fetchval(
                        """
                        INSERT INTO connectors (
                            organization_id,
                            tenant_id,
                            full_name,
                            first_name,
                            last_name,
                            linkedin_url,
                            headline,
                            company,
                            current_company,
                            current_title,
                            location,
                            profile_picture_url,
                            shared_connections_count,
                            created_at,
                            updated_at
                        ) VALUES (
                            $1, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW(), NOW()
                        )
                        ON CONFLICT (organization_id, linkedin_url) DO UPDATE SET
                            full_name = EXCLUDED.full_name,
                            first_name = COALESCE(EXCLUDED.first_name, connectors.first_name),
                            last_name = COALESCE(EXCLUDED.last_name, connectors.last_name),
                            headline = EXCLUDED.headline,
                            company = COALESCE(EXCLUDED.company, connectors.company),
                            current_company = EXCLUDED.current_company,
                            current_title = EXCLUDED.current_title,
                            location = EXCLUDED.location,
                            profile_picture_url = COALESCE(EXCLUDED.profile_picture_url, connectors.profile_picture_url),
                            shared_connections_count = GREATEST(connectors.shared_connections_count, EXCLUDED.shared_connections_count),
                            updated_at = NOW(),
                            last_verified_at = NOW()
                        RETURNING id
                        """,
                        organization_id_int,
                        mutual_conn.full_name,
                        first_name,
                        last_name,
                        mutual_conn.linkedin_url,
                        mutual_conn.headline,
                        mutual_conn.current_company,
                        mutual_conn.current_company,
                        mutual_conn.current_title,
                        mutual_conn.location,
                        mutual_conn.profile_picture_url,
                        shared_connections,
                    )

                    team_member_connector_id = None
                    if team_member_numeric is not None:
                        team_member_connector_id = await self._ensure_team_member_connector(
                            conn,
                            organization_id_int,
                            team_member_numeric,
                            connector_id,
                            "mutuals_discovery",
                        )

                    confidence_score = min(1.0, 0.35 + (shared_connections * 0.05))

                    await conn.execute(
                        """
                        INSERT INTO prospect_connectors (
                            organization_id,
                            tenant_id,
                            prospect_id,
                            connector_id,
                            team_member_id,
                            team_member_connector_id,
                            connection_degree,
                            shared_connections_count,
                            confidence_score,
                            status,
                            source,
                            algorithm_version,
                            last_seen_at,
                            created_at,
                            updated_at
                        ) VALUES (
                            $1, $1, $2, $3, $4, $5, $6, $7, $8,
                            'discovered', 'mutuals_discovery', 'mutuals_v2', NOW(), NOW(), NOW()
                        )
                        ON CONFLICT (organization_id, prospect_id, connector_id, team_member_id)
                        DO UPDATE SET
                            shared_connections_count = GREATEST(
                                prospect_connectors.shared_connections_count,
                                EXCLUDED.shared_connections_count
                            ),
                            connection_degree = COALESCE(EXCLUDED.connection_degree, prospect_connectors.connection_degree),
                            confidence_score = GREATEST(COALESCE(prospect_connectors.confidence_score, 0), EXCLUDED.confidence_score),
                            team_member_connector_id = COALESCE(prospect_connectors.team_member_connector_id, EXCLUDED.team_member_connector_id),
                            last_seen_at = NOW(),
                            updated_at = NOW(),
                            source = CASE
                                WHEN prospect_connectors.source IN ('legacy_backfill', 'unknown') THEN EXCLUDED.source
                                ELSE prospect_connectors.source
                            END
                        """,
                        organization_id_int,
                        prospect_id,
                        connector_id,
                        team_member_numeric,
                        team_member_connector_id,
                        mutual_conn.connection_degree,
                        shared_connections,
                        confidence_score,
                    )

                except Exception as e:
                    logger.error(f"Error storing mutual connection {mutual_conn.linkedin_url}: {e}")
                    continue

    async def _store_discovery_job(self, discovery_job: MutualsDiscoveryJob):
        """Store discovery job in database"""

        async with asyncpg.connect(self._require_database_url()) as conn:
            await conn.execute("""
                INSERT INTO mutuals_discovery_jobs (
                    job_id, tenant_id, integration_set_id, prospect_ids, team_member_ids,
                    status, total_prospects, completed_prospects, failed_prospects,
                    total_mutuals_found, apify_runs, results, error_details,
                    created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            """,
                discovery_job.job_id, discovery_job.tenant_id, discovery_job.integration_set_id,
                discovery_job.prospect_ids, discovery_job.team_member_ids,
                discovery_job.status.value, discovery_job.total_prospects,
                discovery_job.completed_prospects, discovery_job.failed_prospects,
                discovery_job.total_mutuals_found,
                json.dumps(discovery_job.apify_runs, default=str),
                json.dumps(discovery_job.results, default=str),
                json.dumps(discovery_job.error_details, default=str),
                discovery_job.created_at, discovery_job.updated_at
            )

    async def _update_discovery_job(self, discovery_job: MutualsDiscoveryJob):
        """Update discovery job in database"""

        async with asyncpg.connect(self._require_database_url()) as conn:
            await conn.execute("""
                UPDATE mutuals_discovery_jobs SET
                    status = $2,
                    completed_prospects = $3,
                    failed_prospects = $4,
                    total_mutuals_found = $5,
                    apify_runs = $6,
                    results = $7,
                    error_details = $8,
                    updated_at = $9
                WHERE job_id = $1
            """,
                discovery_job.job_id, discovery_job.status.value,
                discovery_job.completed_prospects, discovery_job.failed_prospects,
                discovery_job.total_mutuals_found,
                json.dumps(discovery_job.apify_runs, default=str),
                json.dumps(discovery_job.results, default=str),
                json.dumps(discovery_job.error_details, default=str),
                discovery_job.updated_at
            )

    # Public API methods
    async def get_job_status(self, job_id: str, tenant_id: str) -> Optional[Dict]:
        """Get discovery job status"""

        async with asyncpg.connect(self._require_database_url()) as conn:
            row = await conn.fetchrow("""
                SELECT * FROM mutuals_discovery_jobs
                WHERE job_id = $1 AND tenant_id = $2
            """, job_id, tenant_id)

            if row:
                return {
                    "job_id": row['job_id'],
                    "status": row['status'],
                    "total_prospects": row['total_prospects'],
                    "completed_prospects": row['completed_prospects'],
                    "failed_prospects": row['failed_prospects'],
                    "total_mutuals_found": row['total_mutuals_found'],
                    "created_at": row['created_at'].isoformat(),
                    "updated_at": row['updated_at'].isoformat(),
                    "team_members_count": len(row['team_member_ids']) if row['team_member_ids'] else 0,
                    "progress_percentage": (row['completed_prospects'] + row['failed_prospects']) / row['total_prospects'] * 100
                }

        return None

    async def validate_session_health(self, tenant_id: str) -> Dict[str, Any]:
        """Validate health of LinkedIn sessions for organization"""

        team_member_ids = await self._get_active_team_members(tenant_id)

        session_health = {
            "total_team_members": len(team_member_ids),
            "valid_sessions": 0,
            "expired_sessions": 0,
            "rate_limited_sessions": 0,
            "sessions": []
        }

        for team_member_id in team_member_ids:
            lock_owner = f"mutuals-health:{tenant_id}:{team_member_id}"
            session_info = await self._get_valid_session(tenant_id, team_member_id, lock_owner=lock_owner)

            if session_info:
                session_data, jar_id, jar_user_id = session_info
                is_valid = await self._is_session_valid(session_data)

                # Check rate limit status
                is_rate_limited = False
                if self.redis:
                    rate_limit_key = f"rate_limit:{team_member_id}"
                    if self.redis.get(rate_limit_key):
                        is_rate_limited = True

                if is_rate_limited:
                    status = "rate_limited"
                    session_health["rate_limited_sessions"] += 1
                elif is_valid:
                    status = "valid"
                    session_health["valid_sessions"] += 1
                else:
                    status = "expired"
                    session_health["expired_sessions"] += 1

                session_health["sessions"].append({
                    "team_member_id": team_member_id,
                    "status": status,
                    "last_validated": datetime.now(timezone.utc).isoformat()
                })

                with portal_get_conn() as conn:
                    release_cookie_lock(conn, jar_id, lock_owner)
            else:
                session_health["expired_sessions"] += 1
                session_health["sessions"].append({
                    "team_member_id": team_member_id,
                    "status": "no_session",
                    "last_validated": datetime.now(timezone.utc).isoformat()
                })

        return session_health

    async def estimate_discovery_capacity(self, tenant_id: str, prospect_count: int) -> Dict[str, Any]:
        """Estimate discovery capacity and time for given prospect count"""

        session_health = await self.validate_session_health(tenant_id)
        valid_sessions = session_health["valid_sessions"]

        if valid_sessions == 0:
            return {
                "status": "no_capacity",
                "message": "No valid LinkedIn sessions available",
                "estimated_time_minutes": 0,
                "max_prospects_per_hour": 0
            }

        # Estimate processing capacity
        # Assuming 3-5 minutes per prospect with random delays
        minutes_per_prospect = 4  # Average
        prospects_per_hour_per_session = 60 / minutes_per_prospect  # ~15 per hour per session
        max_prospects_per_hour = int(valid_sessions * prospects_per_hour_per_session)

        estimated_time_minutes = (prospect_count / max_prospects_per_hour) * 60

        return {
            "status": "available",
            "valid_sessions": valid_sessions,
            "max_prospects_per_hour": max_prospects_per_hour,
            "estimated_time_minutes": int(estimated_time_minutes),
            "estimated_completion": (datetime.now(timezone.utc) + timedelta(minutes=estimated_time_minutes)).isoformat()
        }

    async def health_check(self) -> Dict[str, Any]:
        """Health check for mutuals orchestrator service"""

        health_status = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "providers": {},
            "cache": {},
            "database": {}
        }

        # Check Apify API
        if self.apify_api_token:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        f"{self.apify_base_url}/acts/{self.linkedin_mutuals_actor_id}",
                        headers={"Authorization": f"Bearer {self.apify_api_token}"}
                    )
                    health_status["providers"]["apify"] = {
                        "status": "available" if response.status_code == 200 else "degraded",
                        "response_time_ms": response.elapsed.total_seconds() * 1000,
                        "actor_id": self.linkedin_mutuals_actor_id
                    }
            except Exception as e:
                health_status["providers"]["apify"] = {
                    "status": "unavailable",
                    "error": str(e)
                }
        else:
            health_status["providers"]["apify"] = {"status": "not_configured"}

        # Check Redis cache
        if self.redis:
            try:
                self.redis.ping()
                health_status["cache"] = {"status": "available"}
            except Exception as e:
                health_status["cache"] = {"status": "unavailable", "error": str(e)}
        else:
            health_status["cache"] = {"status": "not_configured"}

        # Check database
        try:
            async with asyncpg.connect(self._require_database_url()) as conn:
                await conn.fetchval("SELECT 1")
            health_status["database"] = {"status": "available"}
        except Exception as e:
            health_status["database"] = {"status": "unavailable", "error": str(e)}
            health_status["status"] = "degraded"

        # Determine overall status
        if health_status["database"]["status"] != "available":
            health_status["status"] = "unhealthy"
        elif health_status["providers"]["apify"]["status"] == "unavailable":
            health_status["status"] = "degraded"

        return health_status

    async def find_mutuals(
        self,
        prospect_id: Union[str, int],
        linkedin_url: str,
        organization_id: Union[str, int],
        tenant_id: Union[str, int, None] = None
    ) -> MutualsResult:
        """
        Lightweight lookup for mutual connections used by Corporate Connect.

        For now we consult existing `prospect_connectors` data. When no cached
        relationships are present we return an empty result so downstream
        stages can proceed gracefully.
        """

        try:
            org_id_int = int(str(organization_id))
        except (TypeError, ValueError):
            logger.warning("Invalid organization id supplied to find_mutuals: %s", organization_id)
            return MutualsResult(connectors=[])

        try:
            async with asyncpg.connect(self._require_database_url()) as conn:
                rows = await conn.fetch("""
                    SELECT
                        pc.id AS prospect_connector_id,
                        pc.connector_id,
                        pc.mutual_connections_count,
                        pc.relationship_strength,
                        pc.discovered_via,
                        pc.rank,
                        pc.ranking_score,
                        c.full_name,
                        c.linkedin_url,
                        c.headline,
                        c.company,
                        c.location,
                        c.profile_picture_url
                    FROM prospect_connectors pc
                    JOIN connectors c
                      ON c.id = pc.connector_id
                     AND c.organization_id = pc.organization_id
                    WHERE pc.prospect_id = $1
                      AND pc.organization_id = $2
                    ORDER BY COALESCE(pc.rank, 999), pc.ranking_score DESC, pc.created_at ASC
                """, int(str(prospect_id)), org_id_int)

        except Exception as exc:
            logger.error("Failed to fetch cached mutual connections: %s", exc)
            return MutualsResult(connectors=[])

        connectors: List[MutualConnection] = []
        for row in rows:
            connector = MutualConnection(
                linkedin_url=row["linkedin_url"],
                full_name=row["full_name"],
                headline=row["headline"],
                current_company=row["company"],
                current_title=row["headline"],
                location=row["location"],
                profile_picture_url=row["profile_picture_url"],
                connection_degree=2,
                shared_connections_count=row["mutual_connections_count"] or 0
            )
            connector.metadata = {
                "prospect_connector_id": row["prospect_connector_id"],
                "connector_id": row["connector_id"],
                "relationship_strength": row["relationship_strength"] or 0.5,
                "discovered_via": row["discovered_via"] or "cache",
                "rank": row["rank"],
                "ranking_score": row["ranking_score"] or 0.0,
                "tenant_id": tenant_id or organization_id,
                "linkedin_target_url": linkedin_url,
                "prospect_id": int(str(prospect_id))
            }
            connectors.append(connector)

        return MutualsResult(connectors=connectors)

    async def find_mutual_connections(
        self,
        *,
        prospect_linkedin_url: str,
        organization_id: Union[str, int],
        team_member_ids: Optional[List[Union[str, int]]] = None,
        prospect_id: Optional[Union[str, int]] = None,
        tenant_id: Optional[Union[str, int]] = None,
    ) -> Dict[str, Any]:
        """Legacy compatibility wrapper that returns mutual connections as dictionaries."""
        connectors_payload: List[Dict[str, Any]] = []

        if prospect_id is not None:
            try:
                cached_result = await self.find_mutuals(
                    prospect_id=prospect_id,
                    linkedin_url=prospect_linkedin_url,
                    organization_id=organization_id,
                    tenant_id=tenant_id,
                )
                for connector in cached_result.connectors:
                    if isinstance(connector, MutualConnection):
                        connector_dict = asdict(connector)
                    elif isinstance(connector, dict):
                        connector_dict = dict(connector)
                    else:
                        connector_dict = dict(connector)  # type: ignore[arg-type]
                    metadata = getattr(connector, "metadata", None) or connector_dict.get("metadata", {})
                    if metadata:
                        connector_dict["metadata"] = metadata
                    connectors_payload.append(connector_dict)
            except Exception as exc:  # pragma: no cover - defensive compatibility
                logger.warning("Cached mutual lookup failed for %s: %s", prospect_linkedin_url, exc)

        if not connectors_payload and apify_client and hasattr(apify_client, "run_actor"):
            try:
                run_response = apify_client.run_actor(  # type: ignore[attr-defined]
                    self.linkedin_mutuals_actor_id,
                    {
                        "prospectUrl": prospect_linkedin_url,
                        "organizationId": organization_id,
                        "teamMemberIds": team_member_ids or [],
                        "tenantId": tenant_id,
                    },
                )
                if asyncio.iscoroutine(run_response):
                    run_response = await run_response
                items = (run_response or {}).get("items", [])
                for item in items:
                    connector_payload = {
                        "full_name": item.get("fullName") or item.get("name"),
                        "linkedin_url": item.get("profileUrl") or item.get("linkedinUrl"),
                        "headline": item.get("headline"),
                        "company": item.get("company"),
                        "connection_degree": item.get("mutualConnectionsCount") or item.get("connectionDegree") or 2,
                        "metadata": {
                            "provider": "apify",
                            "raw": item,
                            "team_member_ids": team_member_ids or [],
                        },
                    }
                    connectors_payload.append(connector_payload)
            except Exception as exc:  # pragma: no cover - integration fallback
                logger.warning("Apify mutual discovery failed for %s: %s", prospect_linkedin_url, exc)

        total_found = len(connectors_payload)
        return {
            "status": "success" if total_found >= 0 else "error",
            "connectors": connectors_payload,
            "total_mutuals_found": total_found,
        }

    async def discover_mutuals_for_prospect(
        self,
        prospect_data: Dict[str, Any],
        team_member_data: Dict[str, Any],
        organization_id: Union[str, int],
        max_connections: int = 50
    ) -> Dict[str, Any]:
        """
        Discover mutual connections for a specific prospect using team member credentials

        Args:
            prospect_data: Dictionary containing prospect information (linkedin_url required)
            team_member_data: Dictionary containing team member info and cookies
            organization_id: Organization/tenant identifier
            max_connections: Maximum number of mutual connections to return

        Returns:
            Dictionary containing discovered connections and metadata
        """
        try:
            # Extract required data
            prospect_linkedin_url = prospect_data.get("linkedin_url")
            team_member_linkedin_url = team_member_data.get("linkedin_url")
            cookies = team_member_data.get("cookies", {})

            if not prospect_linkedin_url or not team_member_linkedin_url:
                return {
                    "connections": [],
                    "error": "Missing required LinkedIn URLs",
                    "success": False
                }

            if not cookies.get("li_at"):
                return {
                    "connections": [],
                    "error": "Missing LinkedIn authentication cookie (li_at)",
                    "success": False
                }

            # Use the existing discover_mutuals_apify method
            tenant_id = str(organization_id)
            connections = await self._discover_mutuals_apify(
                prospect_url=prospect_linkedin_url,
                team_member_url=team_member_linkedin_url,
                session_data=cookies,
                tenant_id=tenant_id,
                max_connections=max_connections
            )

            return {
                "connections": [asdict(conn) for conn in connections],
                "success": True,
                "total_found": len(connections),
                "max_requested": max_connections,
                "prospect_url": prospect_linkedin_url,
                "team_member_url": team_member_linkedin_url,
                "organization_id": organization_id
            }

        except Exception as e:
            logger.error(f"Failed to discover mutuals for prospect: {e}")
            return {
                "connections": [],
                "error": str(e),
                "success": False,
                "organization_id": organization_id
            }


# Global service instance
mutuals_orchestrator_service = MutualsOrchestratorService(
    database_url=settings.DATABASE_URL or os.getenv("DATABASE_URL"),
    redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    apify_api_token=settings.APIFY_TOKEN,
    phantombuster_api_key=settings.PHANTOMBUSTER_API_KEY,
)
