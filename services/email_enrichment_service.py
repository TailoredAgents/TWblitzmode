"""
Corporate Email Enrichment Service

Enhanced email enrichment service designed for the corporate warm-intro workflow.
Integrates with the prospect_connectors table and provides batch processing
for connector email discovery using multiple providers.

Features:
- Corporate schema integration (organizations, prospects, connectors)
- Batch processing with intelligent queuing
- CUFinder-powered email discovery with caching
- Confidence scoring
- Cost optimization with caching
- Rate limiting and quota management
- Comprehensive audit logging
"""

import os
import json
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

# Import existing integration client
from integrations.cufinder_client import CUFinderClient, EmailEnrichmentResult, EnrichmentStatus

logger = logging.getLogger(__name__)

class EmailDiscoveryStatus(Enum):
    """Email discovery status for corporate workflow"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INSUFFICIENT_QUOTA = "insufficient_quota"
    NO_EMAILS_FOUND = "no_emails_found"

@dataclass
class ConnectorEmailResult:
    """Email enrichment result for a single connector"""
    connector_id: int
    prospect_connector_id: int
    email: Optional[str]
    confidence: float
    source: str
    status: EmailDiscoveryStatus
    cost_usd: float
    processing_time_seconds: float
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

@dataclass
class BatchEnrichmentResult:
    """Result of batch email enrichment for an organization"""
    organization_id: int
    prospect_id: Optional[int]
    total_connectors: int
    emails_found: int
    high_confidence_emails: int
    total_cost_usd: float
    processing_time_seconds: float
    connector_results: List[ConnectorEmailResult]
    cache_hit_rate: float

class CorporateEmailEnrichmentService:
    """Production-ready email enrichment service for corporate workflow"""

    def __init__(self):
        # Service configuration
        self.batch_size = int(os.getenv('EMAIL_BATCH_SIZE', '50'))
        self.min_confidence_threshold = float(os.getenv('MIN_EMAIL_CONFIDENCE', '0.7'))
        self.cache_duration_days = int(os.getenv('EMAIL_CACHE_DAYS', '30'))

        # Cost and quota settings
        self.cost_per_email_lookup = float(os.getenv('COST_PER_EMAIL_LOOKUP', '0.03'))
        self.max_cost_per_batch = float(os.getenv('MAX_EMAIL_BATCH_COST', '50.0'))

        # Provider clients (multi-provider strategy)
        self.cufinder_client = CUFinderClient(fail_on_missing=False)    # Primary
        if not self.cufinder_client.is_configured:
            logger.warning(
                "CUFinder client operating in degraded mode: configure an API key to enable enrichment."
            )

    async def enrich_prospect_connectors(
        self,
        prospect_id: int,
        organization_id: int,
        force_refresh: bool = False
    ) -> BatchEnrichmentResult:
        """Enrich emails for all top connectors of a specific prospect"""

        start_time = time.time()
        logger.info(f"Starting email enrichment for prospect {prospect_id}")

        try:
            # Get top-ranked connectors for this prospect
            connectors = await self._get_prospect_connectors_for_enrichment(
                prospect_id, organization_id
            )

            if not connectors:
                return BatchEnrichmentResult(
                    organization_id=organization_id,
                    prospect_id=prospect_id,
                    total_connectors=0,
                    emails_found=0,
                    high_confidence_emails=0,
                    total_cost_usd=0.0,
                    processing_time_seconds=time.time() - start_time,
                    connector_results=[],
                    cache_hit_rate=0.0
                )

            # Check organization quota
            if not await self._check_email_quota(organization_id, len(connectors)):
                logger.warning(f"Insufficient email quota for organization {organization_id}")
                return self._create_quota_exceeded_result(
                    organization_id, prospect_id, len(connectors), start_time
                )

            # Process connectors in batches
            all_results = []
            cache_hits = 0

            for i in range(0, len(connectors), self.batch_size):
                batch = connectors[i:i + self.batch_size]

                logger.info(f"Processing email batch {i//self.batch_size + 1}: {len(batch)} connectors")

                batch_results, batch_cache_hits = await self._process_connector_batch(
                    batch, organization_id, force_refresh
                )

                all_results.extend(batch_results)
                cache_hits += batch_cache_hits

                # Rate limiting between batches
                if i + self.batch_size < len(connectors):
                    await asyncio.sleep(2)

            # Calculate aggregate results
            emails_found = len([r for r in all_results if r.email])
            high_confidence = len([r for r in all_results if r.confidence >= self.min_confidence_threshold])
            total_cost = sum(r.cost_usd for r in all_results)
            cache_hit_rate = cache_hits / len(connectors) if connectors else 0.0

            # Update prospect status
            if emails_found > 0:
                await self._update_prospect_enrichment_status(prospect_id, organization_id, "enriched")
            else:
                await self._update_prospect_enrichment_status(prospect_id, organization_id, "enrichment_failed")

            # Create audit log
            await self._create_enrichment_audit(
                organization_id, prospect_id, emails_found, total_cost
            )

            processing_time = time.time() - start_time

            logger.info(
                f"Email enrichment completed for prospect {prospect_id}: "
                f"{emails_found}/{len(connectors)} emails found, "
                f"${total_cost:.2f} cost, {cache_hit_rate:.1%} cache hit rate"
            )

            return BatchEnrichmentResult(
                organization_id=organization_id,
                prospect_id=prospect_id,
                total_connectors=len(connectors),
                emails_found=emails_found,
                high_confidence_emails=high_confidence,
                total_cost_usd=total_cost,
                processing_time_seconds=processing_time,
                connector_results=all_results,
                cache_hit_rate=cache_hit_rate
            )

        except Exception as e:
            logger.error(f"Email enrichment failed for prospect {prospect_id}: {e}")
            return self._create_error_result(
                organization_id, prospect_id, str(e), start_time
            )

    async def enrich_connector(
        self,
        connector: Dict[str, Any],
        organization_id: int,
        force_refresh: bool = False
    ) -> ConnectorEmailResult:
        """
        Lightweight enrichment for a single connector used by Corporate Connect.
        """

        payload = dict(connector)
        metadata = payload.get("metadata") or {}
        payload.setdefault("connector_id", metadata.get("connector_id"))
        payload.setdefault("prospect_connector_id", metadata.get("prospect_connector_id"))
        payload.setdefault("full_name", metadata.get("full_name") or payload.get("full_name"))
        payload.setdefault("company", metadata.get("company") or payload.get("company"))
        payload.setdefault("linkedin_url", metadata.get("linkedin_url") or payload.get("linkedin_url"))

        results, _ = await self._process_connector_batch(
            [payload],
            organization_id=organization_id,
            force_refresh=force_refresh
        )

        if results:
            result = results[0]
            result.metadata.update(metadata)
            result.metadata.setdefault("prospect_id", payload.get("prospect_id") or metadata.get("prospect_id"))
            result.metadata.setdefault("tenant_id", metadata.get("tenant_id"))
            return result

        return ConnectorEmailResult(
            connector_id=payload.get("connector_id") or 0,
            prospect_connector_id=payload.get("prospect_connector_id") or 0,
            email=None,
            confidence=0.0,
            source="unavailable",
            status=EmailDiscoveryStatus.NO_EMAILS_FOUND,
            cost_usd=0.0,
            processing_time_seconds=0.0,
            error_message="No email address discovered for connector",
            metadata=metadata
        )

    async def enrich_organization_connectors(
        self,
        organization_id: int,
        limit: int = 100
    ) -> BatchEnrichmentResult:
        """Batch enrich emails for all connectors in an organization"""

        start_time = time.time()
        logger.info(f"Starting organization-wide email enrichment for org {organization_id}")

        try:
            # Get all connectors without emails
            connectors = await self._get_organization_connectors_for_enrichment(
                organization_id, limit
            )

            if not connectors:
                return BatchEnrichmentResult(
                    organization_id=organization_id,
                    prospect_id=None,
                    total_connectors=0,
                    emails_found=0,
                    high_confidence_emails=0,
                    total_cost_usd=0.0,
                    processing_time_seconds=time.time() - start_time,
                    connector_results=[],
                    cache_hit_rate=0.0
                )

            # Process in batches with rate limiting
            all_results = []
            cache_hits = 0

            for i in range(0, len(connectors), self.batch_size):
                batch = connectors[i:i + self.batch_size]

                batch_results, batch_cache_hits = await self._process_connector_batch(
                    batch, organization_id, force_refresh=False
                )

                all_results.extend(batch_results)
                cache_hits += batch_cache_hits

                # Longer delay for organization-wide processing
                if i + self.batch_size < len(connectors):
                    await asyncio.sleep(5)

            # Aggregate and return results
            emails_found = len([r for r in all_results if r.email])
            high_confidence = len([r for r in all_results if r.confidence >= self.min_confidence_threshold])
            total_cost = sum(r.cost_usd for r in all_results)

            return BatchEnrichmentResult(
                organization_id=organization_id,
                prospect_id=None,
                total_connectors=len(connectors),
                emails_found=emails_found,
                high_confidence_emails=high_confidence,
                total_cost_usd=total_cost,
                processing_time_seconds=time.time() - start_time,
                connector_results=all_results,
                cache_hit_rate=cache_hits / len(connectors) if connectors else 0.0
            )

        except Exception as e:
            logger.error(f"Organization email enrichment failed for org {organization_id}: {e}")
            return self._create_error_result(organization_id, None, str(e), start_time)

    async def _get_prospect_connectors_for_enrichment(
        self,
        prospect_id: int,
        organization_id: int
    ) -> List[Dict[str, Any]]:
        """Get top-ranked connectors for a prospect that need email enrichment"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            # Get top 5 connectors without emails or with low confidence
            connectors = query(conn, """
                SELECT
                    pc.id as prospect_connector_id,
                    pc.connector_id,
                    c.full_name,
                    c.linkedin_url,
                    c.company,
                    c.email,
                    c.email_status,
                    c.email_confidence,
                    pc.rank,
                    pc.ranking_score
                FROM prospect_connectors pc
                JOIN connectors c ON pc.connector_id = c.id
                WHERE pc.prospect_id = ? AND pc.organization_id = ?
                AND pc.rank IS NOT NULL
                AND (c.email IS NULL OR c.email_status = 'not_checked'
                     OR (c.email_confidence IS NOT NULL AND c.email_confidence < 0.7))
                ORDER BY pc.rank ASC
                LIMIT 5
            """, (prospect_id, organization_id))

            return [dict(row) for row in connectors]

    async def _get_organization_connectors_for_enrichment(
        self,
        organization_id: int,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Get connectors across organization that need email enrichment"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            connectors = query(conn, """
                SELECT
                    pc.id as prospect_connector_id,
                    pc.connector_id,
                    c.full_name,
                    c.linkedin_url,
                    c.company,
                    c.email,
                    c.email_status,
                    c.email_confidence,
                    pc.ranking_score
                FROM prospect_connectors pc
                JOIN connectors c ON pc.connector_id = c.id
                WHERE pc.organization_id = ?
                AND (c.email IS NULL OR c.email_status = 'not_checked')
                ORDER BY pc.ranking_score DESC
                LIMIT ?
            """, (organization_id, limit))

            return [dict(row) for row in connectors]

    async def _process_connector_batch(
        self,
        connectors: List[Dict[str, Any]],
        organization_id: int,
        force_refresh: bool = False
    ) -> Tuple[List[ConnectorEmailResult], int]:
        """Process a batch of connectors for email enrichment"""

        results = []
        cache_hits = 0

        # Check cache first (if not forcing refresh)
        if not force_refresh:
            connectors, cached_results, cache_hit_count = await self._check_email_cache(
                connectors, organization_id
            )
            results.extend(cached_results)
            cache_hits = cache_hit_count

        if not connectors:
            return results, cache_hits

        # Process each connector with multi-provider strategy
        for connector in connectors:
            result = await self._enrich_single_connector_multiProvider(
                connector, organization_id
            )
            results.append(result)

            # Update connector in database
            await self._update_connector_email(result)

            # Cache the result
            await self._cache_email_result(result, organization_id)

            # Rate limiting between individual lookups
            await asyncio.sleep(0.5)

        return results, cache_hits

    async def _enrich_single_connector_multiProvider(
        self,
        connector: Dict[str, Any],
        organization_id: int
    ) -> ConnectorEmailResult:
        """Enrich single connector using multi-provider strategy"""

        start_time = time.time()

        # Extract name components and company info
        full_name = connector.get('full_name', '')
        name_parts = full_name.split() if full_name else []
        first_name = name_parts[0] if name_parts else ''
        last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
        company = connector.get('company', '')

        try:
            result = await self._try_cufinder(first_name, last_name, company, connector)
        except Exception as exc:
            logger.warning(f"CUFinder lookup failed for {full_name}: {exc}")
            return ConnectorEmailResult(
                connector_id=connector['connector_id'],
                prospect_connector_id=connector['prospect_connector_id'],
                email=None,
                confidence=0.0,
                source='cufinder',
                status=EmailDiscoveryStatus.FAILED,
                cost_usd=0.0,
                processing_time_seconds=time.time() - start_time,
                error_message=str(exc),
            )

        if result.email and result.confidence >= self.min_confidence_threshold:
            logger.info(f"Found email via CUFinder: {result.email} (confidence: {result.confidence})")
            return result

        # Return whatever CUFinder produced (could be low confidence or empty)
        return result

    async def _try_cufinder(
        self,
        first_name: str,
        last_name: str,
        company: str,
        connector: Dict[str, Any]
    ) -> ConnectorEmailResult:
        """Try CUFinder email discovery"""

        enrichment_result = await self.cufinder_client.enrich_email(
            linkedin_url=connector.get('linkedin_url', ''),
            full_name=" ".join(filter(None, [first_name, last_name])) or connector.get('name'),
            company=company,
            company_domain=connector.get('company_domain'),
            title=connector.get('title'),
        )

        if enrichment_result.email:
            status = EmailDiscoveryStatus.COMPLETED
        elif enrichment_result.status == EnrichmentStatus.CONFIGURATION_REQUIRED:
            status = EmailDiscoveryStatus.FAILED
        else:
            status = EmailDiscoveryStatus.NO_EMAILS_FOUND

        return ConnectorEmailResult(
            connector_id=connector['connector_id'],
            prospect_connector_id=connector['prospect_connector_id'],
            email=enrichment_result.email,
            confidence=enrichment_result.confidence,
            source='cufinder',
            status=status,
            cost_usd=enrichment_result.cost,
            processing_time_seconds=0.5,
            error_message=enrichment_result.error_message,
        )

    # Legacy multi-provider stubs removed; CUFinder is the sole enrichment path.

    async def _check_email_cache(
        self,
        connectors: List[Dict[str, Any]],
        organization_id: int
    ) -> Tuple[List[Dict[str, Any]], List[ConnectorEmailResult], int]:
        """Check email cache for existing results"""

        from ..api.db_core import get_conn, query

        uncached_connectors = []
        cached_results = []
        cache_hits = 0

        with get_conn() as conn:
            for connector in connectors:
                # Check if we have a recent cache entry
                cached = query(conn, """
                    SELECT email, confidence, source, created_at
                    FROM email_cache
                    WHERE connector_id = ? AND organization_id = ?
                    AND created_at > datetime('now', '-{} days')
                """.format(self.cache_duration_days), (connector['connector_id'], organization_id))

                if cached:
                    cache_hits += 1
                    cache_entry = cached[0]

                    cached_result = ConnectorEmailResult(
                        connector_id=connector['connector_id'],
                        prospect_connector_id=connector['prospect_connector_id'],
                        email=cache_entry['email'],
                        confidence=cache_entry['confidence'] or 0.0,
                        source=f"{cache_entry['source']}_cached",
                        status=EmailDiscoveryStatus.COMPLETED if cache_entry['email'] else EmailDiscoveryStatus.NO_EMAILS_FOUND,
                        cost_usd=0.0,  # No cost for cached results
                        processing_time_seconds=0.0
                    )
                    cached_results.append(cached_result)
                else:
                    uncached_connectors.append(connector)

        logger.info(f"Email cache: {cache_hits} hits, {len(uncached_connectors)} misses")
        return uncached_connectors, cached_results, cache_hits

    async def _update_connector_email(self, result: ConnectorEmailResult):
        """Update connector with enrichment result"""

        from ..api.db_core import get_conn, execute

        try:
            with get_conn() as conn:
                execute(conn, """
                    UPDATE connectors SET
                        email = ?,
                        email_status = ?,
                        email_confidence = ?,
                        email_source = ?,
                        last_enriched_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    result.email,
                    'available' if result.email else 'unavailable',
                    result.confidence,
                    result.source,
                    result.connector_id
                ))

        except Exception as e:
            logger.error(f"Error updating connector {result.connector_id}: {e}")

    async def _cache_email_result(self, result: ConnectorEmailResult, organization_id: int):
        """Cache email enrichment result"""

        from ..api.db_core import get_conn, execute

        try:
            with get_conn() as conn:
                execute(conn, """
                    INSERT OR REPLACE INTO email_cache (
                        connector_id, organization_id, email, confidence,
                        source, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    result.connector_id, organization_id, result.email,
                    result.confidence, result.source, result.status.value
                ))

        except Exception as e:
            logger.error(f"Error caching email result: {e}")

    async def _check_email_quota(self, organization_id: int, requested_count: int) -> bool:
        """Check if organization has sufficient email enrichment quota"""

        from ..api.db_core import get_conn, query

        try:
            with get_conn() as conn:
                # Get organization's email quota from integration settings
                quota = query(conn, """
                    SELECT feature_flags
                    FROM integration_sets
                    WHERE organization_id = ?
                """, (organization_id,))

                if not quota:
                    return False

                feature_flags = json.loads(quota[0]['feature_flags'] or '{}')
                daily_quota = feature_flags.get('email_enrichment_quota', 100)

                # Check today's usage
                today_usage = query(conn, """
                    SELECT COUNT(*) as used_today
                    FROM email_cache
                    WHERE organization_id = ?
                    AND date(created_at) = date('now')
                    AND email IS NOT NULL
                """, (organization_id,))

                used_today = today_usage[0]['used_today'] if today_usage else 0

                return (used_today + requested_count) <= daily_quota

        except Exception as e:
            logger.error(f"Error checking email quota: {e}")
            return False

    async def _update_prospect_enrichment_status(
        self,
        prospect_id: int,
        organization_id: int,
        status: str
    ):
        """Update prospect status after enrichment"""

        from ..api.db_core import get_conn, execute

        try:
            with get_conn() as conn:
                execute(conn, """
                    UPDATE prospects
                    SET status = ?, processed_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND organization_id = ?
                """, (status, prospect_id, organization_id))

        except Exception as e:
            logger.error(f"Error updating prospect status: {e}")

    async def _create_enrichment_audit(
        self,
        organization_id: int,
        prospect_id: Optional[int],
        emails_found: int,
        cost: float
    ):
        """Create audit log for enrichment operation"""

        from ..api.db_core import get_conn, execute

        try:
            with get_conn() as conn:
                execute(conn, """
                    INSERT INTO audit_events (
                        organization_id, actor_type, actor_id, action,
                        target_type, target_id, payload, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    organization_id, "system", 0, "email_enrichment",
                    "prospect" if prospect_id else "organization",
                    prospect_id or organization_id,
                    json.dumps({"emails_found": emails_found, "cost_usd": cost})
                ))

        except Exception as e:
            logger.error(f"Error creating enrichment audit: {e}")

    def _create_quota_exceeded_result(
        self,
        organization_id: int,
        prospect_id: Optional[int],
        requested_count: int,
        start_time: float
    ) -> BatchEnrichmentResult:
        """Create result for quota exceeded scenario"""

        return BatchEnrichmentResult(
            organization_id=organization_id,
            prospect_id=prospect_id,
            total_connectors=requested_count,
            emails_found=0,
            high_confidence_emails=0,
            total_cost_usd=0.0,
            processing_time_seconds=time.time() - start_time,
            connector_results=[],
            cache_hit_rate=0.0
        )

    def _create_error_result(
        self,
        organization_id: int,
        prospect_id: Optional[int],
        error_message: str,
        start_time: float
    ) -> BatchEnrichmentResult:
        """Create result for error scenario"""

        return BatchEnrichmentResult(
            organization_id=organization_id,
            prospect_id=prospect_id,
            total_connectors=0,
            emails_found=0,
            high_confidence_emails=0,
            total_cost_usd=0.0,
            processing_time_seconds=time.time() - start_time,
            connector_results=[],
            cache_hit_rate=0.0
        )

    async def get_enrichment_stats(
        self,
        organization_id: int,
        days: int = 7
    ) -> Dict[str, Any]:
        """Get email enrichment statistics for organization"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            stats = query(conn, """
                SELECT
                    COUNT(*) as total_enrichments,
                    COUNT(CASE WHEN email IS NOT NULL THEN 1 END) as emails_found,
                    AVG(confidence) as avg_confidence,
                    SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END) as available_emails
                FROM email_cache
                WHERE organization_id = ?
                AND created_at >= datetime('now', '-{} days')
            """.format(days), (organization_id,))

            return dict(stats[0]) if stats else {}

# Global service instance
EmailEnrichmentService = CorporateEmailEnrichmentService
email_enrichment_service = CorporateEmailEnrichmentService()

# Database schema for email caching
EMAIL_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS email_cache (
    id SERIAL PRIMARY KEY,
    connector_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
    email VARCHAR(255),
    confidence DECIMAL(3,2),
    source VARCHAR(50),
    status VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT unique_connector_org UNIQUE(connector_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_email_cache_org ON email_cache(organization_id);
CREATE INDEX IF NOT EXISTS idx_email_cache_created ON email_cache(created_at);
CREATE INDEX IF NOT EXISTS idx_email_cache_status ON email_cache(status);
"""

# Backwards compatibility alias
EnrichmentResult = ConnectorEmailResult
