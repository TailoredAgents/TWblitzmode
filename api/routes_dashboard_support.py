from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from core.feature_flags import feature_flag_payload
from api.database import get_db_connection
from .deps import get_current_user

try:  # psycopg2 is expected at runtime; guard so linters don't fail
    from psycopg2.errors import UndefinedColumn  # type: ignore[import]
except Exception:  # pragma: no cover - fallback for limited environments
    UndefinedColumn = Exception  # type: ignore[assignment]

logger = logging.getLogger(__name__)

try:
    from src.services.tier_service import build_tier_payload  # type: ignore
except ImportError:  # pragma: no cover - fallback for legacy layout
    from services.tier_service import build_tier_payload  # type: ignore

try:
    from src.services.cookie_vault_service import cookie_vault  # type: ignore
except ImportError:  # pragma: no cover - local development without vault service
    cookie_vault = None  # type: ignore[assignment]


router = APIRouter(prefix="/api", tags=["dashboard"])


async def _load_dashboard_overview(user_id: int, tenant_id: str) -> Dict[str, Any]:
    """Collect dashboard metrics using the native adapter on a worker thread."""

    def _collect() -> Dict[str, Any]:
        overview: Dict[str, Any] = {
            "prospects": {
                "total": 0,
                "by_status": {},
                "this_week": 0,
                "completion_rate": 0.0,
            },
            "connectors": {
                "total": 0,
                "with_emails": 0,
                "avg_score": 0.0,
            },
            "workflows": {
                "total": 0,
                "pending_approval": 0,
                "completed_this_week": 0,
                "success_rate": 0.0,
            },
            "quotas": {
                "emails_sent_this_week": 0,
                "weekly_limit": 0,
                "utilization": 0.0,
            },
            "integrations": {
                "apify": "disconnected",
                "cufinder": "disconnected",
                "email_provider": "disconnected",
            },
            "metadata": {},
        }

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Prospect status counts (fallback to unknown until column lands)
                    try:
                        cursor.execute(
                            """
                            SELECT COALESCE(status, 'unknown') AS status,
                                   COUNT(*)::int AS count
                            FROM prospects
                            WHERE user_id = %s AND tenant_id = %s
                            GROUP BY status
                            """,
                            (user_id, tenant_id),
                        )
                        status_rows = cursor.fetchall() or []
                        status_map: Dict[str, int] = {}
                        for raw_row in status_rows:
                            record = dict(raw_row)
                            status_key = record.get("status") or "unknown"
                            status_map[status_key] = int(record.get("count") or 0)
                        overview["prospects"]["by_status"] = status_map
                    except UndefinedColumn:
                        # Reset the transaction before issuing any more queries.
                        # Without this, subsequent statements would fail with
                        # InFailedSqlTransaction and the dashboard would keep retrying.
                        try:
                            conn.rollback()
                        except Exception as rollback_error:
                            logger.warning(
                                "Rollback after missing prospects.status failed: %s",
                                rollback_error,
                                extra={"user_id": user_id, "tenant_id": tenant_id},
                            )
                        # TODO: Revert to real grouping once prospects.status is added in prod.
                        logger.warning(
                            "prospects.status column missing - defaulting dashboard status counts",
                            extra={"user_id": user_id, "tenant_id": tenant_id},
                        )
                        overview["prospects"]["by_status"] = {"unknown": 0}

                    # Total prospects
                    cursor.execute(
                        """
                        SELECT COUNT(*)::int AS total
                        FROM prospects
                        WHERE user_id = %s AND tenant_id = %s
                        """,
                        (user_id, tenant_id),
                    )
                    total_row = cursor.fetchone() or {"total": 0}
                    total_prospects = int(dict(total_row).get("total", 0) or 0)
                    overview["prospects"]["total"] = total_prospects

                    # Prospects created this week
                    cursor.execute(
                        """
                        SELECT COUNT(*)::int AS total
                        FROM prospects
                        WHERE user_id = %s
                          AND tenant_id = %s
                          AND COALESCE(created_at, NOW()) >= NOW() - INTERVAL '7 days'
                        """,
                        (user_id, tenant_id),
                    )
                    week_row = cursor.fetchone() or {"total": 0}
                    prospects_this_week = int(dict(week_row).get("total", 0) or 0)
                    overview["prospects"]["this_week"] = prospects_this_week

                    # Completed introductions
                    cursor.execute(
                        """
                        SELECT COUNT(*)::int AS total
                        FROM introductions
                        WHERE tenant_id = %s
                          AND status IN ('sent', 'approved', 'completed')
                        """,
                        (tenant_id,),
                    )
                    introductions_row = cursor.fetchone() or {"total": 0}
                    introductions_completed = int(dict(introductions_row).get("total", 0) or 0)
                    overview["prospects"]["completion_rate"] = (
                        float(introductions_completed) / float(total_prospects)
                        if total_prospects
                        else 0.0
                    )

                    # Connector metrics
                    try:
                        cursor.execute(
                            """
                            SELECT
                                COUNT(*)::int AS total,
                                SUM(
                                    CASE
                                        WHEN connector_email IS NOT NULL AND connector_email <> ''
                                        THEN 1 ELSE 0
                                    END
                                )::int AS with_email,
                                AVG(COALESCE(ranking_score, 0)) AS avg_score
                            FROM mutual_connections
                            WHERE user_id = %s AND tenant_id = %s
                            """,
                            (user_id, tenant_id),
                        )
                        connector_row = cursor.fetchone() or {}
                        row_dict = dict(connector_row)
                        overview["connectors"]["total"] = int(row_dict.get("total", 0) or 0)
                        overview["connectors"]["with_emails"] = int(row_dict.get("with_email", 0) or 0)
                        avg_score = row_dict.get("avg_score", 0.0)
                        overview["connectors"]["avg_score"] = float(avg_score or 0.0)
                    except Exception:
                        logger.debug("Mutual connections table unavailable for user %s", user_id, exc_info=True)

                    # Workflow metrics
                    workflows_total = workflows_pending = workflows_completed_all_time = workflows_completed_week = 0
                    organization_lookup = None
                    try:
                        organization_lookup = int(tenant_id)
                    except (TypeError, ValueError):
                        organization_lookup = None

                    try:
                        cursor.execute(
                            """
                            SELECT
                                COUNT(*)::int AS total,
                                SUM(CASE WHEN status IN ('running', 'pending', 'approved') THEN 1 ELSE 0 END)::int AS pending,
                                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)::int AS completed,
                                SUM(
                                    CASE
                                        WHEN status = 'completed'
                                             AND COALESCE(updated_at, NOW()) >= NOW() - INTERVAL '7 days'
                                        THEN 1 ELSE 0
                                    END
                                )::int AS completed_week
                            FROM workflow_executions
                            WHERE tenant_id = %s OR organization_id = %s
                            """,
                            (str(tenant_id), organization_lookup if organization_lookup is not None else -1),
                        )
                        workflow_row = cursor.fetchone() or {}
                        row_dict = dict(workflow_row)
                        workflows_total = int(row_dict.get("total", 0) or 0)
                        workflows_pending = int(row_dict.get("pending", 0) or 0)
                        workflows_completed_all_time = int(row_dict.get("completed", 0) or 0)
                        workflows_completed_week = int(row_dict.get("completed_week", 0) or 0)
                    except Exception:
                        logger.debug("Workflow executions table unavailable for tenant %s", tenant_id, exc_info=True)

                    overview["workflows"]["total"] = workflows_total
                    overview["workflows"]["pending_approval"] = workflows_pending
                    overview["workflows"]["completed_this_week"] = workflows_completed_week
                    overview["workflows"]["success_rate"] = (
                        float(workflows_completed_all_time) / float(workflows_total)
                        if workflows_total
                        else 0.0
                    )

                    # Email quota metrics
                    try:
                        cursor.execute(
                            """
                            SELECT COUNT(*)::int AS total
                            FROM introductions
                            WHERE user_id = %s
                              AND tenant_id = %s
                              AND sent_date IS NOT NULL
                              AND COALESCE(sent_date::timestamptz, NOW()) >= NOW() - INTERVAL '7 days'
                            """,
                            (user_id, tenant_id),
                        )
                        email_row = cursor.fetchone() or {"total": 0}
                        overview["quotas"]["emails_sent_this_week"] = int(dict(email_row).get("total", 0) or 0)
                    except Exception:
                        logger.debug("introductions table missing sent_date for tenant %s", tenant_id, exc_info=True)

                    # Integration status
                    try:
                        cursor.execute(
                            """
                            SELECT apify_api_key, cufinder_api_key, smtp_config_encrypted
                            FROM integration_sets
                            WHERE tenant_id = %s OR organization_id = %s
                            ORDER BY updated_at DESC
                            LIMIT 1
                            """,
                            (str(tenant_id), organization_lookup if organization_lookup is not None else -1),
                        )
                        integration_row = cursor.fetchone()
                        if integration_row:
                            payload = dict(integration_row)
                            overview["integrations"]["apify"] = (
                                "connected" if payload.get("apify_api_key") else "disconnected"
                            )
                            overview["integrations"]["cufinder"] = (
                                "connected" if payload.get("cufinder_api_key") else "disconnected"
                            )
                            overview["integrations"]["email_provider"] = (
                                "connected" if payload.get("smtp_config_encrypted") else "disconnected"
                            )
                    except Exception:
                        logger.debug("integration_sets table unavailable for tenant %s", tenant_id, exc_info=True)
            overview["metadata"]["last_updated"] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            logger.warning("Dashboard overview query failed for user %s tenant %s: %s", user_id, tenant_id, exc)

        return overview

    return await asyncio.to_thread(_collect)


async def _load_organization_record(organization_identifier: str) -> Optional[Dict[str, Any]]:
    """Fetch organization metadata by id or tenant string."""

    identifier = str(organization_identifier).strip()
    if not identifier:
        return None

    def _query() -> Optional[Dict[str, Any]]:
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM organizations WHERE id = %s LIMIT 1",
                        (identifier,),
                    )
                    row = cursor.fetchone()
                    if row:
                        record = dict(row)
                        record.setdefault("organization_id", record.get("id"))
                        tenant_value = record.get("tenant_id") or record.get("organization_id") or identifier
                        record["tenant_id"] = str(tenant_value)
                        return record

                    cursor.execute(
                        "SELECT * FROM organizations WHERE tenant_id = %s LIMIT 1",
                        (identifier,),
                    )
                    row = cursor.fetchone()
                    if row:
                        record = dict(row)
                        record.setdefault("organization_id", record.get("id"))
                        tenant_value = record.get("tenant_id") or identifier
                        record["tenant_id"] = str(tenant_value)
                        return record
        except Exception:
            logger.debug("Organization lookup failed for identifier %s", identifier, exc_info=True)
        return None

    return await asyncio.to_thread(_query)


@router.get("/feature-flags")
async def get_feature_flags(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Return evaluated feature flags for the authenticated tenant."""

    tenant_raw = current_user.get("tenant_id")
    try:
        tenant_id = int(tenant_raw) if tenant_raw is not None else None
    except (TypeError, ValueError):
        tenant_id = None

    payload = feature_flag_payload(tenant_id)
    return {"status": "success", "data": payload}


@router.get("/analytics/overview", response_model=None)
async def get_analytics_overview(
    days: int = Query(30, ge=1, le=365),
    organization_id: Optional[str] = Query(None),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any] | JSONResponse:
    """Aggregate analytics metrics for the dashboard overview cards."""

    user_identifier = current_user.get("user_id") or current_user.get("id")
    if user_identifier is None:
        raise HTTPException(status_code=401, detail="User context unavailable")

    tenant_context: Optional[str] = current_user.get("tenant_id") or current_user.get("organization_id")

    if organization_id is not None:
        current_org = current_user.get("organization_id")
        role = (current_user.get("role") or "").lower()
        if current_org is not None and str(organization_id) != str(current_org) and role != "admin":
            raise HTTPException(status_code=403, detail="Cross-tenant analytics access is restricted")
        tenant_context = organization_id

    if tenant_context is None:
        logger.debug("Analytics overview requested without tenant context for user %s", user_identifier)
        return {"status": "success", "data": {"metadata": {"requested_days": days}}}

    try:
        overview = await _load_dashboard_overview(int(user_identifier), str(tenant_context))
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning(
            "Failed to load analytics overview for user %s tenant %s: %s",
            user_identifier,
            tenant_context,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Failed to load analytics overview"},
        )

    metadata = {
        "requested_days": days,
        "tenant_id": str(tenant_context),
        "user_id": str(user_identifier),
    }

    if isinstance(overview, dict):
        existing_meta = overview.get("metadata")
        if isinstance(existing_meta, dict):
            existing_meta.update(metadata)
        else:
            overview["metadata"] = metadata
    else:
        overview = {"metadata": metadata}

    return {"status": "success", "data": overview}


@router.get("/user/tier-info")
async def get_user_tier_info(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Provide tier metadata for Link chat guardrails and capability gating."""

    organization: Optional[Dict[str, Any]] = None
    organization_id = current_user.get("organization_id")
    if organization_id is not None:
        try:
            organization = await _load_organization_record(str(organization_id))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Unable to load organization %s for tier info: %s", organization_id, exc)

    payload = build_tier_payload(user=current_user, organization=organization)

    tenant_identifier = (
        current_user.get("tenant_id")
        or current_user.get("organization_id")
        or (organization.get("id") if isinstance(organization, dict) else None)
    )

    if tenant_identifier and payload.get("cookieVaultAccess") and cookie_vault is not None:
        try:
            payload["cookieVaultSummary"] = await cookie_vault.summarize_linkedin_cookies(str(tenant_identifier))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug(
                "Unable to load cookie vault summary for tenant %s: %s",
                tenant_identifier,
                exc,
            )

    return payload
