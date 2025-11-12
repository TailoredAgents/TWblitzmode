"""
LinkedIn Cookie Verification Service
September 2025 - Enterprise Cookie Validation and User Discovery

Validates LinkedIn li_at and jsessionid cookies by performing stealth login
and extracting user profile information (username, full name) for verification.

Features:
- Playwright-based stealth browsing with anti-detection
- Cookie validation with session verification
- User profile extraction (username, display name)
- Error handling for invalid/expired cookies
- Rate limiting and human-like behavior simulation
"""

import asyncio
import logging
import os
import random
import time
from typing import Dict, Any, Tuple, Optional
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import Enum

import httpx

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    _PLAYWRIGHT_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - exercised when playwright missing
    async_playwright = None  # type: ignore[assignment]
    Browser = BrowserContext = Page = Any  # type: ignore[assignment]
    _PLAYWRIGHT_IMPORT_ERROR = exc

from .audit_logging_service import audit_logger, AuditEventType, AuditSeverity

logger = logging.getLogger(__name__)

INSTALL_PLAYWRIGHT_HINT = "Install Playwright with scripts/install_playwright.sh"
FALLBACK_HINT = (
    f"{INSTALL_PLAYWRIGHT_HINT} or set LINKEDIN_COOKIE_VERIFIER_API to an external verification service."
)


def determine_verifier_mode() -> Tuple[str, str]:
    """Determine which verification strategy should be used."""

    requested = os.getenv("LINKEDIN_VERIFIER_MODE", "auto").strip().lower()
    if requested not in {"auto", "playwright", "api", "disabled"}:
        logger.warning("Unknown LINKEDIN_VERIFIER_MODE=%s; defaulting to auto", requested)
        requested = "auto"

    api_endpoint = os.getenv("LINKEDIN_COOKIE_VERIFIER_API")

    playwright_available = async_playwright is not None

    if requested == "disabled":
        return "disabled", "Verifier disabled via configuration. " + FALLBACK_HINT

    if requested == "playwright":
        if playwright_available:
            return "playwright", "Playwright forced via configuration."
        detail = str(_PLAYWRIGHT_IMPORT_ERROR) if _PLAYWRIGHT_IMPORT_ERROR else "Playwright is not installed."
        return "disabled", f"Playwright requested but unavailable: {detail} {FALLBACK_HINT}"

    if requested == "api":
        if api_endpoint:
            return "api", "External verification API forced via configuration."
        return "disabled", "API verification requested but LINKEDIN_COOKIE_VERIFIER_API is not set. " + FALLBACK_HINT

    # Auto mode
    if playwright_available:
        return "playwright", "Playwright auto-selected for cookie verification."
    if api_endpoint:
        return "api", "Playwright unavailable; using external verification API."
    return "disabled", "No verification strategy available. " + FALLBACK_HINT

class VerificationStatus(Enum):
    """Cookie verification status"""
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    RATE_LIMITED = "rate_limited"
    CHALLENGE_REQUIRED = "challenge_required"
    NETWORK_ERROR = "network_error"

@dataclass
class CookieVerificationResult:
    """Result of cookie verification"""
    status: VerificationStatus
    username: Optional[str] = None
    full_name: Optional[str] = None
    profile_url: Optional[str] = None
    profile_image_url: Optional[str] = None
    error_message: Optional[str] = None
    verification_timestamp: datetime = None

    def __post_init__(self):
        if self.verification_timestamp is None:
            self.verification_timestamp = datetime.now(timezone.utc)

class _LinkedInCookieVerifier:
    """LinkedIn cookie verification service using Playwright stealth browsing"""

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.verification_count = 0
        self.last_verification_time = 0
        self.min_delay_between_verifications = 30  # seconds

        self.verifier_mode, self.mode_reason = determine_verifier_mode()
        self.api_endpoint = os.getenv("LINKEDIN_COOKIE_VERIFIER_API")
        self.api_key = os.getenv("LINKEDIN_COOKIE_VERIFIER_API_KEY")
        self.api_header_name = os.getenv("LINKEDIN_COOKIE_VERIFIER_API_HEADER", "Authorization")
        self.api_timeout = float(os.getenv("LINKEDIN_COOKIE_VERIFIER_TIMEOUT", "15"))

        # User agents for rotation
        self.user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"
        ]

    async def _ensure_browser_ready(self) -> None:
        """Ensure browser and context are ready for verification"""
        if self.verifier_mode != "playwright":
            raise RuntimeError("Playwright verification mode is disabled in the current configuration")
        if async_playwright is None:  # Safety guard for runtime checks
            raise RuntimeError(
                "Playwright is required for LinkedIn cookie verification. "
                "Install the optional dependency with `pip install playwright` "
                "and run `playwright install`."
            ) from _PLAYWRIGHT_IMPORT_ERROR
        if not self.browser:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding',
                    '--no-first-run',
                    '--no-default-browser-check'
                ]
            )

        if not self.context:
            self.context = await self.browser.new_context(
                user_agent=random.choice(self.user_agents),
                viewport={'width': 1366, 'height': 768},
                locale='en-US',
                timezone_id='America/New_York',
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }
            )

            # Add stealth scripts to avoid detection
            await self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });

                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });

                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });

                window.chrome = {
                    runtime: {}
                };
            """)

    async def _apply_rate_limiting(self) -> bool:
        """Apply rate limiting between verifications"""
        current_time = time.time()
        time_since_last = current_time - self.last_verification_time

        if time_since_last < self.min_delay_between_verifications:
            sleep_time = self.min_delay_between_verifications - time_since_last
            logger.info(f"Rate limiting: waiting {sleep_time:.1f} seconds before verification")
            await asyncio.sleep(sleep_time)

        self.last_verification_time = time.time()
        return True

    async def _verify_via_api(
        self,
        *,
        li_at: str,
        jsessionid: str,
        tenant_id: Optional[int],
        user_id: Optional[int],
        verification_start: float,
    ) -> CookieVerificationResult:
        """Fallback verification using an external HTTP API."""

        if not self.api_endpoint:
            return CookieVerificationResult(
                status=VerificationStatus.NETWORK_ERROR,
                error_message="External cookie verification API not configured. " + FALLBACK_HINT,
            )

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            header = (self.api_header_name or "Authorization").strip()
            header_value = self.api_key
            if header.lower() == "authorization" and not header_value.lower().startswith("bearer "):
                header_value = f"Bearer {header_value}"
            headers[header] = header_value

        payload = {
            "li_at": li_at,
            "jsessionid": jsessionid,
            "tenant_id": tenant_id,
            "user_id": user_id,
        }

        try:
            async with httpx.AsyncClient(timeout=self.api_timeout) as client:
                response = await client.post(self.api_endpoint, json=payload, headers=headers)
        except httpx.TimeoutException:
            logger.error("LinkedIn cookie verification API timed out")
            return CookieVerificationResult(
                status=VerificationStatus.NETWORK_ERROR,
                error_message="Cookie verification API timed out.",
            )
        except httpx.RequestError as exc:
            logger.error("LinkedIn cookie verification API request failed: %s", exc)
            return CookieVerificationResult(
                status=VerificationStatus.NETWORK_ERROR,
                error_message="Cookie verification API request failed.",
            )

        if response.status_code >= 500:
            logger.error(
                "Cookie verification API error %s: %s",
                response.status_code,
                response.text,
            )
            return CookieVerificationResult(
                status=VerificationStatus.NETWORK_ERROR,
                error_message=f"Verification API unavailable ({response.status_code}).",
            )

        if response.status_code == 401:
            logger.warning("Cookie verification API rejected credentials")
            return CookieVerificationResult(
                status=VerificationStatus.INVALID,
                error_message="Verification API authentication failed.",
            )

        try:
            data = response.json()
        except ValueError:
            logger.error("Verification API returned non-JSON payload: %s", response.text[:200])
            return CookieVerificationResult(
                status=VerificationStatus.NETWORK_ERROR,
                error_message="Verification API returned invalid response.",
            )

        status_map = {
            "valid": VerificationStatus.VALID,
            "invalid": VerificationStatus.INVALID,
            "expired": VerificationStatus.EXPIRED,
            "challenge_required": VerificationStatus.CHALLENGE_REQUIRED,
            "rate_limited": VerificationStatus.RATE_LIMITED,
            "network_error": VerificationStatus.NETWORK_ERROR,
        }

        status_value = str(data.get("status", "")).lower()
        mapped_status = status_map.get(status_value, VerificationStatus.INVALID)

        result = CookieVerificationResult(
            status=mapped_status,
            username=data.get("username") or data.get("user") or data.get("memberId"),
            full_name=data.get("full_name") or data.get("name"),
            profile_url=data.get("profile_url") or data.get("profileUrl"),
            profile_image_url=data.get("profile_image_url") or data.get("profileImageUrl"),
            error_message=data.get("message"),
        )

        verification_time = time.time() - verification_start

        if mapped_status is VerificationStatus.VALID:
            logger.info("✅ Cookie verification API reported valid credentials in %.2fs", verification_time)
            if tenant_id and user_id:
                await audit_logger.log_event(
                    event_type=AuditEventType.AUTHENTICATION,
                    actor_type="user",
                    actor_id=str(user_id),
                    target_type="linkedin_session",
                    target_id=f"verification_{result.username or 'api'}",
                    organization_id=tenant_id,
                    details={
                        "action": "cookie_verification",
                        "status": "success",
                        "source": "api",
                        "verification_time_ms": int(verification_time * 1000),
                    },
                    severity=AuditSeverity.INFO,
                )
        else:
            logger.warning(
                "Cookie verification API returned status %s: %s",
                mapped_status.value,
                result.error_message,
            )
            if tenant_id and user_id:
                await audit_logger.log_event(
                    event_type=AuditEventType.AUTHENTICATION,
                    actor_type="user",
                    actor_id=str(user_id),
                    target_type="linkedin_session",
                    target_id="verification_api_failure",
                    organization_id=tenant_id,
                    details={
                        "action": "cookie_verification",
                        "status": mapped_status.value,
                        "source": "api",
                        "message": result.error_message,
                    },
                    severity=AuditSeverity.WARNING,
                )

        return result

    async def _human_delay(self, min_seconds: float = 2.0, max_seconds: float = 5.0) -> None:
        """Add human-like delays between actions"""
        delay = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(delay)

    async def verify_linkedin_cookies(
        self,
        li_at: str,
        jsessionid: str,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None
    ) -> CookieVerificationResult:
        """
        Verify LinkedIn cookies and extract user profile information

        Args:
            li_at: LinkedIn authentication token
            jsessionid: LinkedIn session ID
            tenant_id: Optional tenant ID for audit logging
            user_id: Optional user ID for audit logging

        Returns:
            CookieVerificationResult with verification status and user data
        """

        verification_start = time.time()

        if self.verifier_mode == "disabled":
            logger.warning("LinkedIn cookie verification disabled: %s", self.mode_reason)
            return CookieVerificationResult(
                status=VerificationStatus.NETWORK_ERROR,
                error_message=self.mode_reason,
            )

        try:
            # Apply rate limiting
            await self._apply_rate_limiting()

            if self.verifier_mode == "api":
                return await self._verify_via_api(
                    li_at=li_at,
                    jsessionid=jsessionid,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    verification_start=verification_start,
                )

            # Ensure browser is ready
            await self._ensure_browser_ready()

            # Create a new page for this verification
            page = await self.context.new_page()

            try:
                # Set LinkedIn cookies
                await page.context.add_cookies([
                    {
                        "name": "li_at",
                        "value": li_at,
                        "domain": ".linkedin.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "None"
                    },
                    {
                        "name": "JSESSIONID",
                        "value": jsessionid,
                        "domain": ".www.linkedin.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "None"
                    }
                ])

                logger.info("Attempting LinkedIn cookie verification...")

                # Navigate to LinkedIn feed
                await page.goto("https://www.linkedin.com/feed/",
                              wait_until="domcontentloaded",
                              timeout=30000)

                await self._human_delay(3, 6)

                # Check if we're redirected to login (invalid cookies)
                current_url = page.url
                if "login" in current_url or "challenge" in current_url:
                    logger.warning("Cookies invalid - redirected to login/challenge")
                    return CookieVerificationResult(
                        status=VerificationStatus.INVALID,
                        error_message="Cookies expired or invalid - redirected to login"
                    )

                # Look for profile elements
                try:
                    # Wait for navigation elements to load
                    await page.wait_for_selector("nav.global-nav", timeout=15000)
                    await self._human_delay(2, 4)

                    # Try to find the "Me" menu button
                    me_button_selectors = [
                        "button[aria-label*='View profile']",
                        "button.global-nav__primary-link--me",
                        "div.global-nav__me > button",
                        "img.global-nav__me-photo",
                        "a.global-nav__primary-link--me-menu-trigger"
                    ]

                    me_button = None
                    for selector in me_button_selectors:
                        try:
                            me_button = await page.wait_for_selector(selector, timeout=5000)
                            if me_button:
                                break
                        except:
                            continue

                    if not me_button:
                        logger.warning("Could not find profile menu button")
                        return CookieVerificationResult(
                            status=VerificationStatus.INVALID,
                            error_message="Could not locate profile menu - possibly invalid session"
                        )

                    # Click on the Me menu
                    await me_button.click()
                    await self._human_delay(2, 4)

                    # Look for profile information in the dropdown
                    profile_selectors = [
                        "div.global-nav__me-content a[href*='/in/']",
                        "a[data-control-name='identity_welcome_message']",
                        "div.global-nav__me-content div.text-heading-small",
                        "div.global-nav__me-content .t-16"
                    ]

                    username = None
                    full_name = None
                    profile_url = None

                    # Extract profile URL and username
                    for selector in profile_selectors:
                        try:
                            profile_link = await page.query_selector(selector)
                            if profile_link:
                                href = await profile_link.get_attribute("href")
                                if href and "/in/" in href:
                                    profile_url = href
                                    # Extract username from URL
                                    username = href.rstrip('/').split('/')[-1]
                                    break
                        except:
                            continue

                    # Extract full name from profile area
                    name_selectors = [
                        "div.global-nav__me-content .text-heading-small",
                        "div.global-nav__me-content .t-16.t-black.t-bold",
                        "div.global-nav__me-content strong",
                        "span.text-heading-small"
                    ]

                    for selector in name_selectors:
                        try:
                            name_element = await page.query_selector(selector)
                            if name_element:
                                text = await name_element.inner_text()
                                if text and text.strip() and len(text.strip()) > 2:
                                    full_name = text.strip()
                                    break
                        except:
                            continue

                    # Try alternative method - go to profile page directly
                    if not username or not full_name:
                        try:
                            await page.goto("https://www.linkedin.com/in/me/", timeout=15000)
                            await self._human_delay(2, 4)

                            # Get username from URL
                            current_url = page.url
                            if "/in/" in current_url:
                                username = current_url.split("/in/")[-1].rstrip('/')

                            # Get name from profile page
                            name_selectors_profile = [
                                "h1.text-heading-xlarge",
                                "h1.pv-top-card--list h1",
                                ".pv-text-details__left-panel h1"
                            ]

                            for selector in name_selectors_profile:
                                try:
                                    name_elem = await page.wait_for_selector(selector, timeout=5000)
                                    if name_elem:
                                        full_name = (await name_elem.inner_text()).strip()
                                        break
                                except:
                                    continue

                        except Exception as e:
                            logger.debug(f"Could not access profile page: {e}")

                    # Validate results
                    if username and full_name:
                        verification_time = time.time() - verification_start

                        result = CookieVerificationResult(
                            status=VerificationStatus.VALID,
                            username=username,
                            full_name=full_name,
                            profile_url=f"https://www.linkedin.com/in/{username}/" if username else None
                        )

                        # Log successful verification
                        logger.info(f"✅ Cookie verification successful: {full_name} (@{username}) in {verification_time:.2f}s")

                        # Audit log
                        if tenant_id and user_id:
                            await audit_logger.log_event(
                                event_type=AuditEventType.AUTHENTICATION,
                                actor_type="user",
                                actor_id=str(user_id),
                                target_type="linkedin_session",
                                target_id=f"verification_{username}",
                                organization_id=tenant_id,
                                details={
                                    "action": "cookie_verification",
                                    "status": "success",
                                    "username": username,
                                    "verification_time_ms": int(verification_time * 1000)
                                },
                                severity=AuditSeverity.INFO
                            )

                        return result

                    else:
                        logger.warning("Could not extract complete profile information")
                        return CookieVerificationResult(
                            status=VerificationStatus.INVALID,
                            error_message="Could not extract profile information - session may be limited"
                        )

                except Exception as e:
                    logger.error(f"Error during profile extraction: {e}")
                    return CookieVerificationResult(
                        status=VerificationStatus.INVALID,
                        error_message=f"Profile extraction failed: {str(e)}"
                    )

            finally:
                await page.close()

        except Exception as e:
            logger.error(f"LinkedIn cookie verification failed: {e}")

            # Audit log failure
            if tenant_id and user_id:
                try:
                    await audit_logger.log_event(
                        event_type=AuditEventType.AUTHENTICATION,
                        actor_type="user",
                        actor_id=str(user_id),
                        target_type="linkedin_session",
                        target_id="verification_failed",
                        organization_id=tenant_id,
                        details={
                            "action": "cookie_verification",
                            "status": "failed",
                            "error": str(e)
                        },
                        severity=AuditSeverity.WARNING
                    )
                except:
                    pass  # Don't fail on audit logging issues

            return CookieVerificationResult(
                status=VerificationStatus.NETWORK_ERROR,
                error_message=f"Verification failed: {str(e)}"
            )

    async def cleanup(self) -> None:
        """Clean up browser resources"""
        try:
            if self.context:
                await self.context.close()
                self.context = None
            if self.browser:
                await self.browser.close()
                self.browser = None
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.cleanup()

# Global instance for service reuse
_verifier_instance: Optional[_LinkedInCookieVerifier] = None

async def get_cookie_verifier() -> _LinkedInCookieVerifier:
    """Get or create the global cookie verifier instance"""
    global _verifier_instance
    if _verifier_instance is None:
        _verifier_instance = _LinkedInCookieVerifier()
    if _verifier_instance.verifier_mode == "playwright" and async_playwright is None:
        raise RuntimeError(
            "Playwright is required for LinkedIn cookie verification. "
            f"{FALLBACK_HINT}"
        ) from _PLAYWRIGHT_IMPORT_ERROR
    return _verifier_instance

async def verify_linkedin_cookies(
    li_at: str,
    jsessionid: str,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None
) -> CookieVerificationResult:
    """
    Convenience function for cookie verification

    Args:
        li_at: LinkedIn authentication token
        jsessionid: LinkedIn session ID
        tenant_id: Optional tenant ID for audit logging
        user_id: Optional user ID for audit logging

    Returns:
        CookieVerificationResult with verification status and user data
    """
    verifier = await get_cookie_verifier()
    return await verifier.verify_linkedin_cookies(li_at, jsessionid, tenant_id, user_id)


def get_cookie_verifier_health() -> Dict[str, Any]:
    """Return readiness metadata for cookie verification services."""

    mode, reason = determine_verifier_mode()
    return {
        "provider": "cookie_verifier",
        "configured": mode != "disabled",
        "mode": mode,
        "reason": reason,
        "playwrightAvailable": async_playwright is not None,
        "apiConfigured": bool(os.getenv("LINKEDIN_COOKIE_VERIFIER_API")),
    }


if async_playwright is None:
    LinkedInCookieVerifier = None  # type: ignore[assignment]
else:
    LinkedInCookieVerifier = _LinkedInCookieVerifier  # type: ignore[assignment]