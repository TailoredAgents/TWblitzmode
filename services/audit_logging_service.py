"""
Comprehensive Audit Logging Service
Enterprise-grade security and compliance logging for all system actions
September 2025 - Critical Security Enhancement
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict
from enum import Enum
import asyncio
import uuid
import hashlib
from pathlib import Path

from api.database import get_db

logger = logging.getLogger(__name__)

class AuditEventType(Enum):
    # Authentication Events
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    PASSWORD_RESET = "password_reset"
    PASSWORD_CHANGED = "password_changed"
    TOKEN_REFRESH = "token_refresh"

    # Data Access Events
    PROSPECT_CREATED = "prospect_created"
    PROSPECT_VIEWED = "prospect_viewed"
    PROSPECT_UPDATED = "prospect_updated"
    PROSPECT_DELETED = "prospect_deleted"
    BULK_PROSPECT_IMPORT = "bulk_prospect_import"

    # Email Events
    EMAIL_SENT = "email_sent"
    EMAIL_CAMPAIGN_CREATED = "email_campaign_created"
    EMAIL_SETTINGS_UPDATED = "email_settings_updated"
    EMAIL_TEMPLATE_CREATED = "email_template_created"

    # LinkedIn Events
    LINKEDIN_COOKIES_STORED = "linkedin_cookies_stored"
    LINKEDIN_PROFILE_ACCESSED = "linkedin_profile_accessed"
    LINKEDIN_SEARCH_PERFORMED = "linkedin_search_performed"

    # AI/ML Events
    AI_WORKFLOW_STARTED = "ai_workflow_started"
    AI_EMAIL_GENERATED = "ai_email_generated"
    AI_ANALYSIS_PERFORMED = "ai_analysis_performed"

    # Administrative Events
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    ROLE_CHANGED = "role_changed"
    PERMISSIONS_UPDATED = "permissions_updated"

    # System Events
    BACKUP_CREATED = "backup_created"
    SYSTEM_MAINTENANCE = "system_maintenance"
    CONFIGURATION_CHANGED = "configuration_changed"
    ERROR_OCCURRED = "error_occurred"
    ONBOARDING_NUDGE = "onboarding_nudge"
    BILLING_ALERT = "billing_alert"
    EXTERNAL_API_CALL = "external_api_call"

    # Security Events
    UNAUTHORIZED_ACCESS_ATTEMPT = "unauthorized_access_attempt"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    DATA_EXPORT = "data_export"
    ENCRYPTION_KEY_ROTATED = "encryption_key_rotated"

    # Compliance Events
    GDPR_REQUEST = "gdpr_request"
    DATA_RETENTION_CLEANUP = "data_retention_cleanup"
    PRIVACY_POLICY_ACCEPTED = "privacy_policy_accepted"
    SEAT_REQUESTED = "seat_requested"

class AuditSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class AuditEvent:
    """Audit event with comprehensive metadata"""
    id: str
    tenant_id: str
    user_id: Optional[str]
    event_type: AuditEventType
    severity: AuditSeverity
    action: str
    resource_type: str
    resource_id: Optional[str]
    details: Dict[str, Any]
    ip_address: Optional[str]
    user_agent: Optional[str]
    session_id: Optional[str]
    correlation_id: Optional[str]
    timestamp: datetime
    success: bool
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "error_message": self.error_message
        }

class AuditLoggingService:
    """Enterprise audit logging service with compliance features"""

    def __init__(self):
        self.retention_days = int(os.getenv("AUDIT_RETENTION_DAYS", "2555"))  # 7 years default
        self.log_level = os.getenv("AUDIT_LOG_LEVEL", "INFO")
        self.enable_realtime_alerts = os.getenv("ENABLE_AUDIT_ALERTS", "true").lower() == "true"
        self.log_file: Optional[str] = None

        # Initialize structured logger
        self._init_structured_logger()

        # Critical events that require immediate attention
        self.critical_events = {
            AuditEventType.UNAUTHORIZED_ACCESS_ATTEMPT,
            AuditEventType.SUSPICIOUS_ACTIVITY,
            AuditEventType.DATA_EXPORT,
            AuditEventType.ENCRYPTION_KEY_ROTATED,
            AuditEventType.LOGIN_FAILED
        }

    def _init_structured_logger(self):
        """Initialize structured logging for audit events"""
        self.audit_logger = logging.getLogger("audit")
        self.audit_logger.setLevel(getattr(logging, self.log_level))

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # Avoid attaching duplicate handlers when the service is re-instantiated (e.g. in tests)
        if self.audit_logger.handlers:
            return

        configured_path = Path(os.getenv("AUDIT_LOG_FILE", "/var/log/VouchLink-AI/audit.log"))
        fallback_env = os.getenv("AUDIT_LOG_FALLBACK_FILE")
        default_fallback = Path.cwd() / "logs" / "audit.log"
        fallback_path = Path(fallback_env) if fallback_env else default_fallback

        for candidate in (configured_path, fallback_path):
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                handler = logging.FileHandler(candidate)
                handler.setFormatter(formatter)
                self.audit_logger.addHandler(handler)
                self.log_file = str(candidate)
                if candidate == fallback_path and candidate != configured_path:
                    logger.info("Audit logging falling back to %s", candidate)
                break
            except Exception as exc:
                logger.warning("Failed to configure audit log file at %s: %s", candidate, exc)
        else:
            # Final safeguard: emit audit events to stderr so they are not lost.
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            self.audit_logger.addHandler(stream_handler)
            self.log_file = None
            logger.error(
                "Fell back to stream-based audit logging; configure AUDIT_LOG_FILE or AUDIT_LOG_FALLBACK_FILE"
            )

    async def log_event(
        self,
        tenant_id: Optional[str] = None,
        event_type: Optional[AuditEventType] = None,
        action: str = "",
        resource_type: Optional[str] = None,
        user_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        severity: Optional[AuditSeverity] = None,
        *,
        organization_id: Optional[Any] = None,
        actor_type: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        **legacy_kwargs: Any,
    ) -> str:
        """Log an audit event"""
        try:
            metadata_legacy = legacy_kwargs.pop("metadata", None)
            actor_id_legacy = legacy_kwargs.pop("actor_id", None)
            if legacy_kwargs:
                logger.debug("Ignoring unsupported audit log kwargs: %s", legacy_kwargs)

            if tenant_id is None and organization_id is not None:
                tenant_id = str(organization_id)

            if tenant_id is None:
                raise ValueError("tenant_id is required for audit logging")

            if resource_type is None and target_type is not None:
                resource_type = target_type

            if resource_id is None and target_id is not None:
                resource_id = target_id

            merged_details: Dict[str, Any] = {}
            if payload:
                merged_details.update(payload)
            if details:
                merged_details.update(details)
            else:
                details = None  # ensure we reuse below

            if metadata_legacy:
                if isinstance(metadata_legacy, dict):
                    merged_details.update(metadata_legacy)
                else:
                    merged_details["metadata"] = metadata_legacy

            if actor_id_legacy is not None:
                merged_details.setdefault("actor_id", actor_id_legacy)

            if actor_type is not None:
                merged_details.setdefault("actor_type", actor_type)

            if not merged_details:
                merged_details = details or {}

            details = merged_details

            if resource_type is None:
                resource_type = "unknown"

            if event_type is None:
                if action.endswith("_failed") or action.endswith("_error"):
                    event_type = AuditEventType.ERROR_OCCURRED
                elif action.endswith("_started") or action.startswith("automated_workflow"):
                    event_type = AuditEventType.AI_WORKFLOW_STARTED
                else:
                    event_type = AuditEventType.SYSTEM_MAINTENANCE

            # Generate unique event ID
            event_id = str(uuid.uuid4())

            # Determine severity if not provided
            if severity is None:
                severity = self._determine_severity(event_type, success)

            # Sanitize details to remove sensitive information
            sanitized_details = self._sanitize_details(details or {})

            # Create audit event
            audit_event = AuditEvent(
                id=event_id,
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=event_type,
                severity=severity,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=sanitized_details,
                ip_address=ip_address,
                user_agent=user_agent,
                session_id=session_id,
                correlation_id=correlation_id,
                timestamp=datetime.now(timezone.utc),
                success=success,
                error_message=error_message
            )

            # Store in database
            await self._store_audit_event(audit_event)

            # Log to structured logger
            self._log_to_structured_logger(audit_event)

            # Send real-time alerts for critical events
            if self.enable_realtime_alerts and event_type in self.critical_events:
                await self._send_security_alert(audit_event)

            return event_id

        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")
            # Fallback logging to ensure we don't lose critical events
            self.audit_logger.error(f"AUDIT_LOG_FAILURE: {event_type.value} - {action} - {str(e)}")
            return ""

    def _determine_severity(self, event_type: AuditEventType, success: bool) -> AuditSeverity:
        """Determine event severity based on type and success"""
        if not success:
            return AuditSeverity.HIGH

        if event_type in {
            AuditEventType.UNAUTHORIZED_ACCESS_ATTEMPT,
            AuditEventType.SUSPICIOUS_ACTIVITY,
            AuditEventType.ENCRYPTION_KEY_ROTATED
        }:
            return AuditSeverity.CRITICAL
        elif event_type in {
            AuditEventType.LOGIN_FAILED,
            AuditEventType.DATA_EXPORT,
            AuditEventType.ROLE_CHANGED,
            AuditEventType.PERMISSIONS_UPDATED
        }:
            return AuditSeverity.HIGH
        elif event_type in {
            AuditEventType.PASSWORD_CHANGED,
            AuditEventType.EMAIL_SETTINGS_UPDATED,
            AuditEventType.CONFIGURATION_CHANGED
        }:
            return AuditSeverity.MEDIUM
        else:
            return AuditSeverity.LOW

    def _sanitize_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive information from event details"""
        sanitized = details.copy()

        # Fields to remove completely
        sensitive_fields = {
            'password', 'password_hash', 'token', 'secret', 'key', 'cookie',
            'api_key', 'access_token', 'refresh_token', 'private_key'
        }

        # Fields to hash instead of removing
        hash_fields = {'email', 'linkedin_url', 'phone'}

        def sanitize_recursive(obj):
            if isinstance(obj, dict):
                result = {}
                for key, value in obj.items():
                    key_lower = key.lower()
                    if any(sensitive in key_lower for sensitive in sensitive_fields):
                        result[key] = "[REDACTED]"
                    elif any(hash_field in key_lower for hash_field in hash_fields):
                        result[key] = hashlib.sha256(str(value).encode()).hexdigest()[:8]
                    else:
                        result[key] = sanitize_recursive(value)
                return result
            elif isinstance(obj, list):
                return [sanitize_recursive(item) for item in obj]
            else:
                return obj

        return sanitize_recursive(sanitized)

    async def _store_audit_event(self, audit_event: AuditEvent):
        """Store audit event in database"""
        try:
            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO audit_events (
                            id, tenant_id, user_id, event_type, severity, action,
                            resource_type, resource_id, details, ip_address, user_agent,
                            session_id, correlation_id, timestamp, success, error_message
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            audit_event.id,
                            audit_event.tenant_id,
                            audit_event.user_id,
                            audit_event.event_type.value,
                            audit_event.severity.value,
                            audit_event.action,
                            audit_event.resource_type,
                            audit_event.resource_id,
                            json.dumps(audit_event.details),
                            audit_event.ip_address,
                            audit_event.user_agent,
                            audit_event.session_id,
                            audit_event.correlation_id,
                            audit_event.timestamp.isoformat(),
                            audit_event.success,
                            audit_event.error_message,
                        ),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Failed to store audit event in database: {e}")
            # Continue with other logging methods

    def _log_to_structured_logger(self, audit_event: AuditEvent):
        """Log to structured logger"""
        try:
            log_data = audit_event.to_dict()
            log_message = f"AUDIT: {audit_event.event_type.value} - {audit_event.action}"

            if audit_event.severity == AuditSeverity.CRITICAL:
                self.audit_logger.critical(f"{log_message} | {json.dumps(log_data)}")
            elif audit_event.severity == AuditSeverity.HIGH:
                self.audit_logger.error(f"{log_message} | {json.dumps(log_data)}")
            elif audit_event.severity == AuditSeverity.MEDIUM:
                self.audit_logger.warning(f"{log_message} | {json.dumps(log_data)}")
            else:
                self.audit_logger.info(f"{log_message} | {json.dumps(log_data)}")

        except Exception as e:
            logger.error(f"Failed to log to structured logger: {e}")

    async def _send_security_alert(self, audit_event: AuditEvent):
        """Send real-time security alerts for critical events"""
        try:
            # This would integrate with alerting systems like Slack, PagerDuty, etc.
            alert_data = {
                "event_id": audit_event.id,
                "tenant_id": audit_event.tenant_id,
                "event_type": audit_event.event_type.value,
                "severity": audit_event.severity.value,
                "action": audit_event.action,
                "timestamp": audit_event.timestamp.isoformat(),
                "ip_address": audit_event.ip_address,
                "user_id": audit_event.user_id
            }

            logger.warning(f"SECURITY_ALERT: {json.dumps(alert_data)}")

            # TODO: Implement actual alerting integration
            # await self._send_slack_alert(alert_data)
            # await self._send_pagerduty_alert(alert_data)

        except Exception as e:
            logger.error(f"Failed to send security alert: {e}")

    async def query_audit_events(
        self,
        tenant_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        event_types: Optional[List[AuditEventType]] = None,
        user_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        severity: Optional[AuditSeverity] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Query audit events with filters"""
        try:
            conn = get_db()
            try:
                description = None
                with conn.cursor() as cursor:
                    # Build query with filters
                    where_conditions = ["tenant_id = ?"]
                    params: List[Any] = [tenant_id]

                    if start_date:
                        where_conditions.append("timestamp >= ?")
                        params.append(start_date.isoformat())

                    if end_date:
                        where_conditions.append("timestamp <= ?")
                        params.append(end_date.isoformat())

                    if event_types:
                        placeholders = ",".join("?" for _ in event_types)
                        where_conditions.append(f"event_type IN ({placeholders})")
                        params.extend([et.value for et in event_types])

                    if user_id:
                        where_conditions.append("user_id = ?")
                        params.append(user_id)

                    if resource_type:
                        where_conditions.append("resource_type = ?")
                        params.append(resource_type)

                    if resource_id:
                        where_conditions.append("resource_id = ?")
                        params.append(resource_id)

                    if severity:
                        where_conditions.append("severity = ?")
                        params.append(severity.value)

                    query = f"""
                        SELECT *
                        FROM audit_events
                        WHERE {' AND '.join(where_conditions)}
                        ORDER BY timestamp DESC
                        LIMIT ? OFFSET ?
                    """
                    params.extend([limit, offset])

                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                    description = cursor.description

                events: List[Dict[str, Any]] = []
                for row in rows:
                    if hasattr(row, "_mapping"):
                        event_dict = dict(row._mapping)
                    else:
                        columns = [desc[0] for desc in description] if description else []
                        event_dict = dict(zip(columns, row))

                    if event_dict.get("details"):
                        try:
                            event_dict["details"] = json.loads(event_dict["details"])
                        except Exception:
                            pass

                    events.append(event_dict)

                return events
            finally:
                conn.close()

        except Exception as e:
            logger.error(f"Failed to query audit events: {e}")
            return []

    async def generate_compliance_report(
        self,
        tenant_id: str,
        start_date: datetime,
        end_date: datetime,
        report_type: str = "gdpr"
    ) -> Dict[str, Any]:
        """Generate compliance report"""
        try:
            # Query relevant events for the period
            events = await self.query_audit_events(
                tenant_id=tenant_id,
                start_date=start_date,
                end_date=end_date
            )

            # Generate report statistics
            report = {
                "tenant_id": tenant_id,
                "report_type": report_type,
                "period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                },
                "total_events": len(events),
                "events_by_type": {},
                "events_by_severity": {},
                "security_incidents": 0,
                "data_access_events": 0,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }

            # Analyze events
            for event in events:
                event_type = event.get('event_type', 'unknown')
                severity = event.get('severity', 'low')

                # Count by type
                report["events_by_type"][event_type] = report["events_by_type"].get(event_type, 0) + 1

                # Count by severity
                report["events_by_severity"][severity] = report["events_by_severity"].get(severity, 0) + 1

                # Count security incidents
                if severity in ['high', 'critical']:
                    report["security_incidents"] += 1

                # Count data access events
                if 'viewed' in event_type or 'accessed' in event_type:
                    report["data_access_events"] += 1

            return report

        except Exception as e:
            logger.error(f"Failed to generate compliance report: {e}")
            return {
                "error": str(e),
                "generated_at": datetime.now(timezone.utc).isoformat()
            }

    async def cleanup_old_events(self) -> int:
        """Clean up old audit events based on retention policy"""
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_days)

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM audit_events WHERE timestamp < ?",
                        (cutoff_date.isoformat(),),
                    )
                    deleted_count = cursor.rowcount
                conn.commit()
            finally:
                conn.close()

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old audit events")

            return deleted_count

        except Exception as e:
            logger.error(f"Failed to cleanup old audit events: {e}")
            return 0

    async def health_check(self) -> Dict[str, Any]:
        """Health check for audit logging service"""
        try:
            health_status = {
                "status": "healthy",
                "retention_days": self.retention_days,
                "realtime_alerts_enabled": self.enable_realtime_alerts,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            # Test database connection
            try:
                conn = get_db()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT COUNT(*) FROM audit_events LIMIT 1")
                finally:
                    conn.close()
                health_status["database_connected"] = True
            except Exception as e:
                health_status["database_connected"] = False
                health_status["database_error"] = str(e)
                health_status["status"] = "degraded"

            # Test logging
            try:
                test_event_id = await self.log_event(
                    tenant_id="health_check",
                    event_type=AuditEventType.SYSTEM_MAINTENANCE,
                    action="health_check",
                    resource_type="system"
                )
                health_status["logging_test"] = "passed" if test_event_id else "failed"
            except Exception as e:
                health_status["logging_test"] = "failed"
                health_status["logging_error"] = str(e)
                health_status["status"] = "degraded"

            return health_status

        except Exception as e:
            logger.error(f"Audit logging health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

# Global audit logging service instance
audit_service = AuditLoggingService()

# Alias for backward compatibility
audit_logger = audit_service
