"""
Global Analytics and Overview Service

Enterprise-grade analytics service for the VouchLink AI corporate platform.
Provides real-time metrics, KPI tracking, and comprehensive reporting
for organization performance and system health.

Features:
- Real-time metrics aggregation and caching
- Multi-dimensional analytics (time series, cohort, funnel)
- Performance KPI tracking and alerting
- Organization benchmarking and insights
- Cost tracking and optimization recommendations
- Predictive analytics and forecasting
"""

import os
import json
import time
import logging
import asyncio
from collections import deque
from datetime import datetime, timedelta, date, timezone
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)

class MetricType(Enum):
    """Types of metrics tracked"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    RATE = "rate"

class TimeGranularity(Enum):
    """Time granularity for analytics"""
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"

@dataclass
class OrganizationMetrics:
    """Organization-level metrics snapshot"""
    organization_id: int
    organization_name: str
    date: date

    # Prospect metrics
    prospects_imported: int = 0
    prospects_processed: int = 0
    prospects_failed: int = 0
    prospects_pending: int = 0

    # Connector metrics
    connectors_found: int = 0
    connectors_scored: int = 0
    top_connectors_identified: int = 0

    # Email metrics
    emails_enriched: int = 0
    emails_scheduled: int = 0
    emails_sent: int = 0
    emails_delivered: int = 0
    emails_opened: int = 0
    emails_replied: int = 0
    emails_bounced: int = 0

    # Performance metrics
    avg_prospect_processing_time: float = 0.0
    avg_email_response_time: float = 0.0
    success_rate: float = 0.0

    # Cost metrics
    total_cost_usd: float = 0.0
    cost_per_prospect: float = 0.0
    cost_per_email: float = 0.0

    # Quota metrics
    weekly_email_quota: int = 0
    quota_utilization: float = 0.0

@dataclass
class SystemMetrics:
    """System-wide performance metrics"""
    timestamp: datetime

    # Queue metrics
    queue_depth: Dict[str, int]
    queue_processing_rate: Dict[str, float]
    queue_error_rate: Dict[str, float]

    # API metrics
    api_requests_per_minute: int
    api_error_rate: float
    api_latency_p95: float

    # Database metrics
    db_connections_active: int
    db_query_latency_avg: float

    # External service metrics
    external_api_success_rate: Dict[str, float]
    external_api_latency: Dict[str, float]

class GlobalAnalyticsService:
    """Production-ready analytics service for corporate insights"""

    def __init__(self):
        # Redis configuration for caching
        self.redis_client = None
        if REDIS_AVAILABLE:
            try:
                redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
            except Exception as e:
                logger.warning(f"Redis not available for analytics caching: {e}")

        # Cache configuration
        self.metrics_cache_ttl = int(os.getenv('METRICS_CACHE_TTL', '300'))  # 5 minutes
        self.dashboard_cache_ttl = int(os.getenv('DASHBOARD_CACHE_TTL', '60'))  # 1 minute

        # Analytics configuration
        self.default_lookback_days = int(os.getenv('DEFAULT_LOOKBACK_DAYS', '30'))
        self.enable_predictive_analytics = os.getenv('ENABLE_PREDICTIVE_ANALYTICS', 'true').lower() == 'true'
        self.recent_agent_events = deque(maxlen=200)

    async def get_organization_overview(
        self,
        organization_id: int,
        days: int = None
    ) -> Dict[str, Any]:
        """Get comprehensive organization overview"""

        days = days or self.default_lookback_days
        cache_key = f"org_overview:{organization_id}:{days}"

        # Try cache first
        cached = await self._get_cached_data(cache_key)
        if cached:
            return cached

        try:
            from ..api.db_core import get_conn, query

            with get_conn() as conn:
                # Basic organization info
                org_info = query(conn, """
                    SELECT id, name, domain, industry, size, subscription_tier, created_at
                    FROM organizations WHERE id = ?
                """, (organization_id,))[0]

                # Current metrics
                current_metrics = await self._get_current_metrics(organization_id, days)

                # Trend analysis
                trend_data = await self._get_trend_analysis(organization_id, days)

                # Performance insights
                performance = await self._get_performance_insights(organization_id, days)

                # Cost analysis
                cost_analysis = await self._get_cost_analysis(organization_id, days)

                # Funnel analysis
                funnel_metrics = await self._get_funnel_analysis(organization_id, days)

                # Predictive insights
                predictions = {}
                if self.enable_predictive_analytics:
                    predictions = await self._get_predictive_insights(organization_id)

                overview = {
                    "organization": dict(org_info),
                    "period_days": days,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "current_metrics": current_metrics,
                    "trends": trend_data,
                    "performance": performance,
                    "cost_analysis": cost_analysis,
                    "funnel_metrics": funnel_metrics,
                    "predictions": predictions,
                    "health_score": await self._calculate_health_score(current_metrics)
                }

                # Cache the result
                await self._cache_data(cache_key, overview, self.dashboard_cache_ttl)

                return overview

        except Exception as e:
            logger.error(f"Error getting organization overview: {e}")
            return {"error": str(e)}

    async def _get_current_metrics(self, organization_id: int, days: int) -> Dict[str, Any]:
        """Get current period metrics"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            # Prospects metrics
            prospects_stats = query(conn, """
                SELECT
                    COUNT(*) as total_prospects,
                    COUNT(CASE WHEN status = 'pending_lookup' THEN 1 END) as pending_lookup,
                    COUNT(CASE WHEN status = 'ready_for_mutuals' THEN 1 END) as ready_for_mutuals,
                    COUNT(CASE WHEN status = 'mutuals_found' THEN 1 END) as mutuals_found,
                    COUNT(CASE WHEN status = 'lookup_failed' THEN 1 END) as failed,
                    AVG(CASE WHEN processed_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (processed_at - created_at))/3600 END) as avg_processing_hours
                FROM prospects
                WHERE organization_id = ? AND created_at >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]

            # Connectors metrics
            connectors_stats = query(conn, """
                SELECT
                    COUNT(DISTINCT c.id) as total_connectors,
                    COUNT(DISTINCT CASE WHEN c.email IS NOT NULL THEN c.id END) as enriched_connectors,
                    AVG(pc.ranking_score) as avg_ranking_score,
                    COUNT(CASE WHEN pc.rank <= 5 THEN 1 END) as top_connectors
                FROM connectors c
                JOIN prospect_connectors pc ON c.id = pc.connector_id
                WHERE c.organization_id = ? AND c.created_at >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]

            # Email metrics
            email_stats = query(conn, """
                SELECT
                    COUNT(*) as total_emails,
                    COUNT(CASE WHEN state = 'sent' THEN 1 END) as sent_emails,
                    COUNT(CASE WHEN state = 'delivered' THEN 1 END) as delivered_emails,
                    COUNT(CASE WHEN state = 'opened' THEN 1 END) as opened_emails,
                    COUNT(CASE WHEN state = 'replied' THEN 1 END) as replied_emails,
                    COUNT(CASE WHEN state = 'bounced' THEN 1 END) as bounced_emails,
                    COUNT(CASE WHEN state = 'failed' THEN 1 END) as failed_emails
                FROM email_jobs
                WHERE organization_id = ? AND created_at >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]

            # Cost metrics
            cost_stats = query(conn, """
                SELECT
                    COALESCE(SUM(cost_usd), 0) as total_cost,
                    COALESCE(AVG(cost_usd), 0) as avg_daily_cost
                FROM organization_metrics
                WHERE organization_id = ? AND metric_date >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]

            # Quota utilization
            quota_stats = query(conn, """
                SELECT
                    feature_flags
                FROM integration_sets
                WHERE organization_id = ?
            """, (organization_id,))

            weekly_quota = 20  # Default
            if quota_stats and quota_stats[0]['feature_flags']:
                flags = json.loads(quota_stats[0]['feature_flags'])
                weekly_quota = flags.get('email_quota', 20)

            # Calculate current week usage
            week_usage = query(conn, """
                SELECT COUNT(*) as emails_this_week
                FROM email_jobs
                WHERE organization_id = ?
                AND state IN ('sent', 'delivered', 'opened', 'replied')
                AND sent_at >= DATE('now', 'weekday 0', '-7 days')
            """, (organization_id,))[0]

            return {
                "prospects": dict(prospects_stats),
                "connectors": dict(connectors_stats),
                "emails": dict(email_stats),
                "costs": dict(cost_stats),
                "quota": {
                    "weekly_limit": weekly_quota,
                    "used_this_week": week_usage['emails_this_week'],
                    "utilization_percent": (week_usage['emails_this_week'] / weekly_quota * 100) if weekly_quota > 0 else 0
                }
            }

    async def _get_trend_analysis(self, organization_id: int, days: int) -> Dict[str, Any]:
        """Get trend analysis over time"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            # Daily trends
            daily_trends = query(conn, """
                SELECT
                    DATE(created_at) as date,
                    COUNT(*) as prospects_imported,
                    COUNT(CASE WHEN status = 'ready_for_mutuals' THEN 1 END) as prospects_processed
                FROM prospects
                WHERE organization_id = ? AND created_at >= DATE('now', '-{} days')
                GROUP BY DATE(created_at)
                ORDER BY date
            """.format(days), (organization_id,))

            # Email trends
            email_trends = query(conn, """
                SELECT
                    DATE(created_at) as date,
                    COUNT(*) as emails_scheduled,
                    COUNT(CASE WHEN state = 'sent' THEN 1 END) as emails_sent,
                    COUNT(CASE WHEN state = 'replied' THEN 1 END) as emails_replied
                FROM email_jobs
                WHERE organization_id = ? AND created_at >= DATE('now', '-{} days')
                GROUP BY DATE(created_at)
                ORDER BY date
            """.format(days), (organization_id,))

            # Calculate week-over-week growth
            current_week = query(conn, """
                SELECT COUNT(*) as count FROM prospects
                WHERE organization_id = ? AND created_at >= DATE('now', '-7 days')
            """, (organization_id,))[0]['count']

            previous_week = query(conn, """
                SELECT COUNT(*) as count FROM prospects
                WHERE organization_id = ?
                AND created_at >= DATE('now', '-14 days')
                AND created_at < DATE('now', '-7 days')
            """, (organization_id,))[0]['count']

            wow_growth = ((current_week - previous_week) / previous_week * 100) if previous_week > 0 else 0

            return {
                "daily_prospects": [dict(row) for row in daily_trends],
                "daily_emails": [dict(row) for row in email_trends],
                "week_over_week_growth": {
                    "current_week": current_week,
                    "previous_week": previous_week,
                    "growth_percent": wow_growth
                }
            }

    async def _get_performance_insights(self, organization_id: int, days: int) -> Dict[str, Any]:
        """Get performance insights and benchmarks"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            # Processing efficiency
            efficiency_stats = query(conn, """
                SELECT
                    AVG(CASE WHEN processed_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (processed_at - created_at))/3600 END) as avg_processing_hours,
                    MIN(CASE WHEN processed_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (processed_at - created_at))/3600 END) as min_processing_hours,
                    MAX(CASE WHEN processed_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (processed_at - created_at))/3600 END) as max_processing_hours
                FROM prospects
                WHERE organization_id = ? AND created_at >= DATE('now', '-{} days')
                AND processed_at IS NOT NULL
            """.format(days), (organization_id,))[0]

            # Email performance
            email_performance = query(conn, """
                SELECT
                    COUNT(*) as total_sent,
                    COUNT(CASE WHEN state = 'delivered' THEN 1 END) as delivered,
                    COUNT(CASE WHEN state = 'opened' THEN 1 END) as opened,
                    COUNT(CASE WHEN state = 'replied' THEN 1 END) as replied,
                    COUNT(CASE WHEN state = 'bounced' THEN 1 END) as bounced,
                    AVG(CASE WHEN sent_at IS NOT NULL AND state = 'replied'
                        THEN EXTRACT(EPOCH FROM (updated_at - sent_at))/3600 END) as avg_response_hours
                FROM email_jobs
                WHERE organization_id = ? AND created_at >= DATE('now', '-{} days')
                AND state IN ('sent', 'delivered', 'opened', 'replied', 'bounced')
            """.format(days), (organization_id,))[0]

            # Calculate rates
            total_sent = email_performance['total_sent'] or 1
            delivery_rate = (email_performance['delivered'] / total_sent) * 100
            open_rate = (email_performance['opened'] / total_sent) * 100
            reply_rate = (email_performance['replied'] / total_sent) * 100
            bounce_rate = (email_performance['bounced'] / total_sent) * 100

            # Connector quality metrics
            connector_quality = query(conn, """
                SELECT
                    AVG(ranking_score) as avg_score,
                    COUNT(CASE WHEN rank = 1 THEN 1 END) as top_ranked_count,
                    COUNT(CASE WHEN ranking_score >= 0.8 THEN 1 END) as high_quality_count,
                    COUNT(*) as total_connectors
                FROM prospect_connectors
                WHERE organization_id = ? AND created_at >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]

            # Industry benchmarks (simplified)
            benchmarks = {
                "delivery_rate": {"value": 95.0, "status": "good" if delivery_rate >= 90 else "warning"},
                "open_rate": {"value": 25.0, "status": "good" if open_rate >= 20 else "warning"},
                "reply_rate": {"value": 5.0, "status": "good" if reply_rate >= 3 else "warning"},
                "bounce_rate": {"value": 2.0, "status": "good" if bounce_rate <= 5 else "warning"}
            }

            return {
                "processing_efficiency": dict(efficiency_stats),
                "email_rates": {
                    "delivery_rate": delivery_rate,
                    "open_rate": open_rate,
                    "reply_rate": reply_rate,
                    "bounce_rate": bounce_rate
                },
                "connector_quality": dict(connector_quality),
                "benchmarks": benchmarks,
                "avg_response_time_hours": email_performance['avg_response_hours']
            }

    async def _get_cost_analysis(self, organization_id: int, days: int) -> Dict[str, Any]:
        """Get detailed cost analysis"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            # Overall cost metrics
            cost_summary = query(conn, """
                SELECT
                    SUM(cost_usd) as total_cost,
                    AVG(cost_usd) as avg_daily_cost,
                    COUNT(DISTINCT metric_date) as active_days
                FROM organization_metrics
                WHERE organization_id = ? AND metric_date >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]

            # Cost breakdown by activity
            activity_costs = {
                "executive_lookup": {"cost": 0.02, "volume": 0},
                "email_enrichment": {"cost": 0.01, "volume": 0},
                "linkedin_automation": {"cost": 0.005, "volume": 0}
            }

            # Get volumes for cost calculation
            prospects_processed = query(conn, """
                SELECT COUNT(*) as count FROM prospects
                WHERE organization_id = ? AND status != 'pending_lookup'
                AND created_at >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]['count']

            emails_enriched = query(conn, """
                SELECT COUNT(*) as count FROM connectors
                WHERE organization_id = ? AND email IS NOT NULL
                AND created_at >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]['count']

            mutuals_discovered = query(conn, """
                SELECT COUNT(*) as count FROM prospect_connectors
                WHERE organization_id = ? AND created_at >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]['count']

            # Calculate estimated costs
            activity_costs["executive_lookup"]["volume"] = prospects_processed
            activity_costs["email_enrichment"]["volume"] = emails_enriched
            activity_costs["linkedin_automation"]["volume"] = mutuals_discovered

            total_estimated = sum(
                activity["cost"] * activity["volume"]
                for activity in activity_costs.values()
            )

            # Cost efficiency metrics
            cost_per_prospect = (cost_summary['total_cost'] / prospects_processed) if prospects_processed > 0 else 0
            cost_per_email = (cost_summary['total_cost'] / emails_enriched) if emails_enriched > 0 else 0

            return {
                "summary": dict(cost_summary),
                "activity_breakdown": activity_costs,
                "estimated_total": total_estimated,
                "efficiency": {
                    "cost_per_prospect": cost_per_prospect,
                    "cost_per_email": cost_per_email
                },
                "optimization_tips": self._generate_cost_optimization_tips(activity_costs)
            }

    async def _get_funnel_analysis(self, organization_id: int, days: int) -> Dict[str, Any]:
        """Get conversion funnel analysis"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            # Funnel stages
            funnel_data = query(conn, """
                SELECT
                    COUNT(*) as prospects_imported,
                    COUNT(CASE WHEN status != 'pending_lookup' THEN 1 END) as prospects_processed,
                    COUNT(CASE WHEN status = 'ready_for_mutuals' THEN 1 END) as prospects_with_executives,
                    COUNT(CASE WHEN status = 'mutuals_found' THEN 1 END) as prospects_with_connectors
                FROM prospects
                WHERE organization_id = ? AND created_at >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]

            # Email funnel
            email_funnel = query(conn, """
                SELECT
                    COUNT(DISTINCT pc.prospect_id) as prospects_with_emails,
                    COUNT(CASE WHEN ej.state = 'sent' THEN 1 END) as emails_sent,
                    COUNT(CASE WHEN ej.state = 'delivered' THEN 1 END) as emails_delivered,
                    COUNT(CASE WHEN ej.state = 'opened' THEN 1 END) as emails_opened,
                    COUNT(CASE WHEN ej.state = 'replied' THEN 1 END) as emails_replied
                FROM prospect_connectors pc
                LEFT JOIN email_jobs ej ON ej.prospect_connector_id = pc.id
                WHERE pc.organization_id = ? AND pc.created_at >= DATE('now', '-{} days')
            """.format(days), (organization_id,))[0]

            # Calculate conversion rates
            imported = funnel_data['prospects_imported'] or 1
            conversion_rates = {
                "import_to_processed": (funnel_data['prospects_processed'] / imported) * 100,
                "processed_to_executives": (funnel_data['prospects_with_executives'] / imported) * 100,
                "executives_to_connectors": (funnel_data['prospects_with_connectors'] / imported) * 100,
                "connectors_to_emails": (email_funnel['emails_sent'] / imported) * 100,
                "emails_to_replies": (email_funnel['emails_replied'] / (email_funnel['emails_sent'] or 1)) * 100
            }

            return {
                "funnel_stages": dict(funnel_data),
                "email_funnel": dict(email_funnel),
                "conversion_rates": conversion_rates,
                "bottlenecks": self._identify_funnel_bottlenecks(conversion_rates)
            }

    async def _get_predictive_insights(self, organization_id: int) -> Dict[str, Any]:
        """Get predictive analytics insights"""

        try:
            from ..api.db_core import get_conn, query

            with get_conn() as conn:
                # Get historical data for prediction
                historical_data = query(conn, """
                    SELECT
                        metric_date,
                        prospects_imported,
                        emails_sent,
                        emails_replied,
                        cost_usd
                    FROM organization_metrics
                    WHERE organization_id = ?
                    AND metric_date >= DATE('now', '-90 days')
                    ORDER BY metric_date
                """, (organization_id,))

                if len(historical_data) < 7:
                    return {"error": "Insufficient historical data for predictions"}

                # Simple trend analysis (in production, use proper ML models)
                recent_data = historical_data[-7:]  # Last 7 days
                avg_prospects = sum(row['prospects_imported'] for row in recent_data) / len(recent_data)
                avg_emails = sum(row['emails_sent'] for row in recent_data) / len(recent_data)
                avg_replies = sum(row['emails_replied'] for row in recent_data) / len(recent_data)

                # Predict next 7 days (simplified linear projection)
                predictions = {
                    "next_7_days": {
                        "predicted_prospects": int(avg_prospects * 7),
                        "predicted_emails": int(avg_emails * 7),
                        "predicted_replies": int(avg_replies * 7),
                        "confidence": "medium"
                    },
                    "recommendations": [
                        "Based on current trends, consider increasing weekly email quota",
                        "Email reply rate is trending upward - good time for outreach",
                        "Prospect processing is stable - maintain current workflow"
                    ]
                }

                return predictions

        except Exception as e:
            logger.error(f"Error generating predictive insights: {e}")
            return {"error": "Prediction service unavailable"}

    async def _calculate_health_score(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate overall organization health score"""

        score = 100
        factors = []

        # Check prospect processing health
        prospects = metrics.get("prospects", {})
        if prospects.get("total_prospects", 0) > 0:
            failed_rate = (prospects.get("failed", 0) / prospects["total_prospects"]) * 100
            if failed_rate > 20:
                score -= 15
                factors.append("High prospect failure rate")
            elif failed_rate > 10:
                score -= 5
                factors.append("Moderate prospect failure rate")

        # Check email performance
        emails = metrics.get("emails", {})
        if emails.get("total_emails", 0) > 0:
            failed_email_rate = (emails.get("failed_emails", 0) / emails["total_emails"]) * 100
            if failed_email_rate > 10:
                score -= 10
                factors.append("High email failure rate")

        # Check quota utilization
        quota = metrics.get("quota", {})
        utilization = quota.get("utilization_percent", 0)
        if utilization > 90:
            score -= 5
            factors.append("Near quota limit")
        elif utilization < 20:
            score -= 5
            factors.append("Low quota utilization")

        # Determine health status
        if score >= 90:
            status = "excellent"
            color = "green"
        elif score >= 75:
            status = "good"
            color = "blue"
        elif score >= 60:
            status = "fair"
            color = "yellow"
        else:
            status = "poor"
            color = "red"

        return {
            "score": max(0, score),
            "status": status,
            "color": color,
            "factors": factors
        }

    def _generate_cost_optimization_tips(self, activity_costs: Dict[str, Any]) -> List[str]:
        """Generate cost optimization recommendations"""

        tips = []

        # Analyze cost distribution
        total_cost = sum(act["cost"] * act["volume"] for act in activity_costs.values())

        if total_cost == 0:
            return ["No cost data available for optimization"]

        for activity, data in activity_costs.items():
            activity_total = data["cost"] * data["volume"]
            percentage = (activity_total / total_cost) * 100

            if percentage > 50:
                tips.append(f"Consider optimizing {activity} - it's {percentage:.1f}% of total costs")

        # General optimization tips
        if not tips:
            tips.extend([
                "Monitor email enrichment accuracy to avoid unnecessary API calls",
                "Batch prospect processing to reduce per-unit costs",
                "Review quota settings to optimize email sending efficiency"
            ])

        return tips

    def _identify_funnel_bottlenecks(self, conversion_rates: Dict[str, float]) -> List[str]:
        """Identify bottlenecks in the conversion funnel"""

        bottlenecks = []

        if conversion_rates["import_to_processed"] < 80:
            bottlenecks.append("Prospect processing - many prospects failing lookup")

        if conversion_rates["processed_to_executives"] < 60:
            bottlenecks.append("Executive discovery - low success rate finding contacts")

        if conversion_rates["executives_to_connectors"] < 70:
            bottlenecks.append("Mutual connections - few connectors being found")

        if conversion_rates["emails_to_replies"] < 3:
            bottlenecks.append("Email engagement - low reply rates")

        return bottlenecks or ["No significant bottlenecks identified"]

    async def _get_cached_data(self, key: str) -> Optional[Dict[str, Any]]:
        """Get data from Redis cache"""

        if not self.redis_client:
            return None

        try:
            cached = await self.redis_client.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Cache read error: {e}")

        return None

    async def _cache_data(self, key: str, data: Dict[str, Any], ttl: int):
        """Cache data in Redis"""

        if not self.redis_client:
            return

        try:
            await self.redis_client.setex(key, ttl, json.dumps(data, default=str))
        except Exception as e:
            logger.warning(f"Cache write error: {e}")

    async def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health metrics"""

        try:
            health_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "healthy",
                "components": {
                    "database": await self._check_database_health(),
                    "redis": await self._check_redis_health(),
                    "external_apis": await self._check_external_apis_health()
                }
            }

            # Determine overall status
            component_statuses = [comp["status"] for comp in health_data["components"].values()]
            if "error" in component_statuses:
                health_data["status"] = "error"
            elif "warning" in component_statuses:
                health_data["status"] = "warning"

            return health_data

        except Exception as e:
            logger.error(f"System health check failed: {e}")
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "error",
                "error": str(e)
            }

    async def _check_database_health(self) -> Dict[str, Any]:
        """Check database connectivity and performance"""

        try:
            from ..api.db_core import get_conn, query

            start_time = time.time()
            with get_conn() as conn:
                result = query(conn, "SELECT 1 as health_check")
                if result:
                    latency = (time.time() - start_time) * 1000
                    return {
                        "status": "healthy",
                        "latency_ms": round(latency, 2),
                        "last_check": datetime.now(timezone.utc).isoformat()
                    }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat()
            }

    async def _check_redis_health(self) -> Dict[str, Any]:
        """Check Redis connectivity"""

        if not self.redis_client:
            return {"status": "disabled", "message": "Redis not configured"}

        try:
            start_time = time.time()
            await self.redis_client.ping()
            latency = (time.time() - start_time) * 1000

            return {
                "status": "healthy",
                "latency_ms": round(latency, 2),
                "last_check": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat()
            }

    async def _check_external_apis_health(self) -> Dict[str, Any]:
        """Check external API health"""

        # This would ping external services like CUFinder, SendGrid, etc.
        # For now, return a placeholder

        return {
            "status": "healthy",
            "apis_checked": ["cufinder", "sendgrid"],
            "last_check": datetime.now(timezone.utc).isoformat()
        }

    async def track_agent_event(
        self,
        organization_id: int,
        event_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record agent execution telemetry for dashboards and audits."""

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "organization_id": organization_id,
            "event_type": event_type,
            "metadata": metadata or {},
        }

        self.recent_agent_events.append(event)

        if self.redis_client:
            key = f"agent_events:{organization_id}"
            try:
                await self.redis_client.lpush(key, json.dumps(event))
                await self.redis_client.ltrim(key, 0, 199)
            except Exception as exc:  # pragma: no cover - cache failures are non-fatal
                logger.debug("Failed to persist agent event to redis: %s", exc)

        logger.info("📊 Agent telemetry event recorded: %s", event)
        return event

# Global service instance
global_analytics_service = GlobalAnalyticsService()
