"""
LinkedIn Campaign Service
Handles LinkedIn messaging campaigns via PhantomBuster integration
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

from api.database import get_db

def _is_postgresql_connection(conn) -> bool:
    """Detect if connection is PostgreSQL"""
    return hasattr(conn, 'info') or 'postgresql' in str(type(conn)).lower()

def _format_placeholder(conn) -> str:
    """Format parameter placeholder for database compatibility"""
    return '%s' if _is_postgresql_connection(conn) else '?'

from api.database import get_db
from integrations.phantombuster_linkedin_client import get_phantombuster_linkedin_client, LinkedInMessageResult, CampaignStatus
from integrations.openai_client import get_openai_email_client
from services.error_classifier import error_classifier

logger = logging.getLogger(__name__)

@dataclass
class LinkedInCampaignRequest:
    prospect_id: int
    introducer_ids: List[int]
    message_type: str
    delay_between_messages: int
    send_connection_requests: bool
    scheduled_for: Optional[datetime]
    custom_message_context: Optional[str]

@dataclass
class LinkedInCampaignResult:
    campaign_id: int
    status: str
    total_recipients: int
    messages_sent: int
    messages_failed: int
    total_cost: float
    phantom_container_id: str
    estimated_completion: Optional[datetime]

class LinkedInService:
    """
    Service for managing LinkedIn messaging campaigns
    """
    
    MESSAGE_TYPES = {
        'direct_introduction': 'Direct Introduction Request',
        'warm_introduction': 'Warm Introduction Request', 
        'meeting_request': 'Meeting Facilitation Request',
        'custom': 'Custom Message'
    }
    
    def normalize_linkedin_url(self, url: str) -> str:
        """Normalize LinkedIn URL to standard format"""
        if not url:
            return ""
        
        # Remove trailing slash and query parameters
        url = url.rstrip('/').split('?')[0]
        
        # Extract profile handle
        if 'linkedin.com/in/' in url:
            handle = url.split('linkedin.com/in/')[-1]
            return f"https://linkedin.com/in/{handle}"
        
        return url
    
    async def create_linkedin_campaign(
        self,
        request: LinkedInCampaignRequest,
        tenant_id: int,
        user_id: int
    ) -> LinkedInCampaignResult:
        """
        Create and optionally launch LinkedIn messaging campaign
        """
        try:
            # Validate introducers belong to tenant
            conn = get_db()
            cursor = conn.cursor()
            
            # Get prospect details
            placeholder = _format_placeholder(conn)
            cursor.execute(f"""
                SELECT full_name, company, title, linkedin_url
                FROM prospects 
                WHERE id = {placeholder} AND tenant_id = {placeholder}
            """, (request.prospect_id, tenant_id))
            
            prospect = cursor.fetchone()
            if not prospect:
                raise ValueError(f"Prospect {request.prospect_id} not found")
            
            # Get introducer details  
            placeholder = _format_placeholder(conn)
            if _is_postgresql_connection(conn):
                cursor.execute("""
                    SELECT id, full_name, email, company, title, linkedin_url
                    FROM contacts
                    WHERE id = ANY(%s) AND tenant_id = %s
                """, (request.introducer_ids, tenant_id))
            else:
                cursor.execute(f"""
                    SELECT id, full_name, email, company, title, linkedin_url
                    FROM contacts
                    WHERE id IN ({','.join('?' * len(request.introducer_ids))}) AND tenant_id = ?
                """, tuple(request.introducer_ids) + (tenant_id,))
            
            introducers = cursor.fetchall()
            if len(introducers) != len(request.introducer_ids):
                raise ValueError("Some introducers not found or not accessible")
            
            # Check daily LinkedIn limits
            daily_usage = await self.get_daily_linkedin_usage(tenant_id)
            if daily_usage['messages_sent_today'] + len(introducers) > 300:  # LinkedIn daily limit
                raise ValueError(f"Daily LinkedIn message limit would be exceeded. Current: {daily_usage['messages_sent_today']}, Requested: {len(introducers)}")
            
            # Create campaign record
            campaign_name = f"{prospect['full_name']} - {request.message_type} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            placeholder = _format_placeholder(conn)
            if _is_postgresql_connection(conn):
                cursor.execute(f"""
                    INSERT INTO linkedin_campaigns (
                        tenant_id, prospect_id, name, message_type, status,
                        delay_between_messages, send_connection_requests,
                        scheduled_for, total_recipients, created_at
                    )
                    VALUES ({', '.join([placeholder] * 10)})
                    RETURNING id
                """, (
                    tenant_id, request.prospect_id, campaign_name, request.message_type,
                    'draft', request.delay_between_messages, request.send_connection_requests,
                    request.scheduled_for, len(introducers), datetime.now()
                ))
                campaign_id = cursor.fetchone()[0]
            else:
                cursor.execute(f"""
                    INSERT INTO linkedin_campaigns (
                        tenant_id, prospect_id, name, message_type, status,
                        delay_between_messages, send_connection_requests,
                        scheduled_for, total_recipients, created_at
                    )
                    VALUES ({', '.join([placeholder] * 10)})
                """, (
                    tenant_id, request.prospect_id, campaign_name, request.message_type,
                    'draft', request.delay_between_messages, request.send_connection_requests,
                    request.scheduled_for, len(introducers), datetime.now()
                ))
                campaign_id = cursor.lastrowid
            
            # Generate personalized messages for each introducer
            ai_client = get_openai_email_client(tenant_id)
            campaign_messages = []
            
            for introducer in introducers:
                try:
                    # Generate LinkedIn message
                    message_content = await ai_client.generate_linkedin_message(
                        prospect={
                            'name': prospect['full_name'],
                            'company': prospect['company'],
                            'title': prospect['title'],
                            'linkedin_url': prospect['linkedin_url']
                        },
                        introducer={
                            'name': introducer['full_name'],
                            'company': introducer['company'],
                            'title': introducer['title']
                        },
                        message_type=request.message_type,
                        custom_context=request.custom_message_context
                    )
                    
                    # Store campaign message
                    placeholder = _format_placeholder(conn)
                    cursor.execute(f"""
                        INSERT INTO linkedin_campaign_messages (
                            campaign_id, introducer_id, linkedin_url, message_content,
                            personalization_data, status, created_at
                        )
                        VALUES ({', '.join([placeholder] * 7)})
                    """, (
                        campaign_id, introducer['id'], introducer['linkedin_url'],
                        message_content, {
                            'prospect': prospect['full_name'],
                            'introducer': introducer['full_name'],
                            'message_type': request.message_type
                        }, 'pending', datetime.now()
                    ))
                    
                    campaign_messages.append({
                        'introducer_id': introducer['id'],
                        'linkedin_url': introducer['linkedin_url'],
                        'message': message_content,
                        'introducer_name': introducer['full_name']
                    })
                    
                except Exception as e:
                    logger.error(f"Failed to generate message for introducer {introducer['id']}: {e}")
                    # Mark this message as failed
                    placeholder = _format_placeholder(conn)
                    cursor.execute(f"""
                        INSERT INTO linkedin_campaign_messages (
                            campaign_id, introducer_id, linkedin_url, message_content,
                            status, error_message, created_at
                        )
                        VALUES ({', '.join([placeholder] * 7)})
                    """, (
                        campaign_id, introducer['id'], introducer['linkedin_url'],
                        f"Failed to generate message: {str(e)}", 'failed', str(e), datetime.now()
                    ))
            
            conn.commit()
            conn.close()
            
            return LinkedInCampaignResult(
                campaign_id=campaign_id,
                status='draft',
                total_recipients=len(introducers),
                messages_sent=0,
                messages_failed=0,
                total_cost=len(campaign_messages) * 0.10,  # $0.10 per message
                phantom_container_id="",
                estimated_completion=None
            )
            
        except Exception as e:
            logger.error(f"Failed to create LinkedIn campaign: {e}")
            raise
    
    async def launch_linkedin_campaign(self, campaign_id: int, tenant_id: int) -> LinkedInCampaignResult:
        """
        Launch a drafted LinkedIn campaign via PhantomBuster
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Get campaign details
            placeholder = _format_placeholder(conn)
            cursor.execute(f"""
                SELECT c.*, p.full_name as prospect_name
                FROM linkedin_campaigns c
                JOIN prospects p ON c.prospect_id = p.id
                WHERE c.id = {placeholder} AND c.tenant_id = {placeholder} AND c.status = 'draft'
            """, (campaign_id, tenant_id))
            
            campaign = cursor.fetchone()
            if not campaign:
                raise ValueError(f"Campaign {campaign_id} not found or not in draft status")
            
            # Get campaign messages
            placeholder = _format_placeholder(conn)
            cursor.execute(f"""
                SELECT lm.*, c.full_name as introducer_name
                FROM linkedin_campaign_messages lm
                JOIN contacts c ON lm.introducer_id = c.id
                WHERE lm.campaign_id = {placeholder} AND lm.status = 'pending'
                ORDER BY lm.id
            """, (campaign_id,))
            
            messages = cursor.fetchall()
            if not messages:
                raise ValueError(f"No pending messages found for campaign {campaign_id}")
            
            # Get PhantomBuster client
            pb_client = get_phantombuster_linkedin_client(tenant_id)
            
            # Prepare messages for bulk sending
            recipients = []
            for msg in messages:
                recipients.append({
                    'linkedin_url': msg['linkedin_url'],
                    'name': msg['introducer_name'],
                    'message': msg['message_content']
                })
            
            # Launch PhantomBuster campaign
            result = await pb_client.send_bulk_linkedin_messages(
                recipients=recipients,
                delay_between_messages=campaign['delay_between_messages'],
                batch_delay=campaign['delay_between_messages'] * 2
            )
            
            if not result.success:
                # Mark campaign as failed
                placeholder = _format_placeholder(conn)
                cursor.execute(f"""
                    UPDATE linkedin_campaigns
                    SET status = 'failed', updated_at = {placeholder}
                    WHERE id = {placeholder}
                """, (datetime.now(), campaign_id))
                
                # Record error
                await error_classifier.record_provider_error(
                    provider='phantombuster',
                    error_code='campaign_launch_failed',
                    error_message=result.error or 'Unknown error',
                    tenant_id=tenant_id
                )
                
                conn.commit()
                conn.close()
                
                return LinkedInCampaignResult(
                    campaign_id=campaign_id,
                    status='failed',
                    total_recipients=len(messages),
                    messages_sent=0,
                    messages_failed=len(messages),
                    total_cost=0.0,
                    phantom_container_id="",
                    estimated_completion=None
                )
            
            # Update campaign with PhantomBuster details
            placeholder = _format_placeholder(conn)
            cursor.execute(f"""
                UPDATE linkedin_campaigns
                SET 
                    status = 'running',
                    phantom_container_id = {placeholder},
                    phantom_id = {placeholder},
                    started_at = {placeholder},
                    total_cost = {placeholder},
                    updated_at = {placeholder}
                WHERE id = {placeholder}
            """, (
                result.container_id, result.phantom_id, datetime.now(),
                result.cost, datetime.now(), campaign_id
            ))
            
            # Update message statuses to 'sending'
            placeholder = _format_placeholder(conn)
            cursor.execute(f"""
                UPDATE linkedin_campaign_messages
                SET status = 'sending', sent_at = {placeholder}
                WHERE campaign_id = {placeholder} AND status = 'pending'
            """, (datetime.now(), campaign_id))
            
            # Record metrics
            placeholder = _format_placeholder(conn)
            cursor.execute(f"""
                INSERT INTO linkedin_metrics (
                    tenant_id, campaign_id, event_type, created_at, cost
                )
                VALUES ({', '.join([placeholder] * 5)})
            """, (tenant_id, campaign_id, 'campaign_launched', datetime.now(), result.cost))
            
            # Update daily usage
            await self._update_daily_usage(tenant_id, len(messages), result.cost)
            
            conn.commit()
            conn.close()
            
            return LinkedInCampaignResult(
                campaign_id=campaign_id,
                status='running',
                total_recipients=len(messages),
                messages_sent=0,
                messages_failed=0,
                total_cost=result.cost,
                phantom_container_id=result.container_id,
                estimated_completion=result.estimated_completion
            )
            
        except Exception as e:
            logger.error(f"Failed to launch LinkedIn campaign: {e}")
            raise
    
    async def get_campaign_status(self, campaign_id: int, tenant_id: int) -> Dict[str, Any]:
        """
        Get LinkedIn campaign status from PhantomBuster and update database
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Get campaign details
            placeholder = _format_placeholder(conn)
            cursor.execute(f"""
                SELECT * FROM linkedin_campaigns
                WHERE id = {placeholder} AND tenant_id = {placeholder}
            """, (campaign_id, tenant_id))
            
            campaign = cursor.fetchone()
            if not campaign:
                raise ValueError(f"Campaign {campaign_id} not found")
            
            if not campaign['phantom_container_id']:
                # Campaign not yet launched
                return {
                    'campaign_id': campaign_id,
                    'status': campaign['status'],
                    'progress': 0.0,
                    'messages_sent': campaign['messages_sent'],
                    'messages_failed': campaign['messages_failed'],
                    'total_recipients': campaign['total_recipients']
                }
            
            # Get status from PhantomBuster
            pb_client = get_phantombuster_linkedin_client(tenant_id)
            phantom_status = await pb_client.get_campaign_status(campaign['phantom_container_id'])
            
            # Update campaign status in database
            placeholder = _format_placeholder(conn)
            cursor.execute(f"""
                UPDATE linkedin_campaigns
                SET 
                    messages_sent = {placeholder},
                    messages_failed = {placeholder},
                    updated_at = {placeholder}
                WHERE id = {placeholder}
            """, (phantom_status.messages_sent, phantom_status.messages_failed, datetime.now(), campaign_id))
            
            # Update campaign status if completed
            if phantom_status.status in ['finished', 'completed']:
                placeholder = _format_placeholder(conn)
                cursor.execute(f"""
                    UPDATE linkedin_campaigns
                    SET status = 'completed', completed_at = {placeholder}
                    WHERE id = {placeholder}
                """, (phantom_status.completion_time or datetime.now(), campaign_id))
            elif phantom_status.status == 'error':
                placeholder = _format_placeholder(conn)
                cursor.execute(f"""
                    UPDATE linkedin_campaigns
                    SET status = 'failed'
                    WHERE id = {placeholder}
                """, (campaign_id,))
            
            conn.commit()
            conn.close()
            
            return {
                'campaign_id': campaign_id,
                'status': phantom_status.status,
                'progress': phantom_status.progress,
                'messages_sent': phantom_status.messages_sent,
                'messages_failed': phantom_status.messages_failed,
                'messages_pending': phantom_status.messages_pending,
                'total_recipients': campaign['total_recipients'],
                'current_recipient': phantom_status.current_recipient,
                'next_message_eta': phantom_status.next_message_eta,
                'completion_time': phantom_status.completion_time,
                'error_details': phantom_status.error_details
            }
            
        except Exception as e:
            logger.error(f"Failed to get campaign status: {e}")
            raise
    
    async def stop_campaign(self, campaign_id: int, tenant_id: int) -> Dict[str, Any]:
        """
        Stop a running LinkedIn campaign
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Get campaign details
            placeholder = _format_placeholder(conn)
            cursor.execute(f"""
                SELECT phantom_container_id FROM linkedin_campaigns
                WHERE id = {placeholder} AND tenant_id = {placeholder} AND status = 'running'
            """, (campaign_id, tenant_id))
            
            campaign = cursor.fetchone()
            if not campaign:
                raise ValueError(f"Running campaign {campaign_id} not found")
            
            # Stop PhantomBuster campaign
            pb_client = get_phantombuster_linkedin_client(tenant_id)
            result = await pb_client.stop_campaign(campaign['phantom_container_id'])
            
            if result['success']:
                # Update campaign status
                placeholder = _format_placeholder(conn)
                cursor.execute(f"""
                    UPDATE linkedin_campaigns
                    SET status = 'stopped', updated_at = {placeholder}
                    WHERE id = {placeholder}
                """, (datetime.now(), campaign_id))
                
                conn.commit()
            
            conn.close()
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to stop campaign: {e}")
            raise
    
    async def get_daily_linkedin_usage(self, tenant_id: int) -> Dict[str, int]:
        """
        Get daily LinkedIn usage statistics
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            today = datetime.now().date()
            
            # Get or create daily usage record
            placeholder = _format_placeholder(conn)
            cursor.execute(f"""
                SELECT messages_sent, messages_failed, total_cost, phantom_executions
                FROM linkedin_daily_usage
                WHERE tenant_id = {placeholder} AND usage_date = {placeholder}
            """, (tenant_id, today))
            
            usage = cursor.fetchone()
            
            if not usage:
                # Create today's record
                placeholder = _format_placeholder(conn)
                if _is_postgresql_connection(conn):
                    cursor.execute(f"""
                        INSERT INTO linkedin_daily_usage (tenant_id, usage_date, created_at)
                        VALUES ({', '.join([placeholder] * 3)})
                        RETURNING messages_sent, messages_failed, total_cost, phantom_executions
                    """, (tenant_id, today, datetime.now()))
                else:
                    cursor.execute(f"""
                        INSERT INTO linkedin_daily_usage (tenant_id, usage_date, created_at, messages_sent, messages_failed, total_cost, phantom_executions)
                        VALUES ({', '.join([placeholder] * 7)})
                    """, (tenant_id, today, datetime.now(), 0, 0, 0.0, 0))
                    cursor.execute(f"""
                        SELECT messages_sent, messages_failed, total_cost, phantom_executions
                        FROM linkedin_daily_usage
                        WHERE rowid = ?
                    """, (cursor.lastrowid,))
                
                usage = cursor.fetchone()
                conn.commit()
            
            conn.close()
            
            return {
                'messages_sent_today': usage[0],
                'messages_failed_today': usage[1], 
                'cost_today': float(usage[2]),
                'phantom_executions_today': usage[3],
                'quota_remaining': max(0, 300 - usage[0])  # 300 daily limit
            }
            
        except Exception as e:
            logger.error(f"Failed to get daily usage: {e}")
            return {
                'messages_sent_today': 0,
                'messages_failed_today': 0,
                'cost_today': 0.0,
                'phantom_executions_today': 0,
                'quota_remaining': 300
            }
    
    async def _update_daily_usage(self, tenant_id: int, messages_count: int, cost: float):
        """
        Update daily usage statistics
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            today = datetime.now().date()
            
            placeholder = _format_placeholder(conn)
            if _is_postgresql_connection(conn):
                cursor.execute(f"""
                    INSERT INTO linkedin_daily_usage (
                        tenant_id, usage_date, messages_sent, total_cost, 
                        phantom_executions, created_at, updated_at
                    )
                    VALUES ({', '.join([placeholder] * 7)})
                    ON CONFLICT (tenant_id, usage_date)
                    DO UPDATE SET
                        messages_sent = linkedin_daily_usage.messages_sent + EXCLUDED.messages_sent,
                        total_cost = linkedin_daily_usage.total_cost + EXCLUDED.total_cost,
                        phantom_executions = linkedin_daily_usage.phantom_executions + EXCLUDED.phantom_executions,
                        updated_at = EXCLUDED.updated_at
                """, (tenant_id, today, messages_count, cost, 1, datetime.now(), datetime.now()))
            else:
                cursor.execute(f"""
                    INSERT OR REPLACE INTO linkedin_daily_usage (
                        tenant_id, usage_date, messages_sent, total_cost, 
                        phantom_executions, created_at, updated_at
                    )
                    VALUES ({', '.join([placeholder] * 7)})
                """, (tenant_id, today, messages_count, cost, 1, datetime.now(), datetime.now()))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to update daily usage: {e}")

# Global service instance
linkedin_service = LinkedInService()
