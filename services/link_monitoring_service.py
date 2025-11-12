"""
Production Monitoring and Metrics Service for Link Master Agent
Provides comprehensive monitoring, health checks, and performance metrics

Features:
- Real-time health monitoring
- Performance metrics collection
- Error tracking and alerting
- Resource utilization monitoring
- SLA compliance tracking
- Production readiness verification
"""

import asyncio
import logging
import psutil
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import json
import os
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class HealthStatus(Enum):
    """Health check status levels"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"

class MetricType(Enum):
    """Types of metrics collected"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"

@dataclass
class HealthCheck:
    """Individual health check result"""
    name: str
    status: HealthStatus
    message: str
    timestamp: datetime
    response_time_ms: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            'status': self.status.value,
            'timestamp': self.timestamp.isoformat()
        }

@dataclass
class Metric:
    """Individual metric data point"""
    name: str
    value: float
    metric_type: MetricType
    timestamp: datetime
    tags: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            'metric_type': self.metric_type.value,
            'timestamp': self.timestamp.isoformat()
        }

@dataclass
class AlertRule:
    """Alert rule configuration"""
    name: str
    metric_name: str
    condition: str  # e.g., "> 100", "< 0.95"
    threshold: float
    severity: str  # low, medium, high, critical
    cooldown_minutes: int = 5
    last_triggered: Optional[datetime] = None

class LinkMonitoringService:
    """
    Comprehensive monitoring service for Link Master Agent

    Provides health checks, metrics collection, alerting, and performance monitoring
    for production deployment of the VouchLink chat system.
    """

    def __init__(self):
        self.start_time = datetime.now(timezone.utc)
        self.metrics_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.health_checks: Dict[str, HealthCheck] = {}
        self.alert_rules: List[AlertRule] = []
        self.active_alerts: List[Dict[str, Any]] = []

        # Performance counters
        self.request_count = 0
        self.error_count = 0
        self.total_response_time = 0.0
        self.active_sessions = 0
        self.total_sessions_created = 0

        # Resource monitoring
        self.cpu_usage_history: deque = deque(maxlen=100)
        self.memory_usage_history: deque = deque(maxlen=100)

        # Initialize default alert rules
        self._setup_default_alerts()

        logger.info("LinkMonitoringService initialized")

    def _setup_default_alerts(self):
        """Setup default monitoring alerts"""
        self.alert_rules = [
            AlertRule("high_error_rate", "error_rate", "> 0.05", 0.05, "high", 5),
            AlertRule("slow_response_time", "avg_response_time", "> 5000", 5000, "medium", 3),
            AlertRule("high_cpu_usage", "cpu_usage", "> 80", 80, "medium", 2),
            AlertRule("high_memory_usage", "memory_usage", "> 85", 85, "high", 2),
            AlertRule("many_active_sessions", "active_sessions", "> 1000", 1000, "low", 10),
            AlertRule("database_connection_failure", "database_health", "< 1", 1, "critical", 1),
            AlertRule("websocket_connection_failure", "websocket_health", "< 1", 1, "critical", 1)
        ]

    async def record_request(self, session_id: str, user_id: int, response_time_ms: float, success: bool = True):
        """Record a request for metrics tracking"""
        now = datetime.now(timezone.utc)

        # Update counters
        self.request_count += 1
        self.total_response_time += response_time_ms

        if not success:
            self.error_count += 1

        # Record metrics
        await self.record_metric("requests_total", self.request_count, MetricType.COUNTER)
        await self.record_metric("errors_total", self.error_count, MetricType.COUNTER)
        await self.record_metric("response_time_ms", response_time_ms, MetricType.HISTOGRAM)

        # Calculate and record derived metrics
        error_rate = self.error_count / max(self.request_count, 1)
        avg_response_time = self.total_response_time / max(self.request_count, 1)

        await self.record_metric("error_rate", error_rate, MetricType.GAUGE)
        await self.record_metric("avg_response_time", avg_response_time, MetricType.GAUGE)

        # Check alert conditions
        await self._check_alerts()

    async def record_session_created(self, session_id: str, user_id: int, organization_id: int):
        """Record new session creation"""
        self.total_sessions_created += 1
        self.active_sessions += 1

        await self.record_metric("sessions_created_total", self.total_sessions_created, MetricType.COUNTER)
        await self.record_metric("active_sessions", self.active_sessions, MetricType.GAUGE)

    async def record_session_ended(self, session_id: str):
        """Record session ending"""
        self.active_sessions = max(0, self.active_sessions - 1)
        await self.record_metric("active_sessions", self.active_sessions, MetricType.GAUGE)

    async def record_metric(self, name: str, value: float, metric_type: MetricType, tags: Optional[Dict[str, str]] = None):
        """Record a custom metric"""
        metric = Metric(
            name=name,
            value=value,
            metric_type=metric_type,
            timestamp=datetime.now(timezone.utc),
            tags=tags
        )

        # Store in history
        self.metrics_history[name].append(metric)

        # Log significant metrics
        if name in ["error_rate", "avg_response_time", "cpu_usage", "memory_usage"]:
            logger.debug(f"Metric recorded: {name} = {value}")

    async def perform_health_checks(self) -> Dict[str, HealthCheck]:
        """Perform comprehensive health checks"""
        health_checks = {}

        # System health
        health_checks["system"] = await self._check_system_health()
        health_checks["memory"] = await self._check_memory_health()
        health_checks["disk"] = await self._check_disk_health()

        # Service health
        health_checks["database"] = await self._check_database_health()
        health_checks["websocket"] = await self._check_websocket_health()
        health_checks["agent_services"] = await self._check_agent_services_health()

        # Application health
        health_checks["response_time"] = await self._check_response_time_health()
        health_checks["error_rate"] = await self._check_error_rate_health()
        health_checks["session_management"] = await self._check_session_health()

        # Store results
        self.health_checks = health_checks

        # Overall system status
        overall_status = self._calculate_overall_health(health_checks)
        health_checks["overall"] = HealthCheck(
            name="overall",
            status=overall_status,
            message=f"System {overall_status.value}",
            timestamp=datetime.now(timezone.utc)
        )

        return health_checks

    async def _check_system_health(self) -> HealthCheck:
        """Check system resource health"""
        start_time = time.time()

        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.cpu_usage_history.append(cpu_percent)
            await self.record_metric("cpu_usage", cpu_percent, MetricType.GAUGE)

            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            self.memory_usage_history.append(memory_percent)
            await self.record_metric("memory_usage", memory_percent, MetricType.GAUGE)

            # Determine status
            if cpu_percent > 90 or memory_percent > 95:
                status = HealthStatus.CRITICAL
                message = f"High resource usage: CPU {cpu_percent:.1f}%, Memory {memory_percent:.1f}%"
            elif cpu_percent > 80 or memory_percent > 85:
                status = HealthStatus.WARNING
                message = f"Moderate resource usage: CPU {cpu_percent:.1f}%, Memory {memory_percent:.1f}%"
            else:
                status = HealthStatus.HEALTHY
                message = f"System healthy: CPU {cpu_percent:.1f}%, Memory {memory_percent:.1f}%"

            response_time = (time.time() - start_time) * 1000

            return HealthCheck(
                name="system",
                status=status,
                message=message,
                timestamp=datetime.now(timezone.utc),
                response_time_ms=response_time,
                metadata={
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                    "memory_available_gb": memory.available / (1024**3)
                }
            )

        except Exception as e:
            logger.error(f"System health check failed: {e}")
            return HealthCheck(
                name="system",
                status=HealthStatus.CRITICAL,
                message=f"System health check failed: {str(e)}",
                timestamp=datetime.now(timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000
            )

    async def _check_memory_health(self) -> HealthCheck:
        """Check memory usage patterns"""
        start_time = time.time()

        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()

            # Check for memory leaks (rapid growth)
            if len(self.memory_usage_history) > 10:
                recent_avg = sum(list(self.memory_usage_history)[-5:]) / 5
                older_avg = sum(list(self.memory_usage_history)[-10:-5]) / 5
                growth_rate = (recent_avg - older_avg) / older_avg if older_avg > 0 else 0

                if growth_rate > 0.2:  # 20% growth
                    status = HealthStatus.WARNING
                    message = f"Memory growth detected: {growth_rate:.1%}"
                else:
                    status = HealthStatus.HEALTHY
                    message = f"Memory stable: {memory_percent:.1f}%"
            else:
                status = HealthStatus.HEALTHY
                message = f"Memory usage: {memory_percent:.1f}%"

            return HealthCheck(
                name="memory",
                status=status,
                message=message,
                timestamp=datetime.now(timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000,
                metadata={
                    "rss_mb": memory_info.rss / (1024*1024),
                    "vms_mb": memory_info.vms / (1024*1024),
                    "percent": memory_percent
                }
            )

        except Exception as e:
            logger.error(f"Memory health check failed: {e}")
            return HealthCheck(
                name="memory",
                status=HealthStatus.CRITICAL,
                message=f"Memory health check failed: {str(e)}",
                timestamp=datetime.now(timezone.utc)
            )

    async def _check_disk_health(self) -> HealthCheck:
        """Check disk space health"""
        start_time = time.time()

        try:
            disk_usage = psutil.disk_usage('/')
            free_percent = (disk_usage.free / disk_usage.total) * 100
            used_percent = 100 - free_percent

            if used_percent > 95:
                status = HealthStatus.CRITICAL
                message = f"Disk space critical: {used_percent:.1f}% used"
            elif used_percent > 85:
                status = HealthStatus.WARNING
                message = f"Disk space low: {used_percent:.1f}% used"
            else:
                status = HealthStatus.HEALTHY
                message = f"Disk space healthy: {used_percent:.1f}% used"

            return HealthCheck(
                name="disk",
                status=status,
                message=message,
                timestamp=datetime.now(timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000,
                metadata={
                    "total_gb": disk_usage.total / (1024**3),
                    "used_gb": disk_usage.used / (1024**3),
                    "free_gb": disk_usage.free / (1024**3),
                    "used_percent": used_percent
                }
            )

        except Exception as e:
            logger.error(f"Disk health check failed: {e}")
            return HealthCheck(
                name="disk",
                status=HealthStatus.CRITICAL,
                message=f"Disk health check failed: {str(e)}",
                timestamp=datetime.now(timezone.utc)
            )

    async def _check_database_health(self) -> HealthCheck:
        """Check database connectivity and performance"""
        logger.warning("Database health check requested but no implementation is configured")

        await self.record_metric("database_health", 0, MetricType.GAUGE)

        return HealthCheck(
            name="database",
            status=HealthStatus.UNKNOWN,
            message="Database health check not configured",
            timestamp=datetime.now(timezone.utc),
            metadata={}
        )

    async def _check_websocket_health(self) -> HealthCheck:
        """Check WebSocket service health"""
        logger.warning("WebSocket health check requested but no implementation is configured")

        await self.record_metric("websocket_health", 0, MetricType.GAUGE)

        return HealthCheck(
            name="websocket",
            status=HealthStatus.UNKNOWN,
            message="WebSocket health check not configured",
            timestamp=datetime.now(timezone.utc),
            metadata={}
        )

    async def _check_agent_services_health(self) -> HealthCheck:
        """Check health of agent services"""
        start_time = time.time()

        try:
            # Check critical agent services
            services_status = {}

            # Check master chat agent
            try:
                from .master_chat_agent import master_chat_agent
                services_status["master_chat_agent"] = True
            except Exception:
                services_status["master_chat_agent"] = False

            # Check conversation context manager
            try:
                from .conversation_context_manager import conversation_context_manager
                services_status["context_manager"] = True
            except Exception:
                services_status["context_manager"] = False

            # Check security filter
            try:
                from .chat_security_filter import chat_security_filter
                services_status["security_filter"] = True
            except Exception:
                services_status["security_filter"] = False

            # Check tool registry
            try:
                from .chat_tool_registry import chat_tool_registry
                services_status["tool_registry"] = True
            except Exception:
                services_status["tool_registry"] = False

            # Determine overall agent health
            healthy_services = sum(1 for status in services_status.values() if status)
            total_services = len(services_status)
            health_ratio = healthy_services / total_services

            if health_ratio == 1.0:
                status = HealthStatus.HEALTHY
                message = f"All {total_services} agent services healthy"
            elif health_ratio >= 0.8:
                status = HealthStatus.WARNING
                message = f"{healthy_services}/{total_services} agent services healthy"
            else:
                status = HealthStatus.CRITICAL
                message = f"Only {healthy_services}/{total_services} agent services healthy"

            return HealthCheck(
                name="agent_services",
                status=status,
                message=message,
                timestamp=datetime.now(timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000,
                metadata={
                    "services_status": services_status,
                    "health_ratio": health_ratio
                }
            )

        except Exception as e:
            logger.error(f"Agent services health check failed: {e}")
            return HealthCheck(
                name="agent_services",
                status=HealthStatus.CRITICAL,
                message=f"Agent services health check failed: {str(e)}",
                timestamp=datetime.now(timezone.utc)
            )

    async def _check_response_time_health(self) -> HealthCheck:
        """Check response time performance"""
        if self.request_count == 0:
            return HealthCheck(
                name="response_time",
                status=HealthStatus.HEALTHY,
                message="No requests processed yet",
                timestamp=datetime.now(timezone.utc)
            )

        avg_response_time = self.total_response_time / self.request_count

        if avg_response_time > 10000:  # 10 seconds
            status = HealthStatus.CRITICAL
            message = f"Very slow responses: {avg_response_time:.1f}ms avg"
        elif avg_response_time > 5000:  # 5 seconds
            status = HealthStatus.WARNING
            message = f"Slow responses: {avg_response_time:.1f}ms avg"
        else:
            status = HealthStatus.HEALTHY
            message = f"Response time healthy: {avg_response_time:.1f}ms avg"

        return HealthCheck(
            name="response_time",
            status=status,
            message=message,
            timestamp=datetime.now(timezone.utc),
            metadata={
                "avg_response_time_ms": avg_response_time,
                "total_requests": self.request_count
            }
        )

    async def _check_error_rate_health(self) -> HealthCheck:
        """Check error rate health"""
        if self.request_count == 0:
            return HealthCheck(
                name="error_rate",
                status=HealthStatus.HEALTHY,
                message="No requests processed yet",
                timestamp=datetime.now(timezone.utc)
            )

        error_rate = self.error_count / self.request_count

        if error_rate > 0.1:  # 10%
            status = HealthStatus.CRITICAL
            message = f"High error rate: {error_rate:.1%}"
        elif error_rate > 0.05:  # 5%
            status = HealthStatus.WARNING
            message = f"Elevated error rate: {error_rate:.1%}"
        else:
            status = HealthStatus.HEALTHY
            message = f"Error rate healthy: {error_rate:.1%}"

        return HealthCheck(
            name="error_rate",
            status=status,
            message=message,
            timestamp=datetime.now(timezone.utc),
            metadata={
                "error_rate": error_rate,
                "error_count": self.error_count,
                "total_requests": self.request_count
            }
        )

    async def _check_session_health(self) -> HealthCheck:
        """Check session management health"""
        if self.active_sessions > 10000:
            status = HealthStatus.WARNING
            message = f"Very high session count: {self.active_sessions}"
        elif self.active_sessions > 5000:
            status = HealthStatus.WARNING
            message = f"High session count: {self.active_sessions}"
        else:
            status = HealthStatus.HEALTHY
            message = f"Session count healthy: {self.active_sessions}"

        return HealthCheck(
            name="session_management",
            status=status,
            message=message,
            timestamp=datetime.now(timezone.utc),
            metadata={
                "active_sessions": self.active_sessions,
                "total_sessions_created": self.total_sessions_created
            }
        )

    def _calculate_overall_health(self, health_checks: Dict[str, HealthCheck]) -> HealthStatus:
        """Calculate overall system health"""
        critical_count = sum(1 for check in health_checks.values() if check.status == HealthStatus.CRITICAL)
        warning_count = sum(1 for check in health_checks.values() if check.status == HealthStatus.WARNING)

        if critical_count > 0:
            return HealthStatus.CRITICAL
        elif warning_count > 2:
            return HealthStatus.WARNING
        elif warning_count > 0:
            return HealthStatus.WARNING
        else:
            return HealthStatus.HEALTHY

    async def _check_alerts(self):
        """Check alert conditions and trigger alerts"""
        current_time = datetime.now(timezone.utc)

        for rule in self.alert_rules:
            # Skip if in cooldown period
            if (rule.last_triggered and
                current_time - rule.last_triggered < timedelta(minutes=rule.cooldown_minutes)):
                continue

            # Get current metric value
            if rule.metric_name in self.metrics_history:
                recent_metrics = list(self.metrics_history[rule.metric_name])
                if recent_metrics:
                    current_value = recent_metrics[-1].value

                    # Evaluate condition
                    if self._evaluate_alert_condition(current_value, rule.condition, rule.threshold):
                        await self._trigger_alert(rule, current_value)

    def _evaluate_alert_condition(self, value: float, condition: str, threshold: float) -> bool:
        """Evaluate alert condition"""
        if condition.startswith(">"):
            return value > threshold
        elif condition.startswith("<"):
            return value < threshold
        elif condition.startswith(">="):
            return value >= threshold
        elif condition.startswith("<="):
            return value <= threshold
        elif condition.startswith("=="):
            return value == threshold
        else:
            return False

    async def _trigger_alert(self, rule: AlertRule, current_value: float):
        """Trigger an alert"""
        rule.last_triggered = datetime.now(timezone.utc)

        alert = {
            "id": f"alert_{int(time.time())}",
            "rule_name": rule.name,
            "metric_name": rule.metric_name,
            "severity": rule.severity,
            "current_value": current_value,
            "threshold": rule.threshold,
            "condition": rule.condition,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": f"Alert: {rule.name} - {rule.metric_name} {rule.condition} {rule.threshold} (current: {current_value})"
        }

        self.active_alerts.append(alert)

        # Keep only recent alerts
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        self.active_alerts = [
            alert for alert in self.active_alerts
            if datetime.fromisoformat(alert["timestamp"]) > cutoff_time
        ]

        logger.warning(f"Alert triggered: {alert['message']}")

    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        health_checks = await self.perform_health_checks()

        # Calculate uptime
        uptime = datetime.now(timezone.utc) - self.start_time

        # Get recent metrics
        recent_metrics = {}
        for metric_name, history in self.metrics_history.items():
            if history:
                recent_metrics[metric_name] = {
                    "current": history[-1].value,
                    "avg_last_10": sum(m.value for m in list(history)[-10:]) / min(len(history), 10)
                }

        return {
            "status": health_checks["overall"].status.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": int(uptime.total_seconds()),
            "health_checks": {name: check.to_dict() for name, check in health_checks.items()},
            "metrics": recent_metrics,
            "performance": {
                "total_requests": self.request_count,
                "total_errors": self.error_count,
                "error_rate": self.error_count / max(self.request_count, 1),
                "avg_response_time_ms": self.total_response_time / max(self.request_count, 1),
                "active_sessions": self.active_sessions,
                "total_sessions_created": self.total_sessions_created
            },
            "alerts": {
                "active_count": len(self.active_alerts),
                "recent_alerts": self.active_alerts[-10:]  # Last 10 alerts
            },
            "system_info": {
                "cpu_count": psutil.cpu_count(),
                "memory_total_gb": psutil.virtual_memory().total / (1024**3),
                "disk_total_gb": psutil.disk_usage('/').total / (1024**3),
                "process_id": os.getpid()
            }
        }

    async def get_metrics_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get metrics summary for specified time period"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        summary = {}
        for metric_name, history in self.metrics_history.items():
            recent_metrics = [m for m in history if m.timestamp > cutoff_time]

            if recent_metrics:
                values = [m.value for m in recent_metrics]
                summary[metric_name] = {
                    "count": len(values),
                    "min": min(values),
                    "max": max(values),
                    "avg": sum(values) / len(values),
                    "latest": values[-1],
                    "trend": "stable"  # Could implement trend analysis
                }

        return {
            "period_hours": hours,
            "metrics": summary,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

# Global monitoring service instance
link_monitoring_service = LinkMonitoringService()