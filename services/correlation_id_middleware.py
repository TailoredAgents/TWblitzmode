"""
Correlation ID Middleware and Distributed Tracing
Provides request tracing across microservices and message queues for the Tailored Agents AI platform
"""

import asyncio
import json
import logging
import uuid
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Callable, Iterator
from contextvars import ContextVar, Token
from dataclasses import dataclass, asdict
from contextlib import contextmanager

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Context variables for storing correlation data throughout request lifecycle
correlation_id_context: ContextVar[str] = ContextVar('correlation_id', default=None)
trace_context: ContextVar[Dict[str, Any]] = ContextVar('trace_context', default=None)

logger = logging.getLogger(__name__)

@dataclass
class TraceSpan:
    """Represents a trace span for distributed tracing"""
    span_id: str
    parent_span_id: Optional[str]
    operation_name: str
    service_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    status: str = "started"  # started, completed, failed
    tags: Dict[str, Any] = None
    logs: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = {}
        if self.logs is None:
            self.logs = []

@dataclass
class TraceContext:
    """Context for distributed tracing"""
    trace_id: str
    correlation_id: str
    root_span: TraceSpan
    spans: List[TraceSpan]
    service_name: str
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    organization_id: Optional[str] = None

class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for correlation ID and distributed tracing"""

    def __init__(self, app, service_name: str = "tailored_agents_api"):
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with correlation ID and tracing"""

        # Extract or generate correlation ID
        correlation_id = self._extract_correlation_id(request)

        # Extract trace ID (or use correlation ID if not present)
        trace_id = request.headers.get("x-trace-id", correlation_id)

        # Create trace context
        trace_context = self._create_trace_context(
            trace_id=trace_id,
            correlation_id=correlation_id,
            request=request
        )

        # Set context variables
        correlation_id_context.set(correlation_id)
        trace_context_var.set(trace_context)

        # Start root span
        root_span = self._start_span(
            operation_name=f"{request.method} {request.url.path}",
            service_name=self.service_name
        )

        # Add request metadata to span
        root_span.tags.update({
            "http.method": request.method,
            "http.url": str(request.url),
            "http.scheme": request.url.scheme,
            "http.user_agent": request.headers.get("user-agent", ""),
            "correlation_id": correlation_id,
            "trace_id": trace_id
        })

        start_time = time.time()

        try:
            # Process request
            response = await call_next(request)

            # Complete span successfully
            self._finish_span(root_span, status="completed")
            root_span.tags["http.status_code"] = response.status_code

            # Add correlation headers to response
            response.headers["x-correlation-id"] = correlation_id
            response.headers["x-trace-id"] = trace_id

            # Log successful request
            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                f"Request completed: {request.method} {request.url.path} "
                f"- Status: {response.status_code} - Duration: {duration_ms:.2f}ms "
                f"- Correlation ID: {correlation_id}"
            )

            return response

        except Exception as e:
            # Complete span with error
            self._finish_span(root_span, status="failed")
            root_span.tags["error"] = True
            root_span.tags["error.message"] = str(e)
            root_span.logs.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "error",
                "message": str(e)
            })

            # Log error
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                f"Request failed: {request.method} {request.url.path} "
                f"- Error: {str(e)} - Duration: {duration_ms:.2f}ms "
                f"- Correlation ID: {correlation_id}"
            )

            raise

        finally:
            # Clear context variables
            correlation_id_context.set(None)
            trace_context_var.set(None)

    def _extract_correlation_id(self, request: Request) -> str:
        """Extract correlation ID from request headers or generate new one"""

        # Check for existing correlation ID in various header formats
        correlation_id = (
            request.headers.get("x-correlation-id") or
            request.headers.get("x-request-id") or
            request.headers.get("correlation-id") or
            request.headers.get("request-id")
        )

        if not correlation_id:
            # Generate new correlation ID
            correlation_id = f"req_{uuid.uuid4().hex[:16]}"

        return correlation_id

    def _create_trace_context(
        self,
        trace_id: str,
        correlation_id: str,
        request: Request
    ) -> TraceContext:
        """Create trace context for the request"""

        # Extract user/tenant info from request if available
        user_id = getattr(request.state, 'user_id', None)
        tenant_id = getattr(request.state, 'tenant_id', None)
        organization_id = getattr(request.state, 'organization_id', None)

        root_span = TraceSpan(
            span_id=f"span_{uuid.uuid4().hex[:16]}",
            parent_span_id=None,
            operation_name="http_request",
            service_name=self.service_name,
            start_time=datetime.now(timezone.utc)
        )

        return TraceContext(
            trace_id=trace_id,
            correlation_id=correlation_id,
            root_span=root_span,
            spans=[root_span],
            service_name=self.service_name,
            user_id=str(user_id) if user_id else None,
            tenant_id=str(tenant_id) if tenant_id else None,
            organization_id=str(organization_id) if organization_id else None
        )

    def _start_span(self, operation_name: str, service_name: str) -> TraceSpan:
        """Start a new trace span"""
        span = TraceSpan(
            span_id=f"span_{uuid.uuid4().hex[:16]}",
            parent_span_id=None,  # Will be set if needed
            operation_name=operation_name,
            service_name=service_name,
            start_time=datetime.now(timezone.utc)
        )
        return span

    def _finish_span(self, span: TraceSpan, status: str = "completed") -> None:
        """Finish a trace span"""
        span.end_time = datetime.now(timezone.utc)
        span.status = status

        if span.start_time and span.end_time:
            duration = (span.end_time - span.start_time).total_seconds() * 1000
            span.duration_ms = round(duration, 2)

# Global context variable for trace context
trace_context_var: ContextVar[TraceContext] = ContextVar('trace_context', default=None)

class DistributedTracer:
    """Distributed tracing utility for services and message queues"""

    def __init__(self, service_name: str):
        self.service_name = service_name

    def start_span(
        self,
        operation_name: str,
        parent_span_id: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None
    ) -> TraceSpan:
        """Start a new trace span"""

        span = TraceSpan(
            span_id=f"span_{uuid.uuid4().hex[:16]}",
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            service_name=self.service_name,
            start_time=datetime.now(timezone.utc),
            tags=tags or {}
        )

        # Add to current trace context if available
        trace_context = trace_context_var.get()
        if trace_context:
            trace_context.spans.append(span)
            span.tags.update({
                "trace_id": trace_context.trace_id,
                "correlation_id": trace_context.correlation_id
            })

        return span

    def finish_span(
        self,
        span: TraceSpan,
        status: str = "completed",
        error: Optional[Exception] = None
    ) -> None:
        """Finish a trace span"""

        span.end_time = datetime.now(timezone.utc)
        span.status = status

        if span.start_time and span.end_time:
            duration = (span.end_time - span.start_time).total_seconds() * 1000
            span.duration_ms = round(duration, 2)

        if error:
            span.tags["error"] = True
            span.tags["error.message"] = str(error)
            span.logs.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "error",
                "message": str(error)
            })

        # Log span completion
        logger.debug(
            f"Span completed: {span.operation_name} "
            f"- Duration: {span.duration_ms}ms "
            f"- Status: {span.status} "
            f"- Service: {span.service_name}"
        )

    def add_span_tag(self, span: TraceSpan, key: str, value: Any) -> None:
        """Add tag to span"""
        span.tags[key] = value

    def add_span_log(self, span: TraceSpan, message: str, level: str = "info") -> None:
        """Add log entry to span"""
        span.logs.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message
        })

    def get_trace_headers(self) -> Dict[str, str]:
        """Get headers for propagating trace context to downstream services"""

        trace_context = trace_context_var.get()
        correlation_id = correlation_id_context.get()

        headers = {}

        if correlation_id:
            headers["x-correlation-id"] = correlation_id

        if trace_context:
            headers["x-trace-id"] = trace_context.trace_id

            # Add current span ID as parent for downstream services
            if trace_context.spans:
                current_span = trace_context.spans[-1]
                headers["x-parent-span-id"] = current_span.span_id

        return headers

# Global tracer instances for different services
api_tracer = DistributedTracer("tailored_agents_api")
workflow_tracer = DistributedTracer("workflow_service")
message_queue_tracer = DistributedTracer("message_queue")
ai_agents_tracer = DistributedTracer("ai_agents")

# Utility functions for easy access
def get_correlation_id() -> Optional[str]:
    """Get current correlation ID"""
    return correlation_id_context.get()

def get_trace_context() -> Optional[TraceContext]:
    """Get current trace context"""
    return trace_context_var.get()

def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID in context"""
    correlation_id_context.set(correlation_id)


def ensure_correlation_id(prefix: str = "corr") -> str:
    """Ensure a correlation ID exists in context and return it."""
    current = correlation_id_context.get()
    if current:
        return current

    new_id = f"{prefix}_{uuid.uuid4().hex[:16]}"
    correlation_id_context.set(new_id)
    return new_id


@contextmanager
def correlation_scope(correlation_id: Optional[str] = None) -> Iterator[str]:
    """Context manager that sets a correlation ID for the enclosed block."""
    if correlation_id is None:
        correlation_id = f"corr_{uuid.uuid4().hex[:16]}"

    token: Token = correlation_id_context.set(correlation_id)
    try:
        yield correlation_id
    finally:
        correlation_id_context.reset(token)

def create_child_span(
    operation_name: str,
    service_name: str,
    tags: Optional[Dict[str, Any]] = None
) -> TraceSpan:
    """Create a child span from the current context"""

    tracer = DistributedTracer(service_name)

    # Get parent span ID from current context
    trace_context = trace_context_var.get()
    parent_span_id = None

    if trace_context and trace_context.spans:
        parent_span_id = trace_context.spans[-1].span_id

    return tracer.start_span(
        operation_name=operation_name,
        parent_span_id=parent_span_id,
        tags=tags
    )

def trace_async_operation(operation_name: str, service_name: str):
    """Decorator for tracing async operations"""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            span = create_child_span(operation_name, service_name)

            try:
                result = await func(*args, **kwargs)
                api_tracer.finish_span(span, status="completed")
                return result
            except Exception as e:
                api_tracer.finish_span(span, status="failed", error=e)
                raise

        return wrapper
    return decorator

def trace_sync_operation(operation_name: str, service_name: str):
    """Decorator for tracing sync operations"""

    def decorator(func):
        def wrapper(*args, **kwargs):
            span = create_child_span(operation_name, service_name)

            try:
                result = func(*args, **kwargs)
                api_tracer.finish_span(span, status="completed")
                return result
            except Exception as e:
                api_tracer.finish_span(span, status="failed", error=e)
                raise

        return wrapper
    return decorator

# Message queue tracing utilities
def add_tracing_to_message(message_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Add tracing information to message queue payload"""

    correlation_id = get_correlation_id()
    trace_context = get_trace_context()

    if correlation_id:
        message_payload["_correlation_id"] = correlation_id

    if trace_context:
        message_payload["_trace_id"] = trace_context.trace_id

        # Add current span as parent for message processing
        if trace_context.spans:
            current_span = trace_context.spans[-1]
            message_payload["_parent_span_id"] = current_span.span_id

    return message_payload

def extract_tracing_from_message(message_payload: Dict[str, Any]) -> None:
    """Extract and set tracing context from message queue payload"""

    correlation_id = message_payload.get("_correlation_id")
    trace_id = message_payload.get("_trace_id")
    parent_span_id = message_payload.get("_parent_span_id")

    if correlation_id:
        set_correlation_id(correlation_id)

    if trace_id:
        # Create a minimal trace context for message processing
        root_span = TraceSpan(
            span_id=parent_span_id or f"span_{uuid.uuid4().hex[:16]}",
            parent_span_id=None,
            operation_name="message_processing",
            service_name="message_queue",
            start_time=datetime.now(timezone.utc)
        )

        trace_context = TraceContext(
            trace_id=trace_id,
            correlation_id=correlation_id or trace_id,
            root_span=root_span,
            spans=[root_span],
            service_name="message_queue"
        )

        trace_context_var.set(trace_context)

# Export tracing data for monitoring systems
def export_trace_data(trace_context: TraceContext) -> Dict[str, Any]:
    """Export trace data in OpenTelemetry compatible format"""

    return {
        "trace_id": trace_context.trace_id,
        "correlation_id": trace_context.correlation_id,
        "service_name": trace_context.service_name,
        "user_id": trace_context.user_id,
        "tenant_id": trace_context.tenant_id,
        "organization_id": trace_context.organization_id,
        "spans": [
            {
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "operation_name": span.operation_name,
                "service_name": span.service_name,
                "start_time": span.start_time.isoformat(),
                "end_time": span.end_time.isoformat() if span.end_time else None,
                "duration_ms": span.duration_ms,
                "status": span.status,
                "tags": span.tags,
                "logs": span.logs
            }
            for span in trace_context.spans
        ]
    }

# Example usage and testing
async def example_traced_operation():
    """Example of how to use distributed tracing"""

    # This would typically be called within a request context
    correlation_id = "example_correlation_123"
    set_correlation_id(correlation_id)

    # Create spans for different operations
    with trace_async_operation("database_query", "database_service"):
        await asyncio.sleep(0.1)  # Simulate database query

    with trace_async_operation("external_api_call", "external_service"):
        await asyncio.sleep(0.2)  # Simulate external API call

    # Get trace context for export
    trace_context = get_trace_context()
    if trace_context:
        trace_data = export_trace_data(trace_context)
        print(f"Exported trace data: {json.dumps(trace_data, indent=2)}")

if __name__ == "__main__":
    asyncio.run(example_traced_operation())