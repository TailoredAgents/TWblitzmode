"""
Email Service Layer
Orchestrates email enrichment, generation, campaign management, and sending
"""

import asyncio
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import json

from api.database import get_db
from integrations.cufinder_client import (
    get_cufinder_client,
    EmailEnrichmentResult,
)
from integrations.sendgrid_client import get_sendgrid_client, EmailResult
from integrations.openai_client import get_openai_client, GeneratedMessage
from services.error_classifier import error_classifier
from core.settings import settings

# Import agent logger for real-time communication and cost tracking
try:
    from services.agent_logger import agent_logger, AgentEventType
    agent_logging_available = True
except ImportError:
    logging.warning("Agent logger not available in email service")
    agent_logging_available = False

# Communication Hub integration
try:
    from services.communication_client import CommunicationHubClient, MessageType, MessagePriority
    from services.message_translator import MessageTranslator, BusinessContext
    from services.metadata_enricher import MetadataEnricher
    communication_hub_available = True
except ImportError:
    logging.warning("Communication Hub not available in email service")
    communication_hub_available = False

logger = logging.getLogger(__name__)

# Singleton service instance
email_service = None

class CampaignStatus(Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    PAUSED = "paused"
    CANCELLED = "cancelled"

class ChannelPreference(Enum):
    EMAIL_ONLY = "email_only"
    LINKEDIN_ONLY = "linkedin_only"
    EMAIL_FIRST = "email_first"
    LINKEDIN_FIRST = "linkedin_first"
    HYBRID = "hybrid"

@dataclass
class EnrichmentStats:
    total_contacts: int = 0
    already_had_email: int = 0
    enriched_count: int = 0
    failed_count: int = 0
    high_confidence: int = 0
    low_confidence: int = 0
    suppressed: int = 0
    total_cost: float = 0.0

@dataclass
class CampaignStats:
    total_recipients: int = 0
    sent: int = 0
    delivered: int = 0
    opened: int = 0
    clicked: int = 0
    replied: int = 0
    bounced: int = 0
    unsubscribed: int = 0
    conversion_rate: float = 0.0
    cost: float = 0.0

class EmailService:
    """
    Core email service orchestrating all email operations
    """
    
    def __init__(self):
        self.warmup_limits = {
            0: 20,    # Day 1-7
            7: 50,    # Day 8-14
            14: 100,  # Day 15-21
            21: 200,  # Day 22-30
            30: 500   # Day 30+
        }

        # Default confidence thresholds
        self.min_confidence_for_send = 0.7
        self.min_confidence_for_auto_send = 0.85

        # Communication Hub integration
        if communication_hub_available:
            self.communication_hub = CommunicationHubClient()
            self.message_translator = MessageTranslator()
            self.metadata_enricher = MetadataEnricher()
        else:
            self.communication_hub = None
            self.message_translator = None
            self.metadata_enricher = None

        # Rate limiting service
        try:
            from services.rate_limiting_service import rate_limiter
            self.rate_limiter = rate_limiter
            logger.info("✅ Email service initialized with rate limiting")
        except ImportError:
            logger.warning("⚠️ Rate limiting service not available for email service")
            self.rate_limiter = None

    async def _deliver_email(
        self,
        tenant_id: int,
        payload: Dict[str, Any],
        provider: str = "sendgrid",
    ) -> EmailResult:
        """Enforce SendGrid-only delivery."""
        if provider != "sendgrid":
            raise RuntimeError("Only SendGrid is permitted for outbound email delivery.")
        sendgrid = get_sendgrid_client(tenant_id)
        return await sendgrid.send_email(**payload)
        
    async def enrich_contacts(
        self,
        contact_ids: List[int],
        tenant_id: int,
        force_refresh: bool = False,
        min_confidence: float = 0.0,
        db=None
    ) -> Dict:
        """
        Enrich multiple contacts with email addresses
        Returns detailed statistics about the enrichment process
        """
        if not db:
            import asyncio
            loop = asyncio.get_event_loop()
            db = await loop.run_in_executor(None, get_db)
            
        stats = EnrichmentStats(total_contacts=len(contact_ids))
        results = []
        
        # Get CUFinder client for this tenant
        cufinder = get_cufinder_client(tenant_id, fail_on_missing=False)
        if not cufinder.is_configured:
            reason = (
                cufinder.configuration_reason
                or "CUFinder email enrichment is disabled until credentials are configured."
            )
            logger.warning(f"CUFinder disabled for tenant {tenant_id}: {reason}")
            return {
                'enriched_count': 0,
                'failed_count': len(contact_ids),
                'already_had_email': 0,
                'high_confidence': 0,
                'low_confidence': 0,
                'suppressed': 0,
                'total_cost': 0.0,
                'results': [],
                'status': 'configuration_required',
                'message': reason,
            }
        
        cursor = db.cursor()
        
        for contact_id in contact_ids:
            try:
                # Get contact details (async)
                loop = asyncio.get_event_loop()
                contact = await loop.run_in_executor(None, self._get_contact_details, cursor, contact_id, tenant_id)
                if not contact:
                    stats.failed_count += 1
                    continue
                
                # Check if suppressed
                if contact.get('suppressed'):
                    stats.suppressed += 1
                    logger.info(f"Contact {contact_id} is suppressed, skipping")
                    continue
                
                # Check if already has high-confidence email
                if (contact.get('email') and 
                    contact.get('email_confidence', 0) >= self.min_confidence_for_send and 
                    not force_refresh):
                    stats.already_had_email += 1
                    continue
                
                # Enrich with CUFinder (primary path)
                enrichment_result = await cufinder.enrich_email(
                    linkedin_url=contact.get('linkedin_url'),
                    full_name=contact.get('full_name'),
                    company=contact.get('company'),
                    company_domain=contact.get('company_domain'),
                    title=contact.get('title') or contact.get('headline')
                )
                
                if enrichment_result.email and enrichment_result.confidence >= min_confidence:
                    # Update contact with enriched email (async)
                    await loop.run_in_executor(None, self._update_contact_email, cursor, contact_id, enrichment_result, tenant_id)
                    
                    stats.enriched_count += 1
                    if enrichment_result.confidence >= self.min_confidence_for_auto_send:
                        stats.high_confidence += 1
                    else:
                        stats.low_confidence += 1
                    
                    stats.total_cost += enrichment_result.cost
                    
                    results.append({
                        'contact_id': contact_id,
                        'email': enrichment_result.email,
                        'confidence': enrichment_result.confidence,
                        'source': enrichment_result.source
                    })
                else:
                    # Last-resort fallback: Use PB Profile Scraper to enrich profile fields, then retry CUFinder
                    logger.info(f"CUFinder did not find email for contact {contact_id}; attempting PB profile enrichment as last resort")
                    fallback_email = None
                    fallback_conf = 0.0
                    try:
                        linkedin_url = contact.get('linkedin_url')
                        if linkedin_url:
                            from integrations.phantombuster_client import phantombuster_client
                            container_id = phantombuster_client.launch_profile_scraper([linkedin_url], tenant_id=tenant_id)
                            pb_results = phantombuster_client.poll_and_fetch_results(container_id)
                            if pb_results:
                                # Choose the matching result if present
                                chosen = None
                                for item in pb_results:
                                    url = item.get('profileUrl') or item.get('linkedinUrl') or item.get('publicProfileUrl') or item.get('url')
                                    if url and linkedin_url.split('?')[0].rstrip('/') in url:
                                        chosen = item
                                        break
                                if not chosen:
                                    chosen = pb_results[0]
                                normalized = phantombuster_client.normalize_profile_result(chosen)
                                # Update contact details to improve CUFinder matching
                                try:
                                    update_fields = []
                                    update_vals = []
                                    for col in ['full_name','company','title','location']:
                                        val = normalized.get(col)
                                        if val and (not contact.get(col) or str(contact.get(col)).strip() == ''):
                                            update_fields.append(f"{col} = %s")
                                            update_vals.append(val)
                                    # If PB returned an email, store it as unverified and mark source
                                    if normalized.get('email'):
                                        update_fields.extend(["email = %s", "email_source = %s", "email_verified = %s", "email_last_verified = %s"])
                                        update_vals.extend([normalized['email'], 'profile_scraper', False, datetime.now()])
                                    if update_fields:
                                        update_vals.extend([contact_id, tenant_id])
                                        cursor.execute(
                                            f"UPDATE contacts SET {', '.join(update_fields)}, updated_at = %s WHERE id = %s AND tenant_id = %s",
                                            tuple(update_vals[:-2] + [datetime.now(), update_vals[-2], update_vals[-1]])
                                        )
                                        db.commit()
                                except Exception as up_e:
                                    logger.warning(f"Failed to update contact fields from PB data: {up_e}")
                                # Retry CUFinder with enriched data
                                enriched_retry = await cufinder.enrich_email(
                                    linkedin_url=linkedin_url,
                                    full_name=normalized.get('full_name') or contact.get('full_name'),
                                    company=normalized.get('company') or contact.get('company'),
                                    company_domain=contact.get('company_domain'),
                                    title=normalized.get('title') or contact.get('title') or contact.get('headline')
                                )
                                if enriched_retry.email and enriched_retry.confidence >= min_confidence:
                                    await loop.run_in_executor(None, self._update_contact_email, cursor, contact_id, enriched_retry, tenant_id)
                                    stats.enriched_count += 1
                                    if enriched_retry.confidence >= self.min_confidence_for_auto_send:
                                        stats.high_confidence += 1
                                    else:
                                        stats.low_confidence += 1
                                    stats.total_cost += enriched_retry.cost
                                    results.append({
                                        'contact_id': contact_id,
                                        'email': enriched_retry.email,
                                        'confidence': enriched_retry.confidence,
                                        'source': enriched_retry.source
                                    })
                                    continue  # Move to next contact
                        # If no LinkedIn URL or no PB results, mark failed
                        logger.info(f"PB profile enrichment unavailable or no improvement for contact {contact_id}")
                    except Exception as pb_e:
                        logger.warning(f"PB last-resort profile enrichment failed for contact {contact_id}: {pb_e}")
                    # Record as failed after fallback path
                    stats.failed_count += 1
                    logger.info(f"No email found for contact {contact_id} after last-resort fallback")
                    
            except Exception as e:
                logger.error(f"Failed to enrich contact {contact_id}: {e}")
                stats.failed_count += 1
                
                error_classifier.record_provider_error(
                    'cufinder', 'enrichment_error', str(e), tenant_id
                )
        
        db.commit()
        
        # Log enrichment stats
        logger.info(f"Enrichment complete: {stats.enriched_count}/{stats.total_contacts} enriched, "
                   f"{stats.failed_count} failed, cost: ${stats.total_cost:.2f}")
        
        return {
            'enriched_count': stats.enriched_count,
            'failed_count': stats.failed_count,
            'already_had_email': stats.already_had_email,
            'high_confidence': stats.high_confidence,
            'low_confidence': stats.low_confidence,
            'suppressed': stats.suppressed,
            'total_cost': stats.total_cost,
            'results': results
        }
    
    async def create_campaign(
        self,
        prospect_id: int,
        introducer_ids: List[int],
        tenant_id: int,
        user_id: int,
        message_type: str = 'warm_intro',
        use_ai: bool = True,
        channel_preference: str = 'email_first',
        schedule_send: Optional[datetime] = None,
        ab_test: bool = False,
        db=None
    ) -> Dict:
        """
        Create an email campaign with AI-generated or template messages
        """
        if not db:
            db = get_db()
            
        cursor = db.cursor()
        
        # Get prospect details
        cursor.execute("""
            SELECT * FROM prospects 
            WHERE id = %s AND tenant_id = %s
        """, (prospect_id, tenant_id))
        prospect = cursor.fetchone()
        
        if not prospect:
            raise ValueError(f"Prospect {prospect_id} not found")
        
        # Get tenant context for AI generation
        cursor.execute("""
            SELECT t.name as company_name, u.first_name, u.last_name
            FROM tenants t
            JOIN users u ON u.tenant_id = t.id
            WHERE t.id = %s AND u.id = %s
        """, (tenant_id, user_id))
        tenant_context = cursor.fetchone()
        
        # Create campaign record
        cursor.execute("""
            INSERT INTO email_campaigns 
            (tenant_id, user_id, prospect_id, name, status, message_type, 
             total_recipients, created_at, scheduled_for)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            tenant_id, user_id, prospect_id,
            f"Campaign for {prospect['full_name']}",
            CampaignStatus.SCHEDULED.value if schedule_send else CampaignStatus.DRAFT.value,
            message_type,
            len(introducer_ids),
            datetime.now(),
            schedule_send
        ))
        
        campaign_id = cursor.lastrowid
        messages = []
        
        # Get AI client if using AI
        openai_client = await get_openai_client(tenant_id) if use_ai else None
        
        # Process each introducer
        for introducer_id in introducer_ids:
            cursor.execute("""
                SELECT c.*, mc.connection_strength, mc.shared_connections_count
                FROM contacts c
                LEFT JOIN mutual_connections mc ON c.id = mc.contact_id
                WHERE c.id = %s AND c.tenant_id = %s
            """, (introducer_id, tenant_id))
            
            introducer = cursor.fetchone()
            
            if not introducer:
                logger.warning(f"Introducer {introducer_id} not found")
                continue
            
            # Check email availability
            if channel_preference in ['email_only', 'email_first'] and not introducer.get('email'):
                logger.info(f"No email for introducer {introducer_id}, skipping or using LinkedIn")
                if channel_preference == 'email_only':
                    continue
            
            # Generate message
            if use_ai and openai_client:
                # Build context for AI
                ai_context = {
                    'sender_name': f"{tenant_context['first_name']} {tenant_context['last_name']}",
                    'sender_company': tenant_context['company_name'],
                    'connection_strength': introducer.get('connection_strength', 'professional'),
                    'shared_connections': introducer.get('shared_connections_count', 0),
                    'value_proposition': self._get_value_proposition(tenant_id)
                }
                
                # Generate with AI
                if ab_test:
                    # Generate variants for A/B testing
                    variants = await openai_client.generate_variants(
                        introducer=dict(introducer),
                        prospect=dict(prospect),
                        message_type=message_type,
                        context=ai_context,
                        num_variants=3
                    )

                    # Log AI cost for A/B testing variants
                    if agent_logging_available:
                        await agent_logger.log_cost_incurred(
                            agent_id="email_service",
                            service_name="OpenAI GPT-4 A/B Testing",
                            cost_amount=0.15,  # Estimated $0.15 for 3 variants
                            cost_currency="USD",
                            cost_details={
                                "model": "gpt-4",
                                "variants_generated": 3,
                                "cost_per_variant": 0.05,
                                "prospect_company": prospect.get('company', 'Unknown'),
                                "introducer_name": introducer.get('full_name', 'Unknown')
                            },
                            tenant_id=str(tenant_id),
                            workflow_id=str(campaign_id)
                        )
                    
                    for variant in variants:
                        # Store each variant
                        cursor.execute("""
                            INSERT INTO email_ab_tests
                            (tenant_id, campaign_id, variant_name, subject, body, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            tenant_id, campaign_id, variant.variant_id,
                            variant.subject, variant.body, datetime.now()
                        ))
                        
                        if variant.variant_id == "variant_1":  # Use first variant as default
                            subject = variant.subject
                            body = variant.body
                else:
                    # Generate single message
                    generated = await openai_client.generate_email(
                        introducer=dict(introducer),
                        prospect=dict(prospect),
                        message_type=message_type,
                        context=ai_context
                    )

                    # Log AI cost for single email generation
                    if agent_logging_available:
                        await agent_logger.log_cost_incurred(
                            agent_id="email_service",
                            service_name="OpenAI GPT-4 Email Generation",
                            cost_amount=0.05,  # Estimated $0.05 per email
                            cost_currency="USD",
                            cost_details={
                                "model": "gpt-4",
                                "message_type": message_type,
                                "prospect_company": prospect.get('company', 'Unknown'),
                                "introducer_name": introducer.get('full_name', 'Unknown'),
                                "tokens_estimated": 500
                            },
                            tenant_id=str(tenant_id),
                            workflow_id=str(campaign_id)
                        )
                    subject = generated.subject
                    body = generated.body
            else:
                # Use template
                template = self._get_template(message_type, tenant_id)
                subject = self._render_template(template['subject'], introducer, prospect)
                body = self._render_template(template['body'], introducer, prospect)
            
            # Determine channel
            channel = self._determine_channel(
                introducer, 
                channel_preference, 
                introducer.get('email_confidence', 0)
            )
            
            # Queue the message
            cursor.execute("""
                INSERT INTO outreach_queue
                (tenant_id, prospect_id, contact_id, campaign_id, channel, 
                 subject, message, status, send_priority, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                tenant_id, prospect_id, introducer_id, campaign_id, channel,
                subject, body, 'pending',
                self._calculate_priority(introducer),
                datetime.now()
            ))
            
            messages.append({
                'id': cursor.lastrowid,
                'introducer': introducer['full_name'],
                'channel': channel,
                'subject': subject,
                'body': body[:200] + '...' if len(body) > 200 else body
            })
        
        db.commit()
        
        logger.info(f"Campaign {campaign_id} created with {len(messages)} messages")

        # Send campaign creation message to Communication Hub
        await self._notify_user(
            organization_id,
            user_id,
            "campaign_created",
            f"Generated {len(messages)} introduction emails for {prospect['full_name']}",
            {
                "campaign_id": campaign_id,
                "prospect_name": prospect['full_name'],
                "prospect_company": prospect.get('company', 'Unknown'),
                "total_messages": len(messages),
                "message_type": message_type,
                "channel_preference": channel_preference,
                "ai_generated": use_ai
            }
        )

        return {
            'id': campaign_id,
            'prospect_id': prospect_id,
            'prospect_name': prospect['full_name'],
            'total_messages': len(messages),
            'status': CampaignStatus.SCHEDULED.value if schedule_send else CampaignStatus.DRAFT.value,
            'messages': messages
        }
    
    async def send_campaign(
        self,
        campaign_id: int,
        tenant_id: int,
        test_mode: bool = False
    ) -> CampaignStats:
        """
        Execute campaign sending with warmup limits and tracking
        """
        import asyncio
        loop = asyncio.get_event_loop()
        db = await loop.run_in_executor(None, get_db)
        cursor = db.cursor()
        
        stats = CampaignStats()
        
        # Get campaign details
        cursor.execute("""
            SELECT * FROM email_campaigns 
            WHERE id = %s AND tenant_id = %s
        """, (campaign_id, tenant_id))
        
        campaign = cursor.fetchone()
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        
        # Update campaign status
        cursor.execute("""
            UPDATE email_campaigns 
            SET status = %s, started_at = %s
            WHERE id = %s
        """, (CampaignStatus.SENDING.value, datetime.now(), campaign_id))
        
        # Get daily limit
        daily_limit = self._get_daily_send_limit(tenant_id, db)
        sent_today = self._get_sent_today_count(tenant_id, db)
        available_quota = max(0, daily_limit - sent_today)
        
        if available_quota == 0:
            logger.warning(f"Daily limit reached for tenant {tenant_id}")
            return stats
        
        # Get pending messages ordered by priority
        cursor.execute("""
            SELECT oq.*, c.email, c.email_confidence, c.full_name
            FROM outreach_queue oq
            JOIN contacts c ON oq.contact_id = c.id
            WHERE oq.campaign_id = %s 
            AND oq.status = 'pending'
            AND oq.channel IN ('email', 'email_first')
            ORDER BY oq.send_priority DESC
            LIMIT %s
        """, (campaign_id, available_quota))
        
        messages = cursor.fetchall()
        stats.total_recipients = len(messages)
        
        for message in messages:
            try:
                # Skip if no email or low confidence
                if not message['email'] or message['email_confidence'] < self.min_confidence_for_send:
                    logger.info(f"Skipping message {message['id']}: No email or low confidence")
                    continue
                
                # Send email
                if test_mode:
                    # In test mode, just mark as sent
                    result = EmailResult(success=True, message_id="test_" + str(message['id']))
                else:
                    result = await self._deliver_email(
                        tenant_id,
                        {
                            "to_email": message['email'],
                            "subject": message['subject'],
                            "body": message['message'],
                            "categories": [f"campaign_{campaign_id}"],
                            "custom_args": {
                                'campaign_id': str(campaign_id),
                                'message_id': str(message['id'])
                            },
                        },
                    )
                
                if result.success:
                    # Update message status and metrics (async)
                    await loop.run_in_executor(None, self._update_message_sent, cursor, message, tenant_id)
                    
                    stats.sent += 1
                    stats.cost += result.cost
                else:
                    # Handle send failure (async)
                    await loop.run_in_executor(None, self._update_message_failed, cursor, message['id'])
                    
                    logger.error(f"Failed to send message {message['id']}: {result.error_message}")
                
            except Exception as e:
                logger.error(f"Error sending message {message['id']}: {e}")
                
                await loop.run_in_executor(None, self._update_message_failed, cursor, message['id'])
        
        # Update campaign stats (async)
        await loop.run_in_executor(None, self._update_campaign_stats, cursor, campaign_id, stats)
        
        db.commit()
        db.close()
        
        logger.info(f"Campaign {campaign_id} sent: {stats.sent}/{stats.total_recipients} messages")

        # Send campaign completion message to Communication Hub
        user_id = campaign.get('user_id', 1)
        organization_id = campaign.get('organization_id', 1)  # Get org from campaign

        if stats.sent > 0:
            await self._notify_user(
                organization_id,
                user_id,
                "campaign_completed",
                f"Campaign completed: {stats.sent}/{stats.total_recipients} emails sent successfully",
                {
                    "campaign_id": campaign_id,
                    "emails_sent": stats.sent,
                    "total_recipients": stats.total_recipients,
                    "success_rate": f"{(stats.sent / stats.total_recipients * 100):.1f}%" if stats.total_recipients > 0 else "0%",
                    "cost_usd": stats.cost,
                    "campaign_status": "completed"
                }
            )
        else:
            await self._notify_user(
                organization_id,
                user_id,
                "campaign_failed",
                "Campaign completed with no emails sent - check recipient configurations",
                {
                    "campaign_id": campaign_id,
                    "emails_sent": 0,
                    "total_recipients": stats.total_recipients,
                    "issues": "No emails sent - may be due to rate limits or configuration issues"
                }
            )

        return stats
    
    async def get_campaign_preview(
        self,
        campaign_id: int,
        tenant_id: int,
        db=None
    ) -> Dict:
        """
        Get preview of campaign messages before sending
        """
        if not db:
            db = get_db()
            
        cursor = db.cursor()
        
        # Get campaign details
        cursor.execute("""
            SELECT c.*, p.full_name as prospect_name
            FROM email_campaigns c
            JOIN prospects p ON c.prospect_id = p.id
            WHERE c.id = %s AND c.tenant_id = %s
        """, (campaign_id, tenant_id))
        
        campaign = cursor.fetchone()
        
        # Get messages with introducer details
        cursor.execute("""
            SELECT oq.*, c.full_name, c.email, c.company
            FROM outreach_queue oq
            JOIN contacts c ON oq.contact_id = c.id
            WHERE oq.campaign_id = %s
            ORDER BY oq.send_priority DESC
        """, (campaign_id,))
        
        messages = cursor.fetchall()
        
        # Get A/B test variants if any
        cursor.execute("""
            SELECT * FROM email_ab_tests
            WHERE campaign_id = %s
        """, (campaign_id,))
        
        variants = cursor.fetchall()
        
        return {
            'campaign': dict(campaign) if campaign else None,
            'messages': [dict(m) for m in messages],
            'variants': [dict(v) for v in variants],
            'total_messages': len(messages)
        }
    
    async def get_tenant_metrics(
        self,
        tenant_id: int,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        db=None
    ) -> Dict:
        """
        Get comprehensive email metrics for tenant dashboard
        """
        if not db:
            db = get_db()
            
        cursor = db.cursor()
        
        # Default to last 30 days
        if not date_from:
            date_from = datetime.now() - timedelta(days=30)
        if not date_to:
            date_to = datetime.now()
        
        # Get overall stats
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT em.contact_id) as total_contacts,
                SUM(em.sent_count) as total_sent,
                SUM(em.bounce_count) as total_bounced,
                SUM(em.open_count) as total_opened,
                SUM(em.click_count) as total_clicked,
                SUM(em.reply_count) as total_replied,
                COUNT(DISTINCT CASE WHEN em.suppressed = 1 THEN em.contact_id END) as total_suppressed
            FROM email_metrics em
            WHERE em.tenant_id = %s
            AND em.last_sent BETWEEN %s AND %s
        """, (tenant_id, date_from, date_to))
        
        overall = cursor.fetchone() or {}
        
        # Calculate rates
        total_sent = overall.get('total_sent', 0) or 0
        open_rate = (overall.get('total_opened', 0) / total_sent * 100) if total_sent > 0 else 0
        click_rate = (overall.get('total_clicked', 0) / total_sent * 100) if total_sent > 0 else 0
        reply_rate = (overall.get('total_replied', 0) / total_sent * 100) if total_sent > 0 else 0
        bounce_rate = (overall.get('total_bounced', 0) / total_sent * 100) if total_sent > 0 else 0
        
        # Get today's stats
        cursor.execute("""
            SELECT COUNT(*) as sent_today
            FROM outreach_queue
            WHERE tenant_id = %s 
            AND channel = 'email'
            AND DATE(sent_at) = DATE(%s)
        """, (tenant_id, datetime.now()))
        
        today_stats = cursor.fetchone()
        
        # Get daily limit and warmup status
        cursor.execute("""
            SELECT daily_limit, warmup_status, current_reputation_score
            FROM tenant_email_settings
            WHERE tenant_id = %s
        """, (tenant_id,))
        
        settings = cursor.fetchone() or {}
        
        # Get weekly performance
        cursor.execute("""
            SELECT 
                DATE(sent_at) as day,
                COUNT(*) as sent,
                SUM(CASE WHEN email_status = 'opened' THEN 1 ELSE 0 END) as opened,
                SUM(CASE WHEN email_status = 'replied' THEN 1 ELSE 0 END) as replied
            FROM outreach_queue
            WHERE tenant_id = %s
            AND channel = 'email'
            AND sent_at >= DATE_SUB(%s, INTERVAL 7 DAY)
            GROUP BY DATE(sent_at)
            ORDER BY day
        """, (tenant_id, datetime.now()))
        
        weekly_data = cursor.fetchall()
        
        # Get campaign performance
        cursor.execute("""
            SELECT 
                id,
                name,
                status,
                sent_count,
                open_count,
                reply_count,
                (reply_count * 100.0 / NULLIF(sent_count, 0)) as conversion_rate
            FROM email_campaigns
            WHERE tenant_id = %s
            AND created_at BETWEEN %s AND %s
            ORDER BY created_at DESC
            LIMIT 10
        """, (tenant_id, date_from, date_to))
        
        campaigns = cursor.fetchall()
        
        # Get cost breakdown
        cursor.execute("""
            SELECT 
                service,
                SUM(count) as total_operations,
                SUM(total_cost) as total_cost
            FROM email_costs
            WHERE tenant_id = %s
            AND date BETWEEN %s AND %s
            GROUP BY service
        """, (tenant_id, date_from, date_to))
        
        costs = cursor.fetchall()
        
        return {
            'overall_stats': {
                'total_contacts': overall.get('total_contacts', 0),
                'total_sent': total_sent,
                'total_bounced': overall.get('total_bounced', 0),
                'total_opened': overall.get('total_opened', 0),
                'total_clicked': overall.get('total_clicked', 0),
                'total_replied': overall.get('total_replied', 0),
                'total_suppressed': overall.get('total_suppressed', 0)
            },
            'rates': {
                'open_rate': round(open_rate, 1),
                'click_rate': round(click_rate, 1),
                'reply_rate': round(reply_rate, 1),
                'bounce_rate': round(bounce_rate, 1)
            },
            'today': {
                'sent_today': today_stats.get('sent_today', 0) if today_stats else 0,
                'daily_limit': settings.get('daily_limit', 100),
                'remaining': max(0, settings.get('daily_limit', 100) - (today_stats.get('sent_today', 0) if today_stats else 0))
            },
            'warmup': {
                'status': settings.get('warmup_status', 'not_started'),
                'reputation_score': settings.get('current_reputation_score', 50)
            },
            'weekly_data': [dict(d) for d in weekly_data],
            'campaigns': [dict(c) for c in campaigns],
            'costs': {
                'breakdown': [dict(c) for c in costs],
                'total': sum(c['total_cost'] for c in costs)
            }
        }
    
    async def update_tenant_settings(
        self,
        tenant_id: int,
        tenant_settings: Dict,
        db=None
    ) -> Dict:
        """
        Update tenant email settings
        """
        if not db:
            db = get_db()
            
        cursor = db.cursor()
        
        # Encrypt sensitive fields
        from api.security import enc
        
        if 'sendgrid_api_key' in tenant_settings:
            tenant_settings['sendgrid_api_key_encrypted'] = enc(tenant_settings.pop('sendgrid_api_key'))
        
        if 'cufinder_api_key' in tenant_settings:
            tenant_settings['cufinder_api_key_encrypted'] = enc(tenant_settings.pop('cufinder_api_key'))
        
        # Build update query
        update_fields = []
        values = []
        for key, value in tenant_settings.items():
            update_fields.append(f"{key} = %s")
            values.append(value)
        
        values.append(datetime.now())  # updated_at
        values.append(tenant_id)
        
        cursor.execute(f"""
            UPDATE tenant_email_settings 
            SET {', '.join(update_fields)}, updated_at = %s
            WHERE tenant_id = %s
        """, values)
        
        # If email changed, initiate domain verification
        if 'from_email' in tenant_settings:
            domain = tenant_settings['from_email'].split('@')[1]
            sendgrid = get_sendgrid_client(tenant_id)
            verification = await sendgrid.verify_domain(domain)
            
            # Store verification status
            cursor.execute("""
                UPDATE tenant_email_settings
                SET domain_verified = FALSE
                WHERE tenant_id = %s
            """, (tenant_id,))
            
            db.commit()
            
            return {
                'success': True,
                'domain_verification': verification
            }
        
        db.commit()
        
        return {'success': True}
    
    async def process_webhook_event(self, event: Dict, db=None):
        """
        Process incoming webhook events from SendGrid
        """
        if not db:
            import asyncio
            loop = asyncio.get_event_loop()
            db = await loop.run_in_executor(None, get_db)
            
        # Extract tenant_id from custom args
        tenant_id = event.get('tenant_id') or event.get('unique_args', {}).get('tenant_id')
        
        if tenant_id:
            sendgrid = get_sendgrid_client(int(tenant_id))
            await sendgrid.process_webhook_event(event)
    
    def _get_daily_send_limit(self, tenant_id: int, db) -> int:
        """Get daily sending limit based on warmup status"""
        cursor = db.cursor()
        cursor.execute("""
            SELECT daily_limit, warmup_status, warmup_started_at
            FROM tenant_email_settings
            WHERE tenant_id = %s
        """, (tenant_id,))
        
        settings = cursor.fetchone()
        if not settings:
            return 20  # Default for new tenants
        
        # Calculate based on warmup period
        if settings['warmup_status'] == 'warming' and settings['warmup_started_at']:
            days_warming = (datetime.now() - settings['warmup_started_at']).days
            
            for day_threshold, limit in sorted(self.warmup_limits.items()):
                if days_warming >= day_threshold:
                    current_limit = limit
                else:
                    break
            
            return min(current_limit, settings['daily_limit'])
        
        return settings['daily_limit']
    
    def _get_sent_today_count(self, tenant_id: int, db) -> int:
        """Get count of emails sent today"""
        cursor = db.cursor()
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM outreach_queue
            WHERE tenant_id = %s
            AND channel = 'email'
            AND DATE(sent_at) = DATE(%s)
        """, (tenant_id, datetime.now()))
        
        result = cursor.fetchone()
        return result['count'] if result else 0
    
    def _determine_channel(
        self,
        contact: Dict,
        preference: str,
        email_confidence: float
    ) -> str:
        """Determine best channel based on preference and data availability"""
        has_email = contact.get('email') and email_confidence >= self.min_confidence_for_send
        has_linkedin = contact.get('linkedin_url')
        
        if preference == 'email_only':
            return 'email' if has_email else None
        elif preference == 'linkedin_only':
            return 'linkedin' if has_linkedin else None
        elif preference == 'email_first':
            return 'email' if has_email else ('linkedin' if has_linkedin else None)
        elif preference == 'linkedin_first':
            return 'linkedin' if has_linkedin else ('email' if has_email else None)
        else:  # hybrid
            # Choose based on confidence and availability
            if has_email and email_confidence >= self.min_confidence_for_auto_send:
                return 'email'
            elif has_linkedin:
                return 'linkedin'
            elif has_email:
                return 'email'
        
        return None
    
    def _calculate_priority(self, contact: Dict) -> int:
        """Calculate send priority based on various factors"""
        priority = 0
        
        # Connection strength
        strength = contact.get('connection_strength', 0)
        if isinstance(strength, str):
            strength_map = {'weak': 1, 'medium': 5, 'strong': 10}
            priority += strength_map.get(strength, 0)
        else:
            priority += min(strength, 10)
        
        # Email confidence
        priority += int(contact.get('email_confidence', 0) * 10)
        
        # Shared connections
        priority += min(contact.get('shared_connections_count', 0), 10)
        
        # Has previous interaction
        if contact.get('previous_interaction'):
            priority += 5
        
        return priority
    
    def _get_template(self, message_type: str, tenant_id: int) -> Dict:
        """Get email template for tenant"""
        # Could fetch from database, for now return default
        templates = {
            'warm_intro': {
                'subject': "Introduction to {prospect_name}?",
                'body': """Hi {introducer_first_name},

I hope this message finds you well. I noticed you're connected with {prospect_name} at {prospect_company}, and I was wondering if you might be open to making an introduction.

{value_proposition}

Would you be comfortable making this introduction? I'm happy to provide more context if helpful.

Best regards,
{sender_name}"""
            }
        }
        
        return templates.get(message_type, templates['warm_intro'])
    
    def _render_template(self, template: str, introducer: Dict, prospect: Dict) -> str:
        """Render template with data"""
        replacements = {
            '{introducer_first_name}': introducer.get('full_name', '').split()[0] or 'there',
            '{introducer_name}': introducer.get('full_name', ''),
            '{prospect_name}': prospect.get('full_name', ''),
            '{prospect_company}': prospect.get('company', 'their company'),
            '{prospect_title}': prospect.get('title', prospect.get('headline', '')),
            '{value_proposition}': self._get_value_proposition(prospect.get('tenant_id')),
            '{sender_name}': '[Your name]'  # Should be fetched from user context
        }
        
        result = template
        for key, value in replacements.items():
            result = result.replace(key, value)
        
        return result
    
    def _get_value_proposition(self, tenant_id: int) -> str:
        """Get tenant's value proposition"""
        # Could be stored in database per tenant
        return "We're working on innovative solutions that could benefit your team, and I believe a conversation could be mutually valuable."

    def validate_team_member_send_from(self, team_member: Dict[str, Any]) -> Dict[str, Any]:
        """Validate team member send-from configuration"""
        validation_result = {
            "is_valid": False,
            "send_from_name": None,
            "send_from_email": None,
            "warnings": [],
            "errors": []
        }

        # Check send_from_name
        send_from_name = team_member.get('send_from_name') or team_member.get('name')
        if not send_from_name:
            validation_result["errors"].append("No send-from name configured")
        else:
            validation_result["send_from_name"] = send_from_name

        # Check send_from_email
        send_from_email = team_member.get('send_from_email') or team_member.get('email')
        if not send_from_email:
            validation_result["errors"].append("No send-from email configured")
        else:
            # Basic email validation
            import re
            email_pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
            if not re.match(email_pattern, send_from_email):
                validation_result["errors"].append(f"Invalid send-from email format: {send_from_email}")
            else:
                validation_result["send_from_email"] = send_from_email

        # Check if using fallback values
        if not team_member.get('send_from_name') and team_member.get('name'):
            validation_result["warnings"].append("Using team member name as send-from name (consider setting explicit send_from_name)")

        if not team_member.get('send_from_email') and team_member.get('email'):
            validation_result["warnings"].append("Using team member email as send-from email (consider setting explicit send_from_email)")

        # Overall validation status
        validation_result["is_valid"] = len(validation_result["errors"]) == 0

        return validation_result
    
    async def send_introduction_email(
        self,
        introducer: Dict,
        prospect: Dict,
        subject: str,
        body: str,
        tenant_id: int,
        user_id: int = None
    ) -> EmailResult:
        """
        Send introduction email through configured email provider with rate limiting
        """
        try:
            # Check rate limits before processing
            identifier = str(tenant_id)

            if self.rate_limiter:
                try:
                    rate_limit_result = await self.rate_limiter.check_rate_limit("sendgrid", identifier)

                    if rate_limit_result.action.value == "deny":
                        error_msg = f"SendGrid rate limit exceeded for tenant {tenant_id}. Reset in {rate_limit_result.wait_seconds:.1f}s"
                        logger.warning(f"🚨 {error_msg}")
                        return EmailResult(success=False, error=error_msg)

                    elif rate_limit_result.action.value == "wait":
                        logger.info(f"⏳ SendGrid rate limit - waiting {rate_limit_result.wait_seconds:.1f}s")
                        await asyncio.sleep(rate_limit_result.wait_seconds)

                    # Log quota usage warnings
                    if rate_limit_result.quota_used_percentage > 80:
                        logger.warning(f"⚠️ SendGrid quota {rate_limit_result.quota_used_percentage:.1f}% used for tenant {tenant_id}")

                except Exception as e:
                    logger.error(f"❌ Rate limit check failed for SendGrid: {e}")
                    # Continue with request but log error

            # Validate team member send-from configuration
            validation = self.validate_team_member_send_from(introducer)
            if not validation["is_valid"]:
                error_msg = f"Team member send-from configuration invalid: {', '.join(validation['errors'])}"
                logger.error(f"❌ {error_msg}")
                return EmailResult(success=False, error=error_msg)

            # Log any warnings
            for warning in validation["warnings"]:
                logger.warning(f"⚠️ {warning}")

            # Use validated send-from information
            send_from_name = validation["send_from_name"]
            send_from_email = validation["send_from_email"]

            recipient_email = introducer.get('email')
            if not recipient_email:
                raise RuntimeError("Introducer is missing an email address.")

            # Prepare email data with proper send-from information
            email_data = {
                'to': recipient_email,
                'subject': subject,
                'body': body,
                'from_name': send_from_name,
                'from_email': send_from_email,
                'reply_to': send_from_email  # Use send-from email as reply-to
            }
            
            # Send email
            result = await self._deliver_email(tenant_id, {
                "to_email": email_data['to'],
                "subject": email_data['subject'],
                "body": email_data['body'],
                "from_email": email_data['from_email'],
                "from_name": email_data['from_name'],
                "reply_to": email_data['reply_to'],
            })

            # Record API call result
            if self.rate_limiter:
                if result.success:
                    await self.rate_limiter.record_api_success("sendgrid")
                else:
                    await self.rate_limiter.record_api_error("sendgrid", "send_failed")

            # Log success
            if result.success:
                logger.info(f"✅ Successfully sent introduction email to {prospect.get('email')} "
                           f"from {send_from_name} <{send_from_email}>")
                if tenant_id:
                    error_classifier.record_provider_success('sendgrid', tenant_id)
            else:
                logger.error(f"❌ Failed to send introduction email: {result.error}")

            return result
            
        except Exception as e:
            # Record exception error
            if self.rate_limiter:
                await self.rate_limiter.record_api_error("sendgrid", "exception")

            logger.error(f"❌ Failed to send introduction email for tenant {tenant_id}: {e}")
            if tenant_id:
                error_classifier.record_provider_error('sendgrid', 'send_failed', str(e), tenant_id)

            return EmailResult(success=False, error=str(e))

    # Helper methods for async database operations
    def _get_contact_details(self, cursor, contact_id: int, tenant_id: int):
        """Helper method for getting contact details synchronously"""
        cursor.execute("""
            SELECT c.*, em.suppressed 
            FROM contacts c
            LEFT JOIN email_metrics em ON c.id = em.contact_id AND em.tenant_id = %s
            WHERE c.id = %s AND c.tenant_id = %s
        """, (tenant_id, contact_id, tenant_id))
        return cursor.fetchone()

    def _update_contact_email(self, cursor, contact_id: int, enrichment_result, tenant_id: int):
        """Helper method for updating contact email synchronously"""
        cursor.execute("""
            UPDATE contacts 
            SET email = %s, 
                email_confidence = %s,
                email_source = %s,
                email_verified = %s,
                email_last_verified = %s,
                updated_at = %s
            WHERE id = %s
        """, (
            enrichment_result.email,
            enrichment_result.confidence,
            enrichment_result.source,
            enrichment_result.confidence > 0.9,
            datetime.now(),
            datetime.now(),
            contact_id
        ))
        
        # Create or update email metrics
        cursor.execute("""
            INSERT INTO email_metrics (contact_id, tenant_id, created_at)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE updated_at = %s
        """, (contact_id, tenant_id, datetime.now(), datetime.now()))

    def _update_message_sent(self, cursor, message: Dict, tenant_id: int):
        """Helper method for updating message status when sent"""
        cursor.execute("""
            UPDATE outreach_queue 
            SET status = 'sent', 
                sent_at = %s, 
                email_status = 'sent'
            WHERE id = %s
        """, (datetime.now(), message['id']))
        
        # Update metrics
        cursor.execute("""
            UPDATE email_metrics 
            SET sent_count = sent_count + 1,
                last_sent = %s
            WHERE contact_id = %s AND tenant_id = %s
        """, (datetime.now(), message['contact_id'], tenant_id))

    def _update_message_failed(self, cursor, message_id: int):
        """Helper method for updating message status when failed"""
        cursor.execute("""
            UPDATE outreach_queue 
            SET status = 'failed',
                email_status = 'failed'
            WHERE id = %s
        """, (message_id,))

    def _update_campaign_stats(self, cursor, campaign_id: int, stats):
        """Helper method for updating campaign statistics"""
        from .shared_types import CampaignStatus
        cursor.execute("""
            UPDATE email_campaigns 
            SET status = %s,
                sent_count = %s,
                completed_at = %s
            WHERE id = %s
        """, (
            CampaignStatus.SENT.value if stats.sent == stats.total_recipients else CampaignStatus.SENDING.value,
            stats.sent,
            datetime.now() if stats.sent == stats.total_recipients else None,
            campaign_id
        ))

    async def _notify_user(self, organization_id: int, user_id: int, event_type: str, message: str, metadata: Dict[str, Any] = None):
        """Send notification to user via Communication Hub"""
        if not self.communication_hub or not self.message_translator:
            return

        try:
            # Determine appropriate business context based on event type
            if event_type == "campaign_created":
                context = BusinessContext.PROGRESS_REPORT
            elif event_type == "campaign_completed":
                context = BusinessContext.SUCCESS_NOTIFICATION
            elif event_type == "campaign_failed":
                context = BusinessContext.ERROR_RESOLUTION
            elif event_type.startswith("email_"):
                context = BusinessContext.OPERATIONAL_UPDATE
            else:
                context = BusinessContext.OPERATIONAL_UPDATE

            # Translate to business-friendly language
            business_message = await self.message_translator.translate(
                message,
                context,
                include_technical_details=False
            )

            # Enrich with organizational context
            enriched_metadata = await self.metadata_enricher.enrich(
                metadata or {},
                organization_id=organization_id,
                user_id=user_id,
                service_name="email_service"
            )

            # Send notification
            await self.communication_hub.send_message(
                message_type=MessageType.SERVICE_UPDATE,
                content=business_message,
                tenant_id=str(organization_id),
                user_id=str(user_id),
                metadata=enriched_metadata,
                priority=MessagePriority.HIGH if event_type in ["campaign_failed"] else MessagePriority.MEDIUM
            )

        except Exception as e:
            logger.warning(f"Failed to send user notification: {e}")

# Singleton instance
email_service = EmailService()
