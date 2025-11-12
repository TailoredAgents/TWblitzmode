from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from services.centralized_logging_service import (
    LogCategory,
    LogLevel,
    log_structured,
)

from . import auth as auth_helpers
from .database import get_db_connection
from .mt_db import get_db as get_native_db
from .deps import get_current_user
from .query_converter import convert_params, convert_query


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_reset_rate_limit(ip: str | None) -> bool:
    """Basic placeholder for rate limiting password resets.

    Always allows by default; tests may monkeypatch this to force denial.
    """
    return True


def _tenant_from_headers(request: Request) -> Optional[str]:
    # Prefer explicit org header; fallback to tenant header
    h = request.headers
    org = h.get("x-organization-id") or h.get("x-organization")
    ten = h.get("x-tenant-id") or h.get("x-tenant")
    return str(org or ten) if (org or ten) else None


@router.post("/refresh")
async def refresh_token(request: Request, response: Response) -> Dict[str, Any]:
    log_structured(
        LogLevel.INFO,
        "auth.refresh.received",
        category=LogCategory.SECURITY,
        client_ip=request.client.host if request.client else None,
    )

    refresh = request.cookies.get("refresh_token")
    if not refresh:
        log_structured(
            LogLevel.WARNING,
            "auth.refresh.missing_token",
            category=LogCategory.SECURITY,
        )
        raise HTTPException(status_code=401, detail="Missing refresh token")

    # Decode payload (unsigned base64 payload per security helpers)
    try:
        payload = auth_helpers.decode_access_token(refresh)  # returns None on invalid
    except Exception:
        payload = None

    if not payload:
        # Fallback: tolerate refresh-style payloads by manual decode
        try:
            # _decode_payload is internal; emulate logically by using decode_token with HTTPException path
            payload = auth_helpers.decode_token(refresh)
        except HTTPException:
            log_structured(
                LogLevel.WARNING,
                "auth.refresh.invalid",
                category=LogCategory.SECURITY,
            )
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        except Exception:
            log_structured(
                LogLevel.WARNING,
                "auth.refresh.invalid",
                category=LogCategory.SECURITY,
            )
            raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        log_structured(
            LogLevel.WARNING,
            "auth.refresh.wrong_type",
            category=LogCategory.SECURITY,
        )
        raise HTTPException(status_code=401, detail="Wrong token type")

    tenant_id = payload.get("tenant_id")
    user_id = payload.get("user_id")
    session_id = payload.get("sid")
    version = payload.get("ver") or 1

    if not all([tenant_id, user_id, session_id]):
        log_structured(
            LogLevel.WARNING,
            "auth.refresh.malformed",
            category=LogCategory.SECURITY,
        )
        raise HTTPException(status_code=401, detail="Malformed refresh token")

    token_hash = _hash_token(refresh)

    # Validate session record
    with get_db_connection() as conn:
        # Set RLS GUCs to match tenant scope from token
        try:
            with conn.cursor() as gcur:
                gcur.execute(convert_query("SELECT set_config('app.current_tenant_id', ?, true)"), tuple(convert_params((str(tenant_id),))))
                gcur.execute(convert_query("SELECT set_config('app.current_organization_id', ?, true)"), tuple(convert_params((str(tenant_id),))))
        except Exception:
            pass
        with conn.cursor() as cur:
            cur.execute(
                convert_query(
                    """
                    SELECT id, revoked_at, expires_at, token_version
                    FROM auth_sessions
                    WHERE tenant_id = ? AND user_id = ? AND session_id = ? AND refresh_token_hash = ?
                    """
                ),
                tuple(convert_params((tenant_id, user_id, session_id, token_hash))),
            )
            row = cur.fetchone()

        if not row:
            log_structured(
                LogLevel.WARNING,
                "auth.refresh.session_not_found",
                category=LogCategory.SECURITY,
                tenant_id=str(tenant_id),
                user_id=str(user_id),
            )
            raise HTTPException(status_code=401, detail="Session invalid")

        if row.get("revoked_at") is not None:
            log_structured(
                LogLevel.WARNING,
                "auth.refresh.session_revoked",
                category=LogCategory.SECURITY,
            )
            raise HTTPException(status_code=401, detail="Session revoked")

        expires_at = row.get("expires_at")
        if expires_at is not None and isinstance(expires_at, datetime) and expires_at.replace(tzinfo=timezone.utc) < _now():
            log_structured(
                LogLevel.WARNING,
                "auth.refresh.session_expired",
                category=LogCategory.SECURITY,
            )
            raise HTTPException(status_code=401, detail="Session expired")

        # Rotate refresh token and issue access token
        access_token = auth_helpers.create_access_token(
            {"user_id": user_id, "tenant_id": tenant_id}, expires_delta=timedelta(hours=1)
        )

        new_refresh = auth_helpers.create_refresh_token(
            user_id=int(user_id),
            tenant_id=int(tenant_id),
            session_id=str(session_id),
            version=int(row.get("token_version") or version) + 1,
            lifetime=timedelta(days=7),
        )
        new_hash = _hash_token(new_refresh)

        with conn.cursor() as cur:
            cur.execute(
                convert_query(
                    """
                    UPDATE auth_sessions
                    SET refresh_token_hash = ?, token_version = token_version + 1, last_rotated_at = NOW()
                    WHERE id = ?
                    """
                ),
                tuple(convert_params((new_hash, row["id"]))),
            )

        # Set refreshed cookie
        response.set_cookie(
            key="refresh_token",
            value=new_refresh,
            httponly=True,
            secure=os.getenv("COOKIE_SECURE", "1").lower() in ("1", "true", "yes"),
            samesite="lax",
            path="/",
            max_age=int(timedelta(days=7).total_seconds()),
        )

        return {"data": {"access_token": access_token}}


@router.post("/login")
async def login(request: Request, response: Response, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    log_structured(
        LogLevel.INFO,
        "auth.login.received",
        category=LogCategory.SECURITY,
        client_ip=request.client.host if request.client else None,
    )

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    email = (body or {}).get("email")
    user_id = (body or {}).get("user_id")
    password = (body or {}).get("password") or ""

    if not (email or user_id):
        raise HTTPException(status_code=400, detail="Email or user_id required")

    tenant_hint = _tenant_from_headers(request)
    if not tenant_hint:
        # Enforce explicit tenant context because RLS is enabled across users
        raise HTTPException(status_code=400, detail="X-Organization-Id header is required for login")

    with get_db_connection() as conn:
        # Set RLS GUCs based on provided tenant context
        try:
            with conn.cursor() as gcur:
                gcur.execute(convert_query("SELECT set_config('app.current_tenant_id', ?, true)"), tuple(convert_params((str(tenant_hint),))))
                gcur.execute(convert_query("SELECT set_config('app.current_organization_id', ?, true)"), tuple(convert_params((str(tenant_hint),))))
        except Exception:
            pass
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    convert_query(
                        "SELECT id, tenant_id, email, password_hash, first_name, last_name, role FROM users WHERE id = ?"
                    ),
                    tuple(convert_params((user_id,))),
                )
            else:
                cur.execute(
                    convert_query(
                        "SELECT id, tenant_id, email, password_hash, first_name, last_name, role FROM users WHERE LOWER(email) = LOWER(?) ORDER BY id LIMIT 1"
                    ),
                    tuple(convert_params((email,))),
                )
            row = cur.fetchone()

        if not row:
            log_structured(LogLevel.WARNING, "auth.login.user_not_found", category=LogCategory.SECURITY)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not auth_helpers.verify_password(password, row.get("password_hash") or ""):
            log_structured(LogLevel.WARNING, "auth.login.bad_password", category=LogCategory.SECURITY)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        uid = int(row["id"])
        tenant_id = int(row.get("tenant_id") or 1)

        access_token = auth_helpers.create_token(user_id=uid, tenant_id=tenant_id, hours=1)

        # create session + refresh cookie
        session_id = secrets.token_urlsafe(16)
        refresh = auth_helpers.create_refresh_token(uid, tenant_id, session_id, version=1, lifetime=timedelta(days=7))
        refresh_hash = _hash_token(refresh)

        with conn.cursor() as cur:
            # Upsert on (tenant_id, session_id)
            cur.execute(
                convert_query(
                    """
                    INSERT INTO auth_sessions (tenant_id, user_id, session_id, refresh_token_hash, token_version, current_jti, expires_at)
                    VALUES (?, ?, ?, ?, 1, NULL, NOW() + INTERVAL '7 days')
                    ON CONFLICT (tenant_id, session_id) DO UPDATE
                    SET refresh_token_hash = EXCLUDED.refresh_token_hash,
                        token_version = auth_sessions.token_version + 1,
                        updated_at = NOW(),
                        last_rotated_at = NOW(),
                        revoked_at = NULL,
                        expires_at = NOW() + INTERVAL '7 days'
                    """
                ),
                tuple(convert_params((tenant_id, uid, session_id, refresh_hash))),
            )

        response.set_cookie(
            key="refresh_token",
            value=refresh,
            httponly=True,
            secure=os.getenv("COOKIE_SECURE", "1").lower() in ("1", "true", "yes"),
            samesite="lax",
            path="/",
            max_age=int(timedelta(days=7).total_seconds()),
        )

        user_payload = {
            "id": uid,
            "email": row.get("email"),
            "first_name": row.get("first_name"),
            "last_name": row.get("last_name"),
            "role": row.get("role") or "user",
            "tenant_id": tenant_id,
        }

        return {"data": {"access_token": access_token, "user": user_payload}}


@router.get("/me")
async def me(request: Request, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    log_structured(LogLevel.INFO, "auth.me.received", category=LogCategory.SECURITY)

    if not authorization or not authorization.lower().startswith("bearer "):
        log_structured(LogLevel.WARNING, "auth.me.missing_authorization", category=LogCategory.SECURITY)
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = auth_helpers.decode_token(token)
    except HTTPException:
        log_structured(LogLevel.WARNING, "auth.me.http_exception", category=LogCategory.SECURITY)
        raise

    # Hydrate from dependency to include account context if available
    user = await get_current_user(request, authorization=authorization)
    return {"data": user, "token": payload}


@router.post("/forgot-password")
async def forgot_password(request: Request) -> Dict[str, Any]:
    log_structured(LogLevel.INFO, "auth.forgot.received", category=LogCategory.SECURITY)

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    email = (body or {}).get("email")
    _org_slug = (body or {}).get("organization_slug")

    client_ip = request.client.host if request.client else None
    if not check_reset_rate_limit(client_ip):
        log_structured(LogLevel.WARNING, "auth.forgot.rate_limited", category=LogCategory.SECURITY, email=email)
        raise HTTPException(status_code=429, detail="Too many requests")

    # Stub success; real email dispatch intentionally omitted in Blitz mode
    return {"data": {"message": "If the email exists, a reset link has been sent."}}


@router.get("/login/roster")
async def login_roster(request: Request) -> Dict[str, Any]:
    # Lightweight roster for login screen; non-authenticated
    tenant_hint = _tenant_from_headers(request)
    with get_db_connection() as conn:
        # Apply tenant scoping if provided
        if tenant_hint:
            try:
                with conn.cursor() as gcur:
                    gcur.execute(convert_query("SELECT set_config('app.current_tenant_id', ?, true)"), tuple(convert_params((str(tenant_hint),))))
                    gcur.execute(convert_query("SELECT set_config('app.current_organization_id', ?, true)"), tuple(convert_params((str(tenant_hint),))))
            except Exception:
                pass
        with conn.cursor() as cur:
            cur.execute(
                convert_query(
                    """
                    SELECT id, first_name, last_name, last_login_at
                    FROM users
                    ORDER BY last_login_at DESC NULLS LAST, id ASC
                    LIMIT 50
                    """
                )
            )
            rows = cur.fetchall() or []

    users = [
        {
            "id": r.get("id"),
            "first_name": r.get("first_name"),
            "last_name": r.get("last_name"),
            "last_login_at": r.get("last_login_at").isoformat() if r.get("last_login_at") else None,
        }
        for r in rows
    ]
    return {"users": users}


@router.post("/logout")
async def logout(request: Request, response: Response) -> Dict[str, Any]:
    log_structured(
        LogLevel.INFO,
        "auth.logout.received",
        category=LogCategory.SECURITY,
        client_ip=request.client.host if request.client else None,
    )

    refresh = request.cookies.get("refresh_token")
    if not refresh:
        # Idempotent logout: clear cookie anyway
        response.delete_cookie("refresh_token", path="/")
        return {"data": {"success": True}}

    # Decode refresh to scope RLS and locate session
    try:
        payload = auth_helpers.decode_access_token(refresh) or {}
    except Exception:
        payload = {}

    tenant_id = payload.get("tenant_id")
    user_id = payload.get("user_id")
    session_id = payload.get("sid")
    token_hash = _hash_token(refresh)

    if tenant_id and user_id and session_id:
        with get_db_connection() as conn:
            # Set tenant GUCs to satisfy RLS on auth_sessions
            try:
                with conn.cursor() as gcur:
                    gcur.execute(convert_query("SELECT set_config('app.current_tenant_id', ?, true)"), tuple(convert_params((str(tenant_id),))))
                    gcur.execute(convert_query("SELECT set_config('app.current_organization_id', ?, true)"), tuple(convert_params((str(tenant_id),))))
            except Exception:
                pass

            with conn.cursor() as cur:
                cur.execute(
                    convert_query(
                        """
                        UPDATE auth_sessions
                        SET revoked_at = NOW()
                        WHERE tenant_id = ? AND user_id = ? AND session_id = ? AND refresh_token_hash = ? AND revoked_at IS NULL
                        """
                    ),
                    tuple(convert_params((tenant_id, user_id, session_id, token_hash))),
                )

        log_structured(
            LogLevel.INFO,
            "auth.logout.session_revoked",
            category=LogCategory.SECURITY,
            tenant_id=str(tenant_id),
            user_id=str(user_id),
        )

    # Clear cookie regardless
    response.delete_cookie("refresh_token", path="/")
    return {"data": {"success": True}}
