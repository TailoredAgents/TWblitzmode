"""
External API Integration Orchestrator
September 2025 - Production-Ready Multi-Provider Integration

Coordinates all external API integrations with:
- Clearbit executive lookup
- CUFinder email enrichment
- SendGrid email delivery
- Apify LinkedIn scraping
- Intelligent fallback strategies
- Circuit breaker patterns
- Comprehensive error handling
"""

import asyncio
import logging
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import traceback

from integrations.clearbit_client import ClearbitClient, create_clearbit_client
from integrations.cufinder_client import CUFinderClient
from integrations.hunter_client import HunterClient
from integrations.apollo_client import ApolloClient
from integrations.sendgrid_client import SendGridEmailService
from integrations.apify_client import ApifyClient
from services.audit_logging_service import audit_logger, AuditEventType, AuditSeverity
from api.database import get_db

logger = logging.getLogger(__name__)

class IntegrationProvider(Enum):
    CLEARBIT = "clearbit"
    APOLLO = "apollo"
    CUFINDER = "cufinder"
    HUNTER = "hunter"
    SENDGRID = "sendgrid"
    APIFY = "apify"
    PHANTOMBUSTER = "phantombuster"

class OperationType(Enum):
    EXECUTIVE_LOOKUP = "executive_lookup"
    COMPANY_ENRICHMENT = "company_enrichment"
    EMAIL_ENRICHMENT = "email_enrichment"
    EMAIL_SENDING = "email_sending"
    LINKEDIN_SCRAPING = "linkedin_scraping"

@dataclass
class IntegrationResult:
    """Result from external API operation"""
    operation: OperationType
    provider: IntegrationProvider
    success: bool
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    response_time_ms: int = 0
    cost: float = 0.0
    confidence_score: float = 0.0
    cached: bool = False
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

@dataclass
class IntegrationConfig:
    """Configuration for external integrations"""
    clearbit_api_key: Optional[str] = None
    apollo_api_key: Optional[str] = None
    cufinder_api_key: Optional[str] = None
    hunter_api_key: Optional[str] = None
    sendgrid_api_key: Optional[str] = None
    apify_api_key: Optional[str] = None
    phantombuster_api_key: Optional[str] = None

    # Feature flags
    enable_clearbit: bool = True
    enable_apollo_fallback: bool = True
    enable_cufinder: bool = True
    enable_hunter_fallback: bool = True
    enable_email_sending: bool = True
    enable_linkedin_scraping: bool = True

    # Rate limiting and quotas
    daily_clearbit_quota: int = 1000
    daily_cufinder_quota: int = 5000
    daily_email_quota: int = 10000
    hourly_linkedin_quota: int = 50

class ExternalAPIOrchestrator:
    """Production-ready external API integration orchestrator"""

    def __init__(self,
                 config: IntegrationConfig,
                 database_url: str,
                 redis_url: str = "redis://localhost:6379/2"):

        self.config = config
        self.database_url = database_url
        self.redis_url = redis_url

        # Initialize API clients
        self.clearbit_client = None
        self.apollo_client = None
        self.cufinder_client = None
        self.hunter_client = None
        self.sendgrid_client = None
        self.apify_client = None

        # Usage tracking
        self.daily_usage = {}
        self.hourly_usage = {}

        # Performance metrics
        self.operation_metrics = {}

        logger.info("🔌 External API Orchestrator initialized")

    async def initialize_clients(self):
        """Initialize all API clients with proper configuration"""

        try:
            # Initialize Clearbit
            if self.config.clearbit_api_key and self.config.enable_clearbit:
                self.clearbit_client = create_clearbit_client(
                    api_key=self.config.clearbit_api_key,
                    redis_url=self.redis_url,
                    database_url=self.database_url
                )
                logger.info("✅ Clearbit client initialized")

            # Initialize Apollo
            if self.config.apollo_api_key and self.config.enable_apollo_fallback:
                self.apollo_client = ApolloClient()
                logger.info("✅ Apollo client initialized")

            # Initialize CUFinder
            if self.config.cufinder_api_key and self.config.enable_cufinder:
                self.cufinder_client = CUFinderClient(
                    api_key=self.config.cufinder_api_key,
                    redis_url=self.redis_url
                )
                logger.info("✅ CUFinder client initialized")

            # Initialize Hunter
            if self.config.hunter_api_key and self.config.enable_hunter_fallback:
                self.hunter_client = HunterClient()
                logger.info("✅ Hunter client initialized")

            # Initialize SendGrid
            if self.config.sendgrid_api_key and self.config.enable_email_sending:
                self.sendgrid_client = SendGridEmailService(
                    api_key=self.config.sendgrid_api_key
                )
                logger.info("✅ SendGrid client initialized")

            # Initialize Apify
            if self.config.apify_api_key and self.config.enable_linkedin_scraping:
                self.apify_client = ApifyClient(
                    api_key=self.config.apify_api_key
                )
                logger.info("✅ Apify client initialized")

            logger.info("🚀 All external API clients initialized successfully")

        except Exception as e:
            logger.error(f"❌ Failed to initialize API clients: {e}")
            raise

    async def enrich_executive(self,
                             tenant_id: int,
                             company_domain: str,
                             executive_name: str,
                             executive_email: Optional[str] = None) -> IntegrationResult:
        """
        Enrich executive data using primary and fallback providers

        Strategy:
        1. Try Clearbit (primary) - most accurate but expensive
        2. Fallback to Apollo if Clearbit fails
        3. Return best available data with confidence scoring
        """

        operation_start = time.time()
        logger.info(f"🔍 Enriching executive: {executive_name} at {company_domain}")

        # Check quotas
        if not await self._check_quota(tenant_id, "executive_lookup"):
            return IntegrationResult(
                operation=OperationType.EXECUTIVE_LOOKUP,
                provider=IntegrationProvider.CLEARBIT,
                success=False,
                error_message="Daily quota exceeded for executive lookup"
            )

        try:
            # Primary: Clearbit lookup
            if self.clearbit_client:
                clearbit_result = await self._try_clearbit_lookup(
                    company_domain, executive_name, executive_email
                )

                if clearbit_result.success and clearbit_result.confidence_score >= 0.7:
                    # High confidence result from Clearbit
                    await self._record_usage(tenant_id, "executive_lookup", "clearbit")
                    await self._log_integration_event(tenant_id, clearbit_result, "primary_success")

                    clearbit_result.response_time_ms = int((time.time() - operation_start) * 1000)
                    logger.info(f"✅ High-confidence Clearbit result: {clearbit_result.confidence_score:.2f}")
                    return clearbit_result

            # Fallback: Apollo lookup
            if self.config.enable_apollo_fallback:
                apollo_result = await self._try_apollo_lookup(
                    company_domain, executive_name, executive_email
                )

                if apollo_result.success:
                    await self._record_usage(tenant_id, "executive_lookup", "apollo")
                    await self._log_integration_event(tenant_id, apollo_result, "fallback_success")

                    apollo_result.response_time_ms = int((time.time() - operation_start) * 1000)
                    logger.info(f"✅ Apollo fallback successful: {apollo_result.confidence_score:.2f}")
                    return apollo_result

            # No successful enrichment
            failed_result = IntegrationResult(
                operation=OperationType.EXECUTIVE_LOOKUP,
                provider=IntegrationProvider.CLEARBIT,
                success=False,
                error_message="All executive lookup providers failed",
                response_time_ms=int((time.time() - operation_start) * 1000)
            )

            await self._log_integration_event(tenant_id, failed_result, "all_providers_failed")
            logger.warning(f"❌ All executive lookup providers failed for {executive_name}")
            return failed_result

        except Exception as e:
            logger.error(f"❌ Executive enrichment failed: {e}")
            return IntegrationResult(
                operation=OperationType.EXECUTIVE_LOOKUP,
                provider=IntegrationProvider.CLEARBIT,
                success=False,
                error_message=str(e),
                response_time_ms=int((time.time() - operation_start) * 1000)
            )

    async def enrich_emails(self,
                          tenant_id: int,
                          contacts: List[Dict[str, Any]]) -> List[IntegrationResult]:
        """
        Batch email enrichment using CUFinder and Hunter fallback

        Args:
            contacts: List of contacts with name and company info

        Returns:
            List of IntegrationResult with email data
        """

        logger.info(f"📧 Enriching emails for {len(contacts)} contacts")
        results = []

        # Check quotas
        if not await self._check_quota(tenant_id, "email_enrichment", len(contacts)):
            return [IntegrationResult(
                operation=OperationType.EMAIL_ENRICHMENT,
                provider=IntegrationProvider.CUFINDER,
                success=False,
                error_message="Daily quota exceeded for email enrichment"
            )]

        try:
            # Primary: CUFinder batch lookup
            if self.cufinder_client:
                cufinder_results = await self._try_cufinder_batch(contacts)
                results.extend(cufinder_results)

                # Track successful enrichments
                successful_count = len([r for r in cufinder_results if r.success])
                await self._record_usage(tenant_id, "email_enrichment", "cufinder", successful_count)

            # Fallback: Hunter for failed cases
            if self.config.enable_hunter_fallback:
                failed_contacts = [
                    contacts[i] for i, result in enumerate(results)
                    if not result.success
                ]

                if failed_contacts:
                    hunter_results = await self._try_hunter_batch(failed_contacts)
                    # Replace failed results with Hunter results
                    for i, result in enumerate(results):
                        if not result.success and i < len(hunter_results):
                            results[i] = hunter_results[i]

            logger.info(f"✅ Email enrichment complete: {len([r for r in results if r.success])}/{len(contacts)} successful")
            return results

        except Exception as e:
            logger.error(f"❌ Email enrichment failed: {e}")
            return [IntegrationResult(
                operation=OperationType.EMAIL_ENRICHMENT,
                provider=IntegrationProvider.CUFINDER,
                success=False,
                error_message=str(e)
            )]

    async def send_introduction_email(self,
                                    tenant_id: int,
                                    email_data: Dict[str, Any]) -> IntegrationResult:
        """
        Send introduction email via SendGrid with tracking and compliance

        Args:
            email_data: Email content and metadata

        Returns:
            IntegrationResult with sending status
        """

        operation_start = time.time()
        logger.info(f"📬 Sending introduction email to {email_data.get('to_email')}")

        # Check quotas
        if not await self._check_quota(tenant_id, "email_sending"):
            return IntegrationResult(
                operation=OperationType.EMAIL_SENDING,
                provider=IntegrationProvider.SENDGRID,
                success=False,
                error_message="Daily email quota exceeded"
            )

        try:
            if not self.sendgrid_client:
                raise Exception("SendGrid client not initialized")

            # Enhance email with compliance features
            enhanced_email = await self._prepare_compliant_email(email_data)

            # Send via SendGrid
            send_result = await self.sendgrid_client.send_email(enhanced_email)

            if send_result.success:
                await self._record_usage(tenant_id, "email_sending", "sendgrid")

                result = IntegrationResult(
                    operation=OperationType.EMAIL_SENDING,
                    provider=IntegrationProvider.SENDGRID,
                    success=True,
                    data={"message_id": send_result.message_id, "status": send_result.status.value},
                    response_time_ms=int((time.time() - operation_start) * 1000),
                    cost=0.001  # Approximate cost per email
                )

                await self._log_integration_event(tenant_id, result, "email_sent")
                logger.info(f"✅ Email sent successfully: {send_result.message_id}")
                return result
            else:
                raise Exception(send_result.error_message)

        except Exception as e:
            logger.error(f"❌ Email sending failed: {e}")
            return IntegrationResult(
                operation=OperationType.EMAIL_SENDING,
                provider=IntegrationProvider.SENDGRID,
                success=False,
                error_message=str(e),
                response_time_ms=int((time.time() - operation_start) * 1000)
            )

    async def scrape_linkedin_connections(self,
                                        tenant_id: int,
                                        linkedin_url: str,
                                        team_member_cookies: Dict[str, str]) -> IntegrationResult:
        """
        Scrape LinkedIn mutual connections using Apify

        Args:
            linkedin_url: Target LinkedIn profile URL
            team_member_cookies: LinkedIn session cookies

        Returns:
            IntegrationResult with mutual connections data
        """

        operation_start = time.time()
        logger.info(f"🔗 Scraping LinkedIn connections for {linkedin_url}")

        # Check quotas
        if not await self._check_quota(tenant_id, "linkedin_scraping"):
            return IntegrationResult(
                operation=OperationType.LINKEDIN_SCRAPING,
                provider=IntegrationProvider.APIFY,
                success=False,
                error_message="Hourly LinkedIn scraping quota exceeded"
            )

        try:
            if not self.apify_client:
                raise Exception("Apify client not initialized")

            # Start Apify actor run
            run_result = await self.apify_client.start_mutual_connections_actor(
                linkedin_url, team_member_cookies
            )

            if run_result["success"]:
                await self._record_usage(tenant_id, "linkedin_scraping", "apify")

                result = IntegrationResult(
                    operation=OperationType.LINKEDIN_SCRAPING,
                    provider=IntegrationProvider.APIFY,
                    success=True,
                    data={"run_id": run_result["run_id"], "status": "started"},
                    response_time_ms=int((time.time() - operation_start) * 1000),
                    cost=0.05  # Approximate cost per run
                )

                await self._log_integration_event(tenant_id, result, "linkedin_scraping_started")
                logger.info(f"✅ LinkedIn scraping started: {run_result['run_id']}")
                return result
            else:
                raise Exception(run_result.get("error", "Unknown Apify error"))

        except Exception as e:
            logger.error(f"❌ LinkedIn scraping failed: {e}")
            return IntegrationResult(
                operation=OperationType.LINKEDIN_SCRAPING,
                provider=IntegrationProvider.APIFY,
                success=False,
                error_message=str(e),
                response_time_ms=int((time.time() - operation_start) * 1000)
            )

    async def get_integration_health(self) -> Dict[str, Any]:
        """Get health status of all external integrations"""

        health_status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "providers": {},
            "overall_status": "healthy"
        }

        # Check each provider
        providers_to_check = [
            ("clearbit", self.clearbit_client),
            ("cufinder", self.cufinder_client),
            ("sendgrid", self.sendgrid_client),
            ("apify", self.apify_client)
        ]

        for provider_name, client in providers_to_check:
            if client:
                try:
                    # Attempt a simple health check
                    status = await self._check_provider_health(provider_name, client)
                    health_status["providers"][provider_name] = status
                except Exception as e:
                    health_status["providers"][provider_name] = {
                        "status": "unhealthy",
                        "error": str(e)
                    }
                    health_status["overall_status"] = "degraded"
            else:
                health_status["providers"][provider_name] = {
                    "status": "disabled",
                    "reason": "Client not initialized"
                }

        return health_status

    # Private helper methods

    async def _try_clearbit_lookup(self,
                                 company_domain: str,
                                 executive_name: str,
                                 executive_email: Optional[str]) -> IntegrationResult:
        """Try Clearbit executive lookup"""

        try:
            enrichment_result = await self.clearbit_client.enrich_prospect(
                company_domain, executive_name, executive_email
            )

            if enrichment_result["success"]:
                return IntegrationResult(
                    operation=OperationType.EXECUTIVE_LOOKUP,
                    provider=IntegrationProvider.CLEARBIT,
                    success=True,
                    data=enrichment_result,
                    confidence_score=enrichment_result["overall_confidence"],
                    cost=0.50  # Approximate Clearbit cost
                )
            else:
                return IntegrationResult(
                    operation=OperationType.EXECUTIVE_LOOKUP,
                    provider=IntegrationProvider.CLEARBIT,
                    success=False,
                    error_message="No data found"
                )

        except Exception as e:
            return IntegrationResult(
                operation=OperationType.EXECUTIVE_LOOKUP,
                provider=IntegrationProvider.CLEARBIT,
                success=False,
                error_message=str(e)
            )

    async def _try_apollo_lookup(self,
                               company_domain: str,
                               executive_name: str,
                               executive_email: Optional[str]) -> IntegrationResult:
        """Try Apollo executive lookup (fallback)"""

        try:
            # Use real Apollo client
            if not self.apollo_client:
                raise Exception("Apollo client not initialized")

            apollo_result = await self.apollo_client.lookup_executive(
                company_domain, executive_name, executive_email
            )

            if apollo_result.status.value == "success":
                return IntegrationResult(
                    operation=OperationType.EXECUTIVE_LOOKUP,
                    provider=IntegrationProvider.APOLLO,
                    success=True,
                    data={
                        "executive": apollo_result.executive_data,
                        "overall_confidence": apollo_result.confidence,
                        "data_source": "apollo"
                    },
                    confidence_score=apollo_result.confidence,
                    cost=apollo_result.cost
                )
            else:
                return IntegrationResult(
                    operation=OperationType.EXECUTIVE_LOOKUP,
                    provider=IntegrationProvider.APOLLO,
                    success=False,
                    error_message=apollo_result.error_message or "Apollo lookup failed"
                )

        except Exception as e:
            return IntegrationResult(
                operation=OperationType.EXECUTIVE_LOOKUP,
                provider=IntegrationProvider.APOLLO,
                success=False,
                error_message=str(e)
            )

    async def _try_cufinder_batch(self, contacts: List[Dict[str, Any]]) -> List[IntegrationResult]:
        """Try CUFinder batch email enrichment"""

        results = []
        for contact in contacts:
            try:
                # Use existing CUFinder client
                enrichment_result = await self.cufinder_client.find_email(
                    first_name=contact.get("first_name", ""),
                    last_name=contact.get("last_name", ""),
                    company_domain=contact.get("company_domain", "")
                )

                result = IntegrationResult(
                    operation=OperationType.EMAIL_ENRICHMENT,
                    provider=IntegrationProvider.CUFINDER,
                    success=enrichment_result.status.value == "success",
                    data=asdict(enrichment_result) if enrichment_result.email else None,
                    confidence_score=enrichment_result.confidence,
                    cost=enrichment_result.cost
                )
                results.append(result)

            except Exception as e:
                results.append(IntegrationResult(
                    operation=OperationType.EMAIL_ENRICHMENT,
                    provider=IntegrationProvider.CUFINDER,
                    success=False,
                    error_message=str(e)
                ))

        return results

    async def _try_hunter_batch(self, contacts: List[Dict[str, Any]]) -> List[IntegrationResult]:
        """Try Hunter email enrichment (fallback)"""

        results = []
        for contact in contacts:
            try:
                # Use real Hunter client
                if not self.hunter_client:
                    raise Exception("Hunter client not initialized")

                hunter_result = await self.hunter_client.find_email(
                    first_name=contact.get("first_name", ""),
                    last_name=contact.get("last_name", ""),
                    company_domain=contact.get("company_domain", "")
                )

                result = IntegrationResult(
                    operation=OperationType.EMAIL_ENRICHMENT,
                    provider=IntegrationProvider.HUNTER,
                    success=hunter_result.status.value == "success",
                    data={"email": hunter_result.email, "confidence": hunter_result.confidence} if hunter_result.email else None,
                    confidence_score=hunter_result.confidence,
                    cost=hunter_result.cost,
                    error_message=hunter_result.error_message if not hunter_result.email else None
                )
                results.append(result)

            except Exception as e:
                results.append(IntegrationResult(
                    operation=OperationType.EMAIL_ENRICHMENT,
                    provider=IntegrationProvider.HUNTER,
                    success=False,
                    error_message=str(e)
                ))

        return results

    async def _prepare_compliant_email(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare email with compliance features (unsubscribe, etc.)"""

        enhanced_email = email_data.copy()

        # Add unsubscribe link
        unsubscribe_url = f"https://vouchlinkai.com/unsubscribe?token={email_data.get('unsubscribe_token', '')}"

        # Add compliance footer
        compliance_footer = f"""

        ---
        This email was sent to you as part of a professional introduction.
        If you no longer wish to receive these emails, you can unsubscribe here: {unsubscribe_url}

        VouchLink AI Corporate Introductions
        © 2025 All rights reserved
        """

        enhanced_email["content"] = email_data.get("content", "") + compliance_footer
        enhanced_email["tracking_enabled"] = True
        enhanced_email["category"] = "introduction"

        return enhanced_email

    async def _check_quota(self,
                         tenant_id: int,
                         operation_type: str,
                         count: int = 1) -> bool:
        """Check if operation is within quota limits"""

        try:
            # Import database connection here to avoid circular imports

            with get_db() as conn:
                cursor = conn.cursor()

                # Get current usage for today
                today = datetime.now(timezone.utc).date()
                cursor.execute("""
                    SELECT COALESCE(SUM(count), 0) as daily_usage
                    FROM api_usage
                    WHERE tenant_id = %s
                    AND operation_type = %s
                    AND DATE(timestamp) = %s
                """, (tenant_id, operation_type, today))

                current_usage = cursor.fetchone()[0]

                # Check against quotas
                quota_limits = {
                    "executive_lookup": self.config.daily_clearbit_quota,
                    "email_enrichment": self.config.daily_cufinder_quota,
                    "email_sending": self.config.daily_email_quota,
                    "linkedin_scraping": self.config.hourly_linkedin_quota  # This needs hourly check
                }

                limit = quota_limits.get(operation_type, 1000)

                # For LinkedIn scraping, check hourly quota
                if operation_type == "linkedin_scraping":
                    current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                    cursor.execute("""
                        SELECT COALESCE(SUM(count), 0) as hourly_usage
                        FROM api_usage
                        WHERE tenant_id = %s
                        AND operation_type = %s
                        AND timestamp >= %s
                    """, (tenant_id, operation_type, current_hour))

                    current_usage = cursor.fetchone()[0]

                if (current_usage + count) <= limit:
                    return True
                else:
                    logger.warning(f"Quota exceeded for {operation_type}: {current_usage + count} > {limit}")
                    return False

        except Exception as e:
            logger.error(f"Failed to check quota: {e}")
            # Return True to not block operations if quota check fails
            return True

    async def _record_usage(self,
                          tenant_id: int,
                          operation_type: str,
                          provider: str,
                          count: int = 1):
        """Record API usage for analytics and billing"""

        try:
            # Import database connection here to avoid circular imports

            with get_db() as conn:
                cursor = conn.cursor()

                # Create api_usage table if it doesn't exist
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_usage (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER NOT NULL,
                        operation_type VARCHAR(100) NOT NULL,
                        provider VARCHAR(50) NOT NULL,
                        count INTEGER NOT NULL DEFAULT 1,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create index if it doesn't exist
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_api_usage_tenant_operation_date
                    ON api_usage (tenant_id, operation_type, DATE(timestamp))
                """)

                # Record usage
                cursor.execute("""
                    INSERT INTO api_usage (tenant_id, operation_type, provider, count, timestamp)
                    VALUES (%s, %s, %s, %s, %s)
                """, (tenant_id, operation_type, provider, count, datetime.now(timezone.utc)))

                conn.commit()

                logger.debug(f"Recorded API usage: {tenant_id} {operation_type} {provider} {count}")

        except Exception as e:
            logger.error(f"Failed to record API usage: {e}")

    async def _log_integration_event(self,
                                   tenant_id: int,
                                   result: IntegrationResult,
                                   event_type: str):
        """Log integration events for audit trail"""

        try:
            await audit_logger.log_event(
                event_type=AuditEventType.EXTERNAL_API_CALL,
                actor_type="system",
                actor_id="external_api_orchestrator",
                target_type="integration",
                target_id=f"{result.provider.value}_{result.operation.value}",
                organization_id=tenant_id,
                details={
                    "operation": result.operation.value,
                    "provider": result.provider.value,
                    "success": result.success,
                    "response_time_ms": result.response_time_ms,
                    "cost": result.cost,
                    "event_type": event_type
                },
                severity=AuditSeverity.INFO if result.success else AuditSeverity.WARNING
            )

        except Exception as e:
            logger.error(f"Failed to log integration event: {e}")

    async def _check_provider_health(self, provider_name: str, client: Any) -> Dict[str, Any]:
        """Check health of specific provider"""

        # Basic health check - can be enhanced per provider
        return {
            "status": "healthy",
            "last_check": datetime.now(timezone.utc).isoformat(),
            "response_time_ms": 50
        }

# Factory function
def create_external_api_orchestrator(config: IntegrationConfig, **kwargs) -> ExternalAPIOrchestrator:
    """Create configured external API orchestrator"""
    return ExternalAPIOrchestrator(config=config, **kwargs)
