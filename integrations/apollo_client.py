"""
Apollo.io API Client
Production-ready client with rate limiting for Apollo.io API
Used for executive lookup and company enrichment as fallback provider for Clearbit
"""

import os
import json
import time
import asyncio
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

import httpx

logger = logging.getLogger(__name__)

class ApolloStatus(Enum):
    """Apollo API response status"""
    SUCCESS = "success"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    INVALID_REQUEST = "invalid_request"

@dataclass
class ApolloExecutiveResult:
    """Apollo executive lookup result"""
    executive_data: Optional[Dict[str, Any]]
    confidence: float
    source: str = "apollo"
    cost: float = 0.25
    status: ApolloStatus = ApolloStatus.FAILED
    error_message: Optional[str] = None

class ApolloClient:
    """Production-ready Apollo.io API client with rate limiting"""

    def __init__(self):
        self.api_key = os.getenv('APOLLO_API_KEY')
        self.base_url = "https://api.apollo.io/v1"
        self.rate_limit_delay = 1.0  # seconds between requests
        self.timeout = 30

        # Import rate limiting service
        try:
            from services.rate_limiting_service import rate_limiter
            self.rate_limiter = rate_limiter
        except ImportError:
            logger.warning("⚠️ Rate limiting service not available - using basic rate limiting")
            self.rate_limiter = None

        if not self.api_key:
            logger.warning("APOLLO_API_KEY not configured - Apollo.io fallback disabled")
        else:
            logger.info("✅ Apollo.io client initialized with rate limiting")

    async def lookup_executive(
        self,
        company_domain: str,
        executive_name: str,
        executive_email: Optional[str] = None,
        organization_id: Optional[int] = None
    ) -> ApolloExecutiveResult:
        """Look up executive information using Apollo.io People Search API with rate limiting"""

        if not self.api_key:
            return ApolloExecutiveResult(
                executive_data=None,
                confidence=0.0,
                status=ApolloStatus.FAILED,
                error_message="Apollo.io API key not configured"
            )

        # Check rate limits before making request
        identifier = str(organization_id) if organization_id else "default"

        if self.rate_limiter:
            try:
                rate_limit_result = await self.rate_limiter.check_rate_limit("apollo", identifier)

                if rate_limit_result.action.value == "deny":
                    logger.warning(f"🚨 Apollo.io rate limit exceeded for org {organization_id}. "
                                 f"Reset in {rate_limit_result.wait_seconds:.1f}s")
                    return ApolloExecutiveResult(
                        executive_data=None,
                        confidence=0.0,
                        status=ApolloStatus.RATE_LIMITED,
                        error_message=f"Rate limit exceeded. Try again in {rate_limit_result.wait_seconds:.0f} seconds"
                    )

                elif rate_limit_result.action.value == "wait":
                    logger.info(f"⏳ Apollo.io rate limit - waiting {rate_limit_result.wait_seconds:.1f}s")
                    await asyncio.sleep(rate_limit_result.wait_seconds)

                # Log quota usage
                if rate_limit_result.quota_used_percentage > 80:
                    logger.warning(f"⚠️ Apollo.io quota {rate_limit_result.quota_used_percentage:.1f}% used for org {organization_id}")

            except Exception as e:
                logger.error(f"❌ Rate limit check failed for Apollo.io: {e}")
                # Continue with request but log error

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Build search query
                search_params = {
                    "api_key": self.api_key,
                    "q_organization_domains": company_domain,
                    "person_titles": ["CEO", "CTO", "COO", "CFO", "VP", "Director", "Manager", "President"],
                    "page": 1,
                    "per_page": 10
                }

                # Add name filter if provided
                if executive_name:
                    name_parts = executive_name.split()
                    if len(name_parts) >= 2:
                        search_params["first_name"] = name_parts[0]
                        search_params["last_name"] = " ".join(name_parts[1:])

                # Add email filter if provided
                if executive_email:
                    search_params["emails"] = [executive_email]

                response = await client.post(
                    f"{self.base_url}/mixed_people/search",
                    json=search_params
                )

                await asyncio.sleep(self.rate_limit_delay)

                if response.status_code == 200:
                    data = response.json()
                    people = data.get("people", [])

                    # Record successful API call
                    if self.rate_limiter:
                        await self.rate_limiter.record_api_success("apollo")

                    if people:
                        # Find best match
                        best_match = self._find_best_executive_match(
                            people, executive_name, executive_email
                        )

                        if best_match:
                            logger.info(f"✅ Apollo.io executive lookup successful for {executive_name}")
                            return ApolloExecutiveResult(
                                executive_data=best_match["executive_data"],
                                confidence=best_match["confidence"],
                                status=ApolloStatus.SUCCESS
                            )

                    return ApolloExecutiveResult(
                        executive_data=None,
                        confidence=0.0,
                        status=ApolloStatus.FAILED,
                        error_message="No matching executive found"
                    )

                elif response.status_code == 429:
                    # Record rate limit error
                    if self.rate_limiter:
                        await self.rate_limiter.record_api_error("apollo", "rate_limit")

                    logger.warning(f"🚨 Apollo.io rate limit hit for org {organization_id}")
                    return ApolloExecutiveResult(
                        executive_data=None,
                        confidence=0.0,
                        status=ApolloStatus.RATE_LIMITED,
                        error_message="Rate limit exceeded"
                    )

                elif response.status_code == 402:
                    # Record quota error
                    if self.rate_limiter:
                        await self.rate_limiter.record_api_error("apollo", "quota_exceeded")

                    logger.error(f"💰 Apollo.io quota exceeded for org {organization_id}")
                    return ApolloExecutiveResult(
                        executive_data=None,
                        confidence=0.0,
                        status=ApolloStatus.QUOTA_EXCEEDED,
                        error_message="API quota exceeded"
                    )

                else:
                    # Record generic API error
                    if self.rate_limiter:
                        await self.rate_limiter.record_api_error("apollo", "api_error")

                    logger.error(f"❌ Apollo.io API error {response.status_code} for org {organization_id}")
                    return ApolloExecutiveResult(
                        executive_data=None,
                        confidence=0.0,
                        status=ApolloStatus.FAILED,
                        error_message=f"API error: {response.status_code}"
                    )

        except Exception as e:
            # Record exception error
            if self.rate_limiter:
                await self.rate_limiter.record_api_error("apollo", "exception")

            logger.error(f"❌ Apollo.io API exception for org {organization_id}: {e}")
            return ApolloExecutiveResult(
                executive_data=None,
                confidence=0.0,
                status=ApolloStatus.FAILED,
                error_message=str(e)
            )

    def _find_best_executive_match(
        self,
        people: List[Dict[str, Any]],
        target_name: Optional[str],
        target_email: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Find the best matching executive from Apollo results"""

        if not people:
            return None

        best_match = None
        best_score = 0.0

        for person in people:
            score = 0.0

            # Base score for having executive-level title
            title = person.get("title", "").lower()
            if any(keyword in title for keyword in ["ceo", "cto", "coo", "cfo", "president", "founder"]):
                score += 0.5
            elif any(keyword in title for keyword in ["vp", "director", "head"]):
                score += 0.3
            elif any(keyword in title for keyword in ["manager", "lead"]):
                score += 0.1

            # Score for name match
            if target_name:
                person_name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
                if target_name.lower() in person_name.lower() or person_name.lower() in target_name.lower():
                    score += 0.3

            # Score for email match (highest priority)
            if target_email and person.get("email"):
                if target_email.lower() == person.get("email", "").lower():
                    score += 0.5

            # Score for having complete profile
            if person.get("email"):
                score += 0.1
            if person.get("linkedin_url"):
                score += 0.1

            if score > best_score:
                best_score = score
                best_match = {
                    "executive_data": {
                        "full_name": f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                        "title": person.get("title"),
                        "email": person.get("email"),
                        "linkedin_url": person.get("linkedin_url"),
                        "company_name": person.get("organization", {}).get("name"),
                        "company_domain": person.get("organization", {}).get("primary_domain"),
                        "location": person.get("city"),
                        "phone": person.get("phone_numbers", [{}])[0].get("raw_number") if person.get("phone_numbers") else None
                    },
                    "confidence": min(best_score, 1.0)
                }

        return best_match

    async def enrich_company(self, company_domain: str, organization_id: Optional[int] = None) -> Dict[str, Any]:
        """Get company information from Apollo with rate limiting"""

        if not self.api_key:
            return {"error": "API key not configured"}

        # Check rate limits before making request
        identifier = str(organization_id) if organization_id else "default"

        if self.rate_limiter:
            try:
                rate_limit_result = await self.rate_limiter.check_rate_limit("apollo", identifier)

                if rate_limit_result.action.value == "deny":
                    logger.warning(f"🚨 Apollo.io company enrichment rate limit exceeded for org {organization_id}")
                    return {"error": f"Rate limit exceeded. Try again in {rate_limit_result.wait_seconds:.0f} seconds"}

                elif rate_limit_result.action.value == "wait":
                    logger.info(f"⏳ Apollo.io company enrichment rate limit - waiting {rate_limit_result.wait_seconds:.1f}s")
                    await asyncio.sleep(rate_limit_result.wait_seconds)

            except Exception as e:
                logger.error(f"❌ Rate limit check failed for Apollo.io company enrichment: {e}")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/organizations/search",
                    json={
                        "api_key": self.api_key,
                        "q_organization_domains": company_domain,
                        "page": 1,
                        "per_page": 1
                    }
                )

                await asyncio.sleep(self.rate_limit_delay)

                if response.status_code == 200:
                    data = response.json()
                    organizations = data.get("organizations", [])

                    # Record successful API call
                    if self.rate_limiter:
                        await self.rate_limiter.record_api_success("apollo")

                    if organizations:
                        org = organizations[0]
                        logger.info(f"✅ Apollo.io company enrichment successful for {company_domain}")
                        return {
                            "name": org.get("name"),
                            "domain": org.get("primary_domain"),
                            "industry": org.get("industry"),
                            "size": org.get("estimated_num_employees"),
                            "location": f"{org.get('city', '')}, {org.get('state', '')}".strip(", "),
                            "description": org.get("short_description"),
                            "website": org.get("website_url"),
                            "linkedin": org.get("linkedin_url")
                        }

                    return {"error": "Company not found"}

                elif response.status_code == 429:
                    # Record rate limit error
                    if self.rate_limiter:
                        await self.rate_limiter.record_api_error("apollo", "rate_limit")
                    return {"error": "Rate limit exceeded"}

                elif response.status_code == 402:
                    # Record quota error
                    if self.rate_limiter:
                        await self.rate_limiter.record_api_error("apollo", "quota_exceeded")
                    return {"error": "API quota exceeded"}

                else:
                    # Record generic API error
                    if self.rate_limiter:
                        await self.rate_limiter.record_api_error("apollo", "api_error")
                    return {"error": f"API error: {response.status_code}"}

        except Exception as e:
            # Record exception error
            if self.rate_limiter:
                await self.rate_limiter.record_api_error("apollo", "exception")

            logger.error(f"❌ Apollo.io company enrichment exception for org {organization_id}: {e}")
            return {"error": str(e)}

# Global client instance
apollo_client = ApolloClient()