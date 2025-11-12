"""
Tenant secret management API routes.

Exposes endpoints to store, rotate, and revoke tenant-scoped secrets in the
encrypted cookie vault service.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .deps import get_current_admin
from services.cookie_vault_service import cookie_vault, VaultItemType
from services.audit_logging_service import (
    audit_service,
    AuditEventType,
    AuditSeverity,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/secrets", tags=["secrets"])


class SecretCreateRequest(BaseModel):
    """Request payload for creating a tenant secret."""

    item_type: VaultItemType = Field(
        ..., description="Type of secret being stored (e.g. API token, cookie)."
    )
    label: str = Field(..., min_length=3, max_length=255)
    data: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None
    expires_at: Optional[datetime] = None

    class Config:
        use_enum_values = True


class SecretRotateRequest(BaseModel):
    """Payload for rotating an existing secret."""

    data: Dict[str, Any]
    label: Optional[str] = Field(
        None, description="Optional replacement label applied to the rotated secret."
    )
    metadata: Optional[Dict[str, Any]] = None
    expires_at: Optional[datetime] = None


class SecretResponse(BaseModel):
    """Serialized secret metadata (no sensitive values)."""

    id: str
    label: str
    item_type: str
    created_at: str
    last_accessed: Optional[str] = None
    expires_at: Optional[str] = None
    is_active: bool
    metadata: Optional[Dict[str, Any]] = None


class SecretListResponse(BaseModel):
    items: List[SecretResponse]


def _serialize_secret(item: Dict[str, Any]) -> SecretResponse:
    return SecretResponse(
        id=item["id"],
        label=item["label"],
        item_type=item["item_type"],
        created_at=item["created_at"],
        last_accessed=item.get("last_accessed"),
        expires_at=item.get("expires_at"),
        is_active=item.get("is_active", True),
        metadata=item.get("metadata"),
    )


@router.get("", response_model=SecretListResponse)
async def list_secrets(
    item_type: Optional[VaultItemType] = Query(
        None, description="Filter by secret type."
    ),
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> SecretListResponse:
    """List all active secrets for the current tenant."""

    tenant_id = str(current_user["tenant_id"])
    user_id = str(current_user["id"])

    try:
        items = await cookie_vault.list_vault_items(
            tenant_id, user_id, item_type=item_type
        )
        return SecretListResponse(items=[_serialize_secret(item) for item in items])
    except Exception as exc:
        logger.exception("Failed to list vault secrets for tenant %s", tenant_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("", response_model=SecretResponse, status_code=201)
async def create_secret(
    payload: SecretCreateRequest,
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> SecretResponse:
    """Store a new secret in the tenant vault."""

    tenant_id = str(current_user["tenant_id"])
    user_id = str(current_user["id"])

    try:
        item_type = (
            payload.item_type
            if isinstance(payload.item_type, VaultItemType)
            else VaultItemType(payload.item_type)
        )

        secret_id = await cookie_vault.store_vault_item(
            tenant_id=tenant_id,
            user_id=user_id,
            item_type=item_type,
            label=payload.label,
            sensitive_data=payload.data,
            expires_at=payload.expires_at,
            metadata=payload.metadata,
        )

        await audit_service.log_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=AuditEventType.CONFIGURATION_CHANGED,
            action="tenant_secret_created",
            resource_type="tenant_secret",
            resource_id=secret_id,
            details={
                "item_type": item_type.value,
                "label": payload.label,
                "expires_at": payload.expires_at.isoformat()
                if payload.expires_at
                else None,
            },
            severity=AuditSeverity.MEDIUM,
        )

        metadata = await cookie_vault.list_vault_items(
            tenant_id, user_id, item_type=item_type
        )
        secret_meta = next((item for item in metadata if item["id"] == secret_id), None)
        if not secret_meta:
            raise HTTPException(status_code=404, detail="Secret metadata not found")
        return _serialize_secret(secret_meta)
    except Exception as exc:
        logger.exception("Failed to store tenant secret for %s", tenant_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{secret_id}/rotate", response_model=SecretResponse)
async def rotate_secret(
    secret_id: str,
    payload: SecretRotateRequest,
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> SecretResponse:
    """Rotate an existing secret, returning metadata for the new secret."""

    tenant_id = str(current_user["tenant_id"])
    user_id = str(current_user["id"])

    try:
        existing = await cookie_vault.retrieve_vault_item(secret_id, tenant_id, user_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Secret not found")

        await cookie_vault.delete_vault_item(secret_id, tenant_id, user_id)

        new_label = payload.label or existing["label"]
        item_type = VaultItemType(existing["item_type"])

        new_secret_id = await cookie_vault.store_vault_item(
            tenant_id=tenant_id,
            user_id=user_id,
            item_type=item_type,
            label=new_label,
            sensitive_data=payload.data,
            expires_at=payload.expires_at,
            metadata=payload.metadata or existing.get("metadata"),
        )

        await audit_service.log_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=AuditEventType.ENCRYPTION_KEY_ROTATED,
            action="tenant_secret_rotated",
            resource_type="tenant_secret",
            resource_id=new_secret_id,
            details={
                "previous_secret_id": secret_id,
                "item_type": item_type.value,
                "label": new_label,
            },
            severity=AuditSeverity.HIGH,
        )

        metadata = await cookie_vault.list_vault_items(
            tenant_id, user_id, item_type=item_type
        )
        secret_meta = next((item for item in metadata if item["id"] == new_secret_id), None)
        if not secret_meta:
            raise HTTPException(status_code=404, detail="Secret metadata not found")
        return _serialize_secret(secret_meta)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to rotate secret %s for tenant %s", secret_id, tenant_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{secret_id}/revoke")
async def revoke_secret(
    secret_id: str,
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> None:
    """Revoke (delete) a secret from the vault."""

    tenant_id = str(current_user["tenant_id"])
    user_id = str(current_user["id"])

    try:
        success = await cookie_vault.delete_vault_item(secret_id, tenant_id, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Secret not found")

        await audit_service.log_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=AuditEventType.CONFIGURATION_CHANGED,
            action="tenant_secret_revoked",
            resource_type="tenant_secret",
            resource_id=secret_id,
            severity=AuditSeverity.HIGH,
        )
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to revoke secret %s for tenant %s", secret_id, tenant_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{secret_id}", response_model=SecretResponse, status_code=200)
async def get_secret(
    secret_id: str,
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> SecretResponse:
    """
    Retrieve a specific secret by ID.

    Returns metadata only - never returns plain text secret values.
    Implements tenant isolation to ensure users can only access their own secrets.
    """
    tenant_id = str(current_user["tenant_id"])
    user_id = str(current_user["id"])

    try:
        # List all secrets and find the matching one (ensures tenant isolation)
        metadata = await cookie_vault.list_vault_items(
            tenant_id=tenant_id,
            user_id=user_id,
            item_type=None,  # All types
        )

        secret_meta = next((item for item in metadata if item["id"] == secret_id), None)

        if not secret_meta:
            raise HTTPException(status_code=404, detail=f"Secret {secret_id} not found")

        # Log access for audit trail
        await audit_service.log_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=AuditEventType.CONFIGURATION_CHANGED,
            action="tenant_secret_accessed",
            resource_type="tenant_secret",
            resource_id=secret_id,
            severity=AuditSeverity.LOW,
        )

        return _serialize_secret(secret_meta)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to retrieve secret %s for tenant %s", secret_id, tenant_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{secret_id}", status_code=204)
async def delete_secret(
    secret_id: str,
    current_user: Dict[str, Any] = Depends(get_current_admin),
):
    """
    Delete a secret (alternative to POST /revoke).

    This endpoint provides DELETE method support for secret revocation.
    Tests try DELETE first, then fall back to POST if not available.
    Delegates to the same logic as POST /revoke for consistency.
    """
    # Delegate to revoke_secret for consistent behavior
    return await revoke_secret(secret_id, current_user)


@router.get("/audit-log", status_code=200)
async def get_secrets_audit_log(
    current_user: Dict[str, Any] = Depends(get_current_admin),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of audit entries to return"),
    offset: int = Query(0, ge=0, description="Number of audit entries to skip"),
):
    """
    Retrieve audit log for secrets management operations.

    Returns a paginated list of audit events related to secrets:
    - Secret creation
    - Secret rotation
    - Secret revocation
    - Secret access

    Implements tenant isolation to show only events for current tenant.
    """
    tenant_id = str(current_user["tenant_id"])

    try:
        # Query audit events for secrets-related operations
        # Using the audit service to fetch tenant-scoped events
        from .db_core import get_conn

        with get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT
                    id,
                    tenant_id,
                    user_id,
                    event_type,
                    action,
                    resource_type,
                    resource_id,
                    severity,
                    details,
                    created_at
                FROM audit_events
                WHERE tenant_id = ?
                  AND resource_type = 'tenant_secret'
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (tenant_id, limit, offset)
            )

            audit_entries = []
            for row in cursor.fetchall():
                audit_entries.append({
                    "id": row["id"],
                    "tenant_id": row["tenant_id"],
                    "user_id": row["user_id"],
                    "event_type": row["event_type"],
                    "action": row["action"],
                    "resource_type": row["resource_type"],
                    "resource_id": row["resource_id"],
                    "severity": row["severity"],
                    "details": row["details"],
                    "created_at": row["created_at"],
                })

            # Get total count for pagination
            count_cursor = conn.execute(
                """
                SELECT COUNT(*) as total
                FROM audit_events
                WHERE tenant_id = ?
                  AND resource_type = 'tenant_secret'
                """,
                (tenant_id,)
            )
            total = count_cursor.fetchone()["total"]

        return {
            "audit_log": audit_entries,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(audit_entries)) < total
        }

    except Exception as exc:
        logger.exception("Failed to retrieve audit log for tenant %s", tenant_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
