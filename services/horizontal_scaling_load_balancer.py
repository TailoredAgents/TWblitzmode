#!/usr/bin/env python3
"""
Horizontal Scaling and Load Balancing Infrastructure - September 2025
Enterprise-grade horizontal scaling with intelligent load balancing for AI workloads

Features:
- AI-aware load balancing with workload prediction
- Dynamic horizontal pod autoscaling
- Intelligent request routing based on agent capabilities
- Resource-aware scaling decisions
- Multi-tier load balancing (L4/L7)
- Circuit breaker integration for failed nodes
- Predictive scaling based on historical patterns
- Container orchestration integration (Kubernetes)

Based on 2025 enterprise scaling best practices
"""

import asyncio
import logging
import os
import uuid
import json
import time
import statistics
from typing import List, Dict, Any, Optional, Set, Callable, Tuple
from datetime import datetime, timedelta, timezone
from enum import Enum
from dataclasses import dataclass, field
from collections import deque, defaultdict

# Import enterprise services
from services.resilience_patterns import with_circuit_breaker, with_timeout
from services.monitoring_observability_service import monitoring_service

logger = logging.getLogger(__name__)

class LoadBalancingStrategy(Enum):
    """Load balancing strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    LEAST_RESPONSE_TIME = "least_response_time"
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
    IP_HASH = "ip_hash"
    AI_WORKLOAD_AWARE = "ai_workload_aware"
    CAPABILITY_BASED = "capability_based"
    PREDICTIVE = "predictive"

class ScalingDirection(Enum):
    """Scaling directions"""
    UP = "up"
    DOWN = "down"
    STABLE = "stable"

class ScalingTrigger(Enum):
    """Scaling triggers"""
    CPU_UTILIZATION = "cpu_utilization"
    MEMORY_UTILIZATION = "memory_utilization"
    REQUEST_RATE = "request_rate"
    RESPONSE_TIME = "response_time"
    QUEUE_LENGTH = "queue_length"
    AI_MODEL_LOAD = "ai_model_load"
    WORKFLOW_BACKLOG = "workflow_backlog"
    PREDICTIVE = "predictive"

@dataclass
class ServiceEndpoint:
    """Service endpoint for load balancing"""
    endpoint_id: str
    host: str
    port: int
    weight: int = 100
    max_connections: int = 1000
    current_connections: int = 0
    response_time_ms: float = 0.0
    health_status: str = "healthy"
    capabilities: List[str] = field(default_factory=list)
    ai_model_load: float = 0.0
    last_health_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def connection_utilization(self) -> float:
        """Get connection utilization percentage"""
        return (self.current_connections / self.max_connections) * 100 if self.max_connections > 0 else 0

    @property
    def is_healthy(self) -> bool:
        """Check if endpoint is healthy"""
        return (self.health_status == "healthy" and
                self.connection_utilization < 95 and
                (datetime.now(timezone.utc) - self.last_health_check) < timedelta(minutes=2))

@dataclass
class ScalingMetrics:
    """Metrics for scaling decisions"""
    timestamp: datetime
    cpu_utilization: float
    memory_utilization: float
    request_rate: float
    response_time_ms: float
    queue_length: int
    ai_model_load: float
    workflow_backlog: int
    active_connections: int
    error_rate: float

@dataclass
class ScalingPolicy:
    """Scaling policy configuration"""
    service_name: str
    min_replicas: int
    max_replicas: int
    target_cpu_utilization: float
    target_memory_utilization: float
    target_response_time_ms: float
    scale_up_threshold: float
    scale_down_threshold: float
    scale_up_cooldown_seconds: int
    scale_down_cooldown_seconds: int
    scaling_factor: float = 1.5
    predictive_scaling_enabled: bool = True
    ai_workload_aware: bool = True

@dataclass
class LoadBalancerPool:
    """Pool of endpoints for load balancing"""
    pool_id: str
    pool_name: str
    strategy: LoadBalancingStrategy
    endpoints: List[ServiceEndpoint]
    health_check_interval: int = 30
    health_check_timeout: int = 10
    circuit_breaker_enabled: bool = True
    sticky_sessions: bool = False
    session_affinity_timeout: int = 3600
    metadata: Dict[str, Any] = field(default_factory=dict)

class LoadBalancer:
    """
    Enterprise load balancer with AI-aware routing
    """

    def __init__(self, balancer_id: str = None):
        self.balancer_id = balancer_id or str(uuid.uuid4())
        self.pools: Dict[str, LoadBalancerPool] = {}
        self.routing_rules: Dict[str, Callable] = {}
        self.session_store: Dict[str, str] = {}  # session_id -> endpoint_id
        self.metrics_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

        # Performance tracking
        self.request_count = 0
        self.total_response_time = 0.0
        self.last_routing_times: deque = deque(maxlen=100)

        # Initialize routing strategies
        self._initialize_routing_strategies()

        logger.info(f"⚖️ Load Balancer {self.balancer_id} created")

    def _initialize_routing_strategies(self):
        """Initialize routing strategies"""
        self.routing_rules[LoadBalancingStrategy.ROUND_ROBIN] = self._round_robin_route
        self.routing_rules[LoadBalancingStrategy.LEAST_CONNECTIONS] = self._least_connections_route
        self.routing_rules[LoadBalancingStrategy.LEAST_RESPONSE_TIME] = self._least_response_time_route
        self.routing_rules[LoadBalancingStrategy.WEIGHTED_ROUND_ROBIN] = self._weighted_round_robin_route
        self.routing_rules[LoadBalancingStrategy.IP_HASH] = self._ip_hash_route
        self.routing_rules[LoadBalancingStrategy.AI_WORKLOAD_AWARE] = self._ai_workload_aware_route
        self.routing_rules[LoadBalancingStrategy.CAPABILITY_BASED] = self._capability_based_route
        self.routing_rules[LoadBalancingStrategy.PREDICTIVE] = self._predictive_route

    async def create_pool(self, pool: LoadBalancerPool) -> bool:
        """Create a new load balancer pool"""
        try:
            self.pools[pool.pool_id] = pool

            # Start health checking for this pool
            asyncio.create_task(self._health_check_loop(pool.pool_id))

            logger.info(f"✅ Created load balancer pool {pool.pool_id} with {len(pool.endpoints)} endpoints")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to create pool {pool.pool_id}: {e}")
            return False

    async def add_endpoint(self, pool_id: str, endpoint: ServiceEndpoint) -> bool:
        """Add an endpoint to a pool"""
        try:
            if pool_id not in self.pools:
                logger.error(f"Pool {pool_id} not found")
                return False

            pool = self.pools[pool_id]
            pool.endpoints.append(endpoint)

            logger.info(f"✅ Added endpoint {endpoint.endpoint_id} to pool {pool_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to add endpoint to pool {pool_id}: {e}")
            return False

    async def remove_endpoint(self, pool_id: str, endpoint_id: str) -> bool:
        """Remove an endpoint from a pool"""
        try:
            if pool_id not in self.pools:
                return False

            pool = self.pools[pool_id]
            pool.endpoints = [ep for ep in pool.endpoints if ep.endpoint_id != endpoint_id]

            logger.info(f"✅ Removed endpoint {endpoint_id} from pool {pool_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to remove endpoint from pool {pool_id}: {e}")
            return False

    @with_circuit_breaker(name="load_balancer_routing", failure_threshold=5, timeout=30.0)
    async def route_request(self, pool_id: str, request_data: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        """Route a request to the best available endpoint"""
        try:
            start_time = time.time()

            if pool_id not in self.pools:
                logger.error(f"Pool {pool_id} not found")
                return None

            pool = self.pools[pool_id]

            # Filter healthy endpoints
            healthy_endpoints = [ep for ep in pool.endpoints if ep.is_healthy]

            if not healthy_endpoints:
                logger.warning(f"No healthy endpoints available in pool {pool_id}")
                return None

            # Apply routing strategy
            if pool.strategy in self.routing_rules:
                router = self.routing_rules[pool.strategy]
                selected_endpoint = await router(healthy_endpoints, request_data)
            else:
                # Default to round-robin
                selected_endpoint = await self._round_robin_route(healthy_endpoints, request_data)

            if selected_endpoint:
                # Update connection count
                selected_endpoint.current_connections += 1

                # Handle session affinity
                if pool.sticky_sessions:
                    session_id = request_data.get("session_id")
                    if session_id:
                        self.session_store[session_id] = selected_endpoint.endpoint_id

                # Record routing time
                routing_time = (time.time() - start_time) * 1000
                self.last_routing_times.append(routing_time)

                # Update metrics
                self.request_count += 1

                logger.debug(f"🎯 Routed request to {selected_endpoint.endpoint_id} in {routing_time:.2f}ms")

            return selected_endpoint

        except Exception as e:
            logger.error(f"❌ Request routing failed for pool {pool_id}: {e}")
            return None

    async def release_connection(self, pool_id: str, endpoint_id: str, response_time_ms: float = None):
        """Release a connection and update metrics"""
        try:
            if pool_id not in self.pools:
                return

            pool = self.pools[pool_id]

            for endpoint in pool.endpoints:
                if endpoint.endpoint_id == endpoint_id:
                    endpoint.current_connections = max(0, endpoint.current_connections - 1)

                    if response_time_ms is not None:
                        # Update response time with exponential moving average
                        alpha = 0.1
                        endpoint.response_time_ms = (alpha * response_time_ms +
                                                   (1 - alpha) * endpoint.response_time_ms)

                        self.total_response_time += response_time_ms

                    break

        except Exception as e:
            logger.error(f"❌ Failed to release connection: {e}")

    # Routing Strategy Implementations

    async def _round_robin_route(self, endpoints: List[ServiceEndpoint], request_data: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        """Round-robin routing strategy"""
        if not endpoints:
            return None

        # Simple round-robin based on request count
        index = self.request_count % len(endpoints)
        return endpoints[index]

    async def _least_connections_route(self, endpoints: List[ServiceEndpoint], request_data: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        """Least connections routing strategy"""
        if not endpoints:
            return None

        return min(endpoints, key=lambda ep: ep.current_connections)

    async def _least_response_time_route(self, endpoints: List[ServiceEndpoint], request_data: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        """Least response time routing strategy"""
        if not endpoints:
            return None

        return min(endpoints, key=lambda ep: ep.response_time_ms)

    async def _weighted_round_robin_route(self, endpoints: List[ServiceEndpoint], request_data: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        """Weighted round-robin routing strategy"""
        if not endpoints:
            return None

        # Calculate total weight
        total_weight = sum(ep.weight for ep in endpoints)
        if total_weight == 0:
            return endpoints[0]

        # Use request count for deterministic selection
        target = self.request_count % total_weight
        current_weight = 0

        for endpoint in endpoints:
            current_weight += endpoint.weight
            if current_weight > target:
                return endpoint

        return endpoints[0]

    async def _ip_hash_route(self, endpoints: List[ServiceEndpoint], request_data: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        """IP hash routing strategy for session persistence"""
        if not endpoints:
            return None

        client_ip = request_data.get("client_ip", "127.0.0.1")
        hash_value = hash(client_ip)
        index = hash_value % len(endpoints)

        return endpoints[index]

    async def _ai_workload_aware_route(self, endpoints: List[ServiceEndpoint], request_data: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        """AI workload-aware routing strategy"""
        if not endpoints:
            return None

        # Score endpoints based on AI model load, connections, and response time
        def score_endpoint(ep: ServiceEndpoint) -> float:
            load_score = 1.0 - (ep.ai_model_load / 100.0)
            connection_score = 1.0 - (ep.connection_utilization / 100.0)
            response_score = 1.0 / (1.0 + ep.response_time_ms / 1000.0)

            # Weighted combination
            return 0.4 * load_score + 0.3 * connection_score + 0.3 * response_score

        return max(endpoints, key=score_endpoint)

    async def _capability_based_route(self, endpoints: List[ServiceEndpoint], request_data: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        """Capability-based routing strategy"""
        if not endpoints:
            return None

        required_capability = request_data.get("required_capability")

        if required_capability:
            # Filter endpoints with required capability
            capable_endpoints = [ep for ep in endpoints if required_capability in ep.capabilities]

            if capable_endpoints:
                endpoints = capable_endpoints

        # Fall back to least connections among capable endpoints
        return await self._least_connections_route(endpoints, request_data)

    async def _predictive_route(self, endpoints: List[ServiceEndpoint], request_data: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        """Predictive routing strategy using historical data"""
        if not endpoints:
            return None

        # Simple predictive model based on recent performance
        def predict_performance(ep: ServiceEndpoint) -> float:
            # Predict future response time based on current load trends
            recent_metrics = self.metrics_history.get(ep.endpoint_id, deque())

            if len(recent_metrics) < 5:
                return ep.response_time_ms

            # Calculate trend
            recent_times = [m["response_time"] for m in list(recent_metrics)[-5:]]
            if len(recent_times) > 1:
                trend = (recent_times[-1] - recent_times[0]) / len(recent_times)
                predicted_time = ep.response_time_ms + trend
            else:
                predicted_time = ep.response_time_ms

            return max(0, predicted_time)

        return min(endpoints, key=predict_performance)

    async def _health_check_loop(self, pool_id: str):
        """Health check loop for a specific pool"""
        while pool_id in self.pools:
            try:
                pool = self.pools[pool_id]

                for endpoint in pool.endpoints:
                    await self._check_endpoint_health(endpoint)

                await asyncio.sleep(pool.health_check_interval)

            except Exception as e:
                logger.error(f"❌ Health check error for pool {pool_id}: {e}")
                await asyncio.sleep(60)

    @with_timeout(timeout=10.0)
    async def _check_endpoint_health(self, endpoint: ServiceEndpoint):
        """Check health of a specific endpoint"""
        try:
            # Simulate health check (in real implementation, would make HTTP/gRPC call)
            # For now, mark as healthy if not overloaded
            if endpoint.connection_utilization < 95 and endpoint.ai_model_load < 90:
                endpoint.health_status = "healthy"
            else:
                endpoint.health_status = "degraded"

            endpoint.last_health_check = datetime.now(timezone.utc)

            # Record metrics
            metrics = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "connections": endpoint.current_connections,
                "response_time": endpoint.response_time_ms,
                "ai_model_load": endpoint.ai_model_load,
                "health_status": endpoint.health_status
            }

            self.metrics_history[endpoint.endpoint_id].append(metrics)

        except Exception as e:
            logger.error(f"❌ Health check failed for {endpoint.endpoint_id}: {e}")
            endpoint.health_status = "unhealthy"

    async def get_pool_status(self, pool_id: str) -> Dict[str, Any]:
        """Get status of a specific pool"""
        if pool_id not in self.pools:
            return {"error": "Pool not found"}

        pool = self.pools[pool_id]
        healthy_endpoints = [ep for ep in pool.endpoints if ep.is_healthy]

        return {
            "pool_id": pool_id,
            "pool_name": pool.pool_name,
            "strategy": pool.strategy.value,
            "total_endpoints": len(pool.endpoints),
            "healthy_endpoints": len(healthy_endpoints),
            "total_connections": sum(ep.current_connections for ep in pool.endpoints),
            "average_response_time": statistics.mean([ep.response_time_ms for ep in pool.endpoints]) if pool.endpoints else 0,
            "endpoints": [
                {
                    "endpoint_id": ep.endpoint_id,
                    "host": ep.host,
                    "port": ep.port,
                    "health_status": ep.health_status,
                    "connections": ep.current_connections,
                    "connection_utilization": ep.connection_utilization,
                    "response_time_ms": ep.response_time_ms,
                    "ai_model_load": ep.ai_model_load,
                    "capabilities": ep.capabilities
                }
                for ep in pool.endpoints
            ]
        }

class HorizontalScaler:
    """
    Horizontal Pod Autoscaler with AI workload awareness
    """

    def __init__(self, scaler_id: str = None):
        self.scaler_id = scaler_id or str(uuid.uuid4())
        self.scaling_policies: Dict[str, ScalingPolicy] = {}
        self.scaling_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.last_scaling_actions: Dict[str, datetime] = {}
        self.metrics_collectors: Dict[str, Callable] = {}

        # Predictive scaling
        self.prediction_models: Dict[str, Any] = {}
        self.prediction_horizon_minutes = 15

        logger.info(f"📈 Horizontal Scaler {self.scaler_id} created")

    async def register_service(self, policy: ScalingPolicy) -> bool:
        """Register a service for horizontal scaling"""
        try:
            self.scaling_policies[policy.service_name] = policy

            # Start monitoring loop for this service
            asyncio.create_task(self._scaling_monitor_loop(policy.service_name))

            logger.info(f"✅ Registered service {policy.service_name} for horizontal scaling")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to register service {policy.service_name}: {e}")
            return False

    async def _scaling_monitor_loop(self, service_name: str):
        """Monitoring loop for a specific service"""
        while service_name in self.scaling_policies:
            try:
                policy = self.scaling_policies[service_name]

                # Collect current metrics
                metrics = await self._collect_service_metrics(service_name)

                if metrics:
                    # Record metrics
                    self.scaling_history[service_name].append(metrics)

                    # Make scaling decision
                    scaling_decision = await self._make_scaling_decision(service_name, metrics, policy)

                    if scaling_decision != ScalingDirection.STABLE:
                        await self._execute_scaling_action(service_name, scaling_decision, policy)

                await asyncio.sleep(30)  # Check every 30 seconds

            except Exception as e:
                logger.error(f"❌ Scaling monitor error for {service_name}: {e}")
                await asyncio.sleep(60)

    async def _collect_service_metrics(self, service_name: str) -> Optional[ScalingMetrics]:
        """Collect metrics for a service"""
        try:
            # In real implementation, would collect from Kubernetes metrics API, Prometheus, etc.
            # For now, simulate metrics
            current_time = datetime.now(timezone.utc)

            # Simulate varying load patterns
            time_factor = (current_time.hour + current_time.minute / 60.0) / 24.0
            base_load = 50 + 30 * abs(time_factor - 0.5) * 2  # Higher load during business hours

            metrics = ScalingMetrics(
                timestamp=current_time,
                cpu_utilization=base_load + (hash(service_name) % 20),
                memory_utilization=base_load + (hash(service_name) % 15),
                request_rate=base_load * 2,
                response_time_ms=100 + (base_load - 50) * 2,
                queue_length=int(max(0, base_load - 60)),
                ai_model_load=base_load + (hash(service_name) % 10),
                workflow_backlog=int(max(0, (base_load - 70) * 2)),
                active_connections=int(base_load * 10),
                error_rate=max(0, (base_load - 80) * 0.1)
            )

            return metrics

        except Exception as e:
            logger.error(f"❌ Failed to collect metrics for {service_name}: {e}")
            return None

    async def _make_scaling_decision(self, service_name: str, metrics: ScalingMetrics,
                                   policy: ScalingPolicy) -> ScalingDirection:
        """Make scaling decision based on metrics and policy"""
        try:
            # Check cooldown periods
            last_action = self.last_scaling_actions.get(service_name)
            if last_action:
                time_since_last = (datetime.now(timezone.utc) - last_action).total_seconds()

                # Use different cooldowns for scale up vs scale down
                min_cooldown = min(policy.scale_up_cooldown_seconds, policy.scale_down_cooldown_seconds)
                if time_since_last < min_cooldown:
                    return ScalingDirection.STABLE

            # Scaling triggers
            scale_up_triggers = []
            scale_down_triggers = []

            # CPU utilization
            if metrics.cpu_utilization > policy.target_cpu_utilization + policy.scale_up_threshold:
                scale_up_triggers.append(ScalingTrigger.CPU_UTILIZATION)
            elif metrics.cpu_utilization < policy.target_cpu_utilization - policy.scale_down_threshold:
                scale_down_triggers.append(ScalingTrigger.CPU_UTILIZATION)

            # Memory utilization
            if metrics.memory_utilization > policy.target_memory_utilization + policy.scale_up_threshold:
                scale_up_triggers.append(ScalingTrigger.MEMORY_UTILIZATION)
            elif metrics.memory_utilization < policy.target_memory_utilization - policy.scale_down_threshold:
                scale_down_triggers.append(ScalingTrigger.MEMORY_UTILIZATION)

            # Response time
            if metrics.response_time_ms > policy.target_response_time_ms * 1.5:
                scale_up_triggers.append(ScalingTrigger.RESPONSE_TIME)

            # AI-specific triggers
            if policy.ai_workload_aware:
                if metrics.ai_model_load > 80:
                    scale_up_triggers.append(ScalingTrigger.AI_MODEL_LOAD)

                if metrics.workflow_backlog > 10:
                    scale_up_triggers.append(ScalingTrigger.WORKFLOW_BACKLOG)

            # Predictive scaling
            if policy.predictive_scaling_enabled:
                predicted_load = await self._predict_future_load(service_name)
                if predicted_load > policy.target_cpu_utilization + policy.scale_up_threshold:
                    scale_up_triggers.append(ScalingTrigger.PREDICTIVE)

            # Make decision based on triggers
            if scale_up_triggers:
                logger.info(f"📈 Scale up triggered for {service_name}: {[t.value for t in scale_up_triggers]}")
                return ScalingDirection.UP
            elif scale_down_triggers and not scale_up_triggers:
                logger.info(f"📉 Scale down triggered for {service_name}: {[t.value for t in scale_down_triggers]}")
                return ScalingDirection.DOWN
            else:
                return ScalingDirection.STABLE

        except Exception as e:
            logger.error(f"❌ Scaling decision error for {service_name}: {e}")
            return ScalingDirection.STABLE

    async def _predict_future_load(self, service_name: str) -> float:
        """Predict future load using simple time series analysis"""
        try:
            history = list(self.scaling_history[service_name])

            if len(history) < 10:
                return 0.0

            # Simple linear regression on CPU utilization
            recent_metrics = history[-10:]
            cpu_values = [m.cpu_utilization for m in recent_metrics]

            # Calculate trend
            n = len(cpu_values)
            sum_x = sum(range(n))
            sum_y = sum(cpu_values)
            sum_xy = sum(i * cpu_values[i] for i in range(n))
            sum_x2 = sum(i * i for i in range(n))

            # Linear regression slope
            slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)

            # Predict 15 minutes ahead (assuming 30-second intervals)
            prediction_steps = (self.prediction_horizon_minutes * 60) // 30
            current_value = cpu_values[-1]
            predicted_value = current_value + slope * prediction_steps

            return max(0, predicted_value)

        except Exception as e:
            logger.error(f"❌ Load prediction error for {service_name}: {e}")
            return 0.0

    async def _execute_scaling_action(self, service_name: str, direction: ScalingDirection,
                                    policy: ScalingPolicy):
        """Execute scaling action"""
        try:
            # Get current replica count (simulated)
            current_replicas = await self._get_current_replica_count(service_name)

            if direction == ScalingDirection.UP:
                new_replicas = min(policy.max_replicas,
                                 int(current_replicas * policy.scaling_factor))
                cooldown = policy.scale_up_cooldown_seconds
            else:  # ScalingDirection.DOWN
                new_replicas = max(policy.min_replicas,
                                 int(current_replicas / policy.scaling_factor))
                cooldown = policy.scale_down_cooldown_seconds

            if new_replicas != current_replicas:
                # Execute scaling (in real implementation, would use Kubernetes API)
                success = await self._scale_service(service_name, new_replicas)

                if success:
                    self.last_scaling_actions[service_name] = datetime.now(timezone.utc)

                    logger.info(f"✅ Scaled {service_name} from {current_replicas} to {new_replicas} replicas")

                    # Record scaling event
                    await monitoring_service.record_metric(
                        metric_name="horizontal_scaling_event",
                        value=new_replicas - current_replicas,
                        tags={
                            "service_name": service_name,
                            "direction": direction.value,
                            "old_replicas": current_replicas,
                            "new_replicas": new_replicas
                        }
                    )

        except Exception as e:
            logger.error(f"❌ Scaling action failed for {service_name}: {e}")

    async def _get_current_replica_count(self, service_name: str) -> int:
        """Get current replica count for a service"""
        # Simulate current replica count
        return 3

    async def _scale_service(self, service_name: str, target_replicas: int) -> bool:
        """Scale a service to target replica count"""
        try:
            # Simulate scaling operation
            logger.info(f"🚀 Scaling {service_name} to {target_replicas} replicas")

            # In real implementation, would use Kubernetes API:
            # kubectl scale deployment {service_name} --replicas={target_replicas}

            return True

        except Exception as e:
            logger.error(f"❌ Failed to scale {service_name}: {e}")
            return False

    async def get_scaling_status(self) -> Dict[str, Any]:
        """Get comprehensive scaling status"""
        try:
            status = {
                "scaler_id": self.scaler_id,
                "services": {}
            }

            for service_name, policy in self.scaling_policies.items():
                recent_metrics = list(self.scaling_history[service_name])[-1] if self.scaling_history[service_name] else None
                last_action = self.last_scaling_actions.get(service_name)

                status["services"][service_name] = {
                    "policy": {
                        "min_replicas": policy.min_replicas,
                        "max_replicas": policy.max_replicas,
                        "target_cpu": policy.target_cpu_utilization,
                        "target_memory": policy.target_memory_utilization,
                        "predictive_enabled": policy.predictive_scaling_enabled
                    },
                    "current_metrics": {
                        "cpu_utilization": recent_metrics.cpu_utilization if recent_metrics else 0,
                        "memory_utilization": recent_metrics.memory_utilization if recent_metrics else 0,
                        "response_time_ms": recent_metrics.response_time_ms if recent_metrics else 0,
                        "ai_model_load": recent_metrics.ai_model_load if recent_metrics else 0
                    } if recent_metrics else {},
                    "last_scaling_action": last_action.isoformat() if last_action else None,
                    "metrics_history_count": len(self.scaling_history[service_name])
                }

            return status

        except Exception as e:
            logger.error(f"❌ Failed to get scaling status: {e}")
            return {"error": str(e)}

class HorizontalScalingLoadBalancer:
    """
    Combined horizontal scaling and load balancing system
    """

    def __init__(self):
        self.load_balancer = LoadBalancer()
        self.scaler = HorizontalScaler()
        self.integrated_monitoring = True

        logger.info("🏗️ Horizontal Scaling Load Balancer system initialized")

    async def register_service(self, service_name: str, scaling_policy: ScalingPolicy,
                             load_balancer_pool: LoadBalancerPool) -> bool:
        """Register a service for both scaling and load balancing"""
        try:
            # Register with scaler
            scaling_success = await self.scaler.register_service(scaling_policy)

            # Register with load balancer
            lb_success = await self.load_balancer.create_pool(load_balancer_pool)

            if scaling_success and lb_success:
                logger.info(f"✅ Successfully registered {service_name} for scaling and load balancing")
                return True
            else:
                logger.error(f"❌ Failed to register {service_name}")
                return False

        except Exception as e:
            logger.error(f"❌ Service registration failed for {service_name}: {e}")
            return False

    async def route_request(self, service_name: str, request_data: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        """Route a request through the load balancer"""
        return await self.load_balancer.route_request(service_name, request_data)

    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        try:
            lb_pools = {pool_id: await self.load_balancer.get_pool_status(pool_id)
                       for pool_id in self.load_balancer.pools.keys()}

            scaling_status = await self.scaler.get_scaling_status()

            return {
                "load_balancer": {
                    "balancer_id": self.load_balancer.balancer_id,
                    "total_requests": self.load_balancer.request_count,
                    "average_routing_time_ms": statistics.mean(self.load_balancer.last_routing_times) if self.load_balancer.last_routing_times else 0,
                    "pools": lb_pools
                },
                "horizontal_scaler": scaling_status,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"❌ Failed to get system status: {e}")
            return {"error": str(e)}

# Global instance
horizontal_scaling_lb = HorizontalScalingLoadBalancer()

# Test function
async def test_horizontal_scaling_load_balancer():
    """Test the horizontal scaling and load balancing system"""

    print("🧪 HORIZONTAL SCALING LOAD BALANCER TEST")
    print("=" * 60)

    # Create scaling policy
    scaling_policy = ScalingPolicy(
        service_name="enterprise_orchestrator",
        min_replicas=3,
        max_replicas=20,
        target_cpu_utilization=70.0,
        target_memory_utilization=80.0,
        target_response_time_ms=150.0,
        scale_up_threshold=10.0,
        scale_down_threshold=15.0,
        scale_up_cooldown_seconds=300,
        scale_down_cooldown_seconds=600,
        scaling_factor=1.5,
        predictive_scaling_enabled=True,
        ai_workload_aware=True
    )

    # Create endpoints
    endpoints = [
        ServiceEndpoint(
            endpoint_id="orchestrator_1",
            host="orchestrator-1.vouchlinkai.svc.cluster.local",
            port=8080,
            weight=100,
            capabilities=["executive_search", "email_enrichment"]
        ),
        ServiceEndpoint(
            endpoint_id="orchestrator_2",
            host="orchestrator-2.vouchlinkai.svc.cluster.local",
            port=8080,
            weight=100,
            capabilities=["linkedin_discovery", "mutual_connections"]
        ),
        ServiceEndpoint(
            endpoint_id="orchestrator_3",
            host="orchestrator-3.vouchlinkai.svc.cluster.local",
            port=8080,
            weight=150,  # Higher weight
            capabilities=["executive_search", "linkedin_discovery", "email_enrichment"]
        )
    ]

    # Create load balancer pool
    lb_pool = LoadBalancerPool(
        pool_id="enterprise_orchestrator",
        pool_name="Enterprise Orchestrator Pool",
        strategy=LoadBalancingStrategy.AI_WORKLOAD_AWARE,
        endpoints=endpoints,
        health_check_interval=30,
        circuit_breaker_enabled=True
    )

    # Register service
    success = await horizontal_scaling_lb.register_service(
        service_name="enterprise_orchestrator",
        scaling_policy=scaling_policy,
        load_balancer_pool=lb_pool
    )

    print(f"✅ Service registration: {'Success' if success else 'Failed'}")

    # Test load balancing
    print(f"\n🎯 Testing load balancing...")

    for i in range(10):
        request_data = {
            "client_ip": f"192.168.1.{100 + i}",
            "required_capability": "executive_search",
            "session_id": f"session_{i % 3}"
        }

        endpoint = await horizontal_scaling_lb.route_request("enterprise_orchestrator", request_data)

        if endpoint:
            print(f"  Request {i+1}: Routed to {endpoint.endpoint_id}")

            # Simulate request completion
            await horizontal_scaling_lb.load_balancer.release_connection(
                "enterprise_orchestrator",
                endpoint.endpoint_id,
                response_time_ms=100 + (i * 10)
            )

    # Get system status
    print(f"\n📊 System Status:")
    status = await horizontal_scaling_lb.get_system_status()

    print(f"  Load Balancer:")
    print(f"    Total Requests: {status['load_balancer']['total_requests']}")
    print(f"    Average Routing Time: {status['load_balancer']['average_routing_time_ms']:.2f}ms")

    print(f"  Horizontal Scaler:")
    for service_name, service_data in status['horizontal_scaler']['services'].items():
        print(f"    {service_name}:")
        print(f"      CPU: {service_data['current_metrics'].get('cpu_utilization', 0):.1f}%")
        print(f"      Memory: {service_data['current_metrics'].get('memory_utilization', 0):.1f}%")
        print(f"      AI Model Load: {service_data['current_metrics'].get('ai_model_load', 0):.1f}%")

    print(f"\n🏗️ Horizontal Scaling Load Balancer test completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_horizontal_scaling_load_balancer())