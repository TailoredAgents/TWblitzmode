"""
Master Chat Agent - Central Conversation Interface for Tallwave Link
Provides unified chat interface with LinkedIn cookie handling, multi-agent orchestration,
and secure credential management.

Features:
- Session state management with user/org context
- LinkedIn cookie detection, verification, and secure storage
- Multi-agent workflow orchestration
- Web search with citation tracking
- Command routing for natural language interactions
- Comprehensive security filtering and audit logging
"""

import asyncio
import hashlib
import json
import logging
import re
import secrets
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Iterable, Union

from core.roles import normalize_role

from services.agent_logger import agent_logger, AgentEventType, LogLevel
from services.chat_audit_logger import chat_audit_logger, AuditEventType
from services.idempotency_service import idempotency_service
from services.conversational_prospects import conversational_prospects
from services.database import db
from services.link_tallwave_knowledge_base import LinkKnowledgeBase, KnowledgeResult
try:
    from services.workflow_coordinator import workflow_coordinator
    WORKFLOW_COORDINATOR_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - optional dependency
    workflow_coordinator = None  # type: ignore
    WORKFLOW_COORDINATOR_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "Workflow coordinator unavailable; advanced workflow features disabled: %s",
        exc,
    )
try:
    from api.db_core import get_conn as portal_get_conn, query as portal_query
    PORTAL_DB_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - optional dependency
    portal_get_conn = None  # type: ignore
    portal_query = None  # type: ignore
    PORTAL_DB_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "Portal database utilities unavailable; portal-specific features disabled: %s",
        exc,
    )
try:
    from services.cookie_vault_service import cookie_vault
    COOKIE_VAULT_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - optional dependency
    cookie_vault = None  # type: ignore
    COOKIE_VAULT_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "Cookie vault service unavailable; vault features disabled: %s",
        exc,
    )

try:
    from services.secure_cookie_vault import secure_cookie_vault, CookieType, CookieStatus
    SECURE_COOKIE_VAULT_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - optional dependency
    secure_cookie_vault = None  # type: ignore
    CookieType = None  # type: ignore
    CookieStatus = None  # type: ignore
    SECURE_COOKIE_VAULT_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "Secure cookie vault unavailable; per-user cookie insights disabled: %s",
        exc,
    )

try:
    from services.chat_security_filter import chat_security_filter, SecurityLevel, ViolationType  # type: ignore
    SECURITY_FILTER_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    SECURITY_FILTER_AVAILABLE = False

    class SecurityLevel(Enum):
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"

    class ViolationType(Enum):
        NONE = "none"

    class _SecurityResult:
        __slots__ = ("filtered_text", "violations", "enforcement_action")

        def __init__(self, text: str):
            self.filtered_text = text
            self.violations: List[Any] = []
            self.enforcement_action: Optional[str] = None

    class _SecurityFilterStub:
        def filter_response(self, text: str, *_args, **_kwargs) -> _SecurityResult:
            return _SecurityResult(text)

    chat_security_filter = _SecurityFilterStub()

try:
    from services.chat_tool_registry import chat_tool_registry, ToolCategory, ConfirmationLevel  # type: ignore
    TOOL_REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    TOOL_REGISTRY_AVAILABLE = False

    class ToolCategory(Enum):
        GENERAL = "general"

    class ConfirmationLevel(Enum):
        NONE = "none"
        LOW = "low"
        HIGH = "high"

    class _ToolRegistryStub:
        def __init__(self):
            self.tools: Dict[str, Dict[str, Any]] = {}

        def get_available_tools(
            self,
            category: Optional[Any] = None,
            user_role: Optional[str] = None,
        ) -> List[Dict[str, Any]]:
            return []

        async def confirm_execution(self, *_args, **_kwargs) -> Dict[str, Any]:
            return {"status": "unavailable", "message": "Tool registry not available"}

        def get_tool_suggestions(self, *_args, **_kwargs) -> List[Dict[str, Any]]:
            return []

        async def execute_tool(self, *_args, **_kwargs) -> Dict[str, Any]:
            return {"success": False, "message": "Tool registry not available"}

    chat_tool_registry = _ToolRegistryStub()

try:
    from services.conversation_context_manager import conversation_context_manager, ContextImportance  # type: ignore
    CONTEXT_MANAGER_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    CONTEXT_MANAGER_AVAILABLE = False

    class ContextImportance(Enum):
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"

    class _ConversationContextManagerStub:
        def __init__(self):
            self.current_session_id: Optional[str] = None
            self.conversation_turns: List[Any] = []
            self.entities: Dict[str, Any] = {}
            self.topic_clusters: Dict[str, Any] = {}
            self.conversation_summaries: Dict[str, Any] = {}

        async def start_session(self, session_id: str):
            self.current_session_id = session_id

        async def add_conversation_turn(self, *_args, **_kwargs):
            return None

        async def get_conversation_context(self, *_args, **_kwargs) -> Dict[str, Any]:
            return {}

        async def generate_conversation_summary(self, *_args, **_kwargs) -> str:
            return "Summary not available."

    conversation_context_manager = _ConversationContextManagerStub()

try:
    from services.redis_service import redis_service  # type: ignore
    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    REDIS_AVAILABLE = False

    class _RedisClientStub:
        async def zadd(self, *_args, **_kwargs):
            return 0

        async def zremrangebyscore(self, *_args, **_kwargs):
            return 0

        async def expire(self, *_args, **_kwargs):
            return False

        async def zcard(self, *_args, **_kwargs):
            return 0

    class _RedisServiceStub:
        def __init__(self):
            self.is_connected = False
            self.client = _RedisClientStub()
            self._store: Dict[str, Any] = {}

        async def set(self, key: str, value: Any, ex: Optional[int] = None):
            self._store[key] = value
            return True

        async def get(self, key: str):
            return self._store.get(key)

        async def delete(self, key: str):
            self._store.pop(key, None)
            return True

    redis_service = _RedisServiceStub()

try:
    from services.subscription_feature_service import subscription_feature_service  # type: ignore
    SUBSCRIPTION_SERVICE_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    SUBSCRIPTION_SERVICE_AVAILABLE = False

    class _SubscriptionFeatureStub:
        def get_features_for_tenant(self, *_args, **_kwargs) -> Dict[str, bool]:
            return {}

    subscription_feature_service = _SubscriptionFeatureStub()

try:
    from services.cookie_collection_workflow import cookie_collection_workflow  # type: ignore
    COOKIE_COLLECTION_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    COOKIE_COLLECTION_AVAILABLE = False

    class _CookieCollectionStub:
        async def collect_for_org(self, *_, **__):
            return {
                "counts": {"total_team_members": 0, "valid": 0},
                "missing_members": [],
                "rotation_required": [],
                "expiring_soon": [],
                "missing_vault": 0,
                "missing_preview": None,
                "team_status": {},
                "user_summaries": {},
                "events_logged": 0,
            }

    cookie_collection_workflow = _CookieCollectionStub()

logger = logging.getLogger(__name__)

class SessionStatus(Enum):
    """Session status tracking"""
    ACTIVE = "active"
    WORKFLOW_RUNNING = "workflow_running"
    AWAITING_INPUT = "awaiting_input"
    EXPIRED = "expired"

class CommandType(Enum):
    """Available command types"""
    HELP = "help"
    SUMMARY = "summary"
    CONTEXT = "context"
    HISTORY = "history"
    HISTORY_EXPORT = "history_export"
    ADD_PROSPECT = "add_prospect"
    PROCESS_PROSPECT = "process_prospect"
    STATUS = "status"
    RESET = "reset"
    COOKIE_SUBMISSION = "cookie_submission"
    WEB_SEARCH = "web_search"
    TOOL_EXECUTION = "tool_execution"
    TOOL_CONFIRMATION = "tool_confirmation"
    LIST_TOOLS = "list_tools"
    VAULT_AUDIT = "vault_audit"
    COOKIE_STATUS = "cookie_status"
    COLLECT_COOKIES = "collect_cookies"
    CLEAR = "clear"
    UNKNOWN = "unknown"

@dataclass
class SessionState:
    """Session state for Master Agent conversations"""
    session_id: str
    user_id: int
    organization_id: int
    status: SessionStatus = SessionStatus.ACTIVE
    prospect_data: Optional[Dict] = None
    workflow_id: Optional[str] = None
    cookie_status: Optional[str] = None
    verified_profile: Optional[Dict] = None
    citations: Optional[List[Dict]] = None
    conversation_context: Optional[Dict] = None
    pending_tool_execution: Optional[str] = None  # Tool execution ID awaiting confirmation
    tool_suggestion_context: Optional[Dict] = None  # Context for tool suggestions
    tenant_id: Optional[str] = None
    subscription_tier: Optional[str] = None
    user_role: Optional[str] = None
    feature_flags: Optional[Dict[str, bool]] = None
    # Enhanced workflow tracking fields
    active_workflow_type: Optional[str] = None
    workflow_step: Optional[str] = None
    workflow_context: Optional[Dict] = None
    prospect_id: Optional[int] = None
    workflow_status: Optional[str] = None
    last_workflow_update: Optional[datetime] = None
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.last_activity is None:
            self.last_activity = datetime.now(timezone.utc)
        if self.citations is None:
            self.citations = []
        if self.conversation_context is None:
            self.conversation_context = {}
        if self.workflow_context is None:
            self.workflow_context = {}
        if self.feature_flags is None:
            self.feature_flags = {}

class MasterChatAgent:
    """
    Master Chat Agent for Tallwave Link - central conversation interface.

    Handles all user interactions through natural language, integrating with
    Tallwave services for prospect management, LinkedIn integration,
    and multi-agent workflows.
    """

    def __init__(self):
        self.sessions: Dict[str, SessionState] = {}
        self.session_timeout_hours = 24
        self.knowledge_base = LinkKnowledgeBase()
        self.system_prompt = self.knowledge_base.system_prompt

        # Enhanced rate limiting per user/organization
        self.rate_limits = {
            "messages_per_minute": 30,
            "messages_per_hour": 200,
            "messages_per_day": 1000
        }
        self.rate_limit_tracking: Dict[str, List[datetime]] = {}
        self.security_violation_tracking: Dict[str, List[Tuple[datetime, str]]] = {}
        self.security_violation_limits = {
            "window_minutes": 15,
            "max_high": 3,
            "max_critical": 1
        }
        self.suspended_sessions: Dict[str, datetime] = {}

        # Tenant isolation settings
        self.tenant_isolation_enabled = True
        self.max_sessions_per_user = 5
        self.max_sessions_per_org = 100

        # Security configuration
        self.security_level = SecurityLevel.HIGH
        self.enable_audit_logging = True

        # Legacy patterns kept for backward compatibility
        self.sensitive_patterns = [
            r"sk-[a-zA-Z0-9-_]{32,}",  # OpenAI API keys
            r"Bearer\s+[a-zA-Z0-9-_.]+",  # Bearer tokens
            r"[a-zA-Z0-9]{32,}",  # Generic long tokens (when flagged)
            r"password[\"']?\s*[:=]\s*[\"'][^\"']+[\"']",  # Password fields
            r"api[_-]?key[\"']?\s*[:=]\s*[\"'][^\"']+[\"']",  # API key fields
        ]

        # Command patterns for natural language detection
        self.command_patterns = {
            CommandType.HELP: [
                r"/help", r"help", r"what can you do", r"commands", r"guide", r"instructions"
            ],
            CommandType.SUMMARY: [
                r"/summary", r"/summarize", r"summary", r"summarize", r"conversation summary",
                r"what have we discussed", r"recap", r"review conversation"
            ],
            CommandType.CONTEXT: [
                r"/context", r"context", r"conversation context", r"current context",
                r"what do you remember", r"conversation history"
            ],
            CommandType.HISTORY: [
                r"/history", r"history", r"conversation history", r"previous messages",
                r"what we talked about", r"past conversation"
            ],
            CommandType.HISTORY_EXPORT: [
                r"/export", r"export history", r"download conversation", r"export chat",
                r"export session", r"save conversation", r"download history"
            ],
            CommandType.CLEAR: [
                r"/clear", r"clear", r"clear conversation", r"clear history",
                r"start fresh", r"forget everything"
            ],
            CommandType.ADD_PROSPECT: [
                r"add\s+(?:a\s+)?(?:new\s+)?prospect", r"add\s+(?:a\s+)?(?:new\s+)?target",
                r"new\s+prospect", r"create\s+prospect", r"add\s+someone"
            ],
            CommandType.PROCESS_PROSPECT: [
                r"process\s+prospect", r"start\s+workflow", r"find\s+introducers",
                r"launch\s+workflow", r"begin\s+process"
            ],
            CommandType.STATUS: [
                r"/status", r"status", r"progress", r"what'?s\s+happening", r"check\s+status",
                r"workflow\s+status", r"current\s+status"
            ],
            CommandType.RESET: [
                r"/reset", r"reset", r"start\s+over", r"clear\s+session", r"new\s+session"
            ],
            CommandType.LIST_TOOLS: [
                r"/tools", r"list\s+tools", r"available\s+tools", r"what\s+tools", r"show\s+tools",
                r"capabilities", r"functions"
            ],
            CommandType.VAULT_AUDIT: [
                r"/vault", r"vault\s+status", r"show\s+cookies", r"vault\s+audit",
                r"cookie\s+vault"
            ],
            CommandType.COOKIE_STATUS: [
                r"(?:check|show)\s+(?:my\s+|our\s+)?cookie\s+status",
                r"confirm\s+(?:the\s+)?cookie\s+upload",
                r"did\s+(?:my|our)\s+cookie\s+(?:upload|work)",
                r"linkedin\s+cookie\s+(?:status|ok|good)",
                r"cookie\s+health",
            ],
            CommandType.COLLECT_COOKIES: [
                r"collect\s+(?:org(?:anization)?\s+)?cookies",
                r"aggregate\s+(?:team|org)\s+cookies",
                r"cookie\s+(?:collection|aggregation)",
                r"refresh\s+(?:all\s+)?cookies"
            ],
            CommandType.TOOL_CONFIRMATION: [
                r"yes", r"confirm", r"proceed", r"do\s+it", r"execute",
                r"no", r"cancel", r"abort", r"stop"
            ]
        }

        self.capability_labels = {
            "cookie_vault_admin": "viewing the LinkedIn cookie vault",
            "cookie_collection": "running organization-wide cookie collection",
        }

        logger.info("MasterChatAgent initialized with session management and security filtering")

    async def respond(
        self,
        user_id: int,
        organization_id: int,
        session_id: Optional[str],
        message: str
    ) -> Dict[str, Any]:
        """
        Main entry point for Master Agent conversations

        Args:
            user_id: User identifier
            organization_id: Organization/tenant identifier
            session_id: Optional session ID for continuity
            message: User message content

        Returns:
            Response dictionary with reply and session information
        """
        try:
            start_time = time.time()  # Track processing time

            # Enhanced tenant validation
            if not await self._validate_tenant_access(user_id, organization_id):
                await chat_audit_logger.log_tenant_violation(
                    organization_id, user_id,
                    {"reason": "invalid_tenant_credentials", "message": message[:100]}
                )
                return {
                    "reply": "Access denied. Invalid tenant credentials.",
                    "session_id": session_id,
                    "status": "error",
                    "error": "Tenant validation failed",
                    "code": "tenant_access_denied",
                    "hint": "Please sign out and back in or contact your administrator to confirm access."
                }

            # Rate limiting check
            rate_limit_result = await self._check_rate_limits(user_id, organization_id)
            if not rate_limit_result["allowed"]:
                await chat_audit_logger.log_rate_limit_exceeded(
                    organization_id, user_id,
                    rate_limit_result.get("limit_type", "unknown"),
                    rate_limit_result.get("current_count", 0),
                    rate_limit_result.get("limit_value", 0)
                )
                return {
                    "reply": f"Rate limit exceeded. {rate_limit_result['message']}",
                    "session_id": session_id,
                    "status": "error",
                    "error": "Rate limit exceeded",
                    "code": "rate_limit_exceeded",
                    "hint": "Pause for a moment before sending another message so Link remains responsive."
                }

            # Generate session ID if not provided
            if not session_id:
                session_id = f"master_{user_id}_{int(time.time())}_{secrets.token_hex(8)}"

            suspension_key = f"{organization_id}:{user_id}"
            suspension_until = self.suspended_sessions.get(suspension_key)

            if suspension_until is None:
                suspension_until = await self._load_suspension_from_store(suspension_key)
                if suspension_until:
                    self.suspended_sessions[suspension_key] = suspension_until

            if suspension_until:
                now = datetime.now(timezone.utc)
                if suspension_until > now:
                    wait_minutes = max(int((suspension_until - now).total_seconds() // 60), 1)
                    return {
                        "reply": (
                            "Access temporarily suspended due to repeated security violations. "
                            f"Please retry in about {wait_minutes} minute(s) or contact an administrator."
                        ),
                        "session_id": session_id,
                        "status": "error",
                        "error": "session_suspended",
                        "code": "security_suspended",
                        "hint": "Remove any secrets from the chat history and try again once the suspension expires."
                    }
                # Suspension expired, remove marker locally and in persistent store
                self.suspended_sessions.pop(suspension_key, None)
                await self._clear_suspension_in_store(suspension_key)

            # Get or create session with enhanced validation
            session, session_event = await self._get_or_create_session(
                session_id, user_id, organization_id
            )

            # Update session activity
            session.last_activity = datetime.now(timezone.utc)

            # Ensure subscription and role metadata is available
            await self._ensure_session_entitlements(session)

            # Initialize conversation context if needed
            await self._ensure_context_session(session_id, user_id, organization_id)

            # Add user message to context
            await conversation_context_manager.add_conversation_turn(
                speaker="user",
                message=message,
                message_type="query",
                metadata={
                    "user_id": user_id,
                    "organization_id": organization_id,
                    "session_id": session_id
                }
            )

            # Detect and route command
            command_type = self._detect_command(message)

            # Route to appropriate handler
            if command_type == CommandType.HELP:
                response = await self._handle_help(session, message)
            elif command_type == CommandType.SUMMARY:
                response = await self._handle_summary(session, message)
            elif command_type == CommandType.CONTEXT:
                response = await self._handle_context(session, message)
            elif command_type == CommandType.HISTORY:
                response = await self._handle_history(session, message)
            elif command_type == CommandType.HISTORY_EXPORT:
                response = await self._handle_history_export(session, message)
            elif command_type == CommandType.CLEAR:
                response = await self._handle_clear(session, message)
            elif command_type == CommandType.ADD_PROSPECT:
                response = await self._handle_add_prospect(session, message)
            elif command_type == CommandType.PROCESS_PROSPECT:
                response = await self._handle_process_prospect(session, message)
            elif command_type == CommandType.STATUS:
                response = await self._handle_status(session, message)
            elif command_type == CommandType.RESET:
                response = await self._handle_reset(session, message)
            elif command_type == CommandType.LIST_TOOLS:
                response = await self._handle_list_tools(session, message)
            elif command_type == CommandType.VAULT_AUDIT:
                response = await self._handle_vault_audit(session, message)
            elif command_type == CommandType.COOKIE_STATUS:
                response = await self._handle_cookie_status(session, message)
            elif command_type == CommandType.COLLECT_COOKIES:
                response = await self._handle_collect_org_cookies(session, message)
            elif command_type == CommandType.TOOL_CONFIRMATION:
                response = await self._handle_tool_confirmation(session, message)
            else:
                # Check for LinkedIn cookie submission
                cookie_data = self._detect_linkedin_cookie(message)
                if cookie_data:
                    response = await self._handle_cookie_submission(session, cookie_data, message)
                else:
                    # Check if in active conversation flow
                    response = await self._handle_conversation_flow(session, message)
                    if not response:
                        # Check for tool suggestions and execution
                        tool_response = await self._handle_tool_suggestion(session, message)
                        if tool_response:
                            response = tool_response
                        else:
                            # Default to informational query or web search
                            response = await self._handle_informational_query(session, message)

            security_result = chat_security_filter.filter_response(
                response, organization_id, user_id, "chat_response"
            )

            warning_text, enforcement_action = await self._process_security_violations(session, security_result)

            filtered_response = security_result.filtered_text
            if warning_text:
                filtered_response = f"{filtered_response}\n\n{warning_text}"

            if session_event == "session_expired_restarted":
                filtered_response = (
                    "⚠️ Session expired after extended inactivity. I've started a fresh session and cleared cached "
                    "context to keep things secure.\n\n"
                    f"{filtered_response}"
                )
            elif session_event == "session_reinitialized_conflict":
                filtered_response = (
                    "ℹ️ I noticed another active session for this account and secured a fresh chat session. "
                    "Let me know if you need to reload prior context.\n\n"
                    f"{filtered_response}"
                )

            final_reply = filtered_response
            response_status = "success"
            error_code = None
            session_status_value = session.status.value
            response_hint = warning_text if warning_text else None
            response_code = "ok"

            if enforcement_action:
                final_reply = enforcement_action["reply"]
                response_status = enforcement_action.get("status", "error")
                error_code = enforcement_action.get("error")
                session_status_value = enforcement_action.get("session_status", session.status.value)
                response_hint = enforcement_action.get("hint", response_hint)
                response_code = enforcement_action.get("code", error_code or "security_event")
            elif warning_text:
                response_code = "ok_with_warning"

            await conversation_context_manager.add_conversation_turn(
                speaker="agent",
                message=final_reply,
                message_type="response",
                metadata={
                    "user_id": user_id,
                    "organization_id": organization_id,
                    "session_id": session_id,
                    "command_type": command_type.value if 'command_type' in locals() else None,
                    "security_violations": len(security_result.violations) if security_result.violations else 0
                }
            )

            audit_event_id = await chat_audit_logger.log_interaction(
                organization_id=organization_id,
                user_id=user_id,
                session_id=session_id,
                user_message=message,
                agent_response=final_reply,
                security_result=security_result,
                processing_time_ms=int((time.time() - start_time) * 1000) if 'start_time' in locals() else None,
                command_type=command_type.value if 'command_type' in locals() else None
            )

            await self._audit_interaction(session, message, final_reply, security_result)

            response_payload = {
                "reply": final_reply,
                "session_id": session_id,
                "status": response_status,
                "session_status": session_status_value,
                "citations": session.citations[-5:] if session.citations else [],
                "workflow_id": session.workflow_id,
                "code": response_code if response_status == "success" else error_code
            }

            if error_code:
                response_payload["error"] = error_code
            if response_hint:
                response_payload["hint"] = response_hint

            return response_payload

        except Exception as e:
            logger.error(f"Error in MasterChatAgent.respond: {e}")

            # Audit log the error
            try:
                await agent_logger.log_event(
                    event_type=AgentEventType.AGENT_ERROR,
                    level=LogLevel.ERROR,
                    agent_id="master_chat_agent",
                    session_id=session_id or "unknown",
                    details={
                        "error": str(e),
                        "user_message_length": len(message),
                        "organization_id": organization_id
                    }
                )
            except:
                pass  # Don't fail on audit logging issues

            return {
                "reply": "I encountered an error processing your request. Please try again or contact support if the issue persists.",
                "session_id": session_id,
                "status": "error",
                "error": "Internal processing error",
                "code": "agent_internal_error",
                "hint": "Retry in a few moments. If it continues, reach out to support with this timestamp."
            }

    async def _get_or_create_session(
        self,
        session_id: str,
        user_id: int,
        organization_id: int
    ) -> Tuple[SessionState, Optional[str]]:
        """Get existing session or create new one, returning session event metadata."""

        session_event: Optional[str] = None

        if session_id in self.sessions:
            session = self.sessions[session_id]

            if (session.user_id == user_id and
                session.organization_id == organization_id and
                self._is_session_valid(session)):
                return session, None

            if session.user_id != user_id or session.organization_id != organization_id:
                session_event = "session_reinitialized_conflict"
            elif not self._is_session_valid(session):
                session_event = "session_expired_restarted"
            else:
                session_event = "session_reinitialized"

            del self.sessions[session_id]

        else:
            session_event = "session_created"

        session = SessionState(
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id
        )

        self.sessions[session_id] = session

        logger.info(
            f"Created new session {session_id} for user {user_id} in org {organization_id} "
            f"(event={session_event})"
        )

        try:
            await chat_audit_logger.log_session_event(
                organization_id=organization_id,
                user_id=user_id,
                session_id=session_id,
                event=session_event or "session_created",
                details={"active_sessions": len(self.sessions)}
            )
        except Exception as audit_error:
            logger.debug(f"Unable to record session audit event: {audit_error}")

        return session, session_event

    async def _validate_tenant_access(self, user_id: int, organization_id: int) -> bool:
        """
        Enhanced tenant validation with database verification

        Args:
            user_id: User ID to validate
            organization_id: Organization ID to validate

        Returns:
            True if access is valid, False otherwise
        """
        if not self.tenant_isolation_enabled:
            return True

        try:
            if user_id <= 0:
                return False

            tenant_identifier = str(organization_id)

            user_record = await db.get_user_by_id(user_id)
            if not user_record:
                logger.warning(f"Tenant validation failed: user {user_id} not found")
                return False

            user_tenant_id = str(user_record.get("tenant_id") or "").strip() or "default"

            # Normalise identifiers (allow default tenants to operate across legacy org IDs)
            normalized_tenant = tenant_identifier.strip() or user_tenant_id
            normalized_user_tenant = user_tenant_id or "default"

            tenant_mismatch = (
                normalized_user_tenant != normalized_tenant
                and normalized_user_tenant != "default"
                and normalized_tenant != "default"
            )

            if tenant_mismatch:
                logger.warning(
                    "Tenant validation mismatch for user %s (tenant=%s) and organization %s",
                    user_id,
                    normalized_user_tenant,
                    normalized_tenant
                )
                return False

            # Check session limits
            user_sessions = [s for s in self.sessions.values()
                           if s.user_id == user_id and self._is_session_valid(s)]
            org_sessions = [s for s in self.sessions.values()
                          if s.organization_id == organization_id and self._is_session_valid(s)]

            if len(user_sessions) >= self.max_sessions_per_user:
                logger.warning(f"User {user_id} exceeded max sessions ({self.max_sessions_per_user})")
                return False

            if len(org_sessions) >= self.max_sessions_per_org:
                logger.warning(f"Organization {organization_id} exceeded max sessions ({self.max_sessions_per_org})")
                return False

            return True

        except Exception as e:
            logger.error(f"Tenant validation error: {e}")
            return False

    async def _ensure_session_entitlements(self, session: SessionState) -> None:
        """Load subscription and role metadata for the active session if missing."""

        needs_hydration = (
            session.feature_flags is None
            or session.subscription_tier is None
            or session.user_role is None
            or session.tenant_id is None
        )

        if not needs_hydration:
            return

        details = await self._fetch_user_org_details(session.user_id, session.organization_id)

        subscription_tier = "default"
        user_role: Optional[str] = normalize_role(None)
        tenant_identifier_raw: Optional[Any] = None

        if details:
            user_record = details.get("user") or {}
            organization_record = details.get("organization") or {}

            raw_role = user_record.get("role")
            user_role = normalize_role(raw_role)

            subscription_tier = str(
                details.get("subscription_tier")
                or organization_record.get("subscription_tier")
                or "default"
            ).lower()

            tenant_identifier_raw = (
                organization_record.get("tenant_id")
                or user_record.get("tenant_id")
                or session.organization_id
            )

        tenant_id_str: Optional[str] = None
        if tenant_identifier_raw is not None:
            candidate = str(tenant_identifier_raw).strip()
            tenant_id_str = candidate or None

        session.user_role = user_role
        session.subscription_tier = subscription_tier
        session.tenant_id = tenant_id_str
        feature_flag_scope: Optional[Union[str, int]] = tenant_id_str
        if feature_flag_scope is None:
            feature_flag_scope = session.organization_id
        if SUBSCRIPTION_SERVICE_AVAILABLE and feature_flag_scope is not None:
            session.feature_flags = subscription_feature_service.get_features_for_tenant(feature_flag_scope)
        else:
            session.feature_flags = {}

    async def _check_capability(
        self,
        session: SessionState,
        capability: str,
        *,
        allowed_roles: Optional[Iterable[str]] = None,
        command: str = ""
    ) -> Tuple[bool, Optional[str]]:
        """Validate that the session has access to the requested capability."""

        await self._ensure_session_entitlements(session)
        features = session.feature_flags or {}
        has_feature = bool(features.get(capability))

        if not has_feature:
            guardrail_message = self._format_guardrail_message(session, capability, reason="tier")
            await chat_audit_logger.log_command_execution(
                organization_id=session.organization_id,
                user_id=session.user_id,
                session_id=session.session_id,
                command=command or capability,
                success=False,
                result_summary="capability_blocked",
                metadata={
                    "capability": capability,
                    "reason": "subscription",
                    "subscription_tier": session.subscription_tier,
                    "user_role": session.user_role,
                },
            )
            return False, guardrail_message

        if allowed_roles:
            normalized_required = {normalize_role(role) for role in allowed_roles}
            current_role = normalize_role(session.user_role)
            if current_role not in normalized_required:
                guardrail_message = self._format_guardrail_message(
                    session,
                    capability,
                    reason="role",
                    required_roles=normalized_required,
                )
                await chat_audit_logger.log_command_execution(
                    organization_id=session.organization_id,
                    user_id=session.user_id,
                    session_id=session.session_id,
                    command=command or capability,
                    success=False,
                    result_summary="capability_blocked",
                    metadata={
                        "capability": capability,
                        "reason": "role",
                        "subscription_tier": session.subscription_tier,
                        "user_role": session.user_role,
                        "required_roles": sorted(normalized_required),
                    },
                )
                return False, guardrail_message

        return True, None

    def _format_guardrail_message(
        self,
        session: SessionState,
        capability: str,
        *,
        reason: str,
        required_roles: Optional[Iterable[str]] = None,
    ) -> str:
        """Generate standardized guardrail messaging for blocked capabilities."""

        label = self.capability_labels.get(capability, capability.replace("_", " "))
        tier = (session.subscription_tier or "default").capitalize()

        if reason == "tier":
            return (
                "🚫 This action is only available to Enterprise tenants.\n"
                f"Your organization is on the **{tier}** plan. Upgrade to unlock {label} or "
                "contact support if you believe this is an error."
            )

        if reason == "role":
            formatted_roles = ", ".join(sorted(role.title() for role in (required_roles or [])))
            return (
                "🔒 Your current role does not have permission for this action.\n"
                f"Allowed roles: {formatted_roles or 'organization administrators'}. "
                "Ask an administrator to perform it or adjust your role."
            )

        return (
            "⚠️ This action is currently unavailable for your account. "
            "Reach out to your administrator for assistance."
        )

    async def _check_rate_limits(self, user_id: int, organization_id: int) -> Dict[str, Any]:
        """
        Check rate limits for user and organization

        Args:
            user_id: User ID to check
            organization_id: Organization ID to check

        Returns:
            Dictionary with allowed status and details
        """
        try:
            now = datetime.now(timezone.utc)
            key = f"{organization_id}_{user_id}"

            # Initialize tracking if needed
            if key not in self.rate_limit_tracking:
                self.rate_limit_tracking[key] = []

            # Clean old entries
            requests = self.rate_limit_tracking[key]
            minute_ago = now - timedelta(minutes=1)
            hour_ago = now - timedelta(hours=1)
            day_ago = now - timedelta(days=1)

            # Filter recent requests
            recent_minute = [r for r in requests if r > minute_ago]
            recent_hour = [r for r in requests if r > hour_ago]
            recent_day = [r for r in requests if r > day_ago]

            # Check limits
            if len(recent_minute) >= self.rate_limits["messages_per_minute"]:
                return {
                    "allowed": False,
                    "message": f"Rate limit exceeded: {self.rate_limits['messages_per_minute']} messages per minute",
                    "retry_after": 60,
                    "limit_type": "messages_per_minute",
                    "current_count": len(recent_minute),
                    "limit_value": self.rate_limits["messages_per_minute"]
                }

            if len(recent_hour) >= self.rate_limits["messages_per_hour"]:
                return {
                    "allowed": False,
                    "message": f"Rate limit exceeded: {self.rate_limits['messages_per_hour']} messages per hour",
                    "retry_after": 3600,
                    "limit_type": "messages_per_hour",
                    "current_count": len(recent_hour),
                    "limit_value": self.rate_limits["messages_per_hour"]
                }

            if len(recent_day) >= self.rate_limits["messages_per_day"]:
                return {
                    "allowed": False,
                    "message": f"Rate limit exceeded: {self.rate_limits['messages_per_day']} messages per day",
                    "retry_after": 86400,
                    "limit_type": "messages_per_day",
                    "current_count": len(recent_day),
                    "limit_value": self.rate_limits["messages_per_day"]
                }

            # Add current request
            self.rate_limit_tracking[key] = recent_day + [now]

            return {
                "allowed": True,
                "requests_remaining": {
                    "minute": self.rate_limits["messages_per_minute"] - len(recent_minute),
                    "hour": self.rate_limits["messages_per_hour"] - len(recent_hour),
                    "day": self.rate_limits["messages_per_day"] - len(recent_day)
                }
            }

        except Exception as e:
            logger.error(f"Rate limit check error: {e}")
            return {"allowed": True}  # Fail open for availability

    async def _process_security_violations(
        self,
        session: SessionState,
        security_result
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Log security violations, enforce abuse controls, and determine warning/enforcement actions.
        Returns a tuple of (warning_text, enforcement_response_dict).
        """
        if not security_result or not security_result.violations:
            return None, None

        try:
            key = f"{session.organization_id}:{session.user_id}"
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(minutes=self.security_violation_limits["window_minutes"])

            recent_entries = [
                (ts, severity)
                for ts, severity in self.security_violation_tracking.get(key, [])
                if ts > window_start
            ]

            for violation in security_result.violations:
                severity = violation.severity.lower() if violation.severity else "medium"
                recent_entries.append((now, severity))
                await self._log_single_security_violation(session, violation, security_result.security_score)
                await self._record_violation_in_store(key, severity, now)

            self.security_violation_tracking[key] = recent_entries

            high_or_above_count = sum(1 for _, severity in recent_entries if severity in {"high", "critical"})
            critical_count = sum(1 for _, severity in recent_entries if severity == "critical")

            store_counts = await self._get_violation_counts_from_store(key)
            if store_counts:
                high_or_above_count = max(
                    high_or_above_count,
                    store_counts.get("high", 0) + store_counts.get("critical", 0)
                )
                critical_count = max(critical_count, store_counts.get("critical", 0))

            warning_text = None
            enforcement_response = None

            if critical_count >= self.security_violation_limits["max_critical"]:
                suspension_until = now + timedelta(minutes=30)
                self.suspended_sessions[key] = suspension_until
                await self._persist_suspension_in_store(key, suspension_until)
                if session.session_id in self.sessions:
                    del self.sessions[session.session_id]
                session.status = SessionStatus.EXPIRED
                enforcement_response = {
                    "reply": (
                        "Security policy triggered due to repeated critical violations. "
                        "Your access has been suspended for 30 minutes. "
                        "Please contact an administrator if you believe this is a mistake."
                    ),
                    "status": "error",
                    "error": "security_suspended",
                    "session_status": session.status.value,
                    "code": "security_suspended",
                    "hint": "Remove sensitive secrets from the conversation and wait for the suspension to expire before continuing."
                }
            elif high_or_above_count >= self.security_violation_limits["max_high"]:
                warning_text = (
                    "⚠️ Security notice: I detected sensitive content in recent messages. "
                    "Please avoid sharing credentials or confidential data. "
                    "Further violations may temporarily suspend access."
                )

            return warning_text, enforcement_response

        except Exception as e:
            logger.error(f"Failed to process security violations: {e}")
            return None, None

    async def _log_single_security_violation(
        self,
        session: SessionState,
        violation,
        security_score: float
    ):
        """Log a single security violation through agent and audit channels."""
        try:
            if agent_logger:
                await agent_logger.log_event(
                    event_type=AgentEventType.SECURITY_VIOLATION,
                    level=LogLevel.WARNING if violation.severity in ["low", "medium"] else LogLevel.ERROR,
                    agent_id="master_chat_agent",
                    session_id=session.session_id,
                    details={
                        "violation_type": violation.violation_type.value if hasattr(violation.violation_type, "value") else str(violation.violation_type),
                        "severity": violation.severity,
                        "confidence": violation.confidence,
                        "pattern_matched": violation.pattern_matched,
                        "user_id": session.user_id,
                        "organization_id": session.organization_id,
                        "security_score": security_score
                    }
                )

            await chat_audit_logger.log_security_violation(
                organization_id=session.organization_id,
                user_id=session.user_id,
                session_id=session.session_id,
                violation_type=getattr(violation.violation_type, "value", str(violation.violation_type)),
                severity=violation.severity,
                details={
                    "confidence": violation.confidence,
                    "pattern": violation.pattern_matched,
                    "context": violation.context
                }
            )
        except Exception as e:
            logger.error(f"Failed to record security violation: {e}")

    async def _record_violation_in_store(self, key: str, severity: str, timestamp: datetime) -> None:
        """Persist security violation counts in Redis for cross-instance throttling."""
        if not redis_service.is_connected:
            return

        window_seconds = self.security_violation_limits["window_minutes"] * 60
        redis_key = f"chat_security:violations:{key}:{severity}"
        score = timestamp.timestamp()

        try:
            await redis_service.client.zadd(redis_key, {str(score): score})
            await redis_service.client.zremrangebyscore(redis_key, 0, score - window_seconds)
            await redis_service.client.expire(redis_key, window_seconds)
        except Exception as exc:  # pragma: no cover - best effort persistence
            logger.debug(f"Unable to persist security violation to Redis: {exc}")

    async def _get_violation_counts_from_store(self, key: str) -> Dict[str, int]:
        """Retrieve persisted violation counts for high-severity enforcement."""
        counts: Dict[str, int] = {}
        if not redis_service.is_connected:
            return counts

        window_seconds = self.security_violation_limits["window_minutes"] * 60
        cutoff_score = datetime.now(timezone.utc).timestamp() - window_seconds

        for severity in ("high", "critical"):
            redis_key = f"chat_security:violations:{key}:{severity}"
            try:
                await redis_service.client.zremrangebyscore(redis_key, 0, cutoff_score)
                count = await redis_service.client.zcard(redis_key)
                counts[severity] = count
            except Exception as exc:  # pragma: no cover - best effort persistence
                logger.debug(f"Unable to read violation counter {redis_key}: {exc}")

        return counts

    async def _persist_suspension_in_store(self, key: str, suspension_until: datetime) -> None:
        """Persist session suspension so other instances respect the lockout."""
        if not redis_service.is_connected:
            return

        ttl_seconds = max(int((suspension_until - datetime.now(timezone.utc)).total_seconds()), 0)
        try:
            await redis_service.set(
                f"chat_security:suspension:{key}",
                suspension_until.isoformat(),
                ttl=max(ttl_seconds, 1)
            )
        except Exception as exc:  # pragma: no cover - best effort persistence
            logger.debug(f"Unable to persist suspension for {key}: {exc}")

    async def _load_suspension_from_store(self, key: str) -> Optional[datetime]:
        """Load suspension timestamp from Redis if available."""
        if not redis_service.is_connected:
            return None

        try:
            value = await redis_service.get(f"chat_security:suspension:{key}")
            if not value:
                return None
            return datetime.fromisoformat(value)
        except Exception as exc:  # pragma: no cover - parsing/logging safeguard
            logger.debug(f"Unable to load suspension for {key}: {exc}")
            return None

    async def _clear_suspension_in_store(self, key: str) -> None:
        """Remove suspension marker from Redis."""
        if not redis_service.is_connected:
            return

        try:
            await redis_service.delete(f"chat_security:suspension:{key}")
        except Exception as exc:  # pragma: no cover - best effort clean-up
            logger.debug(f"Unable to clear suspension for {key}: {exc}")

    def _is_session_valid(self, session: SessionState) -> bool:
        """Check if session is still valid (not expired)"""
        if session.last_activity is None:
            return False

        timeout_threshold = datetime.now(timezone.utc) - timedelta(hours=self.session_timeout_hours)
        return session.last_activity > timeout_threshold

    def _detect_command(self, message: str) -> CommandType:
        """Detect command type from user message"""
        message_lower = message.lower().strip()

        for command_type, patterns in self.command_patterns.items():
            for pattern in patterns:
                if re.search(pattern, message_lower):
                    return command_type

        return CommandType.UNKNOWN

    def _detect_linkedin_cookie(self, message: str) -> Optional[Dict[str, str]]:
        """
        Detect LinkedIn cookie JSON in user message

        Returns parsed cookie data if valid LinkedIn cookies found
        """
        try:
            # Try to parse as JSON
            data = json.loads(message)

            # Check for LinkedIn cookie keys
            linkedin_keys = ["li_at", "li_at_encrypted", "JSESSIONID", "jsessionid"]
            found_keys = {key: data.get(key) for key in linkedin_keys if data.get(key)}

            if found_keys:
                logger.info(f"Detected LinkedIn cookie submission with keys: {list(found_keys.keys())}")
                return found_keys

        except (json.JSONDecodeError, TypeError):
            # Not valid JSON, check for cookie-like patterns in text
            cookie_patterns = [
                r"li_at[\"']?\s*[:=]\s*[\"']?([a-zA-Z0-9_-]+)[\"']?",
                r"JSESSIONID[\"']?\s*[:=]\s*[\"']?([a-zA-Z0-9_-]+)[\"']?"
            ]

            found_cookies = {}
            for pattern in cookie_patterns:
                match = re.search(pattern, message, re.IGNORECASE)
                if match:
                    key = pattern.split('[')[0]  # Extract key name
                    found_cookies[key] = match.group(1)

            if found_cookies:
                logger.info(f"Detected LinkedIn cookies in text: {list(found_cookies.keys())}")
                return found_cookies

        return None

    def _filter_sensitive_data(self, text: str) -> str:
        """
        Legacy filter method - now delegates to advanced security filter
        Kept for backward compatibility
        """
        if not text:
            return text

        # Use new advanced filtering with default parameters
        try:
            result = chat_security_filter.filter_response(
                text, 0, 0, "legacy_filter"  # Use default IDs for legacy calls
            )
            return result.filtered_text
        except Exception as e:
            logger.error(f"Advanced filter failed, using legacy patterns: {e}")

            # Fallback to legacy patterns
            filtered_text = text
            for pattern in self.sensitive_patterns:
                filtered_text = re.sub(pattern, "[REDACTED]", filtered_text, flags=re.IGNORECASE)
            return filtered_text

    async def _handle_help(self, session: SessionState, message: str) -> str:
        """Handle help command"""
        return """🤖 **Tallwave Link Master Agent Help**

I'm your central assistant for the Tallwave warm-introduction system. Here's what I can help you with:

**📋 Prospect Management**
• `add a new prospect` - Interactive prospect addition
• `process prospect` - Start introducer finding workflow
• `/status` - Check current workflow progress

**💬 Conversation Commands**
• `/help` - Show this help message
• `/summary` - Get AI-powered conversation summary with insights
• `/context` - View current conversation context and entities
• `/history` - Review conversation history and past interactions
• `/export` - Export full conversation history with metadata
• `/clear` - Clear conversation history and start fresh

**🔗 LinkedIn Integration**
• Submit LinkedIn cookies (JSON format) for session management
• Verify and securely store authentication credentials
• Enable LinkedIn message sending capabilities
• Say `cookie status` to confirm your session or `collect org cookies` to orchestrate a refresh (admins only)

**🛠️ Tools & Automation**
• `/tools` - List available automation tools
• Natural language tool suggestions with confirmations
• Multi-agent workflow orchestration
• `/vault` - (Admins) View cookie vault inventory and session health

**🔍 Information & Search**
• Ask questions about prospects, companies, or executives
• Web search with citation tracking
• Real-time status updates and progress tracking

**📚 Tallwave Processes**
• Ask process questions (e.g., “What is the Tallwave cookie rotation process?”) and I’ll answer from the runbook according to your role
• Administrators receive full instructions; standard users get high-level guidance with escalation paths

**⚙️ Session Management**
• `/reset` - Clear current session and start fresh
• All data is securely stored and tenant-isolated
• Comprehensive audit logging and security filtering

**⚠️ Privacy & Compliance**
• Submit only the minimum LinkedIn session data required—treat `li_at` like a password.
• Do not paste HR records, PHI, PCI, or other restricted data. Those uploads are blocked and redacted.
• I automatically mask sensitive strings, but you remain responsible for keeping customer data out of chat transcripts.

**💡 Tips**
• Use natural language - I understand conversational requests
• Commands work with both `/command` and natural language
• Your LinkedIn cookies are encrypted, stored in the vault, and rotated with audit trails
• All interactions are logged for security and audit purposes
• Context is maintained across the conversation for better assistance

What would you like to do first?"""

    async def _handle_add_prospect(self, session: SessionState, message: str) -> str:
        """Handle prospect addition request"""
        # Integrate with existing conversational prospects service
        try:
            tenant_value = session.tenant_id or session.organization_id
            if tenant_value is None or str(tenant_value).strip() == "":
                return "I need to know which tenant you're working in before adding prospects. Please sign in again or set your tenant context."
            tenant_scope = str(tenant_value).strip()

            response = await conversational_prospects.start_prospect_conversation(
                session.session_id,
                tenant_id=tenant_scope,
                metadata={
                    "user_id": session.user_id,
                    "tenant_id": tenant_scope,
                },
            )
            session.status = SessionStatus.AWAITING_INPUT
            session.conversation_context = {"type": "prospect_addition", "active": True}

            return response

        except ImportError:
            logger.error("Could not import conversational_prospects service")
            return "Prospect addition service is currently unavailable. Please try using the web interface or contact support."

    async def _handle_process_prospect(self, session: SessionState, message: str) -> str:
        """Handle prospect processing/workflow initiation"""
        try:
            # Extract prospect information from message
            prospect_info = self._extract_prospect_from_message(message)

            if not prospect_info and not session.prospect_data:
                return """To process a prospect, I need prospect information first. You can:

1. Say `add a new prospect` to add one interactively
2. Provide prospect details: "Process John Smith from TechCorp"
3. Provide LinkedIn URL: "Process https://linkedin.com/in/johnsmith"

Which prospect would you like me to process?"""

            # Use extracted info or session data
            prospect_data = prospect_info or session.prospect_data

            # If a prospect ID was provided, load the full record for accuracy
            if prospect_data and prospect_data.get("prospect_id"):
                loaded_prospect = await self._fetch_prospect_by_id(
                    prospect_id=int(prospect_data["prospect_id"]),
                    organization_id=session.organization_id,
                    user_id=session.user_id,
                    tenant_id=session.tenant_id,
                )

                if not loaded_prospect:
                    return f"""❌ **Prospect Not Found**

I couldn't find prospect #{prospect_data['prospect_id']} for your organization.

Try a different prospect ID or add the prospect first with `add a new prospect`. """

                normalized_prospect = {
                    "prospect_id": loaded_prospect.get("id"),
                    "name": loaded_prospect.get("full_name") or loaded_prospect.get("name", ""),
                    "company": loaded_prospect.get("company", ""),
                    "title": loaded_prospect.get("headline", ""),
                    "linkedin_url": loaded_prospect.get("linkedin_url", ""),
                    "status": loaded_prospect.get("status", "active")
                }

                # Merge any additional context from the original message
                supplemental_fields = {
                    key: value for key, value in prospect_data.items()
                    if key not in normalized_prospect and value
                }
                prospect_data = {**normalized_prospect, **supplemental_fields}

            # Launch workflow via orchestrator
            from services.orchestrator import orchestrator

            logger.info(f"Launching workflow for prospect: {prospect_data}")

            # Generate workflow ID
            import secrets
            workflow_id = f"workflow_{session.user_id}_{int(time.time())}_{secrets.token_hex(6)}"

            # Start orchestrator workflow
            tenant_scope = session.tenant_id or str(session.organization_id)

            result = await orchestrator.find_introducers(
                prospect_url=prospect_data.get('linkedin_url', ''),
                prospect_name=prospect_data.get('name', ''),
                prospect_company=prospect_data.get('company', ''),
                auto_send_intros=False,  # User can approve later
                warm_up_profile_visits=True,
                tenant_id=tenant_scope,
                user_id=session.user_id
            )

            # Update session with enhanced workflow tracking
            session.status = SessionStatus.WORKFLOW_RUNNING
            session.workflow_id = workflow_id
            session.prospect_data = prospect_data
            session.active_workflow_type = "introducer_discovery"
            session.workflow_step = "initializing"
            session.workflow_status = "running"
            session.last_workflow_update = datetime.now(timezone.utc)

            # Store prospect ID if available from the data
            if 'prospect_id' in prospect_data:
                session.prospect_id = int(prospect_data['prospect_id'])

            # Record workflow initiation in idempotency service
            if idempotency_service:
                await idempotency_service.start_workflow(
                    workflow_id=workflow_id,
                    workflow_type="introducer_discovery",
                    organization_id=session.organization_id,
                    metadata={
                        "prospect_data": prospect_data,
                        "user_id": session.user_id,
                        "session_id": session.session_id
                    }
                )

            if result.get("status") == "success":
                introducers_count = len(result.get("introducers", []))
                return f"""🚀 **Workflow Launched Successfully**

**Prospect**: {prospect_data.get('name', 'Unknown')} from {prospect_data.get('company', 'Unknown Company')}
**Workflow ID**: {workflow_id}
**Status**: {result.get('diagnostics', {}).get('approach', 'Processing')}

**Results Found**:
• {introducers_count} potential introducers discovered
• {result.get('total_mutuals_found', 0)} mutual connections analyzed
• Email enrichment: {result.get('email_enrichment', {}).get('enriched', 0)} contacts enriched

**Next Steps**:
• Review introducers in the Prospects dashboard
• Type `status` to check detailed progress
• Use workflow ID {workflow_id} for reference

🎯 The workflow completed in {result.get('diagnostics', {}).get('winner_latency_ms', 0)}ms using {result.get('primary_provider', 'system')} provider."""

            else:
                error_msg = result.get("error_message", "Unknown error occurred")
                return f"""❌ **Workflow Failed**

**Prospect**: {prospect_data.get('name', 'Unknown')}
**Error**: {error_msg}

**Suggested Actions**:
• Verify the LinkedIn URL is accessible
• Check your LinkedIn cookie configuration
• Try again with a different prospect
• Contact support if issues persist

Type `help` for assistance or try adding a different prospect."""

        except Exception as e:
            logger.error(f"Error processing prospect workflow: {e}")
            return f"""❌ **Workflow Error**

I encountered an error while starting the prospect workflow: {str(e)}

**What to try**:
• Check that the prospect information is complete
• Ensure LinkedIn integration is configured
• Try with a simpler prospect format
• Type `help` for guidance

Please try again or contact support if the issue continues."""

    def _extract_prospect_from_message(self, message: str) -> Optional[Dict[str, str]]:
        """Extract prospect information from user message"""
        message_lower = message.lower()

        # Pattern for "Process [Name] from [Company]"
        name_company_pattern = r"process\s+([^,]+?)\s+(?:from|at)\s+(.+?)(?:\s|$)"
        match = re.search(name_company_pattern, message_lower)
        if match:
            return {
                "name": match.group(1).strip().title(),
                "company": match.group(2).strip().title(),
                "linkedin_url": ""
            }

        # Pattern for LinkedIn URLs
        linkedin_pattern = r"process\s+(?:prospect\s+)?(?:at\s+)?(https?://(?:www\.)?linkedin\.com/in/[^\s]+)"
        match = re.search(linkedin_pattern, message_lower)
        if match:
            return {
                "name": "",
                "company": "",
                "linkedin_url": match.group(1)
            }

        # Pattern for prospect ID
        id_pattern = r"process\s+prospect\s+#?(\d+)"
        match = re.search(id_pattern, message_lower)
        if match:
            prospect_id = int(match.group(1))
            return {
                "prospect_id": prospect_id
            }

        return None

    async def _handle_status(self, session: SessionState, message: str) -> str:
        """Handle status check request with enhanced workflow tracking"""
        status_parts = []

        # Enhanced workflow status checking
        if session.status == SessionStatus.WORKFLOW_RUNNING and session.workflow_id:
            try:
                # Fetch real workflow status from database
                workflow_data = await self._fetch_workflow_status(
                    session.workflow_id,
                    session.organization_id
                )

                if workflow_data:
                    status_parts.append(self._format_workflow_status(workflow_data))

                    # Update session with latest workflow info
                    session.workflow_status = workflow_data.get('status')
                    session.workflow_step = workflow_data.get('current_step')
                    session.last_workflow_update = datetime.now(timezone.utc)
                else:
                    status_parts.append(f"⚠️ **Workflow Status**: Unable to fetch status for workflow {session.workflow_id}")

            except Exception as e:
                logger.error(f"Failed to fetch workflow status: {e}")
                status_parts.append(f"❌ **Workflow Status**: Error retrieving status - {str(e)}")

        # Enhanced prospect information
        if session.prospect_id:
            try:
                prospect_data = await self._fetch_prospect_by_id(
                    prospect_id=session.prospect_id,
                    organization_id=session.organization_id,
                    tenant_id=session.tenant_id,
                )

                if prospect_data:
                    status_parts.append("\n📋 **Current Prospect**")
                    status_parts.append(self._format_prospect_summary(prospect_data))

            except Exception as e:
                logger.error(f"Failed to fetch prospect data: {e}")
                status_parts.append(f"⚠️ **Prospect Status**: Error retrieving prospect data")

        # Session status information
        if session.status == SessionStatus.AWAITING_INPUT:
            context_type = session.conversation_context.get("type", "unknown")
            status_parts.append(f"⏳ **Session Status**: Awaiting your input for {context_type} process.")
        else:
            # Basic session information
            basic_status = f"""✅ **Session Status**: {session.status.value.title()}

📋 **Session Details**
🆔 Session ID: {session.session_id}
📅 Created: {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}
🏢 Organization: {session.organization_id}
🍪 Cookie Status: {session.cookie_status or 'Not configured'}"""

            # Add workflow context if available
            if session.active_workflow_type:
                basic_status += f"\n🔄 Active Workflow: {session.active_workflow_type}"

            if session.workflow_step:
                basic_status += f"\n📍 Current Step: {session.workflow_step}"

            status_parts.append(basic_status)

        # Add ready message if no active workflows
        if not session.workflow_id and not session.prospect_id:
            status_parts.append("\n🚀 Ready for your next request!")

        return "\n\n".join(status_parts)

    async def _handle_reset(self, session: SessionState, message: str) -> str:
        """Handle session reset request"""
        # Clear session data but keep basic info
        session.status = SessionStatus.ACTIVE
        session.prospect_data = None
        session.workflow_id = None
        session.conversation_context = {}
        session.citations = []

        return """🔄 **Session Reset Complete**

Your session has been cleared and reset. Previous conversation context, prospect data, and workflow state have been removed.

Your LinkedIn cookie status and organization settings remain unchanged.

How can I assist you today?"""

    async def _handle_cookie_status(self, session: SessionState, message: str) -> str:
        """Provide role-aware LinkedIn cookie status updates."""

        tenant_value = session.tenant_id or session.organization_id
        if tenant_value is None or str(tenant_value).strip() == "":
            return (
                "I need a tenant context to inspect cookies. Please sign in again so I can confirm the organization."
            )

        tenant_scope = str(tenant_value).strip()
        normalized_role = normalize_role(session.user_role)

        def _parse_timestamp(value: Optional[object]) -> Optional[datetime]:
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    return None
            return None

        try:
            if normalized_role == "admin":
                if not COOKIE_VAULT_AVAILABLE or cookie_vault is None:
                    return (
                        "Cookie vault telemetry is unavailable in this environment. "
                        "Try again once the vault service is online."
                    )

                summary = await cookie_vault.summarize_linkedin_cookies(tenant_scope)
                total_items = summary.get("total_items", 0)
                active_items = summary.get("active_items", 0)
                expired_items = summary.get("expired_items", 0)
                expiring_soon = summary.get("expiring_soon", 0)
                rotation_recommended = summary.get("rotation_recommended", 0)
                last_rotation_at = _parse_timestamp(summary.get("last_rotation_at"))

                def _fmt(dt: Optional[datetime]) -> str:
                    if not dt:
                        return "n/a"
                    return dt.strftime("%Y-%m-%d %H:%M UTC")

                lines = [
                    f"🔐 **Tenant Cookie Status (tenant {tenant_scope})**",
                    f"• Vault items: {active_items} active / {total_items} total",
                    f"• Expired: {expired_items} | Expiring soon: {expiring_soon}",
                    f"• Last rotation recorded: {_fmt(last_rotation_at)}",
                ]

                if rotation_recommended:
                    lines.append(
                        f"• {rotation_recommended} item(s) exceed the rotation window — schedule a refresh soon."
                    )

                user_summaries = summary.get("user_summaries") or []
                if user_summaries:
                    lines.append("")
                    lines.append("👥 **Recent uploads**")
                    for entry in user_summaries[:5]:
                        user_id = entry.get("user_id")
                        active_count = entry.get("active", 0)
                        expired_count = entry.get("expired", 0)
                        uploaded_at = _parse_timestamp(entry.get("last_uploaded_at"))
                        lines.append(
                            f"• User {user_id}: {active_count} active / {expired_count} expired "
                            f"(last upload: {_fmt(uploaded_at)})"
                        )
                    if len(user_summaries) > 5:
                        lines.append(f"• …{len(user_summaries) - 5} additional teammate(s) omitted for brevity")

                lines.append(
                    "\nNeed action? Use `collect org cookies` and I'll orchestrate a fresh scan across the tenant."
                )
                return "\n".join(lines)

            if not SECURE_COOKIE_VAULT_AVAILABLE or secure_cookie_vault is None:
                if session.cookie_status == "verified_and_stored":
                    return (
                        "✅ Your LinkedIn cookie upload was verified and encrypted earlier this session. "
                        "An administrator can view the full vault summary if needed."
                    )
                return (
                    "I can't inspect the secure vault right now, but I'll flag any uploads to Tallwave operations. "
                    "Ask an administrator to confirm once the vault service is available."
                )

            list_kwargs = {
                "tenant_id": tenant_scope,
                "user_id": str(session.user_id),
                "include_expired": True,
            }
            if CookieType:
                list_kwargs["cookie_type"] = CookieType.LINKEDIN_LI_AT

            cookies = await secure_cookie_vault.list_cookies(**list_kwargs)

            latest_cookie = None
            latest_timestamp: Optional[datetime] = None
            for cookie in cookies:
                candidate = (
                    getattr(cookie, "updated_at", None)
                    or getattr(cookie, "created_at", None)
                    or getattr(cookie, "last_used", None)
                )
                parsed = _parse_timestamp(candidate)
                if parsed and (latest_timestamp is None or parsed > latest_timestamp):
                    latest_cookie = cookie
                    latest_timestamp = parsed

            if not latest_cookie:
                return (
                    "I don't see a stored LinkedIn session for you yet. "
                    "Upload your `li_at` + `JSESSIONID` via Settings and I'll confirm once it's vaulted."
                )

            status_value = getattr(latest_cookie, "status", "unknown")
            if isinstance(status_value, CookieStatus):
                status_value = status_value.value
            status_text = str(status_value).replace("_", " ").title()

            expires_at = _parse_timestamp(getattr(latest_cookie, "expires", None))
            expires_text = expires_at.strftime("%Y-%m-%d") if expires_at else "not provided"
            last_verified = latest_timestamp or _parse_timestamp(getattr(latest_cookie, "last_used", None))
            last_verified_text = last_verified.strftime("%Y-%m-%d %H:%M UTC") if last_verified else "not recorded"

            lines = [
                "🔐 **Your LinkedIn Session**",
                f"• Status: {status_text}",
                f"• Last verified: {last_verified_text}",
                f"• Expires: {expires_text}",
            ]

            if session.cookie_status == "verified_and_stored":
                lines.append("• This cookie was verified in this chat and securely stored.")

            lines.append(
                "\nNeed adjustments or a rotation? Let a Tallwave administrator know and I can queue the org-wide refresh."
            )
            return "\n".join(lines)

        except Exception as exc:
            logger.error("Error retrieving cookie status for tenant %s: %s", tenant_scope, exc)
            return (
                "⚠️ I couldn't retrieve cookie status just now. "
                "Please try again later or ask an administrator to review the vault."
            )

    async def _handle_vault_audit(self, session: SessionState, message: str) -> str:
        """Provide administrators with cookie vault and jar status."""

        allowed, denial_message = await self._check_capability(
            session,
            "cookie_vault_admin",
            allowed_roles={"admin"},
            command="vault_audit",
        )
        if not allowed:
            return denial_message

        if not PORTAL_DB_AVAILABLE or portal_get_conn is None or portal_query is None:
            return "⚠️ Portal database functionality is unavailable in this environment."

        organization_id = session.organization_id
        try:
            with portal_get_conn() as conn:
                user_rows = portal_query(conn, "SELECT role, email FROM users WHERE id = ?", (session.user_id,))
                if not user_rows:
                    return "⚠️ Unable to confirm your role for vault access right now."

                row = dict(user_rows[0]) if not isinstance(user_rows[0], dict) else user_rows[0]
                role_value = str(row.get("role", "") or "").lower()
                if normalize_role(role_value) != "admin":
                    return "🔒 Vault and cookie audits are restricted to administrators."

                jar_rows = portal_query(
                    conn,
                    """
                    SELECT user_id, status, last_used_at, usage_count, vault_item_id
                    FROM cookie_jars
                    WHERE organization_id = ?
                    ORDER BY user_id ASC
                    """,
                    (organization_id,),
                )
        except Exception as exc:
            logger.error(f"Vault audit database error: {exc}")
            return "⚠️ Unable to retrieve vault status right now. Please try again later."

        jar_data = [dict(row) for row in jar_rows] if jar_rows else []
        if not jar_data:
            return (
                "ℹ️ No cookie jars are registered for this organization yet. "
                "Upload LinkedIn sessions from Settings › Cookie Jar to get started."
            )

        tenant_id_str = str(organization_id)
        vault_summary = None
        if COOKIE_VAULT_AVAILABLE and cookie_vault is not None:
            try:
                vault_summary = await cookie_vault.summarize_linkedin_cookies(tenant_id_str)
            except Exception as exc:
                logger.warning("Vault summary unavailable for tenant %s: %s", tenant_id_str, exc)
                vault_summary = None
        else:
            logger.debug("Cookie vault service unavailable; skipping vault summary for tenant %s", tenant_id_str)

        status_counts = Counter(row.get("status", "unknown") for row in jar_data)
        lines: List[str] = []
        lines.append(f"🔐 **Cookie Vault Overview** (tenant {organization_id})")
        lines.append(
            f"• Cookie jars: {len(jar_data)} total ({', '.join(f'{status}: {count}' for status, count in status_counts.items())})"
        )

        if vault_summary:
            lines.append(
                f"• Active vault items: {vault_summary['active_items']} / {vault_summary['total_items']}"
            )
            if vault_summary.get("expiring_soon"):
                lines.append(
                    f"• {vault_summary['expiring_soon']} item(s) expiring soon — schedule rotations within {cookie_vault.EXPIRING_SOON_DAYS} days."
                )
            if vault_summary.get("expired_items"):
                lines.append(
                    f"• {vault_summary['expired_items']} item(s) expired and will be skipped by automations until refreshed."
                )
            if vault_summary.get("missing_vault_entries"):
                lines.append(
                    f"• {vault_summary['missing_vault_entries']} jar(s) missing vault backups: {', '.join(vault_summary['missing_vault_users']) or 'unassigned'}"
                )
            if vault_summary.get("rotation_recommended"):
                lines.append("• Rotation recommended — some records exceed rotation policy thresholds.")

        max_users_to_display = 8
        if vault_summary and vault_summary.get("user_summaries"):
            for index, summary in enumerate(vault_summary["user_summaries"]):
                if index >= max_users_to_display:
                    lines.append("• …additional users hidden for brevity")
                    break

                user_id = summary.get("user_id")
                last_used_row = next((row for row in jar_data if str(row.get("user_id")) == str(user_id)), None)
                usage_total = 0
                if last_used_row:
                    try:
                        usage_total = int(last_used_row.get("usage_count") or 0)
                    except (TypeError, ValueError):
                        usage_total = 0

                last_used_str = "never"
                if last_used_row and last_used_row.get("last_used_at"):
                    try:
                        parsed = datetime.fromisoformat(str(last_used_row["last_used_at"]))
                        last_used_str = parsed.strftime("%Y-%m-%d %H:%M UTC")
                    except ValueError:
                        last_used_str = str(last_used_row.get("last_used_at"))

                lines.append(
                    f"• User {user_id}: {summary.get('active', 0)} active / {summary.get('expired', 0)} expired, "
                    f"last used {last_used_str}, total usage {usage_total}"
                )

                if summary.get("rotation_recommended"):
                    lines.append("    • Rotation overdue — refresh this user's cookies soon.")

        lines.append(
            "\nRemember: keep personal data out of transcripts and rotate sessions when teammates leave the tenant."
        )

        return "\n".join(lines)

    async def _handle_collect_org_cookies(self, session: SessionState, message: str) -> str:
        """Initiate organization-wide cookie collection workflow for entitled tenants."""

        allowed, denial_message = await self._check_capability(
            session,
            "cookie_collection",
            allowed_roles={"admin"},
            command="collect_org_cookies",
        )
        if not allowed:
            return denial_message

        start_time = time.time()

        if not COOKIE_COLLECTION_AVAILABLE:
            return (
                "⚠️ Cookie collection automation is not available in this environment. "
                "Please contact your administrator to enable secure workflow integrations."
            )

        try:
            summary = await cookie_collection_workflow.collect_for_org(
                organization_id=session.organization_id,
                requested_by=session.user_id,
            )
        except Exception as exc:
            logger.error(f"Cookie collection workflow failed: {exc}")
            await chat_audit_logger.log_command_execution(
                organization_id=session.organization_id,
                user_id=session.user_id,
                session_id=session.session_id,
                command="collect_org_cookies",
                success=False,
                result_summary="collection_failed",
                metadata={"error": str(exc)},
            )
            return (
                "⚠️ I couldn't start the organization-wide cookie collection workflow right now. "
                "Please try again shortly or contact support if the issue persists."
            )

        elapsed_ms = int((time.time() - start_time) * 1000)

        await chat_audit_logger.log_command_execution(
            organization_id=session.organization_id,
            user_id=session.user_id,
            session_id=session.session_id,
            command="collect_org_cookies",
            success=True,
            execution_time_ms=elapsed_ms,
            result_summary="collection_started",
            metadata=summary,
        )

        counts = summary.get("counts", {})
        total_members = counts.get("total_team_members", 0)
        valid = counts.get("valid", 0)
        missing_members = summary.get("missing_members", [])
        rotation_required = summary.get("rotation_required", [])
        expiring = summary.get("expiring_soon", [])

        lines = [
            "🍪 **Organization Cookie Collection Initiated**",
            f"• Coverage: {valid}/{total_members} team members have active cookies.",
            f"• Missing uploads: {len(missing_members)}",
            f"• Needs rotation: {len(rotation_required)}",
        ]

        if expiring:
            window_days = summary.get("expiring_window_days")
            window_text = f" within {window_days} days" if window_days else " soon"
            lines.append(f"• Expiring soon: {len(expiring)}{window_text}")

        cookie_inventory = summary.get("cookie_inventory", [])
        if cookie_inventory:
            lines.append("• Inventory snapshot:")
            for entry in cookie_inventory[:5]:
                label = entry.get("display_name") or entry.get("email") or f"user {entry.get('user_id')}"
                status_label = (entry.get("status") or "unknown").replace("_", " ").title()
                expires_label = entry.get("expires_at") or "unknown expiry"
                vault_suffix = " • vault" if entry.get("vault_item_present") else ""
                lines.append(f"  - {label}: {status_label}, expires {expires_label}{vault_suffix}")

        def _preview_people(items: List[Dict[str, Any]]) -> Optional[str]:
            names: List[str] = []
            for item in items:
                label = item.get("display_name") or item.get("email")
                if not label and item.get("user_id") is not None:
                    label = f"user {item['user_id']}"
                if label:
                    names.append(str(label))
            if not names:
                return None
            preview = ", ".join(names[:3])
            if len(names) > 3:
                preview += f" (+{len(names) - 3} more)"
            return preview

        missing_preview = _preview_people(missing_members)
        if missing_preview:
            lines.append(f"ℹ️ Pending uploads: {missing_preview}")

        rotation_preview = _preview_people(rotation_required)
        if rotation_preview:
            lines.append(f"♻️ Rotation queued: {rotation_preview}")

        events_logged = summary.get("events_logged")
        if events_logged:
            plural = "s" if events_logged != 1 else ""
            lines.append(
                f"📝 Logged {events_logged} audit reminder{plural}; admins can track progress in Settings → Cookie Vault."
            )

        lines.append("I'll surface updates here as teammates upload fresh cookies.")

        session.status = SessionStatus.WORKFLOW_RUNNING
        session.workflow_context["cookie_collection"] = summary
        session.workflow_status = "cookie_collection_active"
        session.last_workflow_update = datetime.now(timezone.utc)

        return "\n".join(lines)

    async def _handle_list_tools(self, session: SessionState, message: str) -> str:
        """Handle tool listing request"""
        if not TOOL_REGISTRY_AVAILABLE:
            return (
                "🔧 **Tools Unavailable**\n\n"
                "The automation tool registry isn't enabled in this environment. "
                "Please contact your administrator to activate tool support."
            )

        try:
            # Get available tools by category
            all_tools = chat_tool_registry.get_available_tools(user_role=session.user_role)

            if not all_tools:
                return """🔧 **Available Tools**

No tools are currently available. This might be a temporary issue.

Please try again later or contact support if the issue persists."""

            # Group tools by category
            tools_by_category = {}
            for tool in all_tools:
                category = tool["category"]
                if category not in tools_by_category:
                    tools_by_category[category] = []
                tools_by_category[category].append(tool)

            response_parts = ["🔧 **Available Tools & Capabilities**\n"]

            for category, tools in tools_by_category.items():
                # Format category name
                category_name = category.replace("_", " ").title()
                response_parts.append(f"**{category_name}:**")

                for tool in tools:
                    confirmation_icon = "⚠️" if tool["confirmation_level"] != "none" else "✅"
                    dangerous_icon = "🚨" if tool.get("dangerous", False) else ""

                    response_parts.append(f"• {confirmation_icon} **{tool['name']}** {dangerous_icon}")
                    response_parts.append(f"  {tool['description']}")

                    if tool["examples"]:
                        response_parts.append(f"  *Example*: {tool['examples'][0]}")

                    response_parts.append("")

            response_parts.append("**Usage Notes:**")
            response_parts.append("• ✅ = No confirmation required")
            response_parts.append("• ⚠️ = Confirmation required")
            response_parts.append("• 🚨 = Destructive action (extra caution)")
            response_parts.append("\n💡 Just describe what you want to do in natural language, and I'll suggest the right tool!")

            return "\n".join(response_parts)

        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            return "I encountered an error while listing available tools. Please try again or contact support."

    async def _handle_tool_confirmation(self, session: SessionState, message: str) -> str:
        """Handle tool execution confirmation"""
        try:
            if not session.pending_tool_execution:
                return """❓ **No Pending Confirmation**

There's no tool execution waiting for confirmation. If you want to use a tool, just tell me what you'd like to do!

Examples:
• "Find introducers for John Smith at TechCorp"
• "Search for information about blockchain startups"
• "Send introduction email for prospect #123" """

            # Parse confirmation response
            message_lower = message.lower().strip()
            confirmed = any(word in message_lower for word in ["yes", "confirm", "proceed", "do it", "execute", "ok"])
            cancelled = any(word in message_lower for word in ["no", "cancel", "abort", "stop", "nevermind"])

            if not confirmed and not cancelled:
                return """❓ **Please Confirm**

Please respond with:
• **"Yes"** or **"Confirm"** to proceed
• **"No"** or **"Cancel"** to abort

What would you like to do?"""

            # Execute or cancel the pending tool
            if not TOOL_REGISTRY_AVAILABLE:
                session.pending_tool_execution = None
                return (
                    "⚠️ Tool automation is not available right now. "
                    "Please contact support to enable the tool registry."
                )

            execution_result = await chat_tool_registry.confirm_execution(
                session.pending_tool_execution,
                confirmed,
                user_role=session.user_role,
            )

            # Clear pending execution
            session.pending_tool_execution = None

            # Log tool execution
            await chat_audit_logger.log_command_execution(
                organization_id=session.organization_id,
                user_id=session.user_id,
                session_id=session.session_id,
                command=f"tool_confirmation_{execution_result.tool_id}",
                success=execution_result.status.value == "completed",
                execution_time_ms=execution_result.execution_time_ms,
                result_summary=str(execution_result.result) if execution_result.result else None
            )

            if execution_result.status.value == "cancelled":
                return "✅ **Tool Execution Cancelled**\n\nThe operation has been cancelled. How else can I help you?"

            elif execution_result.status.value == "failed":
                error_msg = execution_result.error or "Unknown error occurred"
                return f"""❌ **Tool Execution Failed**

The operation failed with the following error: {error_msg}

Please try again or contact support if the issue persists."""

            elif execution_result.status.value == "completed":
                result = execution_result.result
                if isinstance(result, dict):
                    if result.get("status") == "success":
                        message = result.get("message", "Operation completed successfully.")
                        extra_hint = result.get("hint")
                        undo_notice = ""
                        if result.get("undo_available"):
                            undo_notice = "\n\n*Undo available: say \"undo last action\" to revert this change.*"
                        if extra_hint:
                            undo_notice += f"\n\n_{extra_hint}_"

                        # Add specific formatting for different tool types
                        if execution_result.tool_id == "start_prospect_workflow":
                            workflow_id = result.get("workflow_id")
                            introducers_count = result.get("introducers_found", 0)
                            return f"""✅ **Workflow Started Successfully**

{message}

**Details:**
• Workflow ID: {workflow_id}
• Introducers Found: {introducers_count}

You can check progress by saying "status" or view results in the Prospects dashboard.{undo_notice}"""

                        elif execution_result.tool_id == "web_search":
                            formatted_response = result.get("formatted_response", message)
                            return f"🔍 **Search Completed**\n\n{formatted_response}"
                        elif execution_result.tool_id == "undo_last_tool":
                            return f"♻️ **Undo Completed**\n\n{message}"

                        else:
                            return f"✅ **Operation Completed**\n\n{message}{undo_notice}"

                    else:
                        error_msg = result.get("error", "Operation failed")
                        return f"❌ **Operation Failed**\n\n{error_msg}"

                return f"✅ **Operation Completed**\n\n{str(result)}"

            else:
                return f"⏳ **Operation Status**: {execution_result.status.value.title()}"

        except Exception as e:
            logger.error(f"Error handling tool confirmation: {e}")
            # Clear pending execution on error
            session.pending_tool_execution = None
            return f"❌ **Confirmation Error**\n\nThere was an error processing your confirmation: {str(e)}"

    async def _handle_summary(self, session: SessionState, message: str) -> str:
        """Handle conversation summary request"""
        try:
            summary_data = await self.get_conversation_summary(session.session_id)

            if "error" in summary_data:
                return f"""📝 **Conversation Summary**

{summary_data['error']}

Try starting a conversation first, then ask for a summary!"""

            # Format the summary nicely
            summary_parts = [
                "📝 **Conversation Summary**",
                "",
                f"**Session**: {summary_data.get('session_id', 'N/A')[:8]}...",
                f"**Generated**: {summary_data.get('generated_at', 'N/A')[:19]}",
                "",
                "**Summary:**",
                summary_data.get('summary_text', 'No summary available'),
                ""
            ]

            # Add key insights if available
            insights = summary_data.get('key_insights', [])
            if insights:
                summary_parts.extend([
                    "**Key Insights:**",
                    *[f"• {insight.get('content', insight)}" for insight in insights[:5]],
                    ""
                ])

            # Add action items if available
            action_items = summary_data.get('action_items', [])
            if action_items:
                summary_parts.extend([
                    "**Action Items:**",
                    *[f"• {item}" for item in action_items[:5]],
                    ""
                ])

            # Add metrics
            metrics = summary_data.get('conversation_metrics', {})
            if metrics:
                summary_parts.extend([
                    "**Conversation Metrics:**",
                    f"• Messages: {metrics.get('total_turns', 0)} ({metrics.get('user_messages', 0)} from you, {metrics.get('agent_responses', 0)} from me)",
                    f"• Duration: {metrics.get('session_duration_minutes', 0)} minutes",
                    f"• Entities discovered: {metrics.get('entities_discovered', 0)}",
                    ""
                ])

            # Add productivity score if available
            productivity_score = summary_data.get('productivity_score', 0)
            if productivity_score > 0:
                summary_parts.append(f"**Productivity Score**: {productivity_score}/100")

            return "\n".join(summary_parts)

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "I encountered an error generating the conversation summary. Please try again."

    async def _handle_context(self, session: SessionState, message: str) -> str:
        """Handle conversation context request"""
        try:
            context_data = await self.get_conversation_context(session.session_id)

            if "error" in context_data:
                return f"""🧠 **Conversation Context**

{context_data['error']}

Start a conversation first, then I can show you the context!"""

            context_parts = [
                "🧠 **Conversation Context**",
                "",
                f"**Session**: {context_data.get('session_id', 'N/A')[:8]}...",
                f"**Duration**: {context_data.get('session_duration_minutes', 0)} minutes",
                f"**Total turns**: {context_data.get('total_turns', 0)}",
                ""
            ]

            # Add relevant entities
            entities = context_data.get('relevant_entities', {})
            if entities:
                context_parts.extend([
                    "**Key Entities Mentioned:**"
                ])
                for entity_id, entity_data in list(entities.items())[:8]:  # Limit to 8
                    entity_type = entity_data.get('entity_type', 'unknown')
                    entity_name = entity_data.get('name', 'Unknown')
                    mention_count = entity_data.get('mention_count', 0)
                    context_parts.append(f"• **{entity_name}** ({entity_type}) - mentioned {mention_count} times")
                context_parts.append("")

            # Add active topics
            topics = context_data.get('active_topics', [])
            if topics:
                context_parts.extend([
                    "**Active Topics:**",
                    ", ".join(topics[:10]),  # Limit to 10 topics
                    ""
                ])

            # Add recent conversation snippets
            recent_turns = context_data.get('recent_turns', [])
            if recent_turns:
                context_parts.extend([
                    "**Recent Conversation (last 3 exchanges):**"
                ])
                for turn in recent_turns[-6:]:  # Last 6 turns (3 exchanges)
                    speaker = "You" if turn.get('speaker') == 'user' else "Me"
                    message_preview = turn.get('message', '')[:100]
                    if len(turn.get('message', '')) > 100:
                        message_preview += "..."
                    context_parts.append(f"• **{speaker}**: {message_preview}")

            return "\n".join(context_parts)

        except Exception as e:
            logger.error(f"Error getting context: {e}")
            return "I encountered an error retrieving the conversation context. Please try again."

    async def _handle_history(self, session: SessionState, message: str) -> str:
        """Handle conversation history request"""
        try:
            context_data = await self.get_conversation_context(session.session_id)

            if "error" in context_data:
                return f"""📚 **Conversation History**

{context_data['error']}

Start a conversation first, then I can show you the history!"""

            recent_turns = context_data.get('recent_turns', [])
            if not recent_turns:
                return """📚 **Conversation History**

No conversation history available yet. Start chatting with me and then check your history!"""

            history_parts = [
                "📚 **Conversation History**",
                "",
                f"**Session**: {context_data.get('session_id', 'N/A')[:8]}...",
                f"**Total messages**: {context_data.get('total_turns', 0)}",
                f"**Showing**: Last {min(len(recent_turns), 10)} messages",
                "",
                "**Recent Messages:**",
                ""
            ]

            # Show last 10 turns with timestamps
            for turn in recent_turns[-10:]:
                speaker = "You" if turn.get('speaker') == 'user' else "Me"
                timestamp = turn.get('timestamp', '')[:19] if turn.get('timestamp') else ''
                message = turn.get('message', '')

                # Truncate long messages
                if len(message) > 200:
                    message = message[:200] + "..."

                history_parts.extend([
                    f"**[{timestamp}] {speaker}:**",
                    message,
                    ""
                ])

            # Add summaries if available
            summaries = context_data.get('conversation_summaries', [])
            if summaries:
                history_parts.extend([
                    "**Previous Session Summaries:**"
                ])
                for summary in summaries[-3:]:  # Last 3 summaries
                    summary_text = summary.get('summary_text', '')[:150]
                    if len(summary.get('summary_text', '')) > 150:
                        summary_text += "..."
                    history_parts.append(f"• {summary_text}")

            return "\n".join(history_parts)

        except Exception as e:
            logger.error(f"Error getting history: {e}")
            return "I encountered an error retrieving the conversation history. Please try again."

    async def _handle_history_export(self, session: SessionState, message: str) -> str:
        """Export full conversation history and metadata to disk for auditing."""
        try:
            context_data = await conversation_context_manager.get_conversation_context(
                include_summaries=True,
                max_turns=1000
            )

            recent_turns = context_data.get("recent_turns", [])
            if not recent_turns:
                return """📦 **Conversation Export**

No conversation data available to export yet. Start a conversation and try again!"""

            export_payload = {
                "session_id": session.session_id,
                "organization_id": session.organization_id,
                "user_id": session.user_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_turns": context_data.get("total_turns", len(recent_turns)),
                "turns": recent_turns,
                "summaries": context_data.get("conversation_summaries", []),
                "entities": context_data.get("relevant_entities", {}),
                "context_metadata": context_data.get("context_metadata", {}),
            }

            export_dir = Path("data/chat_exports")
            export_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            export_filename = f"chat_history_{session.session_id}_{timestamp}.json"
            export_path = export_dir / export_filename

            export_json = json.dumps(export_payload, indent=2, default=str)
            export_path.write_text(export_json, encoding="utf-8")
            checksum = hashlib.sha256(export_json.encode("utf-8")).hexdigest()

            await chat_audit_logger.log_command_execution(
                organization_id=session.organization_id,
                user_id=session.user_id,
                session_id=session.session_id,
                command="history_export",
                success=True,
                result_summary=f"turns={len(recent_turns)}, file={export_path}",
                metadata={"checksum": checksum}
            )

            return f"""📦 **Conversation Export Created**

Exported **{len(recent_turns)}** conversation turns and **{len(export_payload['summaries'])}** summaries.

• Session ID: `{session.session_id}`
• File: `{export_path}`
• SHA-256: `{checksum[:16]}…`

Download the file securely from the server to review the full transcript and metadata."""

        except Exception as e:
            logger.error(f"History export failed: {e}")
            await chat_audit_logger.log_command_execution(
                organization_id=session.organization_id,
                user_id=session.user_id,
                session_id=session.session_id,
                command="history_export",
                success=False,
                result_summary=str(e)
            )
            return "I couldn't export the conversation history due to an internal error. Please try again or contact support."

    async def _handle_clear(self, session: SessionState, message: str) -> str:
        """Handle conversation clear request"""
        try:
            # Clear conversation context if it exists
            if conversation_context_manager.current_session_id == session.session_id:
                # Reset the context manager
                conversation_context_manager.conversation_turns.clear()
                conversation_context_manager.entities.clear()
                conversation_context_manager.topic_clusters.clear()
                conversation_context_manager.conversation_summaries.clear()

            # Also clear session conversation context
            session.conversation_context = {}

            return """🧹 **Conversation Cleared**

Your conversation history, context, and memory have been cleared. I've forgotten our previous discussion while keeping your session settings.

**What was cleared:**
• Conversation history and turns
• Entity mentions and tracking
• Topic clusters and context
• Previous summaries

**What was kept:**
• Your session ID and authentication
• LinkedIn cookie status
• Organization settings
• Current workflow state (if any)

How can I help you today with a fresh start?"""

        except Exception as e:
            logger.error(f"Error clearing conversation: {e}")
            return "I encountered an error clearing the conversation. Some history may remain. You can try `/reset` for a complete session reset."

    async def _handle_tool_suggestion(self, session: SessionState, message: str) -> Optional[str]:
        """Handle tool suggestion and execution based on user intent"""
        if not TOOL_REGISTRY_AVAILABLE:
            return None

        try:
            # Get tool suggestions based on message
            suggestions = chat_tool_registry.get_tool_suggestions(message)

            if not suggestions:
                return None

            # If there's a clear top suggestion with high relevance, execute it
            top_suggestion = suggestions[0]

            if top_suggestion["relevance_score"] > 0.7:  # High confidence threshold
                # Extract parameters from message for top suggestion
                tool_id = top_suggestion["tool_id"]
                parameters = self._extract_tool_parameters(tool_id, message)

                if parameters:
                    # Execute the tool
                    execution_result = await chat_tool_registry.execute_tool(
                        tool_id=tool_id,
                        parameters=parameters,
                        user_id=session.user_id,
                        organization_id=session.organization_id,
                        session_id=session.session_id,
                        user_role=session.user_role,
                    )

                    if execution_result.status.value == "pending_confirmation":
                        # Store pending execution in session
                        session.pending_tool_execution = execution_result.execution_id

                        return f"""🔧 **Tool Confirmation Required**

{execution_result.confirmation_message}

**Tool**: {top_suggestion['name']}
**Action**: {top_suggestion['description']}

Type **"yes"** to proceed or **"no"** to cancel."""

                    elif execution_result.status.value == "completed":
                        # Tool executed successfully without confirmation
                        result = execution_result.result
                        if isinstance(result, dict):
                            if result.get("formatted_response"):
                                return result["formatted_response"]

                            message_text = result.get("message", "Operation completed successfully.")
                            hint_text = result.get("hint")
                            undo_notice = ""
                            if result.get("undo_available"):
                                undo_notice = "\n\n*Undo available: say \"undo last action\" to revert this change.*"
                            if hint_text:
                                undo_notice += f"\n\n_{hint_text}_"

                            return f"✅ **{top_suggestion['name']} Completed**\n\n{message_text}{undo_notice}"

                        return f"✅ **{top_suggestion['name']} Completed**\n\n{str(result)}"

                    elif execution_result.status.value == "failed":
                        return f"❌ **{top_suggestion['name']} Failed**\n\n{execution_result.error}"

            # If no high-confidence match, show suggestions
            elif len(suggestions) > 0:
                response_parts = ["🤔 **I can help you with these tools:**\n"]

                for i, suggestion in enumerate(suggestions[:3], 1):
                    conf_text = " (requires confirmation)" if suggestion["confirmation_required"] else ""
                    response_parts.append(f"{i}. **{suggestion['name']}**{conf_text}")
                    response_parts.append(f"   {suggestion['description']}")
                    response_parts.append("")

                response_parts.append("💡 **Tip**: Be more specific about what you want to do, and I'll execute the right tool automatically!")

                return "\n".join(response_parts)

            return None

        except Exception as e:
            logger.error(f"Error in tool suggestion: {e}")
            return None

    def _extract_tool_parameters(self, tool_id: str, message: str) -> Optional[Dict[str, Any]]:
        """Extract tool parameters from user message"""
        try:
            tool = chat_tool_registry.tools.get(tool_id)
            if not tool:
                return None

            parameters = {}
            message_lower = message.lower()

            # Tool-specific parameter extraction
            if tool_id == "start_prospect_workflow":
                # Extract prospect name
                name_patterns = [
                    r"(?:for|prospect|find)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
                    r"([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(?:at|from)",
                ]

                for pattern in name_patterns:
                    match = re.search(pattern, message)
                    if match:
                        parameters["prospect_name"] = match.group(1)
                        break

                # Extract company
                company_patterns = [
                    r"(?:at|from|company)\s+([A-Z][a-zA-Z\s&]+)",
                    r"([A-Z][a-zA-Z\s&]+)\s+(?:company|corp|inc)",
                ]

                for pattern in company_patterns:
                    match = re.search(pattern, message)
                    if match:
                        parameters["prospect_company"] = match.group(1).strip()
                        break

                # Extract LinkedIn URL
                linkedin_pattern = r"(https?://(?:www\.)?linkedin\.com/in/[^\s]+)"
                match = re.search(linkedin_pattern, message)
                if match:
                    parameters["linkedin_url"] = match.group(1)

            elif tool_id == "web_search":
                # Extract search query (everything after search indicators)
                search_patterns = [
                    r"search\s+for\s+(.+)",
                    r"find\s+(?:information\s+about\s+)?(.+)",
                    r"who\s+is\s+(.+)",
                    r"what\s+is\s+(.+)",
                    r"tell\s+me\s+about\s+(.+)"
                ]

                for pattern in search_patterns:
                    match = re.search(pattern, message_lower)
                    if match:
                        parameters["query"] = match.group(1).strip()
                        break

                if not parameters.get("query"):
                    # Use entire message as query if no specific pattern found
                    parameters["query"] = message.strip()

            elif tool_id == "check_workflow_status":
                # Extract workflow ID
                workflow_patterns = [
                    r"workflow\s+([a-zA-Z0-9_-]+)",
                    r"status\s+(?:of\s+)?([a-zA-Z0-9_-]+)",
                    r"([a-zA-Z0-9_-]{8,})"  # Any long alphanumeric string
                ]

                for pattern in workflow_patterns:
                    match = re.search(pattern, message)
                    if match:
                        parameters["workflow_id"] = match.group(1)
                        break

            # Return parameters if we have required ones
            required_params = [p.name for p in tool.parameters if p.required]
            if all(param in parameters for param in required_params):
                return parameters

            return None

        except Exception as e:
            logger.error(f"Error extracting parameters for {tool_id}: {e}")
            return None

    async def _handle_cookie_submission(
        self,
        session: SessionState,
        cookie_data: Dict[str, str],
        original_message: str
    ) -> str:
        """Handle LinkedIn cookie submission and verification"""
        if not COOKIE_VAULT_AVAILABLE:
            return "⚠️ Cookie vault services are not available in this environment. Please configure the vault dependencies to upload cookies."
        try:
            # Import cookie verification service
            from services.linkedin_cookie_verifier import verify_linkedin_cookies
            from services.cookie_vault_service import cookie_vault, VaultItemType

            # Extract li_at and jsessionid
            li_at = cookie_data.get("li_at") or cookie_data.get("li_at_encrypted")
            jsessionid = cookie_data.get("JSESSIONID") or cookie_data.get("jsessionid")

            if not li_at:
                return """❌ **Invalid Cookie Data**

I couldn't find a valid `li_at` cookie in your submission.

Please provide LinkedIn cookies in JSON format including:
- `li_at`: Your LinkedIn authentication token
- `JSESSIONID`: Your LinkedIn session ID (optional but recommended)

You can find these in your browser's developer tools under Application > Cookies > linkedin.com"""

            logger.info(f"Verifying LinkedIn cookies for user {session.user_id}")

            tenant_scope = session.tenant_id or str(session.organization_id)

            # Verify cookies with existing service
            verification_result = await verify_linkedin_cookies(
                li_at=li_at,
                jsessionid=jsessionid or "",
                tenant_id=tenant_scope,
                user_id=session.user_id
            )

            if verification_result.status.value == "valid":
                # Store encrypted cookies in vault
                vault_data = {
                    "li_at": li_at,
                    "jsessionid": jsessionid or "",
                    "verified_at": datetime.now(timezone.utc).isoformat(),
                    "username": verification_result.username,
                    "full_name": verification_result.full_name,
                    "profile_url": verification_result.profile_url
                }

                # Generate expiry time (30 days)
                expires_at = datetime.now(timezone.utc) + timedelta(days=30)

                # Store in vault
                vault_item_id = await cookie_vault.store_vault_item(
                    tenant_id=tenant_scope,
                    user_id=str(session.user_id),
                    item_type=VaultItemType.LINKEDIN_COOKIE,
                    label=f"LinkedIn Session - {verification_result.full_name}",
                    sensitive_data=vault_data,
                    expires_at=expires_at,
                    metadata={
                        "username": verification_result.username,
                        "verification_date": datetime.now(timezone.utc).isoformat()
                    }
                )

                # Update session
                session.cookie_status = "verified_and_stored"
                session.verified_profile = {
                    "username": verification_result.username,
                    "full_name": verification_result.full_name,
                    "profile_url": verification_result.profile_url,
                    "vault_item_id": vault_item_id
                }

                return f"""✅ **LinkedIn Cookie Verified and Stored**

**Profile**: {verification_result.full_name} (@{verification_result.username})
**Status**: Successfully verified and encrypted
**Storage**: Secure vault with AES-256-GCM encryption
**Expires**: {expires_at.strftime('%Y-%m-%d')}

🔒 Your LinkedIn session is now active and secure. You can now:
• Send LinkedIn messages through introducer workflows
• Access LinkedIn features requiring authentication
• Manage cookies through organization settings

Your credentials are encrypted and will never be displayed again."""

            else:
                error_msg = verification_result.error_message or "Verification failed"
                return f"""❌ **LinkedIn Cookie Verification Failed**

**Status**: {verification_result.status.value}
**Error**: {error_msg}

Please ensure your LinkedIn cookies are:
1. Current and not expired
2. From an active LinkedIn session
3. Copied correctly from your browser

To get fresh cookies:
1. Log into LinkedIn in your browser
2. Open Developer Tools (F12)
3. Go to Application > Cookies > linkedin.com
4. Copy the `li_at` and `JSESSIONID` values
5. Submit them in JSON format"""

        except Exception as e:
            logger.error(f"Error handling cookie submission: {e}")
            return f"""❌ **Cookie Processing Error**

There was an error processing your LinkedIn cookies: {str(e)}

Please ensure:
1. Cookies are in valid JSON format
2. You have the required `li_at` value
3. Cookies are current and not expired

Try again or contact support if the issue persists."""

    async def _handle_conversation_flow(
        self,
        session: SessionState,
        message: str
    ) -> Optional[str]:
        """Handle active conversation flows (like prospect addition)"""
        if session.conversation_context.get("active") and session.conversation_context.get("type"):
            context_type = session.conversation_context["type"]

            if context_type == "prospect_addition":
                # Integrate with existing conversational prospects service
                try:
                    from openai import AsyncOpenAI
                    import os

                    # Create OpenAI client for prospect parsing
                    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                    tenant_value = session.tenant_id or session.organization_id
                    if tenant_value is None or str(tenant_value).strip() == "":
                        session.conversation_context = {"active": False}
                        return "I can't continue the prospect workflow without a tenant. Please restart after signing in."
                    tenant_scope = str(tenant_value).strip()

                    response = await conversational_prospects.process_conversation_response(
                        session.session_id,
                        message,
                        client,
                        tenant_id=tenant_scope,
                        metadata={
                            "user_id": session.user_id,
                            "tenant_id": tenant_scope,
                        },
                    )

                    # Check if conversation completed
                    conversation_state = await conversational_prospects.get_conversation_state(
                        session.session_id,
                        tenant_id=tenant_scope,
                    )
                    if not conversation_state or conversation_state.get("step") == "completed":
                        session.conversation_context = {"active": False}
                        session.status = SessionStatus.ACTIVE

                    return response

                except ImportError:
                    logger.error("Could not import required services for conversation flow")
                    session.conversation_context = {"active": False}
                    return "Conversation service is temporarily unavailable. Please try again later."

        return None

    async def _handle_informational_query(self, session: SessionState, message: str) -> str:
        """Handle general informational queries and web search"""
        kb_result = self.knowledge_base.lookup(message, session.user_role)
        if kb_result:
            logger.debug(
                "Knowledge base hit for topic '%s' (audience=%s, guardrail=%s)",
                kb_result.topic,
                kb_result.audience,
                kb_result.guardrail is not None,
            )
            return self._format_knowledge_response(kb_result)

        try:
            from services.browser_service import browser_service

            # Check if this looks like a web search query
            if self._is_search_query(message):
                logger.info(f"Processing web search query: {message}")

                # Perform web search
                search_result = await browser_service.search(message, max_results=3)

                if search_result.status == "success" and search_result.results:
                    # Add citations to session
                    for citation in search_result.results:
                        session.citations.append({
                            "id": citation.id,
                            "title": citation.title,
                            "url": citation.url,
                            "domain": citation.domain
                        })

                    # Format response with citations
                    response = browser_service.format_search_response(search_result, include_citations=True)

                    return f"""🔍 **Search Results for: "{message}"**

{response}

💡 Click any citation ID to view the full source, or ask me to search for more specific information."""

                else:
                    # Search failed or no results
                    error_msg = search_result.error_message or "No relevant results found"
                    return f"""🔍 I searched for "{message}" but couldn't find specific information: {error_msg}

I can help you with:
• **Prospect management** - Say "add a new prospect" to get started
• **LinkedIn integration** - Submit your LinkedIn cookies for messaging
• **Workflow status** - Check progress of running processes
• **Help** - Get a full list of capabilities

Try a more specific search query or ask about Tallwave Link features."""

        except Exception as e:
            logger.error(f"Error in web search: {e}")

        # Fallback response for non-search queries or search errors
        return f"""I understand you're asking: "{message}"

I can help you with:
• **Prospect management** - Say "add a new prospect" to get started
• **LinkedIn integration** - Submit your LinkedIn cookies for messaging
• **Workflow status** - Check progress of running processes
• **Web search** - Ask questions like "Who is the CEO of [company]?"
• **Help** - Get a full list of capabilities

What specific task would you like help with?"""

    def _format_knowledge_response(self, result: KnowledgeResult) -> str:
        """Format knowledge base responses with optional guardrails."""
        if result.is_guardrail:
            return f"🔒 {result.guardrail}"

        sections = [f"📘 **{result.topic}**", "", result.answer.strip()]

        if result.guardrail:
            sections.append("")
            sections.append(f"⚠️ {result.guardrail}")

        if result.references:
            sections.append("")
            sections.append("**References**")
            for reference in result.references:
                sections.append(f"• {reference}")

        return "\n".join(sections).strip()

    def _is_search_query(self, message: str) -> bool:
        """Determine if message is a web search query"""
        message_lower = message.lower()

        # Search indicators
        search_patterns = [
            r"who is\s+(?:the\s+)?(?:ceo|chief executive|president|founder)",
            r"what is\s+",
            r"when did\s+",
            r"where is\s+",
            r"how (?:much|many|does)\s+",
            r"tell me about\s+",
            r"information about\s+",
            r"details on\s+",
            r"find\s+(?:me\s+)?(?:info|information)\s+(?:on|about)",
            r"search\s+for\s+",
            r"look up\s+"
        ]

        # Company/executive patterns
        company_patterns = [
            r"(?:ceo|chief executive|president|founder)\s+(?:of\s+)?[\w\s]+",
            r"[\w\s]+\s+(?:company|corp|corporation|inc|llc)",
            r"executives?\s+at\s+[\w\s]+",
            r"leadership\s+(?:of|at)\s+[\w\s]+"
        ]

        # Check for search patterns
        for pattern in search_patterns + company_patterns:
            if re.search(pattern, message_lower):
                return True

        # Check for question words at start
        question_starters = ["who", "what", "when", "where", "why", "how", "which"]
        first_word = message_lower.split()[0] if message_lower.split() else ""

        return first_word in question_starters

    async def _audit_interaction(
        self,
        session: SessionState,
        user_message: str,
        agent_response: str,
        security_result = None
    ):
        """Audit log the chat interaction with enhanced security context"""
        try:
            audit_details = {
                "user_id": session.user_id,
                "organization_id": session.organization_id,
                "message_length": len(user_message),
                "response_length": len(agent_response),
                "session_status": session.status.value,
                "has_verified_profile": bool(session.verified_profile),
                "cookie_status": session.cookie_status,
                "tenant_isolation_enabled": self.tenant_isolation_enabled,
                "security_level": self.security_level.value
            }

            # Add security filtering results if available
            if security_result:
                audit_details.update({
                    "security_score": security_result.security_score,
                    "redactions_count": security_result.redactions_count,
                    "violations_detected": len(security_result.violations),
                    "violation_types": [v.violation_type.value for v in security_result.violations]
                })

            await agent_logger.log_event(
                event_type=AgentEventType.USER_INTERACTION,
                level=LogLevel.INFO,
                agent_id="master_chat_agent",
                session_id=session.session_id,
                details=audit_details
            )
        except Exception as e:
            logger.error(f"Failed to audit interaction: {e}")

    async def _fetch_user_org_details(self, user_id: int, organization_id: int) -> Optional[Dict[str, Any]]:
        """Fetch user and organization details for validation."""
        try:
            user_record = await db.get_user_by_id(user_id)
            if not user_record:
                return None

            tenant_raw = user_record.get("tenant_id")
            tenant_id_str = str(tenant_raw).strip() if tenant_raw is not None else ""
            tenant_identifier = tenant_id_str or "default"

            organization_record: Optional[Dict[str, Any]] = None
            if PORTAL_DB_AVAILABLE and portal_get_conn and portal_query:
                try:
                    with portal_get_conn() as conn:
                        org_rows = portal_query(
                            conn,
                            """
                            SELECT id, tenant_id, name, subscription_tier, status
                            FROM organizations
                            WHERE id = ? OR tenant_id = ?
                            ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END
                            LIMIT 1
                            """,
                            (organization_id, tenant_raw, organization_id),
                        )
                        if org_rows:
                            organization_record = dict(org_rows[0])
                except Exception as lookup_error:
                    logger.debug(
                        "Unable to fetch organization details for user %s: %s",
                        user_id,
                        lookup_error,
                    )
            else:
                logger.debug(
                    "Portal database unavailable; skipping organization lookup for user %s",
                    user_id,
                )

            organization_key = str(
                organization_record.get("id") if organization_record else organization_id
            )
            org_tenant_id = organization_record.get("tenant_id") if organization_record else None

            matches_tenant = (
                tenant_identifier == "default"
                or (org_tenant_id is not None and str(org_tenant_id) == str(tenant_raw))
                or organization_key == str(tenant_raw)
            )

            return {
                "user": user_record,
                "organization": organization_record,
                "tenant_id": tenant_identifier,
                "organization_id": organization_key,
                "subscription_tier": (organization_record or {}).get("subscription_tier"),
                "matches_tenant": bool(matches_tenant),
            }
        except Exception as e:
            logger.error(f"Failed to fetch user/org details for user {user_id}, org {organization_id}: {e}")
            return None

    async def _fetch_prospect_by_id(
        self,
        prospect_id: int,
        organization_id: int,
        user_id: Optional[int] = None,
        *,
        tenant_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch prospect details by ID within organization scope."""
        try:
            tenant_scope = (tenant_id or "").strip() if tenant_id else ""
            if not tenant_scope:
                tenant_scope = str(organization_id)

            prospect = await db.get_prospect_by_id(
                prospect_id=prospect_id,
                user_id=user_id,
                tenant_id=tenant_scope
            )
            return prospect
        except Exception as e:
            logger.error(f"Failed to fetch prospect {prospect_id} for org {organization_id}: {e}")
            return None

    async def _fetch_workflow_status(self, workflow_id: str, organization_id: int) -> Optional[Dict[str, Any]]:
        """Fetch workflow status and progress information."""
        if not WORKFLOW_COORDINATOR_AVAILABLE or workflow_coordinator is None:
            logger.debug(
                "Workflow coordinator not available; skipping workflow status lookup for %s",
                workflow_id,
            )
            return None
        try:
            workflow_summary = await workflow_coordinator.get_workflow_status(workflow_id)
            if not workflow_summary:
                return None

            return {
                "workflow_id": workflow_summary.workflow_id,
                "status": workflow_summary.status.value if hasattr(workflow_summary.status, "value") else str(workflow_summary.status),
                "current_step": workflow_summary.stage,
                "prospects_processed": workflow_summary.prospects_processed,
                "connectors_found": workflow_summary.connectors_found,
                "emails_scheduled": workflow_summary.emails_scheduled,
                "created_at": workflow_summary.created_at.isoformat() if workflow_summary.created_at else None,
                "updated_at": workflow_summary.updated_at.isoformat() if workflow_summary.updated_at else None,
                "completed_at": workflow_summary.completed_at.isoformat() if workflow_summary.completed_at else None,
                "metadata": workflow_summary.metadata or {}
            }
        except Exception as e:
            logger.error(f"Failed to fetch workflow {workflow_id} for org {organization_id}: {e}")
            return None

    def _format_workflow_status(self, workflow_data: Dict[str, Any]) -> str:
        """Format workflow status for user display."""
        if not workflow_data:
            return "❌ No active workflow found."

        status = workflow_data.get('status', 'unknown')
        workflow_type = workflow_data.get('type', 'Unknown')
        progress = workflow_data.get('progress', {})

        # Create status icon
        status_icons = {
            'running': '🔄',
            'completed': '✅',
            'failed': '❌',
            'paused': '⏸️',
            'pending': '⏳'
        }

        icon = status_icons.get(status.lower(), '❓')

        # Format basic status
        formatted = f"{icon} **{workflow_type}** workflow: `{status}`\n"

        # Add progress details if available
        if progress:
            current_step = progress.get('current_step', 'N/A')
            total_steps = progress.get('total_steps', 'N/A')
            formatted += f"📍 Step: {current_step}/{total_steps}\n"

            if 'description' in progress:
                formatted += f"📝 {progress['description']}\n"

        # Add timing information
        if 'started_at' in workflow_data:
            formatted += f"⏰ Started: {workflow_data['started_at']}\n"

        if 'estimated_completion' in workflow_data:
            formatted += f"🎯 ETA: {workflow_data['estimated_completion']}\n"

        return formatted.strip()

    def _format_prospect_summary(self, prospect_data: Dict[str, Any]) -> str:
        """Format prospect information for user display."""
        if not prospect_data:
            return "❌ No prospect information available."

        name = prospect_data.get('full_name', 'Unknown')
        title = prospect_data.get('title', 'Unknown Title')
        company = prospect_data.get('company', 'Unknown Company')

        formatted = f"👤 **{name}**\n"
        formatted += f"💼 {title} at {company}\n"

        # Add contact information if available
        if 'email' in prospect_data:
            formatted += f"📧 {prospect_data['email']}\n"

        if 'linkedin_url' in prospect_data:
            formatted += f"🔗 [LinkedIn Profile]({prospect_data['linkedin_url']})\n"

        # Add workflow-related information
        if 'workflow_status' in prospect_data:
            status = prospect_data['workflow_status']
            formatted += f"🔄 Workflow: {status}\n"

        return formatted.strip()

    def cleanup_expired_sessions(self):
        """Clean up expired sessions (should be called periodically)"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=self.session_timeout_hours)
        expired_sessions = [
            sid for sid, session in self.sessions.items()
            if session.last_activity < cutoff_time
        ]

        for session_id in expired_sessions:
            del self.sessions[session_id]
            logger.info(f"Cleaned up expired session: {session_id}")

        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")

    async def _ensure_context_session(self, session_id: str, user_id: int, organization_id: int):
        """Ensure conversation context is initialized for session"""
        try:
            # Check if context manager has this session
            if conversation_context_manager.current_session_id != session_id:
                await conversation_context_manager.start_session(
                    session_id=session_id,
                    user_id=user_id,
                    organization_id=organization_id
                )
        except Exception as e:
            logger.error(f"Failed to initialize context session: {e}")

    async def get_conversation_summary(self, session_id: str) -> Dict[str, Any]:
        """Get conversation summary for a session"""
        try:
            if conversation_context_manager.current_session_id == session_id:
                return await conversation_context_manager.generate_conversation_summary(
                    include_insights=True,
                    include_metrics=True
                )
            else:
                return {"error": "Session not found or not active"}
        except Exception as e:
            logger.error(f"Failed to get conversation summary: {e}")
            return {"error": "Failed to generate summary"}

    async def get_conversation_context(self, session_id: str) -> Dict[str, Any]:
        """Get conversation context for a session"""
        try:
            if conversation_context_manager.current_session_id == session_id:
                return await conversation_context_manager.get_conversation_context(
                    include_summaries=True,
                    max_turns=20
                )
            else:
                return {"error": "Session not found or not active"}
        except Exception as e:
            logger.error(f"Failed to get conversation context: {e}")
            return {"error": "Failed to retrieve context"}

# Global Master Agent instance (may be unavailable in minimal environments)
try:
    master_chat_agent = MasterChatAgent()
except Exception as exc:  # pragma: no cover - defensive guard
    logger.warning("Master chat agent unavailable during module import: %s", exc)
    master_chat_agent = None
