"""
Chat Fallback Service for VouchLink AI
Provides HTTP polling fallback when WebSocket connections fail.
"""

import asyncio
import atexit
import json
import logging
import time
import uuid
import weakref
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """Represents a chat message in the fallback system."""
    id: str
    session_id: str
    type: str  # 'user', 'agent', 'system', 'typing', 'error'
    content: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatSession:
    """Represents a chat session with message history."""
    session_id: str
    user_id: int
    tenant_id: str
    created_at: datetime
    last_activity: datetime
    messages: List[ChatMessage] = field(default_factory=list)
    is_active: bool = True


class ChatFallbackService:
    """Service for handling HTTP fallback when WebSocket connections fail."""

    def __init__(self):
        """Initialize the chat fallback service."""
        self.sessions: Dict[str, ChatSession] = {}
        self.pending_messages: Dict[str, deque] = defaultdict(deque)
        self.session_timeout = timedelta(hours=2)
        self.max_messages_per_session = 1000
        self.cleanup_interval = 300  # 5 minutes
        self._cleanup_task = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._finalizer = weakref.finalize(self, ChatFallbackService._finalize_close, weakref.ref(self))

        # Start cleanup task when first used
        self._ensure_cleanup_task()

    async def create_session(self, user_id: int, tenant_id: str) -> str:
        """Create a new chat session for HTTP fallback."""
        self._ensure_cleanup_task()
        session_id = f"http_chat_{user_id}_{tenant_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"

        session = ChatSession(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc)
        )

        self.sessions[session_id] = session

        # Add welcome message
        welcome_message = ChatMessage(
            id=f"welcome_{session_id}",
            session_id=session_id,
            type="agent",
            content="🤖 **Welcome to VouchLink AI!** (HTTP Mode)\n\nYou're connected via HTTP fallback mode. All features are available, with automatic message polling every few seconds.\n\nWhat would you like to work on today?",
            timestamp=datetime.now(timezone.utc),
            metadata={"fallback_mode": True}
        )

        session.messages.append(welcome_message)
        self.pending_messages[session_id].append(welcome_message)

        logger.info(f"Created HTTP fallback chat session: {session_id}")
        return session_id

    async def send_user_message(self, session_id: str, content: str, message_id: Optional[str] = None) -> Dict[str, Any]:
        """Process a user message in HTTP fallback mode."""
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self.sessions[session_id]
        session.last_activity = datetime.now(timezone.utc)

        # Create user message
        user_message = ChatMessage(
            id=message_id or f"user_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            type="user",
            content=content,
            timestamp=datetime.now(timezone.utc)
        )

        session.messages.append(user_message)

        # Add typing indicator
        typing_message = ChatMessage(
            id=f"typing_{int(time.time())}",
            session_id=session_id,
            type="typing",
            content="Agent is thinking...",
            timestamp=datetime.now(timezone.utc)
        )

        self.pending_messages[session_id].append(typing_message)

        try:
            # Import here to avoid circular imports
            from services.pii_redaction_service import pii_redaction_service
            from agent import prospecting_agent
            from agents import Runner
            from context import ProspectingContext

            # Redact PII from user message
            redaction_result = pii_redaction_service.redact_chat_message(content)
            redacted_content = redaction_result["redacted_message"]

            # Log redaction if PII found
            if redaction_result["redaction_count"] > 0:
                logger.warning(
                    f"PII redacted from HTTP fallback message in session {session_id}",
                    extra={
                        "session_id": session_id,
                        "user_id": session.user_id,
                        "tenant_id": session.tenant_id,
                        "pii_types": redaction_result["pii_types_found"],
                        "redaction_count": redaction_result["redaction_count"]
                    }
                )

            # Create context for agent
            context = ProspectingContext(
                current_session_id=session_id,
                tenant_id=session.tenant_id,
                user_id=session.user_id
            )

            # Process with agent
            result = await Runner.run(
                prospecting_agent,
                redacted_content,
                context_variables={
                    "user_id": session.user_id,
                    "tenant_id": session.tenant_id,
                    "session_id": session_id
                }
            )

            # Redact agent response
            from services.pii_redaction_service import redact_chat_content
            agent_response_redacted = redact_chat_content(result.content if hasattr(result, 'content') else str(result))

            # Remove typing indicator
            self.pending_messages[session_id] = deque([
                msg for msg in self.pending_messages[session_id]
                if msg.type != "typing"
            ])

            # Create agent response
            agent_message = ChatMessage(
                id=f"agent_{int(time.time())}_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                type="agent",
                content=agent_response_redacted,
                timestamp=datetime.now(timezone.utc)
            )

            session.messages.append(agent_message)
            self.pending_messages[session_id].append(agent_message)

            return {
                "status": "success",
                "message_id": user_message.id,
                "response_id": agent_message.id
            }

        except Exception as e:
            logger.error(f"Error processing message in HTTP fallback: {e}")

            # Remove typing indicator
            self.pending_messages[session_id] = deque([
                msg for msg in self.pending_messages[session_id]
                if msg.type != "typing"
            ])

            # Create error message
            error_message = ChatMessage(
                id=f"error_{int(time.time())}",
                session_id=session_id,
                type="error",
                content="❌ I encountered an error processing your request. Please try again.",
                timestamp=datetime.now(timezone.utc)
            )

            session.messages.append(error_message)
            self.pending_messages[session_id].append(error_message)

            return {
                "status": "error",
                "error": str(e),
                "message_id": user_message.id
            }

    async def get_messages(self, session_id: str, since: Optional[str] = None) -> Dict[str, Any]:
        """Get new messages for a session since the given timestamp."""
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self.sessions[session_id]
        session.last_activity = datetime.now(timezone.utc)

        # Get pending messages
        pending = list(self.pending_messages[session_id])

        # Clear pending messages after retrieval
        self.pending_messages[session_id].clear()

        # Filter by timestamp if provided
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
                pending = [msg for msg in pending if msg.timestamp > since_dt]
            except ValueError:
                logger.warning(f"Invalid since timestamp: {since}")

        # Convert to dict format
        messages = [
            {
                "id": msg.id,
                "type": msg.type,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "metadata": msg.metadata
            }
            for msg in pending
        ]

        return {
            "session_id": session_id,
            "messages": messages,
            "has_more": len(self.pending_messages[session_id]) > 0,
            "last_activity": session.last_activity.isoformat()
        }

    async def get_session_history(self, session_id: str, limit: int = 50) -> Dict[str, Any]:
        """Get message history for a session."""
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self.sessions[session_id]

        # Get recent messages
        recent_messages = session.messages[-limit:] if limit > 0 else session.messages

        messages = [
            {
                "id": msg.id,
                "type": msg.type,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "metadata": msg.metadata
            }
            for msg in recent_messages
        ]

        return {
            "session_id": session_id,
            "user_id": session.user_id,
            "tenant_id": session.tenant_id,
            "created_at": session.created_at.isoformat(),
            "last_activity": session.last_activity.isoformat(),
            "message_count": len(session.messages),
            "messages": messages
        }

    async def end_session(self, session_id: str) -> bool:
        """End a chat session and clean up resources."""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.is_active = False

            # Keep session for a short time for potential reconnection
            # Will be cleaned up by periodic cleanup

            logger.info(f"Ended HTTP fallback chat session: {session_id}")
            return True

        return False

    def _ensure_cleanup_task(self):
        """Ensure cleanup task is running (create if not exists)."""
        try:
            if self._cleanup_task is None or self._cleanup_task.done():
                loop = asyncio.get_running_loop()
                self._loop = loop
                self._cleanup_task = loop.create_task(
                    self._periodic_cleanup(),
                    name="chat-fallback-cleanup",
                )
        except RuntimeError:
            # No event loop running, task will be created when needed
            pass

    async def _periodic_cleanup(self):
        """Periodically clean up old sessions and messages."""
        try:
            while True:
                await asyncio.sleep(self.cleanup_interval)
                try:
                    await self._cleanup_old_sessions()
                except Exception as e:  # pragma: no cover - defensive logging
                    logger.error(f"Error in periodic cleanup: {e}")
        except asyncio.CancelledError:
            logger.debug("Chat fallback cleanup task cancelled")
            raise

    async def _cleanup_old_sessions(self):
        """Clean up old sessions and limit message history."""
        cutoff_time = datetime.now(timezone.utc) - self.session_timeout
        sessions_to_remove = []

        for session_id, session in self.sessions.items():
            # Remove inactive old sessions
            if not session.is_active and session.last_activity < cutoff_time:
                sessions_to_remove.append(session_id)
                continue

            # Limit message history
            if len(session.messages) > self.max_messages_per_session:
                # Keep only the most recent messages
                session.messages = session.messages[-self.max_messages_per_session:]

        # Remove old sessions
        for session_id in sessions_to_remove:
            del self.sessions[session_id]
            if session_id in self.pending_messages:
                del self.pending_messages[session_id]

    async def close(self) -> None:
        """Shutdown the cleanup task and release resources."""
        if self._cleanup_task is None:
            return

        self._cleanup_task.cancel()
        try:
            await self._cleanup_task
        except asyncio.CancelledError:
            pass
        finally:
            self._cleanup_task = None
            if self._finalizer.alive:
                self._finalizer.detach()

    def close_sync(self, timeout: float = 5.0) -> None:
        """Best-effort synchronous shutdown helper for atexit handlers."""
        if self._cleanup_task is None:
            return

        loop = self._loop
        if loop and loop.is_running() and not loop.is_closed():
            fut = asyncio.run_coroutine_threadsafe(self.close(), loop)
            try:
                fut.result(timeout=timeout)
            except Exception:  # pragma: no cover - defensive guard for shutdown
                logger.debug("Chat fallback cleanup timed out during synchronous shutdown")
            return

        try:
            asyncio.run(self.close())
        except RuntimeError:
            # Event loop is already closed; cancel task without awaiting
            self._cleanup_task.cancel()
            self._cleanup_task = None

    @staticmethod
    def _finalize_close(service_ref: weakref.ReferenceType) -> None:
        service = service_ref()
        if service is not None:
            service._finalize_close_impl()

    def _finalize_close_impl(self) -> None:
        if not self._cleanup_task:
            return

        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(self.close()))
            return

        try:
            asyncio.run(self.close())
        except RuntimeError:
            # Event loop already closed; best effort cleanup
            pass
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("ChatFallbackService shutdown encountered an error: %s", exc)

        remaining_sessions = len(self.sessions)
        if remaining_sessions:
            logger.info(
                "Chat fallback service shutdown completed with %d session(s) remaining in cache",
                remaining_sessions,
            )

    def get_session_count(self) -> int:
        """Get the number of active sessions."""
        return len([s for s in self.sessions.values() if s.is_active])

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the fallback service."""
        active_sessions = [s for s in self.sessions.values() if s.is_active]

        return {
            "total_sessions": len(self.sessions),
            "active_sessions": len(active_sessions),
            "total_messages": sum(len(s.messages) for s in self.sessions.values()),
            "pending_messages": sum(len(q) for q in self.pending_messages.values()),
            "oldest_session": min(
                (s.created_at for s in active_sessions),
                default=datetime.now(timezone.utc)
            ).isoformat() if active_sessions else None
        }


# Global instance
chat_fallback_service = ChatFallbackService()


@atexit.register
def _shutdown_chat_fallback_service() -> None:
    """Ensure background cleanup task is stopped upon interpreter exit."""
    try:
        chat_fallback_service.close_sync()
    except Exception:  # pragma: no cover - best-effort shutdown
        logger.debug("Chat fallback service shutdown encountered an error", exc_info=True)
