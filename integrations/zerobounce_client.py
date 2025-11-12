"""
ZeroBounce Email Validation Client

Production-ready client for ZeroBounce Email Validation API
Used for email verification and deliverability scoring in multi-provider strategy
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

class ZeroBounceStatus(Enum):
    """ZeroBounce validation status"""
    VALID = "valid"
    INVALID = "invalid"
    CATCH_ALL = "catch-all"
    UNKNOWN = "unknown"
    SPAMTRAP = "spamtrap"
    ABUSE = "abuse"
    DO_NOT_MAIL = "do_not_mail"

@dataclass
class ZeroBounceResult:
    """ZeroBounce email validation result"""
    email: str
    status: ZeroBounceStatus
    sub_status: Optional[str]
    confidence: float
    deliverability: str
    disposable: bool
    toxic: bool
    smtp_provider: Optional[str]
    mx_found: bool
    mx_record: Optional[str]
    processing_time_seconds: float
    error_message: Optional[str] = None

class ZeroBounceClient:
    """Production-ready ZeroBounce API client for email validation"""

    def __init__(self):
        self.api_key = os.getenv('ZEROBOUNCE_API_KEY')
        self.base_url = "https://api.zerobounce.net/v2"
        self.rate_limit_delay = 1.0  # seconds between requests
        self.timeout = 30

        if not self.api_key:
            logger.warning("ZEROBOUNCE_API_KEY not configured - email validation disabled")

    async def validate_email(self, email: str, ip_address: Optional[str] = None) -> ZeroBounceResult:
        """Validate a single email address"""

        if not self.api_key:
            return ZeroBounceResult(
                email=email,
                status=ZeroBounceStatus.UNKNOWN,
                sub_status=None,
                confidence=0.0,
                deliverability="unknown",
                disposable=False,
                toxic=False,
                smtp_provider=None,
                mx_found=False,
                mx_record=None,
                processing_time_seconds=0.0,
                error_message="ZeroBounce API key not configured"
            )

        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                params = {
                    "api_key": self.api_key,
                    "email": email
                }

                if ip_address:
                    params["ip_address"] = ip_address

                response = await client.get(
                    f"{self.base_url}/validate",
                    params=params
                )

                await asyncio.sleep(self.rate_limit_delay)
                processing_time = time.time() - start_time

                if response.status_code == 200:
                    data = response.json()

                    # Map ZeroBounce status to our enum
                    status_mapping = {
                        "valid": ZeroBounceStatus.VALID,
                        "invalid": ZeroBounceStatus.INVALID,
                        "catch-all": ZeroBounceStatus.CATCH_ALL,
                        "unknown": ZeroBounceStatus.UNKNOWN,
                        "spamtrap": ZeroBounceStatus.SPAMTRAP,
                        "abuse": ZeroBounceStatus.ABUSE,
                        "do_not_mail": ZeroBounceStatus.DO_NOT_MAIL
                    }

                    status = status_mapping.get(data.get("status", "unknown"), ZeroBounceStatus.UNKNOWN)

                    # Calculate confidence based on status and additional factors
                    confidence = self._calculate_confidence(data, status)

                    return ZeroBounceResult(
                        email=email,
                        status=status,
                        sub_status=data.get("sub_status"),
                        confidence=confidence,
                        deliverability=self._determine_deliverability(status, data),
                        disposable=data.get("disposable", False),
                        toxic=data.get("toxic", False),
                        smtp_provider=data.get("smtp_provider"),
                        mx_found=data.get("mx_found", False),
                        mx_record=data.get("mx_record"),
                        processing_time_seconds=processing_time
                    )

                else:
                    return ZeroBounceResult(
                        email=email,
                        status=ZeroBounceStatus.UNKNOWN,
                        sub_status=None,
                        confidence=0.0,
                        deliverability="unknown",
                        disposable=False,
                        toxic=False,
                        smtp_provider=None,
                        mx_found=False,
                        mx_record=None,
                        processing_time_seconds=processing_time,
                        error_message=f"API error: {response.status_code}"
                    )

        except Exception as e:
            logger.error(f"ZeroBounce API error: {e}")
            return ZeroBounceResult(
                email=email,
                status=ZeroBounceStatus.UNKNOWN,
                sub_status=None,
                confidence=0.0,
                deliverability="unknown",
                disposable=False,
                toxic=False,
                smtp_provider=None,
                mx_found=False,
                mx_record=None,
                processing_time_seconds=time.time() - start_time,
                error_message=str(e)
            )

    async def validate_batch(self, emails: List[str]) -> List[ZeroBounceResult]:
        """Validate multiple email addresses"""

        if not emails:
            return []

        # ZeroBounce supports batch validation, but we'll use individual calls
        # for better error handling and rate limiting
        results = []

        for email in emails:
            result = await self.validate_email(email)
            results.append(result)

            # Rate limiting between validations
            if len(results) < len(emails):
                await asyncio.sleep(self.rate_limit_delay)

        return results

    async def get_credits(self) -> Dict[str, Any]:
        """Get remaining API credits"""

        if not self.api_key:
            return {"error": "API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/getcredits",
                    params={"api_key": self.api_key}
                )

                if response.status_code == 200:
                    data = response.json()
                    return {
                        "credits": data.get("Credits", 0),
                        "valid": True
                    }
                else:
                    return {"error": f"Credits check failed: {response.status_code}"}

        except Exception as e:
            logger.error(f"ZeroBounce credits check error: {e}")
            return {"error": str(e)}

    def _calculate_confidence(self, data: Dict[str, Any], status: ZeroBounceStatus) -> float:
        """Calculate confidence score based on validation results"""

        base_confidence = {
            ZeroBounceStatus.VALID: 0.95,
            ZeroBounceStatus.INVALID: 0.95,
            ZeroBounceStatus.CATCH_ALL: 0.6,
            ZeroBounceStatus.UNKNOWN: 0.3,
            ZeroBounceStatus.SPAMTRAP: 0.95,
            ZeroBounceStatus.ABUSE: 0.95,
            ZeroBounceStatus.DO_NOT_MAIL: 0.95
        }.get(status, 0.5)

        # Adjust confidence based on additional factors
        adjustments = 0.0

        if data.get("mx_found", False):
            adjustments += 0.1

        if data.get("smtp_provider"):
            adjustments += 0.05

        if not data.get("disposable", False):
            adjustments += 0.05

        if not data.get("toxic", False):
            adjustments += 0.05

        return min(1.0, base_confidence + adjustments)

    def _determine_deliverability(self, status: ZeroBounceStatus, data: Dict[str, Any]) -> str:
        """Determine email deliverability rating"""

        if status == ZeroBounceStatus.VALID and not data.get("disposable", False):
            return "high"
        elif status == ZeroBounceStatus.CATCH_ALL:
            return "medium"
        elif status in [ZeroBounceStatus.INVALID, ZeroBounceStatus.SPAMTRAP,
                       ZeroBounceStatus.ABUSE, ZeroBounceStatus.DO_NOT_MAIL]:
            return "none"
        else:
            return "low"

    async def check_api_health(self) -> Dict[str, Any]:
        """Check ZeroBounce API health and connectivity"""

        if not self.api_key:
            return {"healthy": False, "error": "API key not configured"}

        try:
            # Use a simple credits check to verify API connectivity
            credits_result = await self.get_credits()

            if "error" not in credits_result:
                return {
                    "healthy": True,
                    "credits_remaining": credits_result.get("credits", 0),
                    "last_check": time.time()
                }
            else:
                return {
                    "healthy": False,
                    "error": credits_result["error"],
                    "last_check": time.time()
                }

        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "last_check": time.time()
            }

# Global client instance
zerobounce_client = ZeroBounceClient()