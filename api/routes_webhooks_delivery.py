"""
Webhook Delivery API Routes

Provides webhook registration, delivery tracking, and management endpoints.
Production-ready implementation with security controls and retry logic.
"""

import logging
import hmac
import hashlib
import json
import time
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

import httpx
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from .deps import get_current_user
from .mt_db import get_db
from services.centralized_logging_service import LogCategory, LogLevel, log_structured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

ALLOW_PRIVATE_WEBHOOKS = os.getenv("ALLOW_PRIVATE_WEBHOOKS", "").lower() in {"1", "true", "yes"}
ENABLE_E2E_WEBHOOK_TRIGGER = os.getenv("ENABLE_E2E_WEBHOOK_TRIGGER", "").lower() in {"1", "true", "yes"}

# SSRF Protection - Block private IP ranges
BLOCKED_IP_PATTERNS = [
    r'^127\.',  # localhost
    r'^10\.',  # Private Class A
    r'^172\.(1[6-9]|2[0-9]|3[01])\.',  # Private Class B
    r'^192\.168\.',  # Private Class C
    r'^169\.254\.',  # Link-local
]


def _webhook_log(level: LogLevel, message: str, tenant_id: Optional[str], user_id: Optional[str], **extra) -> None:
    log_structured(
        level,
        message,
        category=LogCategory.API,
        tenant_id=str(tenant_id) if tenant_id else None,
        user_id=str(user_id) if user_id else None,
        **extra,
    )

class WebhookRegister(BaseModel):
    """Webhook registration model"""
    url: str
    events: List[str]
    secret: Optional[str] = None

    @field_validator('url')
    def validate_url(cls, v: str) -> str:
        # Basic URL validation
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')

        # SSRF prevention - check for private IPs (unless explicitly allowed for testing)
        if not ALLOW_PRIVATE_WEBHOOKS:
            parsed = urlparse(v)
            hostname = parsed.hostname or ''
            for pattern in BLOCKED_IP_PATTERNS:
                if re.match(pattern, hostname):
                    raise ValueError('Webhook URLs cannot target private IP ranges')

        return v

    @field_validator('events')
    def validate_events(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError('Events list cannot be empty')

        # Validate event names (alphanumeric, dots, underscores only)
        for event in v:
            if not re.match(r'^[a-zA-Z0-9._]+$', event):
                raise ValueError(f'Invalid event name: {event}')

        return v

class WebhookUpdate(BaseModel):
    """Webhook update model"""
    url: Optional[str] = None
    events: Optional[List[str]] = None
    active: Optional[bool] = None


class WebhookTestEvent(BaseModel):
    """Payload for triggering synthetic webhook events (E2E only)."""
    event_type: str
    payload: Dict[str, Any] = {}
    webhook_id: Optional[int] = None

@router.post("/register")
async def register_webhook(
    webhook: WebhookRegister,
    current_user: dict = Depends(get_current_user)
):
    """Register a new webhook"""
    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    user_id = current_user.get("id")

    tenant_id_str = str(organization_id)
    user_id_str = str(user_id) if user_id else None

    _webhook_log(
        LogLevel.INFO,
        "Registering webhook",
        tenant_id=tenant_id_str,
        user_id=user_id_str,
        url=webhook.url,
        events=list(webhook.events),
    )

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Insert webhook
            cursor.execute("""
                INSERT INTO webhooks (
                    organization_id, user_id, url, events, secret, active, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                RETURNING id, url, events, active, created_at
            """, (
                organization_id,
                user_id,
                webhook.url,
                json.dumps(webhook.events),
                webhook.secret,
                True
            ))

            result = cursor.fetchone()
            conn.commit()

            payload = {
                "id": result[0],
                "url": result[1],
                "events": json.loads(result[2]) if result[2] else [],
                "active": result[3],
                "created_at": result[4].isoformat() if result[4] else None
            }

            _webhook_log(
                LogLevel.INFO,
                "Webhook registered",
                tenant_id=tenant_id_str,
                user_id=user_id_str,
                webhook_id=str(result[0]),
            )

            return payload

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except Exception as e:
        _webhook_log(
            LogLevel.ERROR,
            "Failed to register webhook",
            tenant_id=tenant_id_str,
            user_id=user_id_str,
            exc_info=e,
            url=webhook.url,
        )
        raise HTTPException(status_code=500, detail="Failed to register webhook")

@router.get("")
async def list_webhooks(
    current_user: dict = Depends(get_current_user)
):
    """List all webhooks for the organization"""
    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    tenant_id_str = str(organization_id)
    user_id_str = str(current_user.get("id")) if current_user.get("id") else None

    _webhook_log(
        LogLevel.INFO,
        "Listing webhooks",
        tenant_id=tenant_id_str,
        user_id=user_id_str,
    )

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            cursor.execute("""
                SELECT id, url, events, active, created_at, updated_at
                FROM webhooks
                WHERE organization_id = %s
                ORDER BY created_at DESC
            """, (organization_id,))

            webhooks = []
            for row in cursor.fetchall():
                webhooks.append({
                    "id": row[0],
                    "url": row[1],
                    "events": json.loads(row[2]) if row[2] else [],
                    "active": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                    "updated_at": row[5].isoformat() if row[5] else None
                })

            _webhook_log(
                LogLevel.INFO,
                "Webhook list retrieved",
                tenant_id=tenant_id_str,
                user_id=user_id_str,
                webhook_count=len(webhooks),
            )

            return webhooks

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except Exception as e:
        _webhook_log(
            LogLevel.ERROR,
            "Failed to list webhooks",
            tenant_id=tenant_id_str,
            user_id=user_id_str,
            exc_info=e,
        )
        raise HTTPException(status_code=500, detail="Failed to list webhooks")

@router.get("/{webhook_id}/attempts")
async def get_webhook_delivery_attempts(
    webhook_id: int,
    limit: int = Query(default=50, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Get delivery attempts for a webhook"""
    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    tenant_id_str = str(organization_id)
    user_id_str = str(current_user.get("id")) if current_user.get("id") else None

    _webhook_log(
        LogLevel.INFO,
        "Fetching webhook delivery attempts",
        tenant_id=tenant_id_str,
        user_id=user_id_str,
        webhook_id=str(webhook_id),
        limit=limit,
    )

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Verify webhook belongs to organization
            cursor.execute("""
                SELECT id FROM webhooks
                WHERE id = %s AND organization_id = %s
            """, (webhook_id, organization_id))

            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Webhook not found")

            # Get delivery attempts
            cursor.execute("""
                SELECT
                    id, webhook_id, event_type, status,
                    http_status, response_body, error_message,
                    attempt_number, created_at
                FROM webhook_delivery_attempts
                WHERE webhook_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (webhook_id, limit))

            attempts = []
            for row in cursor.fetchall():
                attempts.append({
                    "id": row[0],
                    "webhook_id": row[1],
                    "event_type": row[2],
                    "status": row[3],
                    "http_status": row[4],
                    "response_body": row[5],
                    "error_message": row[6],
                    "attempt_number": row[7],
                    "created_at": row[8].isoformat() if row[8] else None
                })

            _webhook_log(
                LogLevel.INFO,
                "Fetched webhook delivery attempts",
                tenant_id=tenant_id_str,
                user_id=user_id_str,
                webhook_id=str(webhook_id),
                attempt_count=len(attempts),
            )

            return attempts

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except HTTPException:
        raise
    except Exception as e:
        _webhook_log(
            LogLevel.ERROR,
            "Failed to fetch webhook delivery attempts",
            tenant_id=tenant_id_str,
            user_id=user_id_str,
            webhook_id=str(webhook_id),
            exc_info=e,
        )
        raise HTTPException(status_code=500, detail="Failed to get delivery attempts")

@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Delete a webhook"""
    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    tenant_id_str = str(organization_id)
    user_id_str = str(current_user.get("id")) if current_user.get("id") else None

    _webhook_log(
        LogLevel.INFO,
        "Deleting webhook",
        tenant_id=tenant_id_str,
        user_id=user_id_str,
        webhook_id=str(webhook_id),
    )

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Delete webhook (CASCADE will handle delivery attempts)
            cursor.execute("""
                DELETE FROM webhooks
                WHERE id = %s AND organization_id = %s
                RETURNING id
            """, (webhook_id, organization_id))

            result = cursor.fetchone()
            conn.commit()

            if not result:
                raise HTTPException(status_code=404, detail="Webhook not found")

            _webhook_log(
                LogLevel.INFO,
                "Webhook deleted",
                tenant_id=tenant_id_str,
                user_id=user_id_str,
                webhook_id=str(webhook_id),
            )

            return {"success": True, "id": result[0]}

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except HTTPException:
        raise
    except Exception as e:
        _webhook_log(
            LogLevel.ERROR,
            "Failed to delete webhook",
            tenant_id=tenant_id_str,
            user_id=user_id_str,
            webhook_id=str(webhook_id),
            exc_info=e,
        )
        raise HTTPException(status_code=500, detail="Failed to delete webhook")

@router.put("/{webhook_id}")
async def update_webhook(
    webhook_id: int,
    updates: WebhookUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update a webhook"""
    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Build update query dynamically
            update_fields = []
            params = []

            if updates.url is not None:
                update_fields.append("url = %s")
                params.append(updates.url)

            if updates.events is not None:
                update_fields.append("events = %s")
                params.append(json.dumps(updates.events))

            if updates.active is not None:
                update_fields.append("active = %s")
                params.append(updates.active)

            if not update_fields:
                raise HTTPException(status_code=400, detail="No fields to update")

            update_fields.append("updated_at = NOW()")

            params.extend([webhook_id, organization_id])

            cursor.execute(f"""
                UPDATE webhooks
                SET {', '.join(update_fields)}
                WHERE id = %s AND organization_id = %s
                RETURNING id, url, events, active, updated_at
            """, params)

            result = cursor.fetchone()
            conn.commit()

            if not result:
                raise HTTPException(status_code=404, detail="Webhook not found")

            return {
                "id": result[0],
                "url": result[1],
                "events": json.loads(result[2]) if result[2] else [],
                "active": result[3],
                "updated_at": result[4].isoformat() if result[4] else None
            }

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update webhook: {e}")
        raise HTTPException(status_code=500, detail="Failed to update webhook")

def generate_webhook_signature(payload: str, secret: str) -> str:
    """Generate HMAC SHA256 signature for webhook payload"""
    return hmac.new(
        secret.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def _ensure_delivery_table(conn) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_delivery_attempts (
            id SERIAL PRIMARY KEY,
            webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            http_status INTEGER,
            response_body TEXT,
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    conn.commit()
    cursor.close()


def _record_delivery_attempt(
    conn,
    *,
    webhook_id: int,
    event_type: str,
    status: str,
    http_status: Optional[int],
    response_body: Optional[str],
    error_message: Optional[str],
    retry_count: int = 0,
) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO webhook_delivery_attempts (
            webhook_id, event_type, status, http_status,
            response_body, error_message, retry_count, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """,
        (
            webhook_id,
            event_type,
            status,
            http_status,
            response_body,
            error_message,
            retry_count,
        ),
    )
    conn.commit()
    cursor.close()


if ENABLE_E2E_WEBHOOK_TRIGGER:

    @router.post("/trigger-test-event")
    async def trigger_test_event(
        event: WebhookTestEvent,
        current_user: dict = Depends(get_current_user),
    ):
        """
        Trigger all active webhooks for the current organization with a synthetic payload.
        Enabled only when ENABLE_E2E_WEBHOOK_TRIGGER is set.
        """
        organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
        if not organization_id:
            raise HTTPException(status_code=404, detail="Organization not found")

        conn = get_db()
        cursor = conn.cursor()
        try:
            _ensure_delivery_table(conn)

            params = [organization_id, True]
            base_query = """
                SELECT id, url, events, secret
                FROM webhooks
                WHERE organization_id = %s AND active = %s
            """
            if event.webhook_id is not None:
                base_query += " AND id = %s"
                params.append(event.webhook_id)

            cursor.execute(base_query, tuple(params))
            webhooks = cursor.fetchall()
        finally:
            cursor.close()

        if not webhooks:
            raise HTTPException(status_code=404, detail="No active webhooks found")

        payload_envelope = {"event": event.event_type, "payload": event.payload}
        payload_str = json.dumps(payload_envelope)

        attempts: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=5.0) as client:
            for webhook_id, url, events_raw, secret in webhooks:
                events = []
                if events_raw:
                    try:
                        events = json.loads(events_raw)
                    except json.JSONDecodeError:
                        logger.warning("Failed to decode events configuration for webhook %s", webhook_id)

                if events and event.event_type not in events:
                    continue

                headers = {"Content-Type": "application/json"}
                if secret:
                    headers["X-Webhook-Signature"] = generate_webhook_signature(payload_str, secret)

                http_status = None
                response_body = None
                error_message = None
                status = "delivered"

                try:
                    response = await client.post(url, content=payload_str, headers=headers)
                    http_status = response.status_code
                    response_body = response.text[:2048]
                    if response.status_code >= 400:
                        status = "failed"
                        error_message = f"HTTP {response.status_code}"
                except Exception as exc:
                    status = "error"
                    error_message = str(exc)

                _record_delivery_attempt(
                    conn,
                    webhook_id=webhook_id,
                    event_type=event.event_type,
                    status=status,
                    http_status=http_status,
                    response_body=response_body,
                    error_message=error_message,
                    retry_count=0,
                )

                attempts.append(
                    {
                        "webhook_id": webhook_id,
                        "url": url,
                        "status": status,
                        "http_status": http_status,
                        "error": error_message,
                    }
                )

        if not attempts:
            raise HTTPException(status_code=404, detail="No webhooks subscribed to this event")

        return {"attempts": attempts}
