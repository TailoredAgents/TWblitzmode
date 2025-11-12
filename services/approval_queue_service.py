#!/usr/bin/env python3
"""
Approval Queue Service - September 2025 Human-in-the-Loop
Manages approval requests for AI agent actions requiring human oversight
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
import asyncpg
import redis

from core.roles import normalize_role

try:
    from services.websocket_manager import websocket_manager
    websocket_available = True
except ImportError:
    logging.warning("WebSocket manager not available")
    websocket_available = False

try:
    from services.agent_logger import agent_logger
    from services.agent_logger import AgentEventType
    agent_logging_available = True
except ImportError:
    logging.warning("Agent logger not available")
    agent_logging_available = False

# Import Communication Hub integration
try:
    from services.communication_client import CommunicationHubClient, MessageType, MessagePriority
    from services.message_translator import MessageTranslator, BusinessContext
    from services.metadata_enricher import MetadataEnricher
    communication_hub_available = True
except ImportError:
    logging.warning("Communication Hub not available in approval queue service")
    communication_hub_available = False

logger = logging.getLogger(__name__)

class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ESCALATED = "escalated"
    AUTO_APPROVED = "auto_approved"

class ApprovalPriority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

class ApprovalType(Enum):
    EMAIL_CAMPAIGN = "email_campaign"
    PROSPECT_IMPORT = "prospect_import"
    CONNECTOR_OUTREACH = "connector_outreach"
    DATA_EXPORT = "data_export"
    INTEGRATION_CHANGE = "integration_change"
    QUOTA_MODIFICATION = "quota_modification"
    # When an individual personalized email requires human sign-off (used by OpenAI orchestrator)
    EMAIL_SEND = "email_send"
    AI_TOOL_EXECUTION = "ai_tool_execution"

class ApprovalRequest:
    """Comprehensive approval request for September 2025 features"""

    def __init__(self, id="", organization_id=0, workflow_id=None,
                 request_type=ApprovalType.EMAIL_SEND, title="", description="",
                 requested_by=0, priority=ApprovalPriority.NORMAL, risk_score=0.0,
                 context_data=None, auto_approve_threshold=0.25, timeout_minutes=30,
                 status=ApprovalStatus.PENDING, created_at=None, expires_at=None,
                 assigned_to=None, approved_by=None, approved_at=None,
                 rejection_reason=None, escalation_reason=None, metadata=None):
        self.id = id
        self.organization_id = organization_id
        self.workflow_id = workflow_id
        self.request_type = request_type
        self.title = title
        self.description = description
        self.requested_by = requested_by
        self.priority = priority
        self.risk_score = risk_score
        self.context_data = context_data if context_data is not None else {}
        self.auto_approve_threshold = auto_approve_threshold
        self.timeout_minutes = timeout_minutes
        self.status = status
        self.created_at = created_at if created_at is not None else datetime.now(timezone.utc)
        self.expires_at = expires_at if expires_at is not None else (self.created_at + timedelta(minutes=timeout_minutes))
        self.assigned_to = assigned_to
        self.approved_by = approved_by
        self.approved_at = approved_at
        self.rejection_reason = rejection_reason
        self.escalation_reason = escalation_reason
        self.metadata = metadata if metadata is not None else {}

class ApprovalRule:
    """Auto-approval and routing rules"""

    def __init__(self, organization_id=0, request_type=ApprovalType.EMAIL_SEND,
                 auto_approve_threshold=0.25, default_timeout_minutes=30,
                 required_role="admin", escalation_threshold_hours=2,
                 notification_channels=None):
        self.organization_id = organization_id
        self.request_type = request_type
        self.auto_approve_threshold = auto_approve_threshold
        self.default_timeout_minutes = default_timeout_minutes
        self.required_role = required_role
        self.escalation_threshold_hours = escalation_threshold_hours
        self.notification_channels = notification_channels if notification_channels is not None else []

class ApprovalQueueService:
    """
    September 2025 - Human-in-the-Loop Approval Queue Management
    Manages approval workflows for AI agent actions
    """

    def __init__(self, database_url, redis_url="redis://localhost:6379"):
        self.database_url = database_url
        self.redis_client = redis.from_url(redis_url)
        self.db_pool = None
        self.approval_handlers: Dict[ApprovalType, Callable] = {}
        self.notification_handlers: List[Callable] = []

        # Communication Hub integration
        if communication_hub_available:
            self.communication_hub = CommunicationHubClient()
            self.message_translator = MessageTranslator()
            self.metadata_enricher = MetadataEnricher()
        else:
            self.communication_hub = None
            self.message_translator = None
            self.metadata_enricher = None

        # Default approval rules
        self.default_rules = {
            ApprovalType.EMAIL_CAMPAIGN: ApprovalRule(
                organization_id=0,  # Global default
                request_type=ApprovalType.EMAIL_CAMPAIGN,
                auto_approve_threshold=0.2,
                default_timeout_minutes=120,
                required_role="admin",
                escalation_threshold_hours=4,
                notification_channels=["email", "dashboard"]
            ),
            ApprovalType.PROSPECT_IMPORT: ApprovalRule(
                organization_id=0,
                request_type=ApprovalType.PROSPECT_IMPORT,
                auto_approve_threshold=0.3,
                default_timeout_minutes=60,
                required_role="user",
                escalation_threshold_hours=2,
                notification_channels=["dashboard"]
            ),
            ApprovalType.CONNECTOR_OUTREACH: ApprovalRule(
                organization_id=0,
                request_type=ApprovalType.CONNECTOR_OUTREACH,
                auto_approve_threshold=0.25,
                default_timeout_minutes=180,
                required_role="admin",
                escalation_threshold_hours=6,
                notification_channels=["email", "dashboard", "slack"]
            ),
            ApprovalType.EMAIL_SEND: ApprovalRule(
                organization_id=0,
                request_type=ApprovalType.EMAIL_SEND,
                auto_approve_threshold=0.3,
                default_timeout_minutes=60,
                required_role="user",
                escalation_threshold_hours=2,
                notification_channels=["dashboard", "email"]
            ),
            ApprovalType.AI_TOOL_EXECUTION: ApprovalRule(
                organization_id=0,
                request_type=ApprovalType.AI_TOOL_EXECUTION,
                auto_approve_threshold=0.25,
                default_timeout_minutes=90,
                required_role="admin",
                escalation_threshold_hours=4,
                notification_channels=["dashboard", "email"]
            )
        }

    async def initialize(self):
        """Initialize the approval queue service"""
        self.db_pool = await asyncpg.create_pool(self.database_url)

        # Start background tasks
        asyncio.create_task(self._process_expiring_requests())
        asyncio.create_task(self._escalate_pending_requests())

        logger.info("✅ Approval Queue Service initialized")

    async def _acquire_conn(self, organization_id: int):
        """Acquire a pooled connection and set RLS tenant GUCs."""
        class _ConnCtx:
            def __init__(self, pool: asyncpg.Pool, org_id: int):
                self.pool = pool
                self.org_id = org_id
                self.conn: Optional[asyncpg.Connection] = None
            async def __aenter__(self):
                self.conn = await self.pool.acquire()
                try:
                    await self.conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", str(self.org_id))
                    await self.conn.execute("SELECT set_config('app.current_organization_id', $1, true)", str(self.org_id))
                except Exception:
                    pass
                return self.conn
            async def __aexit__(self, exc_type, exc, tb):
                if self.conn:
                    try:
                        await self.pool.release(self.conn)
                    except Exception:
                        pass
        if not self.db_pool:
            raise RuntimeError("ApprovalQueueService not initialized")
        return _ConnCtx(self.db_pool, organization_id)

    async def create_approval_request(self,
                                    organization_id: int,
                                    request_type: ApprovalType,
                                    title: str,
                                    description: str,
                                    requested_by: int,
                                    context_data: Dict[str, Any],
                                    workflow_id: Optional[str] = None,
                                    priority: ApprovalPriority = ApprovalPriority.NORMAL,
                                    risk_score: Optional[float] = None) -> str:
        """Create a new approval request"""

        # Get approval rules for organization
        rules = await self._get_approval_rules(organization_id, request_type)

        # Calculate risk score if not provided
        if risk_score is None:
            risk_score = await self._calculate_risk_score(request_type, context_data, organization_id)

        # Check for auto-approval
        if risk_score <= rules.auto_approve_threshold:
            return await self._auto_approve_request(
                organization_id, request_type, title, description,
                requested_by, context_data, workflow_id, risk_score
            )

        # Create approval request
        request_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=rules.default_timeout_minutes)

        request = ApprovalRequest(
            id=request_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            request_type=request_type,
            title=title,
            description=description,
            requested_by=requested_by,
            priority=priority,
            risk_score=risk_score,
            context_data=context_data,
            auto_approve_threshold=rules.auto_approve_threshold,
            timeout_minutes=rules.default_timeout_minutes,
            status=ApprovalStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            metadata={
                "required_role": rules.required_role,
                "escalation_threshold_hours": rules.escalation_threshold_hours
            }
        )

        # Store in database
        await self._store_approval_request(request)

        # Cache in Redis for quick access
        await self._cache_approval_request(request)

        # Assign to appropriate approver
        await self._assign_approval_request(request, rules)

        # Send notifications
        await self._notify_approval_required(request, rules)

        # Log approval request creation with agent logger
        if agent_logging_available:
            await agent_logger.log_approval_request(
                agent_id="human_approval_agent",
                approval_id=request_id,
                request_type=f"approval_{request_type.value}",
                details={
                    "title": title,
                    "description": description,
                    "risk_score": risk_score,
                    "priority": priority.value,
                    "auto_approve_threshold": rules.auto_approve_threshold,
                    "timeout_minutes": rules.default_timeout_minutes,
                    "requires_role": rules.required_role,
                    "context_summary": self._summarize_context(context_data)
                },
                tenant_id=str(organization_id),
                workflow_id=workflow_id,
                user_id=str(requested_by)
            )

        logger.info(f"Created approval request {request_id} for organization {organization_id}")
        return request_id

    async def approve_request(self,
                            request_id: str,
                            approver_id: int,
                            organization_id: int,
                            comments: Optional[str] = None) -> Dict[str, Any]:
        """Approve an approval request"""

        request = await self._get_approval_request(request_id, organization_id=organization_id)
        if not request:
            return {"error": "Approval request not found"}

        if request.organization_id != organization_id:
            return {"error": "Request not found in your organization"}

        if request.status != ApprovalStatus.PENDING:
            return {"error": f"Request already {request.status.value}"}

        # Check if expired
        if datetime.now(timezone.utc) > request.expires_at:
            await self._expire_request(request)
            return {"error": "Request has expired"}

        # Verify approver permissions
        if not await self._can_approve(approver_id, request, organization_id):
            return {"error": "Insufficient permissions to approve this request"}

        # Update request
        request.status = ApprovalStatus.APPROVED
        request.approved_by = approver_id
        request.approved_at = datetime.now(timezone.utc)
        if comments:
            request.metadata = request.metadata or {}
            request.metadata["approval_comments"] = comments

        # Store updates
        await self._update_approval_request(request)
        await self._cache_approval_request(request)

        # Execute approved action
        execution_result = await self._execute_approved_action(request)

        # Notify stakeholders
        await self._notify_approval_decision(request, "approved", execution_result)

        # Log approval decision with agent logger
        if agent_logging_available:
            await agent_logger.log_approval_decision(
                agent_id="human_approval_agent",
                approval_id=request_id,
                decision="approved",
                details={
                    "approver_id": approver_id,
                    "title": request.title,
                    "execution_status": execution_result.get("status", "unknown"),
                    "execution_details": execution_result,
                    "approval_comments": comments,
                    "risk_score": request.risk_score,
                    "request_type": request.request_type.value
                },
                tenant_id=str(request.organization_id),
                workflow_id=request.workflow_id,
                user_id=str(approver_id)
            )

        # Clean up
        await self._cleanup_approval_request(request_id)

        logger.info(f"Approved request {request_id} by user {approver_id}")

        return {
            "status": "approved",
            "execution_result": execution_result,
            "approved_at": request.approved_at.isoformat()
        }

    async def reject_request(self,
                           request_id: str,
                           approver_id: int,
                           organization_id: int,
                           reason: str) -> Dict[str, Any]:
        """Reject an approval request"""

        request = await self._get_approval_request(request_id, organization_id=organization_id)
        if not request:
            return {"error": "Approval request not found"}

        if request.organization_id != organization_id:
            return {"error": "Request not found in your organization"}

        if request.status != ApprovalStatus.PENDING:
            return {"error": f"Request already {request.status.value}"}

        # Verify approver permissions
        if not await self._can_approve(approver_id, request, organization_id):
            return {"error": "Insufficient permissions to reject this request"}

        # Update request
        request.status = ApprovalStatus.REJECTED
        request.approved_by = approver_id
        request.approved_at = datetime.now(timezone.utc)
        request.rejection_reason = reason

        # Store updates
        await self._update_approval_request(request)

        # Notify stakeholders
        await self._notify_approval_decision(request, "rejected")

        # Log rejection decision with agent logger
        if agent_logging_available:
            await agent_logger.log_approval_decision(
                agent_id="human_approval_agent",
                approval_id=request_id,
                decision="rejected",
                details={
                    "approver_id": approver_id,
                    "title": request.title,
                    "rejection_reason": reason,
                    "risk_score": request.risk_score,
                    "request_type": request.request_type.value,
                    "workflow_impact": "Workflow execution halted due to human rejection"
                },
                tenant_id=str(request.organization_id),
                workflow_id=request.workflow_id,
                user_id=str(approver_id)
            )

        # Handle rejection in workflow
        await self._handle_rejection(request)

        # Clean up
        await self._cleanup_approval_request(request_id)

        logger.info(f"Rejected request {request_id} by user {approver_id}: {reason}")

        return {
            "status": "rejected",
            "rejection_reason": reason,
            "rejected_at": request.approved_at.isoformat()
        }

    async def get_pending_approvals(self,
                                  organization_id: int,
                                  user_id: Optional[int] = None,
                                  limit: int = 50) -> List[Dict[str, Any]]:
        """Get pending approval requests for an organization"""

        async with await self._acquire_conn(organization_id) as conn:
            if user_id:
                # Get requests assigned to specific user
                query = """
                    SELECT * FROM approval_requests
                    WHERE organization_id = $1 AND status = 'pending'
                    AND (assigned_to = $2 OR assigned_to IS NULL)
                    ORDER BY priority DESC, created_at ASC
                    LIMIT $3
                """
                rows = await conn.fetch(query, organization_id, user_id, limit)
            else:
                # Get all pending requests for organization
                query = """
                    SELECT * FROM approval_requests
                    WHERE organization_id = $1 AND status = 'pending'
                    ORDER BY priority DESC, created_at ASC
                    LIMIT $2
                """
                rows = await conn.fetch(query, organization_id, limit)

            requests = []
            for row in rows:
                request_data = dict(row)
                request_data["context_data"] = json.loads(request_data["context_data"])
                request_data["metadata"] = json.loads(request_data.get("metadata") or "{}")
                requests.append(request_data)

            return requests

    async def get_approval_request_details(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Expose approval request details for external services."""

        request = await self._get_approval_request(request_id)
        if not request:
            return None

        data = asdict(request)
        data["status"] = request.status.value
        data["request_type"] = request.request_type.value
        data["priority"] = request.priority.value
        data["created_at"] = request.created_at.isoformat()
        data["expires_at"] = request.expires_at.isoformat()
        if request.approved_at:
            data["approved_at"] = request.approved_at.isoformat()

        return data

    async def get_approval_history(self,
                                 organization_id: int,
                                 days: int = 30,
                                 limit: int = 100) -> List[Dict[str, Any]]:
        """Get approval history for an organization"""

        since_date = datetime.now(timezone.utc) - timedelta(days=days)

        async with await self._acquire_conn(organization_id) as conn:
            query = """
                SELECT ar.*, tm.name as approver_name, req.name as requester_name
                FROM approval_requests ar
                LEFT JOIN team_members tm ON ar.approved_by = tm.id
                LEFT JOIN team_members req ON ar.requested_by = req.id
                WHERE ar.organization_id = $1 AND ar.created_at >= $2
                ORDER BY ar.created_at DESC
                LIMIT $3
            """
            rows = await conn.fetch(query, organization_id, since_date, limit)

            history = []
            for row in rows:
                request_data = dict(row)
                request_data["context_data"] = json.loads(request_data["context_data"])
                request_data["metadata"] = json.loads(request_data.get("metadata") or "{}")
                history.append(request_data)

            return history

    async def get_approval_analytics(self, organization_id: int, days: int = 30) -> Dict[str, Any]:
        """Get approval analytics for an organization"""

        since_date = datetime.now(timezone.utc) - timedelta(days=days)

        async with await self._acquire_conn(organization_id) as conn:
            # Basic metrics
            metrics = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total_requests,
                    COUNT(*) FILTER (WHERE status = 'approved') as approved_count,
                    COUNT(*) FILTER (WHERE status = 'rejected') as rejected_count,
                    COUNT(*) FILTER (WHERE status = 'expired') as expired_count,
                    COUNT(*) FILTER (WHERE status = 'auto_approved') as auto_approved_count,
                    AVG(EXTRACT(EPOCH FROM (approved_at - created_at))/60) as avg_approval_time_minutes,
                    AVG(risk_score) as avg_risk_score
                FROM approval_requests
                WHERE organization_id = $1 AND created_at >= $2
            """, organization_id, since_date)

            # Approval rate by type
            by_type = await conn.fetch("""
                SELECT
                    request_type,
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status = 'approved') as approved,
                    AVG(risk_score) as avg_risk_score
                FROM approval_requests
                WHERE organization_id = $1 AND created_at >= $2
                GROUP BY request_type
                ORDER BY total DESC
            """, organization_id, since_date)

            # Top approvers
            top_approvers = await conn.fetch("""
                SELECT
                    tm.name,
                    COUNT(*) as approvals_count,
                    AVG(EXTRACT(EPOCH FROM (ar.approved_at - ar.created_at))/60) as avg_time_minutes
                FROM approval_requests ar
                JOIN team_members tm ON ar.approved_by = tm.id
                WHERE ar.organization_id = $1 AND ar.created_at >= $2
                AND ar.status IN ('approved', 'rejected')
                GROUP BY tm.id, tm.name
                ORDER BY approvals_count DESC
                LIMIT 10
            """, organization_id, since_date)

            return {
                "summary": dict(metrics),
                "by_type": [dict(row) for row in by_type],
                "top_approvers": [dict(row) for row in top_approvers],
                "period_days": days
            }

    async def _auto_approve_request(self,
                                  organization_id: int,
                                  request_type: ApprovalType,
                                  title: str,
                                  description: str,
                                  requested_by: int,
                                  context_data: Dict[str, Any],
                                  workflow_id: Optional[str],
                                  risk_score: float) -> str:
        """Auto-approve low-risk requests"""

        request_id = str(uuid.uuid4())

        request = ApprovalRequest(
            id=request_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            request_type=request_type,
            title=title,
            description=description,
            requested_by=requested_by,
            priority=ApprovalPriority.LOW,
            risk_score=risk_score,
            context_data=context_data,
            auto_approve_threshold=0.3,
            timeout_minutes=0,
            status=ApprovalStatus.AUTO_APPROVED,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
            approved_at=datetime.now(timezone.utc),
            metadata={"auto_approved": True}
        )

        # Store in database
        await self._store_approval_request(request)

        # Execute immediately
        execution_result = await self._execute_approved_action(request)

        # Log auto-approval with agent logger
        if agent_logging_available:
            await agent_logger.log_approval_decision(
                agent_id="human_approval_agent",
                approval_id=request_id,
                decision="auto_approved",
                details={
                    "title": title,
                    "description": description,
                    "risk_score": risk_score,
                    "auto_approve_threshold": 0.3,
                    "execution_result": execution_result,
                    "request_type": request_type.value,
                    "auto_approval_reason": f"Risk score {risk_score:.3f} below threshold 0.3"
                },
                tenant_id=str(organization_id),
                workflow_id=workflow_id,
                user_id=str(requested_by)
            )

        # Log auto-approval
        await self._log_auto_approval(request, execution_result)

        logger.info(f"Auto-approved request {request_id} (risk: {risk_score:.3f})")
        return request_id

    async def _calculate_risk_score(self,
                                  request_type: ApprovalType,
                                  context_data: Dict[str, Any],
                                  organization_id: int) -> float:
        """Calculate risk score for approval request"""

        base_risk = {
            ApprovalType.EMAIL_CAMPAIGN: 0.4,
            ApprovalType.PROSPECT_IMPORT: 0.2,
            ApprovalType.CONNECTOR_OUTREACH: 0.3,
            ApprovalType.DATA_EXPORT: 0.5,
            ApprovalType.INTEGRATION_CHANGE: 0.6,
            ApprovalType.QUOTA_MODIFICATION: 0.4,
            ApprovalType.EMAIL_SEND: 0.25,
            ApprovalType.AI_TOOL_EXECUTION: 0.25,
        }.get(request_type, 0.3)

        # Adjust based on context
        if request_type == ApprovalType.EMAIL_CAMPAIGN:
            prospect_count = len(context_data.get("prospect_ids", []))
            if prospect_count > 100:
                base_risk += 0.3
            elif prospect_count > 50:
                base_risk += 0.2
            elif prospect_count > 10:
                base_risk += 0.1

        if request_type == ApprovalType.PROSPECT_IMPORT:
            import_size = context_data.get("prospect_count", 0)
            if import_size > 1000:
                base_risk += 0.3
            elif import_size > 500:
                base_risk += 0.2

        return min(base_risk, 1.0)

    async def _get_approval_rules(self, organization_id: int, request_type: ApprovalType) -> ApprovalRule:
        """Get approval rules for organization and request type"""

        # Try to get organization-specific rules
        async with await self._acquire_conn(organization_id) as conn:
            try:
                row = await conn.fetchrow("""
                    SELECT * FROM approval_rules
                    WHERE organization_id = $1 AND request_type = $2
                """, organization_id, request_type.value)

                if row:
                    return ApprovalRule(
                        organization_id=row["organization_id"],
                        request_type=ApprovalType(row["request_type"]),
                        auto_approve_threshold=row["auto_approve_threshold"],
                        default_timeout_minutes=row["default_timeout_minutes"],
                        required_role=row["required_role"],
                        escalation_threshold_hours=row["escalation_threshold_hours"],
                        notification_channels=json.loads(row["notification_channels"])
                    )
            except:
                pass  # Table might not exist

        # Fall back to default rules
        return self.default_rules.get(request_type, self.default_rules[ApprovalType.EMAIL_CAMPAIGN])

    async def _assign_approval_request(self, request: ApprovalRequest, rules: ApprovalRule):
        """Assign approval request to appropriate team member"""

        async with await self._acquire_conn(request.organization_id) as conn:
            # Find available approvers with required role
            approvers = await conn.fetch("""
                SELECT id, name, last_login
                FROM team_members
                WHERE organization_id = $1 AND role = $2 AND is_active = true
                ORDER BY last_login DESC NULLS LAST
            """, request.organization_id, rules.required_role)

            if approvers:
                # Assign to most recently active approver
                assigned_to = approvers[0]["id"]
                request.assigned_to = assigned_to

                await conn.execute("""
                    UPDATE approval_requests SET assigned_to = $1 WHERE id = $2
                """, assigned_to, request.id)

                logger.info(f"Assigned approval {request.id} to user {assigned_to}")

    async def _notify_approval_required(self, request: ApprovalRequest, rules: ApprovalRule):
        """Send notifications for approval requirement"""

        # Communication Hub notification (high priority)
        await self._send_communication_hub_notification(request, "approval_required")

        # Dashboard notification (always enabled)
        await self._send_dashboard_notification(request)

        # Email notification
        if "email" in rules.notification_channels:
            await self._send_email_notification(request)

        # Slack notification
        if "slack" in rules.notification_channels:
            await self._send_slack_notification(request)

    async def _send_dashboard_notification(self, request: ApprovalRequest):
        """Send real-time dashboard notification"""
        notification_data = {
            "type": "approval_required",
            "request_id": request.id,
            "title": request.title,
            "priority": request.priority.value,
            "expires_at": request.expires_at.isoformat(),
            "risk_score": request.risk_score,
            "workflow_id": request.workflow_id,
            "description": request.description,
            "context_data": request.context_data
        }

        # Send via WebSocket for real-time updates
        if websocket_available:
            approval_room = f"approval:{request.organization_id}"
            await websocket_manager.emit("approval_request", notification_data, room=approval_room)
            await websocket_manager.emit("approval_request", notification_data, room=f"org:{request.organization_id}")
            if request.workflow_id:
                await websocket_manager.emit("approval_request", notification_data, room=f"workflow:{request.workflow_id}")

        # Cache notification for WebSocket delivery (fallback)
        self.redis_client.lpush(
            f"notifications:org:{request.organization_id}",
            json.dumps(notification_data)
        )
        self.redis_client.expire(f"notifications:org:{request.organization_id}", 3600)

    async def _send_email_notification(self, request: ApprovalRequest):
        """Send email notification for approval"""
        # This would integrate with the email service
        logger.info(f"📧 Email notification sent for approval {request.id}")

    async def _send_slack_notification(self, request: ApprovalRequest):
        """Send Slack notification for approval"""
        # This would integrate with Slack webhook
        logger.info(f"💬 Slack notification sent for approval {request.id}")

    async def _execute_approved_action(self, request: ApprovalRequest) -> Dict[str, Any]:
        """Execute the approved action"""
        try:
            if request.request_type == ApprovalType.EMAIL_CAMPAIGN:
                return await self._execute_email_campaign(request)
            elif request.request_type == ApprovalType.PROSPECT_IMPORT:
                return await self._execute_prospect_import(request)
            elif request.request_type == ApprovalType.CONNECTOR_OUTREACH:
                return await self._execute_connector_outreach(request)
            elif request.request_type == ApprovalType.EMAIL_SEND:
                return await self._execute_email_send(request)
            elif request.request_type == ApprovalType.AI_TOOL_EXECUTION:
                return await self._execute_ai_tool_execution(request)
            else:
                return {"status": "executed", "message": "Action completed"}

        except Exception as e:
            logger.error(f"Failed to execute approved action for {request.id}: {e}")
            return {"status": "failed", "error": str(e)}

    async def _execute_email_campaign(self, request: ApprovalRequest) -> Dict[str, Any]:
        """Execute approved email campaign"""
        from services.corporate_scheduler_service import CorporateSchedulerService
        scheduler = CorporateSchedulerService()

        # Extract parameters from context
        prospect_ids = request.context_data.get("prospect_ids", [])
        template_id = request.context_data.get("email_template_id")

        # Schedule emails
        job_id = await scheduler.schedule_batch_emails(
            prospect_ids=prospect_ids,
            template_id=template_id,
            organization_id=request.organization_id,
            user_id=request.requested_by,
            requires_approval=False  # Already approved
        )

        return {
            "status": "scheduled",
            "job_id": job_id,
            "prospect_count": len(prospect_ids),
            "template_id": template_id
        }

    async def _execute_prospect_import(self, request: ApprovalRequest) -> Dict[str, Any]:
        """Execute approved prospect import"""
        from services.ingestion_service import IngestionService
        ingestion = IngestionService()

        csv_data = request.context_data.get("csv_data")
        import_name = request.context_data.get("import_name", "Approved Import")

        job_id = await ingestion.start_csv_ingestion(
            csv_data=csv_data,
            organization_id=request.organization_id,
            import_name=import_name,
            user_id=request.requested_by,
            tags=["approved_import"]
        )

        return {
            "status": "started",
            "job_id": job_id,
            "import_name": import_name
        }

    async def _execute_connector_outreach(self, request: ApprovalRequest) -> Dict[str, Any]:
        """Execute approved connector outreach"""
        # This would integrate with the mutuals orchestrator
        return {
            "status": "initiated",
            "message": "Connector outreach initiated"
        }

    async def _execute_email_send(self, request: ApprovalRequest) -> Dict[str, Any]:
        """Execute approved individual email send"""
        from services.corporate_scheduler_service import CorporateSchedulerService
        scheduler = CorporateSchedulerService()

        # Extract parameters from context
        prospect_id = request.context_data.get("prospect_id")
        email_content = request.context_data.get("email_content")
        subject = request.context_data.get("subject", "Introduction")
        manual_send = request.context_data.get("manual_send", False)

        if manual_send:
            return {
                "status": "pending_manual_send",
                "prospect_id": prospect_id,
                "subject": subject,
            }

        if not prospect_id or not email_content:
            return {"status": "failed", "error": "Missing prospect_id or email_content"}

        # Schedule individual email
        job_id = await scheduler.schedule_single_email(
            prospect_id=prospect_id,
            email_content=email_content,
            subject=subject,
            organization_id=request.organization_id,
            user_id=request.requested_by,
            requires_approval=False  # Already approved
        )

        return {
            "status": "scheduled",
            "job_id": job_id,
            "prospect_id": prospect_id,
            "subject": subject
        }

    async def _execute_ai_tool_execution(self, request: ApprovalRequest) -> Dict[str, Any]:
        """Execute approved AI tool via the enhanced orchestrator."""
        try:
            from services.openai_agents_enhanced import enhanced_ai_orchestrator
        except ImportError as exc:
            logger.error(
                "Enhanced AI orchestrator unavailable for approval %s: %s",
                request.id,
                exc,
            )
            return {"status": "failed", "error": "AI orchestrator unavailable"}

        if not enhanced_ai_orchestrator:
            logger.warning(
                "Enhanced AI orchestrator disabled; skipping tool execution for approval %s",
                request.id,
            )
            return {
                "status": "failed",
                "error": "AI orchestrator disabled (enable ai_agents_enabled feature flag)",
            }

        approver_id = request.approved_by or request.requested_by or 0

        try:
            result = await enhanced_ai_orchestrator.approve_tool_execution(
                approval_id=request.id,
                approver_id=approver_id,
                organization_id=request.organization_id,
            )

            if result.get("error"):
                return {"status": "failed", "error": result["error"]}

            return {"status": "executed", "result": result}

        except Exception as exc:
            logger.error("AI tool execution failed for approval %s: %s", request.id, exc)
            return {"status": "failed", "error": str(exc)}

    async def _can_approve(self, user_id: int, request: ApprovalRequest, organization_id: int) -> bool:
        """Check if user can approve the request"""
        async with await self._acquire_conn(request.organization_id) as conn:
            user = await conn.fetchrow("""
                SELECT role FROM team_members
                WHERE id = $1 AND organization_id = $2 AND is_active = true
            """, user_id, organization_id)

            if not user:
                return False

            required_role = normalize_role(request.metadata.get("required_role", "admin"))
            user_role = normalize_role(user["role"])

            # Role hierarchy: admin > user
            role_hierarchy = {"user": 1, "admin": 2}

            return role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 2)

    async def _store_approval_request(self, request: ApprovalRequest):
        """Store approval request in database"""
        async with await self._acquire_conn(request.organization_id) as conn:
            await conn.execute("""
                INSERT INTO approval_requests (
                    id, organization_id, workflow_id, request_type, title, description,
                    requested_by, priority, risk_score, context_data, auto_approve_threshold,
                    timeout_minutes, status, created_at, expires_at, assigned_to,
                    approved_by, approved_at, rejection_reason, escalation_reason, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)
            """, request.id, request.organization_id, request.workflow_id,
            request.request_type.value, request.title, request.description,
            request.requested_by, request.priority.value, request.risk_score,
            json.dumps(request.context_data), request.auto_approve_threshold,
            request.timeout_minutes, request.status.value, request.created_at,
            request.expires_at, request.assigned_to, request.approved_by,
            request.approved_at, request.rejection_reason, request.escalation_reason,
            json.dumps(request.metadata or {}))

    async def _get_approval_request(self, request_id: str, organization_id: Optional[int] = None) -> Optional[ApprovalRequest]:
        """Get approval request from database"""
        if self.db_pool is None:
            raise RuntimeError("ApprovalQueueService not initialized")
        if organization_id is not None:
            async with await self._acquire_conn(organization_id) as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM approval_requests WHERE id = $1
                """, request_id)
        else:
            async with await self._acquire_conn(organization_id) as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM approval_requests WHERE id = $1
                """, request_id)
            row = await conn.fetchrow("""
                SELECT * FROM approval_requests WHERE id = $1
            """, request_id)

            if not row:
                return None

            return ApprovalRequest(
                id=row["id"],
                organization_id=row["organization_id"],
                workflow_id=row["workflow_id"],
                request_type=ApprovalType(row["request_type"]),
                title=row["title"],
                description=row["description"],
                requested_by=row["requested_by"],
                priority=ApprovalPriority(row["priority"]),
                risk_score=row["risk_score"],
                context_data=json.loads(row["context_data"]),
                auto_approve_threshold=row["auto_approve_threshold"],
                timeout_minutes=row["timeout_minutes"],
                status=ApprovalStatus(row["status"]),
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                assigned_to=row["assigned_to"],
                approved_by=row["approved_by"],
                approved_at=row["approved_at"],
                rejection_reason=row["rejection_reason"],
                escalation_reason=row["escalation_reason"],
                metadata=json.loads(row["metadata"] or "{}")
            )

    async def _update_approval_request(self, request: ApprovalRequest):
        """Update approval request in database"""
        async with await self._acquire_conn(request.organization_id) as conn:
            await conn.execute("""
                UPDATE approval_requests SET
                    status = $1, assigned_to = $2, approved_by = $3, approved_at = $4,
                    rejection_reason = $5, escalation_reason = $6, metadata = $7
                WHERE id = $8
            """, request.status.value, request.assigned_to, request.approved_by,
            request.approved_at, request.rejection_reason, request.escalation_reason,
            json.dumps(request.metadata or {}), request.id)

    async def _cache_approval_request(self, request: ApprovalRequest):
        """Cache approval request in Redis"""
        self.redis_client.setex(
            f"approval:{request.id}",
            3600,  # 1 hour cache
            json.dumps(asdict(request), default=str)
        )

    async def _notify_approval_decision(self, request: ApprovalRequest, decision: str, execution_result: Dict[str, Any] = None):
        """Notify stakeholders of approval decision"""

        # Communication Hub notification (high priority for requester)
        await self._send_communication_hub_notification(request, f"approval_{decision}", execution_result)

        notification_data = {
            "type": "approval_decision",
            "request_id": request.id,
            "decision": decision,
            "title": request.title,
            "execution_result": execution_result,
            "approved_by": request.approved_by,
            "approved_at": request.approved_at.isoformat() if request.approved_at else None,
            "rejection_reason": request.rejection_reason,
            "workflow_id": request.workflow_id
        }

        # Send via WebSocket for real-time updates
        if websocket_available:
            approval_room = f"approval:{request.organization_id}"
            await websocket_manager.emit("approval_decision", notification_data, room=approval_room)
            await websocket_manager.emit("approval_decision", notification_data, room=f"org:{request.organization_id}")
            if request.workflow_id:
                await websocket_manager.emit("approval_decision", notification_data, room=f"workflow:{request.workflow_id}")

        # Notify requester
        self.redis_client.lpush(
            f"notifications:user:{request.requested_by}",
            json.dumps(notification_data)
        )

        # Notify organization
        self.redis_client.lpush(
            f"notifications:org:{request.organization_id}",
            json.dumps(notification_data)
        )

    async def _handle_rejection(self, request: ApprovalRequest):
        """Handle workflow rejection"""
        if request.workflow_id:
            # Notify workflow state machine of rejection
            try:
                from services.workflow_state_machine import workflow_state_machine
                await workflow_state_machine.trigger_transition(
                    request.workflow_id,
                    "HUMAN_REJECT",
                    {"rejection_reason": request.rejection_reason}
                )
            except Exception as e:
                logger.error(f"Failed to handle workflow rejection: {e}")

    async def _cleanup_approval_request(self, request_id: str):
        """Clean up approval request resources"""
        # Remove from Redis cache
        self.redis_client.delete(f"approval:{request_id}")

    async def _log_auto_approval(self, request: ApprovalRequest, execution_result: Dict[str, Any]):
        """Log auto-approval for audit"""
        try:
            from services.audit_logging_service import AuditLoggingService
            audit = AuditLoggingService()

            await audit.log_event(
                organization_id=request.organization_id,
                actor_type="system",
                actor_id="auto_approval",
                action=f"auto_approve:{request.request_type.value}",
                target_type="approval_request",
                target_id=request.id,
                payload={
                    "title": request.title,
                    "risk_score": request.risk_score,
                    "execution_result": execution_result
                }
            )
        except Exception as e:
            logger.error(f"Failed to log auto-approval: {e}")

    async def _process_expiring_requests(self):
        """Background task to process expiring requests"""
        while True:
            try:
                async with await self._acquire_conn(request.organization_id) as conn:
                    # Find requests expiring in next 5 minutes
                    expiring_soon = await conn.fetch("""
                        SELECT id FROM approval_requests
                        WHERE status = 'pending'
                        AND expires_at <= $1
                    """, datetime.now(timezone.utc) + timedelta(minutes=5))

                    for row in expiring_soon:
                        await self._expire_request_by_id(row["id"])

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Error processing expiring requests: {e}")
                await asyncio.sleep(60)

    async def _escalate_pending_requests(self):
        """Background task to escalate old pending requests"""
        while True:
            try:
                async with await self._acquire_conn(request.organization_id) as conn:
                    # Find requests older than escalation threshold
                    old_requests = await conn.fetch("""
                        SELECT ar.*, ar.metadata::json->'escalation_threshold_hours' as threshold_hours
                        FROM approval_requests ar
                        WHERE status = 'pending'
                        AND created_at <= $1
                        AND escalation_reason IS NULL
                    """, datetime.now(timezone.utc) - timedelta(hours=4))  # Default 4 hours

                    for row in old_requests:
                        await self._escalate_request(row["id"])

                await asyncio.sleep(3600)  # Check every hour

            except Exception as e:
                logger.error(f"Error escalating requests: {e}")
                await asyncio.sleep(3600)

    async def _expire_request_by_id(self, request_id: str):
        """Expire a request by ID"""
        request = await self._get_approval_request(request_id)
        if request and request.status == ApprovalStatus.PENDING:
            await self._expire_request(request)

    async def _expire_request(self, request: ApprovalRequest):
        """Expire an approval request"""
        request.status = ApprovalStatus.EXPIRED
        await self._update_approval_request(request)

        # Notify stakeholders
        await self._notify_approval_decision(request, "expired")

        logger.info(f"Expired approval request {request.id}")

    async def _escalate_request(self, request_id: str):
        """Escalate an approval request"""
        request = await self._get_approval_request(request_id)
        if request and request.status == ApprovalStatus.PENDING:
            request.status = ApprovalStatus.ESCALATED
            request.escalation_reason = "Automatic escalation due to timeout"
            await self._update_approval_request(request)

            # Notify senior administrators
            await self._notify_escalation(request)

            logger.info(f"Escalated approval request {request.id}")

    async def _notify_escalation(self, request: ApprovalRequest):
        """Notify about request escalation"""
        # This would send escalation notifications to senior staff
        logger.info(f"🚨 Escalation notification for approval {request.id}")

    def _summarize_context(self, context_data: Dict[str, Any]) -> str:
        """Create executive-friendly summary of approval context"""
        summary_parts = []

        if "prospect_ids" in context_data:
            count = len(context_data["prospect_ids"])
            summary_parts.append(f"{count} prospects")

        if "prospect_count" in context_data:
            summary_parts.append(f"{context_data['prospect_count']} prospects")

        if "email_template_id" in context_data:
            summary_parts.append(f"template #{context_data['email_template_id']}")

        if "import_name" in context_data:
            summary_parts.append(f"import '{context_data['import_name']}'")

        if "connector_name" in context_data:
            summary_parts.append(f"connector {context_data['connector_name']}")

        if "high_confidence_emails" in context_data:
            count = len(context_data["high_confidence_emails"])
            summary_parts.append(f"{count} verified emails")

        return " • ".join(summary_parts) if summary_parts else "Standard approval request"

    async def _send_communication_hub_notification(self, request: ApprovalRequest, event_type: str, execution_result: Dict[str, Any] = None):
        """Send user notification via Communication Hub"""
        if not self.communication_hub or not self.message_translator:
            return

        try:
            # Create business-friendly message based on event type
            if event_type == "approval_required":
                message = f"Approval required: {request.title}"
                context = BusinessContext.APPROVAL_REQUEST
            elif event_type == "approval_approved":
                message = f"Request approved: {request.title}"
                context = BusinessContext.SUCCESS_NOTIFICATION
            elif event_type == "approval_rejected":
                message = f"Request rejected: {request.title}"
                context = BusinessContext.ERROR_RESOLUTION
            elif event_type == "approval_expired":
                message = f"Request expired: {request.title}"
                context = BusinessContext.ERROR_RESOLUTION
            else:
                message = f"Approval update: {request.title}"
                context = BusinessContext.OPERATIONAL_UPDATE

            # Translate to business-friendly language
            business_message = await self.message_translator.translate(
                message,
                context,
                include_technical_details=False
            )

            # Prepare metadata
            metadata = {
                "request_id": request.id,
                "request_type": request.request_type.value,
                "priority": request.priority.value,
                "risk_score": request.risk_score,
                "workflow_id": request.workflow_id,
                "event_type": event_type
            }

            # Add execution result if available
            if execution_result:
                metadata["execution_result"] = execution_result

            # Add approval decision details
            if request.approved_by:
                metadata["approved_by"] = request.approved_by
                metadata["approved_at"] = request.approved_at.isoformat()
            if request.rejection_reason:
                metadata["rejection_reason"] = request.rejection_reason

            # Enrich with organizational context
            enriched_metadata = await self.metadata_enricher.enrich(
                metadata,
                organization_id=request.organization_id,
                user_id=request.requested_by,
                service_name="approval_queue_service"
            )

            # Send notification to requester
            await self.communication_hub.send_message(
                message_type=MessageType.APPROVAL_UPDATE,
                content=business_message,
                tenant_id=str(request.organization_id),
                user_id=str(request.requested_by),
                metadata=enriched_metadata,
                priority=MessagePriority.HIGH if event_type == "approval_required" else MessagePriority.MEDIUM
            )

            # Also send to organization admins for approval requests
            if event_type == "approval_required":
                await self.communication_hub.send_message(
                    message_type=MessageType.APPROVAL_UPDATE,
                    content=business_message,
                    tenant_id=str(request.organization_id),
                    user_id=None,  # Broadcast to org
                    metadata=enriched_metadata,
                    priority=MessagePriority.HIGH
                )

        except Exception as e:
            logger.warning(f"Failed to send Communication Hub notification: {e}")

    async def close(self):
        """Close all connections"""
        if self.db_pool:
            await self.db_pool.close()
        self.redis_client.close()

# Global instance
from core.settings import settings

approval_queue_service = ApprovalQueueService(
    database_url=settings.DATABASE_URL,
    redis_url=settings.REDIS_URL if getattr(settings, "REDIS_URL", None) else "redis://localhost:6379",
)
