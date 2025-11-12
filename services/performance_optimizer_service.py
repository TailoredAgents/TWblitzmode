"""
Performance Optimizer Service - Campaign Analytics and Optimization
Provides comprehensive performance analysis and optimization for VouchLink campaigns

Features:
- Campaign performance metrics and success rates
- A/B testing insights and optimization recommendations
- Agent performance evaluation and improvement suggestions
- Resource allocation and efficiency optimization
- Predictive modeling for future campaign success
- Real-time performance monitoring and alerting
- Historical trend analysis and benchmarking
"""

import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from api.database import get_db
import json

logger = logging.getLogger(__name__)

class PerformanceMetric(Enum):
    """Performance metrics tracked by the optimizer"""
    RESPONSE_RATE = "response_rate"
    CONNECTION_RATE = "connection_rate"
    MEETING_RATE = "meeting_rate"
    CONVERSION_RATE = "conversion_rate"
    EMAIL_OPEN_RATE = "email_open_rate"
    EMAIL_CLICK_RATE = "email_click_rate"
    LINKEDIN_ACCEPTANCE_RATE = "linkedin_acceptance_rate"
    WORKFLOW_COMPLETION_TIME = "workflow_completion_time"
    COST_PER_LEAD = "cost_per_lead"
    AGENT_EFFICIENCY = "agent_efficiency"

class OptimizationLevel(Enum):
    """Levels of optimization recommendations"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"

@dataclass
class PerformanceInsight:
    """Individual performance insight or recommendation"""
    metric: PerformanceMetric
    level: OptimizationLevel
    current_value: float
    benchmark_value: float
    improvement_potential: float
    recommendation: str
    implementation_effort: str
    expected_impact: str

@dataclass
class CampaignPerformance:
    """Performance data for a specific campaign"""
    campaign_id: str
    campaign_name: str
    start_date: datetime
    end_date: Optional[datetime]
    total_prospects: int
    total_outreach: int
    responses_received: int
    meetings_scheduled: int
    conversions: int
    total_cost: float
    performance_score: float
    key_metrics: Dict[PerformanceMetric, float]

@dataclass
class OptimizationReport:
    """Comprehensive optimization report"""
    organization_id: int
    report_date: datetime
    overall_performance_score: float
    key_insights: List[PerformanceInsight]
    campaign_rankings: List[CampaignPerformance]
    agent_performance: Dict[str, float]
    optimization_recommendations: List[str]
    predicted_improvements: Dict[str, float]
    benchmark_comparison: Dict[str, float]

class PerformanceOptimizerService:
    """
    Performance Optimizer Service for VouchLink campaigns

    Analyzes campaign performance, identifies optimization opportunities,
    and provides data-driven recommendations for improving outcomes.
    """

    def __init__(self):
        # Industry benchmarks (would be updated from real data)
        self.industry_benchmarks = {
            PerformanceMetric.RESPONSE_RATE: 0.15,  # 15% response rate
            PerformanceMetric.CONNECTION_RATE: 0.25,  # 25% LinkedIn connection rate
            PerformanceMetric.MEETING_RATE: 0.08,  # 8% meeting booking rate
            PerformanceMetric.CONVERSION_RATE: 0.05,  # 5% conversion rate
            PerformanceMetric.EMAIL_OPEN_RATE: 0.35,  # 35% email open rate
            PerformanceMetric.EMAIL_CLICK_RATE: 0.08,  # 8% email click rate
            PerformanceMetric.LINKEDIN_ACCEPTANCE_RATE: 0.30,  # 30% LinkedIn acceptance
            PerformanceMetric.WORKFLOW_COMPLETION_TIME: 2.5,  # 2.5 days average
            PerformanceMetric.COST_PER_LEAD: 150.0,  # $150 cost per lead
            PerformanceMetric.AGENT_EFFICIENCY: 0.75  # 75% efficiency score
        }

        # Optimization thresholds
        self.optimization_thresholds = {
            OptimizationLevel.CRITICAL: 0.5,  # 50% below benchmark
            OptimizationLevel.HIGH: 0.7,  # 30% below benchmark
            OptimizationLevel.MEDIUM: 0.85,  # 15% below benchmark
            OptimizationLevel.LOW: 0.95   # 5% below benchmark
        }

        logger.info("PerformanceOptimizerService initialized with industry benchmarks")

    async def analyze_campaign_performance(
        self,
        campaign_id: str,
        organization_id: int,
        time_period_days: int = 30
    ) -> CampaignPerformance:
        """
        Analyze performance of a specific campaign

        Args:
            campaign_id: Campaign identifier
            organization_id: Organization identifier for tenant isolation
            time_period_days: Analysis period in days

        Returns:
            CampaignPerformance with detailed metrics
        """
        logger.info(f"Analyzing campaign performance: {campaign_id} (org: {organization_id})")

        try:
            # Get campaign data from database
            campaign_data = await self._get_campaign_data(campaign_id, organization_id, time_period_days)

            if not campaign_data:
                raise ValueError(f"Campaign {campaign_id} not found or no data available")

            # Calculate performance metrics
            key_metrics = await self._calculate_campaign_metrics(campaign_data)

            # Calculate overall performance score
            performance_score = self._calculate_performance_score(key_metrics)

            return CampaignPerformance(
                campaign_id=campaign_id,
                campaign_name=campaign_data.get("name", f"Campaign {campaign_id}"),
                start_date=campaign_data["start_date"],
                end_date=campaign_data.get("end_date"),
                total_prospects=campaign_data.get("total_prospects", 0),
                total_outreach=campaign_data.get("total_outreach", 0),
                responses_received=campaign_data.get("responses_received", 0),
                meetings_scheduled=campaign_data.get("meetings_scheduled", 0),
                conversions=campaign_data.get("conversions", 0),
                total_cost=campaign_data.get("total_cost", 0.0),
                performance_score=performance_score,
                key_metrics=key_metrics
            )

        except Exception as e:
            logger.error(f"Campaign performance analysis failed: {e}")
            raise

    async def generate_optimization_report(
        self,
        organization_id: int,
        time_period_days: int = 90
    ) -> OptimizationReport:
        """
        Generate comprehensive optimization report for organization

        Args:
            organization_id: Organization identifier
            time_period_days: Analysis period in days

        Returns:
            OptimizationReport with insights and recommendations
        """
        logger.info(f"Generating optimization report for org {organization_id}")

        try:
            # Get all campaigns for organization
            campaigns = await self._get_organization_campaigns(organization_id, time_period_days)

            # Analyze each campaign
            campaign_performances = []
            for campaign in campaigns:
                try:
                    performance = await self.analyze_campaign_performance(
                        campaign["id"], organization_id, time_period_days
                    )
                    campaign_performances.append(performance)
                except Exception as e:
                    logger.warning(f"Failed to analyze campaign {campaign['id']}: {e}")

            # Calculate overall metrics
            overall_score = self._calculate_overall_performance_score(campaign_performances)

            # Generate insights
            insights = await self._generate_performance_insights(campaign_performances, organization_id)

            # Analyze agent performance
            agent_performance = await self._analyze_agent_performance(organization_id, time_period_days)

            # Generate optimization recommendations
            recommendations = self._generate_optimization_recommendations(insights, campaign_performances)

            # Predict improvements
            predicted_improvements = self._predict_improvements(insights, campaign_performances)

            # Benchmark comparison
            benchmark_comparison = self._compare_to_benchmarks(campaign_performances)

            # Rank campaigns by performance
            campaign_rankings = sorted(
                campaign_performances,
                key=lambda x: x.performance_score,
                reverse=True
            )

            return OptimizationReport(
                organization_id=organization_id,
                report_date=datetime.now(timezone.utc),
                overall_performance_score=overall_score,
                key_insights=insights,
                campaign_rankings=campaign_rankings,
                agent_performance=agent_performance,
                optimization_recommendations=recommendations,
                predicted_improvements=predicted_improvements,
                benchmark_comparison=benchmark_comparison
            )

        except Exception as e:
            logger.error(f"Optimization report generation failed: {e}")
            raise

    async def _get_campaign_data(self, campaign_id: str, organization_id: int, days: int) -> Dict[str, Any]:
        """Retrieve campaign data from database"""
        try:

            conn = get_db()
            cursor = conn.cursor()

            # Get campaign basic info
            cursor.execute("""
                SELECT name, start_date, end_date, target_count, total_cost
                FROM campaigns
                WHERE id = ? AND tenant_id = ?
                AND start_date >= datetime('now', '-{} days')
            """.format(days), (campaign_id, organization_id))

            campaign_row = cursor.fetchone()
            if not campaign_row:
                return None

            # Get campaign metrics
            cursor.execute("""
                SELECT
                    COUNT(*) as total_outreach,
                    SUM(CASE WHEN response_received = 1 THEN 1 ELSE 0 END) as responses,
                    SUM(CASE WHEN meeting_scheduled = 1 THEN 1 ELSE 0 END) as meetings,
                    SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as conversions,
                    AVG(CASE WHEN email_opened = 1 THEN 1.0 ELSE 0.0 END) as open_rate,
                    AVG(CASE WHEN email_clicked = 1 THEN 1.0 ELSE 0.0 END) as click_rate,
                    AVG(CASE WHEN linkedin_connected = 1 THEN 1.0 ELSE 0.0 END) as connection_rate
                FROM campaign_activities
                WHERE campaign_id = ? AND tenant_id = ?
            """, (campaign_id, organization_id))

            metrics_row = cursor.fetchone()

            return {
                "name": campaign_row[0],
                "start_date": datetime.fromisoformat(campaign_row[1]),
                "end_date": datetime.fromisoformat(campaign_row[2]) if campaign_row[2] else None,
                "total_prospects": campaign_row[3] or 0,
                "total_cost": campaign_row[4] or 0.0,
                "total_outreach": metrics_row[0] or 0,
                "responses_received": metrics_row[1] or 0,
                "meetings_scheduled": metrics_row[2] or 0,
                "conversions": metrics_row[3] or 0,
                "email_open_rate": metrics_row[4] or 0.0,
                "email_click_rate": metrics_row[5] or 0.0,
                "linkedin_connection_rate": metrics_row[6] or 0.0
            }

        except Exception as e:
            logger.error(f"Error retrieving campaign data: {e}")
            return None

    async def _calculate_campaign_metrics(self, campaign_data: Dict[str, Any]) -> Dict[PerformanceMetric, float]:
        """Calculate performance metrics for campaign"""
        metrics = {}

        total_outreach = campaign_data.get("total_outreach", 0)
        total_prospects = campaign_data.get("total_prospects", 0)

        if total_outreach > 0:
            metrics[PerformanceMetric.RESPONSE_RATE] = campaign_data.get("responses_received", 0) / total_outreach
            metrics[PerformanceMetric.MEETING_RATE] = campaign_data.get("meetings_scheduled", 0) / total_outreach
            metrics[PerformanceMetric.CONVERSION_RATE] = campaign_data.get("conversions", 0) / total_outreach

        metrics[PerformanceMetric.EMAIL_OPEN_RATE] = campaign_data.get("email_open_rate", 0.0)
        metrics[PerformanceMetric.EMAIL_CLICK_RATE] = campaign_data.get("email_click_rate", 0.0)
        metrics[PerformanceMetric.LINKEDIN_ACCEPTANCE_RATE] = campaign_data.get("linkedin_connection_rate", 0.0)

        # Calculate cost metrics
        total_cost = campaign_data.get("total_cost", 0.0)
        conversions = campaign_data.get("conversions", 0)
        if conversions > 0:
            metrics[PerformanceMetric.COST_PER_LEAD] = total_cost / conversions

        # Calculate workflow efficiency (placeholder)
        start_date = campaign_data.get("start_date")
        end_date = campaign_data.get("end_date", datetime.now(timezone.utc))
        if start_date and total_prospects > 0:
            days_elapsed = (end_date - start_date).days or 1
            metrics[PerformanceMetric.WORKFLOW_COMPLETION_TIME] = days_elapsed / total_prospects

        return metrics

    def _calculate_performance_score(self, metrics: Dict[PerformanceMetric, float]) -> float:
        """Calculate overall performance score (0-100)"""
        if not metrics:
            return 0.0

        scores = []

        for metric, value in metrics.items():
            benchmark = self.industry_benchmarks.get(metric)
            if benchmark and benchmark > 0:
                # Calculate score relative to benchmark
                if metric == PerformanceMetric.COST_PER_LEAD or metric == PerformanceMetric.WORKFLOW_COMPLETION_TIME:
                    # Lower is better for these metrics
                    score = min(benchmark / value, 2.0) * 50  # Cap at 100
                else:
                    # Higher is better for these metrics
                    score = min(value / benchmark, 2.0) * 50  # Cap at 100

                scores.append(score)

        return statistics.mean(scores) if scores else 0.0

    async def _get_organization_campaigns(self, organization_id: int, days: int) -> List[Dict[str, Any]]:
        """Get all campaigns for organization within time period"""
        try:

            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, name, start_date, end_date
                FROM campaigns
                WHERE tenant_id = ?
                AND start_date >= datetime('now', '-{} days')
                ORDER BY start_date DESC
            """.format(days), (organization_id,))

            campaigns = []
            for row in cursor.fetchall():
                campaigns.append({
                    "id": row[0],
                    "name": row[1],
                    "start_date": row[2],
                    "end_date": row[3]
                })

            return campaigns

        except Exception as e:
            logger.error(f"Error retrieving organization campaigns: {e}")
            return []

    def _calculate_overall_performance_score(self, campaigns: List[CampaignPerformance]) -> float:
        """Calculate overall performance score across all campaigns"""
        if not campaigns:
            return 0.0

        # Weight by campaign size and recency
        weighted_scores = []
        total_weight = 0

        for campaign in campaigns:
            # Weight by number of prospects and recency
            size_weight = min(campaign.total_prospects / 100, 2.0)  # Cap at 2x weight

            # More recent campaigns get higher weight
            days_ago = (datetime.now(timezone.utc) - campaign.start_date).days
            recency_weight = max(1.0 - (days_ago / 180), 0.1)  # Decay over 6 months

            weight = size_weight * recency_weight
            weighted_scores.append(campaign.performance_score * weight)
            total_weight += weight

        return sum(weighted_scores) / total_weight if total_weight > 0 else 0.0

    async def _generate_performance_insights(
        self,
        campaigns: List[CampaignPerformance],
        organization_id: int
    ) -> List[PerformanceInsight]:
        """Generate performance insights and recommendations"""
        insights = []

        if not campaigns:
            return insights

        # Aggregate metrics across campaigns
        aggregated_metrics = {}
        for metric in PerformanceMetric:
            values = []
            for campaign in campaigns:
                if metric in campaign.key_metrics:
                    values.append(campaign.key_metrics[metric])

            if values:
                aggregated_metrics[metric] = statistics.mean(values)

        # Generate insights for each metric
        for metric, current_value in aggregated_metrics.items():
            benchmark = self.industry_benchmarks.get(metric)
            if benchmark:
                # Calculate improvement potential
                if metric in [PerformanceMetric.COST_PER_LEAD, PerformanceMetric.WORKFLOW_COMPLETION_TIME]:
                    # Lower is better
                    ratio = current_value / benchmark
                    improvement_potential = max(0, (ratio - 1) * 100)
                    level = self._determine_optimization_level(1 / ratio)
                else:
                    # Higher is better
                    ratio = current_value / benchmark
                    improvement_potential = max(0, (1 - ratio) * 100)
                    level = self._determine_optimization_level(ratio)

                insight = PerformanceInsight(
                    metric=metric,
                    level=level,
                    current_value=current_value,
                    benchmark_value=benchmark,
                    improvement_potential=improvement_potential,
                    recommendation=self._generate_metric_recommendation(metric, ratio, current_value),
                    implementation_effort=self._estimate_implementation_effort(metric, improvement_potential),
                    expected_impact=self._estimate_expected_impact(metric, improvement_potential)
                )

                insights.append(insight)

        # Sort by optimization level and improvement potential
        insights.sort(key=lambda x: (x.level.value, -x.improvement_potential))

        return insights

    def _determine_optimization_level(self, ratio: float) -> OptimizationLevel:
        """Determine optimization level based on performance ratio"""
        if ratio < self.optimization_thresholds[OptimizationLevel.CRITICAL]:
            return OptimizationLevel.CRITICAL
        elif ratio < self.optimization_thresholds[OptimizationLevel.HIGH]:
            return OptimizationLevel.HIGH
        elif ratio < self.optimization_thresholds[OptimizationLevel.MEDIUM]:
            return OptimizationLevel.MEDIUM
        elif ratio < self.optimization_thresholds[OptimizationLevel.LOW]:
            return OptimizationLevel.LOW
        else:
            return OptimizationLevel.INFORMATIONAL

    def _generate_metric_recommendation(self, metric: PerformanceMetric, ratio: float, current_value: float) -> str:
        """Generate specific recommendation for metric improvement"""
        recommendations = {
            PerformanceMetric.RESPONSE_RATE: {
                "low": "Improve email personalization and subject lines. A/B test different messaging approaches.",
                "medium": "Optimize send timing and follow-up sequences. Enhance prospect research quality.",
                "high": "Fine-tune message templates and improve prospect targeting criteria."
            },
            PerformanceMetric.CONNECTION_RATE: {
                "low": "Review LinkedIn connection request messages. Ensure profiles appear credible and relevant.",
                "medium": "Optimize connection request timing and personalization. Check profile completeness.",
                "high": "Test different connection request templates and improve mutual connection utilization."
            },
            PerformanceMetric.MEETING_RATE: {
                "low": "Improve meeting scheduling process and value proposition clarity in emails.",
                "medium": "Optimize call-to-action placement and calendar integration. Test different meeting formats.",
                "high": "Refine meeting booking flow and provide clearer agenda previews."
            },
            PerformanceMetric.EMAIL_OPEN_RATE: {
                "low": "Overhaul subject line strategy. Check sender reputation and deliverability issues.",
                "medium": "A/B test subject lines and optimize send timing for target audience.",
                "high": "Fine-tune subject line personalization and test emoji usage."
            },
            PerformanceMetric.COST_PER_LEAD: {
                "low": "Review entire workflow efficiency. Consider automation improvements and better targeting.",
                "medium": "Optimize resource allocation and reduce manual processing time.",
                "high": "Fine-tune targeting criteria and improve conversion funnel efficiency."
            }
        }

        # Determine performance level
        if ratio < 0.7:
            level = "low"
        elif ratio < 0.9:
            level = "medium"
        else:
            level = "high"

        return recommendations.get(metric, {}).get(level, "Monitor performance and maintain current practices.")

    def _estimate_implementation_effort(self, metric: PerformanceMetric, improvement_potential: float) -> str:
        """Estimate implementation effort for optimization"""
        if improvement_potential > 40:
            return "High - Significant process changes required"
        elif improvement_potential > 20:
            return "Medium - Template and workflow modifications needed"
        elif improvement_potential > 10:
            return "Low - Minor adjustments and A/B testing"
        else:
            return "Minimal - Fine-tuning existing approaches"

    def _estimate_expected_impact(self, metric: PerformanceMetric, improvement_potential: float) -> str:
        """Estimate expected impact of optimization"""
        if improvement_potential > 40:
            return f"High - Up to {improvement_potential:.0f}% improvement possible"
        elif improvement_potential > 20:
            return f"Medium - {improvement_potential:.0f}% improvement expected"
        elif improvement_potential > 10:
            return f"Low - {improvement_potential:.0f}% improvement likely"
        else:
            return f"Minimal - {improvement_potential:.0f}% optimization opportunity"

    async def _analyze_agent_performance(self, organization_id: int, days: int) -> Dict[str, float]:
        """Analyze individual agent performance"""
        try:

            conn = get_db()
            cursor = conn.cursor()

            # Get agent performance metrics
            cursor.execute("""
                SELECT
                    agent_id,
                    AVG(CASE WHEN completed_successfully = 1 THEN 1.0 ELSE 0.0 END) as success_rate,
                    AVG(completion_time_hours) as avg_completion_time,
                    COUNT(*) as total_tasks
                FROM agent_task_logs
                WHERE tenant_id = ?
                AND created_at >= datetime('now', '-{} days')
                GROUP BY agent_id
                HAVING COUNT(*) >= 5
            """.format(days), (organization_id,))

            agent_performance = {}
            for row in cursor.fetchall():
                agent_id, success_rate, avg_time, task_count = row

                # Calculate efficiency score
                efficiency = (success_rate * 0.7) + (min(1.0, 8.0 / avg_time) * 0.3) if avg_time else success_rate
                agent_performance[agent_id] = efficiency

            return agent_performance

        except Exception as e:
            logger.error(f"Error analyzing agent performance: {e}")
            return {}

    def _generate_optimization_recommendations(
        self,
        insights: List[PerformanceInsight],
        campaigns: List[CampaignPerformance]
    ) -> List[str]:
        """Generate overall optimization recommendations"""
        recommendations = []

        # High-priority recommendations
        critical_insights = [i for i in insights if i.level == OptimizationLevel.CRITICAL]
        if critical_insights:
            recommendations.append(f"Address {len(critical_insights)} critical performance issues immediately")

        high_insights = [i for i in insights if i.level == OptimizationLevel.HIGH]
        if high_insights:
            recommendations.append(f"Focus on {len(high_insights)} high-impact optimization opportunities")

        # Campaign-specific recommendations
        if campaigns:
            low_performers = [c for c in campaigns if c.performance_score < 40]
            if low_performers:
                recommendations.append(f"Review and restructure {len(low_performers)} underperforming campaigns")

            top_performers = [c for c in campaigns if c.performance_score > 80]
            if top_performers:
                recommendations.append(f"Scale successful patterns from {len(top_performers)} high-performing campaigns")

        # General recommendations
        recommendations.extend([
            "Implement systematic A/B testing for email templates and timing",
            "Establish regular performance review cycles (weekly/monthly)",
            "Consider automation opportunities for repetitive tasks",
            "Enhance prospect research and targeting accuracy"
        ])

        return recommendations

    def _predict_improvements(
        self,
        insights: List[PerformanceInsight],
        campaigns: List[CampaignPerformance]
    ) -> Dict[str, float]:
        """Predict potential improvements from optimizations"""
        predictions = {}

        # Calculate potential improvement in key metrics
        for insight in insights:
            if insight.level in [OptimizationLevel.CRITICAL, OptimizationLevel.HIGH]:
                # Conservative improvement estimate (50% of theoretical maximum)
                predicted_improvement = insight.improvement_potential * 0.5
                predictions[f"{insight.metric.value}_improvement"] = predicted_improvement

        # Overall performance improvement
        if campaigns:
            current_avg_score = statistics.mean([c.performance_score for c in campaigns])
            high_impact_improvements = sum(
                i.improvement_potential for i in insights
                if i.level in [OptimizationLevel.CRITICAL, OptimizationLevel.HIGH]
            )

            # Conservative overall improvement estimate
            predicted_overall_improvement = min(high_impact_improvements * 0.3, 25)  # Cap at 25%
            predictions["overall_performance_improvement"] = predicted_overall_improvement

        return predictions

    def _compare_to_benchmarks(self, campaigns: List[CampaignPerformance]) -> Dict[str, float]:
        """Compare organization performance to industry benchmarks"""
        if not campaigns:
            return {}

        comparison = {}

        # Aggregate metrics across campaigns
        for metric in PerformanceMetric:
            values = []
            for campaign in campaigns:
                if metric in campaign.key_metrics:
                    values.append(campaign.key_metrics[metric])

            if values:
                avg_value = statistics.mean(values)
                benchmark = self.industry_benchmarks.get(metric)

                if benchmark:
                    if metric in [PerformanceMetric.COST_PER_LEAD, PerformanceMetric.WORKFLOW_COMPLETION_TIME]:
                        # Lower is better - calculate as benchmark/current
                        ratio = benchmark / avg_value if avg_value > 0 else 0
                    else:
                        # Higher is better - calculate as current/benchmark
                        ratio = avg_value / benchmark

                    comparison[metric.value] = ratio

        return comparison

# Global service instance
performance_optimizer = PerformanceOptimizerService()
