"""
Advanced Conversation Context Management Service
Provides intelligent context tracking, summarization, and memory management

Features:
- Adaptive context window management
- AI-powered conversation summarization
- Topic clustering and entity tracking
- Memory consolidation and retrieval
- Context-aware response generation
"""

import json
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import openai
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class ContextImportance(Enum):
    """Importance levels for context elements"""
    CRITICAL = "critical"      # Essential for conversation continuity
    HIGH = "high"             # Important for context
    MEDIUM = "medium"         # Helpful background
    LOW = "low"               # Optional details

class EntityType(Enum):
    """Types of entities tracked in conversation"""
    PERSON = "person"
    COMPANY = "company"
    EMAIL = "email"
    PHONE = "phone"
    LOCATION = "location"
    DATE = "date"
    SKILL = "skill"
    INDUSTRY = "industry"
    TOOL = "tool"
    WORKFLOW = "workflow"

@dataclass
class ContextEntity:
    """Individual entity tracked in conversation"""
    entity_id: str
    entity_type: EntityType
    name: str
    attributes: Dict[str, Any]
    first_mentioned: datetime
    last_mentioned: datetime
    mention_count: int
    importance: ContextImportance
    related_entities: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            'entity_type': self.entity_type.value,
            'importance': self.importance.value,
            'first_mentioned': self.first_mentioned.isoformat(),
            'last_mentioned': self.last_mentioned.isoformat()
        }

@dataclass
class ConversationTurn:
    """Single conversation turn with metadata"""
    turn_id: str
    timestamp: datetime
    speaker: str  # 'user' or 'agent'
    message: str
    message_type: str  # 'query', 'response', 'workflow_progress', etc.
    entities_mentioned: List[str]
    topics: List[str]
    sentiment: float  # -1 to 1
    importance: ContextImportance
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            'timestamp': self.timestamp.isoformat(),
            'importance': self.importance.value
        }

@dataclass
class ConversationSummary:
    """Compressed conversation summary"""
    summary_id: str
    session_id: str
    summary_text: str
    key_points: List[str]
    entities_summary: Dict[str, Any]
    topics_covered: List[str]
    decisions_made: List[str]
    action_items: List[str]
    time_period: Tuple[datetime, datetime]
    compressed_turns_count: int
    importance: ContextImportance

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['importance'] = self.importance.value
        data['time_period'] = [self.time_period[0].isoformat(), self.time_period[1].isoformat()]
        return data

class ConversationContextManager:
    """
    Advanced conversation context management with AI-powered summarization

    Manages conversation memory, entity tracking, and intelligent summarization
    for maintaining context across extended conversations.
    """

    def __init__(self, max_context_turns: int = 50, max_entities: int = 100):
        self.max_context_turns = max_context_turns
        self.max_entities = max_entities

        # Active conversation state
        self.conversation_turns: deque = deque(maxlen=max_context_turns)
        self.entities: Dict[str, ContextEntity] = {}
        self.topic_clusters: Dict[str, List[str]] = defaultdict(list)
        self.conversation_summaries: List[ConversationSummary] = []

        # Session tracking
        self.current_session_id: Optional[str] = None
        self.session_start_time: Optional[datetime] = None
        self.last_activity_time: Optional[datetime] = None

        # Context management
        self.context_window_size = 4000  # tokens
        self.summary_trigger_threshold = 30  # turns before summarization

        logger.info("ConversationContextManager initialized")

    async def start_session(self, session_id: str, user_id: int, organization_id: int) -> str:
        """Start a new conversation session"""
        self.current_session_id = session_id
        self.session_start_time = datetime.now(timezone.utc)
        self.last_activity_time = datetime.now(timezone.utc)

        # Load existing context if resuming
        await self._load_session_context(session_id, organization_id)

        logger.info(f"Started conversation session {session_id}")
        return session_id

    async def add_conversation_turn(
        self,
        speaker: str,
        message: str,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a new conversation turn"""
        if not self.current_session_id:
            raise ValueError("No active session")

        turn_id = f"turn_{datetime.now(timezone.utc).timestamp()}_{len(self.conversation_turns)}"
        timestamp = datetime.now(timezone.utc)

        # Extract entities and topics
        entities_mentioned = await self._extract_entities(message)
        topics = await self._extract_topics(message)
        sentiment = await self._analyze_sentiment(message)
        importance = await self._determine_importance(message, speaker, message_type)

        # Create turn
        turn = ConversationTurn(
            turn_id=turn_id,
            timestamp=timestamp,
            speaker=speaker,
            message=message,
            message_type=message_type,
            entities_mentioned=entities_mentioned,
            topics=topics,
            sentiment=sentiment,
            importance=importance,
            metadata=metadata or {}
        )

        # Add to conversation
        self.conversation_turns.append(turn)
        self.last_activity_time = timestamp

        # Update entities
        await self._update_entities(entities_mentioned, timestamp)

        # Update topic clusters
        await self._update_topic_clusters(topics, turn_id)

        # Check if summarization is needed
        if len(self.conversation_turns) >= self.summary_trigger_threshold:
            await self._create_conversation_summary()

        logger.debug(f"Added conversation turn {turn_id}")
        return turn_id

    async def get_conversation_context(
        self,
        include_summaries: bool = True,
        max_turns: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get current conversation context for AI responses"""
        max_turns = max_turns or self.max_context_turns

        # Get recent turns
        recent_turns = list(self.conversation_turns)[-max_turns:]

        # Get relevant entities
        relevant_entities = await self._get_relevant_entities()

        # Get conversation summaries
        summaries = self.conversation_summaries if include_summaries else []

        # Get active topics
        active_topics = await self._get_active_topics()

        context = {
            "session_id": self.current_session_id,
            "session_duration_minutes": self._get_session_duration_minutes(),
            "total_turns": len(self.conversation_turns),
            "recent_turns": [turn.to_dict() for turn in recent_turns],
            "relevant_entities": {eid: entity.to_dict() for eid, entity in relevant_entities.items()},
            "active_topics": active_topics,
            "conversation_summaries": [summary.to_dict() for summary in summaries],
            "context_metadata": {
                "last_activity": self.last_activity_time.isoformat() if self.last_activity_time else None,
                "entity_count": len(self.entities),
                "summary_count": len(self.conversation_summaries)
            }
        }

        return context

    async def generate_conversation_summary(
        self,
        include_insights: bool = True,
        include_metrics: bool = True
    ) -> Dict[str, Any]:
        """Generate comprehensive conversation summary"""
        if not self.conversation_turns:
            return {"error": "No conversation data available"}

        # Basic conversation metrics
        total_turns = len(self.conversation_turns)
        user_turns = len([t for t in self.conversation_turns if t.speaker == 'user'])
        agent_turns = len([t for t in self.conversation_turns if t.speaker == 'agent'])

        # Generate AI summary
        summary_text = await self._generate_ai_summary()

        # Extract key insights
        insights = await self._extract_conversation_insights() if include_insights else []

        # Get action items and decisions
        action_items = await self._extract_action_items()
        decisions = await self._extract_decisions()

        # Calculate metrics
        metrics = await self._calculate_conversation_metrics() if include_metrics else {}

        # Get entity summary
        entity_summary = await self._get_entity_summary()

        summary = {
            "session_id": self.current_session_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary_text": summary_text,
            "key_insights": insights,
            "action_items": action_items,
            "decisions_made": decisions,
            "topics_covered": list(self.topic_clusters.keys()),
            "entity_summary": entity_summary,
            "conversation_metrics": {
                "total_turns": total_turns,
                "user_messages": user_turns,
                "agent_responses": agent_turns,
                "session_duration_minutes": self._get_session_duration_minutes(),
                "entities_discovered": len(self.entities),
                **metrics
            },
            "sentiment_analysis": await self._analyze_overall_sentiment(),
            "productivity_score": await self._calculate_productivity_score()
        }

        return summary

    async def _extract_entities(self, text: str) -> List[str]:
        """Extract entities from text using AI"""
        try:
            # Use OpenAI for entity extraction
            response = await openai.ChatCompletion.acreate(
                model="gpt-4.1",
                messages=[
                    {
                        "role": "system",
                        "content": """Extract entities from the text. Return JSON array of objects with:
                        {"name": "entity_name", "type": "person|company|email|phone|location|date|skill|industry|tool|workflow", "attributes": {}}
                        Focus on business-relevant entities."""
                    },
                    {"role": "user", "content": text}
                ],
                max_tokens=500,
                temperature=0.1
            )

            entities_data = json.loads(response.choices[0].message.content)
            entity_ids = []

            for entity_data in entities_data:
                entity_id = self._create_or_update_entity(
                    name=entity_data["name"],
                    entity_type=EntityType(entity_data["type"]),
                    attributes=entity_data.get("attributes", {})
                )
                entity_ids.append(entity_id)

            return entity_ids

        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return []

    async def _extract_topics(self, text: str) -> List[str]:
        """Extract topics from text"""
        try:
            response = await openai.ChatCompletion.acreate(
                model="gpt-4.1",
                messages=[
                    {
                        "role": "system",
                        "content": "Extract 3-5 main topics from the text as a JSON array of strings. Focus on business and professional topics."
                    },
                    {"role": "user", "content": text}
                ],
                max_tokens=200,
                temperature=0.1
            )

            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"Topic extraction failed: {e}")
            return []

    async def _analyze_sentiment(self, text: str) -> float:
        """Analyze sentiment of text (-1 to 1)"""
        try:
            response = await openai.ChatCompletion.acreate(
                model="gpt-4.1",
                messages=[
                    {
                        "role": "system",
                        "content": "Analyze sentiment of the text. Return a number between -1 (very negative) and 1 (very positive). Return only the number."
                    },
                    {"role": "user", "content": text}
                ],
                max_tokens=10,
                temperature=0.1
            )

            return float(response.choices[0].message.content.strip())

        except Exception as e:
            logger.error(f"Sentiment analysis failed: {e}")
            return 0.0

    async def _determine_importance(self, message: str, speaker: str, message_type: str) -> ContextImportance:
        """Determine importance of conversation turn"""
        # High importance for workflow results, decisions, and specific queries
        if message_type in ['workflow_result', 'decision', 'action_item']:
            return ContextImportance.CRITICAL

        # User queries are generally important
        if speaker == 'user' and '?' in message:
            return ContextImportance.HIGH

        # System messages are usually medium importance
        if speaker == 'system':
            return ContextImportance.MEDIUM

        # Default importance based on length and content
        if len(message) > 200 or any(keyword in message.lower() for keyword in
                                   ['important', 'urgent', 'decision', 'action', 'next steps']):
            return ContextImportance.HIGH

        return ContextImportance.MEDIUM

    def _create_or_update_entity(
        self,
        name: str,
        entity_type: EntityType,
        attributes: Dict[str, Any]
    ) -> str:
        """Create or update entity"""
        entity_id = hashlib.md5(f"{entity_type.value}:{name}".encode()).hexdigest()

        if entity_id in self.entities:
            # Update existing entity
            entity = self.entities[entity_id]
            entity.last_mentioned = datetime.now(timezone.utc)
            entity.mention_count += 1
            entity.attributes.update(attributes)
        else:
            # Create new entity
            now = datetime.now(timezone.utc)
            entity = ContextEntity(
                entity_id=entity_id,
                entity_type=entity_type,
                name=name,
                attributes=attributes,
                first_mentioned=now,
                last_mentioned=now,
                mention_count=1,
                importance=ContextImportance.MEDIUM,
                related_entities=[]
            )
            self.entities[entity_id] = entity

        return entity_id

    async def _update_entities(self, entity_ids: List[str], timestamp: datetime):
        """Update entity timestamps and relationships"""
        for entity_id in entity_ids:
            if entity_id in self.entities:
                self.entities[entity_id].last_mentioned = timestamp

    async def _update_topic_clusters(self, topics: List[str], turn_id: str):
        """Update topic clusters"""
        for topic in topics:
            self.topic_clusters[topic].append(turn_id)

    async def _get_relevant_entities(self, limit: int = 10) -> Dict[str, ContextEntity]:
        """Get most relevant entities for current context"""
        # Sort entities by recency and importance
        sorted_entities = sorted(
            self.entities.items(),
            key=lambda x: (
                x[1].importance.value == 'critical',
                x[1].last_mentioned,
                x[1].mention_count
            ),
            reverse=True
        )

        return dict(sorted_entities[:limit])

    async def _get_active_topics(self, limit: int = 10) -> List[str]:
        """Get most active topics"""
        # Sort topics by recent activity
        topic_scores = {}
        for topic, turn_ids in self.topic_clusters.items():
            # Recent turns get higher scores
            recent_turns = len([tid for tid in turn_ids[-20:]])
            topic_scores[topic] = recent_turns

        sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)
        return [topic for topic, _ in sorted_topics[:limit]]

    async def _generate_ai_summary(self) -> str:
        """Generate AI-powered conversation summary"""
        try:
            # Prepare conversation text
            conversation_text = "\n".join([
                f"{turn.speaker}: {turn.message}"
                for turn in list(self.conversation_turns)[-20:]  # Last 20 turns
            ])

            response = await openai.ChatCompletion.acreate(
                model="gpt-4",
                messages=[
                    {
                        "role": "system",
                        "content": """Summarize this business conversation focusing on:
                        1. Main objectives and goals discussed
                        2. Key decisions made
                        3. Action items identified
                        4. Important contacts or companies mentioned
                        5. Next steps planned

                        Provide a concise 2-3 paragraph summary."""
                    },
                    {"role": "user", "content": conversation_text}
                ],
                max_tokens=500,
                temperature=0.3
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"AI summary generation failed: {e}")
            return "Summary generation temporarily unavailable."

    async def _extract_conversation_insights(self) -> List[Dict[str, Any]]:
        """Extract key insights from conversation"""
        # Implementation for insight extraction
        return []

    async def _extract_action_items(self) -> List[str]:
        """Extract action items from conversation"""
        action_items = []
        for turn in self.conversation_turns:
            if 'action' in turn.message.lower() or 'todo' in turn.message.lower():
                # Simple extraction - could be enhanced with AI
                action_items.append(turn.message)
        return action_items[-5:]  # Return last 5 action items

    async def _extract_decisions(self) -> List[str]:
        """Extract decisions made during conversation"""
        decisions = []
        for turn in self.conversation_turns:
            if any(keyword in turn.message.lower() for keyword in ['decided', 'agreed', 'confirmed']):
                decisions.append(turn.message)
        return decisions[-5:]  # Return last 5 decisions

    async def _calculate_conversation_metrics(self) -> Dict[str, Any]:
        """Calculate detailed conversation metrics"""
        if not self.conversation_turns:
            return {}

        turns = list(self.conversation_turns)

        # Response times (simplified)
        response_times = []
        for i in range(1, len(turns)):
            if turns[i-1].speaker == 'user' and turns[i].speaker == 'agent':
                time_diff = (turns[i].timestamp - turns[i-1].timestamp).total_seconds()
                response_times.append(time_diff)

        avg_response_time = sum(response_times) / len(response_times) if response_times else 0

        return {
            "avg_response_time_seconds": avg_response_time,
            "total_entities_mentioned": len(self.entities),
            "unique_topics_discussed": len(self.topic_clusters),
            "conversation_complexity_score": min(100, len(self.entities) * 2 + len(self.topic_clusters) * 3)
        }

    async def _get_entity_summary(self) -> Dict[str, Any]:
        """Get summary of entities by type"""
        entity_summary = defaultdict(list)
        for entity in self.entities.values():
            entity_summary[entity.entity_type.value].append({
                "name": entity.name,
                "mention_count": entity.mention_count,
                "attributes": entity.attributes
            })
        return dict(entity_summary)

    async def _analyze_overall_sentiment(self) -> Dict[str, Any]:
        """Analyze overall conversation sentiment"""
        if not self.conversation_turns:
            return {"overall_sentiment": 0.0, "sentiment_trend": "neutral"}

        sentiments = [turn.sentiment for turn in self.conversation_turns]
        overall_sentiment = sum(sentiments) / len(sentiments)

        # Calculate trend (last 5 vs first 5)
        if len(sentiments) >= 10:
            early_sentiment = sum(sentiments[:5]) / 5
            recent_sentiment = sum(sentiments[-5:]) / 5
            if recent_sentiment > early_sentiment + 0.1:
                trend = "improving"
            elif recent_sentiment < early_sentiment - 0.1:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "overall_sentiment": overall_sentiment,
            "sentiment_trend": trend,
            "positive_turns": len([s for s in sentiments if s > 0.1]),
            "negative_turns": len([s for s in sentiments if s < -0.1]),
            "neutral_turns": len([s for s in sentiments if -0.1 <= s <= 0.1])
        }

    async def _calculate_productivity_score(self) -> int:
        """Calculate conversation productivity score (0-100)"""
        if not self.conversation_turns:
            return 0

        score = 50  # Base score

        # Add points for entities discovered
        score += min(20, len(self.entities) * 2)

        # Add points for action items
        action_items = await self._extract_action_items()
        score += min(15, len(action_items) * 3)

        # Add points for decisions
        decisions = await self._extract_decisions()
        score += min(10, len(decisions) * 5)

        # Add points for topic coverage
        score += min(5, len(self.topic_clusters))

        return min(100, score)

    def _get_session_duration_minutes(self) -> int:
        """Get session duration in minutes"""
        if not self.session_start_time:
            return 0

        end_time = self.last_activity_time or datetime.now(timezone.utc)
        duration = end_time - self.session_start_time
        return int(duration.total_seconds() / 60)

    async def _create_conversation_summary(self):
        """Create summary when conversation gets too long"""
        if len(self.conversation_turns) < self.summary_trigger_threshold:
            return

        # Create summary of older turns
        turns_to_summarize = list(self.conversation_turns)[:20]  # First 20 turns

        summary_text = await self._generate_ai_summary()

        # Extract key information
        key_points = []
        entities_in_summary = {}
        topics_in_summary = set()

        for turn in turns_to_summarize:
            if turn.importance in [ContextImportance.CRITICAL, ContextImportance.HIGH]:
                key_points.append(turn.message[:200])  # Truncate

            topics_in_summary.update(turn.topics)

            for entity_id in turn.entities_mentioned:
                if entity_id in self.entities:
                    entity = self.entities[entity_id]
                    entities_in_summary[entity_id] = {
                        "name": entity.name,
                        "type": entity.entity_type.value,
                        "mention_count": entity.mention_count
                    }

        # Create summary object
        summary = ConversationSummary(
            summary_id=f"summary_{datetime.now(timezone.utc).timestamp()}",
            session_id=self.current_session_id,
            summary_text=summary_text,
            key_points=key_points[:10],  # Limit key points
            entities_summary=entities_in_summary,
            topics_covered=list(topics_in_summary),
            decisions_made=await self._extract_decisions(),
            action_items=await self._extract_action_items(),
            time_period=(turns_to_summarize[0].timestamp, turns_to_summarize[-1].timestamp),
            compressed_turns_count=len(turns_to_summarize),
            importance=ContextImportance.HIGH
        )

        self.conversation_summaries.append(summary)

        # Remove old turns (keep recent ones)
        for _ in range(len(turns_to_summarize)):
            if self.conversation_turns:
                self.conversation_turns.popleft()

        logger.info(f"Created conversation summary with {len(turns_to_summarize)} turns compressed")

    async def _load_session_context(self, session_id: str, organization_id: int):
        """Load existing context for session (placeholder for database integration)"""
        # This would load from database in production
        logger.info(f"Loading context for session {session_id}")

    async def _save_session_context(self):
        """Save current context to database (placeholder)"""
        # This would save to database in production
        logger.info(f"Saving context for session {self.current_session_id}")

# Global context manager instance
conversation_context_manager = ConversationContextManager()
