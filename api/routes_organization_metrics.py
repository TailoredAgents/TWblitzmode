"""
Organization Metrics API Routes

Provides real-time metrics and analytics for the Executive Overview Dashboard
with AI-powered insights and comprehensive performance tracking.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer
import asyncpg
from pydantic import BaseModel

from .deps import get_current_user, get_connection
from .websocket_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/organization", tags=["metrics"])
security = HTTPBearer()

class OrganizationMetrics(BaseModel):
    totalProspects: int
    activeWorkflows: int
    connectorsFound: int
    emailsSent: int
    conversionRate: float
    revenueImpact: int
    aiInsights: List[str]
    teamPerformance: List[Dict]

class MetricsTrend(BaseModel):
    current: float
    previous: float
    change: float
    trend: str

@router.get("/metrics")
async def get_organization_metrics(
    tenant_id: int = Query(..., description="Tenant ID"),
    range: str = Query("30d", description="Time range: 7d, 30d, 90d"),
    current_user: Dict = Depends(get_current_user)
):
    """Get comprehensive organization metrics for the executive dashboard"""

    if tenant_id != current_user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Unauthorized tenant access")

    try:
        # Calculate date range
        days = {"7d": 7, "30d": 30, "90d": 90}.get(range, 30)
        start_date = datetime.utcnow() - timedelta(days=days)
        previous_start = start_date - timedelta(days=days)

        async with get_connection() as conn:
            # Core metrics queries
            metrics_query = """
                WITH current_period AS (
                    SELECT
                        COUNT(DISTINCT p.id) as total_prospects,
                        COUNT(DISTINCT wc.workflow_id) as active_workflows,
                        COUNT(DISTINCT c.id) as connectors_found,
                        COUNT(DISTINCT ej.id) FILTER (WHERE ej.state IN ('sent', 'delivered', 'opened', 'replied')) as emails_sent
                    FROM prospects p
                    LEFT JOIN workflow_contexts wc ON wc.organization_id = p.organization_id
                        AND wc.workflow_state = 'active'
                        AND wc.created_at >= $2
                    LEFT JOIN prospect_connectors pc ON pc.prospect_id = p.id
                    LEFT JOIN connectors c ON c.id = pc.connector_id
                    LEFT JOIN email_jobs ej ON ej.prospect_connector_id = pc.id
                        AND ej.created_at >= $2
                    WHERE p.organization_id IN (
                        SELECT id FROM organizations WHERE tenant_id = $1
                    )
                ),
                previous_period AS (
                    SELECT
                        COUNT(DISTINCT p.id) as prev_prospects,
                        COUNT(DISTINCT c.id) as prev_connectors,
                        COUNT(DISTINCT ej.id) FILTER (WHERE ej.state IN ('sent', 'delivered', 'opened', 'replied')) as prev_emails
                    FROM prospects p
                    LEFT JOIN prospect_connectors pc ON pc.prospect_id = p.id
                    LEFT JOIN connectors c ON c.id = pc.connector_id
                    LEFT JOIN email_jobs ej ON ej.prospect_connector_id = pc.id
                        AND ej.created_at >= $3 AND ej.created_at < $2
                    WHERE p.organization_id IN (
                        SELECT id FROM organizations WHERE tenant_id = $1
                    )
                )
                SELECT
                    cp.total_prospects,
                    cp.active_workflows,
                    cp.connectors_found,
                    cp.emails_sent,
                    pp.prev_prospects,
                    pp.prev_connectors,
                    pp.prev_emails
                FROM current_period cp, previous_period pp
            """

            metrics_row = await conn.fetchrow(
                metrics_query,
                tenant_id,
                start_date,
                previous_start
            )

            # Conversion rate calculation
            conversion_query = """
                SELECT
                    COUNT(DISTINCT ej.id) FILTER (WHERE ej.state IN ('replied', 'interested')) as conversions,
                    COUNT(DISTINCT ej.id) FILTER (WHERE ej.state IN ('sent', 'delivered', 'opened', 'replied')) as total_sent
                FROM email_jobs ej
                JOIN prospect_connectors pc ON pc.id = ej.prospect_connector_id
                JOIN prospects p ON p.id = pc.prospect_id
                WHERE p.organization_id IN (
                    SELECT id FROM organizations WHERE id = (
                        SELECT organization_id FROM team_members
                        WHERE id = $1 OR (SELECT organization_id FROM users WHERE id = $1) = organization_id
                    )
                )
                AND ej.created_at >= $2
            """

            conversion_row = await conn.fetchrow(conversion_query, tenant_id, start_date)

            # Team performance
            team_performance_query = """
                SELECT
                    tm.name,
                    COUNT(DISTINCT p.id) as prospects,
                    COUNT(DISTINCT c.id) as connectors,
                    COUNT(DISTINCT ej.id) FILTER (WHERE ej.state IN ('sent', 'delivered', 'opened', 'replied')) as emails,
                    COUNT(DISTINCT ej.id) FILTER (WHERE ej.state IN ('replied', 'interested')) as conversions
                FROM team_members tm
                LEFT JOIN prospect_connectors pc ON pc.team_member_id = tm.id
                LEFT JOIN prospects p ON p.id = pc.prospect_id AND p.created_at >= $2
                LEFT JOIN connectors c ON c.id = pc.connector_id
                LEFT JOIN email_jobs ej ON ej.prospect_connector_id = pc.id AND ej.created_at >= $2
                WHERE tm.organization_id IN (
                    SELECT id FROM organizations WHERE id = (
                        SELECT organization_id FROM team_members
                        WHERE id = $1 OR (SELECT organization_id FROM users WHERE id = $1) = organization_id
                    )
                )
                AND tm.status = 'active'
                GROUP BY tm.id, tm.name
                ORDER BY conversions DESC
                LIMIT 10
            """

            team_rows = await conn.fetch(team_performance_query, tenant_id, start_date)

            # Recent AI insights from agent decisions
            ai_insights_query = """
                SELECT reasoning, confidence_score
                FROM agent_decisions ad
                JOIN workflow_contexts wc ON wc.workflow_id = ad.workflow_id
                WHERE ad.tenant_id = $1
                AND ad.reasoning IS NOT NULL
                AND ad.confidence_score > 0.7
                AND ad.decided_at >= $2
                ORDER BY ad.decided_at DESC, ad.confidence_score DESC
                LIMIT 6
            """

            insights_rows = await conn.fetch(ai_insights_query, tenant_id, start_date)

            # Revenue impact calculation (simplified)
            revenue_query = """
                SELECT
                    COUNT(DISTINCT ej.id) FILTER (WHERE ej.state IN ('replied', 'interested')) * 12500 as pipeline_generated,
                    AVG(CASE WHEN ej.state IN ('replied', 'interested') THEN 12500 ELSE 0 END) as avg_deal_size
                FROM email_jobs ej
                JOIN prospect_connectors pc ON pc.id = ej.prospect_connector_id
                JOIN prospects p ON p.id = pc.prospect_id
                WHERE p.organization_id IN (
                    SELECT id FROM organizations WHERE id = (
                        SELECT organization_id FROM team_members
                        WHERE id = $1 OR (SELECT organization_id FROM users WHERE id = $1) = organization_id
                    )
                )
                AND ej.created_at >= $2
            """

            revenue_row = await conn.fetchrow(revenue_query, tenant_id, start_date)

            # Build response
            metrics_values = dict(metrics_row or {})
            total_prospects = metrics_values.get("total_prospects", 0) or 0
            active_workflows = metrics_values.get("active_workflows", 0) or 0
            connectors_found = metrics_values.get("connectors_found", 0) or 0
            emails_sent = metrics_values.get("emails_sent", 0) or 0

            conversion_values = dict(conversion_row or {})
            conversions = conversion_values.get("conversions", 0) or 0
            total_sent = conversion_values.get("total_sent", 0) or 0
            if total_sent == 0:
                total_sent = 1  # Avoid division by zero
            conversion_rate = (conversions / total_sent) * 100

            # AI Insights processing
            ai_insights = []
            if insights_rows:
                for insight_row in insights_rows:
                    if insight_row["reasoning"]:
                        ai_insights.append(insight_row["reasoning"][:150] + "..." if len(insight_row["reasoning"]) > 150 else insight_row["reasoning"])

            # Default insights if none from AI
            if not ai_insights:
                ai_insights = [
                    f"Your team has processed {total_prospects} prospects with {conversion_rate:.1f}% conversion rate",
                    f"Most active connectors are generating {connectors_found/max(total_prospects, 1)*100:.0f}% discovery rate",
                    f"Email engagement shows strongest performance in {range.replace('d', ' day')} period"
                ]

            # Team performance formatting
            team_performance = []
            for row in team_rows:
                team_performance.append({
                    "name": row["name"],
                    "prospects": row["prospects"] or 0,
                    "connectors": row["connectors"] or 0,
                    "emails": row["emails"] or 0,
                    "conversions": row["conversions"] or 0
                })

            revenue_values = dict(revenue_row or {})

            metrics = {
                "totalProspects": total_prospects,
                "activeWorkflows": active_workflows,
                "connectorsFound": connectors_found,
                "emailsSent": emails_sent,
                "conversionRate": round(conversion_rate, 1),
                "revenueImpact": revenue_values.get("pipeline_generated", 0) or 0,
                "aiInsights": ai_insights,
                "teamPerformance": team_performance
            }

            # Broadcast metrics update via WebSocket
            try:
                await ws_manager.broadcast_approval_update(str(tenant_id), {
                    "type": "metrics_update",
                    "metrics": metrics,
                    "timestamp": datetime.utcnow().isoformat()
                })
            except Exception as e:
                logger.warning(f"Failed to broadcast metrics update: {e}")

            return {"metrics": metrics, "range": range, "updated_at": datetime.utcnow().isoformat()}

    except Exception as e:
        logger.error(f"Error fetching organization metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch metrics")

@router.get("/trends")
async def get_metrics_trends(
    tenant_id: int = Query(..., description="Tenant ID"),
    metric: str = Query(..., description="Metric name: prospects, connectors, emails, conversions"),
    current_user: Dict = Depends(get_current_user)
):
    """Get trend data for a specific metric"""

    if tenant_id != current_user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Unauthorized tenant access")

    try:
        # Calculate 30-day periods
        end_date = datetime.utcnow()
        current_start = end_date - timedelta(days=30)
        previous_start = current_start - timedelta(days=30)

        async with get_connection() as conn:
            if metric == "prospects":
                query = """
                    WITH current_period AS (
                        SELECT COUNT(*) as value
                        FROM prospects p
                        WHERE p.organization_id IN (
                            SELECT id FROM organizations WHERE id = (
                                SELECT organization_id FROM team_members
                                WHERE id = $1 OR (SELECT organization_id FROM users WHERE id = $1) = organization_id
                            )
                        )
                        AND p.created_at >= $2
                    ),
                    previous_period AS (
                        SELECT COUNT(*) as value
                        FROM prospects p
                        WHERE p.organization_id IN (
                            SELECT id FROM organizations WHERE id = (
                                SELECT organization_id FROM team_members
                                WHERE id = $1 OR (SELECT organization_id FROM users WHERE id = $1) = organization_id
                            )
                        )
                        AND p.created_at >= $3 AND p.created_at < $2
                    )
                    SELECT
                        cp.value as current_value,
                        pp.value as previous_value
                    FROM current_period cp, previous_period pp
                """
            elif metric == "connectors":
                query = """
                    WITH current_period AS (
                        SELECT COUNT(DISTINCT c.id) as value
                        FROM connectors c
                        JOIN prospect_connectors pc ON pc.connector_id = c.id
                        JOIN prospects p ON p.id = pc.prospect_id
                        WHERE p.organization_id IN (
                            SELECT id FROM organizations WHERE id = (
                                SELECT organization_id FROM team_members
                                WHERE id = $1 OR (SELECT organization_id FROM users WHERE id = $1) = organization_id
                            )
                        )
                        AND pc.created_at >= $2
                    ),
                    previous_period AS (
                        SELECT COUNT(DISTINCT c.id) as value
                        FROM connectors c
                        JOIN prospect_connectors pc ON pc.connector_id = c.id
                        JOIN prospects p ON p.id = pc.prospect_id
                        WHERE p.organization_id IN (
                            SELECT id FROM organizations WHERE id = (
                                SELECT organization_id FROM team_members
                                WHERE id = $1 OR (SELECT organization_id FROM users WHERE id = $1) = organization_id
                            )
                        )
                        AND pc.created_at >= $3 AND pc.created_at < $2
                    )
                    SELECT
                        cp.value as current_value,
                        pp.value as previous_value
                    FROM current_period cp, previous_period pp
                """
            elif metric == "emails":
                query = """
                    WITH current_period AS (
                        SELECT COUNT(*) as value
                        FROM email_jobs ej
                        JOIN prospect_connectors pc ON pc.id = ej.prospect_connector_id
                        JOIN prospects p ON p.id = pc.prospect_id
                        WHERE p.organization_id IN (
                            SELECT id FROM organizations WHERE id = (
                                SELECT organization_id FROM team_members
                                WHERE id = $1 OR (SELECT organization_id FROM users WHERE id = $1) = organization_id
                            )
                        )
                        AND ej.state IN ('sent', 'delivered', 'opened', 'replied')
                        AND ej.created_at >= $2
                    ),
                    previous_period AS (
                        SELECT COUNT(*) as value
                        FROM email_jobs ej
                        JOIN prospect_connectors pc ON pc.id = ej.prospect_connector_id
                        JOIN prospects p ON p.id = pc.prospect_id
                        WHERE p.organization_id IN (
                            SELECT id FROM organizations WHERE id = (
                                SELECT organization_id FROM team_members
                                WHERE id = $1 OR (SELECT organization_id FROM users WHERE id = $1) = organization_id
                            )
                        )
                        AND ej.state IN ('sent', 'delivered', 'opened', 'replied')
                        AND ej.created_at >= $3 AND ej.created_at < $2
                    )
                    SELECT
                        cp.value as current_value,
                        pp.value as previous_value
                    FROM current_period cp, previous_period pp
                """
            else:
                raise HTTPException(status_code=400, detail="Invalid metric type")

            row = await conn.fetchrow(query, tenant_id, current_start, previous_start)
            row_values = dict(row or {})

            current_value = float(row_values.get("current_value", 0) or 0)
            previous_value = float(row_values.get("previous_value", 0) or 0)
            if previous_value == 0:
                previous_value = 1.0  # Avoid division by zero

            change = ((current_value - previous_value) / previous_value) * 100
            trend = "up" if change > 0 else "down" if change < 0 else "neutral"

            return {
                "metric": metric,
                "current": current_value,
                "previous": previous_value,
                "change": round(change, 1),
                "trend": trend
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching trend data for {metric}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch trend data")

@router.post("/metrics/refresh")
async def refresh_metrics_cache(
    tenant_id: int = Query(..., description="Tenant ID"),
    current_user: Dict = Depends(get_current_user)
):
    """Manually refresh metrics cache and broadcast updates"""

    try:
        # Trigger metrics recalculation
        metrics_response = await get_organization_metrics(tenant_id, "30d", current_user)

        # Broadcast via WebSocket
        await ws_manager.broadcast_approval_update(str(tenant_id), {
            "type": "metrics_refresh",
            "metrics": metrics_response["metrics"],
            "timestamp": datetime.utcnow().isoformat()
        })

        return {"success": True, "message": "Metrics refreshed successfully"}

    except Exception as e:
        logger.error(f"Error refreshing metrics cache: {e}")
        raise HTTPException(status_code=500, detail="Failed to refresh metrics")

# WebSocket endpoint for metrics updates
@router.websocket("/ws/metrics/{tenant_id}")
async def websocket_metrics_endpoint(websocket, tenant_id: str):
    """WebSocket endpoint for real-time metrics updates"""
    await websocket.accept()

    try:
        path = f"/ws/metrics/{tenant_id}"
        await ws_manager.handle_connection(websocket, path)
    except Exception as e:
        logger.error(f"WebSocket metrics error for tenant {tenant_id}: {e}")
        await websocket.close(1011, "Internal server error")

@router.get("/export")
async def export_metrics_report(
    tenant_id: int = Query(..., description="Tenant ID"),
    format: str = Query("csv", description="Export format: csv, xlsx, json"),
    range: str = Query("30d", description="Time range"),
    current_user: Dict = Depends(get_current_user)
):
    """Export comprehensive metrics report"""

    try:
        # Get metrics data
        metrics_response = await get_organization_metrics(tenant_id, range, current_user)
        metrics = metrics_response["metrics"]

        if format == "json":
            return {
                "export_data": metrics,
                "generated_at": datetime.utcnow().isoformat(),
                "range": range,
                "tenant_id": tenant_id
            }

        # For CSV/XLSX, would implement pandas export here
        # For now, return JSON with export metadata
        return {
            "message": f"Export in {format} format not yet implemented",
            "available_formats": ["json"],
            "data": metrics
        }

    except Exception as e:
        logger.error(f"Error exporting metrics report: {e}")
        raise HTTPException(status_code=500, detail="Failed to export metrics report")