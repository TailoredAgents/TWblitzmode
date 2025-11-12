"""
Metadata Enricher - Phase 11: Metadata Preservation System

Handles rich context preservation across all Communication Hub services,
ensuring that important business context is maintained throughout the entire
workflow lifecycle from initial prospect upload to final introduction.
"""

import json
import hashlib
import logging
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone
from collections import defaultdict
import copy

logger = logging.getLogger(__name__)

class MetadataEnricher:
    """
    Handles metadata enrichment and context preservation across services

    This system ensures that rich context like prospect information, workflow state,
    agent actions, and business relationships are preserved and available for
    executive-friendly communication throughout the entire process.
    """

    def __init__(self):
        # Context storage for different scopes
        self.context_store: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self.conversation_contexts: Dict[str, Dict[str, Any]] = {}
        self.workflow_contexts: Dict[str, Dict[str, Any]] = {}
        self.agent_contexts: Dict[str, Dict[str, Any]] = {}
        self.prospect_contexts: Dict[str, Dict[str, Any]] = {}
        self.introduction_contexts: Dict[str, Dict[str, Any]] = {}

    def enrich_metadata(
        self,
        base_metadata: Optional[Dict[str, Any]],
        conversation_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        service_name: Optional[str] = None,
        prospect_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Enrich metadata with preserved context from previous interactions

        This ensures that every message contains relevant business context
        that executives need to understand what's happening.
        """
        enriched = copy.deepcopy(base_metadata or {})

        # Add conversation context (previous messages, participant history)
        if conversation_id and conversation_id in self.conversation_contexts:
            enriched.setdefault('conversation_context', {}).update(
                self.conversation_contexts[conversation_id]
            )

        # Add workflow context (stage, progress, timeline)
        if workflow_id and workflow_id in self.workflow_contexts:
            enriched.setdefault('workflow_context', {}).update(
                self.workflow_contexts[workflow_id]
            )

        # Add agent context (capabilities, recent actions, performance)
        if agent_id and agent_id in self.agent_contexts:
            enriched.setdefault('agent_context', {}).update(
                self.agent_contexts[agent_id]
            )

        # Add prospect context (company, role, previous interactions)
        if prospect_id and prospect_id in self.prospect_contexts:
            enriched.setdefault('prospect_context', {}).update(
                self.prospect_contexts[prospect_id]
            )

        # Add service-specific context (API costs, rate limits, capabilities)
        if service_name:
            service_key = f"service_{service_name}"
            if service_key in self.context_store:
                enriched.setdefault('service_context', {}).update(
                    self.context_store[service_key]
                )

        # Add standard enrichment fields for debugging and analytics
        enriched.update({
            'enrichment_timestamp': datetime.now(timezone.utc).isoformat(),
            'enrichment_source': 'metadata_enricher',
            'context_keys_preserved': list(enriched.keys()),
            'enrichment_version': '1.0'
        })

        logger.debug(f"Enriched metadata with {len(enriched)} context keys")
        return enriched

    async def enrich(
        self,
        base_metadata: Optional[Dict[str, Any]],
        organization_id: Optional[int] = None,
        user_id: Optional[int] = None,
        service_name: Optional[str] = None,
        conversation_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        prospect_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Async version of enrich_metadata for compatibility with Communication Hub services

        Args:
            base_metadata: Base metadata to enrich
            organization_id: Organization context
            user_id: User context
            service_name: Name of the calling service
            conversation_id: Conversation context
            workflow_id: Workflow context
            agent_id: Agent context
            prospect_id: Prospect context

        Returns:
            Enriched metadata with organizational and service context
        """
        enriched = self.enrich_metadata(
            base_metadata=base_metadata,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            agent_id=agent_id,
            service_name=service_name,
            prospect_id=prospect_id
        )

        # Add organizational context
        if organization_id:
            enriched['organization_id'] = organization_id
            enriched['organizational_context'] = await self._get_organizational_context(organization_id)

        # Add user context
        if user_id:
            enriched['user_id'] = user_id
            enriched['user_context'] = await self._get_user_context(user_id, organization_id)

        # Add service-specific performance metrics
        if service_name:
            enriched['service_metrics'] = await self._get_service_metrics(service_name, organization_id)

        return enriched

    async def _get_organizational_context(self, organization_id: int) -> Dict[str, Any]:
        """Get organizational context for enrichment"""
        # This would typically query the database for org settings, preferences, etc.
        # For now, return basic context
        return {
            'org_id': organization_id,
            'context_type': 'organizational',
            'enrichment_level': 'basic',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

    async def _get_user_context(self, user_id: int, organization_id: Optional[int] = None) -> Dict[str, Any]:
        """Get user-specific context for enrichment"""
        # This would typically query user preferences, role, permissions, etc.
        # For now, return basic context
        return {
            'user_id': user_id,
            'org_id': organization_id,
            'context_type': 'user',
            'enrichment_level': 'basic',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

    async def _get_service_metrics(self, service_name: str, organization_id: Optional[int] = None) -> Dict[str, Any]:
        """Get service performance metrics for enrichment"""
        # This would typically query service performance data, costs, etc.
        # For now, return basic metrics
        return {
            'service_name': service_name,
            'org_id': organization_id,
            'context_type': 'service_metrics',
            'enrichment_level': 'basic',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'metrics': {
                'requests_processed': 'not_tracked',
                'avg_response_time': 'not_tracked',
                'error_rate': 'not_tracked',
                'cost_per_request': 'not_tracked'
            }
        }

    def preserve_conversation_context(
        self,
        conversation_id: str,
        context: Dict[str, Any]
    ):
        """
        Preserve conversation-level context for future message enrichment

        Examples: participant preferences, conversation tone, previous decisions
        """
        if conversation_id not in self.conversation_contexts:
            self.conversation_contexts[conversation_id] = {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'context_version': 0
            }

        self.conversation_contexts[conversation_id].update({
            **context,
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'context_version': self.conversation_contexts[conversation_id].get('context_version', 0) + 1
        })

        logger.debug(f"Preserved conversation context for {conversation_id}")

    def preserve_workflow_context(
        self,
        workflow_id: str,
        context: Dict[str, Any]
    ):
        """
        Preserve workflow-level context across all related messages

        Examples: prospect batch info, approval requirements, timeline constraints
        """
        if workflow_id not in self.workflow_contexts:
            self.workflow_contexts[workflow_id] = {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'context_version': 0
            }

        self.workflow_contexts[workflow_id].update({
            **context,
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'context_version': self.workflow_contexts[workflow_id].get('context_version', 0) + 1
        })

        logger.debug(f"Preserved workflow context for {workflow_id}")

    def preserve_agent_context(
        self,
        agent_id: str,
        context: Dict[str, Any]
    ):
        """
        Preserve agent-specific context for consistent messaging

        Examples: agent capabilities, recent performance, cost tracking
        """
        if agent_id not in self.agent_contexts:
            self.agent_contexts[agent_id] = {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'context_version': 0
            }

        self.agent_contexts[agent_id].update({
            **context,
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'context_version': self.agent_contexts[agent_id].get('context_version', 0) + 1
        })

        logger.debug(f"Preserved agent context for {agent_id}")

    def preserve_prospect_context(
        self,
        prospect_id: str,
        context: Dict[str, Any]
    ):
        """
        Preserve prospect-specific context across all interactions

        Examples: company info, contact details, mutual connections, introduction history
        """
        if prospect_id not in self.prospect_contexts:
            self.prospect_contexts[prospect_id] = {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'context_version': 0
            }

        self.prospect_contexts[prospect_id].update({
            **context,
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'context_version': self.prospect_contexts[prospect_id].get('context_version', 0) + 1
        })

        logger.debug(f"Preserved prospect context for {prospect_id}")

    def preserve_introduction_context(
        self,
        introduction_id: str,
        context: Dict[str, Any]
    ):
        """
        Preserve introduction-specific context for follow-up tracking

        Examples: introduction email content, connector info, response tracking
        """
        if introduction_id not in self.introduction_contexts:
            self.introduction_contexts[introduction_id] = {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'context_version': 0
            }

        self.introduction_contexts[introduction_id].update({
            **context,
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'context_version': self.introduction_contexts[introduction_id].get('context_version', 0) + 1
        })

        logger.debug(f"Preserved introduction context for {introduction_id}")

    def create_context_fingerprint(self, context: Dict[str, Any]) -> str:
        """
        Create a unique fingerprint for context data to track changes

        This helps detect when context has changed significantly and
        may require executive attention or re-approval.
        """
        # Remove timestamps and version numbers for stable fingerprinting
        stable_context = {k: v for k, v in context.items()
                         if k not in ['last_updated', 'context_version', 'enrichment_timestamp']}

        context_json = json.dumps(stable_context, sort_keys=True, default=str)
        return hashlib.md5(context_json.encode()).hexdigest()

    def get_context_summary(self, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get a comprehensive summary of all preserved context

        Useful for debugging, analytics, and executive dashboards
        """
        summary = {
            'total_conversations': len(self.conversation_contexts),
            'total_workflows': len(self.workflow_contexts),
            'total_agents': len(self.agent_contexts),
            'total_prospects': len(self.prospect_contexts),
            'total_introductions': len(self.introduction_contexts),
            'context_store_keys': len(self.context_store),
            'summary_generated_at': datetime.now(timezone.utc).isoformat()
        }

        if conversation_id and conversation_id in self.conversation_contexts:
            summary['conversation_context'] = self.conversation_contexts[conversation_id]

        return summary

    def get_prospect_journey(self, prospect_id: str) -> Dict[str, Any]:
        """
        Get the complete journey of a prospect through the system

        This provides executives with a complete view of all interactions
        with a specific prospect across all workflows and agents.
        """
        journey = {
            'prospect_id': prospect_id,
            'journey_generated_at': datetime.now(timezone.utc).isoformat(),
            'interactions': [],
            'timeline': []
        }

        # Find all contexts that mention this prospect
        for conv_id, conv_context in self.conversation_contexts.items():
            if prospect_id in str(conv_context):
                journey['interactions'].append({
                    'type': 'conversation',
                    'id': conv_id,
                    'context': conv_context
                })

        for workflow_id, workflow_context in self.workflow_contexts.items():
            if prospect_id in str(workflow_context):
                journey['interactions'].append({
                    'type': 'workflow',
                    'id': workflow_id,
                    'context': workflow_context
                })

        # Get direct prospect context
        if prospect_id in self.prospect_contexts:
            journey['prospect_context'] = self.prospect_contexts[prospect_id]

        return journey

    def clear_context(
        self,
        conversation_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        prospect_id: Optional[str] = None
    ):
        """
        Clear preserved context (useful for testing or privacy compliance)
        """
        cleared = []

        if conversation_id and conversation_id in self.conversation_contexts:
            del self.conversation_contexts[conversation_id]
            cleared.append(f"conversation:{conversation_id}")

        if workflow_id and workflow_id in self.workflow_contexts:
            del self.workflow_contexts[workflow_id]
            cleared.append(f"workflow:{workflow_id}")

        if agent_id and agent_id in self.agent_contexts:
            del self.agent_contexts[agent_id]
            cleared.append(f"agent:{agent_id}")

        if prospect_id and prospect_id in self.prospect_contexts:
            del self.prospect_contexts[prospect_id]
            cleared.append(f"prospect:{prospect_id}")

        logger.info(f"Context cleared for: {', '.join(cleared)}")

    def export_context(self) -> Dict[str, Any]:
        """
        Export all preserved context for backup or analysis
        """
        return {
            'export_timestamp': datetime.now(timezone.utc).isoformat(),
            'conversation_contexts': dict(self.conversation_contexts),
            'workflow_contexts': dict(self.workflow_contexts),
            'agent_contexts': dict(self.agent_contexts),
            'prospect_contexts': dict(self.prospect_contexts),
            'introduction_contexts': dict(self.introduction_contexts),
            'context_store': dict(self.context_store)
        }

    def import_context(self, context_data: Dict[str, Any]):
        """
        Import previously exported context data
        """
        if 'conversation_contexts' in context_data:
            self.conversation_contexts.update(context_data['conversation_contexts'])
        if 'workflow_contexts' in context_data:
            self.workflow_contexts.update(context_data['workflow_contexts'])
        if 'agent_contexts' in context_data:
            self.agent_contexts.update(context_data['agent_contexts'])
        if 'prospect_contexts' in context_data:
            self.prospect_contexts.update(context_data['prospect_contexts'])
        if 'introduction_contexts' in context_data:
            self.introduction_contexts.update(context_data['introduction_contexts'])
        if 'context_store' in context_data:
            self.context_store.update(context_data['context_store'])

        logger.info("Context data imported successfully")

# Global singleton instance for system-wide context preservation
global_metadata_enricher: Optional[MetadataEnricher] = None

def get_global_enricher() -> MetadataEnricher:
    """Get or create the global metadata enricher instance"""
    global global_metadata_enricher

    if global_metadata_enricher is None:
        global_metadata_enricher = MetadataEnricher()
        logger.info("Global metadata enricher initialized")

    return global_metadata_enricher

def preserve_workflow_context(workflow_id: str, context: Dict[str, Any]):
    """Convenience function to preserve workflow context globally"""
    enricher = get_global_enricher()
    enricher.preserve_workflow_context(workflow_id, context)

def preserve_prospect_context(prospect_id: str, context: Dict[str, Any]):
    """Convenience function to preserve prospect context globally"""
    enricher = get_global_enricher()
    enricher.preserve_prospect_context(prospect_id, context)

def get_prospect_journey(prospect_id: str) -> Dict[str, Any]:
    """Convenience function to get complete prospect journey"""
    enricher = get_global_enricher()
    return enricher.get_prospect_journey(prospect_id)