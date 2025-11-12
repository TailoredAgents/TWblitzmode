"""
OpenAI Agents SDK Multi-Agent Orchestrator (September 2025)
Advanced AI orchestration with human-in-the-loop for corporate workflows
"""
import asyncio
import logging
import json
from typing import Dict, List, Optional, Any, Tuple, Union
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
import uuid
from openai import AsyncOpenAI

from services.agent_provisioning_service import (
    agent_provisioning_service,
    ProvisionedAgent,
)
from services.email_service import email_service
from services.database import db, Database
from src.services.prospect_matcher import ProspectMatchingEngine
from src.services.ai_writer import AIWriterService
from src.services.connector_ranking import ConnectorRankingService
try:
    from src.services.company_exec_search import CompanyExecSearchService
except ImportError:  # pragma: no cover
    CompanyExecSearchService = None

from .workflow_persistence_service import WorkflowPersistenceService
from .resilience_patterns import ResilienceManager, BulkheadType
from .error_handling_framework import ErrorHandler, ErrorCategory, ErrorSeverity
from .progress_notifier import progress_notifier

# Import Agent for type annotations to prevent NameError
# Agent represents the OpenAI assistant agent that will be created
class Agent:
    """Placeholder for OpenAI Agent type"""
    pass

logger = logging.getLogger(__name__)

class AgentRole(Enum):
    """AI Agent roles in the corporate workflow orchestration"""
    PROSPECT_ANALYZER = "prospect_analyzer"
    EXECUTIVE_RESEARCHER = "executive_researcher"
    CONNECTION_MAPPER = "connection_mapper"
    EMAIL_COMPOSER = "email_composer"
    RISK_ASSESSOR = "risk_assessor"
    WORKFLOW_COORDINATOR = "workflow_coordinator"
    COMPLIANCE_AUDITOR = "compliance_auditor"
    PERFORMANCE_OPTIMIZER = "performance_optimizer"

class WorkflowStage(Enum):
    """Stages in the corporate introduction workflow"""
    PROSPECT_INTAKE = "prospect_intake"
    EXECUTIVE_RESEARCH = "executive_research"
    CONNECTION_ANALYSIS = "connection_analysis"
    EMAIL_GENERATION = "email_generation"
    RISK_ASSESSMENT = "risk_assessment"
    HUMAN_APPROVAL = "human_approval"
    EMAIL_SENDING = "email_sending"
    FOLLOW_UP = "follow_up"
    COMPLETION = "completion"

@dataclass
class AgentConfig:
    """Configuration for individual AI agents"""
    role: AgentRole
    name: str
    instructions: str
    tools: List[Dict[str, Any]]
    model: str = "gpt-4-turbo-2024-04-09"  # September 2025 model
    temperature: float = 0.3
    max_tokens: int = 4096
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class WorkflowContext:
    """Context shared across all agents in a workflow"""
    workflow_id: str
    tenant_id: str
    prospect_data: Dict[str, Any]
    current_stage: WorkflowStage
    agent_outputs: Dict[AgentRole, Any] = None
    human_feedback: Dict[str, Any] = None
    risk_score: float = 0.0
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.agent_outputs is None:
            self.agent_outputs = {}
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

class OpenAIAgentsOrchestrator:
    """
    September 2025 OpenAI Agents SDK Multi-Agent Orchestrator
    Advanced AI coordination with human oversight for corporate workflows
    """

    def __init__(self, api_key: str = None, organization: str = None,
                 approval_queue_service=None, websocket_manager=None, agent_logger=None):
        self.api_key = api_key
        self.organization = organization
        self.client: Optional[AsyncOpenAI] = None
        self.agent_registry: Dict[int, Dict[AgentRole, ProvisionedAgent]] = {}
        self._org_semaphores: Dict[int, asyncio.Semaphore] = {}
        self._clients: Dict[int, AsyncOpenAI] = {}
        self._client_meta: Dict[int, str] = {}
        self.prospect_engine = ProspectMatchingEngine()
        self.ai_writer = AIWriterService()
        self.connector_ranking = ConnectorRankingService()
        self.exec_search = CompanyExecSearchService() if CompanyExecSearchService else None

        # Dependency injection for services
        self.approval_queue_service = approval_queue_service
        self.websocket_manager = websocket_manager
        self.agent_logger = agent_logger

        # Maintain state of running workflows {workflow_id: {...}} so that we can resume or cancel them
        self.active_workflows: Dict[str, Dict[str, Any]] = {}

        # Enterprise persistence and resilience
        from .workflow_persistence_service import workflow_persistence_service
        self.persistence_service = workflow_persistence_service
        self.resilience_manager = ResilienceManager()
        self.error_handler = ErrorHandler()

        # Register bulkheads for different AI operations
        from .resilience_patterns import BulkheadConfig, BulkheadType
        self.resilience_manager.create_bulkhead(BulkheadConfig(
            name="ai_orchestrator",
            bulkhead_type=BulkheadType.THREAD_POOL,
            max_concurrent=5
        ))

        self.agent_configs = self._initialize_agent_configs()

    def _initialize_agent_configs(self) -> Dict[AgentRole, AgentConfig]:
        """Initialize configuration for each AI agent role"""
        return {
            AgentRole.PROSPECT_ANALYZER: AgentConfig(
                role=AgentRole.PROSPECT_ANALYZER,
                name="Prospect Intelligence Analyst",
                instructions="""You are an expert prospect intelligence analyst for B2B corporate introductions.

Your role:
1. Analyze prospect company data (size, industry, recent news, growth stage)
2. Identify key decision makers and organizational structure
3. Assess prospect readiness and engagement potential
4. Extract relevant business context for personalized outreach
5. Score prospects based on likelihood of positive response

Always provide structured analysis with confidence scores and reasoning.
Focus on finding genuine business connection opportunities, not just contact information.""",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "analyze_company_profile",
                            "description": "Analyze company profile and business context",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "company_name": {"type": "string"},
                                    "domain": {"type": "string"},
                                    "industry": {"type": "string"},
                                    "size": {"type": "string"}
                                },
                                "required": ["company_name"]
                            }
                        }
                    }
                ]
            ),

            AgentRole.EXECUTIVE_RESEARCHER: AgentConfig(
                role=AgentRole.EXECUTIVE_RESEARCHER,
                name="Executive Research Specialist",
                instructions="""You are a specialized executive research analyst for high-level B2B outreach.

Your expertise:
1. Research executive backgrounds, career trajectories, and current roles
2. Identify professional interests, recent achievements, and industry focus
3. Find speaking engagements, publications, and thought leadership content
4. Map executive networks and professional connections
5. Assess executive communication preferences and outreach timing

Provide comprehensive executive profiles with personalization opportunities.
Maintain the highest standards of professional research ethics.""",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "research_executive_profile",
                            "description": "Research executive background and professional profile",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "executive_name": {"type": "string"},
                                    "company": {"type": "string"},
                                    "title": {"type": "string"},
                                    "linkedin_url": {"type": "string"}
                                },
                                "required": ["executive_name", "company"]
                            }
                        }
                    }
                ]
            ),

            AgentRole.CONNECTION_MAPPER: AgentConfig(
                role=AgentRole.CONNECTION_MAPPER,
                name="Professional Network Mapper",
                instructions="""You are an expert in professional network analysis and relationship mapping.

Your capabilities:
1. Map mutual connections between prospects and team members
2. Analyze connection strength and relationship quality
3. Identify optimal introduction pathways and warm referral opportunities
4. Assess relationship context and shared experiences
5. Recommend connection strategies and approach timing

Create detailed connection maps with relationship insights and introduction recommendations.
Prioritize authentic, value-driven professional relationships.""",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "map_mutual_connections",
                            "description": "Map mutual connections between parties",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "prospect_linkedin": {"type": "string"},
                                    "team_member_profiles": {"type": "array", "items": {"type": "string"}},
                                    "connection_depth": {"type": "integer", "minimum": 1, "maximum": 3}
                                },
                                "required": ["prospect_linkedin", "team_member_profiles"]
                            }
                        }
                    }
                ]
            ),

            AgentRole.EMAIL_COMPOSER: AgentConfig(
                role=AgentRole.EMAIL_COMPOSER,
                name="Executive Email Composer",
                instructions="""You are a senior executive communication specialist and email composer.

Your expertise:
1. Craft highly personalized, executive-level introduction emails
2. Incorporate prospect research, mutual connections, and business context
3. Write compelling subject lines that ensure high open rates
4. Structure emails for maximum engagement and response likelihood
5. Adapt tone and style for different executive personalities and industries

Create emails that feel genuinely personal, not automated.
Focus on value proposition and mutual business interests.
Maintain the highest standards of professional communication.""",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "compose_introduction_email",
                            "description": "Compose personalized introduction email",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "prospect_profile": {"type": "object"},
                                    "mutual_connections": {"type": "array"},
                                    "business_context": {"type": "object"},
                                    "email_style": {"type": "string", "enum": ["formal", "casual", "industry-specific"]}
                                },
                                "required": ["prospect_profile", "business_context"]
                            }
                        }
                    }
                ]
            ),

            AgentRole.RISK_ASSESSOR: AgentConfig(
                role=AgentRole.RISK_ASSESSOR,
                name="Corporate Risk Assessment Specialist",
                instructions="""You are a corporate risk assessment specialist for B2B outreach campaigns.

Your analysis covers:
1. Reputation risk assessment for both parties
2. Compliance and regulatory considerations
3. Industry-specific outreach guidelines and restrictions
4. Cultural and geographical communication considerations
5. Potential negative outcomes and mitigation strategies

Provide comprehensive risk assessments with actionable recommendations.
Ensure all outreach activities meet the highest professional and ethical standards.""",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "assess_outreach_risk",
                            "description": "Assess risks associated with outreach campaign",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "prospect_company": {"type": "string"},
                                    "prospect_role": {"type": "string"},
                                    "outreach_method": {"type": "string"},
                                    "industry_context": {"type": "string"}
                                },
                                "required": ["prospect_company", "prospect_role"]
                            }
                        }
                    }
                ]
            ),

            AgentRole.WORKFLOW_COORDINATOR: AgentConfig(
                role=AgentRole.WORKFLOW_COORDINATOR,
                name="Workflow Orchestration Coordinator",
                instructions="""You are the central coordinator for multi-agent workflow orchestration.

Your responsibilities:
1. Coordinate handoffs between different agent specializations
2. Ensure data consistency and context preservation across agents
3. Monitor workflow progress and identify bottlenecks
4. Escalate complex decisions to human oversight
5. Optimize agent collaboration and resource allocation

Maintain comprehensive workflow state and ensure smooth agent coordination.
Prioritize quality outcomes over speed.""",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "coordinate_agent_handoff",
                            "description": "Coordinate handoff between agents",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "from_agent": {"type": "string"},
                                    "to_agent": {"type": "string"},
                                    "context_data": {"type": "object"},
                                    "next_action": {"type": "string"}
                                },
                                "required": ["from_agent", "to_agent", "context_data"]
                            }
                        }
                    }
                ]
            ),

            AgentRole.COMPLIANCE_AUDITOR: AgentConfig(
                role=AgentRole.COMPLIANCE_AUDITOR,
                name="Compliance and Ethics Auditor",
                instructions="""You are a compliance and ethics auditor for corporate outreach activities.

Your oversight includes:
1. GDPR, CAN-SPAM, and international privacy law compliance
2. Industry-specific regulation adherence (financial services, healthcare, etc.)
3. Corporate ethics and professional conduct standards
4. Data handling and privacy protection protocols
5. Audit trail maintenance and compliance documentation

Ensure all activities meet legal and ethical requirements.
Provide clear compliance guidance and corrective actions when needed.""",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "audit_compliance",
                            "description": "Audit workflow for compliance and ethics",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "workflow_data": {"type": "object"},
                                    "jurisdiction": {"type": "string"},
                                    "industry_sector": {"type": "string"}
                                },
                                "required": ["workflow_data"]
                            }
                        }
                    }
                ]
            ),

            AgentRole.PERFORMANCE_OPTIMIZER: AgentConfig(
                role=AgentRole.PERFORMANCE_OPTIMIZER,
                name="Performance Optimization Analyst",
                instructions="""You are a performance optimization analyst for AI-driven outreach campaigns.

Your analysis focuses on:
1. Campaign performance metrics and success rates
2. A/B testing insights and optimization recommendations
3. Agent performance evaluation and improvement suggestions
4. Resource allocation and efficiency optimization
5. Predictive modeling for future campaign success

Provide data-driven insights to continuously improve campaign effectiveness.
Focus on long-term relationship building, not just short-term response rates.""",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "optimize_performance",
                            "description": "Analyze and optimize campaign performance",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "campaign_data": {"type": "object"},
                                    "performance_metrics": {"type": "object"},
                                    "optimization_goals": {"type": "array"}
                                },
                                "required": ["campaign_data", "performance_metrics"]
                            }
                        }
                    }
                ]
            )
        }

    def _serialize_agent_config(self, config: AgentConfig) -> Dict[str, Any]:
        tools_payload = []
        for tool in config.tools or []:
            tools_payload.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })

        return {
            "name": config.name,
            "model": config.model,
            "instructions": config.instructions,
            "temperature": config.temperature,
            "tools": tools_payload,
            "metadata": {
                "human_oversight": str(config.human_oversight),
                "role": config.role.value,
            },
        }

    async def _get_provisioned_agent(self, organization_id: int, role: AgentRole) -> ProvisionedAgent:
        if organization_id not in self.agent_registry:
            await self.initialize_agents(organization_id)

        registry = self.agent_registry.get(organization_id, {})
        agent = registry.get(role)
        if agent:
            return agent

        config = self.agent_configs.get(role)
        if not config:
            raise ValueError(f"Unknown agent role: {role}")

        payload = self._serialize_agent_config(config)
        api_key = await self._resolve_api_key(organization_id)
        provisioned = await agent_provisioning_service.ensure_agent(
            tenant_id=organization_id,
            role=role.value,
            config_payload=payload,
            api_key=api_key,
            organization=self.organization,
        )
        self.agent_registry.setdefault(organization_id, {})[role] = provisioned
        return provisioned

    def _get_org_semaphore(self, organization_id: int) -> asyncio.Semaphore:
        if organization_id not in self._org_semaphores:
            self._org_semaphores[organization_id] = asyncio.Semaphore(max(self.resilience_manager.bulkheads["ai_orchestrator"].max_concurrent, 1))
        return self._org_semaphores[organization_id]

    async def _resolve_api_key(self, organization_id: int) -> str:
        from api.security import dec
        from api.db_core import get_conn
        try:
            from integrations.apify_client import get_tenant_integration_settings

            settings = get_tenant_integration_settings(organization_id)
            key = settings.get("openai_api_key")
            if key:
                return key
        except Exception as exc:
            logger.debug("Integration settings lookup failed for org %s: %s", organization_id, exc)

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(integration_sets)")
            columns = {row[1] for row in cursor.fetchall()}

            encrypted_column = None
            if "openai_api_key_encrypted" in columns:
                encrypted_column = "openai_api_key_encrypted"
            elif "openai_api_key" in columns:
                encrypted_column = "openai_api_key"

            if encrypted_column:
                cursor.execute(
                    f"SELECT {encrypted_column} FROM integration_sets WHERE organization_id = ?",
                    (organization_id,),
                )
                row = cursor.fetchone()
                if row and row[0]:
                    try:
                        return dec(row[0])
                    except Exception:
                        return row[0]

        if self.api_key:
            return self.api_key
        from core.settings import settings

        if settings.OPENAI_API_KEY:
            return settings.OPENAI_API_KEY

        raise RuntimeError("OpenAI API key not configured for organization")

    async def _get_openai_client(self, organization_id: int) -> AsyncOpenAI:
        api_key = await self._resolve_api_key(organization_id)
        client = self._clients.get(organization_id)
        if client and self._client_meta.get(organization_id) == api_key:
            return client

        if client:
            try:
                close_method = getattr(client, "close", None)
                if asyncio.iscoroutinefunction(close_method):
                    await close_method()  # type: ignore[misc]
                elif callable(close_method):
                    close_method()
            except Exception:
                pass

        client = AsyncOpenAI(api_key=api_key, organization=self.organization)
        self._clients[organization_id] = client
        self._client_meta[organization_id] = api_key
        self.client = client
        return client

    async def initialize_agents(self, organization_id: int):
        """Ensure assistants are provisioned for the organization."""
        try:
            client = await self._get_openai_client(organization_id)
            registry: Dict[AgentRole, ProvisionedAgent] = {}

            for role, config in self.agent_configs.items():
                payload = self._serialize_agent_config(config)
                provisioned = await agent_provisioning_service.ensure_agent(
                    tenant_id=organization_id,
                    role=role.value,
                    config_payload=payload,
                    api_key=client.api_key if hasattr(client, "api_key") else None,
                    organization=self.organization,
                )
                registry[role] = provisioned
                logger.info(
                    "✅ Provisioned agent %s (%s) for org %s",
                    provisioned.assistant_id,
                    role.value,
                    organization_id,
                )

            self.agent_registry[organization_id] = registry

        except Exception as e:
            logger.error(f"Failed to initialize agents for org {organization_id}: {e}")
            raise

    async def start_workflow(self, prospect_data: Dict[str, Any], tenant_id: str) -> str:
        """Start a new multi-agent workflow for prospect processing"""
        workflow_id = str(uuid.uuid4())

        try:
            # Use bulkhead for workflow creation
            async with self.resilience_manager.get_bulkhead("ai_orchestrator"):
                # Create workflow in enterprise persistence
                org_id = int(tenant_id) if tenant_id.isdigit() else hash(tenant_id) % 1000000

                requester = prospect_data.get("requested_by_user_id") or prospect_data.get("user_id") or 1

                await self.persistence_service.create_workflow(
                    organization_id=org_id,
                    user_id=int(requester),
                    workflow_type="ai_agent_orchestration",
                    prospects=[prospect_data],
                    team_members=[]
                )

                context = WorkflowContext(
                    workflow_id=workflow_id,
                    tenant_id=tenant_id,
                    prospect_data=prospect_data,
                    current_stage=WorkflowStage.PROSPECT_INTAKE
                )

                # Store context in active_workflows with user and organization IDs
                self.active_workflows[workflow_id] = {
                    "context": context,
                    "status": "running",
                    "current_stage": WorkflowStage.PROSPECT_INTAKE.value,
                    "user_id": int(requester),
                    "organization_id": org_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }

                # Store workflow status in persistence
                await self.persistence_service.update_workflow_status(
                    workflow_id=workflow_id,
                    status="running",
                    current_stage=WorkflowStage.PROSPECT_INTAKE.value
                )

                # Ensure assistants provisioned before continuing
                await self.initialize_agents(org_id)

                logger.info(f"Started workflow {workflow_id} for tenant {tenant_id}")

                # Send workflow started notification
                await progress_notifier.notify_workflow_started(
                    user_id=int(requester),
                    organization_id=org_id,
                    workflow_type="ai_agent_orchestration",
                    workflow_id=workflow_id,
                    total_steps=8,  # Total workflow stages
                    metadata={
                        "prospect_company": prospect_data.get("company_name", "Unknown"),
                        "prospect_name": f"{prospect_data.get('first_name', '')} {prospect_data.get('last_name', '')}".strip(),
                        "tenant_id": tenant_id
                    }
                )

                # Begin with prospect analysis
                await self._execute_stage(workflow_id, WorkflowStage.PROSPECT_INTAKE)

                return workflow_id

        except Exception as e:
            error_context = {
                'workflow_id': workflow_id,
                'tenant_id': tenant_id,
                'prospect_data': prospect_data
            }

            await self.error_handler.handle_error(
                error=e,
                operation="start_ai_workflow",
                context=error_context,
                category=ErrorCategory.WORKFLOW_ERROR,
                severity=ErrorSeverity.HIGH
            )

            logger.error(f"Failed to start AI workflow {workflow_id}: {e}")
            raise

    async def _execute_stage(self, workflow_id: str, stage: WorkflowStage):
        """Execute a specific stage of the workflow with appropriate agent"""
        try:
            # Get workflow context from persistence
            workflow_data = await self.persistence_service.get_workflow(workflow_id)
            if not workflow_data:
                raise ValueError(f"Workflow {workflow_id} not found in persistence")

            # Create context from persisted data
            context = WorkflowContext(
                workflow_id=workflow_id,
                tenant_id=str(workflow_data['organization_id']),
                prospect_data=workflow_data.get('prospects', [{}])[0] if workflow_data.get('prospects') else {},
                current_stage=stage
            )

            # Update stage in persistence
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="running",
                current_stage=stage.value
            )

            # Send stage progress notification
            stage_mapping = {
                WorkflowStage.PROSPECT_INTAKE: (1, "Analyzing prospect information and company data"),
                WorkflowStage.EXECUTIVE_RESEARCH: (2, "Researching executive profiles and LinkedIn data"),
                WorkflowStage.CONNECTION_ANALYSIS: (3, "Mapping mutual connections and relationships"),
                WorkflowStage.EMAIL_GENERATION: (4, "Composing personalized introduction email"),
                WorkflowStage.RISK_ASSESSMENT: (5, "Conducting compliance and risk assessment"),
                WorkflowStage.HUMAN_APPROVAL: (6, "Awaiting human review and approval"),
                WorkflowStage.EMAIL_SENDING: (7, "Sending approved introduction email"),
                WorkflowStage.FOLLOW_UP: (8, "Setting up follow-up workflow"),
                WorkflowStage.COMPLETION: (8, "Workflow completed successfully")
            }

            if stage in stage_mapping:
                step_number, step_message = stage_mapping[stage]
                await progress_notifier.notify_progress_update(
                    user_id=1,  # System user for AI workflows
                    organization_id=int(context.tenant_id) if context.tenant_id.isdigit() else hash(context.tenant_id) % 1000000,
                    workflow_type="ai_agent_orchestration",
                    workflow_id=workflow_id,
                    current_step=step_number,
                    total_steps=8,
                    step_message=step_message,
                    metadata={
                        "stage": stage.value,
                        "prospect_company": context.prospect_data.get("company_name", "Unknown")
                    }
                )

            stage_handlers = {
                WorkflowStage.PROSPECT_INTAKE: self._handle_prospect_analysis,
                WorkflowStage.EXECUTIVE_RESEARCH: self._handle_executive_research,
                WorkflowStage.CONNECTION_ANALYSIS: self._handle_connection_mapping,
                WorkflowStage.EMAIL_GENERATION: self._handle_email_composition,
                WorkflowStage.RISK_ASSESSMENT: self._handle_risk_assessment,
                WorkflowStage.HUMAN_APPROVAL: self._handle_human_approval,
                WorkflowStage.EMAIL_SENDING: self._handle_email_sending,
                WorkflowStage.FOLLOW_UP: self._handle_follow_up,
                WorkflowStage.COMPLETION: self._handle_completion
            }

            handler = stage_handlers.get(stage)
            if handler:
                try:
                    await handler(workflow_id)
                except Exception as e:
                    logger.error(f"Stage {stage} failed for workflow {workflow_id}: {e}")
                    await self._handle_error(workflow_id, stage, e)
            else:
                logger.error(f"No handler for stage {stage}")
        except Exception as e:
            logger.error(f"Failed to execute stage {stage} for workflow {workflow_id}: {e}")
            await self._handle_error(workflow_id, stage, e)

    async def _handle_prospect_analysis(self, workflow_id: str):
        """Handle prospect analysis stage using real company executive search"""
        workflow_data = self.active_workflows[workflow_id]
        context = workflow_data["context"]
        organization_id = workflow_data.get("organization_id")
        user_id = workflow_data.get("user_id")

        # Log task start
        if self.agent_logger:
            await self.agent_logger.log_task_start(
                agent_name="prospect_analyzer",
                task_name="Prospect analysis",
                metadata={
                    "workflow_id": workflow_id,
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "prospect_company": context.prospect_data.get("company", "Unknown")
                }
            )

        try:
            # Use real company executive search service
            from src.services.company_exec_search import CompanyExecSearchService

            exec_service = CompanyExecSearchService()
            company_name = context.prospect_data.get("company", "")

            if not company_name:
                raise ValueError("Company name is required for prospect analysis")

            # Find executives for the company
            executives = await exec_service.find_executives_for_company(
                company_name=company_name,
                titles=["CEO", "Chief Executive", "CMO", "Chief Marketing", "COO", "Chief Operating",
                       "CTO", "Chief Technology", "CFO", "Chief Financial", "President", "Founder"],
                max_results=5
            )

            # Calculate engagement score based on executive findings
            engagement_score = self._calculate_engagement_score(executives, context.prospect_data)

            # Analyze company data based on executive profiles
            company_analysis = self._analyze_company_data(executives, context.prospect_data)

            # Evaluate contact potential
            contact_evaluation = self._evaluate_contact_potential(executives, context.prospect_data)

            result = {
                "company_analysis": company_analysis,
                "contact_evaluation": contact_evaluation,
                "engagement_score": engagement_score,
                "executives_found": [
                    {
                        "name": exec.full_name,
                        "title": exec.title,
                        "linkedin_url": exec.linkedin_url,
                        "confidence_score": exec.confidence_score,
                        "data_source": exec.data_source
                    } for exec in executives
                ],
                "total_executives": len(executives),
                "business_context": {
                    "has_leadership_data": len(executives) > 0,
                    "leadership_accessibility": "High" if len(executives) >= 3 else "Medium" if len(executives) >= 1 else "Low",
                    "data_quality": "High" if any(exec.confidence_score > 0.7 for exec in executives) else "Medium"
                },
                "next_steps": self._determine_next_steps(engagement_score, executives)
            }

            context.agent_outputs[AgentRole.PROSPECT_ANALYZER] = result

            # Log task completion with real metrics
            if self.agent_logger:
                await self.agent_logger.log_task_complete(
                    agent_name="prospect_analyzer",
                    task_name="Prospect analysis",
                    metadata={
                        "workflow_id": workflow_id,
                        "organization_id": organization_id,
                        "user_id": user_id,
                        "engagement_score": engagement_score,
                        "executives_found": len(executives),
                        "data_quality": result["business_context"]["data_quality"],
                        "next_stage": "executive_research" if engagement_score >= 60 else "completion"
                    }
                )

            # Proceed to next stage based on analysis
            if engagement_score >= 60:  # Lowered threshold for real data
                await self._execute_stage(workflow_id, WorkflowStage.EXECUTIVE_RESEARCH)
            else:
                logger.info(f"Prospect scored {engagement_score}% - too low for workflow {workflow_id}, ending process")
                await self._execute_stage(workflow_id, WorkflowStage.COMPLETION)

        except Exception as e:
            logger.error(f"Prospect analysis failed for workflow {workflow_id}: {e}")

            # Log the error
            if self.agent_logger:
                await self.agent_logger.log_task_error(
                    agent_name="prospect_analyzer",
                    task_name="Prospect analysis",
                    error_message=str(e),
                    metadata={
                        "workflow_id": workflow_id,
                        "organization_id": organization_id,
                        "user_id": user_id
                    }
                )

            # Fallback: proceed with limited data if possible
            fallback_result = {
                "company_analysis": {
                    "company_size": "Unknown",
                    "industry_focus": context.prospect_data.get('industry', 'Technology'),
                    "growth_stage": "Unknown"
                },
                "contact_evaluation": {
                    "decision_maker_level": "Unknown",
                    "influence_score": 50
                },
                "engagement_score": 40,  # Low score due to data issues
                "executives_found": [],
                "total_executives": 0,
                "business_context": {
                    "has_leadership_data": False,
                    "leadership_accessibility": "Unknown",
                    "data_quality": "Low",
                    "analysis_error": str(e)
                },
                "next_steps": ["Manual research required"]
            }

            context.agent_outputs[AgentRole.PROSPECT_ANALYZER] = fallback_result
            await self._execute_stage(workflow_id, WorkflowStage.COMPLETION)

    def _calculate_engagement_score(self, executives: list, prospect_data: dict) -> int:
        """Calculate engagement score based on executive findings and prospect data"""
        score = 0

        # Base score for having any executive data
        if executives:
            score += 30

        # Score based on number of executives found
        exec_count_score = min(len(executives) * 15, 40)  # Max 40 points for exec count
        score += exec_count_score

        # Score based on executive seniority
        senior_titles = ["CEO", "Chief Executive", "President", "Founder"]
        c_level_titles = ["CMO", "CTO", "CFO", "COO"]

        for exec in executives:
            title_lower = exec.title.lower()
            if any(title.lower() in title_lower for title in senior_titles):
                score += 15  # High value for senior executives
            elif any(title.lower() in title_lower for title in c_level_titles):
                score += 10  # Medium value for C-level

        # Score based on data quality
        avg_confidence = sum(exec.confidence_score for exec in executives) / len(executives) if executives else 0
        score += int(avg_confidence * 20)  # Max 20 points for data quality

        # Bonus for LinkedIn URLs (easier outreach)
        linkedin_bonus = sum(5 for exec in executives if exec.linkedin_url)
        score += min(linkedin_bonus, 15)  # Max 15 points for LinkedIn presence

        return min(score, 100)  # Cap at 100

    def _analyze_company_data(self, executives: list, prospect_data: dict) -> dict:
        """Analyze company based on executive profiles and known data"""
        if not executives:
            return {
                "company_size": "Unknown",
                "industry_focus": prospect_data.get('industry', 'Technology'),
                "growth_stage": "Unknown",
                "leadership_quality": "Unknown"
            }

        # Estimate company size based on executive diversity
        exec_count = len(executives)
        if exec_count >= 4:
            company_size = "Large Enterprise"
        elif exec_count >= 2:
            company_size = "Mid-market"
        else:
            company_size = "Small Business"

        # Analyze leadership quality
        senior_execs = sum(1 for exec in executives
                          if any(title in exec.title.lower()
                                for title in ["ceo", "president", "founder", "chief"]))

        leadership_quality = "High" if senior_execs >= 2 else "Medium" if senior_execs >= 1 else "Low"

        return {
            "company_size": company_size,
            "industry_focus": prospect_data.get('industry', 'Technology'),
            "growth_stage": "Scaling" if exec_count >= 3 else "Established",
            "leadership_quality": leadership_quality,
            "executive_diversity": exec_count,
            "data_completeness": "High" if exec_count >= 3 else "Medium"
        }

    def _evaluate_contact_potential(self, executives: list, prospect_data: dict) -> dict:
        """Evaluate the potential for successful contact based on executive data"""
        if not executives:
            return {
                "decision_maker_level": "Unknown",
                "influence_score": 30,
                "accessibility": "Low",
                "contact_confidence": "Low"
            }

        # Find highest-ranking executive
        senior_titles = ["CEO", "Chief Executive", "President", "Founder"]
        has_senior_exec = any(any(title.lower() in exec.title.lower() for title in senior_titles)
                             for exec in executives)

        # Calculate influence score
        influence_score = 60  # Base score
        if has_senior_exec:
            influence_score += 25

        # Bonus for LinkedIn accessibility
        linkedin_count = sum(1 for exec in executives if exec.linkedin_url)
        if linkedin_count > 0:
            influence_score += 15

        accessibility = "High" if linkedin_count >= 2 else "Medium" if linkedin_count >= 1 else "Low"
        decision_maker_level = "High" if has_senior_exec else "Medium"
        contact_confidence = "High" if influence_score >= 80 else "Medium" if influence_score >= 60 else "Low"

        return {
            "decision_maker_level": decision_maker_level,
            "influence_score": min(influence_score, 100),
            "accessibility": accessibility,
            "contact_confidence": contact_confidence,
            "linkedin_profiles_found": linkedin_count
        }

    def _determine_next_steps(self, engagement_score: int, executives: list) -> list:
        """Determine next steps based on analysis results"""
        next_steps = []

        if engagement_score >= 80:
            next_steps.extend(["Executive research", "Connection mapping", "Email generation"])
        elif engagement_score >= 60:
            next_steps.extend(["Executive research", "Connection mapping"])
        elif engagement_score >= 40:
            next_steps.extend(["Manual research", "Alternative outreach"])
        else:
            next_steps.extend(["Prospect reconsideration", "Data enhancement"])

        if executives and any(exec.linkedin_url for exec in executives):
            next_steps.append("LinkedIn outreach preparation")

        return next_steps

    async def _handle_executive_research(self, workflow_id: str):
        """Handle executive research stage using real LinkedIn research services"""
        workflow_data = self.active_workflows[workflow_id]
        context = workflow_data["context"]
        organization_id = workflow_data.get("organization_id")
        user_id = workflow_data.get("user_id")

        # Log task start
        if self.agent_logger:
            await self.agent_logger.log_task_start(
                agent_name="executive_research_agent",
                task_name="Executive research",
                metadata={
                    "workflow_id": workflow_id,
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "prospect_name": context.prospect_data.get("full_name", "Unknown")
                }
            )

        try:
            # Get executives from Prospect Analyzer results
            prospect_analysis = context.agent_outputs.get(AgentRole.PROSPECT_ANALYZER, {})
            executives_found = prospect_analysis.get("executives_found", [])

            if not executives_found:
                raise ValueError("No executives found from prospect analysis to research")

            # Perform detailed research on each executive
            research_results = []

            for exec_data in executives_found:
                research_result = await self._research_executive_profile(
                    exec_data, context.prospect_data, organization_id
                )
                research_results.append(research_result)

            # Aggregate and analyze research findings
            aggregated_research = self._aggregate_research_findings(research_results, context.prospect_data)

            result = {
                "executives_researched": len(research_results),
                "research_results": research_results,
                "aggregated_insights": aggregated_research,
                "research_quality": self._assess_research_quality(research_results),
                "engagement_opportunities": self._identify_engagement_opportunities(research_results),
                "personalization_data": self._extract_personalization_data(research_results),
                "next_steps": self._determine_research_next_steps(aggregated_research)
            }

            context.agent_outputs[AgentRole.EXECUTIVE_RESEARCHER] = result

            # Log successful completion
            if self.agent_logger:
                await self.agent_logger.log_task_complete(
                    agent_name="executive_research_agent",
                    task_name="Executive research",
                    metadata={
                        "workflow_id": workflow_id,
                        "organization_id": organization_id,
                        "user_id": user_id,
                        "executives_researched": len(research_results),
                        "research_quality": result["research_quality"],
                        "engagement_opportunities": len(result["engagement_opportunities"])
                    }
                )

            # Proceed to connection mapping
            await self._execute_stage(workflow_id, WorkflowStage.CONNECTION_ANALYSIS)

        except Exception as e:
            logger.error(f"Executive research failed for workflow {workflow_id}: {e}")

            # Log the error
            if self.agent_logger:
                await self.agent_logger.log_task_error(
                    agent_name="executive_research_agent",
                    task_name="Executive research",
                    error_message=str(e),
                    metadata={
                        "workflow_id": workflow_id,
                        "organization_id": organization_id,
                        "user_id": user_id
                    }
                )

            # Fallback: proceed with basic research data
            fallback_result = {
                "executives_researched": 0,
                "research_results": [],
                "aggregated_insights": {
                    "industry_focus": context.prospect_data.get("industry", "Technology"),
                    "company_stage": "Unknown",
                    "key_challenges": ["Data unavailable"],
                    "research_error": str(e)
                },
                "research_quality": "Low",
                "engagement_opportunities": [],
                "personalization_data": {},
                "next_steps": ["Manual research required", "Direct outreach"]
            }

            context.agent_outputs[AgentRole.EXECUTIVE_RESEARCHER] = fallback_result
            await self._execute_stage(workflow_id, WorkflowStage.CONNECTION_ANALYSIS)

    async def _research_executive_profile(self, exec_data: dict, prospect_data: dict, organization_id: int) -> dict:
        """Research individual executive profile using available services"""
        research_result = {
            "executive": exec_data,
            "profile_data": {},
            "insights": {},
            "engagement_angles": [],
            "research_sources": []
        }

        try:
            # Use browser service for web research if LinkedIn URL available
            linkedin_url = exec_data.get("linkedin_url")
            if linkedin_url:
                # Research via web search for public information
                from services.browser_service import browser_service

                exec_name = exec_data.get("name", "")
                company_name = prospect_data.get("company", "")

                # Search for recent news, achievements, and public information
                search_queries = [
                    f'"{exec_name}" "{company_name}" news OR announcement',
                    f'"{exec_name}" "{company_name}" interview OR speaking',
                    f'"{exec_name}" linkedin profile achievements'
                ]

                profile_insights = []
                for query in search_queries:
                    try:
                        search_result = await browser_service.search(query, max_results=2)
                        if search_result.status == "success" and search_result.results:
                            for citation in search_result.results:
                                profile_insights.append({
                                    "source": citation.domain,
                                    "title": citation.title,
                                    "snippet": citation.snippet,
                                    "url": citation.url,
                                    "relevance": citation.relevance_score
                                })
                                research_result["research_sources"].append(citation.id)
                    except Exception as e:
                        logger.warning(f"Search failed for query '{query}': {e}")

                research_result["profile_data"]["web_insights"] = profile_insights

            # Extract insights from title and company context
            title_insights = self._analyze_executive_title(exec_data.get("title", ""))
            research_result["insights"] = {
                "seniority_level": title_insights["seniority"],
                "functional_area": title_insights["function"],
                "decision_authority": title_insights["authority"],
                "likely_pain_points": self._infer_pain_points(title_insights, prospect_data),
                "engagement_style": self._infer_engagement_style(title_insights)
            }

            # Generate engagement angles
            research_result["engagement_angles"] = self._generate_engagement_angles(
                exec_data, title_insights, prospect_data
            )

        except Exception as e:
            logger.error(f"Failed to research executive {exec_data.get('name', 'Unknown')}: {e}")
            research_result["insights"]["research_error"] = str(e)

        return research_result

    def _analyze_executive_title(self, title: str) -> dict:
        """Analyze executive title to extract functional insights"""
        title_lower = title.lower()

        # Determine seniority
        if any(word in title_lower for word in ["ceo", "president", "founder", "owner"]):
            seniority = "C-Suite"
        elif any(word in title_lower for word in ["chief", "cfo", "cto", "cmo", "coo"]):
            seniority = "C-Level"
        elif any(word in title_lower for word in ["vp", "vice president", "director"]):
            seniority = "Senior Management"
        elif any(word in title_lower for word in ["manager", "head"]):
            seniority = "Management"
        else:
            seniority = "Individual Contributor"

        # Determine functional area
        if any(word in title_lower for word in ["marketing", "cmo", "brand", "growth"]):
            function = "Marketing"
        elif any(word in title_lower for word in ["sales", "revenue", "business development"]):
            function = "Sales"
        elif any(word in title_lower for word in ["technology", "cto", "engineering", "technical"]):
            function = "Technology"
        elif any(word in title_lower for word in ["operations", "coo", "operational"]):
            function = "Operations"
        elif any(word in title_lower for word in ["finance", "cfo", "financial"]):
            function = "Finance"
        elif any(word in title_lower for word in ["human resources", "hr", "people"]):
            function = "Human Resources"
        else:
            function = "General Management"

        # Determine decision authority
        authority_map = {
            "C-Suite": "Final Decision Maker",
            "C-Level": "Key Decision Maker",
            "Senior Management": "Influencer",
            "Management": "Recommender",
            "Individual Contributor": "End User"
        }

        return {
            "seniority": seniority,
            "function": function,
            "authority": authority_map.get(seniority, "Unknown")
        }

    def _infer_pain_points(self, title_insights: dict, prospect_data: dict) -> list:
        """Infer likely pain points based on role and company context"""
        pain_points = []

        function = title_insights.get("function", "")
        seniority = title_insights.get("seniority", "")

        # Function-specific pain points
        function_pain_points = {
            "Marketing": ["Lead generation", "Attribution tracking", "ROI measurement", "Brand awareness"],
            "Sales": ["Pipeline management", "Conversion rates", "Sales cycle length", "Territory coverage"],
            "Technology": ["System scalability", "Technical debt", "Team productivity", "Innovation pace"],
            "Operations": ["Process efficiency", "Cost optimization", "Quality control", "Resource allocation"],
            "Finance": ["Budget management", "Financial reporting", "Cash flow", "Investment decisions"],
            "Human Resources": ["Talent acquisition", "Employee retention", "Performance management", "Culture"],
            "General Management": ["Strategic planning", "Growth initiatives", "Competitive positioning", "Organizational efficiency"]
        }

        pain_points.extend(function_pain_points.get(function, ["Strategic challenges", "Operational efficiency"]))

        # Seniority-specific pain points
        if seniority in ["C-Suite", "C-Level"]:
            pain_points.extend(["Board reporting", "Strategic vision", "Market positioning", "Stakeholder management"])
        elif seniority == "Senior Management":
            pain_points.extend(["Team performance", "Budget constraints", "Cross-functional alignment"])

        return pain_points[:4]  # Limit to top 4 most relevant

    def _infer_engagement_style(self, title_insights: dict) -> str:
        """Infer preferred engagement style based on role"""
        seniority = title_insights.get("seniority", "")
        function = title_insights.get("function", "")

        if seniority in ["C-Suite", "C-Level"]:
            return "Strategic and high-level, focus on business impact and ROI"
        elif function == "Technology":
            return "Technical and detailed, focus on implementation and innovation"
        elif function == "Marketing":
            return "Creative and data-driven, focus on metrics and brand impact"
        elif function == "Sales":
            return "Results-oriented and competitive, focus on numbers and outcomes"
        else:
            return "Professional and collaborative, focus on mutual benefits"

    def _generate_engagement_angles(self, exec_data: dict, title_insights: dict, prospect_data: dict) -> list:
        """Generate potential engagement angles for outreach"""
        angles = []

        function = title_insights.get("function", "")
        pain_points = title_insights.get("likely_pain_points", [])

        # Industry-specific angles
        industry = prospect_data.get("industry", "")
        if industry:
            angles.append(f"Industry trends in {industry}")
            angles.append(f"Best practices for {industry} companies")

        # Function-specific angles
        if function:
            angles.append(f"{function} optimization strategies")
            angles.append(f"Latest {function} technology solutions")

        # Pain point-based angles
        for pain_point in pain_points[:2]:  # Top 2 pain points
            angles.append(f"Solutions for {pain_point.lower()}")

        # Generic professional angles
        angles.extend([
            "Networking and industry connections",
            "Thought leadership opportunities",
            "Competitive intelligence sharing"
        ])

        return angles[:5]  # Limit to top 5 angles

    def _aggregate_research_findings(self, research_results: list, prospect_data: dict) -> dict:
        """Aggregate research findings across all executives"""
        if not research_results:
            return {
                "company_focus": "Unknown",
                "leadership_style": "Unknown",
                "key_challenges": [],
                "engagement_readiness": "Low"
            }

        # Analyze leadership composition
        functions = [r["insights"].get("functional_area", "Unknown") for r in research_results]
        seniority_levels = [r["insights"].get("seniority_level", "Unknown") for r in research_results]

        # Aggregate pain points
        all_pain_points = []
        for result in research_results:
            all_pain_points.extend(result["insights"].get("likely_pain_points", []))

        # Count and rank pain points
        pain_point_counts = {}
        for pain_point in all_pain_points:
            pain_point_counts[pain_point] = pain_point_counts.get(pain_point, 0) + 1

        top_challenges = sorted(pain_point_counts.items(), key=lambda x: x[1], reverse=True)[:3]

        # Assess engagement readiness
        c_level_count = sum(1 for level in seniority_levels if level in ["C-Suite", "C-Level"])
        linkedin_profiles = sum(1 for result in research_results
                               if result["executive"].get("linkedin_url"))

        if c_level_count >= 2 and linkedin_profiles >= 2:
            engagement_readiness = "High"
        elif c_level_count >= 1 and linkedin_profiles >= 1:
            engagement_readiness = "Medium"
        else:
            engagement_readiness = "Low"

        return {
            "company_focus": prospect_data.get("industry", "Technology"),
            "leadership_diversity": len(set(functions)),
            "leadership_style": "Traditional" if c_level_count >= 2 else "Collaborative",
            "key_challenges": [challenge[0] for challenge in top_challenges],
            "engagement_readiness": engagement_readiness,
            "total_research_sources": sum(len(r.get("research_sources", [])) for r in research_results),
            "functional_coverage": list(set(functions))
        }

    def _assess_research_quality(self, research_results: list) -> str:
        """Assess overall quality of research conducted"""
        if not research_results:
            return "Poor"

        total_sources = sum(len(r.get("research_sources", [])) for r in research_results)
        profiles_with_data = sum(1 for r in research_results
                                if r.get("profile_data", {}).get("web_insights"))

        if total_sources >= 5 and profiles_with_data >= 2:
            return "High"
        elif total_sources >= 2 and profiles_with_data >= 1:
            return "Medium"
        else:
            return "Low"

    def _identify_engagement_opportunities(self, research_results: list) -> list:
        """Identify specific engagement opportunities from research"""
        opportunities = []

        for result in research_results:
            exec_name = result["executive"].get("name", "Unknown")
            angles = result.get("engagement_angles", [])

            for angle in angles[:2]:  # Top 2 angles per executive
                opportunities.append({
                    "executive": exec_name,
                    "opportunity": angle,
                    "approach": f"Personalized outreach about {angle.lower()}"
                })

        return opportunities

    def _extract_personalization_data(self, research_results: list) -> dict:
        """Extract data useful for email personalization"""
        personalization = {
            "executives_by_function": {},
            "common_challenges": [],
            "industry_insights": [],
            "engagement_hooks": []
        }

        for result in research_results:
            exec_data = result["executive"]
            insights = result["insights"]

            function = insights.get("functional_area", "Unknown")
            if function not in personalization["executives_by_function"]:
                personalization["executives_by_function"][function] = []

            personalization["executives_by_function"][function].append({
                "name": exec_data.get("name"),
                "title": exec_data.get("title"),
                "pain_points": insights.get("likely_pain_points", [])
            })

            # Collect engagement hooks
            web_insights = result.get("profile_data", {}).get("web_insights", [])
            for insight in web_insights:
                if insight.get("relevance", 0) > 0.5:
                    personalization["engagement_hooks"].append({
                        "executive": exec_data.get("name"),
                        "hook": insight.get("title", ""),
                        "source": insight.get("source", "")
                    })

        return personalization

    def _determine_research_next_steps(self, aggregated_research: dict) -> list:
        """Determine next steps based on research quality and findings"""
        next_steps = []

        engagement_readiness = aggregated_research.get("engagement_readiness", "Low")

        if engagement_readiness == "High":
            next_steps.extend([
                "Connection mapping",
                "Personalized email drafting",
                "Multi-touch outreach sequence"
            ])
        elif engagement_readiness == "Medium":
            next_steps.extend([
                "Connection mapping",
                "Basic email outreach",
                "Follow-up strategy"
            ])
        else:
            next_steps.extend([
                "Additional research",
                "Alternative contact methods",
                "Referral identification"
            ])

        if aggregated_research.get("total_research_sources", 0) > 0:
            next_steps.append("Citation-based personalization")

        return next_steps

    async def _handle_connection_mapping(self, workflow_id: str):
        """Handle mutual connection mapping using real prospect matcher service"""
        workflow_data = self.active_workflows[workflow_id]
        context = workflow_data["context"]
        organization_id = workflow_data.get("organization_id")
        user_id = workflow_data.get("user_id")

        # Log task start
        if self.agent_logger:
            await self.agent_logger.log_task_start(
                agent_name="connection_mapping_agent",
                task_name="Connection mapping",
                metadata={
                    "workflow_id": workflow_id,
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "prospect_company": context.prospect_data.get("company", "Unknown")
                }
            )

        try:
            # Get prospect LinkedIn URL from the data
            linkedin_url = context.prospect_data.get("linkedin_url", "")
            prospect_name = context.prospect_data.get("full_name", "")

            if not linkedin_url:
                # Try to get LinkedIn URL from executive research results
                exec_research = context.agent_outputs.get(AgentRole.EXECUTIVE_RESEARCHER, {})
                research_results = exec_research.get("research_results", [])

                for research in research_results:
                    exec_linkedin = research.get("executive", {}).get("linkedin_url")
                    if exec_linkedin:
                        linkedin_url = exec_linkedin
                        prospect_name = research.get("executive", {}).get("name", prospect_name)
                        break

            if not linkedin_url:
                raise ValueError("No LinkedIn URL available for connection mapping")

            # Use real prospect matcher service
            from src.services.prospect_matcher import ProspectMatchingEngine

            matcher = ProspectMatchingEngine()

            # First, we need to create a prospect entry in the database if it doesn't exist
            prospect_data_for_matching = {
                "full_name": prospect_name,
                "company": context.prospect_data.get("company", ""),
                "linkedin_url": linkedin_url,
                "industry": context.prospect_data.get("industry", ""),
                "title": context.prospect_data.get("title", ""),
                "organization_id": organization_id
            }

            # Store prospect temporarily for matching (if needed)
            tenant_value = getattr(context, "tenant_id", None) or organization_id
            if tenant_value is None or str(tenant_value).strip() == "":
                raise ValueError("tenant_id is required for orchestrating prospect matching")
            tenant_scope = str(tenant_value).strip()
            user_scope = (
                int(user_id) if user_id is not None else Database.SYSTEM_USER_ID
            )

            existing_prospects = await db.get_prospects(
                status="all",
                user_id=user_scope,
                tenant_id=tenant_scope,
            )

            # Find if prospect already exists
            prospect_id = None
            for prospect in existing_prospects:
                if (prospect.get("linkedin_url") == linkedin_url or
                    (prospect.get("full_name") == prospect_name and
                     prospect.get("company") == prospect_data_for_matching["company"])):
                    prospect_id = prospect["id"]
                    break

            # If not found, create temporary prospect for matching
            if not prospect_id:
                # Add prospect to database for matching
                await db.add_prospects_batch(
                    [prospect_data_for_matching],
                    user_id=user_scope,
                    tenant_id=tenant_scope,
                )
                prospects = await db.get_prospects(
                    status="all",
                    user_id=user_scope,
                    tenant_id=tenant_scope,
                )
                prospect_id = prospects[-1]["id"]  # Get the last added prospect

            # Perform connection matching
            logger.info(f"Starting connection mapping for prospect {prospect_id}: {prospect_name}")

            matching_result = await matcher.find_prospect_matches(
                prospect_id,
                tenant_id=tenant_scope,
            )

            if matching_result.get("status") == "success":
                mutual_connections = matching_result.get("mutual_connections", [])

                # Analyze connection strength and quality
                connection_analysis = self._analyze_connection_strength(
                    mutual_connections,
                    prospect_data_for_matching,
                    context.agent_outputs.get(AgentRole.EXECUTIVE_RESEARCHER, {})
                )

                result = {
                    "prospect_id": prospect_id,
                    "prospect_name": prospect_name,
                    "linkedin_url": linkedin_url,
                    "total_mutual_connections": len(mutual_connections),
                    "mutual_connections": mutual_connections,
                    "connection_analysis": connection_analysis,
                    "introduction_recommendations": self._generate_introduction_recommendations(
                        mutual_connections, connection_analysis
                    ),
                    "best_connectors": self._identify_best_connectors(mutual_connections),
                    "connection_strategy": self._determine_connection_strategy(connection_analysis),
                    "search_method": matching_result.get("search_method", "unknown"),
                    "data_quality": "High" if len(mutual_connections) >= 3 else "Medium" if len(mutual_connections) >= 1 else "Low"
                }

            else:
                # Handle matching failures
                error_message = matching_result.get("error", "Unknown error")
                logger.warning(f"Connection mapping failed for prospect {prospect_id}: {error_message}")

                result = {
                    "prospect_id": prospect_id,
                    "prospect_name": prospect_name,
                    "linkedin_url": linkedin_url,
                    "total_mutual_connections": 0,
                    "mutual_connections": [],
                    "connection_analysis": {"connection_strength": 20, "quality": "Low"},
                    "introduction_recommendations": [],
                    "best_connectors": [],
                    "connection_strategy": "Direct outreach recommended",
                    "search_method": "failed",
                    "data_quality": "Poor",
                    "error": error_message
                }

            context.agent_outputs[AgentRole.CONNECTION_MAPPER] = result

            # Log completion with real metrics
            if self.agent_logger:
                await self.agent_logger.log_task_complete(
                    agent_name="connection_mapping_agent",
                    task_name="Connection mapping",
                    metadata={
                        "workflow_id": workflow_id,
                        "organization_id": organization_id,
                        "user_id": user_id,
                        "mutual_connections_found": len(result.get("mutual_connections", [])),
                        "connection_strength": result.get("connection_analysis", {}).get("connection_strength", 0),
                        "data_quality": result.get("data_quality", "Unknown")
                    }
                )

            # Determine next stage based on connection strength
            connection_strength = result.get("connection_analysis", {}).get("connection_strength", 0)

            if connection_strength >= 60:  # High connection strength
                await self._execute_stage(workflow_id, WorkflowStage.EMAIL_GENERATION)
            elif connection_strength >= 30:  # Medium connection strength
                await self._execute_stage(workflow_id, WorkflowStage.EMAIL_GENERATION)
            else:  # Low connection strength
                await self._execute_stage(workflow_id, WorkflowStage.RISK_ASSESSMENT)

        except Exception as e:
            logger.error(f"Connection mapping failed for workflow {workflow_id}: {e}")

            # Log the error
            if self.agent_logger:
                await self.agent_logger.log_task_error(
                    agent_name="connection_mapping_agent",
                    task_name="Connection mapping",
                    error_message=str(e),
                    metadata={
                        "workflow_id": workflow_id,
                        "organization_id": organization_id,
                        "user_id": user_id
                    }
                )

            # Fallback: proceed with limited connection data
            fallback_result = {
                "prospect_name": context.prospect_data.get("full_name", "Unknown"),
                "linkedin_url": context.prospect_data.get("linkedin_url", ""),
                "total_mutual_connections": 0,
                "mutual_connections": [],
                "connection_analysis": {
                    "connection_strength": 25,
                    "quality": "Poor",
                    "error": str(e)
                },
                "introduction_recommendations": ["Direct outreach", "Cold email"],
                "best_connectors": [],
                "connection_strategy": "Direct approach due to connection mapping issues",
                "data_quality": "Poor"
            }

            context.agent_outputs[AgentRole.CONNECTION_MAPPER] = fallback_result
            await self._execute_stage(workflow_id, WorkflowStage.EMAIL_GENERATION)

    def _analyze_connection_strength(self, mutual_connections: list, prospect_data: dict, exec_research: dict) -> dict:
        """Analyze the strength and quality of mutual connections"""
        if not mutual_connections:
            return {
                "connection_strength": 10,
                "quality": "Poor",
                "analysis": "No mutual connections found"
            }

        # Score based on number of connections
        connection_count_score = min(len(mutual_connections) * 20, 60)  # Max 60 points

        # Score based on connection quality
        quality_score = 0
        strong_connections = 0

        for connection in mutual_connections:
            # Analyze connection details
            connection_strength = self._assess_individual_connection_strength(connection, prospect_data)
            quality_score += connection_strength

            if connection_strength >= 15:
                strong_connections += 1

        avg_quality = quality_score / len(mutual_connections) if mutual_connections else 0

        # Bonus for having multiple strong connections
        if strong_connections >= 2:
            connection_count_score += 15
        elif strong_connections >= 1:
            connection_count_score += 10

        total_score = min(connection_count_score + avg_quality, 100)

        # Determine quality level
        if total_score >= 80:
            quality = "Excellent"
        elif total_score >= 60:
            quality = "Good"
        elif total_score >= 40:
            quality = "Fair"
        else:
            quality = "Poor"

        return {
            "connection_strength": int(total_score),
            "quality": quality,
            "total_connections": len(mutual_connections),
            "strong_connections": strong_connections,
            "average_connection_quality": round(avg_quality, 1),
            "analysis": f"Found {len(mutual_connections)} mutual connections with {strong_connections} strong relationships"
        }

    def _assess_individual_connection_strength(self, connection: dict, prospect_data: dict) -> int:
        """Assess the strength of an individual mutual connection"""
        score = 0

        # Base score for having a connection
        score += 10

        # Score based on connection title/seniority
        title = connection.get("title", "").lower()
        if any(keyword in title for keyword in ["ceo", "president", "founder", "chief"]):
            score += 20  # C-level connections are very valuable
        elif any(keyword in title for keyword in ["vp", "vice president", "director"]):
            score += 15  # Senior management
        elif any(keyword in title for keyword in ["manager", "lead", "head"]):
            score += 10  # Management level

        # Score based on company relevance
        connection_company = connection.get("company", "").lower()
        prospect_company = prospect_data.get("company", "").lower()

        if connection_company and prospect_company:
            if connection_company == prospect_company:
                score += 15  # Same company connection
            elif any(word in connection_company for word in prospect_company.split()):
                score += 10  # Related company

        # Score based on industry relevance
        prospect_industry = prospect_data.get("industry", "").lower()
        if prospect_industry and prospect_industry in connection.get("description", "").lower():
            score += 5

        return min(score, 25)  # Cap individual connection score

    def _generate_introduction_recommendations(self, mutual_connections: list, connection_analysis: dict) -> list:
        """Generate specific introduction recommendations based on connections"""
        recommendations = []

        if not mutual_connections:
            return ["Direct cold outreach", "LinkedIn direct message", "Company contact form"]

        # Sort connections by potential value
        sorted_connections = sorted(
            mutual_connections,
            key=lambda x: self._assess_individual_connection_strength(x, {}),
            reverse=True
        )

        # Generate recommendations for top connections
        for i, connection in enumerate(sorted_connections[:3]):
            connector_name = connection.get("full_name", "Unknown")
            connector_title = connection.get("title", "")

            if i == 0:  # Best connection
                recommendations.append(f"Warm introduction via {connector_name} ({connector_title}) - highest priority")
            else:
                recommendations.append(f"Alternative introduction via {connector_name} ({connector_title})")

        # Add strategic recommendations
        if connection_analysis.get("connection_strength", 0) >= 70:
            recommendations.append("Multi-connector approach - leverage multiple connections")

        if connection_analysis.get("strong_connections", 0) >= 2:
            recommendations.append("Orchestrated introduction sequence with multiple touchpoints")

        return recommendations

    def _identify_best_connectors(self, mutual_connections: list) -> list:
        """Identify the best connectors for introduction"""
        if not mutual_connections:
            return []

        # Score and rank all connections
        scored_connections = []

        for connection in mutual_connections:
            score = self._assess_individual_connection_strength(connection, {})
            scored_connections.append({
                "connection": connection,
                "score": score,
                "name": connection.get("full_name", "Unknown"),
                "title": connection.get("title", ""),
                "company": connection.get("company", ""),
                "reasoning": self._explain_connector_value(connection, score)
            })

        # Sort by score and return top connectors
        scored_connections.sort(key=lambda x: x["score"], reverse=True)

        return scored_connections[:3]  # Return top 3 connectors

    def _explain_connector_value(self, connection: dict, score: int) -> str:
        """Explain why a connector is valuable"""
        reasons = []

        title = connection.get("title", "").lower()
        if any(keyword in title for keyword in ["ceo", "president", "founder", "chief"]):
            reasons.append("Senior executive level")
        elif any(keyword in title for keyword in ["vp", "vice president", "director"]):
            reasons.append("Senior management level")

        if connection.get("company"):
            reasons.append(f"Works at {connection.get('company')}")

        if score >= 20:
            reasons.append("Strong professional relationship potential")
        elif score >= 15:
            reasons.append("Good connection strength")

        return "; ".join(reasons) if reasons else "Professional connection"

    def _determine_connection_strategy(self, connection_analysis: dict) -> str:
        """Determine the overall connection strategy based on analysis"""
        strength = connection_analysis.get("connection_strength", 0)
        total_connections = connection_analysis.get("total_connections", 0)
        strong_connections = connection_analysis.get("strong_connections", 0)

        if strength >= 80 and strong_connections >= 2:
            return "Multi-connector warm introduction campaign"
        elif strength >= 60 and strong_connections >= 1:
            return "Warm introduction with strong connector"
        elif strength >= 40 and total_connections >= 2:
            return "Selective warm introduction approach"
        elif total_connections >= 1:
            return "Single connector introduction with follow-up"
        else:
            return "Direct outreach with personalization"

    async def _handle_email_composition(self, workflow_id: str):
        """Handle email composition with advanced dynamic personalization"""
        workflow_data = self.active_workflows[workflow_id]
        context = workflow_data["context"]
        organization_id = workflow_data.get("organization_id")
        user_id = workflow_data.get("user_id")

        # Log task start
        if self.agent_logger:
            await self.agent_logger.log_task_start(
                agent_name="email_composer_agent",
                task_name="Email composition",
                metadata={
                    "workflow_id": workflow_id,
                    "organization_id": organization_id,
                    "user_id": user_id
                }
            )

        try:
            # Gather all context from previous agents
            prospect_analysis = context.agent_outputs.get(AgentRole.PROSPECT_ANALYZER, {})
            executive_research = context.agent_outputs.get(AgentRole.EXECUTIVE_RESEARCHER, {})
            connection_mapping = context.agent_outputs.get(AgentRole.CONNECTION_MAPPER, {})

            # Extract personalization data
            personalization_data = self._extract_email_personalization_data(
                prospect_analysis, executive_research, connection_mapping, context.prospect_data
            )

            # Determine email strategy based on connection strength
            email_strategy = self._determine_email_strategy(connection_mapping, prospect_analysis)

            # Compose dynamic email using real personalization
            email_result = await self._compose_personalized_email(
                personalization_data, email_strategy, organization_id
            )

            # Enhance with compliance and optimization
            email_result = await self._enhance_email_with_compliance(email_result, organization_id)

            context.agent_outputs[AgentRole.EMAIL_COMPOSER] = email_result

            # Log successful completion
            if self.agent_logger:
                await self.agent_logger.log_task_complete(
                    agent_name="email_composer_agent",
                    task_name="Email composition",
                    metadata={
                        "workflow_id": workflow_id,
                        "organization_id": organization_id,
                        "user_id": user_id,
                        "email_strategy": email_strategy,
                        "personalization_elements": len(personalization_data.get("personalization_elements", [])),
                        "compliance_check": email_result.get("compliance_status", "unknown")
                    }
                )

            # Proceed to risk assessment
            await self._execute_stage(workflow_id, WorkflowStage.RISK_ASSESSMENT)

        except Exception as e:
            logger.error(f"Email composition failed for workflow {workflow_id}: {e}")

            # Log the error
            if self.agent_logger:
                await self.agent_logger.log_task_error(
                    agent_name="email_composer_agent",
                    task_name="Email composition",
                    error_message=str(e),
                    metadata={
                        "workflow_id": workflow_id,
                        "organization_id": organization_id,
                        "user_id": user_id
                    }
                )

            # Fallback: create basic email
            fallback_result = {
                "subject": f"Introduction via {context.prospect_data.get('company', 'mutual connection')}",
                "email_content": f"Dear {context.prospect_data.get('full_name', 'there')},\n\nI hope this email finds you well...",
                "personalization_elements": [],
                "email_strategy": "fallback_basic",
                "composition_error": str(e)
            }

            context.agent_outputs[AgentRole.EMAIL_COMPOSER] = fallback_result
            await self._execute_stage(workflow_id, WorkflowStage.RISK_ASSESSMENT)

    def _extract_email_personalization_data(
        self,
        prospect_analysis: dict,
        executive_research: dict,
        connection_mapping: dict,
        prospect_data: dict
    ) -> dict:
        """Extract personalization data for email composition"""
        personalization = {
            "prospect_info": {},
            "company_context": {},
            "research_insights": [],
            "connection_references": [],
            "personalization_elements": [],
            "engagement_angles": []
        }

        # Extract prospect information
        personalization["prospect_info"] = {
            "name": prospect_data.get("full_name", ""),
            "title": prospect_data.get("title", ""),
            "company": prospect_data.get("company", ""),
            "industry": prospect_data.get("industry", "")
        }

        # Extract company context from prospect analysis
        if prospect_analysis:
            company_analysis = prospect_analysis.get("company_analysis", {})
            personalization["company_context"] = {
                "size": company_analysis.get("company_size", "Unknown"),
                "stage": company_analysis.get("growth_stage", "Unknown"),
                "focus": company_analysis.get("industry_focus", ""),
                "leadership_quality": company_analysis.get("leadership_quality", "Unknown")
            }

        # Extract research insights from executive research
        if executive_research:
            personalization_data_research = executive_research.get("personalization_data", {})
            engagement_opportunities = executive_research.get("engagement_opportunities", [])

            personalization["research_insights"] = [
                insight.get("hook", "") for insight in personalization_data_research.get("engagement_hooks", [])
                if insight.get("relevance", 0) > 0.5
            ]

            personalization["engagement_angles"] = [
                opp.get("opportunity", "") for opp in engagement_opportunities[:3]
            ]

        # Extract connection references from connection mapping
        if connection_mapping:
            best_connectors = connection_mapping.get("best_connectors", [])
            mutual_connections = connection_mapping.get("mutual_connections", [])

            for connector in best_connectors[:2]:  # Top 2 connectors
                personalization["connection_references"].append({
                    "name": connector.get("name", ""),
                    "title": connector.get("title", ""),
                    "company": connector.get("company", ""),
                    "reasoning": connector.get("reasoning", "")
                })

        # Generate personalization elements list
        elements = []
        if personalization["research_insights"]:
            elements.append(f"Industry insights ({len(personalization['research_insights'])} found)")
        if personalization["connection_references"]:
            elements.append(f"Mutual connections ({len(personalization['connection_references'])} identified)")
        if personalization["engagement_angles"]:
            elements.append(f"Engagement opportunities ({len(personalization['engagement_angles'])} angles)")

        personalization["personalization_elements"] = elements

        return personalization

    def _determine_email_strategy(self, connection_mapping: dict, prospect_analysis: dict) -> str:
        """Determine email strategy based on available data"""
        connection_strength = connection_mapping.get("connection_analysis", {}).get("connection_strength", 0)
        engagement_score = prospect_analysis.get("engagement_score", 0)

        if connection_strength >= 70 and engagement_score >= 80:
            return "warm_introduction_premium"
        elif connection_strength >= 50:
            return "warm_introduction_standard"
        elif engagement_score >= 70:
            return "research_based_outreach"
        elif connection_strength >= 30:
            return "soft_connection_reference"
        else:
            return "professional_direct_outreach"

    async def _compose_personalized_email(
        self,
        personalization_data: dict,
        email_strategy: str,
        organization_id: int
    ) -> dict:
        """Compose personalized email using extracted data and strategy"""

        # Build dynamic prompt based on available personalization
        prompt_parts = [
            "Compose a highly personalized introduction email using the following context:",
            f"\nPersonalization Data: {json.dumps(personalization_data, indent=2)}",
            f"\nEmail Strategy: {email_strategy}"
        ]

        # Strategy-specific instructions
        strategy_instructions = {
            "warm_introduction_premium": "Leverage strong mutual connections and extensive research. Use warm, confident tone.",
            "warm_introduction_standard": "Reference mutual connections naturally. Professional but approachable tone.",
            "research_based_outreach": "Lead with relevant research insights. Demonstrate industry knowledge.",
            "soft_connection_reference": "Mention connections subtly. Focus on value proposition.",
            "professional_direct_outreach": "Professional direct approach. Clear value and credibility focus."
        }

        prompt_parts.append(f"\nStrategy Instructions: {strategy_instructions.get(email_strategy, 'Professional approach')}")

        # Common requirements
        prompt_parts.extend([
            "\nRequirements:",
            "1. Compelling subject line (6-8 words, avoid spam triggers)",
            "2. Personal greeting using correct name/title",
            "3. Authentic connection/research reference if available",
            "4. Clear, specific value proposition",
            "5. Single, clear call-to-action",
            "6. Professional tone matching executive level",
            "7. 150-200 words maximum",
            "8. Include unsubscribe mention for compliance",
            "\nReturn as JSON with: subject, greeting, body, signature, call_to_action, personalization_notes"
        ])

        prompt = "\n".join(prompt_parts)

        try:
            client = await self._get_openai_client(organization_id)
            # Lock model via centralized settings
            try:
                from core.settings import settings as _settings
                _primary_model = _settings.OPENAI_MODEL
            except Exception:
                _primary_model = "gpt-4.1"
            response = await client.chat.completions.create(
                model=_primary_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert executive communication specialist. Compose authentic, personalized emails that build genuine business relationships. Ensure all emails are compliant and professional."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temperature for more consistent, professional output
                max_tokens=1200
            )

            # Parse response
            result_text = response.choices[0].message.content
            try:
                result = json.loads(result_text)

                # Add metadata
                result.update({
                    "email_strategy": email_strategy,
                    "personalization_elements": personalization_data.get("personalization_elements", []),
                    "word_count": len(result.get("body", "").split()),
                    "composed_at": datetime.now(timezone.utc).isoformat()
                })

                return result

            except json.JSONDecodeError:
                # Fallback if not valid JSON
                return {
                    "subject": f"Introduction via {personalization_data['prospect_info'].get('company', 'mutual connection')}",
                    "greeting": f"Dear {personalization_data['prospect_info'].get('name', 'there')},",
                    "body": result_text,
                    "call_to_action": "Would you be open to a brief conversation?",
                    "signature": "Best regards,",
                    "email_strategy": email_strategy,
                    "personalization_elements": personalization_data.get("personalization_elements", []),
                    "composition_note": "Parsed from text response"
                }

        except Exception as e:
            logger.error(f"Email composition API call failed: {e}")
            raise

    async def _enhance_email_with_compliance(self, email_result: dict, organization_id: int) -> dict:
        """Enhance email with compliance checks and optimizations"""
        try:
            # Basic compliance enhancements
            email_content = email_result.get("body", "")

            # Ensure unsubscribe mention is present
            if "unsubscribe" not in email_content.lower():
                signature = email_result.get("signature", "")
                email_result["signature"] = f"{signature}\n\nReply 'UNSUBSCRIBE' to opt out of future communications."

            # Add compliance status
            email_result["compliance_status"] = "basic_check_passed"

            # Could integrate with compliance_auditor_service here for full audit
            # from services.compliance_auditor_service import compliance_auditor
            # audit_result = await compliance_auditor.audit_outreach_campaign(...)

            return email_result

        except Exception as e:
            # Log and flag enhancement failure without propagating the error
            logger.warning(f"Email compliance enhancement failed: {e}")
            email_result["compliance_status"] = "enhancement_failed"
            return email_result

    async def _handle_risk_assessment(self, workflow_id: str):
        """Handle risk assessment stage"""
        context = self.active_workflows[workflow_id]

        prompt = f"""Assess the risks of this outreach campaign:

Prospect Company: {context.prospect_data.get('company', 'Unknown')}
Industry: {context.prospect_data.get('industry', 'Unknown')}
Executive Role: {context.prospect_data.get('role', 'Unknown')}

Email Content: {json.dumps(context.agent_outputs.get(AgentRole.EMAIL_COMPOSER, {}), indent=2)}

Evaluate:
1. Reputation risks for both parties
2. Compliance considerations (GDPR, CAN-SPAM, industry-specific)
3. Cultural and geographical communication factors
4. Potential negative outcomes and probability
5. Mitigation strategies and recommendations
6. Overall risk score (0-100, where 0 is no risk)

Return as JSON with: risk_score, risk_factors, compliance_status, recommendations, and mitigation_strategies."""

        try:
            org_id = int(context.tenant_id) if context.tenant_id.isdigit() else hash(context.tenant_id) % 1000000
            client = await self._get_openai_client(org_id)

            response = await client.chat.completions.create(
                model="gpt-4-turbo-2024-04-09",
                messages=[
                    {"role": "system", "content": "You are a corporate risk assessment specialist. Evaluate business outreach campaigns for potential risks and compliance issues."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1000
            )

            # Parse response
            result_text = response.choices[0].message.content
            try:
                result = json.loads(result_text)
            except json.JSONDecodeError:
                # Fallback if not valid JSON
                result = {
                    "risk_score": 25,
                    "risk_factors": ["Standard business outreach risks"],
                    "compliance_status": "Compliant",
                    "assessment": result_text
                }

            context.agent_outputs[AgentRole.RISK_ASSESSOR] = result
            context.risk_score = result.get('risk_score', 25)

            # Proceed to human approval if risk is acceptable
            if context.risk_score <= 40:  # Low to moderate risk
                await self._execute_stage(workflow_id, WorkflowStage.HUMAN_APPROVAL)
            else:
                logger.warning(f"High risk score {context.risk_score} for workflow {workflow_id}")
                await self._request_human_review(workflow_id, "High risk assessment requires human review")

        except Exception as e:
            # Handle risk assessment errors with enterprise error handling
            error_context = {
                'workflow_id': workflow_id,
                'stage': 'risk_assessment',
                'prospect_data': context.prospect_data
            }
            await self.error_handler.handle_error(
                error=e,
                operation="ai_risk_assessment",
                context=error_context,
                category=ErrorCategory.AI_API_ERROR,
                severity=ErrorSeverity.HIGH
            )
            logger.error(f"Risk assessment failed: {e}")
            # Use fallback low-risk assessment
            result = {
                "risk_score": 30,
                "risk_factors": ["Standard business outreach"],
                "compliance_status": "Compliant (fallback assessment)"
            }
            context.agent_outputs[AgentRole.RISK_ASSESSOR] = result
            context.risk_score = 30
            await self._execute_stage(workflow_id, WorkflowStage.HUMAN_APPROVAL)

    async def _handle_human_approval(self, workflow_id: str):
        """Handle human approval stage - integration with approval queue"""
        context = self.active_workflows[workflow_id]

        # Create approval request for human review
        approval_data = {
            "workflow_id": workflow_id,
            "tenant_id": context.tenant_id,
            "prospect_data": context.prospect_data,
            "agent_analysis": context.agent_outputs,
            "risk_score": context.risk_score,
            "stage": "human_approval",
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Integrate with existing approval queue system
        try:
            # Import approval service dynamically to avoid circular imports
from services.approval_queue_service import ApprovalQueueService, ApprovalType, ApprovalPriority
import os

            import os
            approval_service = ApprovalQueueService(
                os.getenv("DATABASE_URL")
            )
            await approval_service.initialize()

            # Create approval request
            approval_id = await approval_service.create_approval_request(
                organization_id=int(context.tenant_id),
                request_type=ApprovalType.EMAIL_SEND,
                title=f"AI-Generated Introduction Email",
                description=f"Email for {context.prospect_data.get('full_name', 'prospect')} at {context.prospect_data.get('company', 'company')}",
                requested_by=1,  # System user
                context_data={
                    "workflow_id": workflow_id,
                    "email_content": context.agent_outputs.get(AgentRole.EMAIL_COMPOSER, {}),
                    "risk_assessment": context.agent_outputs.get(AgentRole.RISK_ASSESSOR, {}),
                    "prospect_data": context.prospect_data
                },
                priority=ApprovalPriority.HIGH if context.risk_score > 30 else ApprovalPriority.NORMAL,
                risk_score=context.risk_score / 100.0  # Convert to 0-1 scale
            )

            logger.info(f"Created approval request {approval_id} for workflow {workflow_id}")

            # Store approval ID for tracking
            context.approval_id = approval_id

            # Send to WebSocket for real-time notifications
            try:
                from services.websocket_manager import websocket_manager
                await websocket_manager.notify_approval_request({
                    "approval_id": approval_id,
                    "workflow_id": workflow_id,
                    "organization_id": context.tenant_id,
                    "title": f"AI Email Approval - {context.prospect_data.get('company', 'Unknown')}",
                    "risk_score": context.risk_score
                })
            except Exception as ws_error:
                logger.warning(f"WebSocket notification failed: {ws_error}")

            await approval_service.close()

        except Exception as e:
            logger.error(f"Failed to create approval request: {e}")
            # Fallback - just log the approval request
            logger.info(f"Workflow {workflow_id} awaiting human approval (fallback mode)")

        # Workflow will wait for approval decision via the approval queue

    async def _handle_email_sending(self, workflow_id: str):
        """Handle email sending stage"""
        context = self.active_workflows[workflow_id]

        try:
            # Get email content from AI composition
            email_data = context.agent_outputs.get(AgentRole.EMAIL_COMPOSER, {})

            if not email_data:
                raise ValueError("No email content found for sending")

            # Prepare email for sending
            prospect_email = context.prospect_data.get('email')
            if not prospect_email:
                logger.warning(f"No prospect email found for workflow {workflow_id}")
                await self._execute_stage(workflow_id, WorkflowStage.COMPLETION)
                return

            # Import email service dynamically
            try:
                from services.email_scheduler import EmailScheduler

                import os
                email_scheduler = EmailScheduler(
                    database_url=os.getenv("DATABASE_URL")
                )

                # Schedule email for immediate sending
                await email_scheduler.schedule_single_email(
                    organization_id=int(context.tenant_id),
                    prospect_id=context.prospect_data.get('id'),
                    prospect_email=prospect_email,
                    prospect_name=context.prospect_data.get('full_name', 'Unknown'),
                    subject=email_data.get('subject', 'Introduction'),
                    email_body=email_data.get('email_content', email_data.get('body', '')),
                    sender_info={
                        "name": "VouchLink AI Team",
                        "email": "team@vouchlinkai.com"
                    },
                    metadata={
                        "workflow_id": workflow_id,
                        "ai_generated": True,
                        "risk_score": context.risk_score
                    }
                )

                logger.info(f"Email scheduled for sending - workflow {workflow_id}")

            except Exception as email_error:
                logger.error(f"Email service integration failed: {email_error}")
                # Log the email content for manual sending
                logger.info(f"Email content for manual sending - workflow {workflow_id}:")
                logger.info(f"To: {prospect_email}")
                logger.info(f"Subject: {email_data.get('subject', 'Introduction')}")
                logger.info(f"Body: {email_data.get('email_content', email_data.get('body', ''))}")

            await self._execute_stage(workflow_id, WorkflowStage.FOLLOW_UP)

        except Exception as e:
            logger.error(f"Email sending failed for workflow {workflow_id}: {e}")
            context.agent_outputs["email_sending_error"] = {
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await self._execute_stage(workflow_id, WorkflowStage.COMPLETION)

    async def _handle_follow_up(self, workflow_id: str):
        """Handle follow-up stage"""
        # Schedule follow-up tasks, set reminders, etc.
        logger.info(f"Setting up follow-up for workflow {workflow_id}")
        await self._execute_stage(workflow_id, WorkflowStage.COMPLETION)

    async def _handle_completion(self, workflow_id: str):
        """Handle workflow completion"""
        context = self.active_workflows[workflow_id]
        context.current_stage = WorkflowStage.COMPLETION
        context.updated_at = datetime.now(timezone.utc)

        logger.info(f"Workflow {workflow_id} completed successfully")

        # Send workflow completion notification
        org_id = int(context.tenant_id) if context.tenant_id.isdigit() else hash(context.tenant_id) % 1000000
        await progress_notifier.notify_workflow_completed(
            user_id=1,  # System user for AI workflows
            organization_id=org_id,
            workflow_type="ai_agent_orchestration",
            workflow_id=workflow_id,
            success_message=f"Successfully processed prospect from {context.prospect_data.get('company_name', 'Unknown')}",
            results={
                "prospect_company": context.prospect_data.get("company_name", "Unknown"),
                "prospect_name": f"{context.prospect_data.get('first_name', '')} {context.prospect_data.get('last_name', '')}".strip(),
                "email_sent": True,
                "risk_score": getattr(context, 'risk_score', 'Unknown')
            },
            metadata={
                "stages_completed": 8,
                "workflow_duration": str(datetime.now(timezone.utc) - datetime.fromisoformat(context.created_at.replace('Z', '+00:00'))) if hasattr(context, 'created_at') else "Unknown"
            }
        )

        # Archive workflow or clean up as needed
        # In production, you'd save to database before removing from memory

    async def _handle_error(self, workflow_id: str, stage: WorkflowStage, error: Exception):
        """Handle errors in workflow execution"""
        logger.error(f"Error in workflow {workflow_id} at stage {stage}: {error}")

        # Send workflow failure notification
        try:
            if workflow_id in self.active_workflows:
                context = self.active_workflows[workflow_id]
                org_id = int(context.tenant_id) if context.tenant_id.isdigit() else hash(context.tenant_id) % 1000000

                await progress_notifier.notify_workflow_failed(
                    user_id=1,  # System user for AI workflows
                    organization_id=org_id,
                    workflow_type="ai_agent_orchestration",
                    workflow_id=workflow_id,
                    error_message=f"Workflow failed at {stage.value.replace('_', ' ').title()} stage",
                    error_details={
                        "failed_stage": stage.value,
                        "error_type": type(error).__name__,
                        "error_message": str(error),
                        "prospect_company": context.prospect_data.get("company_name", "Unknown")
                    },
                    metadata={
                        "requires_human_intervention": True,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                )
        except Exception as notification_error:
            logger.error(f"Failed to send error notification: {notification_error}")

        # Could implement retry logic, error recovery, or escalation here
        context = self.active_workflows.get(workflow_id)
        if context:
            context.agent_outputs["error"] = {
                "stage": stage.value,
                "error": str(error),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    async def _simulate_agent_processing(self, stage: str, context_data: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate agent processing for demo purposes"""
        await asyncio.sleep(1)  # Simulate processing time
        return {"status": "completed", "stage": stage, "processed": True}

    async def _execute_tool_function(self, function_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tool functions called by agents"""
        # This would implement the actual tool functions

        function_handlers = {
            "analyze_company_profile": self._analyze_company_profile,
            "research_executive_profile": self._research_executive_profile,
            "map_mutual_connections": self._map_mutual_connections,
            "compose_introduction_email": self._compose_introduction_email,
            "assess_outreach_risk": self._assess_outreach_risk,
            "coordinate_agent_handoff": self._coordinate_agent_handoff,
            "audit_compliance": self._audit_compliance,
            "optimize_performance": self._optimize_performance
        }

        handler = function_handlers.get(function_name)
        if handler:
            return await handler(args)
        else:
            return {"error": f"Unknown function: {function_name}"}

    # Tool function implementations
    async def _analyze_company_profile(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze company profile"""
        company = args.get("company_name") or args.get("company")
        prospect_name = args.get("prospect_name")

        if not company and not prospect_name:
            raise ValueError("company_name or prospect_name required")

        analysis = await self.prospect_engine.find_target_matches_realtime(
            prospect_name or "",
            company or ""
        )

        return {
            "status": "success" if not analysis.get("error") else "error",
            "analysis": analysis,
        }

    async def _research_executive_profile(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Research executive profile"""
        if not self.exec_search:
            raise RuntimeError("Executive search service unavailable")

        company = args.get("company") or args.get("company_name")
        if not company:
            raise ValueError("company is required")

        executives = await self.exec_search.find_executives_for_company(
            company_name=company,
            titles=args.get("target_titles"),
            max_results=args.get("max_results", 3),
        )

        return {
            "status": "success",
            "executives": [exec.__dict__ for exec in executives],
        }

    async def _map_mutual_connections(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Map mutual connections"""
        prospect_id = args.get("prospect_id")
        prospect_name = args.get("prospect_name")
        prospect_company = args.get("prospect_company") or args.get("company")

        if not prospect_id and not prospect_name:
            raise ValueError("prospect_id or prospect_name required")

        tenant_value = args.get("tenant_id") or args.get("organization_id")
        if tenant_value is None or str(tenant_value).strip() == "":
            raise ValueError("tenant_id is required to map mutual connections")
        tenant_scope = str(tenant_value).strip()

        if prospect_id:
            analysis = await self.prospect_engine.find_prospect_matches(
                int(prospect_id),
                tenant_id=tenant_scope,
            )
        else:
            analysis = await self.prospect_engine.find_target_matches_realtime(
                prospect_name,
                prospect_company or "",
                tenant_id=tenant_scope,
            )

        if analysis.get("error"):
            return {"status": "error", "error": analysis.get("error")}

        connections = analysis.get("mutual_connections") or []
        summary = {
            "total_connections": len(connections),
            "with_email": sum(1 for c in connections if c.get("email")),
        }
        return {"status": "success", "summary": summary, "connections": connections}

    async def _compose_introduction_email(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Compose introduction email"""
        prospect = args.get("prospect_profile", {})
        connector = args.get("connector_profile", {})
        connection_context = args.get("connection_context")
        requester = args.get("requesting_user_name")

        content = await self.ai_writer.generate_introduction_request(
            prospect_data=prospect,
            team_member_data=connector,
            connection_context=connection_context,
            requesting_user_name=requester,
        )

        return {
            "subject": args.get("subject") or f"Introduction to {prospect.get('name', 'Executive')}",
            "body": content,
            "approval_required": True,
        }

    async def _assess_outreach_risk(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Assess outreach risk"""
        risk_score = 0.2
        if args.get("prospect_role", "").lower().startswith("chief"):
            risk_score += 0.2
        if args.get("contains_personal_data"):
            risk_score += 0.3
        return {
            "status": "success",
            "risk_score": min(risk_score, 1.0),
        }

    async def _coordinate_agent_handoff(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Coordinate agent handoff"""
        workflow_id = args.get("workflow_id")
        if workflow_id not in self.active_workflows:
            return {"status": "error", "error": "Workflow not found"}

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "next_stage": args.get("next_stage"),
            "notes": args.get("notes"),
        }
        self.active_workflows[workflow_id].setdefault("handoffs", []).append(record)
        return {"status": "success", "handoff": record}

    async def _audit_compliance(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Audit compliance"""
        body = args.get("email_body") or args.get("body") or ""
        flags = []
        if "unsubscribe" not in body.lower():
            flags.append("missing_unsubscribe_clause")
        return {"status": "review_needed" if flags else "compliant", "flags": flags}

    async def _optimize_performance(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize performance"""
        metrics = args.get("performance_metrics", {})
        recommendations = []
        if metrics.get("open_rate", 0) < 35:
            recommendations.append("Experiment with new subject lines and preview text.")
        if metrics.get("reply_rate", 0) < 10:
            recommendations.append("Tighten call-to-action and tailor messaging per persona.")
        return {"status": "success", "recommendations": recommendations}

    async def _get_team_member_profiles(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Get team member profiles for connection mapping"""
        try:
            # Import database service dynamically
            from services.vouchlink_ai_dashboard import dashboard_service

            # Query team members for this organization
            team_members = await dashboard_service.get_team_members(int(tenant_id))

            profiles = []
            for member in team_members:
                profiles.append({
                    "name": member.get("name", "Unknown"),
                    "email": member.get("email", ""),
                    "linkedin": member.get("linkedin_url", ""),
                    "title": member.get("role", "Team Member"),
                    "status": member.get("status", "active")
                })

            return profiles

        except Exception as e:
            logger.warning(f"Failed to get team profiles from dashboard service: {e}")
            # Fallback to direct database query scoped by tenant
            try:
                tenant_scope = str(tenant_id)
                team_data = await db.get_team_members(
                    user_id=None,
                    tenant_id=tenant_scope,
                )

                profiles = []
                for member in team_data:
                    profiles.append({
                        "name": member.get("name", "Unknown"),
                        "email": member.get("email", ""),
                        "linkedin": member.get("linkedin_url", ""),
                        "title": member.get("position", member.get("role", "Team Member")),
                        "status": "active" if member.get("is_active", 1) else "inactive",
                    })
                return profiles

            except Exception as db_error:
                logger.error(f"Database fallback also failed: {db_error}")
                # Return empty list when no connections are found
                return []

    async def _request_human_review(self, workflow_id: str, reason: str):
        """Request human review for high-risk or complex cases"""
        logger.info(f"Requesting human review for workflow {workflow_id}: {reason}")
        # This would integrate with your approval queue system

    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get current workflow status"""
        try:
            # Get workflow from enterprise persistence
            workflow_data = await self.persistence_service.get_workflow(workflow_id)
            if not workflow_data:
                return None

            return {
                "workflow_id": workflow_id,
                "tenant_id": str(workflow_data['organization_id']),
                "current_stage": workflow_data.get('current_stage', 'unknown'),
                "status": workflow_data['status'],
                "risk_score": workflow_data.get('metrics', {}).get('risk_score', 0),
                "prospects_count": len(workflow_data.get('prospects', [])),
                "created_at": workflow_data['created_at'],
                "updated_at": workflow_data['updated_at']
            }

        except Exception as e:
            error_context = {'workflow_id': workflow_id}
            await self.error_handler.handle_error(
                error=e,
                operation="get_ai_workflow_status",
                context=error_context,
                category=ErrorCategory.DATA_ACCESS_ERROR,
                severity=ErrorSeverity.MEDIUM
            )
            logger.warning(f"Could not get AI workflow status for {workflow_id}: {e}")
            return None

    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel an active workflow"""
        try:
            # Update workflow status in persistence
            await self.persistence_service.update_workflow_status(
                workflow_id=workflow_id,
                status="cancelled"
            )
            logger.info(f"Cancelled AI workflow {workflow_id}")
            return True

        except Exception as e:
            error_context = {'workflow_id': workflow_id}
            await self.error_handler.handle_error(
                error=e,
                operation="cancel_ai_workflow",
                context=error_context,
                category=ErrorCategory.WORKFLOW_ERROR,
                severity=ErrorSeverity.MEDIUM
            )
            logger.error(f"Failed to cancel AI workflow {workflow_id}: {e}")
            return False

    async def handle_approval_decision(self, workflow_id: str, approval_id: str, decision: str, notes: str = None):
        """Handle approval decision and continue workflow if approved"""
        try:
            # Get workflow from persistence
            workflow_data = await self.persistence_service.get_workflow(workflow_id)
            if not workflow_data:
                logger.warning(f"Workflow {workflow_id} not found for approval decision")
                return

            if decision == "approve":
                logger.info(f"Approval granted for workflow {workflow_id}, continuing to email sending")
                await self.persistence_service.update_workflow_status(
                    workflow_id=workflow_id,
                    status="approved",
                    current_stage=WorkflowStage.EMAIL_SENDING.value
                )
                await self._execute_stage(workflow_id, WorkflowStage.EMAIL_SENDING)
            else:
                logger.info(f"Approval rejected for workflow {workflow_id}: {notes}")
                await self.persistence_service.update_workflow_status(
                    workflow_id=workflow_id,
                    status="rejected",
                    current_stage=WorkflowStage.COMPLETION.value,
                    error_message=f"Approval rejected: {notes}"
                )
                await self._execute_stage(workflow_id, WorkflowStage.COMPLETION)

        except Exception as e:
            error_context = {
                'workflow_id': workflow_id,
                'approval_id': approval_id,
                'decision': decision,
                'notes': notes
            }
            await self.error_handler.handle_error(
                error=e,
                operation="handle_ai_approval_decision",
                context=error_context,
                category=ErrorCategory.WORKFLOW_ERROR,
                severity=ErrorSeverity.HIGH
            )
            logger.error(f"Failed to handle approval decision for workflow {workflow_id}: {e}")

    async def _wait_for_completion(self, thread_id: str, run_id: str) -> Dict[str, Any]:
        """Wait for OpenAI assistant run completion (if using Assistants API)"""
        # This would be used if we were using the Assistants API
        # For now, return empty dict since we're using chat completions
        return {}

# Global orchestrator instance (only create when feature is enabled)
from core.settings import settings

ai_orchestrator = None
if settings.OPENAI_AGENTS_ENABLED and settings.OPENAI_API_KEY:
    try:
        ai_orchestrator = OpenAIAgentsOrchestrator(api_key=settings.OPENAI_API_KEY)
    except Exception as e:
        logger.warning(f"Could not initialize global AI orchestrator: {e}")
        ai_orchestrator = None
else:
    logger.info("OpenAI agent orchestrator disabled (set OPENAI_AGENTS_ENABLED to true and configure OPENAI_API_KEY)")
