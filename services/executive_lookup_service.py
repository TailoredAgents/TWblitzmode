"""
Executive Lookup Service - Real API Integration for Executive Data Enrichment
September 2025 - Enterprise-Grade Prospect Intelligence

This service enriches prospect data with current executive information using multiple
API providers with intelligent fallback strategies, caching, and validation.

Features:
- Clearbit Person & Company API integration (primary)
- Apollo.io People API fallback (secondary)
- Intelligent caching with Redis (7-day TTL for positive results)
- Confidence scoring and validation
- Rate limiting and error handling
- Real-time job status tracking
- Comprehensive audit logging
"""

import asyncio
import json
import logging
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import traceback

import httpx
import asyncpg
from redis import Redis
import backoff

from core.settings import settings
from .audit_logging_service import audit_logger, AuditEventType, AuditSeverity

logger = logging.getLogger(__name__)

class LookupProvider(Enum):
    CLEARBIT = "clearbit"
    APOLLO = "apollo"
    MANUAL = "manual"

class LookupStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIALLY_COMPLETED = "partially_completed"

@dataclass
class ExecutiveData:
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None
    current_company: Optional[str] = None
    previous_companies: List[Dict] = None
    location: Optional[Dict] = None
    confidence_score: float = 0.0
    data_source: LookupProvider = LookupProvider.MANUAL

    def __post_init__(self):
        if self.previous_companies is None:
            self.previous_companies = []

@dataclass
class LookupJob:
    job_id: str
    tenant_id: str
    prospect_ids: List[str]
    status: LookupStatus
    total_prospects: int
    completed_prospects: int = 0
    failed_prospects: int = 0
    results: List[Dict] = None
    error_details: List[Dict] = None
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.results is None:
            self.results = []
        if self.error_details is None:
            self.error_details = []
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = datetime.now(timezone.utc)

class ExecutiveLookupService:
    def __init__(self,
                 database_url: Optional[str] = None,
                 redis_url: str = "redis://localhost:6379/0",
                 clearbit_api_key: Optional[str] = None,
                 apollo_api_key: Optional[str] = None):

        self.database_url = database_url or getattr(settings, 'DATABASE_URL', None) or settings.DATABASE_PATH
        self.redis = Redis.from_url(redis_url) if redis_url else None

        # API Configuration
        self.clearbit_api_key = clearbit_api_key
        self.apollo_api_key = apollo_api_key

        # API Endpoints
        self.clearbit_base_url = "https://person.clearbit.com"
        self.apollo_base_url = "https://api.apollo.io"

        # Rate limiting (requests per minute)
        self.clearbit_rate_limit = 100  # 100 requests/minute
        self.apollo_rate_limit = 300    # 300 requests/minute

        # Cache TTL settings
        self.cache_ttl_positive = 7 * 24 * 3600  # 7 days for found data
        self.cache_ttl_negative = 24 * 3600      # 1 day for not found

        # Confidence thresholds
        self.min_confidence_threshold = 0.7
        self.executive_title_keywords = [
            'ceo', 'chief executive', 'president', 'founder', 'co-founder',
            'cmo', 'chief marketing', 'vp marketing', 'vice president marketing',
            'cto', 'chief technology', 'vp engineering', 'head of engineering',
            'cfo', 'chief financial', 'vp finance', 'head of finance',
            'head of', 'vice president', 'vp ', 'director', 'senior director'
        ]

    async def enrich_prospects_batch(self,
                                   tenant_id: str,
                                   prospect_ids: List[str]) -> str:
        """
        Enrich a batch of prospects with executive data
        Returns job_id for tracking progress
        """
        job_id = f"lookup_{secrets.token_urlsafe(16)}"

        try:
            # Create lookup job
            lookup_job = LookupJob(
                job_id=job_id,
                tenant_id=tenant_id,
                prospect_ids=prospect_ids,
                status=LookupStatus.PENDING,
                total_prospects=len(prospect_ids)
            )

            # Store job in database
            await self._store_lookup_job(lookup_job)

            # Start async processing
            asyncio.create_task(self._process_lookup_batch(lookup_job))

            await audit_logger.log_event(
                tenant_id=tenant_id,
                event_type=AuditEventType.DATA_ENRICHMENT,
                action="executive_lookup_batch_started",
                resource_type="prospect",
                details={
                    "job_id": job_id,
                    "prospect_count": len(prospect_ids)
                },
                severity=AuditSeverity.LOW
            )

            logger.info(f"Started executive lookup batch job {job_id} for {len(prospect_ids)} prospects")
            return job_id

        except Exception as e:
            logger.error(f"Failed to start executive lookup batch: {e}")
            await audit_logger.log_event(
                tenant_id=tenant_id,
                event_type=AuditEventType.SYSTEM_ERROR,
                action="executive_lookup_batch_failed",
                resource_type="prospect",
                details={"error": str(e), "prospect_ids": prospect_ids},
                severity=AuditSeverity.HIGH
            )
            raise

    async def _process_lookup_batch(self, lookup_job: LookupJob):
        """Process executive lookup for a batch of prospects"""

        try:
            # Update job status
            lookup_job.status = LookupStatus.IN_PROGRESS
            await self._update_lookup_job(lookup_job)

            # Process prospects concurrently (max 5 at a time)
            semaphore = asyncio.Semaphore(5)
            tasks = []

            for prospect_id in lookup_job.prospect_ids:
                task = asyncio.create_task(
                    self._process_single_prospect(semaphore, lookup_job, prospect_id)
                )
                tasks.append(task)

            # Wait for all tasks to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for i, result in enumerate(results):
                prospect_id = lookup_job.prospect_ids[i]

                if isinstance(result, Exception):
                    lookup_job.failed_prospects += 1
                    lookup_job.error_details.append({
                        "prospect_id": prospect_id,
                        "error": str(result),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                else:
                    lookup_job.completed_prospects += 1
                    lookup_job.results.append(result)

            # Determine final status
            if lookup_job.failed_prospects == 0:
                lookup_job.status = LookupStatus.COMPLETED
            elif lookup_job.completed_prospects == 0:
                lookup_job.status = LookupStatus.FAILED
            else:
                lookup_job.status = LookupStatus.PARTIALLY_COMPLETED

            lookup_job.updated_at = datetime.now(timezone.utc)
            await self._update_lookup_job(lookup_job)

            # Log completion
            await audit_logger.log_event(
                tenant_id=lookup_job.tenant_id,
                event_type=AuditEventType.DATA_ENRICHMENT,
                action="executive_lookup_batch_completed",
                resource_type="prospect",
                details={
                    "job_id": lookup_job.job_id,
                    "total_prospects": lookup_job.total_prospects,
                    "completed": lookup_job.completed_prospects,
                    "failed": lookup_job.failed_prospects,
                    "status": lookup_job.status.value
                },
                severity=AuditSeverity.MEDIUM if lookup_job.failed_prospects > 0 else AuditSeverity.LOW
            )

            logger.info(f"Completed executive lookup job {lookup_job.job_id}: "
                       f"{lookup_job.completed_prospects}/{lookup_job.total_prospects} successful")

        except Exception as e:
            lookup_job.status = LookupStatus.FAILED
            lookup_job.updated_at = datetime.now(timezone.utc)
            await self._update_lookup_job(lookup_job)

            logger.error(f"Executive lookup batch job {lookup_job.job_id} failed: {e}")
            raise

    async def _process_single_prospect(self,
                                     semaphore: asyncio.Semaphore,
                                     lookup_job: LookupJob,
                                     prospect_id: str) -> Dict:
        """Process executive lookup for a single prospect"""

        async with semaphore:
            try:
                # Get prospect data from database
                prospect = await self._get_prospect_data(lookup_job.tenant_id, prospect_id)
                if not prospect:
                    raise ValueError(f"Prospect {prospect_id} not found")

                # Check cache first
                cached_result = await self._get_cached_lookup(prospect)
                if cached_result:
                    await self._update_prospect_data(lookup_job.tenant_id, prospect_id, cached_result)
                    return {
                        "prospect_id": prospect_id,
                        "status": "completed",
                        "data_source": "cache",
                        "executive_data": asdict(cached_result)
                    }

                # Perform lookup using APIs
                executive_data = await self._lookup_executive_data(prospect)

                if executive_data:
                    # Cache the result
                    await self._cache_lookup_result(prospect, executive_data)

                    # Update prospect in database
                    await self._update_prospect_data(lookup_job.tenant_id, prospect_id, executive_data)

                    return {
                        "prospect_id": prospect_id,
                        "status": "completed",
                        "data_source": executive_data.data_source.value,
                        "confidence_score": executive_data.confidence_score,
                        "executive_data": asdict(executive_data)
                    }
                else:
                    # Cache negative result
                    await self._cache_negative_result(prospect)

                    return {
                        "prospect_id": prospect_id,
                        "status": "not_found",
                        "message": "No executive data found"
                    }

            except Exception as e:
                logger.error(f"Failed to process prospect {prospect_id}: {e}")
                return {
                    "prospect_id": prospect_id,
                    "status": "failed",
                    "error": str(e)
                }

    async def _lookup_executive_data(self, prospect: Dict) -> Optional[ExecutiveData]:
        """
        Lookup executive data using multiple API providers with fallback strategy
        """

        company = prospect.get('company', '')
        full_name = prospect.get('full_name', '')

        if not company or not full_name:
            logger.warning(f"Insufficient data for lookup: company={company}, name={full_name}")
            return None

        # Try Clearbit first (primary provider)
        if self.clearbit_api_key:
            try:
                executive_data = await self._lookup_with_clearbit(company, full_name)
                if executive_data and executive_data.confidence_score >= self.min_confidence_threshold:
                    return executive_data
            except Exception as e:
                logger.warning(f"Clearbit lookup failed for {full_name} at {company}: {e}")

        # Fallback to Apollo (secondary provider)
        if self.apollo_api_key:
            try:
                executive_data = await self._lookup_with_apollo(company, full_name)
                if executive_data and executive_data.confidence_score >= self.min_confidence_threshold:
                    return executive_data
            except Exception as e:
                logger.warning(f"Apollo lookup failed for {full_name} at {company}: {e}")

        logger.info(f"No high-confidence executive data found for {full_name} at {company}")
        return None

    @backoff.on_exception(backoff.expo, httpx.HTTPError, max_tries=3)
    async def _lookup_with_clearbit(self, company: str, full_name: str) -> Optional[ExecutiveData]:
        """
        Lookup executive data using Clearbit Person API
        """

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Construct email domain from company name
            company_domain = await self._guess_company_domain(company)

            # Try multiple email formats
            email_formats = self._generate_email_formats(full_name, company_domain)

            for email in email_formats:
                try:
                    response = await client.get(
                        f"{self.clearbit_base_url}/v1/people/find",
                        params={"email": email},
                        auth=(self.clearbit_api_key, ""),
                        headers={"User-Agent": "VouchLink-AI/1.0"}
                    )

                    if response.status_code == 200:
                        data = response.json()
                        executive_data = self._parse_clearbit_response(data, company, full_name)
                        if executive_data:
                            return executive_data
                    elif response.status_code == 202:
                        # Clearbit is looking up the person, wait and retry
                        await asyncio.sleep(2)
                        continue
                    elif response.status_code != 404:
                        # Log unexpected errors but continue
                        logger.warning(f"Clearbit API error {response.status_code}: {response.text}")

                except httpx.HTTPError as e:
                    logger.warning(f"Clearbit request failed: {e}")
                    continue

            return None

    @backoff.on_exception(backoff.expo, httpx.HTTPError, max_tries=3)
    async def _lookup_with_apollo(self, company: str, full_name: str) -> Optional[ExecutiveData]:
        """
        Lookup executive data using Apollo.io People API
        """

        first_name, last_name = self._split_name(full_name)

        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "api_key": self.apollo_api_key,
                "first_name": first_name,
                "last_name": last_name,
                "organization_name": company,
                "person_titles": ["CEO", "Chief Executive Officer", "President", "Founder", "Co-Founder"]
            }

            try:
                response = await client.post(
                    f"{self.apollo_base_url}/v1/mixed_people/search",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "VouchLink-AI/1.0"
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    return self._parse_apollo_response(data, company, full_name)
                else:
                    logger.warning(f"Apollo API error {response.status_code}: {response.text}")
                    return None

            except httpx.HTTPError as e:
                logger.warning(f"Apollo request failed: {e}")
                return None

    def _parse_clearbit_response(self, data: Dict, company: str, full_name: str) -> Optional[ExecutiveData]:
        """Parse Clearbit API response into ExecutiveData"""

        try:
            person = data.get('person', {})
            employment = data.get('company', {})

            # Validate that this is the right person
            api_name = f"{person.get('name', {}).get('givenName', '')} {person.get('name', {}).get('familyName', '')}".strip()
            api_company = employment.get('name', '')

            confidence_score = self._calculate_confidence_score(
                full_name, api_name, company, api_company
            )

            if confidence_score < self.min_confidence_threshold:
                return None

            # Check if this person has an executive title
            title = person.get('employment', {}).get('title', '')
            if not self._is_executive_title(title):
                logger.info(f"Person found but not an executive: {title}")
                return None

            executive_data = ExecutiveData(
                full_name=api_name or full_name,
                first_name=person.get('name', {}).get('givenName'),
                last_name=person.get('name', {}).get('familyName'),
                title=title,
                linkedin_url=person.get('linkedin', {}).get('handle'),
                email=person.get('email'),
                current_company=api_company or company,
                location={
                    'city': person.get('location'),
                    'country': person.get('geo', {}).get('country')
                },
                confidence_score=confidence_score,
                data_source=LookupProvider.CLEARBIT
            )

            return executive_data

        except Exception as e:
            logger.error(f"Error parsing Clearbit response: {e}")
            return None

    def _parse_apollo_response(self, data: Dict, company: str, full_name: str) -> Optional[ExecutiveData]:
        """Parse Apollo API response into ExecutiveData"""

        try:
            people = data.get('people', [])
            if not people:
                return None

            # Find the best match
            best_match = None
            best_confidence = 0

            for person in people:
                api_name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
                api_company = person.get('organization', {}).get('name', '')

                confidence_score = self._calculate_confidence_score(
                    full_name, api_name, company, api_company
                )

                if confidence_score > best_confidence and confidence_score >= self.min_confidence_threshold:
                    # Check if this person has an executive title
                    title = person.get('title', '')
                    if self._is_executive_title(title):
                        best_match = person
                        best_confidence = confidence_score

            if not best_match:
                return None

            executive_data = ExecutiveData(
                full_name=f"{best_match.get('first_name', '')} {best_match.get('last_name', '')}".strip(),
                first_name=best_match.get('first_name'),
                last_name=best_match.get('last_name'),
                title=best_match.get('title'),
                linkedin_url=best_match.get('linkedin_url'),
                email=best_match.get('email'),
                current_company=best_match.get('organization', {}).get('name', company),
                location={
                    'city': best_match.get('city'),
                    'state': best_match.get('state'),
                    'country': best_match.get('country')
                },
                confidence_score=best_confidence,
                data_source=LookupProvider.APOLLO
            )

            return executive_data

        except Exception as e:
            logger.error(f"Error parsing Apollo response: {e}")
            return None

    def _calculate_confidence_score(self,
                                  expected_name: str,
                                  api_name: str,
                                  expected_company: str,
                                  api_company: str) -> float:
        """
        Calculate confidence score for API response match

        Score components:
        - Name similarity: 0.6 weight
        - Company similarity: 0.4 weight
        """

        name_similarity = self._calculate_string_similarity(
            expected_name.lower(), api_name.lower()
        )

        company_similarity = self._calculate_string_similarity(
            expected_company.lower(), api_company.lower()
        )

        confidence_score = (0.6 * name_similarity) + (0.4 * company_similarity)
        return min(confidence_score, 1.0)

    def _calculate_string_similarity(self, str1: str, str2: str) -> float:
        """Calculate similarity between two strings using Jaccard similarity"""

        if not str1 or not str2:
            return 0.0

        # Convert to sets of words
        words1 = set(str1.split())
        words2 = set(str2.split())

        if not words1 or not words2:
            return 0.0

        # Calculate Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))

        return intersection / union if union > 0 else 0.0

    def _is_executive_title(self, title: str) -> bool:
        """Check if a title indicates an executive-level position"""

        if not title:
            return False

        title_lower = title.lower()
        return any(keyword in title_lower for keyword in self.executive_title_keywords)

    def _split_name(self, full_name: str) -> Tuple[str, str]:
        """Split full name into first and last name"""

        name_parts = full_name.strip().split()
        if len(name_parts) >= 2:
            return name_parts[0], ' '.join(name_parts[1:])
        elif len(name_parts) == 1:
            return name_parts[0], ''
        else:
            return '', ''

    def _generate_email_formats(self, full_name: str, domain: str) -> List[str]:
        """Generate possible email formats for a person"""

        first_name, last_name = self._split_name(full_name)
        first_name = first_name.lower()
        last_name = last_name.lower()

        formats = []
        if first_name and last_name and domain:
            formats.extend([
                f"{first_name}.{last_name}@{domain}",
                f"{first_name}@{domain}",
                f"{last_name}@{domain}",
                f"{first_name[0]}{last_name}@{domain}",
                f"{first_name}{last_name}@{domain}",
                f"{first_name}_{last_name}@{domain}"
            ])

        return formats

    async def _guess_company_domain(self, company: str) -> str:
        """Guess company domain from company name"""

        # Simple domain guessing - in production, use a more sophisticated approach
        company_clean = company.lower().replace(' ', '').replace('.', '').replace(',', '')

        # Remove common suffixes
        suffixes = ['inc', 'corp', 'corporation', 'llc', 'ltd', 'limited', 'company', 'co']
        for suffix in suffixes:
            if company_clean.endswith(suffix):
                company_clean = company_clean[:-len(suffix)]

        return f"{company_clean}.com"

    # Cache management methods
    async def _get_cached_lookup(self, prospect: Dict) -> Optional[ExecutiveData]:
        """Get cached lookup result for prospect"""

        if not self.redis:
            return None

        cache_key = self._generate_cache_key(prospect)

        try:
            cached_data = self.redis.get(cache_key)
            if cached_data:
                data = json.loads(cached_data)
                if data.get('status') == 'found':
                    return ExecutiveData(**data['executive_data'])
                else:
                    # Negative cache hit
                    return None
        except Exception as e:
            logger.warning(f"Cache read error: {e}")

        return None

    async def _cache_lookup_result(self, prospect: Dict, executive_data: ExecutiveData):
        """Cache positive lookup result"""

        if not self.redis:
            return

        cache_key = self._generate_cache_key(prospect)
        cache_data = {
            'status': 'found',
            'executive_data': asdict(executive_data),
            'cached_at': datetime.now(timezone.utc).isoformat()
        }

        try:
            self.redis.setex(
                cache_key,
                self.cache_ttl_positive,
                json.dumps(cache_data, default=str)
            )
        except Exception as e:
            logger.warning(f"Cache write error: {e}")

    async def _cache_negative_result(self, prospect: Dict):
        """Cache negative lookup result"""

        if not self.redis:
            return

        cache_key = self._generate_cache_key(prospect)
        cache_data = {
            'status': 'not_found',
            'cached_at': datetime.now(timezone.utc).isoformat()
        }

        try:
            self.redis.setex(
                cache_key,
                self.cache_ttl_negative,
                json.dumps(cache_data, default=str)
            )
        except Exception as e:
            logger.warning(f"Cache write error: {e}")

    def _generate_cache_key(self, prospect: Dict) -> str:
        """Generate cache key for prospect lookup"""

        company = prospect.get('company', '').lower().strip()
        full_name = prospect.get('full_name', '').lower().strip()

        # Create a hash of company + name for cache key
        cache_string = f"{company}:{full_name}"
        cache_hash = hashlib.md5(cache_string.encode()).hexdigest()

        return f"executive_lookup:{cache_hash}"

    # Database operations
    async def _get_prospect_data(self, tenant_id: str, prospect_id: str) -> Optional[Dict]:
        """Get prospect data from database"""

        async with asyncpg.connect(self.database_url) as conn:
            row = await conn.fetchrow("""
                SELECT id, company, full_name, first_name, last_name, title, email
                FROM prospects
                WHERE id = $1 AND organization_id = $2
            """, prospect_id, tenant_id)

            return dict(row) if row else None

    async def _update_prospect_data(self, tenant_id: str, prospect_id: str, executive_data: ExecutiveData):
        """Update prospect with enriched executive data"""

        async with asyncpg.connect(self.database_url) as conn:
            await conn.execute("""
                UPDATE prospects SET
                    first_name = $3,
                    last_name = $4,
                    title = $5,
                    linkedin_url = $6,
                    email = COALESCE($7, email),
                    current_company = $8,
                    lookup_confidence_score = $9,
                    status = 'ready_for_mutuals',
                    updated_at = NOW()
                WHERE id = $1 AND organization_id = $2
            """, prospect_id, tenant_id, executive_data.first_name, executive_data.last_name,
                executive_data.title, executive_data.linkedin_url, executive_data.email,
                executive_data.current_company, executive_data.confidence_score)

    async def _store_lookup_job(self, lookup_job: LookupJob):
        """Store lookup job in database"""

        async with asyncpg.connect(self.database_url) as conn:
            await conn.execute("""
                INSERT INTO executive_lookup_jobs (
                    job_id, tenant_id, prospect_ids, status, total_prospects,
                    completed_prospects, failed_prospects, results, error_details,
                    created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """, lookup_job.job_id, lookup_job.tenant_id, lookup_job.prospect_ids,
                lookup_job.status.value, lookup_job.total_prospects,
                lookup_job.completed_prospects, lookup_job.failed_prospects,
                json.dumps(lookup_job.results, default=str),
                json.dumps(lookup_job.error_details, default=str),
                lookup_job.created_at, lookup_job.updated_at)

    async def _update_lookup_job(self, lookup_job: LookupJob):
        """Update lookup job in database"""

        async with asyncpg.connect(self.database_url) as conn:
            await conn.execute("""
                UPDATE executive_lookup_jobs SET
                    status = $2,
                    completed_prospects = $3,
                    failed_prospects = $4,
                    results = $5,
                    error_details = $6,
                    updated_at = $7
                WHERE job_id = $1
            """, lookup_job.job_id, lookup_job.status.value,
                lookup_job.completed_prospects, lookup_job.failed_prospects,
                json.dumps(lookup_job.results, default=str),
                json.dumps(lookup_job.error_details, default=str),
                lookup_job.updated_at)

    # Public API methods
    async def get_job_status(self, job_id: str, tenant_id: str) -> Optional[Dict]:
        """Get lookup job status"""

        async with asyncpg.connect(self.database_url) as conn:
            row = await conn.fetchrow("""
                SELECT * FROM executive_lookup_jobs
                WHERE job_id = $1 AND tenant_id = $2
            """, job_id, tenant_id)

            if row:
                return {
                    "job_id": row['job_id'],
                    "status": row['status'],
                    "total_prospects": row['total_prospects'],
                    "completed_prospects": row['completed_prospects'],
                    "failed_prospects": row['failed_prospects'],
                    "created_at": row['created_at'].isoformat(),
                    "updated_at": row['updated_at'].isoformat(),
                    "results_count": len(json.loads(row['results'])) if row['results'] else 0,
                    "errors_count": len(json.loads(row['error_details'])) if row['error_details'] else 0
                }

        return None

    async def validate_prospect_data(self,
                                   company: str,
                                   full_name: str) -> Dict[str, Any]:
        """
        Validate prospect data and provide confidence assessment
        Returns validation result with confidence score
        """

        try:
            # Check cache first
            prospect_data = {"company": company, "full_name": full_name}
            cached_result = await self._get_cached_lookup(prospect_data)

            if cached_result:
                return {
                    "status": "valid",
                    "confidence_score": cached_result.confidence_score,
                    "executive_data": asdict(cached_result),
                    "data_source": "cache"
                }

            # Perform real-time lookup (single prospect)
            executive_data = await self._lookup_executive_data(prospect_data)

            if executive_data:
                # Cache the result
                await self._cache_lookup_result(prospect_data, executive_data)

                return {
                    "status": "valid",
                    "confidence_score": executive_data.confidence_score,
                    "executive_data": asdict(executive_data),
                    "data_source": executive_data.data_source.value
                }
            else:
                # Cache negative result
                await self._cache_negative_result(prospect_data)

                return {
                    "status": "not_found",
                    "confidence_score": 0.0,
                    "message": "No executive data found"
                }

        except Exception as e:
            logger.error(f"Prospect validation failed: {e}")
            return {
                "status": "error",
                "confidence_score": 0.0,
                "error": str(e)
            }

    async def lookup_executive(
        self,
        company: str,
        executive_name: str,
        organization_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Optional[ExecutiveData]:
        """
        Lightweight lookup used by real-time workflows.

        Attempts cache-first resolution, falls back to live provider lookup,
        and records negative results to avoid repeated calls.
        """

        prospect = {
            "company": company,
            "full_name": executive_name,
            "organization_id": organization_id,
            "tenant_id": tenant_id or organization_id
        }

        try:
            cached = await self._get_cached_lookup(prospect)
            if cached:
                return cached

            executive_data = await self._lookup_executive_data(prospect)
            if executive_data:
                await self._cache_lookup_result(prospect, executive_data)
                return executive_data

            await self._cache_negative_result(prospect)
            return None

        except Exception as exc:
            logger.error(
                "Real-time executive lookup failed for %s at %s: %s",
                executive_name,
                company,
                exc
            )
            return None

    async def get_cache_stats(self, tenant_id: str) -> Dict[str, Any]:
        """Get cache statistics for monitoring"""

        if not self.redis:
            return {"cache_enabled": False}

        try:
            # Get cache keys related to this tenant (approximation)
            cache_keys = self.redis.keys("executive_lookup:*")

            total_keys = len(cache_keys)
            positive_hits = 0
            negative_hits = 0

            # Sample some keys to get hit ratio
            sample_size = min(100, total_keys)
            sample_keys = cache_keys[:sample_size] if cache_keys else []

            for key in sample_keys:
                try:
                    data = json.loads(self.redis.get(key))
                    if data.get('status') == 'found':
                        positive_hits += 1
                    else:
                        negative_hits += 1
                except:
                    continue

            return {
                "cache_enabled": True,
                "total_cached_entries": total_keys,
                "sample_size": sample_size,
                "positive_hit_ratio": positive_hits / sample_size if sample_size > 0 else 0,
                "negative_hit_ratio": negative_hits / sample_size if sample_size > 0 else 0,
                "cache_ttl_positive_days": self.cache_ttl_positive // 86400,
                "cache_ttl_negative_hours": self.cache_ttl_negative // 3600
            }
        except Exception as e:
            logger.error(f"Cache stats error: {e}")
            return {"cache_enabled": True, "error": str(e)}

    async def health_check(self) -> Dict[str, Any]:
        """Health check for executive lookup service"""

        health_status = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "providers": {},
            "cache": {},
            "database": {}
        }

        # Check API providers
        if self.clearbit_api_key:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(
                        f"{self.clearbit_base_url}/v1/people/find",
                        params={"email": "test@example.com"},
                        auth=(self.clearbit_api_key, "")
                    )
                    health_status["providers"]["clearbit"] = {
                        "status": "available",
                        "response_time_ms": response.elapsed.total_seconds() * 1000
                    }
            except Exception as e:
                health_status["providers"]["clearbit"] = {
                    "status": "unavailable",
                    "error": str(e)
                }
        else:
            health_status["providers"]["clearbit"] = {"status": "not_configured"}

        if self.apollo_api_key:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(
                        f"{self.apollo_base_url}/v1/mixed_people/search",
                        json={"api_key": self.apollo_api_key, "first_name": "Test"},
                        headers={"Content-Type": "application/json"}
                    )
                    health_status["providers"]["apollo"] = {
                        "status": "available",
                        "response_time_ms": response.elapsed.total_seconds() * 1000
                    }
            except Exception as e:
                health_status["providers"]["apollo"] = {
                    "status": "unavailable",
                    "error": str(e)
                }
        else:
            health_status["providers"]["apollo"] = {"status": "not_configured"}

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
            async with asyncpg.connect(self.database_url) as conn:
                await conn.fetchval("SELECT 1")
            health_status["database"] = {"status": "available"}
        except Exception as e:
            health_status["database"] = {"status": "unavailable", "error": str(e)}
            health_status["status"] = "degraded"

        # Determine overall status
        provider_issues = sum(1 for p in health_status["providers"].values()
                            if p.get("status") != "available")

        if health_status["database"]["status"] != "available":
            health_status["status"] = "unhealthy"
        elif provider_issues == len(health_status["providers"]):
            health_status["status"] = "degraded"

        return health_status


# Global service instance
executive_lookup_service = ExecutiveLookupService(
    database_url="",  # Will be set by configuration
    redis_url="redis://localhost:6379/0"
)

# Backwards compatibility alias
LookupResult = ExecutiveData