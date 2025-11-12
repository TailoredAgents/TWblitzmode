"""
Comprehensive Audit Logging Service for Link Master Chat Agent
Provides detailed audit trails, security monitoring, and compliance logging

Features:
- Multi-level audit logging (interaction, security, compliance)
- Tenant-scoped audit trails with data isolation
- Real-time security monitoring and alerting
- Compliance reporting and data retention
- Performance metrics and analytics
- Export capabilities for external SIEM systems
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

logger = logging.getLogger(__name__)

class AuditEventType(Enum):
    """Types of audit events"""
    USER_MESSAGE = "user_message"
    AGENT_RESPONSE = "agent_response"
    SECURITY_VIOLATION = "security_violation"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    TENANT_VIOLATION = "tenant_violation"
    SESSION_CREATED = "session_created"
    SESSION_EXPIRED = "session_expired"
    COMMAND_EXECUTED = "command_executed"
    TOOL_EXECUTED = "tool_executed"
    WORKFLOW_TRIGGERED = "workflow_triggered"
    DATA_ACCESSED = "data_accessed"
    AUTHENTICATION_EVENT = "authentication_event"
    CONFIGURATION_CHANGE = "configuration_change"
    ERROR_OCCURRED = "error_occurred"

class AuditLevel(Enum):
    """Audit logging levels"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class ComplianceRequirement(Enum):
    """Compliance frameworks supported"""
    GDPR = "gdpr"
    SOX = "sox"
    HIPAA = "hipaa"
    SOC2 = "soc2"
    ISO27001 = "iso27001"

@dataclass
class AuditEvent:
    """Structured audit event"""
    event_id: str
    event_type: AuditEventType
    level: AuditLevel
    timestamp: datetime
    organization_id: int
    user_id: int
    session_id: str
    agent_id: str

    # Event details
    description: str
    details: Dict[str, Any]

    # Security context
    security_score: Optional[float] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    # Compliance tags
    compliance_tags: Set[ComplianceRequirement] = None

    # Performance metrics
    processing_time_ms: Optional[int] = None
    memory_usage_mb: Optional[float] = None

    def __post_init__(self):
        if self.compliance_tags is None:
            self.compliance_tags = set()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['event_type'] = self.event_type.value
        data['level'] = self.level.value
        data['timestamp'] = self.timestamp.isoformat()
        data['compliance_tags'] = [tag.value for tag in self.compliance_tags]
        return data

class ChatAuditLogger:
    """
    Comprehensive audit logging service for chat interactions

    Provides detailed audit trails with tenant isolation, security monitoring,
    and compliance reporting capabilities.
    """

    def __init__(self):
        self.audit_events: List[AuditEvent] = []
        self.max_events_in_memory = 10000
        self.retention_days = 90
        self.retention_check_interval_minutes = 15
        self._last_retention_check = datetime.now(timezone.utc)

        self.storage_dir = Path(os.getenv("CHAT_AUDIT_LOG_DIR", "data/chat_audit_logs"))
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        except Exception as storage_error:
            logger.warning(f"Unable to create audit log directory {self.storage_dir}: {storage_error}")

        # Security monitoring thresholds
        self.security_thresholds = {
            "low_security_score": 70.0,
            "critical_violations_per_hour": 10,
            "failed_auth_attempts_per_hour": 20,
            "rate_limit_violations_per_hour": 50
        }

        # Performance monitoring
        self.performance_metrics = {
            "total_events": 0,
            "events_by_type": {},
            "events_by_organization": {},
            "average_processing_time": 0.0
        }

        logger.info("ChatAuditLogger initialized with comprehensive monitoring")

    async def log_interaction(
        self,
        organization_id: int,
        user_id: int,
        session_id: str,
        user_message: str,
        agent_response: str,
        security_result = None,
        processing_time_ms: int = None,
        **kwargs
    ) -> str:
        """
        Log a complete chat interaction with security context

        Args:
            organization_id: Tenant organization ID
            user_id: User ID
            session_id: Chat session ID
            user_message: User's input message
            agent_response: Agent's response
            security_result: Security filtering result
            processing_time_ms: Response processing time
            **kwargs: Additional context

        Returns:
            Event ID for correlation
        """
        event_id = str(uuid.uuid4())

        # Determine security score and compliance tags
        security_score = security_result.security_score if security_result else 100.0
        compliance_tags = self._determine_compliance_tags(user_message, agent_response)

        # Create audit event
        # Include the model_id used for AI responses (locked globally)
        try:
            from core.settings import settings as _settings
            _model_id = _settings.OPENAI_MODEL
        except Exception:
            _model_id = "unknown"

        audit_event = AuditEvent(
            event_id=event_id,
            event_type=AuditEventType.AGENT_RESPONSE,
            level=AuditLevel.INFO,
            timestamp=datetime.now(timezone.utc),
            organization_id=organization_id,
            user_id=user_id,
            session_id=session_id,
            agent_id="master_chat_agent",
            description=f"Chat interaction: user message ({len(user_message)} chars) -> agent response ({len(agent_response)} chars)",
            details={
                "user_message_length": len(user_message),
                "agent_response_length": len(agent_response),
                "user_message_hash": self._hash_message(user_message),
                "agent_response_hash": self._hash_message(agent_response),
                "security_violations": len(security_result.violations) if security_result else 0,
                "redactions_applied": security_result.redactions_count if security_result else 0,
                "model_id": _model_id,
                **kwargs
            },
            security_score=security_score,
            compliance_tags=compliance_tags,
            processing_time_ms=processing_time_ms
        )

        await self._store_audit_event(audit_event)
        await self._check_security_alerts(audit_event)

        return event_id

    async def log_security_violation(
        self,
        organization_id: int,
        user_id: int,
        session_id: str,
        violation_type: str,
        severity: str,
        details: Dict[str, Any]
    ) -> str:
        """Log security violation with alerting"""
        event_id = str(uuid.uuid4())

        # Determine audit level based on severity
        audit_level = AuditLevel.CRITICAL if severity == "critical" else \
                     AuditLevel.ERROR if severity == "high" else \
                     AuditLevel.WARNING if severity == "medium" else \
                     AuditLevel.INFO

        audit_event = AuditEvent(
            event_id=event_id,
            event_type=AuditEventType.SECURITY_VIOLATION,
            level=audit_level,
            timestamp=datetime.now(timezone.utc),
            organization_id=organization_id,
            user_id=user_id,
            session_id=session_id,
            agent_id="chat_security_filter",
            description=f"Security violation: {violation_type} ({severity})",
            details=details,
            compliance_tags={ComplianceRequirement.SOC2, ComplianceRequirement.ISO27001}
        )

        await self._store_audit_event(audit_event)
        await self._handle_security_alert(audit_event)

        return event_id

    async def log_rate_limit_exceeded(
        self,
        organization_id: int,
        user_id: int,
        limit_type: str,
        current_count: int,
        limit_value: int
    ) -> str:
        """Log rate limit violation"""
        event_id = str(uuid.uuid4())

        audit_event = AuditEvent(
            event_id=event_id,
            event_type=AuditEventType.RATE_LIMIT_EXCEEDED,
            level=AuditLevel.WARNING,
            timestamp=datetime.now(timezone.utc),
            organization_id=organization_id,
            user_id=user_id,
            session_id="rate_limit_check",
            agent_id="master_chat_agent",
            description=f"Rate limit exceeded: {limit_type}",
            details={
                "limit_type": limit_type,
                "current_count": current_count,
                "limit_value": limit_value,
                "percentage_used": (current_count / limit_value) * 100
            },
            compliance_tags={ComplianceRequirement.SOC2}
        )

        await self._store_audit_event(audit_event)
        return event_id

    async def log_tenant_violation(
        self,
        organization_id: int,
        user_id: int,
        violation_details: Dict[str, Any]
    ) -> str:
        """Log tenant isolation violation"""
        event_id = str(uuid.uuid4())

        audit_event = AuditEvent(
            event_id=event_id,
            event_type=AuditEventType.TENANT_VIOLATION,
            level=AuditLevel.ERROR,
            timestamp=datetime.now(timezone.utc),
            organization_id=organization_id,
            user_id=user_id,
            session_id="tenant_validation",
            agent_id="master_chat_agent",
            description="Tenant isolation violation detected",
            details=violation_details,
            compliance_tags={ComplianceRequirement.SOC2, ComplianceRequirement.GDPR}
        )

        await self._store_audit_event(audit_event)
        await self._handle_security_alert(audit_event)

        return event_id

    async def log_session_event(
        self,
        organization_id: int,
        user_id: int,
        session_id: str,
        event: str,
        details: Optional[Dict[str, Any]] = None
    ) -> str:
        """Record session lifecycle events for auditing and retention."""
        event_key = (event or "session_created").lower()

        if "expired" in event_key:
            audit_type = AuditEventType.SESSION_EXPIRED
            level = AuditLevel.WARNING
            description = "Session expired and was reset"
        elif "conflict" in event_key:
            audit_type = AuditEventType.SESSION_CREATED
            level = AuditLevel.WARNING
            description = "Session reinitialized due to ownership conflict"
        else:
            audit_type = AuditEventType.SESSION_CREATED
            level = AuditLevel.INFO
            description = "Session initialized"

        audit_event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=audit_type,
            level=level,
            timestamp=datetime.now(timezone.utc),
            organization_id=organization_id,
            user_id=user_id,
            session_id=session_id,
            agent_id="master_chat_agent",
            description=description,
            details={
                "event": event_key,
                **(details or {})
            }
        )

        await self._store_audit_event(audit_event)
        return audit_event.event_id

    async def log_command_execution(
        self,
        organization_id: int,
        user_id: int,
        session_id: str,
        command: str,
        success: bool,
        execution_time_ms: int = None,
        result_summary: str = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log command execution"""
        event_id = str(uuid.uuid4())

        audit_event = AuditEvent(
            event_id=event_id,
            event_type=AuditEventType.COMMAND_EXECUTED,
            level=AuditLevel.INFO,
            timestamp=datetime.now(timezone.utc),
            organization_id=organization_id,
            user_id=user_id,
            session_id=session_id,
            agent_id="master_chat_agent",
            description=f"Command executed: {command}",
            details={
                "command": command,
                "success": success,
                "result_summary": result_summary or "",
                "metadata": metadata or {}
            },
            processing_time_ms=execution_time_ms
        )

        await self._store_audit_event(audit_event)
        return event_id

    async def get_audit_trail(
        self,
        organization_id: int,
        start_date: datetime = None,
        end_date: datetime = None,
        event_types: List[AuditEventType] = None,
        user_id: int = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Retrieve audit trail with filtering

        Args:
            organization_id: Tenant organization ID
            start_date: Start date for filtering
            end_date: End date for filtering
            event_types: Event types to include
            user_id: Specific user ID filter
            limit: Maximum events to return

        Returns:
            List of audit events
        """
        filtered_events = []

        for event in self.audit_events:
            # Tenant isolation - only return events for this organization
            if event.organization_id != organization_id:
                continue

            # Date filtering
            if start_date and event.timestamp < start_date:
                continue
            if end_date and event.timestamp > end_date:
                continue

            # Event type filtering
            if event_types and event.event_type not in event_types:
                continue

            # User filtering
            if user_id and event.user_id != user_id:
                continue

            filtered_events.append(event.to_dict())

            if len(filtered_events) >= limit:
                break

        # Sort by timestamp (newest first)
        filtered_events.sort(key=lambda e: e['timestamp'], reverse=True)

        return filtered_events

    async def get_security_summary(
        self,
        organization_id: int,
        hours: int = 24
    ) -> Dict[str, Any]:
        """Get security summary for organization"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        security_events = [
            event for event in self.audit_events
            if (event.organization_id == organization_id and
                event.timestamp > cutoff_time and
                event.event_type in [
                    AuditEventType.SECURITY_VIOLATION,
                    AuditEventType.RATE_LIMIT_EXCEEDED,
                    AuditEventType.TENANT_VIOLATION
                ])
        ]

        return {
            "organization_id": organization_id,
            "time_period_hours": hours,
            "total_security_events": len(security_events),
            "violations_by_type": self._group_by_field(security_events, "event_type"),
            "violations_by_severity": self._group_by_field(security_events, "level"),
            "affected_users": len(set(e.user_id for e in security_events)),
            "average_security_score": self._calculate_average_security_score(organization_id, cutoff_time),
            "compliance_status": self._assess_compliance_status(security_events)
        }

    async def export_audit_log(
        self,
        organization_id: int,
        format: str = "json",
        start_date: datetime = None,
        end_date: datetime = None
    ) -> str:
        """Export audit log for external systems"""
        events = await self.get_audit_trail(
            organization_id, start_date, end_date, limit=50000
        )

        if format.lower() == "json":
            return json.dumps(events, indent=2, default=str)
        elif format.lower() == "csv":
            return self._export_as_csv(events)
        elif format.lower() == "siem":
            return self._export_as_siem(events)
        else:
            raise ValueError(f"Unsupported export format: {format}")

    def _hash_message(self, message: str) -> str:
        """Create hash of message for audit trail without storing content"""
        import hashlib
        return hashlib.sha256(message.encode()).hexdigest()[:16]

    def _determine_compliance_tags(
        self,
        user_message: str,
        agent_response: str
    ) -> Set[ComplianceRequirement]:
        """Determine which compliance frameworks apply"""
        tags = {ComplianceRequirement.SOC2}  # Default

        # Add GDPR if processing EU personal data
        if any(term in user_message.lower() for term in ["gdpr", "eu", "european", "privacy"]):
            tags.add(ComplianceRequirement.GDPR)

        # Add specific compliance based on content
        if any(term in (user_message + agent_response).lower() for term in ["financial", "audit", "sox"]):
            tags.add(ComplianceRequirement.SOX)

        return tags

    async def _store_audit_event(self, event: AuditEvent):
        """Store audit event in memory and persistent storage"""
        self.audit_events.append(event)

        # Maintain memory limits
        self._enforce_in_memory_retention()

        # Update metrics
        self.performance_metrics["total_events"] += 1
        event_type = event.event_type.value
        self.performance_metrics["events_by_type"][event_type] = \
            self.performance_metrics["events_by_type"].get(event_type, 0) + 1

        # Persist to disk and enforce retention periodically
        self._persist_to_disk(event)
        self._enforce_disk_retention()

    def _enforce_in_memory_retention(self):
        """Trim in-memory events based on retention window and capacity."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        self.audit_events = [
            event for event in self.audit_events
            if event.timestamp >= cutoff_time
        ]

        if len(self.audit_events) > self.max_events_in_memory:
            self.audit_events = self.audit_events[-self.max_events_in_memory:]

    def _persist_to_disk(self, event: AuditEvent):
        """Persist audit event to disk as JSONL for long-term retention."""
        if not self.storage_dir or not self.storage_dir.exists():
            return

        file_path = self.storage_dir / f"audit_{event.timestamp.strftime('%Y%m%d')}.jsonl"
        try:
            with file_path.open("a", encoding="utf-8") as handle:
                json.dump(event.to_dict(), handle)
                handle.write("\n")
        except Exception as e:
            logger.debug(f"Failed to persist audit event to disk: {e}")

    def _enforce_disk_retention(self):
        """Remove audit log files outside retention window (runs periodically)."""
        now = datetime.now(timezone.utc)
        if (now - self._last_retention_check).total_seconds() < self.retention_check_interval_minutes * 60:
            return

        self._last_retention_check = now
        cutoff_date = (now - timedelta(days=self.retention_days)).date()

        try:
            for file_path in self.storage_dir.glob("audit_*.jsonl"):
                try:
                    date_part = file_path.stem.replace("audit_", "")
                    file_date = datetime.strptime(date_part, "%Y%m%d").date()
                    if file_date < cutoff_date:
                        file_path.unlink(missing_ok=True)
                except ValueError:
                    continue
        except Exception as retention_error:
            logger.debug(f"Disk retention enforcement failed: {retention_error}")

    async def _check_security_alerts(self, event: AuditEvent):
        """Check if event triggers security alerts"""
        if event.security_score and event.security_score < self.security_thresholds["low_security_score"]:
            logger.warning(f"Low security score detected: {event.security_score} for org {event.organization_id}")

    async def _handle_security_alert(self, event: AuditEvent):
        """Handle high-priority security alerts"""
        if event.level in [AuditLevel.ERROR, AuditLevel.CRITICAL]:
            logger.error(f"Security alert: {event.description} for org {event.organization_id}")
            # TODO: Send to alerting system (Slack, email, etc.)

    def _group_by_field(self, events: List[AuditEvent], field: str) -> Dict[str, int]:
        """Group events by a specific field"""
        groups = {}
        for event in events:
            value = getattr(event, field)
            if hasattr(value, 'value'):  # Enum
                value = value.value
            groups[str(value)] = groups.get(str(value), 0) + 1
        return groups

    def _calculate_average_security_score(
        self,
        organization_id: int,
        since: datetime
    ) -> float:
        """Calculate average security score for organization"""
        scores = [
            event.security_score for event in self.audit_events
            if (event.organization_id == organization_id and
                event.timestamp > since and
                event.security_score is not None)
        ]
        return sum(scores) / len(scores) if scores else 100.0

    def _assess_compliance_status(self, events: List[AuditEvent]) -> Dict[str, str]:
        """Assess compliance status based on events"""
        return {
            "soc2": "compliant" if len(events) < 10 else "needs_review",
            "gdpr": "compliant",
            "overall": "compliant" if len(events) < 5 else "needs_review"
        }

    def _export_as_csv(self, events: List[Dict[str, Any]]) -> str:
        """Export events as CSV"""
        if not events:
            return ""

        import csv
        import io

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=events[0].keys())
        writer.writeheader()
        writer.writerows(events)

        return output.getvalue()

    def _export_as_siem(self, events: List[Dict[str, Any]]) -> str:
        """Export in SIEM-compatible format"""
        siem_events = []
        for event in events:
            siem_event = {
                "timestamp": event["timestamp"],
                "source": "vouchlink_chat_agent",
                "event_type": event["event_type"],
                "severity": event["level"],
                "user_id": event["user_id"],
                "organization_id": event["organization_id"],
                "message": event["description"],
                "raw_data": json.dumps(event)
            }
            siem_events.append(json.dumps(siem_event))

        return "\n".join(siem_events)

# Global audit logger instance
chat_audit_logger = ChatAuditLogger()
