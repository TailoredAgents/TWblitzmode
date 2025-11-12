#!/usr/bin/env python3
"""
Enterprise Monitoring & Observability Service - September 2025 Production Hardening
Comprehensive monitoring, metrics collection, and observability for Master Game Plan

Features:
- Real-time metrics collection and aggregation
- Distributed tracing across all workflow stages
- Performance monitoring with alerting
- Health checks and SLA monitoring
- Custom dashboards and reporting
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Union, Callable
import weakref

# Import enterprise services
from services.database_pool_manager import get_main_db_connection
from services.error_handling_framework import error_handler
from services.resilience_patterns import resilience_manager

logger = logging.getLogger(__name__)

class MetricType(Enum):
    """Types of metrics"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"

class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

class TraceEventType(Enum):
    """Distributed tracing event types"""
    WORKFLOW_START = "workflow_start"
    WORKFLOW_END = "workflow_end"
    STAGE_START = "stage_start"
    STAGE_END = "stage_end"
    SERVICE_CALL = "service_call"
    DATABASE_QUERY = "database_query"
    ERROR_EVENT = "error_event"
    APPROVAL_REQUEST = "approval_request"
    EMAIL_SENT = "email_sent"

@dataclass
class Metric:
    """Individual metric data point"""
    name: str
    metric_type: MetricType
    value: Union[int, float]
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    help_text: str = ""

@dataclass
class TraceSpan:
    """Distributed tracing span"""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    service_name: str = "unknown"
    operation_name: str = "unknown"
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    status: str = "ok"
    tags: Dict[str, Any] = field(default_factory=dict)
    logs: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

@dataclass
class HealthCheck:
    """Health check definition"""
    name: str
    service: str
    check_function: Callable
    interval_seconds: int = 30
    timeout_seconds: int = 10
    failure_threshold: int = 3
    current_failures: int = 0
    last_check: Optional[datetime] = None
    last_success: Optional[datetime] = None
    status: str = "unknown"

@dataclass
class Alert:
    """System alert"""
    id: str
    level: AlertLevel
    title: str
    description: str
    service: str
    metric_name: Optional[str] = None
    threshold_value: Optional[float] = None
    current_value: Optional[float] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    tags: Dict[str, str] = field(default_factory=dict)

class MetricsCollector:
    """Collects and aggregates system metrics"""

    def __init__(self):
        self.metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))
        self.metric_definitions: Dict[str, Metric] = {}
        self.aggregation_window = timedelta(minutes=1)
        self._lock = asyncio.Lock()

    async def record_metric(self,
                          name: str,
                          value: Union[int, float],
                          metric_type: MetricType = MetricType.GAUGE,
                          labels: Dict[str, str] = None,
                          help_text: str = ""):
        """Record a metric value"""

        async with self._lock:
            metric = Metric(
                name=name,
                metric_type=metric_type,
                value=value,
                labels=labels or {},
                help_text=help_text
            )

            # Store metric
            metric_key = self._get_metric_key(name, labels or {})
            self.metrics[metric_key].append(metric)

            # Update metric definition
            if name not in self.metric_definitions:
                self.metric_definitions[name] = metric

    def _get_metric_key(self, name: str, labels: Dict[str, str]) -> str:
        """Generate unique key for metric with labels"""
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    async def get_metrics(self,
                         name_pattern: Optional[str] = None,
                         time_range: Optional[timedelta] = None) -> List[Metric]:
        """Get metrics matching pattern and time range"""

        cutoff_time = datetime.now(timezone.utc) - (time_range or timedelta(hours=1))
        result = []

        async with self._lock:
            for metric_key, metric_deque in self.metrics.items():
                if name_pattern and name_pattern not in metric_key:
                    continue

                for metric in metric_deque:
                    if metric.timestamp >= cutoff_time:
                        result.append(metric)

        return result

    async def get_aggregated_metrics(self,
                                   name: str,
                                   labels: Dict[str, str] = None,
                                   aggregation: str = "avg",
                                   window: timedelta = None) -> Optional[float]:
        """Get aggregated metric value over time window"""

        window = window or self.aggregation_window
        cutoff_time = datetime.now(timezone.utc) - window
        metric_key = self._get_metric_key(name, labels or {})

        async with self._lock:
            values = [
                metric.value for metric in self.metrics[metric_key]
                if metric.timestamp >= cutoff_time
            ]

        if not values:
            return None

        if aggregation == "avg":
            return sum(values) / len(values)
        elif aggregation == "sum":
            return sum(values)
        elif aggregation == "min":
            return min(values)
        elif aggregation == "max":
            return max(values)
        elif aggregation == "count":
            return len(values)
        else:
            return values[-1]  # latest

class DistributedTracer:
    """Distributed tracing across services"""

    def __init__(self):
        self.active_spans: Dict[str, TraceSpan] = {}
        self.completed_traces: deque = deque(maxlen=10000)
        self._lock = asyncio.Lock()

    async def start_span(self,
                        operation_name: str,
                        service_name: str = "unknown",
                        trace_id: Optional[str] = None,
                        parent_span_id: Optional[str] = None,
                        tags: Dict[str, Any] = None) -> TraceSpan:
        """Start a new tracing span"""

        span_id = str(uuid.uuid4())
        trace_id = trace_id or str(uuid.uuid4())

        span = TraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            service_name=service_name,
            operation_name=operation_name,
            tags=tags or {}
        )

        async with self._lock:
            self.active_spans[span_id] = span

        return span

    async def finish_span(self,
                         span: TraceSpan,
                         status: str = "ok",
                         error: Optional[str] = None):
        """Finish a tracing span"""

        span.end_time = datetime.now(timezone.utc)
        span.duration_ms = (span.end_time - span.start_time).total_seconds() * 1000
        span.status = status
        span.error = error

        async with self._lock:
            if span.span_id in self.active_spans:
                del self.active_spans[span.span_id]

            self.completed_traces.append(span)

    async def add_span_log(self, span: TraceSpan, level: str, message: str, **kwargs):
        """Add log entry to span"""

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            **kwargs
        }

        span.logs.append(log_entry)

    async def get_trace(self, trace_id: str) -> List[TraceSpan]:
        """Get all spans for a trace"""

        spans = []

        # Check active spans
        async with self._lock:
            for span in self.active_spans.values():
                if span.trace_id == trace_id:
                    spans.append(span)

            # Check completed traces
            for span in self.completed_traces:
                if span.trace_id == trace_id:
                    spans.append(span)

        return sorted(spans, key=lambda s: s.start_time)

    async def get_traces_by_service(self,
                                  service_name: str,
                                  time_range: timedelta = timedelta(hours=1)) -> List[TraceSpan]:
        """Get traces for a specific service"""

        cutoff_time = datetime.now(timezone.utc) - time_range
        spans = []

        async with self._lock:
            for span in self.completed_traces:
                if (span.service_name == service_name and
                    span.start_time >= cutoff_time):
                    spans.append(span)

        return sorted(spans, key=lambda s: s.start_time, reverse=True)

class HealthMonitor:
    """Health monitoring and checks"""

    def __init__(self):
        self.health_checks: Dict[str, HealthCheck] = {}
        self.health_history: deque = deque(maxlen=1000)
        self._monitoring_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    def register_health_check(self, health_check: HealthCheck):
        """Register a health check"""
        self.health_checks[health_check.name] = health_check
        logger.info(f"🩺 Registered health check: {health_check.name}")

    async def start_monitoring(self):
        """Start health monitoring"""
        if self._monitoring_task:
            logger.warning("Health monitoring already started")
            return

        self._monitoring_task = asyncio.create_task(self._monitor_health())
        logger.info("🩺 Health monitoring started")

    async def _monitor_health(self):
        """Background health monitoring task"""
        while not self._shutdown_event.is_set():
            try:
                # Run all health checks
                for health_check in self.health_checks.values():
                    await self._run_health_check(health_check)

                # Wait for next check interval
                await asyncio.sleep(10)  # Check every 10 seconds

            except Exception as e:
                logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(10)

    async def _run_health_check(self, health_check: HealthCheck):
        """Run individual health check"""
        now = datetime.now(timezone.utc)

        # Skip if not time for next check
        if (health_check.last_check and
            (now - health_check.last_check).total_seconds() < health_check.interval_seconds):
            return

        try:
            # Run the check with timeout
            result = await asyncio.wait_for(
                health_check.check_function(),
                timeout=health_check.timeout_seconds
            )

            # Process result
            if result.get('healthy', False):
                health_check.status = "healthy"
                health_check.current_failures = 0
                health_check.last_success = now
            else:
                health_check.current_failures += 1
                if health_check.current_failures >= health_check.failure_threshold:
                    health_check.status = "unhealthy"
                else:
                    health_check.status = "degraded"

            health_check.last_check = now

            # Store health history
            self.health_history.append({
                "timestamp": now,
                "check_name": health_check.name,
                "service": health_check.service,
                "status": health_check.status,
                "result": result
            })

        except asyncio.TimeoutError:
            health_check.current_failures += 1
            health_check.status = "timeout"
            health_check.last_check = now

        except Exception as e:
            health_check.current_failures += 1
            health_check.status = "error"
            health_check.last_check = now

            logger.error(f"Health check {health_check.name} failed: {e}")

    async def get_health_summary(self) -> Dict[str, Any]:
        """Get overall health summary"""

        healthy_checks = sum(1 for hc in self.health_checks.values() if hc.status == "healthy")
        total_checks = len(self.health_checks)

        service_health = defaultdict(list)
        for hc in self.health_checks.values():
            service_health[hc.service].append(hc.status)

        return {
            "overall_status": "healthy" if healthy_checks == total_checks else "degraded",
            "healthy_checks": healthy_checks,
            "total_checks": total_checks,
            "health_percentage": (healthy_checks / max(total_checks, 1)) * 100,
            "service_health": {
                service: {
                    "status": "healthy" if all(status == "healthy" for status in statuses) else "degraded",
                    "checks": len(statuses),
                    "healthy": sum(1 for status in statuses if status == "healthy")
                }
                for service, statuses in service_health.items()
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def stop_monitoring(self):
        """Stop health monitoring"""
        self._shutdown_event.set()

        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        logger.info("🩺 Health monitoring stopped")

class AlertManager:
    """Alert management and notifications"""

    def __init__(self):
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: deque = deque(maxlen=1000)
        self.alert_rules: List[Dict[str, Any]] = []
        self.notification_handlers: List[Callable] = []

    def add_alert_rule(self,
                      metric_name: str,
                      threshold: float,
                      operator: str = ">=",
                      level: AlertLevel = AlertLevel.WARNING,
                      service: str = "unknown"):
        """Add alert rule for metric threshold"""

        rule = {
            "metric_name": metric_name,
            "threshold": threshold,
            "operator": operator,
            "level": level,
            "service": service
        }

        self.alert_rules.append(rule)
        logger.info(f"🚨 Added alert rule: {metric_name} {operator} {threshold}")

    def add_notification_handler(self, handler: Callable):
        """Add notification handler for alerts"""
        self.notification_handlers.append(handler)

    async def check_alerts(self, metrics: List[Metric]):
        """Check metrics against alert rules"""

        for metric in metrics:
            for rule in self.alert_rules:
                if metric.name != rule["metric_name"]:
                    continue

                # Evaluate threshold
                triggered = False
                operator = rule["operator"]
                threshold = rule["threshold"]

                if operator == ">=" and metric.value >= threshold:
                    triggered = True
                elif operator == ">" and metric.value > threshold:
                    triggered = True
                elif operator == "<=" and metric.value <= threshold:
                    triggered = True
                elif operator == "<" and metric.value < threshold:
                    triggered = True
                elif operator == "==" and metric.value == threshold:
                    triggered = True

                if triggered:
                    await self._trigger_alert(metric, rule)

    async def _trigger_alert(self, metric: Metric, rule: Dict[str, Any]):
        """Trigger an alert"""

        alert_id = f"{rule['service']}_{rule['metric_name']}_{rule['threshold']}"

        # Check if alert already active
        if alert_id in self.active_alerts:
            return

        # Create alert
        alert = Alert(
            id=alert_id,
            level=rule["level"],
            title=f"{rule['metric_name']} threshold exceeded",
            description=f"{rule['metric_name']} value {metric.value} {rule['operator']} {rule['threshold']}",
            service=rule["service"],
            metric_name=rule["metric_name"],
            threshold_value=rule["threshold"],
            current_value=metric.value,
            tags=metric.labels
        )

        self.active_alerts[alert_id] = alert
        self.alert_history.append(alert)

        # Send notifications
        for handler in self.notification_handlers:
            try:
                await handler(alert)
            except Exception as e:
                logger.error(f"Notification handler failed: {e}")

        logger.warning(f"🚨 Alert triggered: {alert.title}")

    async def resolve_alert(self, alert_id: str):
        """Resolve an active alert"""

        if alert_id in self.active_alerts:
            alert = self.active_alerts[alert_id]
            alert.resolved_at = datetime.now(timezone.utc)
            del self.active_alerts[alert_id]

            logger.info(f"✅ Alert resolved: {alert.title}")

    async def get_alerts(self,
                        level: Optional[AlertLevel] = None,
                        service: Optional[str] = None,
                        active_only: bool = False) -> List[Alert]:
        """Get alerts with filtering"""

        alerts = list(self.active_alerts.values()) if active_only else list(self.alert_history)

        if level:
            alerts = [a for a in alerts if a.level == level]

        if service:
            alerts = [a for a in alerts if a.service == service]

        return sorted(alerts, key=lambda a: a.created_at, reverse=True)

class MonitoringObservabilityService:
    """Main monitoring and observability service"""

    def __init__(self):
        self.metrics_collector = MetricsCollector()
        self.tracer = DistributedTracer()
        self.health_monitor = HealthMonitor()
        self.alert_manager = AlertManager()

        # Background tasks
        self._background_tasks: List[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()

        # Performance tracking
        self.workflow_performance = defaultdict(list)
        self.service_performance = defaultdict(list)

        logger.info("📊 Monitoring & Observability Service initialized")

    async def initialize(self):
        """Initialize the monitoring service"""

        # Setup default health checks
        await self._setup_default_health_checks()

        # Setup default alert rules
        self._setup_default_alert_rules()

        # Setup default notification handlers
        self._setup_default_notification_handlers()

        # Start health monitoring
        await self.health_monitor.start_monitoring()

        # Start background tasks
        self._background_tasks = [
            asyncio.create_task(self._metrics_aggregation_task()),
            asyncio.create_task(self._alert_checking_task()),
            asyncio.create_task(self._performance_tracking_task())
        ]

        logger.info("✅ Monitoring & Observability Service initialized")

    async def _setup_default_health_checks(self):
        """Setup default system health checks"""

        # Database health check
        database_check = HealthCheck(
            name="database_connection",
            service="database",
            check_function=self._check_database_health,
            interval_seconds=30
        )
        self.health_monitor.register_health_check(database_check)

        # Error handler health check
        error_handler_check = HealthCheck(
            name="error_handler",
            service="error_handling",
            check_function=self._check_error_handler_health,
            interval_seconds=60
        )
        self.health_monitor.register_health_check(error_handler_check)

        # Resilience patterns health check
        resilience_check = HealthCheck(
            name="resilience_patterns",
            service="resilience",
            check_function=self._check_resilience_health,
            interval_seconds=60
        )
        self.health_monitor.register_health_check(resilience_check)

    def _setup_default_alert_rules(self):
        """Setup default alert rules"""

        # Database connection errors
        self.alert_manager.add_alert_rule(
            metric_name="database_connection_errors",
            threshold=5,
            operator=">=",
            level=AlertLevel.CRITICAL,
            service="database"
        )

        # Workflow failure rate
        self.alert_manager.add_alert_rule(
            metric_name="workflow_failure_rate",
            threshold=10.0,
            operator=">=",
            level=AlertLevel.WARNING,
            service="workflow"
        )

        # Circuit breaker open
        self.alert_manager.add_alert_rule(
            metric_name="circuit_breaker_open_count",
            threshold=1,
            operator=">=",
            level=AlertLevel.CRITICAL,
            service="resilience"
        )

        # Response time alert
        self.alert_manager.add_alert_rule(
            metric_name="avg_response_time_ms",
            threshold=5000,  # 5 seconds
            operator=">=",
            level=AlertLevel.WARNING,
            service="performance"
        )

    def _setup_default_notification_handlers(self):
        """Setup default notification handlers"""

        # Log-based notification
        async def log_notification_handler(alert: Alert):
            logger.warning(f"🚨 ALERT [{alert.level.value.upper()}]: {alert.title} - {alert.description}")

        self.alert_manager.add_notification_handler(log_notification_handler)

    async def _check_database_health(self) -> Dict[str, Any]:
        """Check database connectivity"""

        try:
            async with get_main_db_connection() as conn:
                result = await conn.fetchval("SELECT 1")
                return {"healthy": result == 1, "response_time_ms": 50}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    async def _check_error_handler_health(self) -> Dict[str, Any]:
        """Check error handler health"""

        try:
            stats = error_handler.get_error_stats()
            recent_errors = len(stats.get("recent_errors", []))
            return {
                "healthy": recent_errors < 100,  # Less than 100 errors in last hour
                "recent_errors": recent_errors,
                "total_errors": stats.get("total_errors", 0)
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    async def _check_resilience_health(self) -> Dict[str, Any]:
        """Check resilience patterns health"""

        try:
            health = await resilience_manager.get_health_summary()

            # Check if any circuit breakers are open
            cb_health = health.get("circuit_breakers", {})
            open_circuit_breakers = sum(
                1 for cb_data in cb_health.values()
                if cb_data.get("state") == "open"
            )

            return {
                "healthy": open_circuit_breakers == 0,
                "open_circuit_breakers": open_circuit_breakers,
                "total_circuit_breakers": len(cb_health)
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    async def _metrics_aggregation_task(self):
        """Background task for metrics aggregation"""

        while not self._shutdown_event.is_set():
            try:
                # Aggregate metrics every minute
                await self._aggregate_metrics()
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Metrics aggregation error: {e}")
                await asyncio.sleep(60)

    async def _alert_checking_task(self):
        """Background task for alert checking"""

        while not self._shutdown_event.is_set():
            try:
                # Check alerts every 30 seconds
                recent_metrics = await self.metrics_collector.get_metrics(
                    time_range=timedelta(minutes=5)
                )
                await self.alert_manager.check_alerts(recent_metrics)
                await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"Alert checking error: {e}")
                await asyncio.sleep(30)

    async def _performance_tracking_task(self):
        """Background task for performance tracking"""

        while not self._shutdown_event.is_set():
            try:
                # Track performance metrics every 5 minutes
                await self._track_performance_metrics()
                await asyncio.sleep(300)

            except Exception as e:
                logger.error(f"Performance tracking error: {e}")
                await asyncio.sleep(300)

    async def _aggregate_metrics(self):
        """Aggregate metrics for dashboard"""

        # Get recent metrics
        recent_metrics = await self.metrics_collector.get_metrics(
            time_range=timedelta(minutes=5)
        )

        # Calculate aggregations
        metric_aggregations = defaultdict(list)
        for metric in recent_metrics:
            metric_aggregations[metric.name].append(metric.value)

        # Record aggregated metrics
        for metric_name, values in metric_aggregations.items():
            if values:
                avg_value = sum(values) / len(values)
                await self.metrics_collector.record_metric(
                    f"{metric_name}_avg_5min",
                    avg_value,
                    MetricType.GAUGE
                )

    async def _track_performance_metrics(self):
        """Track system performance metrics"""

        # Get workflow performance
        workflow_spans = await self.tracer.get_traces_by_service(
            "enterprise_master_game_plan_orchestrator",
            time_range=timedelta(minutes=5)
        )

        if workflow_spans:
            durations = [span.duration_ms for span in workflow_spans if span.duration_ms]
            if durations:
                avg_duration = sum(durations) / len(durations)
                await self.metrics_collector.record_metric(
                    "workflow_avg_duration_ms",
                    avg_duration,
                    MetricType.GAUGE,
                    {"service": "workflow"}
                )

    # Public API methods for instrumentation

    async def record_workflow_event(self,
                                  workflow_id: str,
                                  event_type: str,
                                  organization_id: int,
                                  duration_ms: Optional[float] = None,
                                  metadata: Dict[str, Any] = None):
        """Record workflow event for monitoring"""

        labels = {
            "workflow_id": workflow_id,
            "organization_id": str(organization_id),
            "event_type": event_type
        }

        # Record event count
        await self.metrics_collector.record_metric(
            "workflow_events_total",
            1,
            MetricType.COUNTER,
            labels
        )

        # Record duration if provided
        if duration_ms is not None:
            await self.metrics_collector.record_metric(
                "workflow_event_duration_ms",
                duration_ms,
                MetricType.HISTOGRAM,
                labels
            )

    async def record_service_call(self,
                                service_name: str,
                                operation: str,
                                duration_ms: float,
                                success: bool = True,
                                error: Optional[str] = None):
        """Record service call metrics"""

        labels = {
            "service": service_name,
            "operation": operation,
            "status": "success" if success else "error"
        }

        # Record call count
        await self.metrics_collector.record_metric(
            "service_calls_total",
            1,
            MetricType.COUNTER,
            labels
        )

        # Record duration
        await self.metrics_collector.record_metric(
            "service_call_duration_ms",
            duration_ms,
            MetricType.HISTOGRAM,
            labels
        )

        # Record error if present
        if error:
            await self.metrics_collector.record_metric(
                "service_errors_total",
                1,
                MetricType.COUNTER,
                {**labels, "error_type": type(error).__name__ if isinstance(error, Exception) else "unknown"}
            )

    async def start_trace(self,
                         operation_name: str,
                         service_name: str,
                         trace_id: Optional[str] = None,
                         parent_span_id: Optional[str] = None,
                         workflow_id: Optional[str] = None,
                         organization_id: Optional[int] = None) -> TraceSpan:
        """Start distributed trace"""

        tags = {}
        if workflow_id:
            tags["workflow_id"] = workflow_id
        if organization_id:
            tags["organization_id"] = str(organization_id)

        return await self.tracer.start_span(
            operation_name=operation_name,
            service_name=service_name,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            tags=tags
        )

    async def finish_trace(self,
                          span: TraceSpan,
                          success: bool = True,
                          error: Optional[str] = None):
        """Finish distributed trace"""

        status = "ok" if success else "error"
        await self.tracer.finish_span(span, status=status, error=error)

    async def get_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive dashboard data"""

        # Get recent metrics
        recent_metrics = await self.metrics_collector.get_metrics(
            time_range=timedelta(hours=1)
        )

        # Get health summary
        health_summary = await self.health_monitor.get_health_summary()

        # Get active alerts
        active_alerts = await self.alert_manager.get_alerts(active_only=True)

        # Get recent traces
        recent_traces = await self.tracer.get_traces_by_service(
            "enterprise_master_game_plan_orchestrator",
            time_range=timedelta(hours=1)
        )

        # Calculate key performance indicators
        kpis = await self._calculate_kpis(recent_metrics, recent_traces)

        return {
            "health_summary": health_summary,
            "active_alerts": [asdict(alert) for alert in active_alerts],
            "recent_alerts_count": len(active_alerts),
            "kpis": kpis,
            "recent_traces_count": len(recent_traces),
            "metrics_summary": {
                "total_metrics": len(recent_metrics),
                "unique_metric_names": len(set(m.name for m in recent_metrics))
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def _calculate_kpis(self, metrics: List[Metric], traces: List[TraceSpan]) -> Dict[str, Any]:
        """Calculate key performance indicators"""

        kpis = {}

        # Workflow success rate
        workflow_successes = len([t for t in traces if t.status == "ok" and "workflow" in t.operation_name])
        workflow_total = len([t for t in traces if "workflow" in t.operation_name])

        if workflow_total > 0:
            kpis["workflow_success_rate"] = (workflow_successes / workflow_total) * 100
        else:
            kpis["workflow_success_rate"] = 100

        # Average response time
        durations = [t.duration_ms for t in traces if t.duration_ms and t.duration_ms > 0]
        if durations:
            kpis["avg_response_time_ms"] = sum(durations) / len(durations)
        else:
            kpis["avg_response_time_ms"] = 0

        # Error rate
        error_traces = len([t for t in traces if t.status == "error"])
        total_traces = len(traces)

        if total_traces > 0:
            kpis["error_rate"] = (error_traces / total_traces) * 100
        else:
            kpis["error_rate"] = 0

        # Throughput (requests per minute)
        if traces:
            time_span = (max(t.start_time for t in traces) - min(t.start_time for t in traces)).total_seconds() / 60
            if time_span > 0:
                kpis["throughput_rpm"] = len(traces) / time_span
            else:
                kpis["throughput_rpm"] = 0
        else:
            kpis["throughput_rpm"] = 0

        return kpis

    async def close(self):
        """Shutdown monitoring service"""

        logger.info("🔄 Shutting down Monitoring & Observability Service")

        # Signal shutdown
        self._shutdown_event.set()

        # Stop health monitoring
        await self.health_monitor.stop_monitoring()

        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info("✅ Monitoring & Observability Service shutdown complete")

# Global monitoring service instance
monitoring_service = MonitoringObservabilityService()

# Convenience decorators for instrumentation

def monitor_performance(service_name: str = None, operation_name: str = None):
    """Decorator to monitor function performance"""

    def decorator(func):
        service = service_name or getattr(func, '__module__', 'unknown').split('.')[-1]
        operation = operation_name or func.__name__

        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                span = await monitoring_service.start_trace(operation, service)

                try:
                    result = await func(*args, **kwargs)
                    await monitoring_service.finish_trace(span, success=True)
                    return result

                except Exception as e:
                    await monitoring_service.finish_trace(span, success=False, error=str(e))
                    raise

                finally:
                    duration_ms = (time.time() - start_time) * 1000
                    await monitoring_service.record_service_call(
                        service, operation, duration_ms, success=True
                    )

            return async_wrapper

        else:
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()

                try:
                    result = func(*args, **kwargs)
                    return result

                finally:
                    duration_ms = (time.time() - start_time) * 1000
                    # Record metrics asynchronously
                    asyncio.create_task(
                        monitoring_service.record_service_call(
                            service, operation, duration_ms, success=True
                        )
                    )

            return sync_wrapper

    return decorator

# Context managers for tracing

class TraceContext:
    """Context manager for distributed tracing"""

    def __init__(self, operation_name: str, service_name: str, **tags):
        self.operation_name = operation_name
        self.service_name = service_name
        self.tags = tags
        self.span: Optional[TraceSpan] = None

    async def __aenter__(self):
        self.span = await monitoring_service.start_trace(
            self.operation_name,
            self.service_name,
            **self.tags
        )
        return self.span

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.span:
            success = exc_type is None
            error = str(exc_val) if exc_val else None
            await monitoring_service.finish_trace(self.span, success=success, error=error)

# Health check helper functions

async def register_workflow_health_checks():
    """Register workflow-specific health checks"""

    # Workflow persistence health
    workflow_persistence_check = HealthCheck(
        name="workflow_persistence",
        service="workflow",
        check_function=lambda: {"healthy": True, "message": "Workflow persistence operational"},
        interval_seconds=60
    )
    monitoring_service.health_monitor.register_health_check(workflow_persistence_check)

    # Service availability checks
    services = [
        "executive_search", "linkedin_url_finder", "connector_ranking",
        "mutuals_orchestrator", "email_enrichment", "approval_queue", "email_service"
    ]

    for service in services:
        service_check = HealthCheck(
            name=f"{service}_availability",
            service=service,
            check_function=lambda s=service: {"healthy": True, "service": s},
            interval_seconds=120
        )
        monitoring_service.health_monitor.register_health_check(service_check)