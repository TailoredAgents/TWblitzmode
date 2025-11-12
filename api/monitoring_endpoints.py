"""
Monitoring and Production Readiness API Endpoints
Provides health checks, metrics, and system status endpoints for production monitoring

Endpoints:
- /api/health - Basic health check
- /api/health/detailed - Comprehensive health status
- /api/metrics - System metrics and performance data
- /api/readiness - Production readiness assessment
- /api/alerts - Active alerts and notifications
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Import monitoring services
try:
    from services.link_monitoring_service import link_monitoring_service
    from services.production_readiness_checker import production_readiness_checker
    from services.master_chat_agent import master_chat_agent
except ImportError as e:
    logger.error(f"Failed to import monitoring services: {e}")
    link_monitoring_service = None
    production_readiness_checker = None
    master_chat_agent = None

# Create router
monitoring_router = APIRouter(prefix="/api", tags=["monitoring"])

@monitoring_router.get("/health")
async def basic_health_check():
    """
    Basic health check endpoint for load balancers and monitoring systems

    Returns simple UP/DOWN status with minimal latency
    """
    try:
        # Quick health indicators
        health_status = {
            "status": "UP",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "VouchLink Link Master Agent",
            "version": "1.0.0"
        }

        # Check if critical services are available
        services_available = True

        if master_chat_agent is None:
            services_available = False

        if not services_available:
            health_status["status"] = "DOWN"
            health_status["message"] = "Critical services unavailable"
            return JSONResponse(
                status_code=503,
                content=health_status
            )

        return health_status

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "DOWN",
                "timestamp": datetime.utcnow().isoformat(),
                "error": "Health check failed",
                "message": str(e)
            }
        )

@monitoring_router.get("/health/detailed")
async def detailed_health_check():
    """
    Comprehensive health check with detailed system status

    Returns detailed health information for all system components
    """
    try:
        if link_monitoring_service is None:
            raise HTTPException(
                status_code=503,
                detail="Monitoring service not available"
            )

        # Get comprehensive system status
        system_status = await link_monitoring_service.get_system_status()

        # Determine HTTP status code based on health
        status_code = 200
        overall_status = system_status.get("status", "unknown")

        if overall_status == "critical":
            status_code = 503  # Service Unavailable
        elif overall_status == "warning":
            status_code = 200  # OK but with warnings

        return JSONResponse(
            status_code=status_code,
            content={
                "health_check": "detailed",
                "timestamp": datetime.utcnow().isoformat(),
                **system_status
            }
        )

    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Health check failed: {str(e)}"
        )

@monitoring_router.get("/metrics")
async def get_system_metrics(
    hours: int = Query(1, ge=1, le=168, description="Hours of metrics history to return"),
    format: str = Query("json", regex="^(json|prometheus)$", description="Output format")
):
    """
    Get system metrics and performance data

    Args:
        hours: Number of hours of historical data to return (1-168)
        format: Output format (json or prometheus)

    Returns:
        System metrics in requested format
    """
    try:
        if link_monitoring_service is None:
            raise HTTPException(
                status_code=503,
                detail="Monitoring service not available"
            )

        # Get metrics summary
        metrics_summary = await link_monitoring_service.get_metrics_summary(hours=hours)

        if format == "prometheus":
            # Convert to Prometheus format
            prometheus_output = _convert_to_prometheus_format(metrics_summary)
            return JSONResponse(
                content={"metrics": prometheus_output, "format": "prometheus"},
                media_type="text/plain"
            )

        # Return JSON format
        return {
            "metrics_summary": metrics_summary,
            "timestamp": datetime.utcnow().isoformat(),
            "period_hours": hours,
            "format": "json"
        }

    except Exception as e:
        logger.error(f"Metrics retrieval failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve metrics: {str(e)}"
        )

@monitoring_router.get("/readiness")
async def production_readiness_check(
    category: Optional[str] = Query(None, description="Specific category to check"),
    severity: Optional[str] = Query(None, description="Minimum severity level to include")
):
    """
    Production readiness assessment

    Args:
        category: Specific category to check (optional)
        severity: Minimum severity level to include (optional)

    Returns:
        Comprehensive production readiness assessment
    """
    try:
        if production_readiness_checker is None:
            raise HTTPException(
                status_code=503,
                detail="Production readiness checker not available"
            )

        # Run readiness checks
        readiness_result = await production_readiness_checker.run_all_checks()

        # Filter by category if specified
        if category:
            filtered_checks = [
                check for check in readiness_result["all_checks"]
                if check["category"] == category
            ]
            readiness_result["filtered_checks"] = filtered_checks
            readiness_result["filter_applied"] = {"category": category}

        # Filter by severity if specified
        if severity:
            severity_levels = ["info", "low", "medium", "high", "critical"]
            if severity not in severity_levels:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid severity level. Must be one of: {severity_levels}"
                )

            min_severity_index = severity_levels.index(severity)
            filtered_checks = [
                check for check in readiness_result.get("filtered_checks", readiness_result["all_checks"])
                if severity_levels.index(check["severity"]) >= min_severity_index
            ]
            readiness_result["filtered_checks"] = filtered_checks
            readiness_result["filter_applied"] = readiness_result.get("filter_applied", {})
            readiness_result["filter_applied"]["severity"] = severity

        # Determine HTTP status code
        overall_status = readiness_result["overall_status"]
        if overall_status == "NOT_READY":
            status_code = 503
        elif overall_status == "NEEDS_ATTENTION":
            status_code = 206  # Partial Content
        else:
            status_code = 200

        return JSONResponse(
            status_code=status_code,
            content={
                "readiness_check": True,
                "timestamp": datetime.utcnow().isoformat(),
                **readiness_result
            }
        )

    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Readiness check failed: {str(e)}"
        )

@monitoring_router.get("/alerts")
async def get_active_alerts(
    severity: Optional[str] = Query(None, description="Filter by severity level"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of alerts to return")
):
    """
    Get active alerts and notifications

    Args:
        severity: Filter by severity level (optional)
        limit: Maximum number of alerts to return

    Returns:
        List of active alerts
    """
    try:
        if link_monitoring_service is None:
            raise HTTPException(
                status_code=503,
                detail="Monitoring service not available"
            )

        # Get system status which includes alerts
        system_status = await link_monitoring_service.get_system_status()
        alerts_data = system_status.get("alerts", {})
        active_alerts = alerts_data.get("recent_alerts", [])

        # Filter by severity if specified
        if severity:
            active_alerts = [
                alert for alert in active_alerts
                if alert.get("severity") == severity
            ]

        # Limit results
        active_alerts = active_alerts[-limit:] if limit else active_alerts

        return {
            "alerts": active_alerts,
            "total_active": alerts_data.get("active_count", 0),
            "returned_count": len(active_alerts),
            "timestamp": datetime.utcnow().isoformat(),
            "filters": {
                "severity": severity,
                "limit": limit
            }
        }

    except Exception as e:
        logger.error(f"Alert retrieval failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve alerts: {str(e)}"
        )

@monitoring_router.get("/metrics/live")
async def get_live_metrics():
    """
    Get real-time system metrics for dashboards

    Returns:
        Current system metrics and resource utilization
    """
    try:
        if link_monitoring_service is None:
            raise HTTPException(
                status_code=503,
                detail="Monitoring service not available"
            )

        # Get current system status
        system_status = await link_monitoring_service.get_system_status()

        # Extract key performance indicators
        performance = system_status.get("performance", {})
        health_checks = system_status.get("health_checks", {})

        # Get system resources from health checks
        system_health = health_checks.get("system", {})
        system_metadata = system_health.get("metadata", {})

        live_metrics = {
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": system_status.get("uptime_seconds", 0),
            "performance": {
                "requests_per_second": _calculate_requests_per_second(performance),
                "error_rate": performance.get("error_rate", 0),
                "avg_response_time_ms": performance.get("avg_response_time_ms", 0),
                "active_sessions": performance.get("active_sessions", 0)
            },
            "resources": {
                "cpu_percent": system_metadata.get("cpu_percent", 0),
                "memory_percent": system_metadata.get("memory_percent", 0),
                "memory_available_gb": system_metadata.get("memory_available_gb", 0)
            },
            "health": {
                "overall_status": system_status.get("status", "unknown"),
                "healthy_checks": len([
                    check for check in health_checks.values()
                    if isinstance(check, dict) and check.get("status") == "healthy"
                ]),
                "total_checks": len(health_checks)
            }
        }

        return live_metrics

    except Exception as e:
        logger.error(f"Live metrics retrieval failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve live metrics: {str(e)}"
        )

@monitoring_router.post("/metrics/record")
async def record_custom_metric(
    metric_name: str,
    metric_value: float,
    metric_type: str = "gauge",
    tags: Optional[Dict[str, str]] = None
):
    """
    Record a custom metric

    Args:
        metric_name: Name of the metric
        metric_value: Value of the metric
        metric_type: Type of metric (gauge, counter, histogram, timer)
        tags: Optional tags for the metric

    Returns:
        Confirmation of metric recording
    """
    try:
        if link_monitoring_service is None:
            raise HTTPException(
                status_code=503,
                detail="Monitoring service not available"
            )

        # Validate metric type
        valid_types = ["gauge", "counter", "histogram", "timer"]
        if metric_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid metric type. Must be one of: {valid_types}"
            )

        # Record the metric
        from services.link_monitoring_service import MetricType
        metric_type_enum = MetricType(metric_type.upper())

        await link_monitoring_service.record_metric(
            name=metric_name,
            value=metric_value,
            metric_type=metric_type_enum,
            tags=tags
        )

        return {
            "status": "recorded",
            "metric_name": metric_name,
            "metric_value": metric_value,
            "metric_type": metric_type,
            "tags": tags,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Custom metric recording failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to record metric: {str(e)}"
        )

def _convert_to_prometheus_format(metrics_summary: Dict[str, Any]) -> str:
    """Convert metrics to Prometheus format"""
    prometheus_lines = []

    for metric_name, metric_data in metrics_summary.get("metrics", {}).items():
        # Convert metric name to Prometheus format
        prom_name = metric_name.replace("-", "_").replace(" ", "_")

        # Add metric type comment
        prometheus_lines.append(f"# TYPE {prom_name} gauge")

        # Add metric value
        value = metric_data.get("latest", 0)
        prometheus_lines.append(f"{prom_name} {value}")

    return "\n".join(prometheus_lines)

def _calculate_requests_per_second(performance: Dict[str, Any]) -> float:
    """Calculate requests per second from performance data"""
    total_requests = performance.get("total_requests", 0)
    # This is a simplified calculation - in production you'd want a sliding window
    return total_requests / 60 if total_requests > 0 else 0

# Health check dependencies for other endpoints
async def ensure_monitoring_available():
    """Dependency to ensure monitoring service is available"""
    if link_monitoring_service is None:
        raise HTTPException(
            status_code=503,
            detail="Monitoring service not available"
        )
    return link_monitoring_service

# Add router to be included in main FastAPI app
__all__ = ["monitoring_router"]