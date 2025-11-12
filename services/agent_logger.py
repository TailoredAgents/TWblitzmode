"""
Agent Logger Service - September 2025 AI Integration
Centralized logging system for AI agents across all services
"""
import logging
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum
import uuid
from pathlib import Path
import asyncio
try:
    import aiofiles  # type: ignore
    AIOFILES_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    aiofiles = None  # type: ignore
    AIOFILES_AVAILABLE = False

# Communication Hub integration with error handling
try:
    from services.communication_client import get_communication_client, MessageType, MessagePriority

    communication_client_available = True
except ImportError:  # pragma: no cover - optional dependency
    communication_client_available = False


def _write_to_file(path: Path, content: str) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)

class LogLevel(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class AgentEventType(Enum):
    AGENT_START = "agent_start"
    AGENT_STOP = "agent_stop"
    AGENT_ERROR = "agent_error"
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"
    TASK_PROGRESS = "task_progress"
    API_CALL = "api_call"
    API_RESPONSE = "api_response"
    WORKFLOW_START = "workflow_start"
    WORKFLOW_COMPLETE = "workflow_complete"
    USER_INTERACTION = "user_interaction"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_DECISION = "approval_decision"
    COMMUNICATION = "communication"
    SYSTEM_EVENT = "system_event"
    DATA_POINT_FOUND = "data_point_found"
    AI_DECISION = "ai_decision"
    EXTERNAL_API_CALL = "external_api_call"
    COST_INCURRED = "cost_incurred"
    RECOVERY_ATTEMPT = "recovery_attempt"

# Mapping internal agent/task names to human-readable descriptions
FRIENDLY_NAMES = {
    "executive_search_agent": "Executive Search",
    "linkedin_url_finder_agent": "LinkedIn Profile Discovery",
    "mutual_connections_agent": "Mutual Connection Analysis",
    "connector_ranking_agent": "Connection Quality Ranking",
    "email_enrichment_agent": "Email Address Verification",
    "human_approval_agent": "Executive Approval Review",
    "email_sending_agent": "Introduction Email Delivery",
    "apify_scraping_agent": "Data Collection Service",
    "openai_analysis_agent": "AI Content Generation",
    "corporate_workflow_agent": "Corporate Process Integration",
    "enterprise_master_game_plan_orchestrator": "Master Game Plan Orchestrator",
    "openai_agents_orchestrator_simple": "AI Content Orchestrator",
    "corporate_workflow_integration": "Corporate Integration Service",
    # Task names
    "executive_search": "Executive Search",
    "linkedin_url_discovery": "LinkedIn Profile Discovery",
    "mutual_connections": "Mutual Connection Analysis",
    "connector_ranking": "Connection Quality Ranking",
    "email_enrichment": "Email Address Verification",
    "human_approval": "Executive Approval Review",
    "email_sending": "Introduction Email Delivery"
}

# Error translations for user-friendly error messages
ERROR_TRANSLATIONS = {
    "ConnectionTimeoutError": "Unable to connect to external service. Retrying automatically.",
    "APIRateLimitExceeded": "Service usage limit reached. Processing will resume shortly.",
    "InvalidDataFormat": "Data format issue detected. Our team has been notified.",
    "AuthenticationFailed": "Service authentication expired. Reconnecting automatically.",
    "HTTPError": "External service temporarily unavailable. Retrying automatically.",
    "ValidationError": "Data validation failed. Please check input parameters.",
    "PermissionError": "Access permission required. Please contact your administrator.",
    "ResourceNotFound": "Requested resource not found. Skipping to next item.",
    "QuotaExceeded": "Service quota exceeded. Please upgrade your plan or wait for reset."
}

class AgentLogger:
    """Centralized logging service for AI agents with executive-friendly messaging"""

    def __init__(self, log_dir: str = "./logs", enable_file_logging: bool = True):
        self.log_dir = Path(log_dir)
        self.enable_file_logging = enable_file_logging
        self.session_id = str(uuid.uuid4())

        # Ensure log directory exists
        if enable_file_logging:
            self.log_dir.mkdir(exist_ok=True)

        # Configure structured logger
        self.logger = logging.getLogger("agent_logger")
        self.logger.setLevel(logging.DEBUG)

        # Configure formatters
        self._setup_formatters()

        # Track active agents
        self.active_agents: Dict[str, Dict[str, Any]] = {}

    def _setup_formatters(self):
        """Setup logging formatters for different outputs"""
        # Console formatter
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)

        if not self.logger.handlers:
            self.logger.addHandler(console_handler)

        # File handler (if enabled)
        if self.enable_file_logging:
            file_handler = logging.FileHandler(
                self.log_dir / f"agent_logs_{datetime.now().strftime('%Y%m%d')}.log"
            )
            file_handler.setFormatter(console_formatter)
            file_handler.setLevel(logging.DEBUG)
            self.logger.addHandler(file_handler)

    def _get_friendly_name(self, identifier: str) -> str:
        """Convert internal identifiers to human-readable names"""
        return FRIENDLY_NAMES.get(identifier, identifier.replace('_', ' ').title())

    def _translate_error(self, error_message: str) -> str:
        """Translate technical errors to business-friendly messages"""
        for error_type, friendly_msg in ERROR_TRANSLATIONS.items():
            if error_type.lower() in error_message.lower():
                return friendly_msg
        return error_message

    def _format_executive_message(self, agent_id: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Format messages for executive-level clarity"""
        friendly_agent = self._get_friendly_name(agent_id)

        # If message already starts with friendly name, use as-is
        if message.startswith(friendly_agent):
            return message

        # Add context from metadata if available
        context_parts = []
        if metadata:
            if 'prospect_name' in metadata:
                context_parts.append(f"for {metadata['prospect_name']}")
            elif 'company' in metadata:
                context_parts.append(f"at {metadata['company']}")
            elif 'company_list' in metadata and len(metadata['company_list']) > 0:
                companies = metadata['company_list'][:2]
                company_text = ', '.join(companies)
                if len(metadata['company_list']) > 2:
                    company_text += f" and {len(metadata['company_list']) - 2} others"
                context_parts.append(f"across {company_text}")

        context = f" {' '.join(context_parts)}" if context_parts else ""
        return f"{friendly_agent}: {message}{context}"

    async def log_event(
        self,
        event_type: AgentEventType,
        agent_id: str,
        message: str,
        level: LogLevel = LogLevel.INFO,
        metadata: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        suggestion: Optional[str] = None
    ):
        """Log an agent event with structured metadata and executive-friendly messaging"""

        # Format message for executive clarity
        formatted_message = self._format_executive_message(agent_id, message, metadata)

        # Translate errors if this is an error event
        if event_type in [AgentEventType.AGENT_ERROR, AgentEventType.TASK_ERROR]:
            formatted_message = self._translate_error(formatted_message)

        event_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": str(uuid.uuid4()),
            "session_id": self.session_id,
            "event_type": event_type.value,
            "agent_id": agent_id,
            "friendly_agent_name": self._get_friendly_name(agent_id),
            "level": level.value,
            "message": formatted_message,
            "original_message": message,
            "suggestion": suggestion,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "workflow_id": workflow_id,
            "task_id": task_id,
            "metadata": metadata or {}
        }

        # Log to structured logger
        log_message = f"[{event_type.value.upper()}] {formatted_message}"
        if metadata and level == LogLevel.DEBUG:
            log_message += f" | Metadata: {json.dumps(metadata, default=str)}"

        getattr(self.logger, level.value)(log_message)

        # Save to structured JSON log file
        if self.enable_file_logging:
            await self._save_structured_log(event_data)

        # Update agent tracking
        await self._update_agent_tracking(agent_id, event_type, event_data)

        # Send suggestion to Communication Hub if available and suggestion provided
        if suggestion and communication_client_available and tenant_id and user_id:
            try:
                client = await get_communication_client()
                friendly_agent = self._get_friendly_name(agent_id)

                # Create conversation ID based on workflow or tenant
                conversation_id = f"workflow_{workflow_id}" if workflow_id else f"suggestions_{tenant_id}"

                await client.send_message(
                    conversation_id=conversation_id,
                    recipient_id=str(user_id),
                    content=f"💡 {friendly_agent} Suggestion: {suggestion}",
                    message_type=MessageType.WORKFLOW_UPDATE,
                    priority=MessagePriority.NORMAL,
                    metadata={
                        "suggestion_type": "agent_recommendation",
                        "agent_id": agent_id,
                        "friendly_agent_name": friendly_agent,
                        "original_event": event_type.value,
                        "event_context": metadata or {}
                    },
                    workflow_id=workflow_id,
                    organization_id=int(tenant_id) if tenant_id.isdigit() else None
                )

                self.logger.debug(f"Sent suggestion to Communication Hub: {suggestion}")

            except Exception as e:
                self.logger.warning(f"Failed to send suggestion to Communication Hub: {e}")

    async def _save_structured_log(self, event_data: Dict[str, Any]):
        """Save event to structured JSON log file"""
        try:
            log_file = self.log_dir / f"agent_events_{datetime.now().strftime('%Y%m%d')}.jsonl"
            line = json.dumps(event_data, default=str) + "\n"

            if AIOFILES_AVAILABLE and aiofiles is not None:
                async with aiofiles.open(log_file, "a") as handle:  # type: ignore[call-arg]
                    await handle.write(line)
            else:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:  # pragma: no cover - fallback for legacy event loop APIs
                    loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _write_to_file, log_file, line)

        except Exception as exc:
            self.logger.error(f"Failed to save structured log: {exc}")

    async def _update_agent_tracking(self, agent_id: str, event_type: AgentEventType, event_data: Dict[str, Any]):
        """Update agent tracking information"""
        if agent_id not in self.active_agents:
            self.active_agents[agent_id] = {
                "agent_id": agent_id,
                "start_time": datetime.now(timezone.utc),
                "last_activity": datetime.now(timezone.utc),
                "events_count": 0,
                "status": "unknown",
                "current_task": None,
                "error_count": 0
            }

        agent_info = self.active_agents[agent_id]
        agent_info["last_activity"] = datetime.now(timezone.utc)
        agent_info["events_count"] += 1

        # Update status based on event type
        if event_type == AgentEventType.AGENT_START:
            agent_info["status"] = "active"
        elif event_type == AgentEventType.AGENT_STOP:
            agent_info["status"] = "stopped"
        elif event_type in [AgentEventType.AGENT_ERROR, AgentEventType.TASK_ERROR]:
            agent_info["status"] = "error"
            agent_info["error_count"] += 1
        elif event_type == AgentEventType.TASK_START:
            agent_info["status"] = "busy"
            agent_info["current_task"] = event_data.get("task_id")
        elif event_type == AgentEventType.TASK_COMPLETE:
            agent_info["status"] = "idle"
            agent_info["current_task"] = None

    async def log_stage_progress(self, agent_id: str, stage_name: str, progress_percent: float, current_action: str, tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Log real-time stage progress with percentage completion"""
        friendly_stage = self._get_friendly_name(stage_name)
        await self.log_event(
            AgentEventType.TASK_PROGRESS,
            agent_id,
            f"{current_action} ({progress_percent:.1f}% complete)",
            LogLevel.INFO,
            {
                "stage_name": stage_name,
                "friendly_stage": friendly_stage,
                "progress_percent": progress_percent,
                "current_action": current_action,
                **(metadata or {})
            },
            tenant_id=tenant_id,
            workflow_id=workflow_id
        )

    async def log_data_point_found(self, agent_id: str, data_type: str, prospect_name: str, source: str, tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Log discovery of specific data points with business context"""
        await self.log_event(
            AgentEventType.DATA_POINT_FOUND,
            agent_id,
            f"Found {data_type} for {prospect_name} via {source}",
            LogLevel.INFO,
            {
                "data_type": data_type,
                "prospect_name": prospect_name,
                "source": source,
                **(metadata or {})
            },
            tenant_id=tenant_id,
            workflow_id=workflow_id
        )

    async def log_ai_decision(self, agent_id: str, decision_type: str, reasoning: str, confidence: float, tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Log AI decision-making with reasoning and confidence scores"""
        await self.log_event(
            AgentEventType.AI_DECISION,
            agent_id,
            f"AI Decision ({confidence:.0f}% confidence): {reasoning}",
            LogLevel.INFO,
            {
                "decision_type": decision_type,
                "reasoning": reasoning,
                "confidence": confidence,
                **(metadata or {})
            },
            tenant_id=tenant_id,
            workflow_id=workflow_id
        )

    async def log_external_api_call(self, agent_id: str, service_name: str, request_type: str, response_summary: str, tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Log external service interactions with business context"""
        await self.log_event(
            AgentEventType.EXTERNAL_API_CALL,
            agent_id,
            f"{service_name} {request_type}: {response_summary}",
            LogLevel.INFO,
            {
                "service_name": service_name,
                "request_type": request_type,
                "response_summary": response_summary,
                **(metadata or {})
            },
            tenant_id=tenant_id,
            workflow_id=workflow_id
        )

    async def log_cost_incurred(self, agent_id: str, service: str, cost_amount: float, currency: str = "USD", tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Log cost incurred for service usage with business impact"""
        await self.log_event(
            AgentEventType.COST_INCURRED,
            agent_id,
            f"Service cost: {currency} {cost_amount:.4f} for {service}",
            LogLevel.INFO,
            {
                "service": service,
                "cost_amount": cost_amount,
                "currency": currency,
                **(metadata or {})
            },
            tenant_id=tenant_id,
            workflow_id=workflow_id
        )

    async def log_recovery_attempt(self, agent_id: str, error_type: str, attempt_number: int, max_attempts: int, recovery_action: str, tenant_id: Optional[str] = None, workflow_id: Optional[str] = None):
        """Log recovery attempts with clear business context"""
        await self.log_event(
            AgentEventType.RECOVERY_ATTEMPT,
            agent_id,
            f"Recovering from {error_type}: {recovery_action} (attempt {attempt_number}/{max_attempts})",
            LogLevel.WARNING,
            {
                "error_type": error_type,
                "attempt_number": attempt_number,
                "max_attempts": max_attempts,
                "recovery_action": recovery_action
            },
            tenant_id=tenant_id,
            workflow_id=workflow_id
        )

    async def log_agent_start(self, agent_id: str, agent_type: str, config: Dict[str, Any], tenant_id: Optional[str] = None, suggestion: Optional[str] = None):
        """Log agent startup with friendly naming"""
        friendly_name = self._get_friendly_name(agent_id)
        await self.log_event(
            AgentEventType.AGENT_START,
            agent_id,
            f"Starting {friendly_name} service",
            LogLevel.INFO,
            {"agent_type": agent_type, "config": config},
            tenant_id=tenant_id,
            suggestion=suggestion
        )

    async def log_agent_stop(self, agent_id: str, reason: str = "normal", tenant_id: Optional[str] = None, suggestion: Optional[str] = None):
        """Log agent shutdown"""
        await self.log_event(
            AgentEventType.AGENT_STOP,
            agent_id,
            f"Agent stopped: {reason}",
            LogLevel.INFO,
            {"reason": reason},
            tenant_id=tenant_id,
            suggestion=suggestion
        )

    async def log_task_start(self, agent_id: str, task_id: str, task_type: str, task_data: Dict[str, Any], tenant_id: Optional[str] = None, suggestion: Optional[str] = None, workflow_id: Optional[str] = None):
        """Log task initiation with executive-friendly messaging"""
        friendly_task = self._get_friendly_name(task_type)

        # Create descriptive message based on task data
        context_message = ""
        if 'prospect_name' in task_data:
            context_message = f" for {task_data['prospect_name']}"
        elif 'company_list' in task_data and len(task_data['company_list']) > 0:
            companies = task_data['company_list'][:2]
            company_text = ', '.join(companies)
            if len(task_data['company_list']) > 2:
                company_text += f" and {len(task_data['company_list']) - 2} others"
            context_message = f" across {company_text}"
        elif 'company' in task_data:
            context_message = f" at {task_data['company']}"

        await self.log_event(
            AgentEventType.TASK_START,
            agent_id,
            f"Starting {friendly_task}{context_message}",
            LogLevel.INFO,
            {"task_type": task_type, "friendly_task": friendly_task, "task_data": task_data},
            tenant_id=tenant_id,
            task_id=task_id,
            workflow_id=workflow_id,
            suggestion=suggestion
        )

    async def log_task_complete(self, agent_id: str, task_id: str, result: Dict[str, Any], duration_ms: float, tenant_id: Optional[str] = None, suggestion: Optional[str] = None, workflow_id: Optional[str] = None, task_type: Optional[str] = None):
        """Log task completion with business impact summary"""
        friendly_task = self._get_friendly_name(task_type) if task_type else "Task"

        # Create descriptive completion message based on results
        completion_summary = ""
        if 'executives_found' in result:
            completion_summary = f" - found {result['executives_found']} executives"
        elif 'linkedin_urls_found' in result:
            completion_summary = f" - discovered {result['linkedin_urls_found']} LinkedIn profiles"
        elif 'connections_found' in result:
            completion_summary = f" - identified {result['connections_found']} mutual connections"
        elif 'emails_verified' in result:
            completion_summary = f" - verified {result['emails_verified']} email addresses"
        elif 'count' in result:
            completion_summary = f" - processed {result['count']} items"

        time_desc = f"in {duration_ms/1000:.1f}s" if duration_ms >= 1000 else f"in {duration_ms:.0f}ms"

        await self.log_event(
            AgentEventType.TASK_COMPLETE,
            agent_id,
            f"Completed {friendly_task} {time_desc}{completion_summary}",
            LogLevel.INFO,
            {"result": result, "duration_ms": duration_ms, "friendly_task": friendly_task},
            tenant_id=tenant_id,
            task_id=task_id,
            workflow_id=workflow_id,
            suggestion=suggestion
        )

    async def log_task_error(self, agent_id: str, task_id: str, error: str, stack_trace: Optional[str] = None, tenant_id: Optional[str] = None, suggestion: Optional[str] = None):
        """Log task error"""
        await self.log_event(
            AgentEventType.TASK_ERROR,
            agent_id,
            f"Task failed: {error}",
            LogLevel.ERROR,
            {"error": error, "stack_trace": stack_trace},
            tenant_id=tenant_id,
            task_id=task_id,
            suggestion=suggestion
        )

    async def log_api_call(self, agent_id: str, endpoint: str, method: str, params: Dict[str, Any], tenant_id: Optional[str] = None):
        """Log API call"""
        await self.log_event(
            AgentEventType.API_CALL,
            agent_id,
            f"API call: {method} {endpoint}",
            LogLevel.DEBUG,
            {"endpoint": endpoint, "method": method, "params": params},
            tenant_id=tenant_id
        )

    async def log_api_response(self, agent_id: str, endpoint: str, status_code: int, response_time_ms: float, tenant_id: Optional[str] = None):
        """Log API response"""
        await self.log_event(
            AgentEventType.API_RESPONSE,
            agent_id,
            f"API response: {status_code} in {response_time_ms:.2f}ms",
            LogLevel.DEBUG,
            {"endpoint": endpoint, "status_code": status_code, "response_time_ms": response_time_ms},
            tenant_id=tenant_id
        )

    async def log_workflow_start(self, agent_id: str, workflow_id: str, workflow_type: str, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
        """Log workflow initiation"""
        await self.log_event(
            AgentEventType.WORKFLOW_START,
            agent_id,
            f"Workflow started: {workflow_type}",
            LogLevel.INFO,
            {"workflow_type": workflow_type},
            tenant_id=tenant_id,
            user_id=user_id,
            workflow_id=workflow_id
        )

    async def log_workflow_complete(self, agent_id: str, workflow_id: str, result: Dict[str, Any], duration_ms: float, tenant_id: Optional[str] = None):
        """Log workflow completion"""
        await self.log_event(
            AgentEventType.WORKFLOW_COMPLETE,
            agent_id,
            f"Workflow completed in {duration_ms:.2f}ms",
            LogLevel.INFO,
            {"result": result, "duration_ms": duration_ms},
            tenant_id=tenant_id,
            workflow_id=workflow_id
        )

    async def log_user_interaction(self, agent_id: str, interaction_type: str, user_input: str, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
        """Log user interaction"""
        await self.log_event(
            AgentEventType.USER_INTERACTION,
            agent_id,
            f"User interaction: {interaction_type}",
            LogLevel.INFO,
            {"interaction_type": interaction_type, "user_input": user_input},
            tenant_id=tenant_id,
            user_id=user_id
        )

    async def log_approval_request(self, agent_id: str, approval_id: str, request_type: str, details: Dict[str, Any], tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, user_id: Optional[str] = None):
        """Log approval request with business context"""
        # Create executive-friendly approval request message
        context_message = ""
        if 'prospect_name' in details and 'company' in details:
            context_message = f" for introduction to {details['prospect_name']} at {details['company']}"
        elif 'prospect_name' in details:
            context_message = f" for {details['prospect_name']}"
        elif 'email_addresses' in details:
            email_count = len(details['email_addresses']) if isinstance(details['email_addresses'], list) else 1
            context_message = f" for {email_count} email{'s' if email_count > 1 else ''}"

        await self.log_event(
            AgentEventType.APPROVAL_REQUEST,
            agent_id,
            f"Approval requested for {request_type.replace('_', ' ')}{context_message}",
            LogLevel.INFO,
            {"approval_id": approval_id, "request_type": request_type, "details": details},
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            user_id=user_id
        )

    async def log_approval_decision(self, agent_id: str, approval_id: str, decision: str, feedback: Optional[str] = None, tenant_id: Optional[str] = None, user_id: Optional[str] = None, workflow_id: Optional[str] = None, impact: Optional[str] = None, approver_id: Optional[str] = None, reason: Optional[str] = None):
        """Log approval decision with business impact"""
        # Create executive-friendly decision message
        decision_text = decision.capitalize()
        impact_text = f" - {impact}" if impact else ""
        reason_text = f" (Reason: {reason})" if reason else ""
        feedback_text = f" with feedback: {feedback}" if feedback else ""

        await self.log_event(
            AgentEventType.APPROVAL_DECISION,
            agent_id,
            f"Request {decision_text}: {approval_id}{impact_text}{reason_text}{feedback_text}",
            LogLevel.INFO,
            {
                "approval_id": approval_id,
                "decision": decision,
                "feedback": feedback,
                "impact": impact,
                "approver_id": approver_id,
                "reason": reason
            },
            tenant_id=tenant_id,
            user_id=user_id,
            workflow_id=workflow_id
        )

    async def log_communication(self, agent_id: str, message_type: str, content: str, recipient: Optional[str] = None, tenant_id: Optional[str] = None):
        """Log agent communication"""
        await self.log_event(
            AgentEventType.COMMUNICATION,
            agent_id,
            f"Communication: {message_type}",
            LogLevel.INFO,
            {"message_type": message_type, "content": content, "recipient": recipient},
            tenant_id=tenant_id
        )

    def get_agent_summary(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get summary of agent activity"""
        return self.active_agents.get(agent_id)

    def get_all_agents_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all active agents"""
        return list(self.active_agents.values())

    async def get_recent_events(self, agent_id: Optional[str] = None, limit: int = 100, event_type: Optional[AgentEventType] = None) -> List[Dict[str, Any]]:
        """Get recent events from structured logs"""
        events = []
        if not self.enable_file_logging:
            return events

        try:
            log_file = self.log_dir / f"agent_events_{datetime.now().strftime('%Y%m%d')}.jsonl"
            if not log_file.exists():
                return events

            async with aiofiles.open(log_file, 'r') as f:
                lines = await f.readlines()

            # Parse and filter events
            for line in reversed(lines[-limit*2:]):  # Get more lines to account for filtering
                try:
                    event = json.loads(line.strip())

                    # Apply filters
                    if agent_id and event.get("agent_id") != agent_id:
                        continue
                    if event_type and event.get("event_type") != event_type.value:
                        continue

                    events.append(event)
                    if len(events) >= limit:
                        break
                except json.JSONDecodeError:
                    continue

        except Exception as e:
            self.logger.error(f"Failed to read recent events: {e}")

        return events

# Global agent logger instance
agent_logger = AgentLogger()

# Convenience functions for easy import
async def log_agent_start(agent_id: str, agent_type: str, config: Dict[str, Any], tenant_id: Optional[str] = None, suggestion: Optional[str] = None):
    await agent_logger.log_agent_start(agent_id, agent_type, config, tenant_id, suggestion)

async def log_agent_stop(agent_id: str, reason: str = "normal", tenant_id: Optional[str] = None, suggestion: Optional[str] = None):
    await agent_logger.log_agent_stop(agent_id, reason, tenant_id, suggestion)

async def log_task_start(agent_id: str, task_id: str, task_type: str, task_data: Dict[str, Any], tenant_id: Optional[str] = None, suggestion: Optional[str] = None):
    await agent_logger.log_task_start(agent_id, task_id, task_type, task_data, tenant_id, suggestion)

async def log_task_complete(agent_id: str, task_id: str, result: Dict[str, Any], duration_ms: float, tenant_id: Optional[str] = None, suggestion: Optional[str] = None):
    await agent_logger.log_task_complete(agent_id, task_id, result, duration_ms, tenant_id, suggestion)

async def log_task_error(agent_id: str, task_id: str, error: str, stack_trace: Optional[str] = None, tenant_id: Optional[str] = None, suggestion: Optional[str] = None):
    await agent_logger.log_task_error(agent_id, task_id, error, stack_trace, tenant_id, suggestion)

async def log_workflow_start(agent_id: str, workflow_id: str, workflow_type: str, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
    await agent_logger.log_workflow_start(agent_id, workflow_id, workflow_type, tenant_id, user_id)

async def log_workflow_complete(agent_id: str, workflow_id: str, result: Dict[str, Any], duration_ms: float, tenant_id: Optional[str] = None):
    await agent_logger.log_workflow_complete(agent_id, workflow_id, result, duration_ms, tenant_id)

async def log_approval_request(agent_id: str, approval_id: str, request_type: str, details: Dict[str, Any], tenant_id: Optional[str] = None):
    await agent_logger.log_approval_request(agent_id, approval_id, request_type, details, tenant_id)

async def log_approval_decision(agent_id: str, approval_id: str, decision: str, feedback: Optional[str] = None, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
    await agent_logger.log_approval_decision(agent_id, approval_id, decision, feedback, tenant_id, user_id)

async def log_communication(agent_id: str, message_type: str, content: str, recipient: Optional[str] = None, tenant_id: Optional[str] = None):
    await agent_logger.log_communication(agent_id, message_type, content, recipient, tenant_id)

# New enhanced logging convenience functions
async def log_stage_progress(agent_id: str, stage_name: str, progress_percent: float, current_action: str, tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
    await agent_logger.log_stage_progress(agent_id, stage_name, progress_percent, current_action, tenant_id, workflow_id, metadata)

async def log_data_point_found(agent_id: str, data_type: str, prospect_name: str, source: str, tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
    await agent_logger.log_data_point_found(agent_id, data_type, prospect_name, source, tenant_id, workflow_id, metadata)

async def log_ai_decision(agent_id: str, decision_type: str, reasoning: str, confidence: float, tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
    await agent_logger.log_ai_decision(agent_id, decision_type, reasoning, confidence, tenant_id, workflow_id, metadata)

async def log_external_api_call(agent_id: str, service_name: str, request_type: str, response_summary: str, tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
    await agent_logger.log_external_api_call(agent_id, service_name, request_type, response_summary, tenant_id, workflow_id, metadata)

async def log_cost_incurred(agent_id: str, service: str, cost_amount: float, currency: str = "USD", tenant_id: Optional[str] = None, workflow_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
    await agent_logger.log_cost_incurred(agent_id, service, cost_amount, currency, tenant_id, workflow_id, metadata)

async def log_recovery_attempt(agent_id: str, error_type: str, attempt_number: int, max_attempts: int, recovery_action: str, tenant_id: Optional[str] = None, workflow_id: Optional[str] = None):
    await agent_logger.log_recovery_attempt(agent_id, error_type, attempt_number, max_attempts, recovery_action, tenant_id, workflow_id)
