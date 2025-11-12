"""
Message Translator - Phase 12: Plain-English Translation Layer

Converts technical AI agent language into executive-friendly, business-focused
communication that provides clear value and actionable insights without
requiring technical knowledge to understand.
"""

import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

class BusinessContext(Enum):
    """Business contexts for tailored messaging"""
    EXECUTIVE_SUMMARY = "executive_summary"
    OPERATIONAL_UPDATE = "operational_update"
    COST_TRANSPARENCY = "cost_transparency"
    APPROVAL_REQUEST = "approval_request"
    PROGRESS_REPORT = "progress_report"
    SUCCESS_NOTIFICATION = "success_notification"
    ERROR_RESOLUTION = "error_resolution"
    # New contexts for distributed systems
    ENTERPRISE_WORKFLOW = "enterprise_workflow"
    CORPORATE_WORKFLOW = "corporate_workflow"
    AI_COORDINATION = "ai_coordination"
    MESH_NETWORK_UPDATE = "mesh_network_update"
    ORCHESTRATOR_STATUS = "orchestrator_status"
    DISTRIBUTED_PROCESSING = "distributed_processing"

class MessageTranslator:
    """
    Translates technical AI agent messages into executive-friendly language

    This ensures that executives receive clear, actionable insights without
    needing to understand technical implementation details.
    """

    def __init__(self):
        self.technical_patterns = self._load_technical_patterns()
        self.business_glossary = self._load_business_glossary()
        self.context_templates = self._load_context_templates()

    def _load_technical_patterns(self) -> Dict[str, str]:
        """
        Load patterns for converting technical language to business language
        """
        return {
            # API and Service Terms
            r'API call(?:s)?': 'system request',
            r'HTTP (\d+)': r'system response \1',
            r'endpoint': 'service connection',
            r'timeout': 'system delay',
            r'rate limit': 'usage limit',
            r'webhook': 'automatic notification',
            r'payload': 'data package',

            # Database and Storage Terms
            r'database query': 'data lookup',
            r'record(?:s)?': 'entry/entries',
            r'table': 'data collection',
            r'schema': 'data structure',
            r'migration': 'data update',
            r'index': 'search optimization',

            # Processing Terms
            r'thread': 'processing task',
            r'queue': 'task list',
            r'batch processing': 'bulk operation',
            r'async(?:hronous)?': 'background',
            r'pipeline': 'workflow',
            r'orchestration': 'coordination',

            # Error and Status Terms
            r'exception': 'error',
            r'stack trace': 'error details',
            r'debug(?:ging)?': 'troubleshooting',
            r'log(?:s|ging)?': 'activity record',
            r'monitoring': 'system tracking',
            r'health check': 'system status check',

            # AI and ML Terms
            r'machine learning': 'intelligent analysis',
            r'algorithm': 'automated process',
            r'model': 'AI system',
            r'inference': 'prediction',
            r'training': 'learning process',
            r'neural network': 'AI decision system',

            # LinkedIn and Networking Terms
            r'scraping': 'data collection',
            r'profile parsing': 'contact analysis',
            r'connection discovery': 'relationship mapping',
            r'mutual connections': 'shared contacts',
            r'LinkedIn API': 'LinkedIn integration',

            # Email and Communication Terms
            r'SMTP': 'email system',
            r'template rendering': 'message creation',
            r'personalization': 'customization',
            r'A/B testing': 'message optimization',
            r'open rate': 'email engagement',
            r'click-through': 'link engagement',

            # Business Process Terms
            r'workflow automation': 'automated process',
            r'task orchestration': 'task coordination',
            r'approval workflow': 'approval process',
            r'business logic': 'process rules',
            r'integration': 'system connection',

            # Distributed Systems Terms
            r'microservice(?:s)?': 'specialized system component',
            r'load balancer': 'traffic distributor',
            r'circuit breaker': 'system protection',
            r'service mesh': 'service network',
            r'distributed system': 'networked services',
            r'service discovery': 'service locator',
            r'fault tolerance': 'error resilience',
            r'horizontal scaling': 'capacity expansion',
            r'vertical scaling': 'performance boost',
            r'container(?:s)?': 'application package',
            r'kubernetes': 'application orchestrator',
            r'docker': 'application container',

            # Enterprise Workflow Terms
            r'enterprise orchestrator': 'business process manager',
            r'master game plan': 'comprehensive business strategy',
            r'workflow persistence': 'process state management',
            r'bulk operations': 'batch processing',
            r'parallel processing': 'simultaneous task execution',
            r'workflow coordination': 'process synchronization',
            r'enterprise resilience': 'business continuity',
            r'process recovery': 'workflow restoration',
            r'checkpoint(?:s)?': 'progress milestone',
            r'heartbeat': 'status ping',

            # AI and Mesh Network Terms
            r'AI agent(?:s)?': 'intelligent assistant',
            r'mesh network': 'interconnected system',
            r'agent coordination': 'assistant collaboration',
            r'multi-agent system': 'coordinated AI team',
            r'agent registration': 'assistant enrollment',
            r'agent discovery': 'assistant detection',
            r'message routing': 'communication direction',
            r'event propagation': 'information distribution',
            r'state synchronization': 'information alignment',
            r'consensus protocol': 'agreement process',

            # Communication and Messaging Terms
            r'publish-subscribe': 'broadcast system',
            r'message queue': 'task queue',
            r'event streaming': 'real-time updates',
            r'websocket(?:s)?': 'live connection',
            r'real-time communication': 'instant messaging',
            r'notification system': 'alert service',
            r'communication hub': 'central messenger',
            r'message translator': 'language converter',
            r'metadata enricher': 'context enhancer',

            # Performance and Monitoring Terms
            r'latency': 'response delay',
            r'throughput': 'processing capacity',
            r'bottleneck': 'performance constraint',
            r'scalability': 'growth capacity',
            r'performance metrics': 'efficiency measurements',
            r'system monitoring': 'health tracking',
            r'observability': 'system visibility',
            r'telemetry': 'system reporting',
            r'dashboard': 'status display',
        }

    def _load_business_glossary(self) -> Dict[str, Dict[str, str]]:
        """
        Load business-friendly definitions and context
        """
        return {
            'prospect': {
                'definition': 'potential business contact',
                'context': 'someone who could provide valuable introductions or business opportunities'
            },
            'connector': {
                'definition': 'mutual business contact',
                'context': 'someone who can facilitate introductions between you and prospects'
            },
            'introduction': {
                'definition': 'business introduction',
                'context': 'facilitated connection to expand your professional network'
            },
            'workflow': {
                'definition': 'automated business process',
                'context': 'step-by-step process that handles tasks without manual intervention'
            },
            'agent': {
                'definition': 'AI assistant',
                'context': 'intelligent system that handles specific business tasks automatically'
            },
            'orchestrator': {
                'definition': 'process coordinator',
                'context': 'system that manages and coordinates multiple business tasks'
            },
            'metadata': {
                'definition': 'additional information',
                'context': 'background details that provide context for better decision-making'
            },
            'API cost': {
                'definition': 'service usage fee',
                'context': 'charge for using external business services and data'
            },
            # Distributed Systems Terms
            'microservice': {
                'definition': 'specialized business function',
                'context': 'independent system component handling specific business tasks'
            },
            'load balancer': {
                'definition': 'workload distributor',
                'context': 'system that distributes work evenly across multiple components'
            },
            'circuit breaker': {
                'definition': 'automatic safety switch',
                'context': 'protection mechanism that prevents system overload'
            },
            'mesh network': {
                'definition': 'interconnected system network',
                'context': 'network where all components can communicate with each other'
            },
            'enterprise orchestrator': {
                'definition': 'business process coordinator',
                'context': 'system that manages complex multi-step business workflows'
            },
            'workflow persistence': {
                'definition': 'process state preservation',
                'context': 'ability to save and restore business process progress'
            },
            'AI coordination': {
                'definition': 'intelligent system collaboration',
                'context': 'multiple AI assistants working together on business tasks'
            },
            'message queue': {
                'definition': 'task waiting list',
                'context': 'organized list of business tasks waiting to be processed'
            },
            'communication hub': {
                'definition': 'central communication center',
                'context': 'system that routes all messages and notifications across the platform'
            },
            'distributed processing': {
                'definition': 'parallel task execution',
                'context': 'handling multiple business tasks simultaneously across different systems'
            },
            'fault tolerance': {
                'definition': 'error resilience',
                'context': 'ability to continue operating when problems occur'
            },
            'horizontal scaling': {
                'definition': 'capacity expansion',
                'context': 'adding more systems to handle increased business volume'
            },
            'service discovery': {
                'definition': 'system locator',
                'context': 'automatic way for systems to find and connect to each other'
            },
            'consensus protocol': {
                'definition': 'agreement mechanism',
                'context': 'way for multiple systems to agree on business decisions'
            },
            'event streaming': {
                'definition': 'real-time data flow',
                'context': 'continuous stream of business updates and notifications'
            },
            'observability': {
                'definition': 'system transparency',
                'context': 'ability to see what is happening inside business systems'
            }
        }

    def _load_context_templates(self) -> Dict[BusinessContext, Dict[str, str]]:
        """
        Load templates for different business contexts
        """
        return {
            BusinessContext.EXECUTIVE_SUMMARY: {
                'intro': '📊 Executive Summary:',
                'format': 'Brief, high-level overview with key metrics and outcomes',
                'tone': 'Strategic and results-focused'
            },
            BusinessContext.OPERATIONAL_UPDATE: {
                'intro': '⚙️ Process Update:',
                'format': 'Current status with next steps and timeline',
                'tone': 'Clear and action-oriented'
            },
            BusinessContext.COST_TRANSPARENCY: {
                'intro': '💰 Cost Report:',
                'format': 'Clear breakdown of charges with business value explanation',
                'tone': 'Transparent and value-focused'
            },
            BusinessContext.APPROVAL_REQUEST: {
                'intro': '✋ Approval Needed:',
                'format': 'Clear action request with context and implications',
                'tone': 'Respectful and urgent'
            },
            BusinessContext.PROGRESS_REPORT: {
                'intro': '📈 Progress Update:',
                'format': 'Milestone achievements with forward-looking timeline',
                'tone': 'Positive and momentum-building'
            },
            BusinessContext.SUCCESS_NOTIFICATION: {
                'intro': '✅ Success:',
                'format': 'Achievement announcement with impact and next steps',
                'tone': 'Celebratory and forward-looking'
            },
            BusinessContext.ERROR_RESOLUTION: {
                'intro': '🔧 Issue Resolution:',
                'format': 'Problem explanation with solution and prevention measures',
                'tone': 'Honest and solution-focused'
            },
            BusinessContext.ENTERPRISE_WORKFLOW: {
                'intro': '🏢 Enterprise Process:',
                'format': 'Comprehensive workflow status with business impact',
                'tone': 'Professional and strategic'
            },
            BusinessContext.CORPORATE_WORKFLOW: {
                'intro': '🔄 Corporate Workflow:',
                'format': 'Multi-stage business process with clear progression',
                'tone': 'Business-focused and systematic'
            },
            BusinessContext.AI_COORDINATION: {
                'intro': '🤖 AI Team Update:',
                'format': 'Intelligent system collaboration with coordination status',
                'tone': 'Technical but accessible'
            },
            BusinessContext.MESH_NETWORK_UPDATE: {
                'intro': '🌐 Network Status:',
                'format': 'System connectivity and communication health',
                'tone': 'Infrastructure-focused but business-relevant'
            },
            BusinessContext.ORCHESTRATOR_STATUS: {
                'intro': '🎯 Process Manager:',
                'format': 'Coordination system status with workflow oversight',
                'tone': 'Control-focused and authoritative'
            },
            BusinessContext.DISTRIBUTED_PROCESSING: {
                'intro': '⚡ Parallel Processing:',
                'format': 'Multi-system task execution with efficiency metrics',
                'tone': 'Performance-focused and results-oriented'
            }
        }

    def translate_message(
        self,
        technical_content: str,
        context: BusinessContext = BusinessContext.OPERATIONAL_UPDATE,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Translate technical message into executive-friendly language

        Args:
            technical_content: Original technical message
            context: Business context for appropriate tone and format
            metadata: Additional context for enriched translation

        Returns:
            Executive-friendly translated message
        """
        # Start with the original content
        translated = technical_content

        # Apply technical pattern replacements
        for pattern, replacement in self.technical_patterns.items():
            translated = re.sub(pattern, replacement, translated, flags=re.IGNORECASE)

        # Add business context and formatting
        template = self.context_templates.get(context, self.context_templates[BusinessContext.OPERATIONAL_UPDATE])

        # Structure the message based on context
        if context == BusinessContext.EXECUTIVE_SUMMARY:
            translated = self._format_executive_summary(translated, metadata)
        elif context == BusinessContext.COST_TRANSPARENCY:
            translated = self._format_cost_report(translated, metadata)
        elif context == BusinessContext.APPROVAL_REQUEST:
            translated = self._format_approval_request(translated, metadata)
        elif context == BusinessContext.PROGRESS_REPORT:
            translated = self._format_progress_report(translated, metadata)
        elif context == BusinessContext.SUCCESS_NOTIFICATION:
            translated = self._format_success_notification(translated, metadata)
        elif context == BusinessContext.ERROR_RESOLUTION:
            translated = self._format_error_resolution(translated, metadata)
        elif context == BusinessContext.ENTERPRISE_WORKFLOW:
            translated = self._format_enterprise_workflow(translated, metadata)
        elif context == BusinessContext.CORPORATE_WORKFLOW:
            translated = self._format_corporate_workflow(translated, metadata)
        elif context == BusinessContext.AI_COORDINATION:
            translated = self._format_ai_coordination(translated, metadata)
        elif context == BusinessContext.MESH_NETWORK_UPDATE:
            translated = self._format_mesh_network_update(translated, metadata)
        elif context == BusinessContext.ORCHESTRATOR_STATUS:
            translated = self._format_orchestrator_status(translated, metadata)
        elif context == BusinessContext.DISTRIBUTED_PROCESSING:
            translated = self._format_distributed_processing(translated, metadata)
        else:
            # Default operational update format
            translated = f"{template['intro']} {translated}"

        # Clean up and enhance readability
        translated = self._enhance_readability(translated)

        logger.debug(f"Translated message for {context.value}: {len(translated)} characters")
        return translated

    async def translate(
        self,
        content: str,
        context: BusinessContext = BusinessContext.OPERATIONAL_UPDATE,
        include_technical_details: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Async version of translate_message for compatibility with Communication Hub

        Args:
            content: Technical content to translate
            context: Business context for appropriate formatting
            include_technical_details: Whether to include technical details (currently ignored)
            metadata: Additional context data

        Returns:
            Business-friendly translated message
        """
        return self.translate_message(content, context, metadata)

    def _format_executive_summary(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as executive summary"""
        summary_parts = []

        if metadata and metadata.get('prospect_count'):
            summary_parts.append(f"Processed {metadata['prospect_count']} prospects")

        if metadata and metadata.get('cost_amount'):
            summary_parts.append(f"Total investment: ${metadata['cost_amount']:.2f}")

        if metadata and metadata.get('success_rate'):
            summary_parts.append(f"Success rate: {metadata['success_rate']}%")

        summary = f"📊 Executive Summary: {content}"
        if summary_parts:
            summary += f"\n\n• {' • '.join(summary_parts)}"

        return summary

    def _format_cost_report(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as cost transparency report"""
        cost_details = []

        if metadata:
            if metadata.get('service_name'):
                cost_details.append(f"Service: {metadata['service_name']}")
            if metadata.get('prospects_processed'):
                cost_details.append(f"Prospects processed: {metadata['prospects_processed']}")
            if metadata.get('cost_per_item'):
                cost_details.append(f"Cost per prospect: ${metadata['cost_per_item']:.2f}")

        report = f"💰 Cost Transparency: {content}"
        if cost_details:
            report += f"\n\nDetails:\n• {chr(10).join(f'• {detail}' for detail in cost_details)}"

        return report

    def _format_approval_request(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as approval request"""
        request_parts = [f"✋ Approval Required: {content}"]

        if metadata:
            if metadata.get('prospect_name'):
                request_parts.append(f"For: {metadata['prospect_name']}")
            if metadata.get('estimated_cost'):
                request_parts.append(f"Estimated cost: ${metadata['estimated_cost']:.2f}")
            if metadata.get('expected_outcome'):
                request_parts.append(f"Expected outcome: {metadata['expected_outcome']}")

        request_parts.append("Please review and approve to proceed.")
        return '\n\n'.join(request_parts)

    def _format_progress_report(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as progress report"""
        progress_parts = [f"📈 Progress Update: {content}"]

        if metadata:
            if metadata.get('completion_percentage'):
                progress_parts.append(f"Progress: {metadata['completion_percentage']}% complete")
            if metadata.get('next_milestone'):
                progress_parts.append(f"Next milestone: {metadata['next_milestone']}")
            if metadata.get('estimated_completion'):
                progress_parts.append(f"Estimated completion: {metadata['estimated_completion']}")

        return '\n\n'.join(progress_parts)

    def _format_success_notification(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as success notification"""
        success_parts = [f"✅ Success: {content}"]

        if metadata:
            if metadata.get('results_count'):
                success_parts.append(f"Results: {metadata['results_count']} items processed")
            if metadata.get('time_saved'):
                success_parts.append(f"Time saved: {metadata['time_saved']}")
            if metadata.get('next_action'):
                success_parts.append(f"Next step: {metadata['next_action']}")

        return '\n\n'.join(success_parts)

    def _format_error_resolution(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as error resolution"""
        resolution_parts = [f"🔧 Issue Resolved: {content}"]

        if metadata:
            if metadata.get('root_cause'):
                resolution_parts.append(f"Cause: {metadata['root_cause']}")
            if metadata.get('solution_applied'):
                resolution_parts.append(f"Solution: {metadata['solution_applied']}")
            if metadata.get('prevention_measures'):
                resolution_parts.append(f"Prevention: {metadata['prevention_measures']}")

        return '\n\n'.join(resolution_parts)

    def _format_enterprise_workflow(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as enterprise workflow update"""
        workflow_parts = [f"🏢 Enterprise Process: {content}"]

        if metadata:
            if metadata.get('workflow_id'):
                workflow_parts.append(f"Process ID: {metadata['workflow_id']}")
            if metadata.get('stage'):
                workflow_parts.append(f"Current stage: {metadata['stage'].replace('_', ' ').title()}")
            if metadata.get('progress_percent'):
                workflow_parts.append(f"Progress: {metadata['progress_percent']:.0f}% complete")
            if metadata.get('expected_stages'):
                workflow_parts.append(f"Total stages: {metadata['expected_stages']}")

        return '\n\n'.join(workflow_parts)

    def _format_corporate_workflow(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as corporate workflow update"""
        corporate_parts = [f"🔄 Corporate Workflow: {content}"]

        if metadata:
            if metadata.get('stage_names'):
                corporate_parts.append(f"Process stages: {', '.join(metadata['stage_names'])}")
            if metadata.get('stages_completed'):
                total = metadata.get('total_stages', 1)
                completed = metadata['stages_completed']
                corporate_parts.append(f"Completion: {completed}/{total} stages")
            if metadata.get('prospect_count'):
                corporate_parts.append(f"Processing: {metadata['prospect_count']} prospects")

        return '\n\n'.join(corporate_parts)

    def _format_ai_coordination(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as AI coordination update"""
        ai_parts = [f"🤖 AI Team Update: {content}"]

        if metadata:
            if metadata.get('active_agents'):
                ai_parts.append(f"Active assistants: {metadata['active_agents']}")
            if metadata.get('coordination_status'):
                ai_parts.append(f"Coordination: {metadata['coordination_status']}")
            if metadata.get('tasks_distributed'):
                ai_parts.append(f"Tasks distributed: {metadata['tasks_distributed']}")
            if metadata.get('response_time_ms'):
                ai_parts.append(f"Response time: {metadata['response_time_ms']}ms")

        return '\n\n'.join(ai_parts)

    def _format_mesh_network_update(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as mesh network status update"""
        network_parts = [f"🌐 Network Status: {content}"]

        if metadata:
            if metadata.get('connected_agents'):
                network_parts.append(f"Connected systems: {metadata['connected_agents']}")
            if metadata.get('network_health'):
                network_parts.append(f"Network health: {metadata['network_health']}")
            if metadata.get('message_throughput'):
                network_parts.append(f"Message throughput: {metadata['message_throughput']}/sec")
            if metadata.get('latency_ms'):
                network_parts.append(f"Network latency: {metadata['latency_ms']}ms")

        return '\n\n'.join(network_parts)

    def _format_orchestrator_status(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as orchestrator status update"""
        orchestrator_parts = [f"🎯 Process Manager: {content}"]

        if metadata:
            if metadata.get('active_workflows'):
                orchestrator_parts.append(f"Active processes: {metadata['active_workflows']}")
            if metadata.get('completed_workflows'):
                orchestrator_parts.append(f"Completed processes: {metadata['completed_workflows']}")
            if metadata.get('system_load'):
                orchestrator_parts.append(f"System load: {metadata['system_load']}%")
            if metadata.get('error_rate'):
                orchestrator_parts.append(f"Error rate: {metadata['error_rate']}%")

        return '\n\n'.join(orchestrator_parts)

    def _format_distributed_processing(self, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Format message as distributed processing update"""
        processing_parts = [f"⚡ Parallel Processing: {content}"]

        if metadata:
            if metadata.get('parallel_tasks'):
                processing_parts.append(f"Parallel tasks: {metadata['parallel_tasks']}")
            if metadata.get('processing_nodes'):
                processing_parts.append(f"Processing nodes: {metadata['processing_nodes']}")
            if metadata.get('throughput_per_minute'):
                processing_parts.append(f"Throughput: {metadata['throughput_per_minute']}/min")
            if metadata.get('efficiency_percent'):
                processing_parts.append(f"Efficiency: {metadata['efficiency_percent']}%")

        return '\n\n'.join(processing_parts)

    def _enhance_readability(self, content: str) -> str:
        """Enhance message readability for executives"""
        # Remove excessive technical details
        content = re.sub(r'\b[A-Z]{3,}\b', lambda m: m.group().title(), content)  # Convert ACRONYMS to Title

        # Improve number formatting
        content = re.sub(r'\b(\d+)ms\b', r'\1 milliseconds', content)
        content = re.sub(r'\b(\d+)kb\b', r'\1 KB', content)
        content = re.sub(r'\b(\d+)mb\b', r'\1 MB', content)

        # Clean up redundant technical phrases
        content = re.sub(r'successfully', 'completed', content)
        content = re.sub(r'initiated', 'started', content)
        content = re.sub(r'terminated', 'stopped', content)
        content = re.sub(r'executed', 'completed', content)

        # Ensure proper sentence structure
        content = content.strip()
        if content and not content.endswith('.'):
            content += '.'

        return content

    def translate_agent_name(self, technical_name: str) -> str:
        """
        Translate technical agent names to business-friendly names
        """
        name_translations = {
            'master_game_plan_orchestrator': 'Business Process Coordinator',
            'enterprise_master_game_plan_orchestrator': 'Enterprise Business Coordinator',
            'linkedin_mutuals_service': 'Network Discovery Assistant',
            'email_service': 'Communication Assistant',
            'approval_queue_service': 'Approval Manager',
            'workflow_orchestrator': 'Process Manager',
            'message_queue_orchestrator': 'Task Queue Manager',
            'prospect_enrichment_service': 'Contact Research Assistant',
            'introduction_service': 'Introduction Facilitator',
            'cost_tracking_service': 'Finance Monitor',
            'ai_agent_mesh_networks': 'AI Network Coordinator',
            'communication_hub': 'Central Communication Manager',
            'message_translator': 'Business Language Converter',
            'metadata_enricher': 'Context Enhancement Service',
            'workflow_persistence_service': 'Process State Manager',
            'resilience_manager': 'System Protection Service',
            'error_handler': 'Issue Resolution Service',
            'database_pool_manager': 'Data Connection Manager',
            'redis_streams_queue': 'Task Distribution Service',
            'audit_logging_service': 'Activity Tracking Service',
            'websocket_manager': 'Real-time Communication Service',
            'openai_agents_orchestrator': 'AI Assistant Coordinator',
            'executive_search_agent': 'Executive Discovery Assistant',
            'linkedin_url_finder_agent': 'Profile Discovery Assistant',
            'mutual_connections_agent': 'Network Analysis Assistant',
            'connector_ranking_agent': 'Introduction Ranking Assistant',
            'email_enrichment_agent': 'Contact Information Assistant',
            'human_approval_agent': 'Approval Processing Assistant',
            'email_sending_agent': 'Message Delivery Assistant'
        }

        return name_translations.get(technical_name.lower(), technical_name.replace('_', ' ').title())

    def get_business_impact_summary(self, metadata: Dict[str, Any]) -> str:
        """
        Generate business impact summary from technical metadata
        """
        impact_points = []

        if metadata.get('prospects_processed'):
            impact_points.append(f"Expanded network reach to {metadata['prospects_processed']} new contacts")

        if metadata.get('introductions_facilitated'):
            impact_points.append(f"Facilitated {metadata['introductions_facilitated']} business introductions")

        if metadata.get('time_saved_hours'):
            impact_points.append(f"Saved approximately {metadata['time_saved_hours']} hours of manual work")

        if metadata.get('cost_efficiency'):
            impact_points.append(f"Achieved {metadata['cost_efficiency']}% cost efficiency vs manual process")

        if metadata.get('response_rate'):
            impact_points.append(f"Generated {metadata['response_rate']}% response rate from outreach")

        if impact_points:
            return f"Business Impact:\n• " + '\n• '.join(impact_points)
        else:
            return "Process completed successfully with measurable business value."

# Global translator instance
global_translator: Optional[MessageTranslator] = None

def get_global_translator() -> MessageTranslator:
    """Get or create the global message translator instance"""
    global global_translator

    if global_translator is None:
        global_translator = MessageTranslator()
        logger.info("Global message translator initialized")

    return global_translator

def translate_for_executives(
    content: str,
    context: BusinessContext = BusinessContext.OPERATIONAL_UPDATE,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """Convenience function to translate messages for executives"""
    translator = get_global_translator()
    return translator.translate_message(content, context, metadata)

def translate_agent_message(
    agent_name: str,
    content: str,
    context: BusinessContext = BusinessContext.OPERATIONAL_UPDATE,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """Translate agent message with friendly agent name"""
    translator = get_global_translator()
    friendly_name = translator.translate_agent_name(agent_name)
    translated_content = translator.translate_message(content, context, metadata)

    return f"{friendly_name}: {translated_content}"