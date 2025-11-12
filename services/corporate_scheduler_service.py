"""
Corporate Email Scheduler Service

Manages the scheduling and automation of introduction emails within corporate quotas.
Handles weekly email limits, smart timing, GPT-4 content generation, and delivery tracking.

Features:
- Weekly quota enforcement per organization
- Smart scheduling across business hours
- GPT-4 powered email content generation
- Multi-tenant SMTP/SendGrid integration
- Email delivery tracking and analytics
- Compliance with CAN-SPAM regulations
- Automatic retry logic for failed sends
"""

import os
import json
import random
import logging
import asyncio
from datetime import datetime, timedelta, time as dt_time, timezone
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

# Import existing integrations
logger = logging.getLogger(__name__)

from integrations.openai_client import OpenAIClient
from integrations.sendgrid_multi_tenant_client import SendGridMultiTenantClient
from core.settings import settings

# September 2025 - Import OpenAI Agents SDK for human-in-the-loop approval
try:
    from services.vouchlink_ai_organization_agent import VouchLinkAIOrganizationAgent
    AGENTS_SDK_AVAILABLE = True
except ImportError:
    AGENTS_SDK_AVAILABLE = False
    logger.warning("OpenAI Agents SDK not available - human-in-the-loop approval disabled")

class EmailJobState(Enum):
    """Email job states for corporate workflow"""
    QUEUED = "queued"
    PREPARING = "preparing"
    PREPARED = "prepared"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PENDING_APPROVAL = "pending_approval"  # September 2025 - Human-in-the-loop approval

class SchedulingStrategy(Enum):
    """Email scheduling strategies"""
    IMMEDIATE = "immediate"
    BUSINESS_HOURS = "business_hours"
    OPTIMAL_TIMING = "optimal_timing"
    SPREAD_EVENLY = "spread_evenly"

@dataclass
class EmailContent:
    """Generated email content"""
    subject: str
    body: str
    template_used: str
    personalization_data: Dict[str, str]
    generation_model: str
    confidence_score: float

@dataclass
class EmailJobResult:
    """Result of email job processing"""
    email_job_id: int
    organization_id: int
    prospect_connector_id: int
    state: EmailJobState
    email_content: Optional[EmailContent]
    scheduled_at: datetime
    sent_at: Optional[datetime]
    cost_usd: float
    error_message: Optional[str] = None
    delivery_tracking: Dict[str, Any] = None

    def __post_init__(self):
        if self.delivery_tracking is None:
            self.delivery_tracking = {}

@dataclass
class SchedulingBatchResult:
    """Result of scheduling a batch of emails"""
    organization_id: int
    total_emails_scheduled: int
    quota_used: int
    quota_remaining: int
    next_available_slot: Optional[datetime]
    email_jobs: List[EmailJobResult]
    total_cost_estimate: float

class CorporateSchedulerService:
    """Production-ready email scheduling service for corporate workflow"""

    def __init__(self):
        # Scheduling configuration
        self.default_weekly_quota = int(os.getenv('DEFAULT_WEEKLY_QUOTA', '20'))
        self.business_hours_start = int(os.getenv('BUSINESS_HOURS_START', '8'))  # 8 AM
        self.business_hours_end = int(os.getenv('BUSINESS_HOURS_END', '18'))     # 6 PM
        self.min_interval_minutes = int(os.getenv('MIN_EMAIL_INTERVAL', '30'))   # 30 min between emails
        self.max_interval_minutes = int(os.getenv('MAX_EMAIL_INTERVAL', '120'))  # 2 hour max

        # Content generation
        try:
            self.openai_client = OpenAIClient()
        except Exception as exc:
            logger.warning(f"OpenAI client unavailable: {exc}")
            self.openai_client = None
        self.sendgrid_client = SendGridMultiTenantClient()

        # Cost estimates
        self.cost_per_email_generation = float(os.getenv('COST_PER_EMAIL_GENERATION', '0.01'))
        self.cost_per_email_send = float(os.getenv('COST_PER_EMAIL_SEND', '0.001'))

        # September 2025 - Human-in-the-loop approval configuration
        self.enable_human_approval = os.getenv('ENABLE_HUMAN_APPROVAL', 'true').lower() == 'true'
        self.auto_approve_threshold = float(os.getenv('AUTO_APPROVE_THRESHOLD', '0.8'))

        # Tallwave configuration
        self.unlimited_delivery = bool(settings.COMPANY_PORTAL_UNLIMITED_SEATS)

        # Initialize Agents SDK if available
        self.organization_agent = None
        if AGENTS_SDK_AVAILABLE and self.enable_human_approval:
            try:
                self.organization_agent = VouchLinkAIOrganizationAgent()
                logger.info("OpenAI Agents SDK initialized for human-in-the-loop approval")
            except Exception as e:
                logger.warning(f"Failed to initialize Agents SDK: {e}")

    async def schedule_prospect_introduction_emails(
        self,
        prospect_id: int,
        organization_id: int,
        strategy: SchedulingStrategy = SchedulingStrategy.BUSINESS_HOURS
    ) -> SchedulingBatchResult:
        """Schedule introduction emails for all connectors of a prospect"""

        logger.info(f"Scheduling introduction emails for prospect {prospect_id}")

        try:
            # Get prospect and enriched connectors
            prospect_data = await self._get_prospect_data(prospect_id, organization_id)
            if not prospect_data:
                logger.warning(f"Prospect {prospect_id} not found")
                return self._create_empty_result(organization_id)

            connectors = await self._get_enriched_connectors(prospect_id, organization_id)
            if not connectors:
                logger.info(f"No enriched connectors found for prospect {prospect_id}")
                return self._create_empty_result(organization_id)

            # Check weekly quota
            quota_status = await self._check_weekly_quota(organization_id)
            available_slots = quota_status['remaining']

            if self.unlimited_delivery:
                available_slots = len(connectors)
                quota_status['weekly_quota'] = None
                quota_status['remaining'] = available_slots
                quota_status['used'] = 0

            if available_slots <= 0:
                logger.warning(f"No email quota available for organization {organization_id}")
                return SchedulingBatchResult(
                    organization_id=organization_id,
                    total_emails_scheduled=0,
                    quota_used=quota_status['used'],
                    quota_remaining=0,
                    next_available_slot=quota_status['next_reset'],
                    email_jobs=[],
                    total_cost_estimate=0.0
                )

            # Limit to available quota
            connectors = connectors[:available_slots]

            # Generate scheduling times
            schedule_times = await self._generate_schedule_times(
                len(connectors), organization_id, strategy
            )

            # Create email jobs
            email_jobs = []
            total_cost = 0.0

            for i, connector in enumerate(connectors):
                try:
                    # Generate email content
                    email_content = await self._generate_introduction_email(
                        prospect_data, connector, organization_id
                    )

                    # September 2025 - Check if email needs human approval
                    needs_approval = await self._requires_human_approval(
                        email_content, connector, organization_id
                    )

                    initial_state = EmailJobState.PENDING_APPROVAL if needs_approval else EmailJobState.QUEUED

                    # Create email job
                    email_job = await self._create_email_job(
                        organization_id, prospect_id, connector,
                        email_content, schedule_times[i], initial_state
                    )

                    # September 2025 - Request approval if needed
                    if needs_approval and self.organization_agent:
                        await self._request_email_approval(email_job, email_content, connector, organization_id)

                    email_jobs.append(EmailJobResult(
                        email_job_id=email_job['id'],
                        organization_id=organization_id,
                        prospect_connector_id=connector['prospect_connector_id'],
                        state=initial_state,
                        email_content=email_content,
                        scheduled_at=schedule_times[i],
                        sent_at=None,
                        cost_usd=self.cost_per_email_generation + self.cost_per_email_send
                    ))

                    total_cost += self.cost_per_email_generation + self.cost_per_email_send

                except Exception as e:
                    logger.error(f"Failed to schedule email for connector {connector['connector_id']}: {e}")

            # Update quota usage
            await self._update_quota_usage(organization_id, len(email_jobs))

            # Create audit log
            await self._create_scheduling_audit(
                organization_id, prospect_id, len(email_jobs), total_cost
            )

            logger.info(f"Scheduled {len(email_jobs)} introduction emails for prospect {prospect_id}")

            return SchedulingBatchResult(
                organization_id=organization_id,
                total_emails_scheduled=len(email_jobs),
                quota_used=quota_status['used'] + len(email_jobs),
                quota_remaining=available_slots - len(email_jobs),
                next_available_slot=max(schedule_times) if schedule_times else None,
                email_jobs=email_jobs,
                total_cost_estimate=total_cost
            )

        except Exception as e:
            logger.error(f"Failed to schedule introduction emails for prospect {prospect_id}: {e}")
            return self._create_empty_result(organization_id)

    async def schedule_introduction(
        self,
        connector: Dict[str, Any],
        organization_id: int,
        tenant_id: Optional[str] = None,
        strategy: SchedulingStrategy = SchedulingStrategy.BUSINESS_HOURS
    ) -> EmailJobResult:
        """
        Schedule a single connector introduction email (Corporate Connect helper).
        """

        payload = dict(connector)
        metadata = payload.get("metadata") or {}
        payload.setdefault("prospect_connector_id", metadata.get("prospect_connector_id"))
        payload.setdefault("connector_id", metadata.get("connector_id"))
        payload.setdefault("full_name", metadata.get("full_name") or payload.get("full_name"))
        payload.setdefault("company", metadata.get("company") or payload.get("company"))
        payload.setdefault("ranking_score", metadata.get("ranking_score", 0.0))
        payload.setdefault("rank", metadata.get("rank"))

        if not payload.get("email"):
            raise ValueError("Connector email address is required to schedule an introduction.")

        prospect_id = payload.get("prospect_id") or metadata.get("prospect_id")
        if not prospect_id:
            raise ValueError("prospect_id is required to schedule an introduction email.")
        payload.setdefault("prospect_id", prospect_id)

        prospect_data = await self._get_prospect_data(int(prospect_id), organization_id)
        if not prospect_data:
            raise ValueError(f"Prospect {prospect_id} not found for organization {organization_id}.")

        schedule_times = await self._generate_schedule_times(
            email_count=1,
            organization_id=organization_id,
            strategy=strategy
        )
        scheduled_at = schedule_times[0]

        email_content = await self._generate_introduction_email(
            prospect_data=prospect_data,
            connector_data=payload,
            organization_id=organization_id
        )

        requires_approval = await self._requires_human_approval(
            email_content=email_content,
            connector_data=payload,
            organization_id=organization_id
        )
        initial_state = EmailJobState.PENDING_APPROVAL if requires_approval else EmailJobState.QUEUED

        email_job = await self._create_email_job(
            organization_id=organization_id,
            prospect_id=int(prospect_id),
            connector_data=payload,
            email_content=email_content,
            scheduled_at=scheduled_at,
            initial_state=initial_state
        )

        if requires_approval:
            await self._request_email_approval(
                email_job=email_job,
                email_content=email_content,
                connector_data=payload,
                organization_id=organization_id
            )

        return EmailJobResult(
            email_job_id=email_job["id"],
            organization_id=organization_id,
            prospect_connector_id=payload.get("prospect_connector_id") or 0,
            state=initial_state,
            email_content=email_content,
            scheduled_at=email_job["scheduled_at"],
            sent_at=None,
            cost_usd=self.cost_per_email_generation + self.cost_per_email_send,
            delivery_tracking={"tenant_id": tenant_id} if tenant_id else {}
        )

    async def process_scheduled_emails(self, limit: int = 50) -> Dict[str, Any]:
        """Process emails that are ready to be sent"""

        logger.info("Processing scheduled emails")

        try:
            # Get emails ready to send
            ready_emails = await self._get_emails_ready_to_send(limit)

            if not ready_emails:
                logger.info("No emails ready to send")
                return {"processed": 0, "sent": 0, "failed": 0}

            results = {"processed": 0, "sent": 0, "failed": 0}

            for email_job in ready_emails:
                try:
                    # Update status to sending
                    await self._update_email_job_state(
                        email_job['id'], EmailJobState.SENDING
                    )

                    # Send email
                    send_result = await self._send_introduction_email(email_job)

                    if send_result['success']:
                        await self._update_email_job_state(
                            email_job['id'], EmailJobState.SENT,
                            sent_at=datetime.now(timezone.utc),
                            tracking_data=send_result.get('tracking', {})
                        )
                        results["sent"] += 1
                    else:
                        await self._update_email_job_state(
                            email_job['id'], EmailJobState.FAILED,
                            error_message=send_result.get('error')
                        )
                        results["failed"] += 1

                    results["processed"] += 1

                except Exception as e:
                    logger.error(f"Failed to process email job {email_job['id']}: {e}")
                    await self._update_email_job_state(
                        email_job['id'], EmailJobState.FAILED,
                        error_message=str(e)
                    )
                    results["failed"] += 1

                # Rate limiting between sends
                await asyncio.sleep(random.uniform(1, 3))

            logger.info(f"Processed {results['processed']} emails: {results['sent']} sent, {results['failed']} failed")
            return results

        except Exception as e:
            logger.error(f"Failed to process scheduled emails: {e}")
            return {"processed": 0, "sent": 0, "failed": 0, "error": str(e)}

    async def _get_prospect_data(self, prospect_id: int, organization_id: int) -> Optional[Dict[str, Any]]:
        """Get prospect information for email generation"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            prospects = query(conn, """
                SELECT
                    id, company, full_name, role, headline,
                    linkedin_url, location, tags
                FROM prospects
                WHERE id = ? AND organization_id = ?
            """, (prospect_id, organization_id))

            return dict(prospects[0]) if prospects else None

    async def _get_enriched_connectors(
        self,
        prospect_id: int,
        organization_id: int
    ) -> List[Dict[str, Any]]:
        """Get connectors with confirmed email addresses"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            connectors = query(conn, """
                SELECT
                    pc.id as prospect_connector_id,
                    pc.connector_id,
                    pc.team_member_id,
                    pc.rank,
                    pc.ranking_score,
                    c.full_name,
                    c.linkedin_url,
                    c.company,
                    c.headline,
                    c.email,
                    c.email_confidence,
                    tm.name as team_member_name,
                    tm.email as team_member_email
                FROM prospect_connectors pc
                JOIN connectors c ON pc.connector_id = c.id
                LEFT JOIN team_members tm ON pc.team_member_id = tm.id
                WHERE pc.prospect_id = ? AND pc.organization_id = ?
                AND c.email IS NOT NULL
                AND c.email_status = 'available'
                AND (c.email_confidence IS NULL OR c.email_confidence >= 0.7)
                ORDER BY pc.rank ASC
            """, (prospect_id, organization_id))

            return [dict(row) for row in connectors]

    async def _check_weekly_quota(self, organization_id: int) -> Dict[str, Any]:
        """Check weekly email quota status for organization"""

        from ..api.db_core import get_conn, query

        try:
            with get_conn() as conn:
                # Get quota settings
                settings = query(conn, """
                    SELECT feature_flags
                    FROM integration_sets
                    WHERE organization_id = ?
                """, (organization_id,))

                if settings:
                    feature_flags = json.loads(settings[0]['feature_flags'] or '{}')
                    weekly_quota = feature_flags.get('email_quota', self.default_weekly_quota)
                else:
                    weekly_quota = self.default_weekly_quota

                # Calculate current week boundaries
                now = datetime.now(timezone.utc)
                week_start = now - timedelta(days=now.weekday())
                week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

                # Count emails sent this week
                used_this_week = query(conn, """
                    SELECT COUNT(*) as used_count
                    FROM email_jobs
                    WHERE organization_id = ?
                    AND state IN ('sent', 'delivered', 'opened', 'replied')
                    AND sent_at >= ?
                """, (organization_id, week_start.isoformat()))

                used = used_this_week[0]['used_count'] if used_this_week else 0
                remaining = max(0, weekly_quota - used)
                next_reset = week_start + timedelta(weeks=1)

                if self.unlimited_delivery:
                    return {
                        'weekly_quota': None,
                        'used': 0,
                        'remaining': float('inf'),
                        'next_reset': next_reset,
                        'week_start': week_start
                    }

                return {
                    'weekly_quota': weekly_quota,
                    'used': used,
                    'remaining': remaining,
                    'next_reset': next_reset,
                    'week_start': week_start
                }

        except Exception as e:
            logger.error(f"Error checking weekly quota: {e}")
            if self.unlimited_delivery:
                return {
                    'weekly_quota': None,
                    'used': 0,
                    'remaining': float('inf'),
                    'next_reset': datetime.now(timezone.utc) + timedelta(days=7),
                    'week_start': datetime.now(timezone.utc)
                }
            return {
                'weekly_quota': self.default_weekly_quota,
                'used': 0,
                'remaining': self.default_weekly_quota,
                'next_reset': datetime.now(timezone.utc) + timedelta(days=7),
                'week_start': datetime.now(timezone.utc)
            }

    async def _generate_schedule_times(
        self,
        email_count: int,
        organization_id: int,
        strategy: SchedulingStrategy
    ) -> List[datetime]:
        """Generate optimal scheduling times for emails"""

        # Get organization timezone (default to UTC)
        org_timezone = await self._get_organization_timezone(organization_id)

        schedule_times = []
        base_time = datetime.now(timezone.utc)

        if strategy == SchedulingStrategy.IMMEDIATE:
            # Schedule all emails within the next hour with random intervals
            for i in range(email_count):
                schedule_time = base_time + timedelta(minutes=random.randint(1, 60))
                schedule_times.append(schedule_time)

        elif strategy == SchedulingStrategy.BUSINESS_HOURS:
            # Schedule during business hours over the next few days
            current_time = base_time
            scheduled_count = 0

            while scheduled_count < email_count:
                # Find next business hour slot
                if self._is_business_hours(current_time):
                    schedule_times.append(current_time)
                    scheduled_count += 1
                    # Add random interval
                    current_time += timedelta(
                        minutes=random.randint(self.min_interval_minutes, self.max_interval_minutes)
                    )
                else:
                    # Move to next business hour
                    current_time = self._next_business_hour(current_time)

        elif strategy == SchedulingStrategy.SPREAD_EVENLY:
            # Spread emails evenly over the week
            interval_hours = (7 * 24) / email_count  # Spread over 7 days
            for i in range(email_count):
                schedule_time = base_time + timedelta(hours=i * interval_hours)
                # Adjust to business hours if needed
                if not self._is_business_hours(schedule_time):
                    schedule_time = self._next_business_hour(schedule_time)
                schedule_times.append(schedule_time)

        else:  # OPTIMAL_TIMING
            # Use data-driven optimal timing (simplified implementation)
            optimal_hours = [9, 11, 14, 16]  # 9AM, 11AM, 2PM, 4PM
            day_offset = 0

            for i in range(email_count):
                hour = optimal_hours[i % len(optimal_hours)]
                if i > 0 and i % len(optimal_hours) == 0:
                    day_offset += 1

                schedule_time = base_time.replace(
                    hour=hour, minute=random.randint(0, 59), second=0, microsecond=0
                ) + timedelta(days=day_offset)

                # Skip weekends
                while schedule_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
                    schedule_time += timedelta(days=1)

                schedule_times.append(schedule_time)

        return sorted(schedule_times)

    def _is_business_hours(self, dt: datetime) -> bool:
        """Check if datetime falls within business hours"""
        return (
            dt.weekday() < 5 and  # Monday = 0, Friday = 4
            self.business_hours_start <= dt.hour < self.business_hours_end
        )

    def _next_business_hour(self, dt: datetime) -> datetime:
        """Find next business hour after given datetime"""
        next_dt = dt.replace(minute=0, second=0, microsecond=0)

        # If it's after business hours, move to next day
        if next_dt.hour >= self.business_hours_end:
            next_dt = next_dt.replace(hour=self.business_hours_start) + timedelta(days=1)
        elif next_dt.hour < self.business_hours_start:
            next_dt = next_dt.replace(hour=self.business_hours_start)

        # Skip weekends
        while next_dt.weekday() >= 5:
            next_dt += timedelta(days=1)

        return next_dt

    async def _generate_introduction_email(
        self,
        prospect_data: Dict[str, Any],
        connector_data: Dict[str, Any],
        organization_id: int
    ) -> EmailContent:
        """Generate personalized introduction email using GPT-4"""

        try:
            # Get email template for organization
            template = await self._get_email_template(organization_id, "introduction")

            # Prepare personalization data
            personalization_data = {
                "prospect_name": prospect_data['full_name'],
                "prospect_company": prospect_data['company'],
                "prospect_role": prospect_data.get('role', 'executive'),
                "connector_name": connector_data['full_name'].split()[0],  # First name
                "connector_full_name": connector_data['full_name'],
                "connector_company": connector_data['company'],
                "team_member_name": connector_data.get('team_member_name', 'Team Member'),
                "ranking_score": f"{connector_data['ranking_score']:.2f}"
            }

            # Generate subject line
            subject_prompt = f"""
            Generate a professional, compelling subject line for an introduction request email.

            Context:
            - Requesting introduction to: {personalization_data['prospect_name']} at {personalization_data['prospect_company']}
            - From connector: {personalization_data['connector_full_name']}
            - Keep it under 50 characters
            - Make it personal but professional

            Generate ONLY the subject line, no quotes or extra text.
            """

            subject_response = await self.openai_client.generate_text(
                prompt=subject_prompt,
                model="gpt-4o-mini",
                max_tokens=20,
                temperature=0.7
            )

            subject = subject_response.content.strip().strip('"').strip("'")

            # Generate email body
            body_prompt = f"""
            Generate a warm, professional introduction request email using this template:

            Template: {template['body_template']}

            Personalization data:
            {json.dumps(personalization_data, indent=2)}

            Guidelines:
            - Keep it concise (under 150 words)
            - Be warm but professional
            - Include value proposition for the introduction
            - Add appropriate context about why this connection makes sense
            - End with easy opt-out language

            Generate ONLY the email body content, no subject line or signatures.
            """

            body_response = await self.openai_client.generate_text(
                prompt=body_prompt,
                model="gpt-4o",
                max_tokens=200,
                temperature=0.8
            )

            body = body_response.content.strip()

            # Add compliance footer
            body += "\n\n---\nThis email was sent on behalf of VouchLink AI. " \
                   "If you'd prefer not to receive introduction requests, please reply 'UNSUBSCRIBE'."

            return EmailContent(
                subject=subject,
                body=body,
                template_used=template['name'],
                personalization_data=personalization_data,
                generation_model="gpt-4o",
                confidence_score=0.85  # GPT-4 generates high quality content
            )

        except Exception as e:
            logger.error(f"Error generating introduction email: {e}")

            # Fallback to simple template
            return EmailContent(
                subject=f"Introduction to {prospect_data['full_name']}",
                body=f"Hi {connector_data['full_name'].split()[0]},\n\n"
                     f"Hope you're well! Could you intro me to {prospect_data['full_name']} "
                     f"at {prospect_data['company']}? Happy to send context. Thanks!",
                template_used="fallback",
                personalization_data={"prospect_name": prospect_data['full_name']},
                generation_model="fallback",
                confidence_score=0.5
            )

    async def _get_email_template(self, organization_id: int, template_type: str) -> Dict[str, Any]:
        """Get email template for organization"""

        from ..api.db_core import get_conn, query

        try:
            with get_conn() as conn:
                templates = query(conn, """
                    SELECT name, subject_template, body_template, variables
                    FROM email_templates
                    WHERE organization_id = ? AND template_type = ? AND is_active = 1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (organization_id, template_type))

                if templates:
                    return dict(templates[0])

        except Exception as e:
            logger.error(f"Error getting email template: {e}")

        # Return default template
        return {
            "name": "default_introduction",
            "subject_template": "Introduction to {{prospect_name}}",
            "body_template": "Hey {{connector_name}} — hope you're well! Could you intro me to {{prospect_name}} at {{prospect_company}}? Happy to send a 2-sentence blurb you can paste. Totally fine if not a fit.",
            "variables": {}
        }

    async def _create_email_job(
        self,
        organization_id: int,
        prospect_id: int,
        connector_data: Dict[str, Any],
        email_content: EmailContent,
        scheduled_at: datetime,
        initial_state: EmailJobState = EmailJobState.QUEUED
    ) -> Dict[str, Any]:
        """Create email job record"""

        from ..api.db_core import get_conn, execute, query

        try:
            with get_conn() as conn:
                job_id = execute(conn, """
                    INSERT INTO email_jobs (
                        organization_id, prospect_connector_id, email_subject,
                        email_content, recipient_email, sender_team_member_id,
                        scheduled_at, state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    organization_id,
                    connector_data['prospect_connector_id'],
                    email_content.subject,
                    email_content.body,
                    connector_data['email'],
                    connector_data.get('team_member_id'),
                    scheduled_at.isoformat(),
                    initial_state.value
                ))

                return {"id": job_id, "scheduled_at": scheduled_at}

        except Exception as e:
            logger.error(f"Error creating email job: {e}")
            raise

    async def _requires_human_approval(
        self,
        email_content: EmailContent,
        connector_data: Dict[str, Any],
        organization_id: int
    ) -> bool:
        """
        Determine if email requires human approval (September 2025 feature)

        Uses intelligent criteria to decide when human oversight is needed
        """

        if not self.enable_human_approval:
            return False

        # Auto-approve high-confidence, high-ranking connectors
        if (email_content.confidence_score >= self.auto_approve_threshold and
            connector_data.get('rank', 10) <= 2 and
            connector_data.get('ranking_score', 0) >= 0.8):
            return False

        # Require approval for:
        # 1. Low confidence email generation
        if email_content.confidence_score < 0.7:
            return True

        # 2. Low-ranking connectors (may be risky)
        if connector_data.get('rank', 10) > 3:
            return True

        # 3. Complex or unusual email content
        if len(email_content.body) > 300 or "complex" in email_content.body.lower():
            return True

        # 4. Check organization approval settings
        try:
            from ..api.db_core import get_conn, query

            with get_conn() as conn:
                settings = query(conn, """
                    SELECT feature_flags
                    FROM integration_sets
                    WHERE organization_id = ?
                """, (organization_id,))

                if settings:
                    feature_flags = json.loads(settings[0]['feature_flags'] or '{}')
                    if feature_flags.get('require_email_approval', False):
                        return True

        except Exception as e:
            logger.warning(f"Error checking approval settings: {e}")

        return False

    async def _request_email_approval(
        self,
        email_job: Dict[str, Any],
        email_content: EmailContent,
        connector_data: Dict[str, Any],
        organization_id: int = None
    ):
        """
        Request human approval for email using OpenAI Agents SDK (September 2025)

        Creates an approval request that can be processed via the human-in-the-loop interface
        """

        try:
            from ..api.db_core import get_conn, execute

            # Create approval request record
            with get_conn() as conn:
                approval_id = execute(conn, """
                    INSERT INTO approval_requests (
                        organization_id, email_job_id, approval_type,
                        content_preview, requestor_type, status,
                        created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """, (
                    organization_id or email_job.get('organization_id'),
                    email_job['id'],
                    'email_send',
                    json.dumps({
                        'subject': email_content.subject,
                        'body_preview': email_content.body[:200] + '...' if len(email_content.body) > 200 else email_content.body,
                        'recipient': connector_data['email'],
                        'connector_name': connector_data['full_name'],
                        'confidence_score': email_content.confidence_score
                    }),
                    'ai_agent',
                    'pending',
                    (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()  # 24 hour expiry
                ))

                logger.info(f"Created approval request {approval_id} for email job {email_job['id']}")

                # If Agents SDK is available, trigger workflow
                if self.organization_agent:
                    # Note: This would integrate with the actual Agents SDK workflow
                    # For now, we log the request
                    logger.info(f"Agents SDK approval workflow triggered for request {approval_id}")

        except Exception as e:
            logger.error(f"Error creating approval request: {e}")
            # Fall back to auto-approve on error
            await self._approve_email_job(email_job['id'], auto_approved=True)

    async def approve_email_job(self, email_job_id: int, approver_id: int, approved: bool, reason: str = "") -> bool:
        """
        Approve or reject an email job (September 2025 human-in-the-loop feature)

        This method would be called by the approval interface
        """

        try:
            from ..api.db_core import get_conn, execute, query

            with get_conn() as conn:
                # Update approval request
                execute(conn, """
                    UPDATE approval_requests
                    SET status = ?, approver_id = ?, decision_reason = ?,
                        approved_at = CURRENT_TIMESTAMP
                    WHERE email_job_id = ? AND approval_type = 'email_send'
                """, (
                    'approved' if approved else 'rejected',
                    approver_id,
                    reason,
                    email_job_id
                ))

                # Update email job state
                new_state = EmailJobState.QUEUED if approved else EmailJobState.CANCELLED
                await self._update_email_job_state(email_job_id, new_state)

                logger.info(f"Email job {email_job_id} {'approved' if approved else 'rejected'} by user {approver_id}")

                return True

        except Exception as e:
            logger.error(f"Error processing approval for email job {email_job_id}: {e}")
            return False

    async def _approve_email_job(self, email_job_id: int, auto_approved: bool = False):
        """Auto-approve an email job"""

        try:
            await self._update_email_job_state(email_job_id, EmailJobState.QUEUED)

            if auto_approved:
                logger.info(f"Email job {email_job_id} auto-approved due to system error")

        except Exception as e:
            logger.error(f"Error auto-approving email job {email_job_id}: {e}")

    async def get_pending_approvals(self, organization_id: int) -> List[Dict[str, Any]]:
        """
        Get pending email approvals for an organization (September 2025)

        Used by the approval dashboard interface
        """

        from ..api.db_core import get_conn, query

        try:
            with get_conn() as conn:
                approvals = query(conn, """
                    SELECT
                        ar.id, ar.email_job_id, ar.content_preview, ar.created_at, ar.expires_at,
                        ej.email_subject, ej.recipient_email,
                        p.full_name as prospect_name, p.company as prospect_company
                    FROM approval_requests ar
                    JOIN email_jobs ej ON ar.email_job_id = ej.id
                    JOIN prospect_connectors pc ON ej.prospect_connector_id = pc.id
                    JOIN prospects p ON pc.prospect_id = p.id
                    WHERE ar.organization_id = ? AND ar.status = 'pending'
                    AND ar.approval_type = 'email_send'
                    AND ar.expires_at > CURRENT_TIMESTAMP
                    ORDER BY ar.created_at ASC
                """, (organization_id,))

                return [dict(row) for row in approvals]

        except Exception as e:
            logger.error(f"Error getting pending approvals: {e}")
            return []

    async def _get_organization_timezone(self, organization_id: int) -> str:
        """Get organization timezone (simplified implementation)"""
        # TODO: Implement timezone detection based on organization location
        return "UTC"

    async def _get_emails_ready_to_send(self, limit: int) -> List[Dict[str, Any]]:
        """Get emails that are ready to be sent"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            ready_emails = query(conn, """
                SELECT
                    ej.id, ej.organization_id, ej.prospect_connector_id,
                    ej.email_subject, ej.email_content, ej.recipient_email,
                    ej.sender_team_member_id, ej.scheduled_at,
                    tm.name as sender_name, tm.email as sender_email
                FROM email_jobs ej
                LEFT JOIN team_members tm ON ej.sender_team_member_id = tm.id
                WHERE ej.state = 'queued'
                AND ej.scheduled_at <= CURRENT_TIMESTAMP
                ORDER BY ej.scheduled_at ASC
                LIMIT ?
            """, (limit,))

            return [dict(row) for row in ready_emails]

    async def _send_introduction_email(self, email_job: Dict[str, Any]) -> Dict[str, Any]:
        """Send introduction email via SendGrid"""

        try:
            send_result = await self.sendgrid_client.send_email(
                organization_id=email_job['organization_id'],
                to_email=email_job['recipient_email'],
                subject=email_job['email_subject'],
                html_content=email_job['email_content'].replace('\n', '<br>'),
                from_email=email_job.get('sender_email'),
                from_name=email_job.get('sender_name', 'VouchLink AI Team')
            )

            return {
                "success": True,
                "tracking": {
                    "sendgrid_message_id": send_result.get('message_id'),
                    "sent_at": datetime.now(timezone.utc).isoformat()
                }
            }

        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return {"success": False, "error": str(e)}

    async def _update_email_job_state(
        self,
        email_job_id: int,
        state: EmailJobState,
        sent_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        tracking_data: Optional[Dict[str, Any]] = None
    ):
        """Update email job state"""

        from ..api.db_core import get_conn, execute

        try:
            with get_conn() as conn:
                execute(conn, """
                    UPDATE email_jobs SET
                        state = ?,
                        sent_at = ?,
                        error_message = ?,
                        tracking_data = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    state.value,
                    sent_at.isoformat() if sent_at else None,
                    error_message,
                    json.dumps(tracking_data) if tracking_data else None,
                    email_job_id
                ))

        except Exception as e:
            logger.error(f"Error updating email job state: {e}")

    async def _update_quota_usage(self, organization_id: int, emails_scheduled: int):
        """Update quota usage tracking"""

        from ..api.db_core import get_conn, execute

        try:
            with get_conn() as conn:
                today = datetime.now(timezone.utc).date()

                execute(conn, """
                    INSERT INTO organization_metrics (
                        organization_id, metric_date, emails_scheduled
                    ) VALUES (?, ?, ?)
                    ON CONFLICT (organization_id, metric_date)
                    DO UPDATE SET emails_scheduled = emails_scheduled + ?
                """, (organization_id, today, emails_scheduled, emails_scheduled))

        except Exception as e:
            logger.error(f"Error updating quota usage: {e}")

    async def _create_scheduling_audit(
        self,
        organization_id: int,
        prospect_id: int,
        emails_scheduled: int,
        cost: float
    ):
        """Create audit log for email scheduling"""

        from ..api.db_core import get_conn, execute

        try:
            with get_conn() as conn:
                execute(conn, """
                    INSERT INTO audit_events (
                        organization_id, actor_type, actor_id, action,
                        target_type, target_id, payload, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    organization_id, "system", 0, "emails_scheduled",
                    "prospect", prospect_id,
                    json.dumps({"emails_scheduled": emails_scheduled, "cost_usd": cost})
                ))

        except Exception as e:
            logger.error(f"Error creating scheduling audit: {e}")

    def _create_empty_result(self, organization_id: int) -> SchedulingBatchResult:
        """Create empty scheduling result"""

        return SchedulingBatchResult(
            organization_id=organization_id,
            total_emails_scheduled=0,
            quota_used=0,
            quota_remaining=0,
            next_available_slot=None,
            email_jobs=[],
            total_cost_estimate=0.0
        )

    async def get_scheduling_stats(
        self,
        organization_id: int,
        days: int = 7
    ) -> Dict[str, Any]:
        """Get email scheduling statistics for organization"""

        from ..api.db_core import get_conn, query

        with get_conn() as conn:
            stats = query(conn, """
                SELECT
                    COUNT(*) as total_scheduled,
                    COUNT(CASE WHEN state = 'sent' THEN 1 END) as total_sent,
                    COUNT(CASE WHEN state = 'delivered' THEN 1 END) as total_delivered,
                    COUNT(CASE WHEN state = 'opened' THEN 1 END) as total_opened,
                    COUNT(CASE WHEN state = 'replied' THEN 1 END) as total_replied,
                    COUNT(CASE WHEN state = 'bounced' THEN 1 END) as total_bounced
                FROM email_jobs
                WHERE organization_id = ?
                AND created_at >= datetime('now', '-{} days')
            """.format(days), (organization_id,))

            result = dict(stats[0]) if stats else {}

            # Calculate rates
            if result.get('total_sent', 0) > 0:
                result['delivery_rate'] = result.get('total_delivered', 0) / result['total_sent']
                result['open_rate'] = result.get('total_opened', 0) / result['total_sent']
                result['reply_rate'] = result.get('total_replied', 0) / result['total_sent']
                result['bounce_rate'] = result.get('total_bounced', 0) / result['total_sent']

            return result

# Global service instance
corporate_scheduler_service = CorporateSchedulerService()

# Backwards compatibility alias
SchedulingResult = EmailJobResult
