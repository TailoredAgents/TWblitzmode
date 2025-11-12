"""Cookie jar governance utilities for LinkedIn session management."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from cryptography.fernet import Fernet, InvalidToken

from .db_core import execute, query
from services.cookie_vault_service import cookie_vault, VaultItemType
from services.audit_logging_service import audit_service, AuditEventType, AuditSeverity

try:  # pragma: no cover - optional runtime dependency
    from services.linkedin_cookie_verifier import LinkedInCookieVerifier, VerificationStatus
except Exception:  # pragma: no cover - optional dependency
    LinkedInCookieVerifier = None  # type: ignore
    VerificationStatus = None  # type: ignore

DEFAULT_COOKIE_TTL_DAYS = int(os.getenv("COOKIE_DEFAULT_TTL_DAYS", "30"))
EXPIRING_SOON_THRESHOLD_DAYS = int(os.getenv("COOKIE_EXPIRING_SOON_THRESHOLD_DAYS", "5"))
DEFAULT_COOKIE_LOCK_SECONDS = int(os.getenv("COOKIE_LOCK_SECONDS", "600"))


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


def _safe_rollback(conn) -> None:
    try:
        rollback = getattr(conn, "rollback", None)
        if callable(rollback):
            rollback()
    except Exception:
        # Silent rollback failure - connection will be refreshed by caller if needed
        pass


def _now() -> datetime:
    return datetime.utcnow()


def _serialize_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat()


def _ensure_datetime(value: Optional[Any]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _get_secret() -> str:
    secret = os.getenv("COOKIE_JAR_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Cookie encryption secret is not configured")
    return secret


def _derive_key(secret: str, salt: bytes) -> bytes:
    derived = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 390_000, dklen=32)
    return base64.urlsafe_b64encode(derived)


def _encrypt_payload(payload: Dict[str, Any]) -> Dict[str, str]:
    secret = _get_secret()
    salt = secrets.token_bytes(16)
    key = _derive_key(secret, salt)
    cipher = Fernet(key)
    encrypted = cipher.encrypt(json.dumps(payload, default=str).encode("utf-8"))
    return {
        "encrypted_payload": encrypted.decode("utf-8"),
        "encryption_salt": base64.b64encode(salt).decode("utf-8"),
    }


def _decrypt_payload(encrypted_payload: str, encryption_salt: str) -> Dict[str, Any]:
    secret = _get_secret()
    try:
        salt = base64.b64decode(encryption_salt.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail="Invalid encryption salt") from exc
    key = _derive_key(secret, salt)
    cipher = Fernet(key)
    try:
        decrypted = cipher.decrypt(encrypted_payload.encode("utf-8"))
    except InvalidToken as exc:
        raise HTTPException(status_code=500, detail="Unable to decrypt cookie payload") from exc
    return json.loads(decrypted.decode("utf-8"))


async def _log_audit_event(
    *,
    tenant_id: int,
    user_id: Optional[int],
    event_type: AuditEventType,
    severity: AuditSeverity,
    action: str,
    resource_id: str,
    details: Dict[str, Any],
) -> None:
    try:
        await audit_service.log_event(
            tenant_id=str(tenant_id),
            user_id=str(user_id) if user_id else None,
            event_type=event_type,
            severity=severity,
            action=action,
            resource_type="cookie_jar",
            resource_id=resource_id,
            details=details,
            success=True,
        )
    except Exception:  # pragma: no cover - best effort
        pass


async def record_cookie_event(
    conn,
    *,
    organization_id: int,
    user_id: Optional[int],
    jar_id: Optional[int],
    event_type: str,
    status: str,
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        execute(
            conn,
            """
            INSERT INTO cookie_events (organization_id, user_id, cookie_jar_id, event_type, status, message, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                user_id,
                jar_id,
                event_type,
                status,
                message,
                json.dumps(metadata or {}, default=str),
            ),
        )
    except Exception as exc:
        if _is_missing_table_error(exc):
            _safe_rollback(conn)
            return
        if _is_poisoned_transaction_error(exc):
            _safe_rollback(conn)
            execute(
                conn,
                """
                INSERT INTO cookie_events (organization_id, user_id, cookie_jar_id, event_type, status, message, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    organization_id,
                    user_id,
                    jar_id,
                    event_type,
                    status,
                    message,
                    json.dumps(metadata or {}, default=str),
                ),
            )
        else:
            _safe_rollback(conn)
            raise
    asyncio.create_task(
        _log_audit_event(
            tenant_id=organization_id,
            user_id=user_id,
            event_type=AuditEventType.CONFIGURATION_CHANGED,
            severity=AuditSeverity.LOW if status == "success" else AuditSeverity.MEDIUM,
            action=f"cookie_{event_type}",
            resource_id=str(jar_id or "n/a"),
            details={
                "status": status,
                "message": message,
                "metadata": metadata or {},
            },
        )
    )


async def store_cookie_payload(
    conn,
    organization_id: int,
    user_id: int,
    cookies: Dict[str, Any],
    *,
    status: str = "pending",
    label: Optional[str] = None,
) -> int:
    if "li_at" not in cookies or not cookies.get("li_at"):
        raise HTTPException(status_code=400, detail="li_at cookie is required")

    encrypted = _encrypt_payload(cookies)
    expires_at_dt = _now() + timedelta(days=DEFAULT_COOKIE_TTL_DAYS)
    if cookies.get("expires_in_days"):
        try:
            expires_at_dt = _now() + timedelta(days=int(cookies["expires_in_days"]))
        except Exception:
            pass

    label = label or cookies.get("label") or f"linkedin-cookie-{user_id}-{int(_now().timestamp())}"
    vault_metadata = {
        "source": "company_portal",
        "user_agent": cookies.get("user_agent"),
    }

    vault_item_id = await cookie_vault.store_vault_item(
        tenant_id=str(organization_id),
        user_id=str(user_id),
        item_type=VaultItemType.LINKEDIN_COOKIE,
        label=label,
        sensitive_data={
            "li_at": cookies.get("li_at"),
            "jsessionid": cookies.get("jsessionid"),
            "user_agent": cookies.get("user_agent"),
            "stored_at": _serialize_dt(_now()),
        },
        expires_at=expires_at_dt,
        metadata=vault_metadata,
    )

    existing = query(
        conn,
        "SELECT id FROM cookie_jars WHERE organization_id = ? AND user_id = ?",
        (organization_id, user_id),
    )

    fields = (
        encrypted["encrypted_payload"],
        encrypted["encryption_salt"],
        status,
        _serialize_dt(expires_at_dt),
        vault_item_id,
    )

    if existing:
        jar_id = int(existing[0]["id"] if isinstance(existing[0], dict) else existing[0][0])
        execute(
            conn,
            """
            UPDATE cookie_jars
            SET encrypted_payload = ?, encryption_salt = ?, status = ?, expires_at = ?, vault_item_id = ?,
                usage_count = 0, error_count = 0, last_error = NULL, last_error_at = NULL,
                status_detail = NULL, locked_at = NULL, lock_expires_at = NULL, locked_by = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (*fields, jar_id),
        )
    else:
        jar_id = execute(
            conn,
            """
            INSERT INTO cookie_jars (
                organization_id, user_id, encrypted_payload, encryption_salt, status, expires_at, vault_item_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                user_id,
                *fields,
            ),
        )

    await record_cookie_event(
        conn,
        organization_id=organization_id,
        user_id=user_id,
        jar_id=jar_id,
        event_type="uploaded",
        status="success",
        message="LinkedIn cookies uploaded and encrypted.",
        metadata={"vault_item_id": vault_item_id},
    )
    return jar_id


async def load_cookie_payload(conn, jar_id: int) -> Dict[str, Any]:
    rows = query(
        conn,
        """
        SELECT organization_id, user_id, encrypted_payload, encryption_salt, vault_item_id
        FROM cookie_jars
        WHERE id = ?
        """,
        (jar_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Cookie jar not found")

    record = dict(rows[0])
    organization_id = int(record["organization_id"])
    user_id = int(record["user_id"])

    if record.get("vault_item_id"):
        vault_item = await cookie_vault.retrieve_vault_item(
            record["vault_item_id"],
            tenant_id=str(organization_id),
            user_id=str(user_id),
        )
        if vault_item and vault_item.get("data"):
            payload = vault_item["data"]
        else:
            payload = {}
    else:
        payload = _decrypt_payload(record["encrypted_payload"], record["encryption_salt"])

    return {
        "organization_id": organization_id,
        "user_id": user_id,
        "payload": payload,
        "vault_item_id": record.get("vault_item_id"),
    }


async def validate_cookie_payload(
    conn,
    organization_id: int,
    user_id: int,
    jar_id: int,
    cookies: Optional[Dict[str, Any]] = None,
) -> str:
    if cookies is None:
        loaded = await load_cookie_payload(conn, jar_id)
        cookies = loaded["payload"]

    if LinkedInCookieVerifier is None:  # pragma: no cover - optional dependency
        execute(
            conn,
            """
            UPDATE cookie_jars
            SET status = 'pending', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (jar_id,),
        )
        await record_cookie_event(
            conn,
            organization_id=organization_id,
            user_id=user_id,
            jar_id=jar_id,
            event_type="verification",
            status="skipped",
            message="LinkedInCookieVerifier unavailable; status set to pending.",
        )
        return "pending"

    verifier = LinkedInCookieVerifier()
    try:
        result = await verifier.verify_linkedin_cookies(
            li_at=cookies.get("li_at"),
            jsessionid=cookies.get("jsessionid"),
            tenant_id=str(organization_id),
            user_id=str(user_id),
        )
    except Exception as exc:  # pragma: no cover - defensive path
        execute(
            conn,
            """
            UPDATE cookie_jars
            SET status = 'invalid', last_error = ?, last_error_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (str(exc), jar_id),
        )
        await record_cookie_event(
            conn,
            organization_id=organization_id,
            user_id=user_id,
            jar_id=jar_id,
            event_type="verification",
            status="error",
            message="Cookie validation failed during LinkedIn verification.",
            metadata={"error": str(exc)},
        )
        raise HTTPException(status_code=502, detail="Cookie validation failed") from exc

    status = result.status.value if hasattr(result, "status") else "invalid"
    status_detail = None
    expires_at_dt = _now() + timedelta(days=DEFAULT_COOKIE_TTL_DAYS)

    if status == "valid":
        if hasattr(result, "verification_timestamp") and result.verification_timestamp:
            expires_at_dt = result.verification_timestamp + timedelta(days=DEFAULT_COOKIE_TTL_DAYS)
        status_value = "valid"
    elif status in {"expired", "rate_limited", "challenge_required"}:
        status_value = "expired"
        status_detail = status
    else:
        status_value = "invalid"
        status_detail = getattr(result, "error_message", None)

    execute(
        conn,
        """
        UPDATE cookie_jars
        SET status = ?, status_detail = ?, last_validated_at = CURRENT_TIMESTAMP,
            expires_at = ?, error_count = CASE WHEN ? = 'valid' THEN error_count ELSE error_count + 1 END,
            last_error = CASE WHEN ? = 'valid' THEN NULL ELSE ? END,
            last_error_at = CASE WHEN ? = 'valid' THEN NULL ELSE CURRENT_TIMESTAMP END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            status_value,
            status_detail,
            _serialize_dt(expires_at_dt),
            status_value,
            status_value,
            status_detail,
            status_value,
            jar_id,
        ),
    )

    await record_cookie_event(
        conn,
        organization_id=organization_id,
        user_id=user_id,
        jar_id=jar_id,
        event_type="verification",
        status="success" if status_value == "valid" else "warning",
        message="LinkedIn cookies verified." if status_value == "valid" else "LinkedIn cookies failed verification.",
        metadata={
            "verification_status": status_value,
            "detail": status_detail,
            "expires_at": _serialize_dt(expires_at_dt),
        },
    )
    return status_value


def get_cookie_status(conn, organization_id: int, user_id: int) -> Dict[str, Any]:
    try:
        rows = query(
            conn,
            """
            SELECT id, status, status_detail, last_validated_at, updated_at, expires_at,
                   last_used_at, usage_count, error_count, last_error, last_error_at,
                   vault_item_id, locked_at, lock_expires_at, locked_by
            FROM cookie_jars
            WHERE organization_id = ? AND user_id = ?
            """,
            (organization_id, user_id),
        )
    except Exception as exc:
        if _is_missing_table_error(exc):
            _safe_rollback(conn)
            return {"status": "missing", "last_validated_at": None}
        if _is_poisoned_transaction_error(exc):
            _safe_rollback(conn)
            rows = query(
                conn,
                """
                SELECT id, status, status_detail, last_validated_at, updated_at, expires_at,
                       last_used_at, usage_count, error_count, last_error, last_error_at,
                       vault_item_id, locked_at, lock_expires_at, locked_by
                FROM cookie_jars
                WHERE organization_id = ? AND user_id = ?
                """,
                (organization_id, user_id),
            )
        else:
            _safe_rollback(conn)
            raise
    if not rows:
        return {"status": "missing", "last_validated_at": None}
    row = dict(rows[0])
    return {
        "id": row.get("id"),
        "status": row.get("status", "pending"),
        "status_detail": row.get("status_detail"),
        "last_validated_at": row.get("last_validated_at"),
        "updated_at": row.get("updated_at"),
        "expires_at": row.get("expires_at"),
        "last_used_at": row.get("last_used_at"),
        "usage_count": row.get("usage_count", 0),
        "error_count": row.get("error_count", 0),
        "last_error": row.get("last_error"),
        "last_error_at": row.get("last_error_at"),
        "vault_item_id": row.get("vault_item_id"),
        "locked_at": row.get("locked_at"),
        "lock_expires_at": row.get("lock_expires_at"),
        "locked_by": row.get("locked_by"),
    }


def list_cookie_statuses(conn, organization_id: int) -> List[Dict[str, Any]]:
    rows = query(
        conn,
        """
        SELECT cj.id, cj.user_id, cj.status, cj.status_detail, cj.last_validated_at, cj.updated_at,
               cj.expires_at, cj.last_used_at, cj.usage_count, cj.error_count, cj.last_error,
               cj.last_error_at, cj.vault_item_id, cj.locked_at, cj.lock_expires_at, cj.locked_by,
               tm.email, tm.first_name, tm.last_name, tm.role
        FROM cookie_jars cj
        LEFT JOIN team_members tm ON tm.user_id = cj.user_id
        WHERE cj.organization_id = ?
        ORDER BY cj.updated_at DESC
        """,
        (organization_id,),
    )
    results: List[Dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        results.append(
            {
                "id": record.get("id"),
                "user_id": record.get("user_id"),
                "email": record.get("email"),
                "first_name": record.get("first_name"),
                "last_name": record.get("last_name"),
                "role": record.get("role"),
                "status": record.get("status"),
                "status_detail": record.get("status_detail"),
                "last_validated_at": record.get("last_validated_at"),
                "updated_at": record.get("updated_at"),
                "expires_at": record.get("expires_at"),
                "last_used_at": record.get("last_used_at"),
                "usage_count": record.get("usage_count"),
                "error_count": record.get("error_count"),
                "last_error": record.get("last_error"),
                "last_error_at": record.get("last_error_at"),
                "vault_item_id": record.get("vault_item_id"),
                "locked_at": record.get("locked_at"),
                "lock_expires_at": record.get("lock_expires_at"),
                "locked_by": record.get("locked_by"),
            }
        )
    return results


def summarize_cookie_health(conn, organization_id: int) -> Dict[str, Any]:
    rows = query(
        conn,
        """
        SELECT status, expires_at FROM cookie_jars
        WHERE organization_id = ?
        """,
        (organization_id,),
    )
    totals = {
        "total": 0,
        "valid": 0,
        "pending": 0,
        "invalid": 0,
        "expired": 0,
        "expiring_soon": 0,
    }
    now = _now()
    soon_threshold = now + timedelta(days=EXPIRING_SOON_THRESHOLD_DAYS)
    for row in rows:
        totals["total"] += 1
        status = row["status"]
        totals[status] = totals.get(status, 0) + 1
        expires_at = _ensure_datetime(row["expires_at"])
        if status == "valid" and expires_at and now <= expires_at <= soon_threshold:
            totals["expiring_soon"] += 1
    return totals


def get_cookie_events(conn, jar_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    rows = query(
        conn,
        """
        SELECT event_type, status, message, metadata, created_at
        FROM cookie_events
        WHERE cookie_jar_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (jar_id, limit),
    )
    events: List[Dict[str, Any]] = []
    for row in rows:
        metadata = {}
        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"])
            except json.JSONDecodeError:
                metadata = {}
        events.append(
            {
                "event_type": row["event_type"],
                "status": row["status"],
                "message": row["message"],
                "metadata": metadata,
                "created_at": row["created_at"],
            }
        )
    return events


def acquire_cookie_lock(conn, jar_id: int, lock_owner: str, ttl_seconds: int = DEFAULT_COOKIE_LOCK_SECONDS) -> bool:
    row = query(
        conn,
        "SELECT lock_expires_at FROM cookie_jars WHERE id = ?",
        (jar_id,),
    )
    if not row:
        return False

    lock_expires_at = _ensure_datetime(row[0]["lock_expires_at"] if isinstance(row[0], dict) else row[0][0])
    if lock_expires_at and lock_expires_at > _now():
        return False

    execute(
        conn,
        """
        UPDATE cookie_jars
        SET locked_at = CURRENT_TIMESTAMP,
            lock_expires_at = ?,
            locked_by = ?
        WHERE id = ?
        """,
        (
            _serialize_dt(_now() + timedelta(seconds=ttl_seconds)),
            lock_owner,
            jar_id,
        ),
    )
    return True


def release_cookie_lock(conn, jar_id: int, lock_owner: Optional[str] = None) -> None:
    if lock_owner:
        execute(
            conn,
            """
            UPDATE cookie_jars
            SET locked_at = NULL, lock_expires_at = NULL, locked_by = NULL
            WHERE id = ? AND locked_by = ?
            """,
            (jar_id, lock_owner),
        )
    else:
        execute(
            conn,
            """
            UPDATE cookie_jars
            SET locked_at = NULL, lock_expires_at = NULL, locked_by = NULL
            WHERE id = ?
            """,
            (jar_id,),
        )


async def increment_cookie_usage(conn, organization_id: int, jar_id: int, lock_owner: Optional[str] = None) -> None:
    execute(
        conn,
        """
        UPDATE cookie_jars
        SET usage_count = usage_count + 1,
            last_used_at = CURRENT_TIMESTAMP,
            lock_expires_at = NULL,
            locked_at = NULL,
            locked_by = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (jar_id,),
    )
    await record_cookie_event(
        conn,
        organization_id=organization_id,
        user_id=None,
        jar_id=jar_id,
        event_type="usage",
        status="success",
        message="Cookie jar utilized for LinkedIn automation.",
        metadata={"lock_owner": lock_owner},
    )


async def mark_cookie_status(
    conn,
    *,
    organization_id: int,
    user_id: Optional[int],
    jar_id: int,
    status: str,
    status_detail: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    execute(
        conn,
        """
        UPDATE cookie_jars
        SET status = ?, status_detail = ?, last_error = ?, last_error_at = CASE WHEN ? IS NULL THEN last_error_at ELSE CURRENT_TIMESTAMP END,
            error_count = CASE WHEN ? IS NULL THEN error_count ELSE error_count + 1 END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            status,
            status_detail,
            error_message,
            error_message,
            error_message,
            jar_id,
        ),
    )
    await record_cookie_event(
        conn,
        organization_id=organization_id,
        user_id=user_id,
        jar_id=jar_id,
        event_type="status_change",
        status="warning" if status != "valid" else "success",
        message=f"Cookie status updated to {status}.",
        metadata={"detail": status_detail, "error": error_message},
    )
