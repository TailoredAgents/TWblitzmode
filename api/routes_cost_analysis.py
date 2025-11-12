"""
Cost Analysis Admin Panel Routes
Provides comprehensive cost monitoring and analysis for SendGrid usage
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.deps import get_current_user
from services.cost_monitoring_service import cost_monitoring_service, TenantCostSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/cost-analysis", tags=["Cost Analysis"])

# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class CostOverviewResponse(BaseModel):
    """Response for cost overview endpoint"""
    period: Dict[str, Any]  # Changed from Dict[str, str] to allow mixed types
    total_cost: float
    total_emails: int
    total_tenants: int
    avg_cost_per_email: float
    avg_cost_per_tenant: float
    cost_trend: str  # "increasing", "decreasing", "stable"

class TenantCostResponse(BaseModel):
    """Response for individual tenant cost data"""
    tenant_id: int
    tenant_name: str
    period_start: str
    period_end: str
    total_emails_sent: int
    successful_emails: int
    failed_emails: int
    total_cost: float
    cost_per_successful_email: float
    success_rate: float
    recommended_plan: str
    potential_savings: float

class CostTrendResponse(BaseModel):
    """Response for cost trend analysis"""
    period: Dict[str, Any]
    summary: Dict[str, float]
    trend_data: List[Dict[str, Any]]

class CostAlertResponse(BaseModel):
    """Response for cost alerts and thresholds"""
    tenant_id: int
    alert_type: str  # "high_cost", "high_usage", "low_efficiency"
    message: str
    current_value: float
    threshold: float
    severity: str  # "warning", "critical"

# ============================================
# COST OVERVIEW ENDPOINTS
# ============================================

@router.get("/overview", response_model=CostOverviewResponse)
async def get_cost_overview(
    days: int = Query(30, description="Number of days to analyze"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get comprehensive cost overview for all tenants
    
    Provides high-level cost metrics for administrative oversight
    """
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # Get all tenant summaries
        tenant_summaries = await cost_monitoring_service.get_all_tenants_cost_overview(start_date, end_date)
        
        if not tenant_summaries:
            return CostOverviewResponse(
                period={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "days": days
                },
                total_cost=0.0,
                total_emails=0,
                total_tenants=0,
                avg_cost_per_email=0.0,
                avg_cost_per_tenant=0.0,
                cost_trend="stable"
            )
        
        # Calculate aggregated metrics
        total_cost = sum(float(s.total_cost) for s in tenant_summaries)
        total_emails = sum(s.total_emails_sent for s in tenant_summaries)
        total_tenants = len(tenant_summaries)
        avg_cost_per_email = total_cost / total_emails if total_emails > 0 else 0.0
        avg_cost_per_tenant = total_cost / total_tenants if total_tenants > 0 else 0.0
        
        # Get trend analysis
        trend_data = await cost_monitoring_service.get_cost_trends(days=days)
        cost_trend = _analyze_cost_trend(trend_data["trend_data"])
        
        return CostOverviewResponse(
            period={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days
            },
            total_cost=total_cost,
            total_emails=total_emails,
            total_tenants=total_tenants,
            avg_cost_per_email=avg_cost_per_email,
            avg_cost_per_tenant=avg_cost_per_tenant,
            cost_trend=cost_trend
        )
        
    except Exception as e:
        logger.error(f"Failed to get cost overview: {e}")
        raise HTTPException(500, f"Failed to get cost overview: {str(e)}")

@router.get("/tenants", response_model=List[TenantCostResponse])
async def get_all_tenants_costs(
    days: int = Query(30, description="Number of days to analyze"),
    sort_by: str = Query("total_cost", description="Sort by: total_cost, total_emails, success_rate"),
    order: str = Query("desc", description="Sort order: asc, desc"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get cost analysis for all tenants
    
    Provides detailed cost breakdown per tenant for administrative oversight
    """
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        tenant_summaries = await cost_monitoring_service.get_all_tenants_cost_overview(start_date, end_date)
        
        # Convert to response format
        tenant_responses = []
        for summary in tenant_summaries:
            tenant_responses.append(TenantCostResponse(
                tenant_id=summary.tenant_id,
                tenant_name=summary.tenant_name,
                period_start=summary.period_start.isoformat(),
                period_end=summary.period_end.isoformat(),
                total_emails_sent=summary.total_emails_sent,
                successful_emails=summary.successful_emails,
                failed_emails=summary.failed_emails,
                total_cost=float(summary.total_cost),
                cost_per_successful_email=float(summary.cost_per_successful_email),
                success_rate=summary.success_rate,
                recommended_plan=summary.recommended_plan,
                potential_savings=float(summary.potential_savings)
            ))
        
        # Sort results
        reverse_order = order.lower() == "desc"
        if sort_by == "total_cost":
            tenant_responses.sort(key=lambda x: x.total_cost, reverse=reverse_order)
        elif sort_by == "total_emails":
            tenant_responses.sort(key=lambda x: x.total_emails_sent, reverse=reverse_order)
        elif sort_by == "success_rate":
            tenant_responses.sort(key=lambda x: x.success_rate, reverse=reverse_order)
        elif sort_by == "cost_per_email":
            tenant_responses.sort(key=lambda x: x.cost_per_successful_email, reverse=reverse_order)
        
        return tenant_responses
        
    except Exception as e:
        logger.error(f"Failed to get tenant costs: {e}")
        raise HTTPException(500, f"Failed to get tenant costs: {str(e)}")

@router.get("/tenant/{tenant_id}", response_model=TenantCostResponse)
async def get_tenant_cost_details(
    tenant_id: int,
    days: int = Query(30, description="Number of days to analyze"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get detailed cost analysis for specific tenant
    """
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        summary = await cost_monitoring_service.get_tenant_cost_summary(tenant_id, start_date, end_date)
        
        return TenantCostResponse(
            tenant_id=summary.tenant_id,
            tenant_name=summary.tenant_name,
            period_start=summary.period_start.isoformat(),
            period_end=summary.period_end.isoformat(),
            total_emails_sent=summary.total_emails_sent,
            successful_emails=summary.successful_emails,
            failed_emails=summary.failed_emails,
            total_cost=float(summary.total_cost),
            cost_per_successful_email=float(summary.cost_per_successful_email),
            success_rate=summary.success_rate,
            recommended_plan=summary.recommended_plan,
            potential_savings=float(summary.potential_savings)
        )
        
    except Exception as e:
        logger.error(f"Failed to get tenant {tenant_id} cost details: {e}")
        raise HTTPException(500, f"Failed to get tenant cost details: {str(e)}")

# ============================================
# COST TRENDS AND ANALYTICS
# ============================================

@router.get("/trends", response_model=CostTrendResponse)
async def get_cost_trends(
    tenant_id: Optional[int] = Query(None, description="Specific tenant ID (optional)"),
    days: int = Query(30, description="Number of days to analyze"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get cost trends over time for visualization
    """
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    
    try:
        trend_data = await cost_monitoring_service.get_cost_trends(tenant_id, days)
        
        return CostTrendResponse(
            period=trend_data["period"],
            summary=trend_data["summary"],
            trend_data=trend_data["trend_data"]
        )
        
    except Exception as e:
        logger.error(f"Failed to get cost trends: {e}")
        raise HTTPException(500, f"Failed to get cost trends: {str(e)}")

@router.get("/alerts", response_model=List[CostAlertResponse])
async def get_cost_alerts(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get cost alerts and threshold violations
    """
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    
    try:
        # Get recent tenant summaries for alert analysis
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)  # Check last week
        
        tenant_summaries = await cost_monitoring_service.get_all_tenants_cost_overview(start_date, end_date)
        
        alerts = []
        
        # Define alert thresholds
        HIGH_COST_THRESHOLD = 100.0  # $100/week
        LOW_SUCCESS_RATE_THRESHOLD = 80.0  # 80%
        HIGH_COST_PER_EMAIL_THRESHOLD = 0.01  # $0.01 per email
        
        for summary in tenant_summaries:
            weekly_cost = float(summary.total_cost)
            success_rate = summary.success_rate
            cost_per_email = float(summary.cost_per_successful_email)
            
            # High cost alert
            if weekly_cost > HIGH_COST_THRESHOLD:
                alerts.append(CostAlertResponse(
                    tenant_id=summary.tenant_id,
                    alert_type="high_cost",
                    message=f"Tenant {summary.tenant_name} has high weekly costs: ${weekly_cost:.2f}",
                    current_value=weekly_cost,
                    threshold=HIGH_COST_THRESHOLD,
                    severity="warning" if weekly_cost < HIGH_COST_THRESHOLD * 1.5 else "critical"
                ))
            
            # Low success rate alert
            if success_rate < LOW_SUCCESS_RATE_THRESHOLD:
                alerts.append(CostAlertResponse(
                    tenant_id=summary.tenant_id,
                    alert_type="low_efficiency",
                    message=f"Tenant {summary.tenant_name} has low success rate: {success_rate:.1f}%",
                    current_value=success_rate,
                    threshold=LOW_SUCCESS_RATE_THRESHOLD,
                    severity="warning" if success_rate > 60 else "critical"
                ))
            
            # High cost per email alert
            if cost_per_email > HIGH_COST_PER_EMAIL_THRESHOLD:
                alerts.append(CostAlertResponse(
                    tenant_id=summary.tenant_id,
                    alert_type="high_cost_per_email",
                    message=f"Tenant {summary.tenant_name} has high cost per email: ${cost_per_email:.4f}",
                    current_value=cost_per_email,
                    threshold=HIGH_COST_PER_EMAIL_THRESHOLD,
                    severity="warning"
                ))
        
        # Sort by severity
        alerts.sort(key=lambda x: 0 if x.severity == "critical" else 1)
        
        return alerts
        
    except Exception as e:
        logger.error(f"Failed to get cost alerts: {e}")
        raise HTTPException(500, f"Failed to get cost alerts: {str(e)}")

# ============================================
# COST OPTIMIZATION RECOMMENDATIONS
# ============================================

@router.get("/optimization-recommendations")
async def get_optimization_recommendations(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get cost optimization recommendations for all tenants
    """
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        tenant_summaries = await cost_monitoring_service.get_all_tenants_cost_overview(start_date, end_date)
        
        recommendations = []
        total_potential_savings = 0.0
        
        for summary in tenant_summaries:
            if float(summary.potential_savings) > 0:
                recommendations.append({
                    "tenant_id": summary.tenant_id,
                    "tenant_name": summary.tenant_name,
                    "current_cost": float(summary.total_cost),
                    "recommended_plan": summary.recommended_plan,
                    "potential_savings": float(summary.potential_savings),
                    "recommendation": f"Switch to {summary.recommended_plan} plan to save ${summary.potential_savings:.2f}/month"
                })
                total_potential_savings += float(summary.potential_savings)
        
        # Sort by potential savings
        recommendations.sort(key=lambda x: x["potential_savings"], reverse=True)
        
        return {
            "total_potential_savings": total_potential_savings,
            "recommendations_count": len(recommendations),
            "recommendations": recommendations,
            "summary": {
                "high_impact": len([r for r in recommendations if r["potential_savings"] > 50]),
                "medium_impact": len([r for r in recommendations if 10 < r["potential_savings"] <= 50]),
                "low_impact": len([r for r in recommendations if r["potential_savings"] <= 10])
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get optimization recommendations: {e}")
        raise HTTPException(500, f"Failed to get optimization recommendations: {str(e)}")

# ============================================
# HELPER FUNCTIONS
# ============================================

def _analyze_cost_trend(trend_data: List[Dict[str, Any]]) -> str:
    """
    Analyze cost trend direction
    
    Args:
        trend_data: List of daily cost data
        
    Returns:
        Trend direction: "increasing", "decreasing", "stable"
    """
    if len(trend_data) < 7:
        return "stable"
    
    # Compare first and last week averages
    first_week = trend_data[:7]
    last_week = trend_data[-7:]
    
    first_week_avg = sum(d["cost"] for d in first_week) / len(first_week)
    last_week_avg = sum(d["cost"] for d in last_week) / len(last_week)
    
    if first_week_avg == 0:
        return "stable"
    
    change_percentage = ((last_week_avg - first_week_avg) / first_week_avg) * 100
    
    if change_percentage > 10:
        return "increasing"
    elif change_percentage < -10:
        return "decreasing"
    else:
        return "stable"