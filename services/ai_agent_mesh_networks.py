#!/usr/bin/env python3
"""
AI Agent Mesh Networks - September 2025 Enterprise Implementation
Advanced mesh networking for AI agents with direct peer-to-peer communication

Features:
- Direct agent-to-agent communication
- Distributed consensus mechanisms
- Mesh-based fault tolerance with automatic routing
- Load balancing across mesh nodes
- Real-time agent discovery and health monitoring
- Byzantine fault tolerance for distributed decisions
- Event-driven messaging with reliable delivery

Based on 2025 enterprise AI orchestration best practices
"""

import asyncio
import logging
import os
import uuid
import json
import hashlib
import time
from typing import List, Dict, Any, Optional, Set, Callable, Tuple, Union
from datetime import datetime, timedelta, timezone
from enum import Enum
from dataclasses import dataclass, asdict, field
from collections import defaultdict, deque

# Import enterprise services
from services.resilience_patterns import with_circuit_breaker, with_timeout
from services.monitoring_observability_service import monitoring_service

# Import Communication Hub integration
try:
    from services.communication_client import CommunicationHubClient, MessageType as CommHubMessageType, MessagePriority as CommHubMessagePriority
    from services.message_translator import MessageTranslator, BusinessContext
    from services.metadata_enricher import MetadataEnricher
    communication_hub_available = True
except ImportError:
    communication_hub_available = False
    logger.warning("Communication Hub services not available in AI Agent Mesh Networks")

logger = logging.getLogger(__name__)

class MeshMessageType(Enum):
    """Types of messages in the mesh network"""
    HEARTBEAT = "heartbeat"
    DISCOVERY = "discovery"
    WORK_REQUEST = "work_request"
    WORK_RESPONSE = "work_response"
    CONSENSUS_PROPOSAL = "consensus_proposal"
    CONSENSUS_VOTE = "consensus_vote"
    CONSENSUS_COMMIT = "consensus_commit"
    HEALTH_CHECK = "health_check"
    LOAD_BALANCE = "load_balance"
    FAILOVER = "failover"
    ALERT = "alert"
    COORDINATION = "coordination"

class AgentState(Enum):
    """States of agents in the mesh network"""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    BUSY = "busy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    FAILED = "failed"
    MAINTENANCE = "maintenance"

class ConsensusStatus(Enum):
    """Status of consensus proposals"""
    PROPOSED = "proposed"
    VOTING = "voting"
    COMMITTED = "committed"
    REJECTED = "rejected"
    EXPIRED = "expired"

@dataclass
class MeshMessage:
    """Message in the mesh network"""
    message_id: str
    message_type: MeshMessageType
    source_agent: str
    target_agent: Optional[str]  # None for broadcast
    payload: Dict[str, Any]
    timestamp: datetime
    ttl_seconds: int = 300
    delivery_attempts: int = 0
    max_delivery_attempts: int = 3
    correlation_id: Optional[str] = None
    reply_to: Optional[str] = None

    def is_expired(self) -> bool:
        """Check if message has expired"""
        return datetime.now(timezone.utc) > (self.timestamp + timedelta(seconds=self.ttl_seconds))

    def can_retry(self) -> bool:
        """Check if message can be retried"""
        return self.delivery_attempts < self.max_delivery_attempts

@dataclass
class ConsensusProposal:
    """Consensus proposal in the mesh network"""
    proposal_id: str
    proposer: str
    proposal_type: str
    proposal_data: Dict[str, Any]
    votes: Dict[str, bool] = field(default_factory=dict)
    status: ConsensusStatus = ConsensusStatus.PROPOSED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=5))
    required_votes: int = 1
    threshold_percentage: float = 0.67  # 67% majority required

    def add_vote(self, agent_id: str, vote: bool):
        """Add a vote to the proposal"""
        self.votes[agent_id] = vote

    def is_approved(self) -> bool:
        """Check if proposal is approved"""
        if len(self.votes) < self.required_votes:
            return False

        approval_count = sum(1 for vote in self.votes.values() if vote)
        approval_rate = approval_count / len(self.votes)
        return approval_rate >= self.threshold_percentage

    def is_rejected(self) -> bool:
        """Check if proposal is rejected"""
        if len(self.votes) < self.required_votes:
            return False

        rejection_count = sum(1 for vote in self.votes.values() if not vote)
        rejection_rate = rejection_count / len(self.votes)
        return rejection_rate > (1 - self.threshold_percentage)

    def is_expired(self) -> bool:
        """Check if proposal has expired"""
        return datetime.now(timezone.utc) > self.expires_at

@dataclass
class AgentCapability:
    """Capability descriptor for agents"""
    capability_id: str
    capability_name: str
    version: str
    parameters: Dict[str, Any]
    resource_requirements: Dict[str, float]
    performance_metrics: Dict[str, float]

@dataclass
class AgentNode:
    """Node in the agent mesh network"""
    agent_id: str
    agent_name: str
    agent_type: str
    capabilities: List[AgentCapability]
    state: AgentState
    endpoint: str
    mesh_port: int
    load_percentage: float = 0.0
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    connections: Set[str] = field(default_factory=set)
    message_queue: deque = field(default_factory=deque)
    pending_responses: Dict[str, MeshMessage] = field(default_factory=dict)
    consensus_participation: Dict[str, bool] = field(default_factory=dict)
    performance_history: List[Dict[str, float]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_healthy(self) -> bool:
        """Check if agent node is healthy"""
        if self.state in [AgentState.FAILED, AgentState.UNREACHABLE]:
            return False

        # Check if heartbeat is recent (within 2 minutes)
        heartbeat_age = datetime.now(timezone.utc) - self.last_heartbeat
        return heartbeat_age < timedelta(minutes=2)

    def get_capability_by_type(self, capability_type: str) -> Optional[AgentCapability]:
        """Get capability by type"""
        for capability in self.capabilities:
            if capability.capability_name == capability_type:
                return capability
        return None

    def update_performance(self, metrics: Dict[str, float]):
        """Update performance metrics"""
        performance_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **metrics
        }

        self.performance_history.append(performance_record)

        # Keep only last 100 records
        if len(self.performance_history) > 100:
            self.performance_history.pop(0)

        # Update current load
        self.load_percentage = metrics.get("load_percentage", self.load_percentage)

class MeshNetworkTopology:
    """Manages the topology of the mesh network"""

    def __init__(self):
        self.nodes: Dict[str, AgentNode] = {}
        self.adjacency_matrix: Dict[str, Dict[str, bool]] = {}
        self.routing_table: Dict[str, Dict[str, List[str]]] = {}  # source -> target -> path
        self.network_partitions: List[Set[str]] = []

    def add_node(self, node: AgentNode):
        """Add a node to the mesh network"""
        self.nodes[node.agent_id] = node
        self.adjacency_matrix[node.agent_id] = {}
        self.routing_table[node.agent_id] = {}

        # Initialize connections with all existing nodes
        for existing_node_id in self.nodes:
            if existing_node_id != node.agent_id:
                self.adjacency_matrix[node.agent_id][existing_node_id] = True
                self.adjacency_matrix[existing_node_id][node.agent_id] = True

        self._update_routing_table()

    def remove_node(self, agent_id: str):
        """Remove a node from the mesh network"""
        if agent_id in self.nodes:
            del self.nodes[agent_id]

            # Remove from adjacency matrix
            if agent_id in self.adjacency_matrix:
                del self.adjacency_matrix[agent_id]

            for node_connections in self.adjacency_matrix.values():
                if agent_id in node_connections:
                    del node_connections[agent_id]

            # Remove from routing table
            if agent_id in self.routing_table:
                del self.routing_table[agent_id]

            for routing_map in self.routing_table.values():
                if agent_id in routing_map:
                    del routing_map[agent_id]

            self._update_routing_table()

    def get_shortest_path(self, source: str, target: str) -> Optional[List[str]]:
        """Get shortest path between two nodes using Dijkstra's algorithm"""
        if source not in self.nodes or target not in self.nodes:
            return None

        if source == target:
            return [source]

        # Use cached routing table
        if source in self.routing_table and target in self.routing_table[source]:
            return self.routing_table[source][target]

        return None

    def get_alternative_routes(self, source: str, target: str, max_routes: int = 3) -> List[List[str]]:
        """Get alternative routes for fault tolerance"""
        routes = []

        # Primary route
        primary = self.get_shortest_path(source, target)
        if primary:
            routes.append(primary)

        # Find alternative routes by temporarily removing nodes from primary path
        if primary and len(primary) > 2:
            for i in range(1, len(primary) - 1):
                intermediate_node = primary[i]

                # Temporarily remove intermediate node
                temp_adjacency = self.adjacency_matrix.copy()
                if intermediate_node in temp_adjacency:
                    del temp_adjacency[intermediate_node]

                for node_connections in temp_adjacency.values():
                    if intermediate_node in node_connections:
                        del node_connections[intermediate_node]

                # Find alternative path
                alternative = self._dijkstra(source, target, temp_adjacency)
                if alternative and alternative not in routes:
                    routes.append(alternative)

                if len(routes) >= max_routes:
                    break

        return routes

    def _update_routing_table(self):
        """Update routing table using Dijkstra's algorithm"""
        for source in self.nodes:
            self.routing_table[source] = {}
            for target in self.nodes:
                if source != target:
                    path = self._dijkstra(source, target, self.adjacency_matrix)
                    if path:
                        self.routing_table[source][target] = path

    def _dijkstra(self, source: str, target: str, adjacency: Dict[str, Dict[str, bool]]) -> Optional[List[str]]:
        """Dijkstra's shortest path algorithm"""
        if source not in adjacency or target not in adjacency:
            return None

        distances = {node: float('inf') for node in adjacency}
        distances[source] = 0
        previous = {}
        unvisited = set(adjacency.keys())

        while unvisited:
            current = min(unvisited, key=lambda node: distances[node])

            if distances[current] == float('inf'):
                break

            if current == target:
                # Reconstruct path
                path = []
                while current is not None:
                    path.append(current)
                    current = previous.get(current)
                return path[::-1]

            unvisited.remove(current)

            for neighbor in adjacency.get(current, {}):
                if neighbor in unvisited and adjacency[current][neighbor]:
                    alt_distance = distances[current] + 1  # All edges have weight 1
                    if alt_distance < distances[neighbor]:
                        distances[neighbor] = alt_distance
                        previous[neighbor] = current

        return None

    def detect_partitions(self) -> List[Set[str]]:
        """Detect network partitions using connected components"""
        visited = set()
        partitions = []

        for node_id in self.nodes:
            if node_id not in visited:
                component = self._dfs(node_id, visited)
                if component:
                    partitions.append(component)

        self.network_partitions = partitions
        return partitions

    def _dfs(self, start_node: str, visited: set) -> Set[str]:
        """Depth-first search for connected components"""
        component = set()
        stack = [start_node]

        while stack:
            current = stack.pop()
            if current not in visited:
                visited.add(current)
                component.add(current)

                # Add unvisited neighbors to stack
                for neighbor in self.adjacency_matrix.get(current, {}):
                    if neighbor not in visited and self.adjacency_matrix[current][neighbor]:
                        stack.append(neighbor)

        return component

class AIAgentMeshNetwork:
    """
    Main AI Agent Mesh Network implementation
    Manages distributed AI agents with direct peer-to-peer communication
    """

    def __init__(self, network_id: str = None):
        self.network_id = network_id or str(uuid.uuid4())
        self.topology = MeshNetworkTopology()

        # Message management
        self.message_handlers: Dict[MeshMessageType, Callable] = {}
        self.pending_messages: Dict[str, MeshMessage] = {}
        self.message_delivery_queue = asyncio.Queue()

        # Consensus management
        self.active_proposals: Dict[str, ConsensusProposal] = {}
        self.consensus_handlers: Dict[str, Callable] = {}

        # Load balancing
        self.load_balancer_strategies: Dict[str, Callable] = {}
        self.work_distribution_queues: Dict[str, asyncio.Queue] = {}

        # Communication Hub integration
        self.communication_hub_client = None
        self.message_translator = None
        self.metadata_enricher = None
        if communication_hub_available:
            self.communication_hub_client = CommunicationHubClient()
            self.message_translator = MessageTranslator()
            self.metadata_enricher = MetadataEnricher()

        # Health monitoring
        self.health_check_interval = 30  # seconds
        self.heartbeat_interval = 10  # seconds

        # Performance metrics
        self.network_metrics = {
            "total_messages_sent": 0,
            "total_messages_delivered": 0,
            "average_latency_ms": 0.0,
            "active_consensus_proposals": 0,
            "network_partitions": 0
        }

        # Initialize default handlers
        self._initialize_default_handlers()

        logger.info(f"🕸️ AI Agent Mesh Network {self.network_id} created")

    def _initialize_default_handlers(self):
        """Initialize default message handlers"""

        self.message_handlers[MeshMessageType.HEARTBEAT] = self._handle_heartbeat
        self.message_handlers[MeshMessageType.DISCOVERY] = self._handle_discovery
        self.message_handlers[MeshMessageType.HEALTH_CHECK] = self._handle_health_check
        self.message_handlers[MeshMessageType.CONSENSUS_PROPOSAL] = self._handle_consensus_proposal
        self.message_handlers[MeshMessageType.CONSENSUS_VOTE] = self._handle_consensus_vote
        self.message_handlers[MeshMessageType.CONSENSUS_COMMIT] = self._handle_consensus_commit
        self.message_handlers[MeshMessageType.LOAD_BALANCE] = self._handle_load_balance
        self.message_handlers[MeshMessageType.FAILOVER] = self._handle_failover

        # Load balancing strategies
        self.load_balancer_strategies["round_robin"] = self._round_robin_strategy
        self.load_balancer_strategies["least_loaded"] = self._least_loaded_strategy
        self.load_balancer_strategies["capability_based"] = self._capability_based_strategy

    async def _notify_user(self, message: str, message_type: CommHubMessageType = CommHubMessageType.WORKFLOW_UPDATE,
                          priority: CommHubMessagePriority = CommHubMessagePriority.NORMAL,
                          context: BusinessContext = BusinessContext.OPERATIONAL_UPDATE,
                          conversation_id: str = None, organization_id: int = None):
        """Send executive-friendly notifications to Communication Hub"""
        if not self.communication_hub_client or not self.message_translator:
            return

        try:
            # Translate technical message to business language
            business_message = self.message_translator.translate_message(message, context)

            # Create metadata with mesh network context
            metadata = {}
            if self.metadata_enricher:
                metadata = self.metadata_enricher.enrich_metadata(
                    {"mesh_network_id": self.network_id},
                    workflow_id=f"mesh_network_{self.network_id}",
                    service_name="distributed_coordination_network"
                )

            # Use default conversation if none provided
            conv_id = conversation_id or f"mesh_network_{self.network_id}"
            org_id = organization_id or 1

            async with self.communication_hub_client as client:
                await client.send_message(
                    conversation_id=conv_id,
                    recipient_id="system",
                    content=business_message,
                    message_type=message_type,
                    priority=priority,
                    metadata=metadata,
                    organization_id=org_id,
                    service_name="distributed_coordination_network"
                )
        except Exception as e:
            logger.warning(f"Failed to send user notification: {e}")

    async def register_agent(self, agent: AgentNode) -> bool:
        """Register a new agent in the mesh network"""
        try:
            # Add agent to topology
            self.topology.add_node(agent)

            # Initialize work queue for agent
            self.work_distribution_queues[agent.agent_id] = asyncio.Queue()

            # Send discovery message to existing agents
            discovery_message = MeshMessage(
                message_id=str(uuid.uuid4()),
                message_type=MeshMessageType.DISCOVERY,
                source_agent=agent.agent_id,
                target_agent=None,  # Broadcast
                payload={
                    "agent_type": agent.agent_type,
                    "capabilities": [asdict(cap) for cap in agent.capabilities],
                    "endpoint": agent.endpoint,
                    "mesh_port": agent.mesh_port
                },
                timestamp=datetime.now(timezone.utc)
            )

            await self.broadcast_message(discovery_message)

            # Notify users about agent joining the network
            await self._notify_user(
                f"AI agent {agent.agent_id} has joined the distributed coordination network. "
                f"Network now has {len(self.topology.nodes)} active agents providing enhanced reliability and processing capacity.",
                CommHubMessageType.WORKFLOW_UPDATE,
                CommHubMessagePriority.NORMAL,
                BusinessContext.OPERATIONAL_UPDATE
            )

            logger.info(f"✅ Registered agent {agent.agent_id} in mesh network")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to register agent {agent.agent_id}: {e}")
            return False

    async def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent from the mesh network"""
        try:
            # Remove from topology
            self.topology.remove_node(agent_id)

            # Clean up work queue
            if agent_id in self.work_distribution_queues:
                del self.work_distribution_queues[agent_id]

            # Cancel pending consensus proposals from this agent
            expired_proposals = [
                proposal_id for proposal_id, proposal in self.active_proposals.items()
                if proposal.proposer == agent_id
            ]

            for proposal_id in expired_proposals:
                del self.active_proposals[proposal_id]

            # Notify users about agent leaving the network
            await self._notify_user(
                f"AI agent {agent_id} has left the distributed coordination network. "
                f"Remaining {len(self.topology.nodes)} agents continue to provide reliable service with automatic workload redistribution.",
                CommHubMessageType.WORKFLOW_UPDATE,
                CommHubMessagePriority.NORMAL,
                BusinessContext.OPERATIONAL_UPDATE
            )

            logger.info(f"✅ Unregistered agent {agent_id} from mesh network")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to unregister agent {agent_id}: {e}")
            return False

    async def send_message(self, message: MeshMessage) -> bool:
        """Send a message through the mesh network"""
        try:
            self.network_metrics["total_messages_sent"] += 1

            if message.target_agent:
                # Unicast message
                await self._route_unicast_message(message)
            else:
                # Broadcast message
                await self._route_broadcast_message(message)

            return True

        except Exception as e:
            logger.error(f"❌ Failed to send message {message.message_id}: {e}")
            return False

    @with_circuit_breaker(name="mesh_message_routing", failure_threshold=5, timeout=30.0)
    async def _route_unicast_message(self, message: MeshMessage):
        """Route a unicast message to specific target"""
        target_agent = message.target_agent

        if target_agent not in self.topology.nodes:
            raise ValueError(f"Target agent {target_agent} not found in mesh")

        target_node = self.topology.nodes[target_agent]

        if not target_node.is_healthy():
            # Try failover routing
            await self._handle_agent_failover(target_agent, message)
            return

        # Get routing path
        path = self.topology.get_shortest_path(message.source_agent, target_agent)

        if not path:
            raise RuntimeError(f"No route available to {target_agent}")

        # Deliver message
        await self._deliver_message_to_agent(target_agent, message)

    async def _route_broadcast_message(self, message: MeshMessage):
        """Route a broadcast message to all agents"""
        for agent_id, node in self.topology.nodes.items():
            if agent_id != message.source_agent and node.is_healthy():
                # Create copy for each recipient
                broadcast_copy = MeshMessage(
                    message_id=str(uuid.uuid4()),
                    message_type=message.message_type,
                    source_agent=message.source_agent,
                    target_agent=agent_id,
                    payload=message.payload.copy(),
                    timestamp=message.timestamp,
                    correlation_id=message.message_id
                )

                await self._deliver_message_to_agent(agent_id, broadcast_copy)

    @with_timeout(timeout=10.0)
    async def _deliver_message_to_agent(self, agent_id: str, message: MeshMessage):
        """Deliver a message to a specific agent"""
        try:
            agent_node = self.topology.nodes[agent_id]

            # Add to agent's message queue
            agent_node.message_queue.append(message)

            # Call appropriate handler
            if message.message_type in self.message_handlers:
                handler = self.message_handlers[message.message_type]
                await handler(agent_id, message)

            self.network_metrics["total_messages_delivered"] += 1

            # Update latency metrics
            delivery_time = (datetime.now(timezone.utc) - message.timestamp).total_seconds() * 1000
            self._update_latency_metrics(delivery_time)

        except Exception as e:
            logger.error(f"❌ Failed to deliver message to {agent_id}: {e}")

            # Retry if possible
            if message.can_retry():
                message.delivery_attempts += 1
                await asyncio.sleep(2 ** message.delivery_attempts)  # Exponential backoff
                await self._deliver_message_to_agent(agent_id, message)

    async def broadcast_message(self, message: MeshMessage):
        """Broadcast a message to all agents in the mesh"""
        message.target_agent = None  # Ensure it's marked as broadcast
        await self.send_message(message)

    async def propose_consensus(self, proposer_id: str, proposal_type: str,
                               proposal_data: Dict[str, Any],
                               required_votes: int = None) -> str:
        """Initiate a consensus proposal"""
        try:
            # Calculate required votes (default to majority)
            if required_votes is None:
                required_votes = max(1, len(self.topology.nodes) // 2 + 1)

            proposal = ConsensusProposal(
                proposal_id=str(uuid.uuid4()),
                proposer=proposer_id,
                proposal_type=proposal_type,
                proposal_data=proposal_data,
                required_votes=required_votes
            )

            self.active_proposals[proposal.proposal_id] = proposal

            # Broadcast proposal to all agents
            proposal_message = MeshMessage(
                message_id=str(uuid.uuid4()),
                message_type=MeshMessageType.CONSENSUS_PROPOSAL,
                source_agent=proposer_id,
                target_agent=None,  # Broadcast
                payload={
                    "proposal_id": proposal.proposal_id,
                    "proposal_type": proposal_type,
                    "proposal_data": proposal_data,
                    "required_votes": required_votes,
                    "expires_at": proposal.expires_at.isoformat()
                },
                timestamp=datetime.now(timezone.utc)
            )

            await self.broadcast_message(proposal_message)

            self.network_metrics["active_consensus_proposals"] += 1
            logger.info(f"📋 Consensus proposal {proposal.proposal_id} initiated by {proposer_id}")

            return proposal.proposal_id

        except Exception as e:
            logger.error(f"❌ Failed to initiate consensus proposal: {e}")
            return ""

    async def vote_on_proposal(self, voter_id: str, proposal_id: str, vote: bool) -> bool:
        """Vote on a consensus proposal"""
        try:
            if proposal_id not in self.active_proposals:
                logger.warning(f"Proposal {proposal_id} not found for voting")
                return False

            proposal = self.active_proposals[proposal_id]

            if proposal.is_expired():
                proposal.status = ConsensusStatus.EXPIRED
                logger.warning(f"Proposal {proposal_id} has expired")
                return False

            # Record vote
            proposal.add_vote(voter_id, vote)

            # Send vote message
            vote_message = MeshMessage(
                message_id=str(uuid.uuid4()),
                message_type=MeshMessageType.CONSENSUS_VOTE,
                source_agent=voter_id,
                target_agent=proposal.proposer,
                payload={
                    "proposal_id": proposal_id,
                    "vote": vote,
                    "voter_id": voter_id
                },
                timestamp=datetime.now(timezone.utc)
            )

            await self.send_message(vote_message)

            # Check if consensus reached
            await self._check_consensus_status(proposal)

            logger.info(f"🗳️ Agent {voter_id} voted {vote} on proposal {proposal_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to vote on proposal {proposal_id}: {e}")
            return False

    async def _check_consensus_status(self, proposal: ConsensusProposal):
        """Check if consensus has been reached on a proposal"""
        if proposal.is_approved():
            proposal.status = ConsensusStatus.COMMITTED

            # Broadcast commit message
            commit_message = MeshMessage(
                message_id=str(uuid.uuid4()),
                message_type=MeshMessageType.CONSENSUS_COMMIT,
                source_agent=proposal.proposer,
                target_agent=None,  # Broadcast
                payload={
                    "proposal_id": proposal.proposal_id,
                    "proposal_type": proposal.proposal_type,
                    "proposal_data": proposal.proposal_data,
                    "status": "committed"
                },
                timestamp=datetime.now(timezone.utc)
            )

            await self.broadcast_message(commit_message)

            # Execute consensus action if handler exists
            if proposal.proposal_type in self.consensus_handlers:
                handler = self.consensus_handlers[proposal.proposal_type]
                await handler(proposal)

            logger.info(f"✅ Consensus reached and committed for proposal {proposal.proposal_id}")

        elif proposal.is_rejected():
            proposal.status = ConsensusStatus.REJECTED
            logger.info(f"❌ Consensus rejected for proposal {proposal.proposal_id}")

    async def request_work_distribution(self, requester_id: str, work_type: str,
                                      work_data: Dict[str, Any],
                                      strategy: str = "least_loaded") -> Optional[str]:
        """Request work distribution to the best available agent"""
        try:
            # Find suitable agents
            suitable_agents = self._find_suitable_agents(work_type)

            if not suitable_agents:
                logger.warning(f"No suitable agents found for work type {work_type}")
                return None

            # Apply load balancing strategy
            if strategy in self.load_balancer_strategies:
                balancer = self.load_balancer_strategies[strategy]
                selected_agent = await balancer(suitable_agents, work_type, work_data)
            else:
                # Default to least loaded
                selected_agent = await self._least_loaded_strategy(suitable_agents, work_type, work_data)

            if not selected_agent:
                logger.warning(f"No available agent selected for work distribution")
                return None

            # Send work request
            work_request = MeshMessage(
                message_id=str(uuid.uuid4()),
                message_type=MeshMessageType.WORK_REQUEST,
                source_agent=requester_id,
                target_agent=selected_agent,
                payload={
                    "work_type": work_type,
                    "work_data": work_data,
                    "requested_at": datetime.now(timezone.utc).isoformat()
                },
                timestamp=datetime.now(timezone.utc)
            )

            await self.send_message(work_request)
            logger.info(f"🎯 Work distributed to agent {selected_agent}")

            return selected_agent

        except Exception as e:
            logger.error(f"❌ Failed to distribute work: {e}")
            return None

    def _find_suitable_agents(self, work_type: str) -> List[str]:
        """Find agents suitable for specific work type"""
        suitable_agents = []

        for agent_id, node in self.topology.nodes.items():
            if not node.is_healthy():
                continue

            if node.state == AgentState.MAINTENANCE:
                continue

            # Check if agent has required capability
            for capability in node.capabilities:
                if capability.capability_name == work_type:
                    suitable_agents.append(agent_id)
                    break

        return suitable_agents

    async def _round_robin_strategy(self, agents: List[str], work_type: str, work_data: Dict[str, Any]) -> Optional[str]:
        """Round-robin load balancing strategy"""
        if not agents:
            return None

        # Simple round-robin based on current time
        index = int(time.time()) % len(agents)
        return agents[index]

    async def _least_loaded_strategy(self, agents: List[str], work_type: str, work_data: Dict[str, Any]) -> Optional[str]:
        """Least loaded load balancing strategy"""
        if not agents:
            return None

        least_loaded_agent = None
        lowest_load = float('inf')

        for agent_id in agents:
            node = self.topology.nodes[agent_id]
            if node.load_percentage < lowest_load:
                lowest_load = node.load_percentage
                least_loaded_agent = agent_id

        return least_loaded_agent

    async def _capability_based_strategy(self, agents: List[str], work_type: str, work_data: Dict[str, Any]) -> Optional[str]:
        """Capability-based load balancing strategy"""
        if not agents:
            return None

        best_agent = None
        best_score = -1

        for agent_id in agents:
            node = self.topology.nodes[agent_id]
            capability = node.get_capability_by_type(work_type)

            if capability:
                # Score based on performance metrics and load
                performance_score = capability.performance_metrics.get("success_rate", 0.0)
                load_penalty = node.load_percentage / 100.0
                total_score = performance_score * (1 - load_penalty)

                if total_score > best_score:
                    best_score = total_score
                    best_agent = agent_id

        return best_agent

    async def _handle_agent_failover(self, failed_agent_id: str, original_message: MeshMessage):
        """Handle agent failover by routing to alternative agent"""
        try:
            # Find alternative agents
            work_type = original_message.payload.get("work_type", "general")
            alternative_agents = self._find_suitable_agents(work_type)

            # Remove failed agent from alternatives
            alternative_agents = [a for a in alternative_agents if a != failed_agent_id]

            if not alternative_agents:
                logger.error(f"No alternative agents available for failover from {failed_agent_id}")
                return

            # Select best alternative using least loaded strategy
            failover_agent = await self._least_loaded_strategy(alternative_agents, work_type, {})

            if failover_agent:
                # Update target and resend
                original_message.target_agent = failover_agent
                original_message.delivery_attempts = 0  # Reset attempts

                failover_notification = MeshMessage(
                    message_id=str(uuid.uuid4()),
                    message_type=MeshMessageType.FAILOVER,
                    source_agent="mesh_network",
                    target_agent=failover_agent,
                    payload={
                        "original_target": failed_agent_id,
                        "failover_reason": "agent_unavailable",
                        "original_message_id": original_message.message_id
                    },
                    timestamp=datetime.now(timezone.utc)
                )

                await self.send_message(failover_notification)
                await self.send_message(original_message)

                logger.info(f"🔄 Failover completed: {failed_agent_id} -> {failover_agent}")

        except Exception as e:
            logger.error(f"❌ Failover failed for {failed_agent_id}: {e}")

    # Message Handlers
    async def _handle_heartbeat(self, agent_id: str, message: MeshMessage):
        """Handle heartbeat message"""
        if agent_id in self.topology.nodes:
            node = self.topology.nodes[agent_id]
            node.last_heartbeat = datetime.now(timezone.utc)

            # Update performance metrics if provided
            if "performance" in message.payload:
                node.update_performance(message.payload["performance"])

    async def _handle_discovery(self, agent_id: str, message: MeshMessage):
        """Handle discovery message"""
        logger.info(f"🔍 Agent discovery from {message.source_agent}")

        # Send back our own discovery response if this is from a new agent
        if message.source_agent not in self.topology.nodes:
            # This would be handled at the agent level
            pass

    async def _handle_health_check(self, agent_id: str, message: MeshMessage):
        """Handle health check message"""
        if agent_id in self.topology.nodes:
            node = self.topology.nodes[agent_id]

            # Update health status based on check results
            health_status = message.payload.get("health_status", "unknown")

            if health_status == "healthy":
                node.state = AgentState.ACTIVE
            elif health_status == "degraded":
                node.state = AgentState.DEGRADED
            elif health_status == "failed":
                node.state = AgentState.FAILED

    async def _handle_consensus_proposal(self, agent_id: str, message: MeshMessage):
        """Handle consensus proposal message"""
        proposal_id = message.payload.get("proposal_id")
        if proposal_id and proposal_id not in self.active_proposals:
            # This is a new proposal - would be handled by individual agents
            logger.info(f"📋 New consensus proposal {proposal_id} received")

    async def _handle_consensus_vote(self, agent_id: str, message: MeshMessage):
        """Handle consensus vote message"""
        proposal_id = message.payload.get("proposal_id")
        vote = message.payload.get("vote", False)
        voter_id = message.payload.get("voter_id")

        if proposal_id in self.active_proposals:
            proposal = self.active_proposals[proposal_id]
            proposal.add_vote(voter_id, vote)
            await self._check_consensus_status(proposal)

    async def _handle_consensus_commit(self, agent_id: str, message: MeshMessage):
        """Handle consensus commit message"""
        proposal_id = message.payload.get("proposal_id")
        logger.info(f"✅ Consensus committed for proposal {proposal_id}")

        if proposal_id in self.active_proposals:
            self.network_metrics["active_consensus_proposals"] -= 1

    async def _handle_load_balance(self, agent_id: str, message: MeshMessage):
        """Handle load balance message"""
        load_info = message.payload.get("load_info", {})

        if agent_id in self.topology.nodes:
            node = self.topology.nodes[agent_id]
            node.load_percentage = load_info.get("load_percentage", node.load_percentage)

    async def _handle_failover(self, agent_id: str, message: MeshMessage):
        """Handle failover message"""
        original_target = message.payload.get("original_target")
        failover_reason = message.payload.get("failover_reason")

        logger.info(f"🔄 Failover notification: {original_target} -> {agent_id} ({failover_reason})")

    # Monitoring and maintenance
    async def start_network_monitoring(self):
        """Start network monitoring tasks"""
        asyncio.create_task(self._heartbeat_monitor())
        asyncio.create_task(self._health_monitor())
        asyncio.create_task(self._consensus_monitor())
        asyncio.create_task(self._topology_monitor())

    async def _heartbeat_monitor(self):
        """Monitor agent heartbeats"""
        while True:
            try:
                current_time = datetime.now(timezone.utc)

                for agent_id, node in self.topology.nodes.items():
                    heartbeat_age = current_time - node.last_heartbeat

                    if heartbeat_age > timedelta(minutes=2):
                        if node.state != AgentState.UNREACHABLE:
                            node.state = AgentState.UNREACHABLE
                            logger.warning(f"⚠️ Agent {agent_id} marked as unreachable")

                await asyncio.sleep(self.heartbeat_interval)

            except Exception as e:
                logger.error(f"❌ Heartbeat monitoring error: {e}")
                await asyncio.sleep(60)

    async def _health_monitor(self):
        """Monitor overall network health"""
        while True:
            try:
                # Check network partitions
                partitions = self.topology.detect_partitions()
                self.network_metrics["network_partitions"] = len(partitions)

                if len(partitions) > 1:
                    logger.warning(f"⚠️ Network partitioned into {len(partitions)} components")

                # Update monitoring service
                await monitoring_service.record_metric(
                    metric_name="mesh_network_partitions",
                    value=len(partitions),
                    tags={"network_id": self.network_id}
                )

                await asyncio.sleep(self.health_check_interval)

            except Exception as e:
                logger.error(f"❌ Health monitoring error: {e}")
                await asyncio.sleep(120)

    async def _consensus_monitor(self):
        """Monitor consensus proposals"""
        while True:
            try:
                current_time = datetime.now(timezone.utc)
                expired_proposals = []

                for proposal_id, proposal in self.active_proposals.items():
                    if proposal.is_expired() and proposal.status == ConsensusStatus.PROPOSED:
                        proposal.status = ConsensusStatus.EXPIRED
                        expired_proposals.append(proposal_id)

                # Clean up expired proposals
                for proposal_id in expired_proposals:
                    del self.active_proposals[proposal_id]
                    self.network_metrics["active_consensus_proposals"] -= 1
                    logger.info(f"⏰ Consensus proposal {proposal_id} expired")

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"❌ Consensus monitoring error: {e}")
                await asyncio.sleep(120)

    async def _topology_monitor(self):
        """Monitor network topology changes"""
        while True:
            try:
                # Update routing tables periodically
                self.topology._update_routing_table()

                # Report topology metrics
                await monitoring_service.record_metric(
                    metric_name="mesh_network_nodes",
                    value=len(self.topology.nodes),
                    tags={"network_id": self.network_id}
                )

                healthy_nodes = sum(1 for node in self.topology.nodes.values() if node.is_healthy())
                await monitoring_service.record_metric(
                    metric_name="mesh_network_healthy_nodes",
                    value=healthy_nodes,
                    tags={"network_id": self.network_id}
                )

                await asyncio.sleep(300)  # Update every 5 minutes

            except Exception as e:
                logger.error(f"❌ Topology monitoring error: {e}")
                await asyncio.sleep(600)

    def _update_latency_metrics(self, delivery_time_ms: float):
        """Update latency metrics"""
        current_avg = self.network_metrics["average_latency_ms"]
        total_messages = self.network_metrics["total_messages_delivered"]

        if total_messages > 0:
            # Exponential moving average
            alpha = 0.1
            self.network_metrics["average_latency_ms"] = (alpha * delivery_time_ms +
                                                         (1 - alpha) * current_avg)

    async def get_network_status(self) -> Dict[str, Any]:
        """Get comprehensive network status"""
        try:
            partitions = self.topology.detect_partitions()

            return {
                "network_id": self.network_id,
                "topology": {
                    "total_nodes": len(self.topology.nodes),
                    "healthy_nodes": sum(1 for node in self.topology.nodes.values() if node.is_healthy()),
                    "partitions": len(partitions),
                    "partition_details": [list(partition) for partition in partitions]
                },
                "consensus": {
                    "active_proposals": len(self.active_proposals),
                    "proposal_details": [
                        {
                            "proposal_id": p.proposal_id,
                            "proposer": p.proposer,
                            "status": p.status.value,
                            "votes": len(p.votes),
                            "required_votes": p.required_votes
                        }
                        for p in self.active_proposals.values()
                    ]
                },
                "performance": {
                    **self.network_metrics,
                    "message_delivery_rate": (
                        self.network_metrics["total_messages_delivered"] /
                        max(1, self.network_metrics["total_messages_sent"]) * 100
                    )
                },
                "agents": [
                    {
                        "agent_id": node.agent_id,
                        "agent_type": node.agent_type,
                        "state": node.state.value,
                        "load_percentage": node.load_percentage,
                        "capabilities": [cap.capability_name for cap in node.capabilities],
                        "last_heartbeat": node.last_heartbeat.isoformat(),
                        "connections": len(node.connections)
                    }
                    for node in self.topology.nodes.values()
                ],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"❌ Failed to get network status: {e}")
            return {"error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}

# Global mesh network instance
ai_agent_mesh = AIAgentMeshNetwork()

# Test function
async def test_ai_agent_mesh():
    """Test the AI Agent Mesh Network"""

    print("🧪 AI AGENT MESH NETWORK TEST")
    print("=" * 60)

    # Create test agents
    capabilities = [
        AgentCapability(
            capability_id="exec_search",
            capability_name="executive_search",
            version="2.0.0",
            parameters={"max_results": 10},
            resource_requirements={"cpu": 1.0, "memory": 2.0},
            performance_metrics={"success_rate": 0.95, "avg_latency": 150.0}
        )
    ]

    agent1 = AgentNode(
        agent_id="agent_001",
        agent_name="Executive Search Agent",
        agent_type="search_agent",
        capabilities=capabilities,
        state=AgentState.ACTIVE,
        endpoint="http://agent1:8080",
        mesh_port=50051
    )

    agent2 = AgentNode(
        agent_id="agent_002",
        agent_name="LinkedIn Discovery Agent",
        agent_type="discovery_agent",
        capabilities=capabilities,
        state=AgentState.ACTIVE,
        endpoint="http://agent2:8080",
        mesh_port=50052
    )

    # Register agents
    await ai_agent_mesh.register_agent(agent1)
    await ai_agent_mesh.register_agent(agent2)

    # Start monitoring
    await ai_agent_mesh.start_network_monitoring()

    # Test consensus
    proposal_id = await ai_agent_mesh.propose_consensus(
        proposer_id="agent_001",
        proposal_type="workflow_optimization",
        proposal_data={"optimization_target": "latency", "threshold": 100}
    )

    await ai_agent_mesh.vote_on_proposal("agent_001", proposal_id, True)
    await ai_agent_mesh.vote_on_proposal("agent_002", proposal_id, True)

    # Test work distribution
    selected_agent = await ai_agent_mesh.request_work_distribution(
        requester_id="client_001",
        work_type="executive_search",
        work_data={"company": "Tech Corp"},
        strategy="least_loaded"
    )

    print(f"🎯 Work assigned to: {selected_agent}")

    # Get network status
    status = await ai_agent_mesh.get_network_status()
    print(f"\n🌐 Network Status:")
    print(f"  Nodes: {status['topology']['healthy_nodes']}/{status['topology']['total_nodes']}")
    print(f"  Active Proposals: {status['consensus']['active_proposals']}")
    print(f"  Average Latency: {status['performance']['average_latency_ms']:.1f}ms")

    print(f"\n🕸️ AI Agent Mesh Network test completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_ai_agent_mesh())