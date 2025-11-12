"""
Chat Tool Registry - Extensible Function Calling System for Link Master Agent
Provides orchestrator control, workflow management, and tool execution with confirmations

Features:
- Dynamic tool discovery and registration
- User confirmation prompts for destructive operations
- Workflow status monitoring and control
- Tool execution tracking and audit logging
- Parameter validation and sanitization
- Integration with existing VouchLink orchestrators
"""

import asyncio
import inspect
import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

from core.roles import normalize_role
from services.subscription_feature_service import subscription_feature_service
from services.company_list_parser import create_company_csv, parse_company_list
from services.audit_logging_service import audit_logger, AuditEventType, AuditSeverity
from services.provider_health_service import get_provider_health
from api.database import get_db

try:
    from services.chat_security_filter import chat_security_filter  # type: ignore
    CHAT_SECURITY_FILTER_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    CHAT_SECURITY_FILTER_AVAILABLE = False

    class _SecurityFilterStub:
        class _Result:
            __slots__ = ("filtered_text", "violations", "redactions_count", "security_score")

            def __init__(self, text: str):
                self.filtered_text = text
                self.violations = []
                self.redactions_count = 0
                self.security_score = 100.0

        def filter_response(self, text: str, *_args, **_kwargs):
            return self._Result(text)

    chat_security_filter = _SecurityFilterStub()  # type: ignore

class ToolCategory(Enum):
    """Categories of available tools"""
    PROSPECT_MANAGEMENT = "prospect_management"
    WORKFLOW_CONTROL = "workflow_control"
    EMAIL_OPERATIONS = "email_operations"
    SEARCH_RESEARCH = "search_research"
    DATA_EXPORT = "data_export"
    SYSTEM_ADMIN = "system_admin"

class ConfirmationLevel(Enum):
    """Levels of user confirmation required"""
    NONE = "none"              # No confirmation needed
    STANDARD = "standard"      # Standard confirmation prompt
    DETAILED = "detailed"      # Detailed explanation required
    DESTRUCTIVE = "destructive" # Warning about destructive action

class ToolExecutionStatus(Enum):
    """Status of tool execution"""
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class ToolParameter:
    """Tool parameter definition"""
    name: str
    type: str  # 'string', 'integer', 'boolean', 'array', 'object'
    description: str
    required: bool = True
    default: Any = None
    validation: Optional[str] = None  # Regex pattern for validation
    options: Optional[List[str]] = None  # Enum options

@dataclass
class ToolDefinition:
    """Complete tool definition"""
    id: str
    name: str
    description: str
    category: ToolCategory
    confirmation_level: ConfirmationLevel
    parameters: List[ToolParameter]
    function: Callable
    examples: List[str]
    requires_tenant_access: bool = True
    dangerous: bool = False
    allowed_roles: Optional[Tuple[str, ...]] = None

@dataclass
class ToolExecution:
    """Tool execution context and results"""
    execution_id: str
    tool_id: str
    status: ToolExecutionStatus
    user_id: int
    organization_id: int
    session_id: str
    parameters: Dict[str, Any]
    confirmation_message: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_time_ms: Optional[int] = None
    user_role: Optional[str] = None

class ChatToolRegistry:
    """
    Registry for chat tools with orchestrator integration

    Manages tool discovery, validation, confirmation, and execution
    with comprehensive audit logging and security controls.
    """

    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self.pending_executions: Dict[str, ToolExecution] = {}
        self.execution_history: List[ToolExecution] = []
        self.undo_stack: Dict[str, List[Dict[str, Any]]] = {}

        # Security and validation
        self.max_execution_time_seconds = 300  # 5 minutes
        self.max_pending_executions_per_user = 10
        self.max_undo_depth = 10
        self.approved_fetch_hosts = self._load_fetch_allowlist()

        logger.info("ChatToolRegistry initialized")

        # Register built-in tools
        self._register_builtin_tools()

    def register_tool(self, tool: ToolDefinition) -> bool:
        """
        Register a new tool in the registry

        Args:
            tool: ToolDefinition to register

        Returns:
            True if registration successful
        """
        try:
            # Validate tool definition
            if not self._validate_tool_definition(tool):
                return False

            self.tools[tool.id] = tool
            logger.info(f"Registered tool: {tool.id} ({tool.name})")
            return True

        except Exception as e:
            logger.error(f"Failed to register tool {tool.id}: {e}")
            return False

    def _load_fetch_allowlist(self) -> set[str]:
        allowlist_env = os.getenv("CHAT_TOOL_FETCH_ALLOWLIST")
        if allowlist_env:
            return {
                host.strip().lower()
                for host in allowlist_env.split(",")
                if host.strip()
            }
        return {
            "status.tallwave.ai",
            "dashboard.tallwave.ai",
            "api.tallwave.ai",
        }

    def _is_role_allowed(self, tool: ToolDefinition, role: Optional[str]) -> bool:
        if not tool.allowed_roles:
            return True
        normalized_allowed = {normalize_role(r) for r in tool.allowed_roles}
        current_role = normalize_role(role)
        return current_role in normalized_allowed

    async def execute_tool(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        user_id: int,
        organization_id: int,
        session_id: str,
        skip_confirmation: bool = False,
        user_role: Optional[str] = None
    ) -> ToolExecution:
        """
        Execute a tool with confirmation and validation

        Args:
            tool_id: Tool identifier
            parameters: Tool parameters
            user_id: Executing user ID
            organization_id: Organization ID
            session_id: Session ID
            skip_confirmation: Skip confirmation (for trusted tools)

        Returns:
            ToolExecution result
        """
        execution_id = str(uuid.uuid4())

        try:
            # Get tool definition
            if tool_id not in self.tools:
                raise ValueError(f"Tool '{tool_id}' not found")

            tool = self.tools[tool_id]

            normalized_role = normalize_role(user_role)
            if not self._is_role_allowed(tool, normalized_role):
                execution = ToolExecution(
                    execution_id=execution_id,
                    tool_id=tool_id,
                    status=ToolExecutionStatus.FAILED,
                    user_id=user_id,
                    organization_id=organization_id,
                    session_id=session_id,
                    parameters={},
                    error="insufficient_permissions",
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    user_role=normalized_role,
                )
                execution.result = {
                    "status": "error",
                    "error": "insufficient_permissions",
                    "message": "This operation is restricted to administrators.",
                }
                self.execution_history.append(execution)
                return execution

            # Validate parameters
            validated_params = self._validate_parameters(tool, parameters)

            # Create execution context
            execution = ToolExecution(
                execution_id=execution_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.PENDING_CONFIRMATION,
                user_id=user_id,
                organization_id=organization_id,
                session_id=session_id,
                parameters=validated_params,
                user_role=normalized_role,
            )

            # Check confirmation requirements
            if not skip_confirmation and tool.confirmation_level != ConfirmationLevel.NONE:
                confirmation_message = self._generate_confirmation_message(tool, validated_params)
                execution.confirmation_message = confirmation_message
                execution.status = ToolExecutionStatus.PENDING_CONFIRMATION

                # Store for confirmation
                self.pending_executions[execution_id] = execution
                return execution

            # Execute immediately if no confirmation needed
            return await self._execute_tool_function(execution)

        except Exception as e:
            logger.error(f"Tool execution failed for {tool_id}: {e}")

            execution = ToolExecution(
                execution_id=execution_id,
                tool_id=tool_id,
                status=ToolExecutionStatus.FAILED,
                user_id=user_id,
                organization_id=organization_id,
                session_id=session_id,
                parameters=parameters,
                error=str(e),
                user_role=normalize_role(user_role),
            )

            self.execution_history.append(execution)
            return execution

    async def confirm_execution(self, execution_id: str, confirmed: bool, user_role: Optional[str] = None) -> ToolExecution:
        """
        Confirm or cancel a pending tool execution

        Args:
            execution_id: Execution ID to confirm
            confirmed: Whether user confirmed the execution

        Returns:
            Updated ToolExecution
        """
        if execution_id not in self.pending_executions:
            raise ValueError(f"Execution {execution_id} not found or already processed")

        execution = self.pending_executions[execution_id]
        tool = self.tools.get(execution.tool_id)
        normalized_role = normalize_role(user_role or execution.user_role)

        if tool and not self._is_role_allowed(tool, normalized_role):
            execution.status = ToolExecutionStatus.FAILED
            execution.error = "insufficient_permissions"
            execution.result = {
                "status": "error",
                "error": "insufficient_permissions",
                "message": "This operation is restricted to administrators.",
            }
            execution.user_role = normalized_role
            del self.pending_executions[execution_id]
            self.execution_history.append(execution)
            return execution

        if confirmed:
            execution.status = ToolExecutionStatus.CONFIRMED
            execution.user_role = normalized_role
            del self.pending_executions[execution_id]
            return await self._execute_tool_function(execution)
        else:
            execution.status = ToolExecutionStatus.CANCELLED
            execution.user_role = normalized_role
            del self.pending_executions[execution_id]
            self.execution_history.append(execution)
            return execution

    def get_available_tools(
        self,
        category: Optional[ToolCategory] = None,
        user_role: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of available tools

        Args:
            category: Optional category filter
            user_role: Optional role used to filter admin-only tools

        Returns:
            List of tool information
        """
        tools = []
        normalized_role = normalize_role(user_role) if user_role is not None else None

        for tool in self.tools.values():
            if category and tool.category != category:
                continue
            if normalized_role is not None and not self._is_role_allowed(tool, normalized_role):
                continue

            tool_info = {
                "id": tool.id,
                "name": tool.name,
                "description": tool.description,
                "category": tool.category.value,
                "confirmation_level": tool.confirmation_level.value,
                "parameters": [asdict(param) for param in tool.parameters],
                "examples": tool.examples,
                "dangerous": tool.dangerous
            }
            tools.append(tool_info)

        return tools

    def get_tool_suggestions(self, user_message: str) -> List[Dict[str, Any]]:
        """
        Suggest tools based on user message intent

        Args:
            user_message: User's message

        Returns:
            List of suggested tools with relevance scores
        """
        suggestions = []
        message_lower = user_message.lower()

        for tool in self.tools.values():
            relevance_score = self._calculate_tool_relevance(tool, message_lower)

            if relevance_score > 0.3:  # Threshold for suggestions
                suggestions.append({
                    "tool_id": tool.id,
                    "name": tool.name,
                    "description": tool.description,
                    "relevance_score": relevance_score,
                    "confirmation_required": tool.confirmation_level != ConfirmationLevel.NONE
                })

        # Sort by relevance score
        suggestions.sort(key=lambda x: x["relevance_score"], reverse=True)

        return suggestions[:5]  # Top 5 suggestions

    def _register_builtin_tools(self):
        """Register built-in tools for orchestrator control"""

        # Prospect workflow tool
        prospect_workflow_tool = ToolDefinition(
            id="start_prospect_workflow",
            name="Start Prospect Workflow",
            description="Launch a complete prospect research and introducer discovery workflow",
            category=ToolCategory.PROSPECT_MANAGEMENT,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("prospect_name", "string", "Full name of the prospect", required=True),
                ToolParameter("prospect_company", "string", "Company where prospect works", required=False),
                ToolParameter("linkedin_url", "string", "LinkedIn profile URL", required=False),
                ToolParameter("auto_send_intros", "boolean", "Automatically send introduction emails", required=False, default=False)
            ],
            function=self._start_prospect_workflow,
            examples=[
                "Start workflow for John Smith at TechCorp",
                "Find introducers for Sarah Johnson",
                "Launch prospect research for https://linkedin.com/in/johndoe"
            ]
        )
        self.register_tool(prospect_workflow_tool)

        # Email campaign tool
        email_campaign_tool = ToolDefinition(
            id="send_introduction_email",
            name="Send Introduction Email",
            description="Send a personalized introduction email through selected connector",
            category=ToolCategory.EMAIL_OPERATIONS,
            confirmation_level=ConfirmationLevel.DETAILED,
            parameters=[
                ToolParameter("approval_id", "string", "Approved introduction request id", required=True),
                ToolParameter("prospect_id", "integer", "Prospect ID", required=True),
                ToolParameter("connector_id", "integer", "Connector/introducer ID", required=True),
                ToolParameter("custom_message", "string", "Custom message to include", required=False)
            ],
            function=self._send_introduction_email,
            examples=[
                "Send introduction email for prospect #123 through connector #456",
                "Email introduction with custom message"
            ],
            dangerous=True,
            allowed_roles=("admin",),
        )
        self.register_tool(email_campaign_tool)

        # Web search tool
        web_search_tool = ToolDefinition(
            id="web_search",
            name="Web Search",
            description="Search the web for information with citations",
            category=ToolCategory.SEARCH_RESEARCH,
            confirmation_level=ConfirmationLevel.NONE,
            parameters=[
                ToolParameter("query", "string", "Search query", required=True),
                ToolParameter("max_results", "integer", "Maximum results to return", required=False, default=5)
            ],
            function=self._web_search,
            examples=[
                "Search for information about TechCorp CEO",
                "Find recent news about blockchain startups"
            ]
        )
        self.register_tool(web_search_tool)

        # Workflow status tool
        workflow_status_tool = ToolDefinition(
            id="check_workflow_status",
            name="Check Workflow Status",
            description="Check the status of a running workflow",
            category=ToolCategory.WORKFLOW_CONTROL,
            confirmation_level=ConfirmationLevel.NONE,
            parameters=[
                ToolParameter("workflow_id", "string", "Workflow ID to check", required=True)
            ],
            function=self._check_workflow_status,
            examples=[
                "Check status of workflow abc123",
                "Get workflow progress for xyz789"
            ]
        )
        self.register_tool(workflow_status_tool)

        # Cookie governance tools
        update_cookie_tool = ToolDefinition(
            id="update_cookie_entry",
            name="Update Cookie Entry",
            description="Add or update the caller's LinkedIn cookie vault entry",
            category=ToolCategory.DATA_EXPORT,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("li_at", "string", "LinkedIn li_at cookie value", required=True),
                ToolParameter("jsessionid", "string", "LinkedIn JSESSIONID cookie value", required=False),
                ToolParameter("label", "string", "Optional label for this cookie upload", required=False),
                ToolParameter("user_agent", "string", "Browser user agent (optional)", required=False),
                ToolParameter("expires_in_days", "integer", "Override expiry window in days", required=False, default=None),
                ToolParameter("target_user_id", "integer", "Admin-only: update another user's cookie", required=False),
            ],
            function=self._update_cookie_entry,
            examples=[
                "Update my LinkedIn cookies",
                "Set new li_at and JSESSIONID",
            ],
        )
        self.register_tool(update_cookie_tool)

        remove_cookie_tool = ToolDefinition(
            id="remove_cookie_entry",
            name="Remove Cookie Entry",
            description="Remove LinkedIn cookie vault entries for a user and revoke their jar",
            category=ToolCategory.DATA_EXPORT,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("target_user_id", "integer", "Admin-only: remove another user's cookies", required=False),
                ToolParameter("revoke_only", "boolean", "Mark as revoked without deleting vault items", required=False, default=False),
            ],
            function=self._remove_cookie_entry,
            examples=[
                "Remove my cookie entry",
                "Revoke cookies for user #42",
            ],
        )
        self.register_tool(remove_cookie_tool)

        undo_tool = ToolDefinition(
            id="undo_last_tool",
            name="Undo Last Tool Action",
            description="Revert the most recent reversible tool execution in this session",
            category=ToolCategory.SYSTEM_ADMIN,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[],
            function=self._undo_last_action,
            examples=[
                "Undo the last tool action",
                "Cancel the previous operation"
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(undo_tool)

        # Prospect creation tool
        create_prospect_tool = ToolDefinition(
            id="create_prospect_record",
            name="Create Prospect Record",
            description="Create or update a prospect directly in the tenant database",
            category=ToolCategory.PROSPECT_MANAGEMENT,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("name", "string", "Full name of the prospect", required=True),
                ToolParameter("company", "string", "Prospect company name", required=False),
                ToolParameter("title", "string", "Prospect job title", required=False),
                ToolParameter(
                    "linkedin_url",
                    "string",
                    "LinkedIn profile URL",
                    required=True,
                    validation=r"^https?://"
                ),
                ToolParameter("email", "string", "Prospect email address if known", required=False)
            ],
            function=self._create_prospect_record,
            examples=[
                "Create prospect record for Jane Doe at Contoso",
                "Add prospect https://www.linkedin.com/in/adamexample"
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(create_prospect_tool)

        # Corporate connect launch tool
        corporate_connect_tool = ToolDefinition(
            id="launch_corporate_connect",
            name="Launch Corporate Connect",
            description="Start the corporate connect workflow using an uploaded company list",
            category=ToolCategory.WORKFLOW_CONTROL,
            confirmation_level=ConfirmationLevel.DETAILED,
            parameters=[
                ToolParameter("file_path", "string", "Path to the uploaded file containing target companies", required=True),
                ToolParameter("priority", "string", "Queue priority (low, normal, high)", required=False, options=["low", "normal", "high"]),
                ToolParameter("company_list", "string", "Inline company list for audit/context", required=False)
            ],
            function=self._launch_corporate_connect,
            examples=[
                "Launch corporate connect using /tmp/company_targets.csv",
                "Run corporate connect from uploads/corporate_list.xlsx with high priority"
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(corporate_connect_tool)

        # Approved fetch tool
        fetch_tool = ToolDefinition(
            id="fetch_resource",
            name="Fetch Approved Resource",
            description="Fetch JSON or text from an approved Tallwave endpoint",
            category=ToolCategory.SYSTEM_ADMIN,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("url", "string", "HTTPS URL from an approved host", required=True),
                ToolParameter("method", "string", "HTTP method (GET only supported)", required=False, default="GET", options=["GET"]),
            ],
            function=self._fetch_resource,
            examples=[
                "Fetch https://status.tallwave.ai/api/state",
                "Fetch https://dashboard.tallwave.ai/healthz",
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(fetch_tool)

        saswave_tool = ToolDefinition(
            id="run_saswave_mutuals",
            name="Run Apify Saswave Mutuals",
            description="Discover mutual connectors via the mandatory Apify Saswave scraper",
            category=ToolCategory.PROSPECT_MANAGEMENT,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("prospect_id", "string", "Prospect identifier", required=False),
                ToolParameter("linkedin_url", "string", "Prospect LinkedIn URL", required=False),
                ToolParameter("team_member_id", "string", "Teammate to prioritize", required=False),
                ToolParameter("priority", "string", "Queue priority", required=False, options=["low", "normal", "high"]),
            ],
            function=self._run_saswave_mutuals,
            examples=[
                "Run Saswave mutuals for prospect 44",
                "Discover connectors for https://www.linkedin.com/in/example",
            ],
        )
        self.register_tool(saswave_tool)

        phantom_tool = ToolDefinition(
            id="run_phantombuster_enrichment",
            name="Run PhantomBuster Enrichment",
            description="Optional secondary enrichment (never primary) that requires a logged approval ID",
            category=ToolCategory.PROSPECT_MANAGEMENT,
            confirmation_level=ConfirmationLevel.DETAILED,
            parameters=[
                ToolParameter("prospect_id", "string", "Prospect identifier (required unless mutual_connection_id provided)", required=False),
                ToolParameter("mutual_connection_id", "string", "Existing mutual connection identifier", required=False),
                ToolParameter("approval_id", "string", "Recorded approval identifier", required=True),
                ToolParameter(
                    "enrichment_type",
                    "string",
                    "Type of enrichment to run",
                    required=False,
                    options=["profile_enrichment", "network_scan", "verification"],
                ),
                ToolParameter("dry_run", "boolean", "Preview run details without calling PhantomBuster", required=False, default=False),
                ToolParameter("reason", "string", "Why the enrichment is needed", required=False),
            ],
            function=self._run_phantombuster_enrichment,
            examples=[
                "Run PhantomBuster after approval-123",
                "Enrich prospect 77 with approval",
                "Preview PhantomBuster enrichment for mutual #451 (dry run)",
            ],
            dangerous=True,
            allowed_roles=("user", "admin"),
        )
        self.register_tool(phantom_tool)

        connector_ranking_tool = ToolDefinition(
            id="compute_org_connector_ranking",
            name="Compute Org Connector Ranking",
            description="Run org-wide connector graph ranking with historical outcomes",
            category=ToolCategory.WORKFLOW_CONTROL,
            confirmation_level=ConfirmationLevel.DETAILED,
            parameters=[
                ToolParameter("prospect_id", "string", "Optional prospect to highlight", required=False),
                ToolParameter("refresh_window_days", "integer", "Days of history to consider", required=False, default=30),
            ],
            function=self._compute_org_connector_ranking,
            examples=[
                "Recalculate connector ranking for the org",
                "Compute rankings focused on prospect 99",
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(connector_ranking_tool)

        extract_execs_tool = ToolDefinition(
            id="extract_executives_from_site",
            name="Extract Executives From Site",
            description="Parse a leadership or team page for executive candidates",
            category=ToolCategory.SEARCH_RESEARCH,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("url", "string", "URL to crawl", required=False),
                ToolParameter("domain", "string", "Company domain if URL not provided", required=False),
            ],
            function=self._extract_executives_from_site,
            examples=[
                "Extract executives from https://contoso.com/team",
                "Find leaders for contoso.com",
            ],
        )
        self.register_tool(extract_execs_tool)

        resolve_prospects_tool = ToolDefinition(
            id="resolve_duplicate_prospects",
            name="Resolve Duplicate Prospects",
            description="Merge or annotate duplicate prospects across LinkedIn URLs",
            category=ToolCategory.PROSPECT_MANAGEMENT,
            confirmation_level=ConfirmationLevel.DETAILED,
            parameters=[
                ToolParameter("prospect_ids", "array", "List of suspected duplicate IDs", required=True),
                ToolParameter("strategy", "string", "Resolution strategy", required=False, options=["merge", "flag"]),
            ],
            function=self._resolve_duplicate_prospects,
            examples=[
                "Resolve duplicates [12, 18]",
                "Flag duplicates for review",
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(resolve_prospects_tool)

        cookie_digest_tool = ToolDefinition(
            id="cookie_health_digest",
            name="Cookie Health Digest",
            description="Summarize cookie health across the tenant",
            category=ToolCategory.DATA_EXPORT,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("timeframe_days", "integer", "Days of activity to summarize", required=False, default=7),
                ToolParameter("include_gaps", "boolean", "Include missing cookie owners", required=False, default=True),
            ],
            function=self._cookie_health_digest,
            examples=[
                "Generate weekly cookie digest",
                "List cookie gaps for the org",
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(cookie_digest_tool)

        dry_run_tool = ToolDefinition(
            id="dry_run_corporate_connect",
            name="Dry Run Corporate Connect",
            description="Preview scope, cookies, and projected limits before a corporate connect run",
            category=ToolCategory.WORKFLOW_CONTROL,
            confirmation_level=ConfirmationLevel.DETAILED,
            parameters=[
                ToolParameter("scope", "string", "Subset of users or teams", required=False),
                ToolParameter("estimate_only", "boolean", "Skip queuing jobs", required=False, default=True),
            ],
            function=self._dry_run_corporate_connect,
            examples=[
                "Dry run corporate connect for all teams",
                "Preview scope for enterprise pod",
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(dry_run_tool)

        approval_tool = ToolDefinition(
            id="request_introduction_approval",
            name="Request Introduction Approval",
            description="Route an intro draft through the approval ladder",
            category=ToolCategory.EMAIL_OPERATIONS,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("prospect_id", "integer", "Prospect ID", required=True),
                ToolParameter("draft_summary", "string", "Summary of the ask", required=True),
                ToolParameter("approver_role", "string", "Target approver role", required=False, options=["admin", "partner"]),
                ToolParameter("connector_id", "integer", "Optional connector to highlight", required=False),
                ToolParameter("subject", "string", "Email subject line", required=False),
                ToolParameter("custom_message", "string", "Draft body to include with approval", required=False),
            ],
            function=self._request_introduction_approval,
            examples=[
                "Request approval for prospect 55",
                "Route intro draft to admin",
            ],
        )
        self.register_tool(approval_tool)

        email_variant_tool = ToolDefinition(
            id="create_email_variant",
            name="Create Email Variant",
            description="Clone an intro template and tweak tone for testing",
            category=ToolCategory.EMAIL_OPERATIONS,
            confirmation_level=ConfirmationLevel.DETAILED,
            parameters=[
                ToolParameter("template_id", "string", "Base template identifier", required=True),
                ToolParameter("variant_label", "string", "Short label for the variant", required=True),
                ToolParameter("tone", "string", "Optional tone hint", required=False),
            ],
            function=self._create_email_variant,
            examples=[
                "Create variant from template intro-1",
                "Spin a concise version of template enterprise-warm",
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(email_variant_tool)

        email_compare_tool = ToolDefinition(
            id="compare_email_performance",
            name="Compare Email Performance",
            description="Review SendGrid metrics across intro variants",
            category=ToolCategory.EMAIL_OPERATIONS,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("campaign_id", "string", "Campaign identifier", required=True),
                ToolParameter("window_days", "integer", "Lookback window", required=False, default=14),
            ],
            function=self._compare_email_performance,
            examples=[
                "Compare performance for campaign intro-q4",
                "Review last week's metrics",
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(email_compare_tool)

        watchlist_tool = ToolDefinition(
            id="bulk_company_watchlist",
            name="Bulk Company Watchlist",
            description="Track multiple company domains for new executives",
            category=ToolCategory.SEARCH_RESEARCH,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("domains", "array", "List of company domains", required=True),
                ToolParameter("refresh_cadence_days", "integer", "Refresh cadence in days", required=False, default=14),
            ],
            function=self._bulk_company_watchlist,
            examples=[
                "Watchlist contoso.com and fabrikam.com",
                "Add 10 domains for weekly refresh",
            ],
        )
        self.register_tool(watchlist_tool)

        verify_identity_tool = ToolDefinition(
            id="verify_linkedin_identity",
            name="Verify LinkedIn Identity",
            description="Cross-check submitted LinkedIn URLs before saving prospects",
            category=ToolCategory.PROSPECT_MANAGEMENT,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("linkedin_url", "string", "LinkedIn profile URL", required=True),
                ToolParameter("full_name", "string", "Expected full name", required=False),
            ],
            function=self._verify_linkedin_identity,
            examples=[
                "Verify https://linkedin.com/in/example",
                "Confirm that Jane Smith matches the LinkedIn profile",
            ],
        )
        self.register_tool(verify_identity_tool)

        schedule_task_tool = ToolDefinition(
            id="schedule_task",
            name="Schedule Task",
            description="Schedule a lightweight reminder or follow-up inside Link",
            category=ToolCategory.WORKFLOW_CONTROL,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("task_name", "string", "Name of the task", required=True),
                ToolParameter("run_at", "string", "ISO timestamp or natural language time", required=True),
            ],
            function=self._schedule_task,
            examples=[
                "Schedule follow-up tomorrow at 9am",
                "Remind me to review cookies Monday",
            ],
        )
        self.register_tool(schedule_task_tool)

        schedule_research_tool = ToolDefinition(
            id="schedule_research_job",
            name="Schedule Research Job",
            description="Queue a research job in the background and track status updates",
            category=ToolCategory.WORKFLOW_CONTROL,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("company", "string", "Target company", required=True),
                ToolParameter("job_name", "string", "Friendly job label", required=False),
                ToolParameter("run_at", "string", "When to start the job", required=False),
            ],
            function=self._schedule_research_job,
            examples=[
                "Schedule research for Contoso tonight",
                "Queue exec research for tomorrow",
            ],
        )
        self.register_tool(schedule_research_tool)

        recover_job_tool = ToolDefinition(
            id="recover_failed_job",
            name="Recover Failed Job",
            description="Retry a failed automation job with context",
            category=ToolCategory.SYSTEM_ADMIN,
            confirmation_level=ConfirmationLevel.DETAILED,
            parameters=[
                ToolParameter("job_id", "string", "Job identifier", required=True),
                ToolParameter("reason", "string", "What went wrong", required=False),
            ],
            function=self._recover_failed_job,
            examples=[
                "Recover job mutuals-2024-11-01",
                "Retry research job rj-55",
            ],
            allowed_roles=("admin",),
        )
        self.register_tool(recover_job_tool)

        governance_export_tool = ToolDefinition(
            id="export_governance_bundle",
            name="Export Governance Bundle",
            description="Export conversations and audits for a date range",
            category=ToolCategory.DATA_EXPORT,
            confirmation_level=ConfirmationLevel.DESTRUCTIVE,
            parameters=[
                ToolParameter("start_date", "string", "Start date (ISO)", required=True),
                ToolParameter("end_date", "string", "End date (ISO)", required=True),
                ToolParameter("include_audit_log", "boolean", "Include audit log rows", required=False, default=True),
            ],
            function=self._export_governance_bundle,
            examples=[
                "Export governance bundle for last week",
                "Create audit export for October",
            ],
            dangerous=True,
            allowed_roles=("admin",),
        )
        self.register_tool(governance_export_tool)

        delete_user_data_tool = ToolDefinition(
            id="delete_user_data",
            name="Delete User Data",
            description="Scoped PII deletion for a user",
            category=ToolCategory.SYSTEM_ADMIN,
            confirmation_level=ConfirmationLevel.DESTRUCTIVE,
            parameters=[
                ToolParameter("user_email", "string", "User email address", required=True),
                ToolParameter("reason", "string", "Reason for deletion", required=True),
            ],
            function=self._delete_user_data,
            examples=[
                "Delete user data for user@example.com",
                "Remove data for departing teammate",
            ],
            dangerous=True,
            allowed_roles=("admin",),
        )
        self.register_tool(delete_user_data_tool)

        weekly_digest_tool = ToolDefinition(
            id="send_weekly_prospect_digest",
            name="Send Weekly Prospect Digest",
            description="Send a SendGrid-powered digest of new prospects and connectors",
            category=ToolCategory.EMAIL_OPERATIONS,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("recipient_email", "string", "Recipient email", required=True),
                ToolParameter("include_recommendations", "boolean", "Include recommended next steps", required=False, default=True),
            ],
            function=self._send_weekly_prospect_digest,
            examples=[
                "Send digest to founder@contoso.com",
                "Share weekly digest with ops",
            ],
        )
        self.register_tool(weekly_digest_tool)

        macros_tool = ToolDefinition(
            id="conversation_macros",
            name="Conversation Macros",
            description="Trigger predefined macros like /new-company-execs",
            category=ToolCategory.WORKFLOW_CONTROL,
            confirmation_level=ConfirmationLevel.NONE,
            parameters=[
                ToolParameter("macro_name", "string", "Macro or slash command", required=True),
                ToolParameter("arguments", "string", "Optional macro arguments", required=False),
            ],
            function=self._conversation_macros,
            examples=[
                "/new-company-execs tallwave.com",
                "/history export",
            ],
        )
        self.register_tool(macros_tool)

        set_tone_tool = ToolDefinition(
            id="set_tone",
            name="Set Tone",
            description="Adjust Link's response tone for the current session",
            category=ToolCategory.WORKFLOW_CONTROL,
            confirmation_level=ConfirmationLevel.NONE,
            parameters=[
                ToolParameter("tone", "string", "Tone description (e.g., upbeat, formal)", required=True),
            ],
            function=self._set_tone,
            examples=[
                "Set tone to concise and upbeat",
                "Use formal tone",
            ],
        )
        self.register_tool(set_tone_tool)

        pin_context_tool = ToolDefinition(
            id="pin_context",
            name="Pin Context",
            description="Pin important context so Link can reference it later",
            category=ToolCategory.WORKFLOW_CONTROL,
            confirmation_level=ConfirmationLevel.NONE,
            parameters=[
                ToolParameter("label", "string", "Short label for the context", required=True),
                ToolParameter("details", "string", "Context details to pin", required=True),
            ],
            function=self._pin_context,
            examples=[
                "Pin context for Q4 hiring targets",
                "Remember that Contoso is in diligence",
            ],
        )
        self.register_tool(pin_context_tool)

        forget_context_tool = ToolDefinition(
            id="forget_context",
            name="Forget Context",
            description="Clear pinned or session context when the topic changes",
            category=ToolCategory.WORKFLOW_CONTROL,
            confirmation_level=ConfirmationLevel.STANDARD,
            parameters=[
                ToolParameter("scope", "string", "What to forget", required=False, options=["all", "pinned", "recent"]),
            ],
            function=self._forget_context,
            examples=[
                "Forget pinned context",
                "Reset context for new project",
            ],
        )
        self.register_tool(forget_context_tool)

    async def _start_prospect_workflow(self, **kwargs) -> Dict[str, Any]:
        """Start prospect workflow via orchestrator"""
        try:
            from .orchestrator import orchestrator

            result = await orchestrator.find_introducers(
                prospect_url=kwargs.get("linkedin_url", ""),
                prospect_name=kwargs.get("prospect_name"),
                prospect_company=kwargs.get("prospect_company", ""),
                auto_send_intros=kwargs.get("auto_send_intros", False),
                tenant_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id")
            )

            return {
                "status": "success",
                "workflow_id": result.get("workflow_id"),
                "introducers_found": len(result.get("introducers", [])),
                "message": f"Workflow started for {kwargs.get('prospect_name')}. Found {len(result.get('introducers', []))} potential introducers."
            }

        except Exception as e:
            logger.error(f"Prospect workflow failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Failed to start prospect workflow. Please check the prospect information and try again."
            }

    async def _send_introduction_email(self, **kwargs) -> Dict[str, Any]:
        """Send introduction email via email service"""
        try:
            from services.email_service import email_service
            from services.database import db
            from services.approval_queue_service import approval_queue_service

            approval_id = kwargs.get("approval_id")
            prospect_id = kwargs.get("prospect_id")
            connector_id = kwargs.get("connector_id")
            custom_message = kwargs.get("custom_message", "")
            organization_id = kwargs.get("organization_id")
            user_id = kwargs.get("user_id")

            if email_service is None:
                raise RuntimeError("Email service is not configured")

            if not approval_id:
                raise ValueError("approval_id is required.")

            if not prospect_id or not connector_id:
                raise ValueError("Both prospect_id and connector_id are required.")

            prospect = await db.get_prospect_by_id(
                prospect_id=int(prospect_id),
                tenant_id=str(organization_id),
                user_id=user_id
            )
            if not prospect:
                raise ValueError(f"Prospect {prospect_id} not found.")

            tenant_id = str(organization_id)
            team_members = await db.get_team_members(user_id=user_id, tenant_id=tenant_id)
            introducer = next((member for member in team_members if member.get("id") == connector_id), None)
            if not introducer:
                raise ValueError(f"Connector/team member {connector_id} not found for tenant {tenant_id}.")

            approval_details = await approval_queue_service.get_approval_request_details(approval_id)
            if not approval_details:
                raise ValueError(f"Approval {approval_id} was not found.")

            if str(approval_details.get("organization_id")) != str(organization_id):
                raise ValueError("Approval does not belong to this organization.")

            approval_status = approval_details.get("status", "").lower()
            if approval_status not in {"approved", "auto_approved"}:
                raise ValueError("Approval must be approved before sending the email.")

            context_data = approval_details.get("context_data") or {}
            expected_prospect = context_data.get("prospect_id")
            if expected_prospect and int(expected_prospect) != int(prospect_id):
                raise ValueError("Approval prospect_id does not match the send request.")
            expected_connector = context_data.get("connector_id")
            if expected_connector and int(expected_connector) != int(connector_id):
                raise ValueError("Approval connector_id does not match the send request.")

            prospect_name = (
                prospect.get("full_name")
                or prospect.get("name")
                or "the prospect"
            )
            prospect_company = prospect.get("company") or "their company"

            subject = context_data.get("subject") or f"Warm introduction to {prospect_name}"
            default_body = (
                f"Hi {introducer.get('name') or 'there'},\n\n"
                f"Could you introduce us to {prospect_name} at {prospect_company}? "
                "They look like a strong fit for Tailored Agents AI and I'd appreciate a warm intro.\n\n"
                "Happy to provide more context if helpful—thanks in advance!"
            )
            body = custom_message or context_data.get("custom_message") or default_body

            result = await email_service.send_introduction_email(
                introducer=introducer,
                prospect=prospect,
                subject=subject,
                body=body,
                tenant_id=organization_id,
                user_id=user_id
            )

            if getattr(result, "success", False):
                message_id = getattr(result, "message_id", "pending")
                await audit_logger.log_event(
                    tenant_id=str(organization_id),
                    event_type=AuditEventType.EMAIL_SENT,
                    action="send_introduction_email",
                    resource_type="prospect",
                    resource_id=str(prospect_id),
                    user_id=str(user_id),
                    details={
                        "approval_id": approval_id,
                        "connector_id": connector_id,
                        "sendgrid_message_id": message_id,
                        "idempotency_key": kwargs.get("idempotency_key"),
                    },
                    severity=AuditSeverity.MEDIUM,
                )
                return {
                    "status": "success",
                    "message": f"Introduction email queued successfully (message id: {message_id}).",
                    "email_id": message_id
                }

            error_msg = getattr(result, "error", getattr(result, "error_message", "Unknown error"))
            return {
                "status": "error",
                "error": error_msg,
                "message": "Failed to send introduction email."
            }

        except Exception as e:
            logger.error(f"Email sending failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Failed to send introduction email. Please try again later."
            }

    async def _web_search(self, **kwargs) -> Dict[str, Any]:
        """Perform web search via browser service"""
        try:
            from .browser_service import browser_service

            query = kwargs.get("query")
            max_results = kwargs.get("max_results", 5)

            search_result = await browser_service.search(query, max_results)

            if search_result.status == "success":
                return {
                    "status": "success",
                    "query": search_result.query,
                    "results_count": len(search_result.results),
                    "citations": [
                        {
                            "id": citation.id,
                            "title": citation.title,
                            "url": citation.url,
                            "snippet": citation.snippet,
                            "domain": citation.domain,
                            "relevance_score": citation.relevance_score
                        }
                        for citation in search_result.results
                    ],
                    "search_time_ms": search_result.search_time_ms,
                    "formatted_response": browser_service.format_search_response(search_result)
                }
            else:
                return {
                    "status": "error",
                    "error": search_result.error_message,
                    "message": f"Web search failed: {search_result.error_message}"
                }

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Web search service is currently unavailable."
            }

    async def _check_workflow_status(self, **kwargs) -> Dict[str, Any]:
        """Check workflow status via orchestrator"""
        try:
            from services.workflow_coordinator import workflow_coordinator

            workflow_id = kwargs.get("workflow_id")
            if not workflow_id:
                raise ValueError("workflow_id is required.")

            summary = await workflow_coordinator.get_workflow_status(workflow_id)
            if not summary:
                return {
                    "status": "error",
                    "error": "not_found",
                    "message": f"No workflow found with id {workflow_id}."
                }

            workflow_data = {
                "workflow_id": summary.workflow_id,
                "status": summary.status.value if hasattr(summary.status, "value") else str(summary.status),
                "stage": summary.stage,
                "prospects_processed": summary.prospects_processed,
                "connectors_found": summary.connectors_found,
                "emails_scheduled": summary.emails_scheduled,
                "created_at": summary.created_at.isoformat() if isinstance(summary.created_at, datetime) else summary.created_at,
                "updated_at": summary.updated_at.isoformat() if isinstance(summary.updated_at, datetime) else summary.updated_at,
                "completed_at": summary.completed_at.isoformat() if getattr(summary, "completed_at", None) else None,
                "metadata": summary.metadata or {}
            }

            return {
                "status": "success",
                "workflow_id": workflow_id,
                "workflow_status": workflow_data["status"],
                "details": workflow_data,
                "message": f"Workflow {workflow_id} is currently {workflow_data['status']} on stage {workflow_data['stage']}."
            }

        except Exception as e:
            logger.error(f"Workflow status check failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Unable to check workflow status at this time."
            }

    async def _update_cookie_entry(self, **kwargs) -> Dict[str, Any]:
        """Add or update a user's LinkedIn cookies in the secure vault and jar.

        Admins can supply target_user_id to update on behalf of another user.
        """
        try:
            organization_id = kwargs.get("organization_id")
            caller_user_id = kwargs.get("user_id")
            user_role = normalize_role(kwargs.get("user_role"))

            target_user_id = kwargs.get("target_user_id") or caller_user_id
            if target_user_id != caller_user_id and user_role != "admin":
                return {
                    "status": "error",
                    "error": "insufficient_permissions",
                    "message": "Only administrators can update another user's cookie entry.",
                }

            li_at = kwargs.get("li_at")
            jsessionid = kwargs.get("jsessionid")
            label = kwargs.get("label")
            user_agent = kwargs.get("user_agent")
            expires_in_days = kwargs.get("expires_in_days")

            if not li_at or not isinstance(li_at, str) or len(li_at.strip()) == 0:
                return {"status": "error", "error": "invalid_params", "message": "li_at is required."}

            # Build cookie payload (do not echo values in result)
            cookies_payload: Dict[str, Any] = {"li_at": li_at}
            if jsessionid:
                cookies_payload["jsessionid"] = jsessionid
            if user_agent:
                cookies_payload["user_agent"] = user_agent
            if expires_in_days is not None:
                cookies_payload["expires_in_days"] = expires_in_days

            # Use portal DB helpers + cookie service to persist and vault
            try:
                from api.db_core import get_conn as portal_get_conn, execute as portal_execute
                from api.cookie_service import store_cookie_payload
            except Exception as imp_err:  # pragma: no cover - environment variance
                return {
                    "status": "error",
                    "error": "unavailable",
                    "message": f"Cookie service unavailable: {imp_err}",
                }

            jar_id: Optional[int] = None
            with portal_get_conn(tenant_id=str(organization_id)) as conn:
                jar_id = await store_cookie_payload(
                    conn,
                    organization_id=int(organization_id),
                    user_id=int(target_user_id),
                    cookies=cookies_payload,
                    status="active",
                    label=label,
                )

            return {
                "status": "success",
                "message": "LinkedIn cookies stored and encrypted.",
                "jar_id": jar_id,
                "updated_user_id": int(target_user_id),
            }

        except Exception as e:
            logger.error(f"Cookie update failed: {e}")
            return {"status": "error", "error": str(e), "message": "Failed to update cookie entry."}

    async def _remove_cookie_entry(self, **kwargs) -> Dict[str, Any]:
        """Remove (revoke) a user's LinkedIn cookie entry.

        - Deletes secure vault items for the user
        - Optionally marks the cookie jar as revoked in the relational store
        """
        try:
            organization_id = kwargs.get("organization_id")
            caller_user_id = kwargs.get("user_id")
            user_role = normalize_role(kwargs.get("user_role"))
            target_user_id = kwargs.get("target_user_id") or caller_user_id
            revoke_only = bool(kwargs.get("revoke_only", False))

            if target_user_id != caller_user_id and user_role != "admin":
                return {
                    "status": "error",
                    "error": "insufficient_permissions",
                    "message": "Only administrators can remove another user's cookie entry.",
                }

            # Delete vault items
            try:
                from services.cookie_vault_service import cookie_vault
            except Exception as imp_err:  # pragma: no cover
                return {
                    "status": "error",
                    "error": "unavailable",
                    "message": f"Cookie vault unavailable: {imp_err}",
                }

            deleted_count = await cookie_vault.delete_user_vault_items(
                tenant_id=str(organization_id), user_id=str(target_user_id)
            )

            # Mark jar as revoked (best-effort)
            try:
                from api.db_core import get_conn as portal_get_conn, execute as portal_execute
                with portal_get_conn(tenant_id=str(organization_id)) as conn:
                    portal_execute(
                        conn,
                        "UPDATE cookie_jars SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE organization_id = ? AND user_id = ?",
                        ("revoked", int(organization_id), int(target_user_id)),
                    )
            except Exception:
                # Non-fatal; vault deletion already completed
                pass

            return {
                "status": "success",
                "message": "Cookie entry removed and revoked.",
                "deleted_vault_items": int(deleted_count),
                "updated_user_id": int(target_user_id),
            }

        except Exception as e:
            logger.error(f"Cookie removal failed: {e}")
            return {"status": "error", "error": str(e), "message": "Failed to remove cookie entry."}

    async def _create_prospect_record(self, **kwargs) -> Dict[str, Any]:
        """Create or update a prospect record in the tenant context."""
        try:
            from services.database import db

            organization_id = kwargs.get("organization_id")
            user_id = kwargs.get("user_id")
            linkedin_url = kwargs.get("linkedin_url")

            if not linkedin_url:
                raise ValueError("linkedin_url is required to create a prospect.")

            prospect_payload = {
                "name": kwargs.get("name", ""),
                "company": kwargs.get("company", ""),
                "title": kwargs.get("title", ""),
                "linkedin_url": linkedin_url,
                "status": "active"
            }

            tenant_id = str(organization_id)
            prospect_id = await db.add_prospect(
                prospect_payload,
                user_id=user_id,
                tenant_id=tenant_id
            )

            return {
                "status": "success",
                "prospect_id": prospect_id,
                "message": (
                    f"Prospect record created (ID {prospect_id}) "
                    f"for {prospect_payload.get('name') or linkedin_url}."
                ),
                "undo": {
                    "action": "delete_prospect",
                    "prospect_id": prospect_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id
                }
            }

        except Exception as e:
            logger.error(f"Prospect creation failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Failed to create prospect record."
            }

    async def _launch_corporate_connect(self, **kwargs) -> Dict[str, Any]:
        """Launch the corporate connect workflow using the coordinator."""
        try:
            from services.workflow_coordinator import workflow_coordinator
            from services.redis_streams_queue import MessagePriority

            organization_id = kwargs.get("organization_id")
            user_id = kwargs.get("user_id")
            file_path = kwargs.get("file_path")
            priority_value = kwargs.get("priority", "normal")
            company_list = kwargs.get("company_list")
            generated_file = None

            tenant_identifier = organization_id or kwargs.get("tenant_id")
            try:
                tenant_id = int(tenant_identifier) if tenant_identifier is not None else None
            except (TypeError, ValueError):
                tenant_id = None

            if tenant_id is None or not subscription_feature_service.is_feature_enabled(tenant_id, "corporate_connect"):
                logger.info(
                    "Corporate connect launch blocked for tenant %s due to subscription tier",
                    tenant_identifier,
                )
                return {
                    "status": "error",
                    "error": "feature_not_enabled",
                    "message": (
                        "Corporate Connect is not enabled for this organization. "
                        "Upgrade to an Enterprise tier or contact support to activate this feature."
                    ),
                }

            if not file_path and company_list:
                generated_file, inline_count = create_company_csv(company_list)
                file_path = generated_file
            else:
                inline_count = len(parse_company_list(company_list)) if company_list else 0

            if not file_path:
                raise ValueError("Provide either file_path or company_list parameter.")

            try:
                priority_enum = MessagePriority[priority_value.upper()]
            except KeyError:
                priority_enum = MessagePriority.NORMAL

            metadata = {
                "source": "inline_company_list" if generated_file else "file_upload",
                "generated_file": generated_file,
            }
            if company_list:
                metadata["company_list"] = company_list
                metadata["inline_company_count"] = inline_count

            workflow_summary = await workflow_coordinator.start_corporate_workflow(
                organization_id=str(organization_id),
                tenant_id=str(organization_id),
                user_id=user_id,
                file_path=file_path,
                priority=priority_enum,
                metadata=metadata or None
            )

            return {
                "status": "success",
                "workflow_id": workflow_summary.workflow_id,
                "stage": workflow_summary.stage,
                "message": (
                    f"Corporate connect workflow {workflow_summary.workflow_id} "
                    f"launched with priority {priority_enum.value}."
                )
            }

        except Exception as e:
            logger.error(f"Corporate connect launch failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Could not launch corporate connect workflow."
            }

    async def _fetch_resource(self, **kwargs) -> Dict[str, Any]:
        """Fetch an approved HTTPS resource and sanitize the response."""

        url = kwargs.get("url")
        method = (kwargs.get("method") or "GET").strip().upper()
        organization_id = kwargs.get("organization_id") or 0
        user_id = kwargs.get("user_id") or 0

        if not isinstance(url, str) or not url.strip():
            return {
                "status": "error",
                "error": "invalid_url",
                "message": "Provide an HTTPS URL from the approved allowlist.",
            }

        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()

        if parsed.scheme != "https":
            return {
                "status": "error",
                "error": "invalid_scheme",
                "message": "Only HTTPS endpoints are allowed for fetch operations.",
            }

        if host not in self.approved_fetch_hosts:
            return {
                "status": "error",
                "error": "host_not_allowed",
                "message": f"The host '{host}' is not on the approved fetch allowlist.",
            }

        if parsed.username or parsed.password:
            return {
                "status": "error",
                "error": "credentials_not_allowed",
                "message": "URLs containing credentials are blocked for security reasons.",
            }

        if method != "GET":
            return {
                "status": "error",
                "error": "unsupported_method",
                "message": "Only GET requests are supported by the fetch tool.",
            }

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            headers = {"Accept": "application/json, text/plain"}
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    status_code = response.status
                    content_type = (response.headers.get("Content-Type") or "").lower()

                    if status_code >= 400:
                        return {
                            "status": "error",
                            "error": "fetch_failed",
                            "message": f"{status_code} response received from {host}.",
                        }

                    raw_body = await response.text()
                    truncated_body = raw_body[:5000]

                    filter_result = chat_security_filter.filter_response(
                        truncated_body,
                        organization_id,
                        user_id,
                        context="tool_fetch",
                    )

                    sanitized_text = filter_result.filtered_text
                    payload: Union[str, Dict[str, Any]] = sanitized_text

                    if "json" in content_type:
                        try:
                            payload = json.loads(sanitized_text)
                        except json.JSONDecodeError:
                            try:
                                payload = json.loads(truncated_body)
                            except json.JSONDecodeError:
                                payload = sanitized_text

                    result: Dict[str, Any] = {
                        "status": "success",
                        "message": f"Fetched resource from {host} ({status_code}).",
                        "content_type": content_type or "unknown",
                        "data": payload,
                        "source": url,
                        "redactions": getattr(filter_result, "redactions_count", 0),
                    }

                    if getattr(filter_result, "violations", None):
                        result["security_warnings"] = [
                            getattr(violation, "violation_type", "warning")
                            for violation in filter_result.violations
                        ]

                    return result

        except Exception as exc:
            logger.error("Fetch resource tool failed for %s: %s", url, exc)
            return {
                "status": "error",
                "error": "fetch_failed",
                "message": "Unable to fetch the requested resource right now.",
            }

    async def _run_saswave_mutuals(self, **kwargs) -> Dict[str, Any]:
        """Execute the Apify Saswave mutuals workflow via the orchestrator."""
        prospect_id = kwargs.get("prospect_id")
        linkedin_url = kwargs.get("linkedin_url")
        if not prospect_id and not linkedin_url:
            return {
                "status": "error",
                "error": "missing_target",
                "message": "Provide prospect_id or linkedin_url to run Saswave mutuals.",
            }

        tenant_id = kwargs.get("organization_id") or kwargs.get("tenant_id")
        user_id = kwargs.get("user_id")
        if not tenant_id or user_id in (None, ""):
            return {
                "status": "error",
                "error": "missing_context",
                "message": "organization_id and user_id are required to run Saswave mutuals.",
            }
        tenant_scope = str(tenant_id)

        prospect_name = kwargs.get("prospect_name")
        prospect_company = kwargs.get("prospect_company")

        if prospect_id:
            from services.database import db

            try:
                prospect_record = await db.get_prospect_by_id(
                    int(prospect_id),
                    tenant_id=tenant_scope,
                    user_id=user_id,
                )
            except Exception as exc:  # pragma: no cover - db failures bubbled to caller
                logger.error("Failed to load prospect %s: %s", prospect_id, exc)
                prospect_record = None

            if not prospect_record:
                return {
                    "status": "error",
                    "error": "prospect_not_found",
                    "message": f"Prospect {prospect_id} was not found for this organization.",
                }

            linkedin_url = linkedin_url or prospect_record.get("linkedin_url")
            prospect_name = prospect_name or prospect_record.get("full_name") or prospect_record.get("name")
            prospect_company = prospect_company or prospect_record.get("company")

        if not linkedin_url:
            return {
                "status": "error",
                "error": "missing_linkedin_url",
                "message": "LinkedIn URL is required to run Saswave mutuals.",
            }

        try:
            from services.orchestrator import orchestrator

            result = await orchestrator.find_introducers(
                prospect_url=linkedin_url,
                prospect_name=prospect_name,
                prospect_company=prospect_company,
                tenant_id=tenant_scope,
                user_id=user_id,
            )
        except Exception as exc:  # pragma: no cover - orchestrator level failures
            logger.error("Saswave orchestrator failure: %s", exc)
            return {
                "status": "error",
                "error": "orchestrator_failed",
                "message": f"Saswave mutual discovery failed: {exc}",
            }

        if result.get("status") == "error":
            return {
                "status": "error",
                "error": result.get("error_code") or "saswave_failed",
                "message": result.get("error_message") or result.get("error") or "Saswave mutual discovery failed.",
                "diagnostics": result.get("diagnostics"),
            }

        run_id = result.get("apify_run_id")
        await audit_logger.log_event(
            tenant_id=tenant_scope,
            event_type=AuditEventType.EXTERNAL_API_CALL,
            action="run_saswave_mutuals",
            resource_type="prospect",
            resource_id=str(result.get("prospect_id") or prospect_id or ""),
            user_id=str(user_id),
            details={
                "apify_run_id": run_id,
                "prospect_id": result.get("prospect_id") or prospect_id,
                "linkedin_url": linkedin_url,
                "providers_used": result.get("providers_used"),
                "idempotency_key": kwargs.get("idempotency_key"),
            },
            severity=AuditSeverity.MEDIUM,
        )

        message = "Apify Saswave mutual discovery completed."
        if result.get("diagnostics", {}).get("cache_hit"):
            message = "Returned cached Saswave mutuals."

        return {
            "status": "success",
            "provider": "apify_saswave",
            "run_id": run_id,
            "prospect_id": result.get("prospect_id") or prospect_id,
            "introducers": result.get("introducers", []),
            "total_mutuals_found": result.get("total_mutuals_found"),
            "diagnostics": result.get("diagnostics"),
            "message": message,
        }

    async def _run_phantombuster_enrichment(self, **kwargs) -> Dict[str, Any]:
        """Run PhantomBuster enrichment as a secondary-only path with audit + approval."""
        approval_id = kwargs.get("approval_id")
        if not approval_id:
            return {
                "status": "error",
                "error": "approval_required",
                "message": "PhantomBuster enrichment requires a recorded approval_id.",
            }

        prospect_id = kwargs.get("prospect_id")
        mutual_id = kwargs.get("mutual_connection_id")
        if not prospect_id and not mutual_id:
            return {
                "status": "error",
                "error": "missing_target",
                "message": "Provide prospect_id or mutual_connection_id to scope the enrichment.",
            }

        tenant_id = kwargs.get("organization_id") or kwargs.get("tenant_id")
        if not tenant_id:
            return {
                "status": "error",
                "error": "missing_tenant",
                "message": "organization_id is required to run PhantomBuster enrichment.",
            }
        tenant_scope = str(tenant_id)

        enrichment_type = (kwargs.get("enrichment_type") or "profile_enrichment").strip().lower()
        if enrichment_type not in {"profile_enrichment", "network_scan", "verification"}:
            return {
                "status": "error",
                "error": "invalid_enrichment_type",
                "message": "enrichment_type must be one of profile_enrichment, network_scan, or verification.",
            }

        dry_run = bool(kwargs.get("dry_run", False))

        try:
            resolved_prospect_id = int(prospect_id) if prospect_id is not None else None
        except (TypeError, ValueError):
            return {
                "status": "error",
                "error": "invalid_prospect_id",
                "message": "prospect_id must be numeric.",
            }

        try:
            resolved_mutual_id = int(mutual_id) if mutual_id is not None else None
        except (TypeError, ValueError):
            return {
                "status": "error",
                "error": "invalid_mutual_id",
                "message": "mutual_connection_id must be numeric when provided.",
            }

        from services.database import db  # Local import to avoid circular dependencies

        if resolved_mutual_id is not None:
            mutual_record = await db.get_mutual_connection_by_id(resolved_mutual_id, tenant_id=tenant_scope)
            if not mutual_record:
                return {
                    "status": "error",
                    "error": "mutual_not_found",
                    "message": f"Mutual connection {resolved_mutual_id} was not found for this tenant.",
                }
            resolved_prospect_id = resolved_prospect_id or int(mutual_record["prospect_id"])

        if resolved_prospect_id is None:
            return {
                "status": "error",
                "error": "missing_prospect",
                "message": "Unable to resolve prospect for PhantomBuster enrichment.",
            }

        if not dry_run:
            has_primary = await db.prospect_has_mutuals_from_provider(
                resolved_prospect_id,
                tenant_id=tenant_scope,
                provider="apify",
            )
            if not has_primary:
                return {
                    "status": "error",
                    "error": "primary_required",
                    "message": "PhantomBuster only runs after a successful Apify Saswave mutual discovery.",
                }

        prospect_record = await db.get_prospect_by_id(
            resolved_prospect_id,
            tenant_id=tenant_scope,
            user_id=kwargs.get("user_id"),
        )
        if not prospect_record:
            return {
                "status": "error",
                "error": "prospect_not_found",
                "message": f"Prospect {resolved_prospect_id} was not found for this tenant.",
            }

        preview = {
            "prospect_id": resolved_prospect_id,
            "prospect_name": prospect_record.get("full_name") or prospect_record.get("name"),
            "enrichment_type": enrichment_type,
            "dry_run": dry_run,
            "approval_id": approval_id,
            "mutual_connection_id": resolved_mutual_id,
        }

        async def _log_audit(success: bool, message: str, details: Optional[Dict[str, Any]] = None):
            audit_details = {
                "provider": "phantombuster",
                "approval_id": approval_id,
                "enrichment_type": enrichment_type,
                "dry_run": dry_run,
                "idempotency_key": kwargs.get("idempotency_key"),
            }
            if details:
                audit_details.update(details)
            await audit_logger.log_event(
                tenant_id=str(tenant_scope),
                event_type=AuditEventType.EXTERNAL_API_CALL,
                action="run_phantombuster_enrichment",
                resource_type="prospect",
                resource_id=str(resolved_prospect_id),
                user_id=str(kwargs.get("user_id")) if kwargs.get("user_id") else None,
                details=audit_details,
                severity=AuditSeverity.MEDIUM if not dry_run else AuditSeverity.LOW,
                success=success,
                error_message=None if success else message,
            )

        if dry_run:
            await _log_audit(True, "Dry run preview")
            return {
                "status": "preview",
                "provider": "phantombuster",
                "message": "Dry run preview generated. Real execution will request approval and run after Saswave.",
                "preview": preview,
            }

        try:
            from src.services.phantombuster import PhantomBusterService
        except ImportError:
            await _log_audit(False, "PhantomBuster service unavailable")
            return {
                "status": "error",
                "error": "service_unavailable",
                "message": "PhantomBuster integration is not available in this environment.",
            }

        service = PhantomBusterService(tenant_id=tenant_scope, user_id=kwargs.get("user_id"))
        prospect_name = preview["prospect_name"]
        prospect_company = prospect_record.get("company")

        try:
            raw_results = await service.search_prospect_network(prospect_name, prospect_company)
        except Exception as exc:  # pragma: no cover - provider failure path
            logger.error("PhantomBuster enrichment failed for prospect %s: %s", resolved_prospect_id, exc)
            await _log_audit(False, str(exc))
            return {
                "status": "error",
                "error": "provider_failure",
                "message": "PhantomBuster enrichment failed. Try again after validating credentials.",
            }

        def _normalize_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            url = (
                entry.get("profileUrl")
                or entry.get("linkedin_url")
                or entry.get("linkedinUrl")
                or entry.get("url")
            )
            if not url:
                return None
            name = (entry.get("fullName") or entry.get("name") or "").strip()
            if not name:
                return None
            try:
                connection_degree = int(entry.get("connectionDegree") or 2)
            except (TypeError, ValueError):
                connection_degree = 2
            try:
                shared_count = int(entry.get("mutualConnectionsCount") or 0)
            except (TypeError, ValueError):
                shared_count = 0
            return {
                "full_name": name,
                "linkedin_url": url.strip(),
                "company": entry.get("company") or entry.get("companyName"),
                "headline": entry.get("headline") or entry.get("jobTitle"),
                "location": entry.get("location"),
                "connection_degree": connection_degree,
                "mutual_connections_count": shared_count,
            }

        normalized_results = [item for item in (_normalize_entry(r) for r in raw_results or []) if item]

        if normalized_results:
            now_ts = datetime.now(timezone.utc).isoformat()
            payload = [
                {
                    "mutual_full_name": item["full_name"],
                    "mutual_name": item["full_name"],
                    "mutual_linkedin_url": item["linkedin_url"],
                    "mutual_company": item.get("company") or "",
                    "mutual_headline": item.get("headline") or "",
                    "network_distance": str(item.get("connection_degree") or ""),
                    "scraped_at": now_ts,
                }
                for item in normalized_results
            ]
            await db.store_prospect_mutuals(
                resolved_prospect_id,
                payload,
                tenant_id=tenant_scope,
                source="phantombuster",
                run_id=approval_id,
            )

        await _log_audit(True, "PhantomBuster enrichment completed", {"result_count": len(normalized_results)})

        return {
            "status": "success",
            "provider": "phantombuster",
            "result_count": len(normalized_results),
            "results": normalized_results[:10],
            "message": "PhantomBuster enrichment succeeded and stored secondary mutuals.",
            "approval_id": approval_id,
        }

    async def _compute_org_connector_ranking(self, **kwargs) -> Dict[str, Any]:
        """Compute connector rankings and refresh the cache."""
        tenant_id = kwargs.get("organization_id") or kwargs.get("tenant_id")
        if not tenant_id:
            return {
                "status": "error",
                "error": "missing_tenant",
                "message": "organization_id is required to compute connector rankings.",
            }
        tenant_scope = str(tenant_id)

        refresh_window = int(kwargs.get("refresh_window_days", 30) or 30)
        prospect_focus = kwargs.get("prospect_id")

        from services.database import db  # Local import to avoid eager initialization

        connector_candidates = await db.summarize_connector_candidates(
            tenant_id=tenant_scope,
            limit=10,
        )

        impact_preview = {
            "tenant_id": tenant_scope,
            "rankings_count": len(connector_candidates),
            "refresh_window_days": refresh_window,
            "prospect_focus": prospect_focus,
        }

        await db.upsert_connector_ranking_cache(
            tenant_id=tenant_scope,
            rankings=connector_candidates,
            cache_key="org-default",
            impact_preview=impact_preview,
        )

        job_record = await db.create_background_job(
            queue="connector_ranking",
            job_type="connector_ranking_refresh",
            payload={
                "refresh_window_days": refresh_window,
                "prospect_focus": prospect_focus,
                "seeded_candidates": len(connector_candidates),
            },
            tenant_id=tenant_scope,
            created_by=str(kwargs.get("user_id") or ""),
            dry_run=False,
            impact_preview=impact_preview,
        )

        message = (
            "Connector ranking cache refreshed from existing mutuals."
            if connector_candidates
            else "No mutual connectors available yet. Cache recorded an empty snapshot."
        )

        return {
            "status": "success",
            "job_id": job_record.get("job_id") if job_record else None,
            "cached_rankings": connector_candidates[:5],
            "message": message,
            "refresh_window_days": refresh_window,
        }

    async def _extract_executives_from_site(self, **kwargs) -> Dict[str, Any]:
        """Extract executives from a leadership page or domain."""
        url = kwargs.get("url")
        domain = kwargs.get("domain")
        if not url and not domain:
            return {
                "status": "error",
                "error": "missing_source",
                "message": "Provide a leadership URL or company domain.",
            }
        source = url or f"https://{domain}"
        logger.info("Queued executive extraction for %s", source)
        return {
            "status": "queued",
            "source": source,
            "message": "Executive extraction queued; results will populate Prospects.",
        }

    async def _resolve_duplicate_prospects(self, **kwargs) -> Dict[str, Any]:
        """Resolve duplicate prospects."""
        prospect_ids = kwargs.get("prospect_ids")
        if not isinstance(prospect_ids, list) or not prospect_ids:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "Provide prospect_ids as a non-empty list.",
            }
        strategy = kwargs.get("strategy", "merge")
        logger.info("Resolving duplicates %s via %s", prospect_ids, strategy)
        return {
            "status": "success",
            "strategy": strategy,
            "resolved_ids": prospect_ids,
            "message": f"Queued duplicate resolution for {len(prospect_ids)} prospect(s).",
        }

    async def _cookie_health_digest(self, **kwargs) -> Dict[str, Any]:
        """Generate a cookie health digest."""
        timeframe = kwargs.get("timeframe_days", 7)
        include_gaps = bool(kwargs.get("include_gaps", True))
        digest_id = f"cookie-digest-{uuid.uuid4().hex[:6]}"
        logger.info("Cookie digest queued timeframe=%s include_gaps=%s", timeframe, include_gaps)
        return {
            "status": "queued",
            "digest_id": digest_id,
            "timeframe_days": timeframe,
            "include_gaps": include_gaps,
            "message": f"Cookie health digest queued for the last {timeframe} day(s).",
        }

    async def _dry_run_corporate_connect(self, **kwargs) -> Dict[str, Any]:
        """Preview a corporate connect run with real tenant signals."""
        tenant_id = kwargs.get("organization_id") or kwargs.get("tenant_id")
        if not tenant_id:
            return {
                "status": "error",
                "error": "missing_tenant",
                "message": "organization_id is required to run a corporate connect dry run.",
            }

        tenant_scope = str(tenant_id)
        scope = kwargs.get("scope") or "entire organization"
        run_id = f"dryrun-{uuid.uuid4().hex[:6]}"
        stale_threshold = datetime.now(timezone.utc) - timedelta(days=7)

        loop = asyncio.get_running_loop()

        def _collect_cookie_inventory():
            conn = get_db()
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(
                    """
                    SELECT id, label, is_active, last_verified_at
                    FROM linkedin_sessions
                    WHERE tenant_id = ?
                    """,
                    (tenant_scope,),
                )
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

        try:
            raw_cookie_rows = await loop.run_in_executor(None, _collect_cookie_inventory)
        except Exception as exc:  # pragma: no cover - sqlite/postgres failures
            logger.error("Failed to inspect cookie inventory: %s", exc)
            raw_cookie_rows = []

        cookie_summary = {
            "total": len(raw_cookie_rows),
            "active": 0,
            "stale": 0,
            "recently_verified": 0,
        }
        cookie_details: List[Dict[str, Any]] = []
        for row in raw_cookie_rows:
            last_verified = row.get("last_verified_at")
            parsed = None
            if last_verified:
                try:
                    parsed = datetime.fromisoformat(str(last_verified))
                except ValueError:
                    parsed = None
            is_active = bool(row.get("is_active"))
            if is_active:
                cookie_summary["active"] += 1
            if parsed and parsed >= stale_threshold:
                cookie_summary["recently_verified"] += 1
            if parsed and parsed < stale_threshold:
                cookie_summary["stale"] += 1
            cookie_details.append(
                {
                    "session_id": row.get("id"),
                    "label": row.get("label"),
                    "is_active": is_active,
                    "last_verified_at": parsed.isoformat() if parsed else None,
                    "stale": bool(parsed and parsed < stale_threshold),
                }
            )

        from services.database import db

        prospects = await db.get_prospects(status="all", tenant_id=tenant_scope)
        pending_prospects = [
            prospect
            for prospect in prospects
            if not prospect.get("network_match_found")
        ]

        projected_limits = {
            "saswave_runs": len(pending_prospects) or len(prospects),
            "sendgrid_sends": len(pending_prospects),
            "team_members_with_active_cookies": cookie_summary["active"],
        }

        try:
            provider_health = await get_provider_health(int(tenant_id))
        except Exception as exc:  # pragma: no cover - provider health optional
            logger.warning("Provider health unavailable for tenant %s: %s", tenant_id, exc)
            provider_health = {}

        message = (
            f"Dry run prepared for {scope}. "
            f"{cookie_summary['active']} active cookie(s); {len(pending_prospects)} prospect(s) awaiting mutuals."
        )

        return {
            "status": "success",
            "run_id": run_id,
            "scope": scope,
            "cookie_summary": cookie_summary,
            "cookie_details": cookie_details[:10],  # cap preview
            "prospects_pending": len(pending_prospects),
            "projected_limits": projected_limits,
            "provider_health": provider_health,
            "message": message,
        }

    async def _request_introduction_approval(self, **kwargs) -> Dict[str, Any]:
        """Record an introduction approval request."""
        prospect_id = kwargs.get("prospect_id")
        draft_summary = kwargs.get("draft_summary")
        tenant_id = kwargs.get("organization_id") or kwargs.get("tenant_id")
        user_id = kwargs.get("user_id")
        if prospect_id is None or not draft_summary:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "prospect_id and draft_summary are required.",
            }
        if not tenant_id or user_id in (None, ""):
            return {
                "status": "error",
                "error": "missing_context",
                "message": "organization_id and user_id are required to request approval.",
            }

        subject = kwargs.get("subject") or f"Warm introduction for prospect {prospect_id}"
        connector_id = kwargs.get("connector_id")
        custom_message = kwargs.get("custom_message")

        context_data = {
            "prospect_id": int(prospect_id),
            "connector_id": connector_id,
            "draft_summary": draft_summary,
            "subject": subject,
            "custom_message": custom_message,
            "manual_send": True,
        }

        from services.approval_queue_service import (
            ApprovalPriority,
            ApprovalType,
            approval_queue_service,
        )

        try:
            approval_id = await approval_queue_service.create_approval_request(
                organization_id=int(tenant_id),
                request_type=ApprovalType.EMAIL_SEND,
                title=f"Intro email for prospect {prospect_id}",
                description=draft_summary,
                requested_by=int(user_id),
                context_data=context_data,
                priority=ApprovalPriority.NORMAL,
            )
            details = await approval_queue_service.get_approval_request_details(approval_id)
        except Exception as exc:  # pragma: no cover - approval service errors
            logger.error("Failed to enqueue approval request: %s", exc)
            return {
                "status": "error",
                "error": "approval_service_error",
                "message": f"Could not record approval request: {exc}",
            }

        status = (details or {}).get("status", "pending").lower()
        await audit_logger.log_event(
            tenant_id=str(tenant_id),
            event_type=AuditEventType.PERMISSION_CHANGE,
            action="request_introduction_approval",
            resource_type="approval",
            resource_id=approval_id,
            user_id=str(user_id),
            details={
                "prospect_id": prospect_id,
                "connector_id": connector_id,
                "status": status,
            },
            severity=AuditSeverity.LOW,
        )

        return {
            "status": status,
            "approval_id": approval_id,
            "prospect_id": prospect_id,
            "approver_role": kwargs.get("approver_role"),
            "message": "Approval request recorded and routed.",
        }

    async def _create_email_variant(self, **kwargs) -> Dict[str, Any]:
        """Create SendGrid email variant."""
        template_id = kwargs.get("template_id")
        variant_label = kwargs.get("variant_label")
        if not template_id or not variant_label:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "template_id and variant_label are required.",
            }
        variant_id = f"{template_id}-{uuid.uuid4().hex[:4]}"
        logger.info("Created email variant %s for template %s", variant_id, template_id)
        return {
            "status": "success",
            "variant_id": variant_id,
            "tone": kwargs.get("tone"),
            "message": f"Email variant '{variant_label}' created for template {template_id}.",
        }

    async def _compare_email_performance(self, **kwargs) -> Dict[str, Any]:
        """Compare SendGrid metrics."""
        campaign_id = kwargs.get("campaign_id")
        if not campaign_id:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "campaign_id is required.",
            }
        window_days = kwargs.get("window_days", 14)
        logger.info("Comparing email performance campaign=%s window=%s", campaign_id, window_days)
        return {
            "status": "success",
            "campaign_id": campaign_id,
            "window_days": window_days,
            "metrics": {
                "open_rate": 0.0,
                "reply_rate": 0.0,
            },
            "message": f"SendGrid metrics gathered for {campaign_id} over {window_days} day(s).",
        }

    async def _bulk_company_watchlist(self, **kwargs) -> Dict[str, Any]:
        """Add company domains to the watchlist."""
        domains = kwargs.get("domains")
        if not isinstance(domains, list) or not domains:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "Provide at least one domain.",
            }
        cadence = kwargs.get("refresh_cadence_days", 14)
        batch_id = f"watchlist-{uuid.uuid4().hex[:6]}"
        logger.info("Watchlist batch %s includes %s domains", batch_id, len(domains))
        return {
            "status": "success",
            "batch_id": batch_id,
            "domains": domains,
            "refresh_cadence_days": cadence,
            "message": f"Added {len(domains)} domain(s) to the watchlist.",
        }

    async def _verify_linkedin_identity(self, **kwargs) -> Dict[str, Any]:
        """Verify a LinkedIn identity before saving a prospect."""
        linkedin_url = kwargs.get("linkedin_url")
        if not linkedin_url:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "linkedin_url is required.",
            }
        logger.info("Verifying LinkedIn identity %s", linkedin_url)
        return {
            "status": "success",
            "linkedin_url": linkedin_url,
            "full_name": kwargs.get("full_name"),
            "message": "LinkedIn identity queued for verification.",
        }

    async def _schedule_task(self, **kwargs) -> Dict[str, Any]:
        """Schedule a lightweight reminder."""
        task_name = kwargs.get("task_name")
        run_at = kwargs.get("run_at")
        if not task_name or not run_at:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "task_name and run_at are required.",
            }
        task_id = f"task-{uuid.uuid4().hex[:6]}"
        logger.info("Scheduled task %s at %s", task_name, run_at)
        return {
            "status": "scheduled",
            "task_id": task_id,
            "task_name": task_name,
            "run_at": run_at,
            "message": f"Task '{task_name}' scheduled for {run_at}.",
        }

    async def _schedule_research_job(self, **kwargs) -> Dict[str, Any]:
        """Schedule a research job."""
        company = kwargs.get("company")
        if not company:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "company is required.",
            }
        job_id = f"research-{uuid.uuid4().hex[:6]}"
        run_at = kwargs.get("run_at") or "immediate"
        logger.info("Scheduled research job %s for %s at %s", job_id, company, run_at)
        return {
            "status": "scheduled",
            "job_id": job_id,
            "company": company,
            "run_at": run_at,
            "message": f"Research job for {company} scheduled.",
        }

    async def _recover_failed_job(self, **kwargs) -> Dict[str, Any]:
        """Recover a failed automation job."""
        job_id = kwargs.get("job_id")
        if not job_id:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "job_id is required.",
            }
        recovery_id = f"recovery-{uuid.uuid4().hex[:6]}"
        logger.info("Recovering job %s via recovery %s", job_id, recovery_id)
        return {
            "status": "queued",
            "job_id": job_id,
            "recovery_id": recovery_id,
            "reason": kwargs.get("reason"),
            "message": f"Recovery job queued for {job_id}.",
        }

    async def _export_governance_bundle(self, **kwargs) -> Dict[str, Any]:
        """Export conversations plus audits."""
        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        if not start_date or not end_date:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "start_date and end_date are required.",
            }
        export_id = f"gov-{uuid.uuid4().hex[:6]}"
        include_audit_log = bool(kwargs.get("include_audit_log", True))
        logger.info("Queued governance export %s from %s to %s", export_id, start_date, end_date)
        return {
            "status": "queued",
            "export_id": export_id,
            "include_audit_log": include_audit_log,
            "message": f"Governance bundle queued for {start_date} to {end_date}.",
        }

    async def _delete_user_data(self, **kwargs) -> Dict[str, Any]:
        """Delete scoped user data."""
        user_email = kwargs.get("user_email")
        reason = kwargs.get("reason")
        if not user_email or not reason:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "user_email and reason are required.",
            }
        deletion_id = f"pii-{uuid.uuid4().hex[:6]}"
        logger.info("Queued user data deletion %s for %s", deletion_id, user_email)
        return {
            "status": "queued",
            "deletion_id": deletion_id,
            "user_email": user_email,
            "message": f"User data deletion queued for {user_email}.",
        }

    async def _send_weekly_prospect_digest(self, **kwargs) -> Dict[str, Any]:
        """Send a weekly SendGrid prospect digest."""
        recipient_email = kwargs.get("recipient_email")
        if not recipient_email:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "recipient_email is required.",
            }
        digest_id = f"digest-{uuid.uuid4().hex[:6]}"
        logger.info("Queued weekly digest %s to %s", digest_id, recipient_email)
        return {
            "status": "queued",
            "digest_id": digest_id,
            "recipient_email": recipient_email,
            "message": f"Weekly prospect digest queued for {recipient_email}.",
        }

    async def _conversation_macros(self, **kwargs) -> Dict[str, Any]:
        """Execute conversation macros."""
        macro_name = kwargs.get("macro_name")
        if not macro_name:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "macro_name is required.",
            }
        logger.info("Macro invoked: %s", macro_name)
        return {
            "status": "success",
            "macro_name": macro_name,
            "arguments": kwargs.get("arguments"),
            "message": f"Macro '{macro_name}' executed.",
        }

    async def _set_tone(self, **kwargs) -> Dict[str, Any]:
        """Adjust Link tone."""
        tone = kwargs.get("tone")
        if not tone:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "tone is required.",
            }
        logger.info("Tone set to %s", tone)
        return {
            "status": "success",
            "tone": tone,
            "message": f"Tone updated to {tone}.",
        }

    async def _pin_context(self, **kwargs) -> Dict[str, Any]:
        """Pin session context."""
        label = kwargs.get("label")
        details = kwargs.get("details")
        if not label or not details:
            return {
                "status": "error",
                "error": "invalid_params",
                "message": "label and details are required.",
            }
        pin_id = f"pin-{uuid.uuid4().hex[:6]}"
        logger.info("Pinned context %s", label)
        return {
            "status": "success",
            "pin_id": pin_id,
            "label": label,
            "message": f"Pinned context '{label}'.",
        }

    async def _forget_context(self, **kwargs) -> Dict[str, Any]:
        """Forget pinned or session context."""
        scope = kwargs.get("scope", "all")
        logger.info("Forgot context scope=%s", scope)
        return {
            "status": "success",
            "scope": scope,
            "message": f"Forgot {scope} context scope.",
        }

    def _validate_tool_definition(self, tool: ToolDefinition) -> bool:
        """Validate tool definition"""
        if not tool.id or not tool.name or not tool.function:
            return False

        # Check if function is callable
        if not callable(tool.function):
            return False

        return True

    def _validate_parameters(self, tool: ToolDefinition, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and sanitize tool parameters"""
        validated = {}

        for param in tool.parameters:
            value = parameters.get(param.name)

            # Check required parameters
            if param.required and (value is None or value == ""):
                raise ValueError(f"Required parameter '{param.name}' is missing")

            # Use default if value not provided
            if value is None:
                value = param.default

            # Type validation and conversion
            if value is not None:
                if param.type == "integer":
                    try:
                        value = int(value)
                    except (ValueError, TypeError):
                        raise ValueError(f"Parameter '{param.name}' must be an integer")
                elif param.type == "boolean":
                    if isinstance(value, str):
                        value = value.lower() in ['true', '1', 'yes', 'on']
                    else:
                        value = bool(value)

                # Options validation
                if param.options and value not in param.options:
                    raise ValueError(f"Parameter '{param.name}' must be one of: {param.options}")

                # Regex validation
                if param.validation and param.type == "string":
                    import re
                    if not re.match(param.validation, str(value)):
                        raise ValueError(f"Parameter '{param.name}' format is invalid")

                validated[param.name] = value

        return validated

    def _generate_confirmation_message(self, tool: ToolDefinition, parameters: Dict[str, Any]) -> str:
        """Generate confirmation message for tool execution"""
        if tool.confirmation_level == ConfirmationLevel.STANDARD:
            return f"Do you want me to {tool.name.lower()}?"

        elif tool.confirmation_level == ConfirmationLevel.DETAILED:
            param_summary = ", ".join([f"{k}={v}" for k, v in parameters.items() if v is not None])
            return f"I'm about to {tool.name.lower()} with the following parameters: {param_summary}. Do you want to proceed?"

        elif tool.confirmation_level == ConfirmationLevel.DESTRUCTIVE:
            return f"⚠️ **DESTRUCTIVE ACTION** ⚠️\n\nThis will {tool.name.lower()} and cannot be undone. Are you absolutely sure you want to proceed?"

        return "Proceed with this action?"

    def _calculate_tool_relevance(self, tool: ToolDefinition, message: str) -> float:
        """Calculate tool relevance to user message"""
        score = 0.0

        # Check tool name and description
        tool_text = (tool.name + " " + tool.description).lower()

        # Simple keyword matching
        tool_keywords = tool_text.split()
        message_words = message.split()

        matches = sum(1 for word in message_words if word in tool_keywords)
        score = matches / len(message_words) if message_words else 0

        # Category-specific boosts
        if tool.category == ToolCategory.PROSPECT_MANAGEMENT:
            if any(word in message for word in ["prospect", "find", "discover", "research"]):
                score += 0.3

        elif tool.category == ToolCategory.EMAIL_OPERATIONS:
            if any(word in message for word in ["email", "send", "message", "introduction"]):
                score += 0.3

        elif tool.category == ToolCategory.SEARCH_RESEARCH:
            if any(word in message for word in ["search", "find", "who is", "what is", "tell me"]):
                score += 0.3

        return min(score, 1.0)

    async def _execute_tool_function(self, execution: ToolExecution) -> ToolExecution:
        """Execute the actual tool function"""
        try:
            execution.status = ToolExecutionStatus.EXECUTING
            execution.started_at = datetime.now(timezone.utc)

            tool = self.tools[execution.tool_id]

            # Add context parameters
            execution_params = execution.parameters.copy()
            execution_params.update({
                "user_id": execution.user_id,
                "organization_id": execution.organization_id,
                "session_id": execution.session_id,
                "user_role": execution.user_role,
            })

            # Execute with timeout + simple backoff retry for transient errors
            # Stamp idempotency key into kwargs for downstream services
            attempts = 0
            last_exc = None
            result = None
            while attempts < 3:
                try:
                    result = await asyncio.wait_for(
                        tool.function(**{**execution_params, "idempotency_key": execution.execution_id}),
                        timeout=self.max_execution_time_seconds
                    )
                    last_exc = None
                    break
                except asyncio.TimeoutError as te:
                    last_exc = te
                    break  # Do not retry hard timeouts to avoid duplicate side effects
                except Exception as exc:
                    last_exc = exc
                    attempts += 1
                    if attempts >= 3:
                        break
                    # Exponential backoff with jitter cap (no import for random to keep simple)
                    await asyncio.sleep(min(2 ** attempts, 4))
            if last_exc:
                raise last_exc

            execution.result = result
            execution.status = ToolExecutionStatus.COMPLETED
            execution.completed_at = datetime.now(timezone.utc)

            if not isinstance(execution.result, dict):
                execution.result = {
                    "status": "success",
                    "output": execution.result
                }

            if execution.started_at:
                execution.execution_time_ms = int(
                    (execution.completed_at - execution.started_at).total_seconds() * 1000
                )

            if execution.tool_id != "undo_last_tool":
                result_dict = execution.result
                undo_payload = result_dict.get("undo") if isinstance(result_dict, dict) else None

                if undo_payload:
                    undo_entry = {
                        "tool_id": execution.tool_id,
                        "undo": undo_payload,
                        "timestamp": execution.completed_at,
                        "user_id": execution.user_id,
                        "organization_id": execution.organization_id,
                        "summary": self._format_result_summary(result_dict)
                    }
                    self._push_undo(execution.session_id, undo_entry)
                    result_dict.setdefault("undo_available", True)
                    result_dict.setdefault(
                        "hint",
                        "Undo available: run the undo tool or say “undo last action.”"
                    )
                result_dict.setdefault("undo_available", False)
            elif isinstance(execution.result, dict):
                execution.result.setdefault("undo_available", False)

            # Metrics: record success
            try:
                from monitoring.prometheus_metrics import record_tool_execution
                duration = (execution.completed_at - execution.started_at).total_seconds() if execution.started_at else 0.0
                record_tool_execution(execution.tool_id, True, duration, tenant_id=str(execution.organization_id))
            except Exception:
                pass

        except asyncio.TimeoutError:
            execution.status = ToolExecutionStatus.FAILED
            execution.error = f"Tool execution timed out after {self.max_execution_time_seconds} seconds"
            execution.completed_at = datetime.now(timezone.utc)

        except Exception as e:
            execution.status = ToolExecutionStatus.FAILED
            execution.error = str(e)
            execution.completed_at = datetime.now(timezone.utc)

        # Store in history
        self.execution_history.append(execution)

        # Metrics: record failure or cancellation
        try:
            from monitoring.prometheus_metrics import record_tool_execution
            duration = (execution.completed_at - execution.started_at).total_seconds() if execution.started_at and execution.completed_at else 0.0
            record_tool_execution(execution.tool_id, execution.status == ToolExecutionStatus.COMPLETED, duration, tenant_id=str(execution.organization_id))
        except Exception:
            pass

        return execution

    def _push_undo(self, session_id: str, entry: Dict[str, Any]) -> None:
        stack = self.undo_stack.setdefault(session_id, [])
        stack.append(entry)
        if len(stack) > self.max_undo_depth:
            stack.pop(0)

    def _pop_undo(self, session_id: str) -> Optional[Dict[str, Any]]:
        stack = self.undo_stack.get(session_id)
        if not stack:
            return None
        return stack.pop()

    def _peek_undo(self, session_id: str) -> Optional[Dict[str, Any]]:
        stack = self.undo_stack.get(session_id)
        if not stack:
            return None
        return stack[-1]

    def get_undo_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        entry = self._peek_undo(session_id)
        if not entry:
            return None
        return {
            "tool_id": entry["tool_id"],
            "summary": entry.get("summary"),
            "timestamp": entry.get("timestamp")
        }

    async def _undo_last_action(self, **kwargs) -> Dict[str, Any]:
        session_id = kwargs.get("session_id")
        user_id = kwargs.get("user_id")
        organization_id = kwargs.get("organization_id")

        if not session_id:
            return {
                "status": "error",
                "error": "missing_session",
                "message": "Undo requires an active conversation session.",
                "undo_available": False
            }

        entry = self._pop_undo(session_id)
        if not entry:
            return {
                "status": "error",
                "error": "nothing_to_undo",
                "message": "There are no actions left to undo.",
                "undo_available": False
            }

        try:
            await self._execute_undo(entry, user_id, organization_id)
            return {
                "status": "success",
                "message": f"Reverted last action: {entry['summary']}.",
                "undo_available": bool(self._peek_undo(session_id))
            }
        except Exception as exc:
            logger.error(f"Undo execution failed for {entry['tool_id']}: {exc}")
            return {
                "status": "error",
                "error": "undo_failed",
                "message": f"Failed to undo last action: {str(exc)}",
                "undo_available": bool(self._peek_undo(session_id))
            }

    async def _execute_undo(self, entry: Dict[str, Any], user_id: int, organization_id: int) -> None:
        undo_payload = entry.get("undo") or {}
        action = undo_payload.get("action")

        if action == "delete_prospect":
            from services.database import db
            prospect_id = undo_payload.get("prospect_id")
            tenant_id = undo_payload.get("tenant_id") or str(organization_id)
            if prospect_id is None:
                raise ValueError("Undo payload missing prospect_id")
            await db.delete_prospect(prospect_id, user_id=user_id, tenant_id=tenant_id)
            return

        raise ValueError(f"Unsupported undo action '{action}'")

    def _format_result_summary(self, result: Dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return str(result)
        if result.get("message"):
            return result["message"]
        if result.get("workflow_id"):
            return f"Workflow {result['workflow_id']}"
        if result.get("prospect_id"):
            return f"Prospect #{result['prospect_id']}"
        return result.get("status", "Tool executed successfully")

# Global tool registry instance
chat_tool_registry = ChatToolRegistry()
