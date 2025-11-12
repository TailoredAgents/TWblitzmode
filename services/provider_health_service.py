from __future__ import annotations

import os
from typing import Any, Dict, Optional

from integrations.apify_client import get_tenant_integration_settings, get_deferred_apify_runs
from integrations.cufinder_client import get_deferred_cufinder_requests
from services.cookie_vault_service import CookieVaultService
from services.linkedin_cookie_verifier import get_cookie_verifier_health

# Note: Stripe and SendGrid connection testing removed for stability
# Status checking only validates configuration presence


def _get_tenant_setting(
    tenant_settings: Dict[str, str],
    key: str,
    env_fallback: Optional[str] = None,
) -> Optional[str]:
    value = tenant_settings.get(key)
    if value and isinstance(value, str):
        return value.strip() or None
    if env_fallback:
        env_value = os.getenv(env_fallback, "").strip()
        return env_value or None
    return None


def _build_cufinder_status(tenant_id: int) -> Dict[str, Any]:
    tenant_settings = get_tenant_integration_settings(tenant_id)

    tenant_key = _get_tenant_setting(tenant_settings, "cufinder_api_key")
    env_key = _get_tenant_setting({}, "", "CUFINDER_API_KEY")

    if tenant_key:
        source = "tenant"
        configured = True
    elif env_key:
        source = "environment"
        configured = True
    else:
        source = "missing"
        configured = False

    message = (
        "CUFinder is ready for enrichment requests."
        if configured
        else "Provide a CUFinder API key in Settings → Integrations to enable email enrichment."
    )

    pending = get_deferred_cufinder_requests(tenant_id)

    return {
        "provider": "cufinder",
        "configured": configured,
        "source": source,
        "message": message,
        "pendingRequests": pending["pending"],
        "lastRequest": pending["latest"],
    }


def _build_cookie_vault_status() -> Dict[str, Any]:
    try:
        service = CookieVaultService()
        health = service.get_health_status()
        configured = True
        message = "Cookie vault is running in plaintext mode; no encryption keys required."
        return {
            **health,
            "configured": configured,
            "message": message,
        }
    except Exception as exc:
        return {
            "provider": "cookie_vault",
            "configured": False,
            "keyConfigured": False,
            "kmsEnabled": False,
            "keySource": None,
            "message": str(exc),
        }


def _build_cookie_verifier_status() -> Dict[str, Any]:
    health = get_cookie_verifier_health()
    if health.get("configured"):
        if health.get("mode") == "playwright":
            message = "Playwright browser verification available."
        else:
            message = "Using external LinkedIn verification API."
    else:
        message = health.get("reason")

    health["message"] = message
    return health


def _build_apify_status(tenant_id: int) -> Dict[str, Any]:
    tenant_settings = get_tenant_integration_settings(tenant_id)

    token = _get_tenant_setting(tenant_settings, "apify_token", "APIFY_TOKEN")
    li_at = _get_tenant_setting(tenant_settings, "linkedin_li_at", "LINKEDIN_LI_AT")
    jsessionid = _get_tenant_setting(
        tenant_settings,
        "linkedin_jsessionid",
        "LINKEDIN_JSESSIONID",
    )

    configured = bool(token)
    cookies_configured = bool(li_at and jsessionid)

    if not configured:
        message = "Add an Apify API token to enable LinkedIn mutual-connection discovery."
        source = "missing"
        disabled_reason = message
    else:
        source = "tenant" if tenant_settings.get("apify_token") else "environment"
        disabled_reason = None
        if cookies_configured:
            message = "Apify is ready with LinkedIn cookies configured."
        else:
            message = (
                "Apify API token is set, but LinkedIn cookies are missing. "
                "Upload `li_at` and `JSESSIONID` to run LinkedIn workflows."
            )

    pending = get_deferred_apify_runs(tenant_id)

    return {
        "provider": "apify",
        "configured": configured,
        "cookiesConfigured": cookies_configured,
        "source": source,
        "message": message,
        "disabledReason": disabled_reason,
        "pendingRuns": pending["pending"],
        "lastRun": pending["latest"],
    }


def _build_email_service_status(tenant_id: int) -> Dict[str, Any]:
    tenant_settings = get_tenant_integration_settings(tenant_id)

    # Check for SendGrid API key
    api_key = _get_tenant_setting(tenant_settings, "sendgrid_api_key", "SENDGRID_API_KEY")
    from_email = _get_tenant_setting(tenant_settings, "sendgrid_from_email", "SENDGRID_FROM_EMAIL")

    if not api_key:
        return {
            "provider": "email_service",
            "configured": False,
            "message": "Add SendGrid API key to enable email sending",
            "source": "missing"
        }

    # For now, just check if the key is configured - actual connection testing
    # can be added later when sendgrid integration is fully stable
    source = "tenant" if tenant_settings.get("sendgrid_api_key") else "environment"
    from_configured = bool(from_email)

    message = (
        "Email service is ready for sending" if from_configured
        else "SendGrid API configured - set from_email for complete setup"
    )

    return {
        "provider": "email_service",
        "configured": True,
        "fromEmailConfigured": from_configured,
        "source": source,
        "message": message,
        "fromEmail": from_email if from_configured else None
    }


async def get_provider_health(tenant_id: int) -> Dict[str, Dict[str, Any]]:
    """
    Return provider readiness metadata for the settings dashboard.
    """
    return {
        "cufinder": _build_cufinder_status(tenant_id),
        "apify": _build_apify_status(tenant_id),
        "cookieVault": _build_cookie_vault_status(),
        "cookieVerifier": _build_cookie_verifier_status(),
        "emailService": _build_email_service_status(tenant_id),
    }
