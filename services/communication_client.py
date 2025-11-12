"""
Communication Hub Client Service

Provides helper functions for AI agents and orchestrators to post messages
to the Communication Hub. Messages will appear in the message thread and trigger
WebSocket notifications so that users can see agent actions in real time.

This service bridges the gap between technical AI operations and executive-friendly
communication by translating complex workflows into plain-English updates.
"""

import aiohttp
import asyncio
import logging
import json
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone
from enum import Enum
from .metadata_enricher import MetadataEnricher, get_global_enricher
from .message_translator import MessageTranslator, get_global_translator, BusinessContext
from .security_validator import SecurityValidator, get_global_security_validator, SecurityValidationError
from .performance_optimizer import PerformanceOptimizer, get_global_performance_optimizer, OptimizationLevel

logger = logging.getLogger(__name__)

class MessageType(Enum):
    """Message types for Communication Hub"""
    TEXT = "text"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESPONSE = "approval_response"
    WORKFLOW_UPDATE = "workflow_update"
    PROGRESS_UPDATE = "progress_update"
    ERROR_NOTIFICATION = "error_notification"
    SUCCESS_NOTIFICATION = "success_notification"
    COST_REPORT = "cost_report"

class MessagePriority(Enum):
    """Message priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

class CommunicationHubClient:
    """
    Client for sending messages to Communication Hub from AI services

    This client handles:
    - HTTP communication with Communication Hub API
    - Plain-English message formatting
    - Multi-tenant context management
    - Error handling and retries
    """

    def __init__(self, base_url: str = "http://localhost:8081", auth_token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.session: Optional[aiohttp.ClientSession] = None
        self.metadata_enricher = get_global_enricher()
        self.message_translator = get_global_translator()
        self.security_validator = get_global_security_validator()
        self.performance_optimizer = get_global_performance_optimizer(OptimizationLevel.ENTERPRISE)
        logger.info("Communication client initialized with all enterprise-grade optimizations: metadata enricher, message translator, security validator, and performance optimizer")

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

    async def send_message(
        self,
        conversation_id: str,
        recipient_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        priority: MessagePriority = MessagePriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
        requires_approval: bool = False,
        organization_id: Optional[int] = None,
        workflow_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        service_name: Optional[str] = None,
        prospect_id: Optional[str] = None,
        preserve_context: bool = True,
        translate_to_business_language: bool = True,
        user_id: Optional[int] = None,
        user_organization_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Send a message to the Communication Hub

        Args:
            conversation_id: ID of the conversation
            recipient_id: ID of the message recipient
            content: Plain-English message content
            message_type: Type of message (text, approval_request, etc.)
            priority: Message priority level
            metadata: Additional metadata to include
            requires_approval: Whether this message requires approval
            organization_id: Organization context
            workflow_id: Associated workflow ID

        Returns:
            Response from Communication Hub API
        """

        # Security validation: Ensure organization-scoped access
        if user_id and user_organization_id and organization_id:
            try:
                self.security_validator.validate_organization_access(
                    user_id, user_organization_id, organization_id, "send_message"
                )

                # Validate message content for security
                if not self.security_validator.validate_message_content_security(content, organization_id):
                    logger.warning(f"Message content failed security validation for org {organization_id}")

            except SecurityValidationError as e:
                logger.error(f"Security validation failed: {e}")
                return {"success": False, "error": f"Security validation failed: {str(e)}"}

        # Enrich metadata with preserved context using the global enricher
        enriched_metadata = self.metadata_enricher.enrich_metadata(
            metadata,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            agent_id=agent_id,
            service_name=service_name,
            prospect_id=prospect_id
        )

        # Security sanitization: Remove cross-organizational data
        if organization_id:
            enriched_metadata = self.security_validator.sanitize_metadata_for_organization(
                enriched_metadata, organization_id
            )

        # Preserve context if enabled for future message enrichment
        if preserve_context:
            # Update conversation context with this interaction
            conversation_context = {
                'last_message_type': message_type.value,
                'last_content_length': len(content),
                'last_priority': priority.value,
                'last_agent': agent_id,
                'last_service': service_name,
                'last_prospect': prospect_id
            }
            self.metadata_enricher.preserve_conversation_context(
                conversation_id, conversation_context
            )

            # Update workflow context if provided
            if workflow_id:
                workflow_context = {
                    'current_stage': enriched_metadata.get('stage', 'active'),
                    'last_message_time': datetime.now(timezone.utc).isoformat(),
                    'conversation_id': conversation_id
                }
                self.metadata_enricher.preserve_workflow_context(
                    workflow_id, workflow_context
                )

            # Update agent context if provided
            if agent_id:
                agent_context = {
                    'last_action': message_type.value,
                    'last_conversation': conversation_id,
                    'last_message_content_type': enriched_metadata.get('content_type', 'text')
                }
                self.metadata_enricher.preserve_agent_context(
                    agent_id, agent_context
                )

            # Update prospect context if provided
            if prospect_id:
                prospect_context = {
                    'last_interaction': datetime.now(timezone.utc).isoformat(),
                    'last_message_type': message_type.value,
                    'current_workflow': workflow_id,
                    'current_conversation': conversation_id
                }
                self.metadata_enricher.preserve_prospect_context(
                    prospect_id, prospect_context
                )

        # Translate content to business-friendly language if enabled
        translated_content = content
        if translate_to_business_language and message_type != MessageType.APPROVAL_RESPONSE:
            # Determine business context based on message type
            business_context = self._get_business_context(message_type)

            # Translate the content
            translated_content = self.message_translator.translate_message(
                content,
                business_context,
                enriched_metadata
            )

            # Store original content in metadata for reference
            enriched_metadata['original_content'] = content
            enriched_metadata['translation_applied'] = True
            enriched_metadata['business_context'] = business_context.value

        # Determine recipient type based on message context
        recipient_type = "ai" if message_type == MessageType.APPROVAL_RESPONSE else "human"

        # Create comprehensive payload with enriched metadata
        payload = {
            "conversation_id": conversation_id,
            "recipient_id": recipient_id,
            "recipient_type": recipient_type,
            "content": translated_content,
            "message_type": message_type.value,
            "priority": priority.value,
            "requires_approval": requires_approval,
            "metadata": {
                **enriched_metadata,
                "workflow_id": workflow_id,
                "organization_id": organization_id,
                "agent_id": agent_id,
                "service_name": service_name,
                "prospect_id": prospect_id,
                "sent_by": "communication_client",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "context_fingerprint": self.metadata_enricher.create_context_fingerprint(enriched_metadata)
            }
        }

        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        try:
            session = self.session or aiohttp.ClientSession()

            async with session.post(
                f"{self.base_url}/api/v1/communication-hub/messages",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:

                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Message sent to Communication Hub: {result.get('data', {}).get('id', 'unknown')}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to send message to Communication Hub: {response.status} - {error_text}")
                    return {"success": False, "error": f"HTTP {response.status}: {error_text}"}

        except Exception as e:
            logger.error(f"Exception sending message to Communication Hub: {e}")
            return {"success": False, "error": str(e)}

        finally:
            if not self.session:
                await session.close()

    async def create_conversation(
        self,
        title: str,
        participants: List[Dict[str, str]],
        organization_id: int,
        priority: MessagePriority = MessagePriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a new conversation in the Communication Hub

        Args:
            title: Conversation title
            participants: List of participants with id, type, name, role
            organization_id: Organization context
            priority: Conversation priority
            metadata: Additional metadata

        Returns:
            Response from Communication Hub API
        """

        payload = {
            "title": title,
            "participants": participants,
            "priority": priority.value,
            "organization_id": organization_id,
            "metadata": metadata or {}
        }

        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        try:
            session = self.session or aiohttp.ClientSession()

            async with session.post(
                f"{self.base_url}/api/v1/communication-hub/conversations",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:

                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Conversation created: {result.get('data', {}).get('id', 'unknown')}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create conversation: {response.status} - {error_text}")
                    return {"success": False, "error": f"HTTP {response.status}: {error_text}"}

        except Exception as e:
            logger.error(f"Exception creating conversation: {e}")
            return {"success": False, "error": str(e)}

        finally:
            if not self.session:
                await session.close()

    async def send_approval_request(
        self,
        conversation_id: str,
        recipient_id: str,
        agent_name: str,
        action_description: str,
        context: Dict[str, Any],
        priority: MessagePriority = MessagePriority.HIGH,
        workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send an approval request message

        Args:
            conversation_id: Conversation ID
            recipient_id: User who needs to approve
            agent_name: Name of the AI agent requesting approval
            action_description: Plain-English description of the action
            context: Context data for the approval
            priority: Request priority
            workflow_id: Associated workflow ID

        Returns:
            Response from Communication Hub API
        """

        content = f"{agent_name} requests approval to {action_description}"

        if context.get("prospect_name"):
            content += f" for {context['prospect_name']}"

        if context.get("company"):
            content += f" at {context['company']}"

        return await self.send_message(
            conversation_id=conversation_id,
            recipient_id=recipient_id,
            content=content,
            message_type=MessageType.APPROVAL_REQUEST,
            priority=priority,
            requires_approval=True,
            metadata={
                "agent_name": agent_name,
                "action_description": action_description,
                "approval_context": context
            },
            workflow_id=workflow_id
        )

    async def send_progress_update(
        self,
        conversation_id: str,
        recipient_id: str,
        agent_name: str,
        progress_message: str,
        metadata: Optional[Dict[str, Any]] = None,
        workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a progress update message

        Args:
            conversation_id: Conversation ID
            recipient_id: User to notify
            agent_name: Name of the AI agent
            progress_message: Plain-English progress description
            metadata: Additional context
            workflow_id: Associated workflow ID

        Returns:
            Response from Communication Hub API
        """

        content = f"{agent_name}: {progress_message}"

        return await self.send_message(
            conversation_id=conversation_id,
            recipient_id=recipient_id,
            content=content,
            message_type=MessageType.PROGRESS_UPDATE,
            priority=MessagePriority.NORMAL,
            metadata={
                "agent_name": agent_name,
                "progress_type": "update",
                **(metadata or {})
            },
            workflow_id=workflow_id
        )

    async def send_cost_report(
        self,
        conversation_id: str,
        recipient_id: str,
        service_name: str,
        cost_amount: float,
        cost_currency: str = "USD",
        cost_details: Optional[Dict[str, Any]] = None,
        workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a cost transparency report

        Args:
            conversation_id: Conversation ID
            recipient_id: User to notify
            service_name: Name of the service incurring costs
            cost_amount: Amount charged
            cost_currency: Currency (default USD)
            cost_details: Detailed cost breakdown
            workflow_id: Associated workflow ID

        Returns:
            Response from Communication Hub API
        """

        content = f"💰 Cost Alert: {service_name} incurred ${cost_amount:.2f} {cost_currency}"

        if cost_details:
            if cost_details.get("prospects_processed"):
                content += f" for {cost_details['prospects_processed']} prospects"
            if cost_details.get("cost_per_item"):
                content += f" (${cost_details['cost_per_item']:.2f} per item)"

        return await self.send_message(
            conversation_id=conversation_id,
            recipient_id=recipient_id,
            content=content,
            message_type=MessageType.COST_REPORT,
            priority=MessagePriority.NORMAL,
            metadata={
                "cost_amount": cost_amount,
                "cost_currency": cost_currency,
                "cost_details": cost_details or {},
                "service_name": service_name
            },
            workflow_id=workflow_id
        )

    async def get_context_summary(self, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get comprehensive context summary for debugging and analytics
        """
        return self.metadata_enricher.get_context_summary(conversation_id)

    async def get_prospect_journey(self, prospect_id: str) -> Dict[str, Any]:
        """
        Get the complete journey of a prospect through the system
        """
        return self.metadata_enricher.get_prospect_journey(prospect_id)

    async def clear_context(
        self,
        conversation_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        prospect_id: Optional[str] = None
    ):
        """
        Clear preserved context (useful for testing or privacy compliance)
        """
        self.metadata_enricher.clear_context(
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            agent_id=agent_id,
            prospect_id=prospect_id
        )
        logger.info(f"Context cleared via communication client")

    def _get_business_context(self, message_type: MessageType) -> BusinessContext:
        """
        Map message types to appropriate business contexts for translation
        """
        context_mapping = {
            MessageType.TEXT: BusinessContext.OPERATIONAL_UPDATE,
            MessageType.APPROVAL_REQUEST: BusinessContext.APPROVAL_REQUEST,
            MessageType.APPROVAL_RESPONSE: BusinessContext.OPERATIONAL_UPDATE,
            MessageType.WORKFLOW_UPDATE: BusinessContext.PROGRESS_REPORT,
            MessageType.PROGRESS_UPDATE: BusinessContext.PROGRESS_REPORT,
            MessageType.ERROR_NOTIFICATION: BusinessContext.ERROR_RESOLUTION,
            MessageType.SUCCESS_NOTIFICATION: BusinessContext.SUCCESS_NOTIFICATION,
            MessageType.COST_REPORT: BusinessContext.COST_TRANSPARENCY,
        }

        return context_mapping.get(message_type, BusinessContext.OPERATIONAL_UPDATE)

# Global singleton instance
communication_client: Optional[CommunicationHubClient] = None

async def get_communication_client() -> CommunicationHubClient:
    """Get or create the global communication client instance"""
    global communication_client

    if communication_client is None:
        communication_client = CommunicationHubClient()

    return communication_client

def initialize_communication_client(base_url: str = "http://localhost:8081", auth_token: Optional[str] = None):
    """Initialize the global communication client"""
    global communication_client
    communication_client = CommunicationHubClient(base_url=base_url, auth_token=auth_token)