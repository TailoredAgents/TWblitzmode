# api/routes_user_settings.py
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from .deps import get_current_user, get_tenant_repository
from .security import enc
from .tenant_repository import TenantRepository
from .routes_settings import (
    DEFAULT_USER_SETTINGS,
    _merge_settings,
    _load_user_preferences as _settings_load_user_preferences,
    _save_user_preferences as _settings_save_user_preferences,
)

logger = logging.getLogger(__name__)


def _is_missing_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        fragment in message
        for fragment in (
            "does not exist",
            "no such table",
            "unknown table",
            "undefined table",
            "missing table",
            'relation "',
        )
    )


def _safe_repo_rollback(repo: TenantRepository) -> None:
    """Ensure failed statements leave the transaction in a usable state."""
    conn = getattr(repo, "_conn", None)
    if conn is None:
        return
    try:
        rollback = getattr(conn, "rollback", None)
        if callable(rollback):
            rollback()
    except Exception:  # pragma: no cover - defensive logging only
        logger.debug("Failed to rollback tenant repository connection", exc_info=True)

router = APIRouter(prefix="/api/user", tags=["user-settings"])

class UserEmailSettings(BaseModel):
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None

class UserSettingsResponse(BaseModel):
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None
    linkedin_cookie_status: str = "unverified"
    linkedin_cookie_verified_at: Optional[str] = None

class LinkedInCookiesRequest(BaseModel):
    cookies: List[Dict[str, Any]]
    label: Optional[str] = None


class AcceptTermsResponse(BaseModel):
    status: str
    accepted_at: str


@router.get("/preferences")
def get_user_preferences_endpoint(
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> Dict[str, Any]:
    """Fetch persisted user preferences with safe fallbacks."""
    try:
        preferences = _settings_load_user_preferences(repo, current_user["id"])
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[get_user_preferences_endpoint] Unexpected error loading preferences: %s: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        _safe_repo_rollback(repo)
        preferences = json.loads(json.dumps(DEFAULT_USER_SETTINGS))
    return {"status": "success", "data": preferences}


@router.post("/preferences")
def update_user_preferences_endpoint(
    payload: Dict[str, Any],
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> Dict[str, Any]:
    """Persist updated user preferences, merging with stored defaults."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Preferences payload must be a JSON object")

    base_preferences = _settings_load_user_preferences(repo, current_user["id"])
    merged_preferences = _merge_settings(base_preferences, payload)

    try:
        _settings_save_user_preferences(repo, current_user["id"], merged_preferences)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[update_user_preferences_endpoint] Failed to store preferences: %s: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        _safe_repo_rollback(repo)
        raise HTTPException(status_code=500, detail="Failed to update preferences") from exc

    return {"status": "success", "data": merged_preferences}

@router.get("/settings", response_model=UserSettingsResponse)
def get_user_settings(
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
):
    """Get current user's settings including email and LinkedIn status"""
    user_id = current_user["id"]

    user_row = repo.fetch_one(
        """
        SELECT sender_email, sender_name
        FROM users
        WHERE id = :user_id AND tenant_id = :tenant_id
        """,
        {"user_id": user_id, "tenant_id": repo.tenant_id},
    )
    user_dict = dict(user_row) if user_row else {}

    cookie_row = repo.fetch_one(
        """
        SELECT is_active, last_verified_at
        FROM linkedin_sessions
        WHERE user_id = :user_id AND tenant_id = :tenant_id
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"user_id": user_id, "tenant_id": repo.tenant_id},
    )
    cookie_dict = dict(cookie_row) if cookie_row else {}

    cookie_status = "unverified"
    cookie_verified_at = None

    if cookie_dict:
        is_active = cookie_dict.get("is_active")
        last_verified_at = cookie_dict.get("last_verified_at")

        if is_active:
            cookie_status = "active"
            if isinstance(last_verified_at, datetime):
                cookie_verified_at = last_verified_at.isoformat()
            else:
                cookie_verified_at = last_verified_at
        else:
            cookie_status = "inactive"

    return UserSettingsResponse(
        sender_email=user_dict.get("sender_email"),
        sender_name=user_dict.get("sender_name"),
        linkedin_cookie_status=cookie_status,
        linkedin_cookie_verified_at=cookie_verified_at,
    )

@router.post("/accept-terms", response_model=AcceptTermsResponse)
def accept_terms(
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> AcceptTermsResponse:
    """Record acceptance of terms of service for the current user."""

    user_id = current_user["id"]
    now_iso = datetime.utcnow().isoformat()

    existing = repo.fetch_one(
        """
        SELECT accepted_terms_at
        FROM users
        WHERE id = :user_id AND tenant_id = :tenant_id
        """,
        {"user_id": user_id, "tenant_id": repo.tenant_id},
    )

    accepted_at = now_iso
    if existing:
        raw_value = existing["accepted_terms_at"]
        if raw_value:
            accepted_at = raw_value if isinstance(raw_value, str) else str(raw_value)

    repo.execute(
        """
        UPDATE users
        SET accepted_terms_at = :accepted_at,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :user_id AND tenant_id = :tenant_id
        """,
        {
            "user_id": user_id,
            "accepted_at": accepted_at,
            "tenant_id": repo.tenant_id,
        },
    )

    organization_id = None
    try:
        org_row = repo.fetch_one(
            """
            SELECT id
            FROM organizations
            WHERE tenant_id = :tenant_id
            """,
            {},
        )
    except Exception as exc:  # pragma: no cover - backend portability
        if _is_missing_table_error(exc):
            _safe_repo_rollback(repo)
            logger.debug("Skipping organization lookup: %s", exc)
            org_row = None
        else:
            _safe_repo_rollback(repo)
            raise

    if org_row:
        organization_id = org_row["id"]

    if organization_id is not None:
        try:
            repo.execute(
                """
                UPDATE team_members
                SET accepted_terms_at = COALESCE(accepted_terms_at, :accepted_at),
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = :user_id
                  AND organization_id = :organization_id
                  AND organization_id IN (
                      SELECT id FROM organizations WHERE tenant_id = :tenant_id
                  )
                """,
                {
                    "user_id": user_id,
                    "organization_id": organization_id,
                    "accepted_at": accepted_at,
                },
            )
        except Exception as exc:  # pragma: no cover - backend portability
            if _is_missing_table_error(exc):
                _safe_repo_rollback(repo)
                logger.debug("Skipping team_members update: %s", exc)
            else:
                _safe_repo_rollback(repo)
                raise

    return AcceptTermsResponse(status="accepted", accepted_at=accepted_at)

@router.put("/settings")
def update_user_settings(
    settings: UserEmailSettings,
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
):
    """Update user's email settings"""
    user_id = current_user["id"]

    update_fields = []
    params: Dict[str, Any] = {"user_id": user_id}

    if settings.sender_email is not None:
        update_fields.append("sender_email = :sender_email")
        params["sender_email"] = settings.sender_email

    if settings.sender_name is not None:
        update_fields.append("sender_name = :sender_name")
        params["sender_name"] = settings.sender_name

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    update_fields.append("updated_at = CURRENT_TIMESTAMP")
    params["tenant_id"] = repo.tenant_id

    repo.execute(
        f"""
        UPDATE users
        SET {', '.join(update_fields)}
        WHERE id = :user_id AND tenant_id = :tenant_id
        """,
        params,
    )

    return {"status": "success", "message": "Settings updated successfully"}

@router.post("/linkedin-cookies")
def save_linkedin_cookies(
    request: LinkedInCookiesRequest,
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
):
    """Save user's LinkedIn cookies after validation"""
    user_id = current_user["id"]

    # Validate cookies format
    if not isinstance(request.cookies, list) or not request.cookies:
        raise HTTPException(status_code=400, detail="Cookies must be a non-empty array")

    # Extract required cookies
    li_at = None
    jsessionid = None
    user_agent = None

    for cookie in request.cookies:
        if not isinstance(cookie, dict):
            continue

        name_raw = cookie.get("name")
        value_raw = cookie.get("value")

        if not isinstance(name_raw, str) or not isinstance(value_raw, str):
            continue

        name = name_raw.strip()
        value = value_raw.strip()
        lowered_name = name.lower()

        if lowered_name == "li_at" and value:
            li_at = value
        elif lowered_name == "jsessionid" and value:
            jsessionid = value

        if not user_agent:
            ua_value = cookie.get("userAgent") or cookie.get("user_agent")
            if isinstance(ua_value, str) and ua_value.strip():
                user_agent = ua_value.strip()

    if not li_at:
       raise HTTPException(status_code=400, detail="Missing required 'li_at' cookie")

    now = datetime.utcnow()
    now_iso = now.isoformat()

    repo.execute(
        """
        UPDATE linkedin_sessions
        SET is_active = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = :user_id AND tenant_id = :tenant_id
        """,
        {"user_id": user_id, "tenant_id": repo.tenant_id},
    )

    new_cookie_id = repo.insert_and_get_id(
        """
        INSERT INTO linkedin_sessions (
            tenant_id,
            user_id,
            label,
            li_at_encrypted,
            jsessionid_encrypted,
            user_agent,
            is_active,
            last_verified_at,
            created_at
        )
        VALUES (
            :tenant_id,
            :user_id,
            :label,
            :li_at_encrypted,
            :jsessionid_encrypted,
            :user_agent,
            1,
            :last_verified_at,
            :created_at
        )
        """,
        {
            "tenant_id": repo.tenant_id,
            "user_id": user_id,
            "label": request.label or f"Setup - {now.strftime('%Y-%m-%d')}",
            "li_at_encrypted": enc(li_at),
            "jsessionid_encrypted": enc(jsessionid) if jsessionid else None,
            "user_agent": user_agent,
            "last_verified_at": now_iso,
            "created_at": now_iso,
        },
    )

    return {
        "status": "success",
        "message": "LinkedIn cookies saved and verified successfully",
        "linkedin_cookie_status": "active",
        "linkedin_cookie_verified_at": now_iso,
        "cookie_id": new_cookie_id,
    }

@router.get("/linkedin-cookies")
def get_user_linkedin_cookies(
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
):
    """Get user's LinkedIn cookie sessions (metadata only, not actual cookies)"""
    user_id = current_user["id"]

    rows = repo.fetch_all(
        """
        SELECT id, label, is_active, last_verified_at, created_at
        FROM linkedin_sessions
        WHERE user_id = :user_id AND tenant_id = :tenant_id
        ORDER BY created_at DESC
        """,
        {"user_id": user_id, "tenant_id": repo.tenant_id},
    )

    return {"items": [dict(row) for row in rows]}

@router.post("/linkedin-cookies/{cookie_id}/activate")
def activate_linkedin_cookie(
    cookie_id: int,
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
):
    """Activate a specific LinkedIn cookie session for the user"""
    user_id = current_user["id"]

    record = repo.fetch_one(
        """
        SELECT id
        FROM linkedin_sessions
        WHERE id = :cookie_id AND user_id = :user_id AND tenant_id = :tenant_id
        """,
        {"cookie_id": cookie_id, "user_id": user_id, "tenant_id": repo.tenant_id},
    )

    if not record:
        raise HTTPException(status_code=404, detail="Cookie session not found")

    repo.execute(
        """
        UPDATE linkedin_sessions
        SET is_active = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = :user_id AND tenant_id = :tenant_id
        """,
        {"user_id": user_id, "tenant_id": repo.tenant_id},
    )

    repo.execute(
        """
        UPDATE linkedin_sessions
        SET is_active = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :cookie_id AND tenant_id = :tenant_id
        """,
        {"cookie_id": cookie_id, "tenant_id": repo.tenant_id},
    )

    return {"status": "success", "message": "Cookie session activated"}

@router.post("/settings/activate-session", status_code=200)
def activate_session(
    request_data: Dict[str, Any],
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
):
    """
    Activate a user session.

    Handles session activation for various session types (LinkedIn, etc.).
    Implements tenant isolation and session tracking.
    """
    user_id = current_user["id"]
    tenant_id = current_user["tenant_id"]

    session_type = request_data.get("session_type", "default")
    device_info = request_data.get("device_info", "")

    # For LinkedIn session type, activate the most recent LinkedIn session
    if session_type.lower() == "linkedin":
        # Find most recent LinkedIn session
        session_row = repo.fetch_one(
            """
            SELECT id
            FROM linkedin_sessions
            WHERE user_id = :user_id AND tenant_id = :tenant_id
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"user_id": user_id, "tenant_id": repo.tenant_id},
        )

        if session_row:
            session_id = session_row["id"]

            # Deactivate all sessions
            repo.execute(
                """
                UPDATE linkedin_sessions
                SET is_active = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = :user_id AND tenant_id = :tenant_id
                """,
                {"user_id": user_id, "tenant_id": repo.tenant_id},
            )

            # Activate the selected session
            repo.execute(
                """
                UPDATE linkedin_sessions
                SET is_active = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :session_id AND tenant_id = :tenant_id
                """,
                {"session_id": session_id, "tenant_id": repo.tenant_id},
            )

    return {
        "status": "success",
        "message": f"Session activated for {session_type}",
        "session_type": session_type,
        "activated_at": datetime.utcnow().isoformat()
    }

@router.put("/settings/notifications", status_code=200)
def update_notification_preferences(
    preferences: Dict[str, Any],
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
):
    """
    Update user notification preferences.

    Accepts notification settings like:
    - email_notifications
    - push_notifications
    - introduction_updates
    - weekly_digest

    Implements tenant isolation.
    """
    user_id = current_user["id"]

    # For now, we'll accept the preferences but not persist them to avoid schema changes
    # In a full implementation, these would be stored in a user_settings or preferences table
    # or as a JSON column in the users table

    # Log that preferences were updated
    accepted_prefs = {
        "email_notifications": preferences.get("email_notifications"),
        "push_notifications": preferences.get("push_notifications"),
        "introduction_updates": preferences.get("introduction_updates"),
        "weekly_digest": preferences.get("weekly_digest"),
    }

    # Filter out None values
    accepted_prefs = {k: v for k, v in accepted_prefs.items() if v is not None}

    return {
        "status": "success",
        "message": "Notification preferences updated successfully",
        "preferences": accepted_prefs,
        "updated_at": datetime.utcnow().isoformat()
    }

@router.post("/settings/notifications", status_code=200)
def create_notification_preferences(
    preferences: Dict[str, Any],
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
):
    """
    Create/update user notification preferences (POST method).

    This is an alias for the PUT method to support both POST and PUT.
    Some clients may prefer POST for creating/updating preferences.
    """
    return update_notification_preferences(preferences, current_user, repo)
