from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, ConfigDict

from core.roles import is_admin, normalize_role

from .deps import get_current_user, get_tenant_repository
from .tenant_repository import TenantRepository
from .security import enc, dec
from services.provider_health_service import get_provider_health as fetch_provider_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class NotificationSettings(BaseModel):
    email: bool = True
    browser: bool = True
    workflows: bool = True
    approvals: bool = True
    system: bool = False


class UserSettingsPayload(BaseModel):
    timezone: str = Field(default="UTC", max_length=64)
    language: str = Field(default="en", max_length=32)
    theme: str = Field(default="dark")
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    model_config = ConfigDict(extra="ignore")

    @field_validator("theme")
    @classmethod
    def validate_theme(cls, value: str) -> str:
        allowed = {"light", "dark", "auto"}
        if value not in allowed:
            raise ValueError(f"Theme must be one of {', '.join(sorted(allowed))}")
        return value


    @field_validator("email")
    @classmethod
    def validate_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        candidate = value.strip()
        if not candidate:
            return None
        if "@" not in candidate or candidate.startswith("@") or candidate.endswith("@"):
            raise ValueError("Invalid email address")
        return candidate


class UserSettingsResponse(UserSettingsPayload):
    id: int
    email: str
    name: str
    role: str


class SystemSettingsPayload(BaseModel):
    auto_approval_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    max_concurrent_workflows: int = Field(default=10, ge=1, le=1000)
    workflow_timeout_minutes: int = Field(default=30, ge=1, le=1440)
    rate_limit_per_minute: int = Field(default=100, ge=1, le=10000)
    debug_mode: bool = False
    audit_logging: bool = True
    data_retention_days: int = Field(default=90, ge=1, le=1825)
    backup_frequency_hours: int = Field(default=24, ge=1, le=168)
    model_config = ConfigDict(extra="ignore")


class SecuritySettingsPayload(BaseModel):
    session_timeout_minutes: int = Field(default=480, ge=5, le=2880)
    require_2fa: bool = False
    password_expiry_days: int = Field(default=90, ge=0, le=365)
    max_failed_attempts: int = Field(default=5, ge=1, le=20)
    ip_whitelist_enabled: bool = False
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:3001"])
    model_config = ConfigDict(extra="ignore")


class CredentialSettingsPayload(BaseModel):
    openai_api_key: Optional[str] = ""
    apify_api_token: Optional[str] = ""
    cufinder_api_key: Optional[str] = ""
    sendgrid_api_key: Optional[str] = ""
    phantombuster_api_key: Optional[str] = ""
    linkedin_li_at: Optional[str] = ""
    model_config = ConfigDict(extra="ignore")


class CredentialStatus(BaseModel):
    configured: bool = False
    masked: Optional[str] = None


class CredentialSettingsResponse(BaseModel):
    openai_api_key: CredentialStatus = Field(default_factory=CredentialStatus)
    apify_api_token: CredentialStatus = Field(default_factory=CredentialStatus)
    cufinder_api_key: CredentialStatus = Field(default_factory=CredentialStatus)
    sendgrid_api_key: CredentialStatus = Field(default_factory=CredentialStatus)
    phantombuster_api_key: CredentialStatus = Field(default_factory=CredentialStatus)
    linkedin_li_at: CredentialStatus = Field(default_factory=CredentialStatus)


DEFAULT_USER_SETTINGS: Dict[str, Any] = {
    "timezone": "UTC",
    "language": "en",
    "theme": "dark",
    "notifications": {
        "email": True,
        "browser": True,
        "workflows": True,
        "approvals": True,
        "system": False,
    },
}

DEFAULT_SYSTEM_SETTINGS: Dict[str, Any] = {
    "auto_approval_threshold": 0.8,
    "max_concurrent_workflows": 10,
    "workflow_timeout_minutes": 30,
    "rate_limit_per_minute": 100,
    "debug_mode": False,
    "audit_logging": True,
    "data_retention_days": 90,
    "backup_frequency_hours": 24,
}

DEFAULT_SECURITY_SETTINGS: Dict[str, Any] = {
    "session_timeout_minutes": 480,
    "require_2fa": False,
    "password_expiry_days": 90,
    "max_failed_attempts": 5,
    "ip_whitelist_enabled": False,
    "cors_origins": ["http://localhost:3000", "http://localhost:3001"],
}

_CREDENTIAL_KEY_MAP: Dict[str, Dict[str, Any]] = {
    "openai_api_key": {"key": "openai_api_key", "encrypted": True},
    "apify_api_token": {"key": "apify_token", "encrypted": True},
    "cufinder_api_key": {"key": "cufinder_api_key", "encrypted": True},
    "sendgrid_api_key": {"key": "sendgrid_api_key", "encrypted": True},
    "phantombuster_api_key": {"key": "phantombuster_api_key", "encrypted": True},
    "linkedin_li_at": {"key": "linkedin_li_at", "encrypted": True},
}


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


def _is_poisoned_transaction_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "current transaction is aborted" in message or "infailedsqltransaction" in message


def _safe_repo_rollback(repo: TenantRepository) -> None:
    conn = getattr(repo, "_conn", None)
    if conn is None:
        return
    try:
        rollback = getattr(conn, "rollback", None)
        if callable(rollback):
            rollback()
    except Exception:
        logger.debug("[settings] Failed to rollback tenant repository connection", exc_info=True)


@router.get("/service-health")
async def get_service_health(
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Provide real provider readiness metadata for the settings dashboard.

    Uses the shared provider health service which inspects tenant configuration,
    pending background jobs, and cookie vault readiness without relying on mocks.
    """
    providers = await fetch_provider_health(current_user["tenant_id"])
    return {
        "status": "success",
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "data": {
            "tenant_id": current_user["tenant_id"],
            "providers": providers,
        },
    }


def _merge_settings(defaults: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge override dict into defaults without mutating defaults."""
    result: Dict[str, Any] = {}
    override = override or {}
    for key, default_value in defaults.items():
        if isinstance(default_value, dict):
            override_section = override.get(key, {}) if isinstance(override.get(key), dict) else {}
            result[key] = _merge_settings(default_value, override_section)
        else:
            result[key] = override.get(key, default_value)
    # Include any additional keys that may have been stored previously
    for key, value in override.items():
        if key not in result:
            result[key] = value
    return result


def _split_display_name(full_name: str) -> tuple[str, Optional[str]]:
    tokens = [segment for segment in (full_name or "").strip().split(" ") if segment]
    if not tokens:
        return "", None
    if len(tokens) == 1:
        return tokens[0], None
    return tokens[0], " ".join(tokens[1:])


def _ensure_user_preferences_table(repo: TenantRepository) -> None:
    connection = getattr(repo, "_conn", None)
    if connection is None:
        return

    is_sqlite_backend = isinstance(connection, sqlite3.Connection)

    if is_sqlite_backend:
        create_table_sql = """
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                preferences TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, user_id)
            )
            """
    else:
        create_table_sql = """
            CREATE TABLE IF NOT EXISTS user_preferences (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                preferences TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, user_id)
            )
            """

    try:
        repo.execute_ddl(create_table_sql)
        repo.execute_ddl(
            """
            CREATE INDEX IF NOT EXISTS idx_user_preferences_tenant
            ON user_preferences(tenant_id)
            """
        )
        repo.execute_ddl(
            """
            CREATE INDEX IF NOT EXISTS idx_user_preferences_user
            ON user_preferences(user_id)
            """
        )
    except Exception:
        logger.debug(
            "Skipping user_preferences bootstrap (handled by migrations or already present)",
            exc_info=True,
        )
        _safe_repo_rollback(repo)


async def _require_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    role = normalize_role(current_user.get("role"))
    if not is_admin(role):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


def _load_user_preferences(repo: TenantRepository, user_id: int) -> Dict[str, Any]:
    logger.debug(f"[_load_user_preferences] Loading preferences for user_id={user_id}")
    _ensure_user_preferences_table(repo)
    row = None
    try:
        logger.debug(f"[_load_user_preferences] Fetching preferences from database for user_id={user_id}")
        row = repo.fetch_one(
            """
            SELECT preferences
            FROM user_preferences
            WHERE tenant_id = :tenant_id AND user_id = :user_id
            """,
            {"user_id": user_id, "tenant_id": repo.tenant_id},
        )
        if not row or not row["preferences"]:
            logger.debug(f"[_load_user_preferences] No preferences found for user_id={user_id}, using defaults")
            return json.loads(json.dumps(DEFAULT_USER_SETTINGS))
    except Exception as exc:
        logger.error(
            f"[_load_user_preferences] Failed to load preferences for user_id={user_id}: {type(exc).__name__}: {str(exc)}",
            exc_info=True,
        )
        _safe_repo_rollback(repo)
        if _is_missing_table_error(exc):
            logger.debug(
                "[_load_user_preferences] user_preferences table unavailable; returning defaults for user_id=%s",
                user_id,
            )
            return json.loads(json.dumps(DEFAULT_USER_SETTINGS))
        if _is_poisoned_transaction_error(exc):
            logger.debug(
                "[_load_user_preferences] Retrying after poisoned transaction for user_id=%s",
                user_id,
            )
            row = repo.fetch_one(
                """
                SELECT preferences
                FROM user_preferences
                WHERE tenant_id = :tenant_id AND user_id = :user_id
                """,
                {"user_id": user_id, "tenant_id": repo.tenant_id},
            )
            if not row or not row["preferences"]:
                return json.loads(json.dumps(DEFAULT_USER_SETTINGS))
        else:
            raise

    try:
        stored = json.loads(row["preferences"])
    except (TypeError, ValueError):
        stored = {}

    return _merge_settings(DEFAULT_USER_SETTINGS, stored)


def _save_user_preferences(repo: TenantRepository, user_id: int, payload: Dict[str, Any]) -> None:
    def _persist() -> None:
        repo.execute(
            """
            DELETE FROM user_preferences
            WHERE tenant_id = :tenant_id AND user_id = :user_id
            """,
            {"user_id": user_id, "tenant_id": repo.tenant_id},
        )
        repo.execute(
            """
            INSERT INTO user_preferences (tenant_id, user_id, preferences, created_at, updated_at)
            VALUES (:tenant_id, :user_id, :preferences, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            {"user_id": user_id, "tenant_id": repo.tenant_id, "preferences": json.dumps(payload)},
        )

    _ensure_user_preferences_table(repo)
    try:
        _persist()
    except Exception as exc:
        _safe_repo_rollback(repo)
        if _is_missing_table_error(exc) or _is_poisoned_transaction_error(exc):
            logger.debug(
                "[_save_user_preferences] Reinitialising preferences table after failure for user_id=%s",
                user_id,
            )
            _ensure_user_preferences_table(repo)
            _persist()
        else:
            raise


@router.get("/preferences")
async def get_user_preferences_endpoint(
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> Dict[str, Any]:
    try:
        preferences = _load_user_preferences(repo, current_user["id"])
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
async def update_user_preferences_endpoint(
    payload: Dict[str, Any],
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Preferences payload must be an object")

    base_preferences = _load_user_preferences(repo, current_user["id"])
    merged_preferences = _merge_settings(base_preferences, payload)

    try:
        _save_user_preferences(repo, current_user["id"], merged_preferences)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[update_user_preferences_endpoint] Failed to persist preferences: %s: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        _safe_repo_rollback(repo)
        raise HTTPException(status_code=500, detail="Failed to update preferences") from exc

    return {"status": "success", "data": merged_preferences}


def _load_tenant_setting(
    repo: TenantRepository,
    *,
    key: str,
    default: Dict[str, Any],
) -> Dict[str, Any]:
    row = repo.fetch_one(
        """
        SELECT setting_value, encrypted
        FROM tenant_settings
        WHERE tenant_id = :tenant_id AND setting_key = :setting_key
        """,
        {"setting_key": key, "tenant_id": repo.tenant_id},
    )
    if not row or not row["setting_value"]:
        return json.loads(json.dumps(default))

    raw_value = row["setting_value"]
    if row["encrypted"]:
        try:
            raw_value = dec(raw_value)
        except Exception:
            raw_value = row["setting_value"]

    try:
        data = json.loads(raw_value)
    except (TypeError, ValueError):
        data = {}

    return _merge_settings(default, data)


def _save_tenant_setting(repo: TenantRepository, *, key: str, payload: Dict[str, Any], encrypted: bool = False) -> None:
    repo.execute(
        """
        DELETE FROM tenant_settings
        WHERE tenant_id = :tenant_id AND setting_key = :setting_key
        """,
        {"setting_key": key, "tenant_id": repo.tenant_id},
    )
    serialized = json.dumps(payload)
    stored_value = enc(serialized) if encrypted else serialized
    repo.execute(
        """
        INSERT INTO tenant_settings (tenant_id, setting_key, setting_value, encrypted, created_at, updated_at)
        VALUES (:tenant_id, :setting_key, :setting_value, :encrypted, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        {
            "tenant_id": repo.tenant_id,
            "setting_key": key,
            "setting_value": stored_value,
            "encrypted": 1 if encrypted else 0,
        },
    )


def _mask_secret(value: str) -> str:
    trimmed = (value or "").strip()
    if not trimmed:
        return ""
    if len(trimmed) <= 4:
        return "•" * len(trimmed)
    return f"{'•' * (len(trimmed) - 4)}{trimmed[-4:]}"


def _load_tenant_secret(repo: TenantRepository, key_descriptor: Dict[str, Any]) -> CredentialStatus:
    row = repo.fetch_one(
        """
        SELECT setting_value, encrypted
        FROM tenant_settings
        WHERE tenant_id = :tenant_id AND setting_key = :setting_key
        """,
        {"setting_key": key_descriptor["key"], "tenant_id": repo.tenant_id},
    )
    if not row or not row["setting_value"]:
        return CredentialStatus(configured=False, masked=None)

    value = row["setting_value"]
    decrypted = value
    should_decrypt = key_descriptor.get("encrypted", False) and row["encrypted"]
    if should_decrypt:
        try:
            decrypted = dec(value)
        except Exception:
            decrypted = ""

    masked = _mask_secret(decrypted)
    return CredentialStatus(configured=bool(decrypted), masked=masked or None)


def _save_tenant_secret(repo: TenantRepository, key_descriptor: Dict[str, Any], value: Optional[str]) -> None:
    repo.execute(
        """
        DELETE FROM tenant_settings
        WHERE tenant_id = :tenant_id AND setting_key = :setting_key
        """,
        {"setting_key": key_descriptor["key"], "tenant_id": repo.tenant_id},
    )
    if value is None:
        return
    trimmed = value.strip()
    if not trimmed:
        return
    stored_value = enc(trimmed) if key_descriptor.get("encrypted") else trimmed
    repo.execute(
        """
        INSERT INTO tenant_settings (tenant_id, setting_key, setting_value, encrypted, created_at, updated_at)
        VALUES (:tenant_id, :setting_key, :setting_value, :encrypted, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        {
            "tenant_id": repo.tenant_id,
            "setting_key": key_descriptor["key"],
            "setting_value": stored_value,
            "encrypted": 1 if key_descriptor.get("encrypted") else 0,
        },
    )


@router.get("/user", response_model=UserSettingsResponse)
async def get_user_settings(
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> UserSettingsResponse:
    user_id = current_user["id"]
    tenant_id = current_user.get("tenant_id", 1)
    logger.debug(f"[get_user_settings] Starting request for user_id={user_id}, tenant_id={tenant_id}")

    try:
        logger.debug(f"[get_user_settings] Fetching user data from database for user_id={user_id}")
        user_row = repo.fetch_one(
            """
            SELECT id, email, first_name, last_name, role
            FROM users
            WHERE id = :user_id AND tenant_id = :tenant_id
            """,
            {"user_id": user_id, "tenant_id": repo.tenant_id},
        )
        if not user_row:
            logger.error(f"[get_user_settings] User not found: user_id={user_id}, tenant_id={tenant_id}")
            raise HTTPException(status_code=404, detail="User not found")

        logger.debug(f"[get_user_settings] User data retrieved successfully for user_id={user_id}")
        user_data = dict(user_row)

        logger.debug(f"[get_user_settings] Loading user preferences for user_id={user_id}")
        preferences = _load_user_preferences(repo, user_id)

        full_name = " ".join(
            part for part in [user_data.get("first_name"), user_data.get("last_name")] if part
        ).strip() or user_data.get("email")

        payload = {
            "id": user_data["id"],
            "email": user_data["email"],
            "name": full_name,
            "role": user_data["role"],
        }
        payload.update(preferences)

        logger.debug(f"[get_user_settings] Successfully retrieved settings for user_id={user_id}")
        return UserSettingsResponse(**payload)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[get_user_settings] Unexpected error for user_id={user_id}: {type(e).__name__}: {str(e)}",
            exc_info=True
        )
        _safe_repo_rollback(repo)
        raise HTTPException(status_code=500, detail="Failed to retrieve user settings")


@router.put("/user")
async def update_user_settings(
    body: UserSettingsPayload,
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> Dict[str, Any]:
    payload = body.model_dump(exclude_none=True)

    preference_keys = {"timezone", "language", "theme", "notifications"}
    preference_override = {
        key: payload[key] for key in preference_keys if key in payload
    }
    preferences_to_store = _merge_settings(DEFAULT_USER_SETTINGS, preference_override)
    _save_user_preferences(repo, current_user["id"], preferences_to_store)

    user_updates: Dict[str, Any] = {}
    has_updated_at = False
    try:
        has_updated_at = repo.table_has_column("users", "updated_at")
    except Exception:
        has_updated_at = False
    name_value = payload.get("name")
    if name_value is not None:
        first_name, last_name = _split_display_name(name_value)
        if first_name:
            user_updates["first_name"] = first_name
        user_updates["last_name"] = last_name

    email_value = payload.get("email")
    if email_value is not None:
        user_updates["email"] = email_value

    if user_updates:
        set_clauses = [f"{column} = :{column}" for column in user_updates.keys()]
        if has_updated_at:
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        params = dict(user_updates)
        params["user_id"] = current_user["id"]
        params["tenant_id"] = repo.tenant_id
        repo.execute(
            f"""
            UPDATE users
            SET {', '.join(set_clauses)}
            WHERE id = :user_id AND tenant_id = :tenant_id
            """,
            params,
        )
    else:
        if has_updated_at:
            repo.execute(
                """
                UPDATE users
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = :user_id AND tenant_id = :tenant_id
                """,
                {"user_id": current_user["id"], "tenant_id": repo.tenant_id},
            )
    return {"status": "success"}


@router.get("/system", response_model=SystemSettingsPayload)
async def get_system_settings(
    current_user: dict = Depends(_require_admin_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> SystemSettingsPayload:
    settings = _load_tenant_setting(repo, key="system_settings", default=DEFAULT_SYSTEM_SETTINGS)
    return SystemSettingsPayload(**settings)


@router.put("/system")
async def update_system_settings(
    body: SystemSettingsPayload,
    current_user: dict = Depends(_require_admin_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> Dict[str, Any]:
    _save_tenant_setting(repo, key="system_settings", payload=body.model_dump(), encrypted=False)
    return {"status": "success"}


@router.get("/security", response_model=SecuritySettingsPayload)
async def get_security_settings(
    current_user: dict = Depends(_require_admin_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> SecuritySettingsPayload:
    settings = _load_tenant_setting(repo, key="security_settings", default=DEFAULT_SECURITY_SETTINGS)
    return SecuritySettingsPayload(**settings)


@router.put("/security")
async def update_security_settings(
    body: SecuritySettingsPayload,
    current_user: dict = Depends(_require_admin_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> Dict[str, Any]:
    _save_tenant_setting(repo, key="security_settings", payload=body.model_dump(), encrypted=False)
    return {"status": "success"}


@router.get("/credentials", response_model=CredentialSettingsResponse)
async def get_api_credentials(
    current_user: dict = Depends(_require_admin_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> CredentialSettingsResponse:
    values: Dict[str, CredentialStatus] = {}
    for response_key, descriptor in _CREDENTIAL_KEY_MAP.items():
        values[response_key] = _load_tenant_secret(repo, descriptor)
    return CredentialSettingsResponse(**values)


@router.put("/credentials")
async def update_api_credentials(
    body: CredentialSettingsPayload,
    current_user: dict = Depends(_require_admin_user),
    repo: TenantRepository = Depends(get_tenant_repository),
) -> Dict[str, Any]:
    incoming = body.model_dump()
    for response_key, descriptor in _CREDENTIAL_KEY_MAP.items():
        raw_value = incoming.get(response_key)
        if raw_value is None:
            continue
        if isinstance(raw_value, str) and not raw_value.strip():
            continue
        _save_tenant_secret(repo, descriptor, raw_value)
    return {"status": "success"}


@router.get("/provider-health")
async def get_provider_health(current_user: dict = Depends(_require_admin_user)) -> Dict[str, Any]:
    tenant_id = current_user.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context is required.")

    data = await fetch_provider_health(int(tenant_id))
    return {"status": "success", "data": data}
