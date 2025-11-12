"""
Hunter.io Email Discovery Client

Production-ready client for Hunter.io Email Finder API
Used as fallback provider in multi-provider email enrichment strategy
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

class HunterStatus(Enum):
    """Hunter.io API response status"""
    SUCCESS = "success"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    INVALID_REQUEST = "invalid_request"

@dataclass
class HunterEmailResult:
    """Hunter.io email discovery result"""
    email: Optional[str]
    confidence: float
    source: str = "hunter"
    cost: float = 0.01
    status: HunterStatus = HunterStatus.FAILED
    error_message: Optional[str] = None
    verification_status: Optional[str] = None

class HunterClient:
    """Production-ready Hunter.io API client for email discovery"""

    def __init__(self):
        self.api_key = os.getenv('HUNTER_API_KEY')
        self.base_url = "https://api.hunter.io/v2"
        self.rate_limit_delay = 2.0  # seconds between requests
        self.timeout = 30

        if not self.api_key:
            logger.warning("HUNTER_API_KEY not configured - Hunter.io fallback disabled")

    async def find_email(
        self,
        first_name: str,
        last_name: str,
        company_domain: str
    ) -> HunterEmailResult:
        """Find email for a specific person at a company"""

        if not self.api_key:
            return HunterEmailResult(
                email=None,
                confidence=0.0,
                status=HunterStatus.FAILED,
                error_message="Hunter.io API key not configured"
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Use Email Finder endpoint
                response = await client.get(
                    f"{self.base_url}/email-finder",
                    params={
                        "domain": company_domain,
                        "first_name": first_name,
                        "last_name": last_name,
                        "api_key": self.api_key
                    }
                )

                await asyncio.sleep(self.rate_limit_delay)

                if response.status_code == 200:
                    data = response.json()

                    if data.get("data", {}).get("email"):
                        email_data = data["data"]

                        return HunterEmailResult(
                            email=email_data["email"],
                            confidence=email_data.get("confidence", 50) / 100.0,
                            status=HunterStatus.SUCCESS,
                            verification_status=email_data.get("verification", {}).get("result")
                        )
                    else:
                        return HunterEmailResult(
                            email=None,
                            confidence=0.0,
                            status=HunterStatus.FAILED,
                            error_message="No email found"
                        )

                elif response.status_code == 429:
                    return HunterEmailResult(
                        email=None,
                        confidence=0.0,
                        status=HunterStatus.RATE_LIMITED,
                        error_message="Rate limit exceeded"
                    )

                elif response.status_code == 402:
                    return HunterEmailResult(
                        email=None,
                        confidence=0.0,
                        status=HunterStatus.QUOTA_EXCEEDED,
                        error_message="API quota exceeded"
                    )

                else:
                    return HunterEmailResult(
                        email=None,
                        confidence=0.0,
                        status=HunterStatus.FAILED,
                        error_message=f"API error: {response.status_code}"
                    )

        except Exception as e:
            logger.error(f"Hunter.io API error: {e}")
            return HunterEmailResult(
                email=None,
                confidence=0.0,
                status=HunterStatus.FAILED,
                error_message=str(e)
            )

    async def verify_email(self, email: str) -> Dict[str, Any]:
        """Verify email address using Hunter.io Email Verifier"""

        if not self.api_key:
            return {"valid": False, "error": "API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/email-verifier",
                    params={
                        "email": email,
                        "api_key": self.api_key
                    }
                )

                await asyncio.sleep(self.rate_limit_delay)

                if response.status_code == 200:
                    data = response.json()
                    verification_data = data.get("data", {})

                    return {
                        "valid": verification_data.get("result") == "deliverable",
                        "result": verification_data.get("result"),
                        "score": verification_data.get("score", 0),
                        "disposable": verification_data.get("disposable", False),
                        "webmail": verification_data.get("webmail", False)
                    }

                else:
                    return {"valid": False, "error": f"Verification failed: {response.status_code}"}

        except Exception as e:
            logger.error(f"Hunter.io email verification error: {e}")
            return {"valid": False, "error": str(e)}

    async def get_domain_info(self, domain: str) -> Dict[str, Any]:
        """Get domain information and email patterns"""

        if not self.api_key:
            return {"error": "API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/domain-search",
                    params={
                        "domain": domain,
                        "api_key": self.api_key,
                        "limit": 10
                    }
                )

                await asyncio.sleep(self.rate_limit_delay)

                if response.status_code == 200:
                    data = response.json()
                    domain_data = data.get("data", {})

                    return {
                        "domain": domain_data.get("domain"),
                        "organization": domain_data.get("organization"),
                        "pattern": domain_data.get("pattern"),
                        "email_count": domain_data.get("emails", 0),
                        "confidence": domain_data.get("confidence", 0)
                    }

                else:
                    return {"error": f"Domain search failed: {response.status_code}"}

        except Exception as e:
            logger.error(f"Hunter.io domain search error: {e}")
            return {"error": str(e)}

# Global client instance
hunter_client = HunterClient()