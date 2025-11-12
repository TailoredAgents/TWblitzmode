"""
CUFinder.io Email Enrichment Client
Production-ready integration for B2B email discovery
"""

import httpx
import asyncio
import logging
import time
from collections import deque
from threading import Lock
from typing import Optional, Dict, List, Deque, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from core.settings import settings
from services.error_classifier import error_classifier
from api.mt_db import get_db

logger = logging.getLogger(__name__)

_PENDING_REQUESTS: Dict[str, Deque[Dict[str, Optional[str]]]] = {}
_PENDING_REQUESTS_LOCK = Lock()


def _queue_key(tenant_id: Optional[int]) -> str:
    return str(tenant_id) if tenant_id is not None else "global"


def _record_pending_request(tenant_id: Optional[int], payload: Dict[str, Any]) -> None:
    """Persist a sanitized snapshot of a deferred enrichment request for auditing."""
    entry = {
        "requested_at": datetime.utcnow().isoformat() + "Z",
        "tenant_id": tenant_id,
        "full_name": payload.get("full_name") or payload.get("name"),
        "company": payload.get("company"),
        "domain": payload.get("domain"),
        "note": payload.get("note", "cufinder_disabled"),
    }
    key = _queue_key(tenant_id)
    with _PENDING_REQUESTS_LOCK:
        queue = _PENDING_REQUESTS.setdefault(key, deque(maxlen=200))
        queue.appendleft(entry)


def get_deferred_cufinder_requests(tenant_id: Optional[int]) -> Dict[str, Any]:
    """Return pending CUFinder requests for health dashboards."""
    key = _queue_key(tenant_id)
    with _PENDING_REQUESTS_LOCK:
        queue = list(_PENDING_REQUESTS.get(key, []))
    latest = queue[0] if queue else None
    return {
        "pending": len(queue),
        "latest": latest,
    }


def clear_deferred_cufinder_requests(tenant_id: Optional[int] = None) -> None:
    """Clear buffered pending requests (primarily for tests)."""
    with _PENDING_REQUESTS_LOCK:
        if tenant_id is None:
            _PENDING_REQUESTS.clear()
        else:
            _PENDING_REQUESTS.pop(_queue_key(tenant_id), None)


class CUFinderConfigurationError(RuntimeError):
    """Raised when CUFinder is not configured for the active tenant."""

    def __init__(self, message: str, tenant_id: Optional[int] = None):
        super().__init__(message)
        self.tenant_id = tenant_id

class EnrichmentStatus(Enum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    INVALID_INPUT = "invalid_input"
    API_ERROR = "api_error"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    CONFIGURATION_REQUIRED = "configuration_required"

@dataclass
class EmailEnrichmentResult:
    email: Optional[str] = None
    confidence: float = 0.0
    status: EnrichmentStatus = EnrichmentStatus.NOT_FOUND
    source: str = "cufinder"
    verified_at: Optional[datetime] = None
    company_domain: Optional[str] = None
    role: Optional[str] = None
    seniority: Optional[str] = None
    department: Optional[str] = None
    error_message: Optional[str] = None
    credits_used: int = 1
    cost: float = 0.03  # Add cost field expected by EmailService

class CircuitBreaker:
    """Circuit breaker pattern for API resilience"""
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half_open
        
    def is_open(self) -> bool:
        if self.state == "open":
            if self.last_failure_time and \
               (datetime.now() - self.last_failure_time).seconds > self.timeout:
                self.state = "half_open"
                return False
            return True
        return False
    
    def record_success(self):
        self.failures = 0
        self.state = "closed"
        
    def record_failure(self):
        self.failures += 1
        self.last_failure_time = datetime.now()
        if self.failures >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failures} failures")

class CUFinderClient:
    """
    CUFinder.io API client for email enrichment
    Docs: https://apidoc.cufinder.io/
    """
    
    BASE_URL = "https://api.cufinder.io/v2"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        tenant_id: Optional[int] = None,
        fail_on_missing: bool = False,
    ):
        self.api_key = (api_key or self._get_api_key_for_tenant(tenant_id) or "").strip()
        self.tenant_id = tenant_id
        self.circuit_breaker = CircuitBreaker()
        self.disabled_reason: Optional[str] = None
        self.fail_on_missing = fail_on_missing
        self._pending_queue_key = _queue_key(tenant_id)
        self.base_url = self._get_base_url_for_tenant(tenant_id)
        self.client: Optional[httpx.AsyncClient] = None
        
        # Validate API key before creating client
        if not self.api_key:
            env_hint = "environment variables" if tenant_id is None else "tenant settings"
            self.disabled_reason = (
                "CUFinder email enrichment is disabled: configure a CUFinder API key "
                f"in {env_hint} to enable automated enrichment."
            )
            logger.warning(
                "⚠️ [CUFINDER AUTH] Missing API key; email enrichment operating in degraded mode "
                f"for tenant {tenant_id or 'default environment'}"
            )
            if fail_on_missing:
                raise CUFinderConfigurationError(self.disabled_reason, tenant_id=tenant_id)
        else:
            logger.info(f"✅ [CUFINDER AUTH] API key configured for tenant {tenant_id}: {len(self.api_key)} chars")
            self.client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json",
                    "User-Agent": "VouchLink-AI-AI-Agent/1.0"
                },
                timeout=httpx.Timeout(10.0),
                trust_env=False  # ignore system proxy env that can misroute requests
            )
        
        # Rate limiting
        self.last_request_time = None
        self.min_request_interval = 0.5  # 2 requests per second max
        
        # Cost tracking
        self.credits_used_today = 0
        self.daily_credit_limit = 1000  # Configurable per tenant

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def configuration_reason(self) -> Optional[str]:
        return self.disabled_reason

    def _handle_disabled_request(self, context: Dict[str, Any]) -> EmailEnrichmentResult:
        """Queue request metadata and surface a configuration-required result."""
        reason = self.disabled_reason or (
            "CUFinder email enrichment is disabled until an API key is configured."
        )
        context_payload = {
            "full_name": context.get("full_name"),
            "company": context.get("company"),
            "domain": context.get("company_domain") or context.get("domain"),
            "note": context.get("note", reason),
        }
        _record_pending_request(self.tenant_id, context_payload)

        if self.tenant_id:
            try:
                error_classifier.record_provider_error(
                    "cufinder",
                    "configuration_missing",
                    reason,
                    tenant_id=self.tenant_id,
                )
            except Exception as exc:
                logger.debug(f"Failed to record provider health for CUFinder: {exc}")

        return EmailEnrichmentResult(
            email=None,
            confidence=0.0,
            status=EnrichmentStatus.CONFIGURATION_REQUIRED,
            source="cufinder",
            error_message=reason,
            credits_used=0,
            cost=0.0,
        )
        
    def _get_base_url_for_tenant(self, tenant_id: Optional[int]) -> str:
        """Allow overriding CUFinder base URL via tenant integration settings (e.g., for region or proxy)."""
        try:
            if tenant_id:
                from integrations.apify_client import get_tenant_integration_settings
                integ = get_tenant_integration_settings(tenant_id)
                if isinstance(integ, dict):
                    base = integ.get('cufinder_base_url')
                    region = (integ.get('cufinder_region') or '').lower()
                    if base and isinstance(base, str) and base.startswith('http'):
                        logger.info(f"[CUFINDER BASE] Using tenant base URL: {base}")
                        return base.rstrip('/') + '/v2'
                    if region == 'eu':
                        # If CUFinder had regional hosts; keep default unless provided
                        logger.info("[CUFINDER BASE] Region EU specified; using default host unless override provided")
            # Default
            return self.BASE_URL
        except Exception as e:
            logger.warning(f"[CUFINDER BASE] Failed to resolve base URL; using default: {e}")
            return self.BASE_URL

    def _get_api_key_for_tenant(self, tenant_id: int) -> str:
        """Get tenant-specific API key from database with enhanced error handling"""
        if not tenant_id:
            import os
            fallback_key = os.getenv('CUFINDER_API_KEY', '')
            logger.info(f"🔍 [CUFINDER AUTH] No tenant_id provided, using environment fallback: {'configured' if fallback_key else 'not configured'}")
            return fallback_key
            
        try:
            logger.info(f"🔍 [CUFINDER AUTH] Retrieving API key for tenant {tenant_id}")
            from integrations.apify_client import get_tenant_integration_settings
            settings = get_tenant_integration_settings(tenant_id)
            
            logger.info(f"🔍 [CUFINDER AUTH] Retrieved {len(settings)} settings for tenant {tenant_id}")
            logger.info(f"🔍 [CUFINDER AUTH] Available setting keys: {list(settings.keys())}")
            
            tenant_key = settings.get('cufinder_api_key', '')
            
            if tenant_key and tenant_key.strip():
                logger.info(f"✅ [CUFINDER AUTH] Tenant-specific key found: {len(tenant_key)} chars")
                return tenant_key
            else:
                logger.warning(f"⚠️ [CUFINDER AUTH] No tenant-specific key found, trying environment fallback")
                import os
                fallback_key = os.getenv('CUFINDER_API_KEY', '')
                if fallback_key:
                    logger.info(f"✅ [CUFINDER AUTH] Environment fallback found: {len(fallback_key)} chars")
                else:
                    logger.error(f"❌ [CUFINDER AUTH] No API key available in tenant settings or environment")
                return fallback_key
                
        except Exception as e:
            logger.error(f"❌ [CUFINDER AUTH] Failed to retrieve tenant settings: {e}")
            import os
            fallback_key = os.getenv('CUFINDER_API_KEY', '')
            logger.info(f"🔧 [CUFINDER AUTH] Using environment fallback: {'configured' if fallback_key else 'not configured'}")
            return fallback_key
    
    def enrich_contact_email(
        self,
        linkedin_url: Optional[str] = None,
        full_name: Optional[str] = None,
        company: Optional[str] = None,
        company_domain: Optional[str] = None,
        title: Optional[str] = None
    ) -> EmailEnrichmentResult:
        """
        Synchronous version of email enrichment for backward compatibility
        """
        if not self.is_configured:
            return self._handle_disabled_request(
                {
                    "full_name": full_name,
                    "company": company,
                    "company_domain": company_domain,
                    "note": "enrichment_skipped_missing_api_key",
                }
            )
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.enrich_email(
                linkedin_url=linkedin_url,
                full_name=full_name,
                company=company,
                company_domain=company_domain,
                title=title
            ))
        finally:
            loop.close()
    
    async def _rate_limit(self):
        """Implement async rate limiting"""
        if self.last_request_time:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.min_request_interval:
                await asyncio.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def _track_cost(self, credits: int = 1):
        """Track API usage costs"""
        if not self.tenant_id:
            return
            
        conn = get_db()
        cursor = conn.cursor()
        
        # Update daily costs
        cursor.execute("""
            INSERT INTO email_costs (tenant_id, date, service, operation, count, unit_cost, total_cost)
            VALUES (%s, %s, 'cufinder', 'enrichment', %s, 0.03, %s)
            ON CONFLICT(tenant_id, date, service, operation) DO UPDATE SET 
                count = email_costs.count + EXCLUDED.count,
                total_cost = email_costs.total_cost + EXCLUDED.total_cost
        """, (
            self.tenant_id,
            datetime.now().date(),
            credits,
            credits * 0.03  # $0.03 per credit estimate
        ))
        
        conn.commit()
        conn.close()
        
        self.credits_used_today += credits
        
        # Check daily limit
        if self.credits_used_today >= self.daily_credit_limit:
            logger.warning(f"Daily credit limit reached for tenant {self.tenant_id}")
    
    async def enrich_email(
        self,
        linkedin_url: Optional[str] = None,
        full_name: Optional[str] = None,
        company: Optional[str] = None,
        company_domain: Optional[str] = None,
        title: Optional[str] = None
    ) -> EmailEnrichmentResult:
        """
        Enrich contact with email using various data points
        Priority: LinkedIn URL > Name + Company Domain > Name + Company
        """

        if not self.is_configured:
            return self._handle_disabled_request(
                {
                    "full_name": full_name,
                    "company": company,
                    "company_domain": company_domain,
                    "note": "enrichment_skipped_missing_api_key",
                }
            )
        
        # Create cache key from available data
        cache_key_parts = []
        if linkedin_url:
            cache_key_parts.append(f"linkedin:{linkedin_url}")
        if full_name:
            cache_key_parts.append(f"name:{full_name}")
        if company:
            cache_key_parts.append(f"company:{company}")
        if company_domain:
            cache_key_parts.append(f"domain:{company_domain}")
        
        cache_key = "|".join(cache_key_parts)
        
        # Check cache first
        cached_result = self._get_cached_enrichment(cache_key)
        if cached_result:
            logger.info(f"Returning cached enrichment result (saved ${0.03})")
            return cached_result
        
        # Check circuit breaker
        if self.circuit_breaker.is_open():
            logger.warning("Circuit breaker is open, skipping enrichment")
            return EmailEnrichmentResult(
                status=EnrichmentStatus.API_ERROR,
                error_message="Service temporarily unavailable"
            )
        
        # Check daily limit
        if self.credits_used_today >= self.daily_credit_limit:
            return EmailEnrichmentResult(
                status=EnrichmentStatus.INSUFFICIENT_CREDITS,
                error_message="Daily credit limit reached"
            )
        
        # Rate limiting
        await self._rate_limit()
        
        try:
            # Normalize linkedin URL
            if linkedin_url and linkedin_url.startswith("https://linkedin.com/"):
                linkedin_url = linkedin_url.replace("https://linkedin.com/", "https://www.linkedin.com/", 1)

            # Select correct CUFinder API endpoint based on 2026 v2 API documentation
            endpoint = None
            payload = {}
            
            # Priority 1: LinkedIn Profile Email Finder API (LinkedIn URL) - most accurate
            if linkedin_url:
                endpoint = f"{self.BASE_URL}/fwe"  # Find with Email endpoint
                # Provide multiple synonymous keys to satisfy different variants
                payload["linkedin_url"] = linkedin_url
                payload["linkedin"] = linkedin_url
                payload["profile_url"] = linkedin_url
                payload["url"] = linkedin_url
                # Also include auxiliary fields (if provided) so fallbacks like /tep have required params
                if full_name:
                    payload["full_name"] = full_name
                    payload["name"] = full_name
                if company:
                    payload["company_name"] = company
                    payload["company"] = company
                if company_domain:
                    payload["domain"] = company_domain
                if title:
                    payload["title"] = title
                
            # Priority 2: Person Enrichment API (Name + Company) - comprehensive data
            elif full_name and company:
                endpoint = f"{self.BASE_URL}/tep"  # Total Enrichment Person endpoint
                payload["full_name"] = full_name
                payload["company_name"] = company
                # Add alternative keys for broader compatibility
                payload["name"] = full_name
                payload["company"] = company
                if title:
                    payload["title"] = title
                    
            # Priority 3: LinkedIn Profile Enrichment API (basic enrichment)
            elif linkedin_url and not full_name:
                endpoint = f"{self.BASE_URL}/epp"  # Enrich Person Profile endpoint
                payload["linkedin_url"] = linkedin_url
                    
            # Fallback: Try Person Enrichment with available data
            else:
                endpoint = f"{self.BASE_URL}/tep"  # Total Enrichment Person endpoint
                if full_name:
                    payload["full_name"] = full_name
                if company:
                    payload["company_name"] = company
                if company_domain:
                    payload["domain"] = company_domain
                if title:
                    payload["title"] = title
                
            # Ensure we have minimum required data
            if not payload:
                return EmailEnrichmentResult(
                    status=EnrichmentStatus.INVALID_INPUT,
                    error_message="Insufficient data for enrichment"
                )
            
            # Make async API request with graceful fallbacks for 404 endpoint changes
            logger.debug(f"Making CUFinder API request to: {endpoint}")
            # Sanitized payload logging - remove sensitive data
            sanitized_payload = {k: v if k not in ['full_name', 'linkedin_url'] else '[REDACTED]' for k, v in payload.items()}
            logger.debug(f"Payload: {sanitized_payload}")

            async def _try_request(urls: List[str]) -> httpx.Response:
                last_resp = None
                for u in urls:
                    try:
                        # Try with Authorization header first
                        resp = await self.client.post(u, json=payload)
                        logger.debug(f"Response status from {u}: {resp.status_code}")
                        # On 401, try alternate header before proceeding
                        if resp.status_code == 401:
                            try:
                                alt_headers = {
                                    **self.client.headers,
                                    "Authorization": None,
                                    "x-api-key": self.api_key
                                }
                                resp_auth = await self.client.post(u, json=payload, headers={k: v for k, v in alt_headers.items() if v})
                                logger.debug(f"Response status (x-api-key) from {u}: {resp_auth.status_code}")
                                if resp_auth.status_code != 404:
                                    return resp_auth
                                last_resp = resp_auth
                            except Exception as he401:
                                logger.warning(f"CUFinder alt-header auth error for {u}: {he401}")
                        # On 404, try next candidate
                        if resp.status_code == 404:
                            last_resp = resp
                            # Try alternative header style (x-api-key)
                            try:
                                alt_headers = {
                                    **self.client.headers,
                                    "Authorization": None,
                                    "x-api-key": self.api_key
                                }
                                resp2 = await self.client.post(u, json=payload, headers={k: v for k, v in alt_headers.items() if v})
                                logger.debug(f"Response status (x-api-key) from {u}: {resp2.status_code}")
                                if resp2.status_code != 404:
                                    return resp2
                                last_resp = resp2
                            except Exception as he2:
                                logger.warning(f"CUFinder alt-header request error for {u}: {he2}")
                            continue
                        return resp
                    except httpx.HTTPError as he:
                        logger.warning(f"CUFinder request error for {u}: {he}")
                        last_resp = None
                        continue
                # If we only saw 404s, return the last; else raise
                # Regardless of last_resp, attempt GET-style fallbacks before failing completely
                try:
                    if linkedin_url:
                        get_candidates = [
                            f"{self.BASE_URL}/email",
                            # Some tenants might route legacy base without /v2
                            "https://api.cufinder.io/email"
                        ]
                        params_variants = [
                            {"linkedin_url": linkedin_url},
                            {"linkedin": linkedin_url},
                            {"url": linkedin_url},
                        ]
                        for get_url in get_candidates:
                            for params in params_variants:
                                try:
                                    resp_get = await self.client.get(get_url, params=params)
                                    logger.debug(f"GET fallback status from {get_url} with {list(params.keys())[0]}: {resp_get.status_code}")
                                    if resp_get.status_code != 404:
                                        return resp_get
                                    # Try x-api-key only
                                    alt_headers = {**self.client.headers, "Authorization": None, "x-api-key": self.api_key}
                                    resp_get2 = await self.client.get(get_url, params=params, headers={k: v for k, v in alt_headers.items() if v})
                                    logger.debug(f"GET fallback (x-api-key) status from {get_url} with {list(params.keys())[0]}: {resp_get2.status_code}")
                                    if resp_get2.status_code != 404:
                                        return resp_get2
                                    last_resp = resp_get2
                                except Exception as ge2:
                                    logger.warning(f"GET fallback attempt failed for {get_url}: {ge2}")
                                    continue
                except Exception as ge:
                    logger.warning(f"GET fallback block failed: {ge}")
                if last_resp is not None:
                    return last_resp
                raise httpx.HTTPError("CUFinder request failed for all endpoints tried")

            # Build endpoint candidates based on v2 API structure
            candidates = [endpoint]
            if endpoint.endswith('/fwe'):
                # LinkedIn Profile Email Finder API fallbacks
                candidates += [
                    f"{self.BASE_URL}/epp",  # Try basic profile enrichment
                ]
                # Only include /tep if we have sufficient person/company data
                if (full_name and (company or company_domain)):
                    candidates.append(f"{self.BASE_URL}/tep")
            elif endpoint.endswith('/tep'):
                # Person Enrichment API fallbacks
                candidates += [
                    f"{self.BASE_URL}/epp",  # Try basic profile enrichment
                    f"{self.BASE_URL}/fwe",  # Try email finder if we have LinkedIn URL
                ]
            elif endpoint.endswith('/epp'):
                # Profile Enrichment API fallbacks
                candidates += [
                    f"{self.BASE_URL}/fwe",  # Try email finder
                    f"{self.BASE_URL}/tep",  # Try total enrichment
                ]

            response = await _try_request(candidates)
            # Don't log response text as it may contain emails
            
            # Handle rate limiting
            if response.status_code == 429:
                self.circuit_breaker.record_failure()
                retry_after = int(response.headers.get('Retry-After', 60))
                
                if self.tenant_id:
                    error_classifier.record_provider_error(
                        'cufinder', 'rate_limited', 
                        f"Rate limited, retry after {retry_after}s",
                        self.tenant_id
                    )
                
                return EmailEnrichmentResult(
                    status=EnrichmentStatus.RATE_LIMITED,
                    error_message=f"Rate limited, retry after {retry_after} seconds"
                )
            
            # Handle other errors
            if response.status_code != 200:
                self.circuit_breaker.record_failure()
                error_msg = f"API error: {response.status_code} - {response.text}"
                # Special-case endpoint 404s to guide future fixes
                if response.status_code == 404:
                    error_msg += " (endpoint not found; tried fallbacks)"
                
                if self.tenant_id:
                    error_classifier.record_provider_error(
                        'cufinder', 'api_error', error_msg, self.tenant_id
                    )
                
                return EmailEnrichmentResult(
                    status=EnrichmentStatus.API_ERROR,
                    error_message=error_msg
                )
            
            # Parse successful response
            data = response.json()
            self.circuit_breaker.record_success()
            
            # Track successful enrichment cost (best-effort)
            try:
                self._track_cost(1)
            except Exception as e:
                logger.warning(f"CUFinder cost tracking failed: {e}")
            
            # Extract email based on CUFinder v2 API response format
            email = None
            confidence = 0.85  # Default confidence
            
            # v2 API Response format - check for direct email field first
            if 'email' in data and data['email']:
                email = data['email']
                confidence = data.get('confidence', 0.95)
                
            # v2 LinkedIn Profile Email Finder (/fwe) response format
            elif 'work_email' in data and data['work_email']:
                email = data['work_email']
                confidence = data.get('email_confidence', 0.90)
                
            # v2 Person Enrichment (/tep) response format
            elif 'person' in data:
                person_data = data['person']
                email = (person_data.get('email') or 
                        person_data.get('work_email') or 
                        person_data.get('business_email'))
                confidence = person_data.get('email_confidence', 0.90)
                
            # v2 Profile Enrichment (/epp) response format
            elif 'profile' in data:
                profile_data = data['profile']
                email = (profile_data.get('email') or 
                        profile_data.get('work_email'))
                confidence = profile_data.get('email_confidence', 0.85)
                
            # Fallback for any email field in response
            else:
                # Try common keys
                email = (data.get('email') or 
                        data.get('work_email') or 
                        data.get('professional_email') or
                        data.get('company_email'))
                # Try nested data containers
                if not email:
                    for key in ['data', 'result', 'contact', 'person']:
                        obj = data.get(key)
                        if isinstance(obj, dict):
                            email = obj.get('email') or obj.get('work_email')
                            if email:
                                break
                # As a last resort, scan for email-like strings
                if not email:
                    import re
                    text_blob = str(data)
                    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text_blob)
                    if match:
                        email = match.group(0)
                        confidence = 0.6
                confidence = data.get('confidence', confidence)
            
            if not email:
                return EmailEnrichmentResult(
                    status=EnrichmentStatus.NOT_FOUND,
                    error_message="No email found in response"
                )
            
            # Build result with enhanced metadata parsing for 2025 API
            result = EmailEnrichmentResult(
                email=email,
                confidence=confidence,
                status=EnrichmentStatus.SUCCESS,
                verified_at=datetime.now(),
                company_domain=data.get('company_domain') or data.get('domain') or company_domain,
                role=data.get('title') or data.get('job_title') or title,
                seniority=data.get('seniority') or data.get('level'),
                department=data.get('department') or data.get('function'),
                cost=0.03,  # Actual cost per credit
                credits_used=1
            )
            
            # Cache the result
            if self.tenant_id:
                self._cache_enrichment(cache_key, result)
            
            return result
            
        except httpx.TimeoutException:
            self.circuit_breaker.record_failure()
            return EmailEnrichmentResult(
                status=EnrichmentStatus.API_ERROR,
                error_message="Request timeout"
            )
        except Exception as e:
            logger.error(f"CUFinder enrichment failed: {e}")
            self.circuit_breaker.record_failure()
            
            if self.tenant_id:
                error_classifier.record_provider_error(
                    'cufinder', 'enrichment_failed', str(e), self.tenant_id
                )
            
            return EmailEnrichmentResult(
                status=EnrichmentStatus.API_ERROR,
                error_message=str(e)
            )
    
    def _cache_enrichment(self, key: str, result: EmailEnrichmentResult):
        """Cache enrichment results to reduce API calls"""
        if not self.tenant_id or not key:
            return
            
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Cache key based on normalized input
            cache_key = f"cufinder_{self.tenant_id}_{hash(key.lower())}"
            
            # Store result in database cache with 30-day expiration
            # Prefer UPSERT that works in PostgreSQL; fall back to SQLite syntax if needed
            try:
                cursor.execute("""
                    INSERT INTO cufinder_cache 
                    (cache_key, tenant_id, email, confidence, status, company_domain, role, 
                     seniority, department, cached_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (cache_key, tenant_id) DO UPDATE SET
                        email = EXCLUDED.email,
                        confidence = EXCLUDED.confidence,
                        status = EXCLUDED.status,
                        company_domain = EXCLUDED.company_domain,
                        role = EXCLUDED.role,
                        seniority = EXCLUDED.seniority,
                        department = EXCLUDED.department,
                        cached_at = EXCLUDED.cached_at,
                        expires_at = EXCLUDED.expires_at
                """, (
                    cache_key, self.tenant_id, result.email, result.confidence,
                    result.status.value, result.company_domain, result.role,
                    result.seniority, result.department, datetime.now(),
                    datetime.now() + timedelta(days=30)
                ))
            except Exception:
                # SQLite older versions: use INSERT OR REPLACE
                cursor.execute("""
                    INSERT OR REPLACE INTO cufinder_cache 
                    (cache_key, tenant_id, email, confidence, status, company_domain, role, 
                     seniority, department, cached_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cache_key, self.tenant_id, result.email, result.confidence,
                    result.status.value, result.company_domain, result.role,
                    result.seniority, result.department, datetime.now(),
                    datetime.now() + timedelta(days=30)
                ))
            
            conn.commit()
            conn.close()
            
            logger.debug(f"Cached CUFinder result for key: {cache_key}")
            
        except Exception as e:
            if "does not exist" in str(e) and "cufinder_cache" in str(e):
                logger.warning(f"⚠️ [CUFINDER CACHE] Cache table missing - skipping cache storage. Run migration to create table.")
            else:
                logger.error(f"❌ [CUFINDER CACHE] Failed to cache enrichment result: {e}")
    
    def _get_cached_enrichment(self, key: str) -> Optional[EmailEnrichmentResult]:
        """Get cached enrichment result if available and not expired"""
        if not self.tenant_id or not key:
            return None
            
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            cache_key = f"cufinder_{self.tenant_id}_{hash(key.lower())}"
            
            cursor.execute("""
                SELECT email, confidence, status, company_domain, role, 
                       seniority, department, cached_at
                FROM cufinder_cache 
                WHERE cache_key = ? AND tenant_id = ? 
                AND expires_at > ?
            """, (cache_key, self.tenant_id, datetime.now()))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                logger.debug(f"Found cached CUFinder result for key: {cache_key}")
                return EmailEnrichmentResult(
                    email=result['email'],
                    confidence=result['confidence'],
                    status=EnrichmentStatus(result['status']),
                    company_domain=result['company_domain'],
                    role=result['role'],
                    seniority=result['seniority'],
                    department=result['department'],
                    verified_at=result['cached_at'],
                    source="cufinder_cache",
                    cost=0.0,  # No cost for cached results
                    credits_used=0
                )
                
            return None
            
        except Exception as e:
            if "does not exist" in str(e) and "cufinder_cache" in str(e):
                logger.warning(f"⚠️ [CUFINDER CACHE] Cache table missing - skipping cache lookup. Run migration to create table.")
            else:
                logger.error(f"❌ [CUFINDER CACHE] Failed to get cached enrichment result: {e}")
            return None
    
    async def batch_enrich(
        self, 
        contacts: List[Dict],
        max_batch_size: int = 10
    ) -> List[EmailEnrichmentResult]:
        """
        Batch enrich multiple contacts efficiently
        """
        results = []
        
        for i in range(0, len(contacts), max_batch_size):
            batch = contacts[i:i + max_batch_size]
            
            for contact in batch:
                result = await self.enrich_email(
                    linkedin_url=contact.get('linkedin_url'),
                    full_name=contact.get('full_name'),
                    company=contact.get('company'),
                    company_domain=contact.get('company_domain'),
                    title=contact.get('title')
                )
                results.append(result)
                
                # Stop if we hit limits
                if result.status in [EnrichmentStatus.RATE_LIMITED, 
                                    EnrichmentStatus.INSUFFICIENT_CREDITS]:
                    logger.warning(f"Stopping batch enrichment: {result.status}")
                    break
        
        return results
    
    async def verify_email(self, email: str) -> Dict:
        """
        CUFinder doesn't have a dedicated email verification endpoint.
        Return a basic validation result instead to avoid 404 errors.
        """
        logger.info(f"Email verification skipped for {email} - CUFinder has no verification endpoint")
        
        # Perform basic email format validation
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        is_valid_format = bool(re.match(email_pattern, email))
        
        if is_valid_format:
            return {
                "valid": True,
                "reason": "basic_format_check",
                "deliverable": None,  # Unknown without actual verification
                "source": "cufinder_basic_check"
            }
        else:
            return {
                "valid": False,
                "reason": "invalid_format",
                "source": "cufinder_basic_check"
            }
    
    async def get_account_info(self) -> Dict:
        """Get CUFinder account information and credits"""
        if not self.is_configured or self.client is None:
            return {
                'error': self.disabled_reason or 'CUFinder API key not configured'
            }
        try:
            endpoint = f"{self.BASE_URL}/account"
            response = await self.client.get(endpoint)
            
            if response.status_code == 200:
                return response.json()
            
            return {'error': f"Failed to get account info: {response.status_code}"}
            
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return {'error': str(e)}

    async def test_api_key(self) -> Dict:
        """Test if the API key is valid by making a simple account info request"""
        try:
            account_info = await self.get_account_info()
            
            if 'error' in account_info:
                return {
                    'valid': False,
                    'error': account_info['error']
                }
            
            return {
                'valid': True,
                'account_info': account_info,
                'message': 'API key is valid'
            }
            
        except Exception as e:
            logger.error(f"API key test failed: {e}")
            return {
                'valid': False, 
                'error': str(e)
            }

    async def close(self):
        """Close the HTTP client"""
        if self.client is not None:
            await self.client.aclose()

# Tenant-scoped clients cache
_tenant_clients = {}

def get_cufinder_client(
    tenant_id: Optional[int] = None,
    *,
    fail_on_missing: bool = False,
) -> CUFinderClient:
    """Get or create tenant-scoped CUFinder client"""
    # Always create new client for proper tenant isolation
    # This ensures each tenant has their own API key and state
    return CUFinderClient(tenant_id=tenant_id, fail_on_missing=fail_on_missing)

def get_cached_cufinder_client(
    tenant_id: Optional[int] = None,
    *,
    fail_on_missing: bool = False,
) -> CUFinderClient:
    """Get cached tenant-scoped CUFinder client (use with caution - mainly for performance)"""
    cache_key = tenant_id or 'default'
    
    if cache_key not in _tenant_clients:
        _tenant_clients[cache_key] = CUFinderClient(
            tenant_id=tenant_id,
            fail_on_missing=fail_on_missing,
        )
    
    return _tenant_clients[cache_key]

def clear_client_cache():
    """Clear all cached clients - useful for testing or config changes"""
    global _tenant_clients
    _tenant_clients.clear()
