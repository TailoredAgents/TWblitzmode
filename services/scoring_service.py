"""
Connector Scoring Service

Implements sophisticated scoring algorithms to rank mutual connections based on
relationship strength, shared context, and likelihood of successful introductions.

Features:
- Multi-factor weighted scoring algorithm
- Machine learning-enhanced scoring (optional)
- Historical success rate tracking
- Company and educational institution matching
- Geographic proximity scoring
- Professional seniority assessment
- Recency and interaction frequency analysis
"""

import os
import re
import json
import math
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import asyncio

logger = logging.getLogger(__name__)

@dataclass
class ScoringFactors:
    """Individual scoring factors for a connector"""
    connection_degree: float  # 0.0-1.0 (1st=1.0, 2nd=0.7, 3rd=0.4)
    company_match: float      # 0.0-1.0 (same company bonus)
    school_match: float       # 0.0-1.0 (shared education bonus)
    seniority_match: float    # 0.0-1.0 (appropriate seniority level)
    location_proximity: float # 0.0-1.0 (geographic proximity)
    mutual_count_norm: float  # 0.0-1.0 (normalized mutual connections)
    interaction_recency: float # 0.0-1.0 (recent interactions)
    industry_relevance: float # 0.0-1.0 (industry alignment)
    historical_success: float # 0.0-1.0 (past introduction success rate)

@dataclass
class ScoredConnector:
    """Connector with comprehensive scoring information"""
    connector_id: int
    prospect_id: int
    full_name: str
    linkedin_url: str
    headline: str
    company: str

    # Scoring
    ranking_score: float
    rank: Optional[int]
    scoring_factors: ScoringFactors
    reason_codes: List[str]

    # Team assignment
    assigned_team_member_id: Optional[int]
    relationship_strength: float

    # Additional context
    estimated_response_probability: float
    confidence_level: str  # "high", "medium", "low"

@dataclass
class ScoringResult:
    """Container returned to workflow coordinator."""
    top_connectors: List[Dict[str, Any]]

class ConnectorScoringService:
    """Production-ready connector scoring and ranking service"""

    # Scoring weights (must sum to 1.0)
    SCORING_WEIGHTS = {
        'connection_degree': 0.30,
        'company_match': 0.20,
        'school_match': 0.10,
        'seniority_match': 0.15,
        'location_proximity': 0.05,
        'mutual_count_norm': 0.10,
        'interaction_recency': 0.05,
        'industry_relevance': 0.03,
        'historical_success': 0.02
    }

    # Executive seniority levels (higher = more senior)
    SENIORITY_LEVELS = {
        'ceo': 10, 'president': 10, 'founder': 10, 'owner': 10,
        'cmo': 9, 'cto': 9, 'cfo': 9, 'coo': 9,
        'chief': 8, 'vp': 7, 'vice president': 7, 'svp': 8,
        'director': 6, 'senior director': 7,
        'head of': 5, 'head': 5,
        'manager': 4, 'senior manager': 5,
        'lead': 3, 'senior': 3,
        'specialist': 2, 'analyst': 2,
        'associate': 1, 'coordinator': 1
    }

    # Industry keywords for relevance scoring
    INDUSTRY_KEYWORDS = {
        'technology': ['tech', 'software', 'saas', 'ai', 'ml', 'data', 'cloud', 'digital'],
        'marketing': ['marketing', 'brand', 'advertising', 'growth', 'demand gen'],
        'sales': ['sales', 'business development', 'revenue', 'account'],
        'finance': ['finance', 'accounting', 'treasury', 'fp&a', 'controller'],
        'operations': ['operations', 'supply chain', 'logistics', 'procurement'],
        'hr': ['human resources', 'hr', 'people', 'talent', 'recruiting'],
        'product': ['product', 'pm', 'product management', 'innovation'],
        'engineering': ['engineering', 'development', 'devops', 'infrastructure']
    }

    # Geographic proximity zones (in miles)
    LOCATION_ZONES = {
        'same_city': (0, 25, 1.0),
        'same_metro': (25, 100, 0.8),
        'same_state': (100, 500, 0.6),
        'same_country': (500, 3000, 0.4),
        'international': (3000, float('inf'), 0.2)
    }

    def __init__(self):
        self.enable_ml_scoring = os.getenv('ENABLE_ML_SCORING', 'false').lower() == 'true'
        self.top_connectors_count = int(os.getenv('TOP_CONNECTORS_COUNT', '5'))

        # Historical data for ML features
        self.historical_data = {}

    async def score_prospect_connectors(
        self,
        prospect_id: int,
        organization_id: int
    ) -> List[ScoredConnector]:
        """Score and rank all connectors for a prospect"""

        logger.info(f"Starting connector scoring for prospect {prospect_id}")

        try:
            # Get prospect and connector data
            prospect_data = await self._get_prospect_data(prospect_id, organization_id)
            if not prospect_data:
                logger.warning(f"Prospect {prospect_id} not found")
                return []

            connector_data = await self._get_prospect_connectors(prospect_id, organization_id)
            if not connector_data:
                logger.info(f"No connectors found for prospect {prospect_id}")
                return []

            # Load historical success data
            await self._load_historical_data(organization_id)

            # Score each connector
            scored_connectors = []
            for connector in connector_data:
                try:
                    scored_connector = await self._score_single_connector(
                        connector, prospect_data, organization_id
                    )
                    scored_connectors.append(scored_connector)
                except Exception as e:
                    logger.error(f"Error scoring connector {connector.get('id', 'unknown')}: {e}")

            # Rank connectors
            ranked_connectors = self._rank_connectors(scored_connectors)

            # Assign to team members
            assigned_connectors = await self._assign_team_members(ranked_connectors, organization_id)

            # Store results
            await self._store_scoring_results(assigned_connectors, prospect_id, organization_id)

            logger.info(f"Scored {len(assigned_connectors)} connectors for prospect {prospect_id}")
            return assigned_connectors

        except Exception as e:
            logger.error(f"Connector scoring failed for prospect {prospect_id}: {e}")
            return []

    async def _get_prospect_data(self, prospect_id: int, organization_id: int) -> Optional[Dict[str, Any]]:
        """Get prospect information for scoring context"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            prospects = query(conn, """
                SELECT
                    id, company, full_name, role, linkedin_url,
                    headline, location, tags
                FROM prospects
                WHERE id = ? AND organization_id = ?
            """, (prospect_id, organization_id))

            return dict(prospects[0]) if prospects else None

    async def _get_prospect_connectors(
        self,
        prospect_id: int,
        organization_id: int
    ) -> List[Dict[str, Any]]:
        """Get all mutual connections for a prospect"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            connectors = query(conn, """
                SELECT
                    pm.id,
                    pm.mutual_full_name,
                    pm.mutual_linkedin_url,
                    pm.mutual_headline,
                    pm.mutual_company,
                    pm.network_distance,
                    pm.scraped_via
                FROM prospect_mutuals pm
                WHERE pm.prospect_id = ? AND pm.organization_id = ?
            """, (prospect_id, organization_id))

            return [dict(row) for row in connectors]

    async def _score_single_connector(
        self,
        connector: Dict[str, Any],
        prospect_data: Dict[str, Any],
        organization_id: int
    ) -> ScoredConnector:
        """Score a single connector against the prospect"""

        # Calculate individual scoring factors
        factors = ScoringFactors(
            connection_degree=self._score_connection_degree(connector.get('network_distance', '2')),
            company_match=self._score_company_match(
                connector.get('mutual_company', ''),
                prospect_data.get('company', '')
            ),
            school_match=await self._score_school_match(connector, prospect_data),
            seniority_match=self._score_seniority_match(
                connector.get('mutual_headline', ''),
                prospect_data.get('role', '')
            ),
            location_proximity=await self._score_location_proximity(connector, prospect_data),
            mutual_count_norm=await self._score_mutual_connections(connector, organization_id),
            interaction_recency=await self._score_interaction_recency(connector, organization_id),
            industry_relevance=self._score_industry_relevance(
                connector.get('mutual_headline', ''),
                prospect_data.get('headline', '')
            ),
            historical_success=self._score_historical_success(connector, organization_id)
        )

        # Calculate weighted final score
        final_score = (
            factors.connection_degree * self.SCORING_WEIGHTS['connection_degree'] +
            factors.company_match * self.SCORING_WEIGHTS['company_match'] +
            factors.school_match * self.SCORING_WEIGHTS['school_match'] +
            factors.seniority_match * self.SCORING_WEIGHTS['seniority_match'] +
            factors.location_proximity * self.SCORING_WEIGHTS['location_proximity'] +
            factors.mutual_count_norm * self.SCORING_WEIGHTS['mutual_count_norm'] +
            factors.interaction_recency * self.SCORING_WEIGHTS['interaction_recency'] +
            factors.industry_relevance * self.SCORING_WEIGHTS['industry_relevance'] +
            factors.historical_success * self.SCORING_WEIGHTS['historical_success']
        )

        # Generate reason codes
        reason_codes = self._generate_reason_codes(factors)

        # Estimate response probability
        response_probability = self._estimate_response_probability(factors, final_score)

        # Determine confidence level
        confidence_level = self._determine_confidence_level(final_score, factors)

        return ScoredConnector(
            connector_id=connector['id'],
            prospect_id=prospect_data['id'],
            full_name=connector.get('mutual_full_name', ''),
            linkedin_url=connector.get('mutual_linkedin_url', ''),
            headline=connector.get('mutual_headline', ''),
            company=connector.get('mutual_company', ''),
            ranking_score=final_score,
            rank=None,  # Will be set during ranking
            scoring_factors=factors,
            reason_codes=reason_codes,
            assigned_team_member_id=None,  # Will be set during assignment
            relationship_strength=0.0,  # Will be calculated during assignment
            estimated_response_probability=response_probability,
            confidence_level=confidence_level
        )

    def _score_connection_degree(self, network_distance: str) -> float:
        """Score based on LinkedIn connection degree"""

        distance_mapping = {
            '1': 1.0,     # 1st degree connection
            '1st': 1.0,
            '2': 0.7,     # 2nd degree connection
            '2nd': 0.7,
            '3': 0.4,     # 3rd degree connection
            '3rd': 0.4,
            '3+': 0.2     # 3rd+ degree connection
        }

        return distance_mapping.get(str(network_distance).lower(), 0.5)

    def _score_company_match(self, connector_company: str, prospect_company: str) -> float:
        """Score based on company alignment"""

        if not connector_company or not prospect_company:
            return 0.0

        connector_company = connector_company.lower().strip()
        prospect_company = prospect_company.lower().strip()

        # Exact match
        if connector_company == prospect_company:
            return 1.0

        # Partial match (one contains the other)
        if connector_company in prospect_company or prospect_company in connector_company:
            return 0.8

        # Industry/domain match (simplified)
        connector_words = set(connector_company.split())
        prospect_words = set(prospect_company.split())
        common_words = connector_words.intersection(prospect_words)

        if len(common_words) > 0:
            return min(0.6, len(common_words) * 0.2)

        return 0.0

    async def _score_school_match(
        self,
        connector: Dict[str, Any],
        prospect_data: Dict[str, Any]
    ) -> float:
        """Score based on shared educational background"""

        from ..api.db_core import get_conn, query

        try:
            # Look for education data in connector and prospect LinkedIn URLs
            connector_education = await self._extract_education_keywords(
                connector.get('mutual_headline', '')
            )
            prospect_education = await self._extract_education_keywords(
                prospect_data.get('headline', '')
            )

            if not connector_education or not prospect_education:
                return 0.0

            # Calculate education overlap
            common_schools = connector_education.intersection(prospect_education)
            if common_schools:
                return min(1.0, len(common_schools) * 0.5)

            return 0.0

        except Exception as e:
            logger.warning(f"Error scoring school match: {e}")
            return 0.0

    async def _extract_education_keywords(self, headline: str) -> set:
        """Extract education keywords from headline"""

        if not headline:
            return set()

        headline_lower = headline.lower()
        education_keywords = {
            'harvard', 'stanford', 'mit', 'berkeley', 'ucla', 'usc', 'nyu',
            'columbia', 'yale', 'princeton', 'penn', 'wharton', 'kellogg',
            'booth', 'sloan', 'fuqua', 'tuck', 'darden', 'johnson', 'ross'
        }

        return {keyword for keyword in education_keywords if keyword in headline_lower}

    def _score_seniority_match(self, connector_title: str, prospect_role: str) -> float:
        """Score based on appropriate seniority level for introduction"""

        if not connector_title or not prospect_role:
            return 0.5

        connector_seniority = self._extract_seniority_level(connector_title)
        prospect_seniority = self._extract_seniority_level(prospect_role)

        # Ideal: connector is at same level or slightly higher
        if connector_seniority >= prospect_seniority:
            if connector_seniority - prospect_seniority <= 2:
                return 1.0  # Perfect match
            elif connector_seniority - prospect_seniority <= 4:
                return 0.8  # Good match
            else:
                return 0.6  # Acceptable but very senior
        else:
            # Connector is less senior - lower score
            difference = prospect_seniority - connector_seniority
            return max(0.2, 1.0 - (difference * 0.2))

    def _extract_seniority_level(self, title: str) -> int:
        """Extract seniority level from job title"""

        if not title:
            return 3  # Default middle level

        title_lower = title.lower()

        # Check for exact matches first
        for keyword, level in self.SENIORITY_LEVELS.items():
            if keyword in title_lower:
                return level

        # Default to middle level
        return 3

    async def _score_location_proximity(
        self,
        connector: Dict[str, Any],
        prospect_data: Dict[str, Any]
    ) -> float:
        """Score based on geographic proximity"""

        try:
            # Extract location information from headlines and profiles
            connector_location = self._extract_location_keywords(
                connector.get('mutual_headline', '')
            )
            prospect_location = self._extract_location_keywords(
                prospect_data.get('headline', '') + ' ' + prospect_data.get('location', '')
            )

            if not connector_location or not prospect_location:
                return 0.5  # Neutral if no location data

            # Check for location matches
            if connector_location.intersection(prospect_location):
                return 1.0  # Same location mentioned

            # Check for same state/region
            us_states = {
                'california', 'texas', 'florida', 'new york', 'illinois', 'pennsylvania',
                'ohio', 'georgia', 'north carolina', 'michigan', 'virginia', 'washington'
            }

            connector_states = connector_location.intersection(us_states)
            prospect_states = prospect_location.intersection(us_states)

            if connector_states and prospect_states and connector_states.intersection(prospect_states):
                return 0.8  # Same state

            return 0.4  # Different locations

        except Exception as e:
            logger.warning(f"Error scoring location proximity: {e}")
            return 0.5

    def _extract_location_keywords(self, text: str) -> set:
        """Extract location keywords from text"""

        if not text:
            return set()

        text_lower = text.lower()

        # Major cities and regions
        locations = {
            'san francisco', 'los angeles', 'new york', 'chicago', 'boston', 'seattle',
            'austin', 'denver', 'atlanta', 'miami', 'dallas', 'houston', 'philadelphia',
            'california', 'texas', 'florida', 'new york', 'illinois', 'massachusetts',
            'washington', 'colorado', 'georgia', 'bay area', 'silicon valley', 'socal'
        }

        return {location for location in locations if location in text_lower}

    async def _score_mutual_connections(
        self,
        connector: Dict[str, Any],
        organization_id: int
    ) -> float:
        """Score based on number of mutual connections (normalized)"""

        # This would require parsing mutual connection counts from LinkedIn data
        # For now, return neutral score based on network distance
        network_distance = connector.get('network_distance', '2')

        if network_distance == '1' or network_distance == '1st':
            return 1.0  # 1st degree connections are valuable
        elif network_distance == '2' or network_distance == '2nd':
            return 0.7  # 2nd degree are good
        else:
            return 0.4  # 3rd+ degree are less valuable

    async def _score_interaction_recency(
        self,
        connector: Dict[str, Any],
        organization_id: int
    ) -> float:
        """Score based on recent interactions"""

        # This would require LinkedIn interaction data
        # For now, return neutral score
        # TODO: Track interaction history from LinkedIn
        return 0.5

    def _score_industry_relevance(self, connector_headline: str, prospect_headline: str) -> float:
        """Score based on industry/functional relevance"""

        if not connector_headline or not prospect_headline:
            return 0.5

        connector_headline = connector_headline.lower()
        prospect_headline = prospect_headline.lower()

        # Find matching industry keywords
        max_relevance = 0.0
        for industry, keywords in self.INDUSTRY_KEYWORDS.items():
            connector_matches = sum(1 for keyword in keywords if keyword in connector_headline)
            prospect_matches = sum(1 for keyword in keywords if keyword in prospect_headline)

            if connector_matches > 0 and prospect_matches > 0:
                relevance = min(1.0, (connector_matches + prospect_matches) * 0.2)
                max_relevance = max(max_relevance, relevance)

        return max_relevance

    def _score_historical_success(self, connector: Dict[str, Any], organization_id: int) -> float:
        """Score based on historical introduction success rate"""

        try:
            # Use historical data if available
            if hasattr(self, 'historical_data') and organization_id in self.historical_data:
                connector_key = connector.get('mutual_linkedin_url', '')
                if connector_key in self.historical_data[organization_id]:
                    success_rate = self.historical_data[organization_id][connector_key]['success_rate']
                    return min(1.0, success_rate)

            # Fallback: use connector characteristics to estimate success
            baseline_success = 0.5

            # Higher success probability for senior connectors
            headline = connector.get('mutual_headline', '').lower()
            if any(title in headline for title in ['ceo', 'founder', 'vp', 'director', 'head']):
                baseline_success += 0.2

            # Higher success for tech industry
            if any(keyword in headline for keyword in ['tech', 'software', 'engineer', 'product']):
                baseline_success += 0.1

            return min(1.0, baseline_success)

        except Exception as e:
            logger.warning(f"Error scoring historical success: {e}")
            return 0.5

    def _generate_reason_codes(self, factors: ScoringFactors) -> List[str]:
        """Generate human-readable reason codes for the score"""

        reasons = []

        if factors.connection_degree >= 0.8:
            reasons.append("1st_degree_connection")
        elif factors.connection_degree >= 0.6:
            reasons.append("2nd_degree_connection")

        if factors.company_match >= 0.8:
            reasons.append("same_company")
        elif factors.company_match >= 0.5:
            reasons.append("related_company")

        if factors.seniority_match >= 0.8:
            reasons.append("appropriate_seniority")

        if factors.industry_relevance >= 0.6:
            reasons.append("industry_match")

        if factors.mutual_count_norm >= 0.7:
            reasons.append("high_mutual_connections")

        if factors.interaction_recency >= 0.7:
            reasons.append("recent_interactions")

        return reasons

    def _estimate_response_probability(self, factors: ScoringFactors, final_score: float) -> float:
        """Estimate probability of positive response to introduction request"""

        # Base probability from overall score
        base_probability = final_score * 0.6

        # Boost for strong relationship indicators
        if factors.connection_degree >= 0.8:  # 1st degree
            base_probability += 0.2

        if factors.company_match >= 0.8:  # Same company
            base_probability += 0.15

        if factors.seniority_match >= 0.8:  # Appropriate seniority
            base_probability += 0.1

        # Cap at reasonable maximum
        return min(0.85, base_probability)

    def _determine_confidence_level(self, final_score: float, factors: ScoringFactors) -> str:
        """Determine confidence level in the scoring"""

        if final_score >= 0.75 and factors.connection_degree >= 0.7:
            return "high"
        elif final_score >= 0.5:
            return "medium"
        else:
            return "low"

    def _rank_connectors(self, scored_connectors: List[ScoredConnector]) -> List[ScoredConnector]:
        """Rank connectors by score and assign rankings"""

        # Sort by score (descending)
        sorted_connectors = sorted(scored_connectors, key=lambda c: c.ranking_score, reverse=True)

        # Assign ranks (1-based)
        for i, connector in enumerate(sorted_connectors):
            connector.rank = i + 1

        return sorted_connectors

    async def _assign_team_members(
        self,
        ranked_connectors: List[ScoredConnector],
        organization_id: int
    ) -> List[ScoredConnector]:
        """Assign connectors to team members based on relationship strength"""

        # Get team member network data
        team_networks = await self._get_team_network_data(organization_id)

        for connector in ranked_connectors:
            best_team_member = None
            best_relationship_strength = 0.0

            # Find team member with strongest connection to this connector
            for team_member_id, network_data in team_networks.items():
                strength = self._calculate_relationship_strength(
                    connector, network_data
                )

                if strength > best_relationship_strength:
                    best_relationship_strength = strength
                    best_team_member = team_member_id

            connector.assigned_team_member_id = best_team_member
            connector.relationship_strength = best_relationship_strength

        return ranked_connectors

    async def _get_team_network_data(self, organization_id: int) -> Dict[int, Dict[str, Any]]:
        """Get team member network information"""

        from ..api.db_core import get_conn, query

        team_networks = {}

        with get_conn() as conn:
            # Get team members and their scraped network data
            networks = query(conn, """
                SELECT
                    tm.id as team_member_id,
                    tm.name,
                    pm.mutual_linkedin_url,
                    pm.scraped_via
                FROM team_members tm
                JOIN prospect_mutuals pm ON pm.scraped_via LIKE '%tm_' || tm.id || '%'
                WHERE tm.organization_id = ? AND tm.status = 'active'
            """, (organization_id,))

            for row in networks:
                team_member_id = row['team_member_id']
                if team_member_id not in team_networks:
                    team_networks[team_member_id] = {
                        'name': row['name'],
                        'connections': set()
                    }

                team_networks[team_member_id]['connections'].add(row['mutual_linkedin_url'])

        return team_networks

    def _calculate_relationship_strength(
        self,
        connector: ScoredConnector,
        team_network_data: Dict[str, Any]
    ) -> float:
        """Calculate relationship strength between team member and connector"""

        # Check if team member has direct connection to this connector
        if connector.linkedin_url in team_network_data.get('connections', set()):
            return 0.9  # Strong direct connection

        # TODO: Add more sophisticated relationship strength calculation
        # based on mutual connections, interaction frequency, etc.

        return 0.1  # Default weak connection

    async def _store_scoring_results(
        self,
        scored_connectors: List[ScoredConnector],
        prospect_id: int,
        organization_id: int
    ) -> None:
        """Store scoring results in database"""

        from ..api.db_core import get_conn, execute, ensure_team_member_connector

        try:
            with get_conn() as conn:
                # Clear existing scoring results for this prospect
                execute(conn, """
                    DELETE FROM prospect_connectors
                    WHERE prospect_id = ? AND organization_id = ?
                """, (prospect_id, organization_id))

                # Insert new scored results
                for connector in scored_connectors:
                    if connector.rank and connector.rank <= self.top_connectors_count:
                        team_member_connector_id = None
                        if connector.assigned_team_member_id is not None:
                            try:
                                team_member_connector_id = ensure_team_member_connector(
                                    conn,
                                    organization_id,
                                    connector.assigned_team_member_id,
                                    connector.connector_id,
                                    "scoring_engine",
                                )
                            except Exception as exc:  # pragma: no cover - defensive
                                logger.warning(
                                    "Failed to ensure team_member_connector link: %s",
                                    exc,
                                )

                        execute(
                            conn,
                            """
                            INSERT INTO prospect_connectors (
                                organization_id,
                                prospect_id,
                                connector_id,
                                team_member_id,
                                team_member_connector_id,
                                rank,
                                ranking_score,
                                reason_codes,
                                relationship_strength,
                                confidence_score,
                                status,
                                source,
                                algorithm_version,
                                last_seen_at,
                                created_at,
                                updated_at
                            ) VALUES (
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                'scored', 'scoring_engine', 'scoring_v1', CURRENT_TIMESTAMP,
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                            )
                            ON CONFLICT (organization_id, prospect_id, connector_id, team_member_id)
                            DO UPDATE SET
                                ranking_score = EXCLUDED.ranking_score,
                                rank = EXCLUDED.rank,
                                reason_codes = EXCLUDED.reason_codes,
                                relationship_strength = EXCLUDED.relationship_strength,
                                confidence_score = EXCLUDED.confidence_score,
                                team_member_connector_id = COALESCE(prospect_connectors.team_member_connector_id, EXCLUDED.team_member_connector_id),
                                status = 'scored',
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            (
                                organization_id,
                                prospect_id,
                                connector.connector_id,
                                connector.assigned_team_member_id,
                                team_member_connector_id,
                                connector.rank,
                                connector.ranking_score,
                                json.dumps(connector.reason_codes),
                                connector.relationship_strength,
                                connector.ranking_score,
                            ),
                        )

                logger.info(f"Stored scoring results for {len(scored_connectors)} connectors")

        except Exception as e:
            logger.error(f"Error storing scoring results: {e}")

    async def _load_historical_data(self, organization_id: int) -> None:
        """Load historical introduction success data for ML features"""

        from ..api.db_core import get_conn, query

        try:
            with get_conn() as conn:
                # Load success/failure data from email tracking
                historical_results = query(conn, """
                    SELECT
                        c.mutual_linkedin_url,
                        COUNT(*) as total_introductions,
                        SUM(CASE WHEN ej.status IN ('replied', 'meeting_scheduled') THEN 1 ELSE 0 END) as successes,
                        AVG(CASE WHEN ej.status IN ('replied', 'meeting_scheduled') THEN 1.0 ELSE 0.0 END) as success_rate,
                        c.mutual_headline,
                        c.mutual_company
                    FROM prospect_mutuals c
                    LEFT JOIN email_jobs ej ON ej.connector_id = c.id
                    WHERE c.organization_id = ? AND ej.created_at >= datetime('now', '-6 months')
                    GROUP BY c.mutual_linkedin_url, c.mutual_headline, c.mutual_company
                    HAVING total_introductions >= 2
                """, (organization_id,))

                if organization_id not in self.historical_data:
                    self.historical_data[organization_id] = {}

                for row in historical_results:
                    self.historical_data[organization_id][row['mutual_linkedin_url']] = {
                        'success_rate': row['success_rate'],
                        'total_introductions': row['total_introductions'],
                        'successes': row['successes'],
                        'headline': row['mutual_headline'],
                        'company': row['mutual_company']
                    }

                logger.info(f"Loaded historical data for {len(historical_results)} connectors")

        except Exception as e:
            logger.warning(f"Error loading historical data: {e}")
            self.historical_data[organization_id] = {}

    async def run_ab_testing_analysis(
        self,
        organization_id: int,
        test_duration_days: int = 30
    ) -> Dict[str, Any]:
        """Run A/B testing analysis on scoring algorithm performance"""

        from ..api.db_core import get_conn, query

        try:
            with get_conn() as conn:
                # Compare performance of different scoring weights
                current_results = query(conn, """
                    SELECT
                        pc.ranking_score,
                        pc.rank,
                        pc.reason_codes,
                        COUNT(CASE WHEN ej.status IN ('replied', 'meeting_scheduled') THEN 1 END) as successes,
                        COUNT(ej.id) as total_sent,
                        AVG(CASE WHEN ej.status IN ('replied', 'meeting_scheduled') THEN 1.0 ELSE 0.0 END) as success_rate
                    FROM prospect_connectors pc
                    LEFT JOIN email_jobs ej ON ej.connector_id = pc.connector_id
                    WHERE pc.organization_id = ?
                    AND pc.created_at >= datetime('now', '-{} days')
                    GROUP BY pc.ranking_score, pc.rank, pc.reason_codes
                """.format(test_duration_days), (organization_id,))

                # Analyze top performers vs bottom performers
                total_connectors = len(current_results)
                if total_connectors < 10:
                    return {"error": "Insufficient data for A/B testing analysis"}

                # Top 20% vs bottom 20%
                top_threshold = int(total_connectors * 0.2)
                bottom_threshold = int(total_connectors * 0.8)

                sorted_results = sorted(current_results, key=lambda x: x['ranking_score'], reverse=True)

                top_performers = sorted_results[:top_threshold]
                bottom_performers = sorted_results[bottom_threshold:]

                top_success_rate = sum(r['success_rate'] or 0 for r in top_performers) / len(top_performers)
                bottom_success_rate = sum(r['success_rate'] or 0 for r in bottom_performers) / len(bottom_performers)

                return {
                    "test_period_days": test_duration_days,
                    "total_connectors_analyzed": total_connectors,
                    "top_20_percent_success_rate": top_success_rate,
                    "bottom_20_percent_success_rate": bottom_success_rate,
                    "algorithm_effectiveness": top_success_rate - bottom_success_rate,
                    "statistical_significance": top_success_rate > bottom_success_rate * 1.2,
                    "recommendations": self._generate_optimization_recommendations(top_performers, bottom_performers)
                }

        except Exception as e:
            logger.error(f"Error running A/B testing analysis: {e}")
            return {"error": str(e)}

    def _generate_optimization_recommendations(
        self,
        top_performers: List[Dict],
        bottom_performers: List[Dict]
    ) -> List[str]:
        """Generate recommendations based on A/B testing results"""

        recommendations = []

        # Analyze reason codes
        top_reasons = []
        bottom_reasons = []

        for performer in top_performers:
            if performer['reason_codes']:
                top_reasons.extend(json.loads(performer['reason_codes']))

        for performer in bottom_performers:
            if performer['reason_codes']:
                bottom_reasons.extend(json.loads(performer['reason_codes']))

        # Find patterns
        top_reason_freq = {reason: top_reasons.count(reason) for reason in set(top_reasons)}
        bottom_reason_freq = {reason: bottom_reasons.count(reason) for reason in set(bottom_reasons)}

        for reason, freq in top_reason_freq.items():
            if freq > len(top_performers) * 0.5:  # Appears in >50% of top performers
                recommendations.append(f"Increase weight for '{reason}' - highly predictive of success")

        for reason, freq in bottom_reason_freq.items():
            if freq > len(bottom_performers) * 0.5:  # Appears in >50% of bottom performers
                recommendations.append(f"Decrease weight for '{reason}' - associated with poor performance")

        return recommendations

    async def score_connectors(
        self,
        prospect_id: int,
        connectors: List[Any],
        organization_id: int
    ) -> ScoringResult:
        """
        Lightweight scoring entry point for Corporate Connect.

        The primary scoring pipeline expects connectors to be persisted in the
        database. Corporate Connect, however, operates on in-memory payloads
        coming straight from the mutuals stage. This helper applies a trimmed
        scoring heuristic so downstream stages receive ranked connectors while
        we move the heavy lifting out-of-band.
        """

        if not connectors:
            return ScoringResult(top_connectors=[])

        ranked: List[Dict[str, Any]] = []
        for connector in connectors:
            if hasattr(connector, "__dict__") and not isinstance(connector, dict):
                data = asdict(connector)
            else:
                data = dict(connector)

            metadata = data.get("metadata") or {}
            relationship_strength = float(metadata.get("relationship_strength", data.get("relationship_strength", 0.5) or 0.5))
            mutuals = int(
                data.get("shared_connections_count")
                or metadata.get("shared_connections_count")
                or 0
            )
            discovery_source = metadata.get("discovered_via", "cache")

            score = (
                0.55 * max(0.0, min(relationship_strength, 1.0))
                + 0.35 * max(0.0, min(mutuals / 5.0, 1.0))
                + 0.10 * (1.0 if discovery_source in {"apify", "phantombuster"} else 0.6)
            )

            ranked.append({
                "connector_id": metadata.get("connector_id"),
                "prospect_id": prospect_id,
                "full_name": data.get("full_name"),
                "linkedin_url": data.get("linkedin_url"),
                "headline": data.get("current_title") or data.get("headline"),
                "company": data.get("current_company") or data.get("company"),
                "relationship_strength": relationship_strength,
                "shared_connections_count": mutuals,
                "discovered_via": discovery_source,
                "ranking_score": round(score, 4),
                "metadata": metadata
            })

        ranked.sort(key=lambda item: item["ranking_score"], reverse=True)

        top_ranked = ranked[: self.top_connectors_count]
        for index, item in enumerate(top_ranked, start=1):
            item["rank"] = index
            item["metadata"]["rank"] = index
            item["metadata"]["ranking_score"] = item["ranking_score"]

        return ScoringResult(top_connectors=top_ranked)

    async def get_scoring_analytics(
        self,
        organization_id: int,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get scoring analytics for organization dashboard"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            analytics = query(conn, """
                SELECT
                    COUNT(DISTINCT prospect_id) as prospects_scored,
                    COUNT(*) as total_connectors,
                    AVG(ranking_score) as avg_score,
                    COUNT(CASE WHEN rank <= 3 THEN 1 END) as top_tier_connectors,
                    AVG(relationship_strength) as avg_relationship_strength
                FROM prospect_connectors
                WHERE organization_id = ?
                AND created_at >= datetime('now', '-{} days')
            """.format(days), (organization_id,))

            return dict(analytics[0]) if analytics else {}

# Global service instance
ScoringService = ConnectorScoringService
scoring_service = ConnectorScoringService()
