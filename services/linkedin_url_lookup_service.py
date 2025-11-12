"""
LinkedIn URL Lookup Service
September 2025 - Executive Profile URL Discovery Integration

Extends the existing linkedin_people_search service to discover LinkedIn URLs
for executives when they're missing from the initial data. Integrates with
the executive lookup workflow to ensure all prospects have LinkedIn URLs
before proceeding to mutual connections discovery.

Features:
- LinkedIn URL discovery using name + company search
- Integration with existing cookie vault and session management
- Rate limiting and anti-detection measures
- Fallback strategies for difficult-to-find profiles
- Database persistence and caching of discovered URLs
"""

import asyncio
import logging
import random
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import Enum

from .linkedin_people_search import LinkedInPeopleSearchService
from .cookie_vault_service import cookie_vault, VaultItemType
from .audit_logging_service import audit_logger, AuditEventType, AuditSeverity

logger = logging.getLogger(__name__)

class LookupStatus(Enum):
    """LinkedIn URL lookup status"""
    FOUND = "found"
    NOT_FOUND = "not_found"
    MULTIPLE_MATCHES = "multiple_matches"
    INSUFFICIENT_DATA = "insufficient_data"
    RATE_LIMITED = "rate_limited"
    SESSION_INVALID = "session_invalid"
    ERROR = "error"

@dataclass
class LinkedInURLLookupResult:
    """Result of LinkedIn URL lookup"""
    status: LookupStatus
    linkedin_url: Optional[str] = None
    profile_data: Optional[Dict[str, Any]] = None
    confidence_score: float = 0.0
    alternative_matches: List[Dict[str, Any]] = None
    search_query_used: Optional[str] = None
    error_message: Optional[str] = None
    lookup_timestamp: datetime = None

    def __post_init__(self):
        if self.lookup_timestamp is None:
            self.lookup_timestamp = datetime.now(timezone.utc)
        if self.alternative_matches is None:
            self.alternative_matches = []

class LinkedInURLLookupService:
    """Service for discovering LinkedIn URLs for executives using intelligent search"""

    def __init__(self):
        self.people_search = LinkedInPeopleSearchService()
        self.lookup_count = 0
        self.last_lookup_time = 0
        self.min_delay_between_lookups = 45  # seconds
        self.daily_lookup_limit = 100
        self.session_cache = {}  # Cache valid sessions

    async def lookup_linkedin_url(
        self,
        prospect_id: int,
        full_name: str,
        company_name: str,
        title: Optional[str] = None,
        location: Optional[str] = None,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None
    ) -> LinkedInURLLookupResult:
        """
        Discover LinkedIn URL for a prospect using intelligent search

        Args:
            prospect_id: Database ID of the prospect
            full_name: Full name of the executive
            company_name: Company name where executive works
            title: Optional job title for better matching
            location: Optional location for disambiguation
            tenant_id: Tenant ID for audit logging
            user_id: User ID for audit logging

        Returns:
            LinkedInURLLookupResult with discovered URL and confidence
        """

        lookup_start = time.time()

        try:
            # Check rate limiting
            if not await self._check_rate_limits(tenant_id):
                return LinkedInURLLookupResult(
                    status=LookupStatus.RATE_LIMITED,
                    error_message="Daily lookup limit exceeded or rate limited"
                )

            # Validate input data
            if not full_name or not company_name:
                return LinkedInURLLookupResult(
                    status=LookupStatus.INSUFFICIENT_DATA,
                    error_message="Full name and company name are required"
                )

            # Check cache first
            cached_result = await self._check_cache(prospect_id, full_name, company_name)
            if cached_result:
                logger.info(f"Found cached LinkedIn URL for {full_name}")
                return cached_result

            # Get valid LinkedIn session
            session_data = await self._get_valid_session(tenant_id, user_id)
            if not session_data:
                return LinkedInURLLookupResult(
                    status=LookupStatus.SESSION_INVALID,
                    error_message="No valid LinkedIn session available"
                )

            # Prepare search queries in order of preference
            search_queries = self._prepare_search_queries(full_name, company_name, title)

            best_result = None
            best_confidence = 0.0

            for search_query in search_queries:
                try:
                    logger.info(f"Searching LinkedIn for: {search_query}")

                    # Perform search using existing people search service
                    search_results = await self._perform_linkedin_search(
                        search_query, session_data
                    )

                    if search_results:
                        # Analyze and score results
                        analyzed_result = await self._analyze_search_results(
                            search_results, full_name, company_name, title, location
                        )

                        if analyzed_result and analyzed_result.confidence_score > best_confidence:
                            best_result = analyzed_result
                            best_confidence = analyzed_result.confidence_score

                        # If we found a high-confidence match, stop searching
                        if best_confidence >= 0.8:
                            break

                    # Add delay between searches
                    await self._human_delay(15, 25)

                except Exception as e:
                    logger.warning(f"Search failed for query '{search_query}': {e}")
                    continue

            # Determine final result
            if best_result:
                # Cache the result
                await self._cache_result(prospect_id, full_name, company_name, best_result)

                # Update database
                await self._update_prospect_linkedin_url(prospect_id, best_result.linkedin_url)

                # Audit log success
                if tenant_id and user_id:
                    await audit_logger.log_event(
                        event_type=AuditEventType.DATA_ENRICHMENT,
                        actor_type="system",
                        actor_id="linkedin_url_lookup",
                        target_type="prospect",
                        target_id=str(prospect_id),
                        organization_id=tenant_id,
                        details={
                            "action": "linkedin_url_discovered",
                            "prospect_name": full_name,
                            "company": company_name,
                            "linkedin_url": best_result.linkedin_url,
                            "confidence_score": best_result.confidence_score,
                            "lookup_time_ms": int((time.time() - lookup_start) * 1000)
                        },
                        severity=AuditSeverity.INFO
                    )

                logger.info(f"✅ Found LinkedIn URL for {full_name}: {best_result.linkedin_url} (confidence: {best_confidence:.2f})")
                return best_result

            else:
                # No match found
                result = LinkedInURLLookupResult(
                    status=LookupStatus.NOT_FOUND,
                    error_message=f"No LinkedIn profile found for {full_name} at {company_name}"
                )

                # Cache negative result (shorter TTL)
                await self._cache_result(prospect_id, full_name, company_name, result, ttl_hours=6)

                logger.warning(f"❌ No LinkedIn URL found for {full_name} at {company_name}")
                return result

        except Exception as e:
            logger.error(f"LinkedIn URL lookup failed for {full_name}: {e}")

            # Audit log failure
            if tenant_id and user_id:
                try:
                    await audit_logger.log_event(
                        event_type=AuditEventType.DATA_ENRICHMENT,
                        actor_type="system",
                        actor_id="linkedin_url_lookup",
                        target_type="prospect",
                        target_id=str(prospect_id),
                        organization_id=tenant_id,
                        details={
                            "action": "linkedin_url_lookup_failed",
                            "prospect_name": full_name,
                            "company": company_name,
                            "error": str(e)
                        },
                        severity=AuditSeverity.WARNING
                    )
                except:
                    pass

            return LinkedInURLLookupResult(
                status=LookupStatus.ERROR,
                error_message=f"Lookup failed: {str(e)}"
            )

    def _prepare_search_queries(
        self,
        full_name: str,
        company_name: str,
        title: Optional[str] = None
    ) -> List[str]:
        """Prepare optimized search queries in order of preference"""

        queries = []

        # Clean and prepare names
        name_parts = full_name.strip().split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        # Clean company name
        company_clean = company_name.replace("Inc.", "").replace("LLC", "").replace("Corp.", "").strip()

        # Query 1: Full name + company (highest priority)
        queries.append(f'"{full_name}" "{company_clean}"')

        # Query 2: First + Last name + company
        if first_name and last_name:
            queries.append(f'{first_name} {last_name} "{company_clean}"')

        # Query 3: Include title if available
        if title:
            title_clean = title.replace("CEO", "Chief Executive").replace("CTO", "Chief Technology")
            queries.append(f'"{full_name}" "{company_clean}" "{title_clean}"')

        # Query 4: Broader search without quotes
        queries.append(f'{full_name} {company_clean}')

        # Query 5: Just name (last resort)
        if len(name_parts) >= 2:
            queries.append(f'{first_name} {last_name}')

        return queries

    async def _perform_linkedin_search(
        self,
        search_query: str,
        session_data: Dict[str, Any]
    ) -> Optional[List[Dict[str, Any]]]:
        """Perform LinkedIn search using existing people search service"""

        try:
            # Use existing LinkedIn people search service
            # This integrates with the existing infrastructure
            search_results = await self.people_search.search_people(
                query=search_query,
                filters={
                    "connectionOf": "SELF",  # Search in our network first
                    "resultType": "PEOPLE"
                },
                limit=20
            )

            return search_results

        except Exception as e:
            logger.warning(f"LinkedIn search failed: {e}")
            return None

    async def _analyze_search_results(
        self,
        search_results: List[Dict[str, Any]],
        target_name: str,
        target_company: str,
        target_title: Optional[str] = None,
        target_location: Optional[str] = None
    ) -> Optional[LinkedInURLLookupResult]:
        """Analyze search results and return best match with confidence score"""

        if not search_results:
            return None

        best_match = None
        best_score = 0.0
        alternative_matches = []

        for result in search_results:
            score = self._calculate_match_score(
                result, target_name, target_company, target_title, target_location
            )

            if score > 0.5:  # Minimum threshold
                match_data = {
                    "linkedin_url": result.get("profileUrl"),
                    "name": result.get("name"),
                    "title": result.get("title"),
                    "company": result.get("company"),
                    "location": result.get("location"),
                    "confidence": score
                }

                if score > best_score:
                    if best_match:
                        alternative_matches.append(best_match)
                    best_match = match_data
                    best_score = score
                else:
                    alternative_matches.append(match_data)

        if best_match:
            return LinkedInURLLookupResult(
                status=LookupStatus.FOUND,
                linkedin_url=best_match["linkedin_url"],
                profile_data=best_match,
                confidence_score=best_score,
                alternative_matches=alternative_matches[:5]  # Top 5 alternatives
            )

        return None

    def _calculate_match_score(
        self,
        result: Dict[str, Any],
        target_name: str,
        target_company: str,
        target_title: Optional[str] = None,
        target_location: Optional[str] = None
    ) -> float:
        """Calculate confidence score for a search result match"""

        score = 0.0

        # Name matching (40% weight)
        result_name = result.get("name", "").lower()
        target_name_lower = target_name.lower()

        if result_name == target_name_lower:
            score += 0.4
        elif target_name_lower in result_name or result_name in target_name_lower:
            score += 0.3
        else:
            # Check name parts
            target_parts = set(target_name_lower.split())
            result_parts = set(result_name.split())
            name_overlap = len(target_parts.intersection(result_parts)) / len(target_parts)
            score += name_overlap * 0.25

        # Company matching (35% weight)
        result_company = result.get("company", "").lower()
        target_company_lower = target_company.lower()

        if target_company_lower in result_company or result_company in target_company_lower:
            score += 0.35
        else:
            # Check company name parts
            target_co_parts = set(target_company_lower.split())
            result_co_parts = set(result_company.split())
            if target_co_parts.intersection(result_co_parts):
                score += 0.2

        # Title matching (15% weight)
        if target_title:
            result_title = result.get("title", "").lower()
            target_title_lower = target_title.lower()

            if target_title_lower in result_title or result_title in target_title_lower:
                score += 0.15
            elif any(word in result_title for word in target_title_lower.split()):
                score += 0.1

        # Location matching (10% weight)
        if target_location:
            result_location = result.get("location", "").lower()
            target_location_lower = target_location.lower()

            if target_location_lower in result_location or result_location in target_location_lower:
                score += 0.1

        return min(score, 1.0)  # Cap at 1.0

    async def _check_rate_limits(self, tenant_id: Optional[int]) -> bool:
        """Check if we can perform another lookup"""

        # Check global rate limit
        current_time = time.time()
        if current_time - self.last_lookup_time < self.min_delay_between_lookups:
            return False

        # Check daily limit (implement with cache/database)
        # For now, simple in-memory check
        if self.lookup_count >= self.daily_lookup_limit:
            return False

        self.last_lookup_time = current_time
        self.lookup_count += 1
        return True

    async def _get_valid_session(
        self,
        tenant_id: Optional[int],
        user_id: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        """Get a valid LinkedIn session for searching"""

        try:
            # Use cookie vault to get valid session
            if tenant_id and user_id:
                sessions = await cookie_vault.list_vault_items(
                    tenant_id=str(tenant_id),
                    user_id=str(user_id),
                    item_type=VaultItemType.LINKEDIN_COOKIE,
                )

                current_time = datetime.now(timezone.utc).replace(tzinfo=None)

                for session in sessions:
                    session_id = session.get("id")
                    if not session_id:
                        continue

                    if not session.get("is_active"):
                        continue

                    expires_at_raw = session.get("expires_at")
                    if expires_at_raw:
                        try:
                            expires_at = datetime.fromisoformat(expires_at_raw)
                            if expires_at.tzinfo is not None:
                                expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
                        except ValueError:
                            expires_at = None
                    else:
                        expires_at = None

                    if expires_at and expires_at <= current_time:
                        continue

                    item = await cookie_vault.retrieve_vault_item(
                        session_id,
                        tenant_id=str(tenant_id),
                        user_id=str(user_id),
                    )
                    if not item:
                        continue

                    data = item.get("data") or {}
                    if not data.get("li_at"):
                        continue

                    return {
                        "li_at": data.get("li_at"),
                        "jsessionid": data.get("jsessionid"),
                        "user_agent": data.get("user_agent"),
                        "vault_item_id": session_id,
                        "expires_at": expires_at_raw,
                        "last_accessed": session.get("last_accessed"),
                    }

            return None

        except Exception as e:
            logger.warning(f"Failed to get valid LinkedIn session: {e}")
            return None

    async def _check_cache(
        self,
        prospect_id: int,
        full_name: str,
        company_name: str
    ) -> Optional[LinkedInURLLookupResult]:
        """Check if we have a cached result for this lookup"""

        # Implement caching logic here
        # For now, return None (no cache)
        return None

    async def _cache_result(
        self,
        prospect_id: int,
        full_name: str,
        company_name: str,
        result: LinkedInURLLookupResult,
        ttl_hours: int = 24
    ) -> None:
        """Cache the lookup result"""

        # Implement caching logic here
        # Could use Redis or database table
        pass

    async def _update_prospect_linkedin_url(
        self,
        prospect_id: int,
        linkedin_url: str
    ) -> None:
        """Update prospect record with discovered LinkedIn URL"""

        try:
            from .mt_db import get_db

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE prospects SET linkedin_url = ? WHERE id = ?",
                    (linkedin_url, prospect_id)
                )
                conn.commit()

            logger.info(f"Updated prospect {prospect_id} with LinkedIn URL: {linkedin_url}")

        except Exception as e:
            logger.error(f"Failed to update prospect LinkedIn URL: {e}")

    async def _human_delay(self, min_seconds: float = 10.0, max_seconds: float = 20.0) -> None:
        """Add human-like delays between operations"""
        delay = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(delay)

    async def cleanup(self) -> None:
        """Clean up resources"""
        if self.people_search:
            await self.people_search.cleanup()

# Global instance
linkedin_url_lookup_service = LinkedInURLLookupService()

# Convenience function
async def lookup_prospect_linkedin_url(
    prospect_id: int,
    full_name: str,
    company_name: str,
    title: Optional[str] = None,
    location: Optional[str] = None,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None
) -> LinkedInURLLookupResult:
    """
    Convenience function for LinkedIn URL lookup

    Args:
        prospect_id: Database ID of the prospect
        full_name: Full name of the executive
        company_name: Company name where executive works
        title: Optional job title for better matching
        location: Optional location for disambiguation
        tenant_id: Tenant ID for audit logging
        user_id: User ID for audit logging

    Returns:
        LinkedInURLLookupResult with discovered URL and confidence
    """
    return await linkedin_url_lookup_service.lookup_linkedin_url(
        prospect_id, full_name, company_name, title, location, tenant_id, user_id
    )