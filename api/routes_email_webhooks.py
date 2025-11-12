"""
SendGrid Webhook Integration for Real-Time Email Event Tracking
Handles email events (delivered, opened, clicked, bounced, etc.) from SendGrid
"""

import json
import logging
from typing import List, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel

from api.database import get_db
from core.settings import settings
from services.cost_monitoring_service import cost_monitoring_service
import hashlib
import hmac
import base64

# Import metrics collector if available
try:
    from monitoring.prometheus_metrics import MetricsCollector
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Mounted under prefix="/api" from api.main
router = APIRouter(prefix="/webhooks", tags=["Email Webhooks"])

# ============================================
# WEBHOOK MODELS
# ============================================

class EmailEvent(BaseModel):
    """Individual email event from SendGrid webhook"""
    email: str
    timestamp: int
    event: str  # delivered, opened, clicked, bounced, dropped, deferred, processed
    sg_message_id: str
    sg_event_id: str
    useragent: str = None
    ip: str = None
    url: str = None  # For click events
    reason: str = None  # For bounce/drop events
    status: str = None  # For bounce events
    response: str = None  # For bounce events
    attempt: str = None  # For deferred events
    category: List[str] = []
    unique_args: Dict[str, Any] = {}

# ============================================
# WEBHOOK SIGNATURE VERIFICATION
# ============================================

def verify_webhook_signature(payload: bytes, signature: str, timestamp: str) -> bool:
    """
    Verify SendGrid webhook signature for security
    
    Args:
        payload: Raw webhook payload
        signature: Signature from X-Twilio-Email-Event-Webhook-Signature header
        timestamp: Timestamp from X-Twilio-Email-Event-Webhook-Timestamp header
    
    Returns:
        bool: True if signature is valid
    """
    if not settings.SENDGRID_WEBHOOK_VERIFICATION_KEY:
        logger.warning("SendGrid webhook verification key not configured - accepting all requests")
        return True
    
    try:
        # SendGrid uses ECDSA verification
        verification_key = settings.SENDGRID_WEBHOOK_VERIFICATION_KEY
        
        # Construct the signed payload
        signed_payload = timestamp.encode('utf-8') + payload
        
        # Create expected signature
        expected_signature = hmac.new(
            verification_key.encode('utf-8'),
            signed_payload,
            hashlib.sha256
        ).digest()
        
        # Decode the received signature
        received_signature = base64.b64decode(signature)
        
        # Compare signatures
        return hmac.compare_digest(expected_signature, received_signature)
        
    except Exception as e:
        logger.error(f"Webhook signature verification failed: {e}")
        return False

# ============================================
# WEBHOOK ENDPOINTS
# ============================================

@router.post("/sendgrid/events")
async def handle_sendgrid_webhook(
    request: Request,
    x_twilio_email_event_webhook_signature: str = Header(None),
    x_twilio_email_event_webhook_timestamp: str = Header(None)
):
    """
    Handle SendGrid webhook events for email tracking
    
    This endpoint receives real-time notifications when emails are:
    - Delivered, opened, clicked
    - Bounced, dropped, marked as spam
    - Deferred or blocked
    """
    try:
        # Get raw payload for signature verification
        payload = await request.body()
        
        # Verify webhook signature for security
        if x_twilio_email_event_webhook_signature and x_twilio_email_event_webhook_timestamp:
            if not verify_webhook_signature(
                payload, 
                x_twilio_email_event_webhook_signature,
                x_twilio_email_event_webhook_timestamp
            ):
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        # Parse JSON payload
        events = json.loads(payload.decode('utf-8'))
        
        if not isinstance(events, list):
            events = [events]
        
        # Process each event
        processed_count = 0
        for event_data in events:
            try:
                event = EmailEvent(**event_data)
                await process_email_event(event)
                processed_count += 1
            except Exception as e:
                logger.error(f"Failed to process email event: {e}")
                logger.error(f"Event data: {event_data}")
        
        logger.info(f"Processed {processed_count}/{len(events)} email events")
        
        return {
            "status": "success",
            "processed": processed_count,
            "total": len(events),
            "message": f"Processed {processed_count} email events"
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error processing webhook")

# ============================================
# EVENT PROCESSING
# ============================================

async def process_email_event(event: EmailEvent):
    """
    Process individual email event and update database
    
    Args:
        event: Parsed email event from SendGrid
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Find the email log entry by SendGrid message ID
        cursor.execute("""
            SELECT id, tenant_id, status, opens_count, clicks_count
            FROM tenant_email_logs
            WHERE sendgrid_message_id = %s
        """, (event.sg_message_id,))
        
        log_entry = cursor.fetchone()
        
        if not log_entry:
            logger.warning(f"No log entry found for message ID: {event.sg_message_id}")
            return
        
        log_id = log_entry["id"]
        tenant_id = log_entry["tenant_id"]
        current_status = log_entry["status"]
        opens_count = log_entry["opens_count"] or 0
        clicks_count = log_entry["clicks_count"] or 0
        
        # Update based on event type
        new_status = current_status
        new_opens = opens_count
        new_clicks = clicks_count
        
        if event.event == "delivered":
            new_status = "delivered"
        elif event.event == "opened":
            new_status = "opened"
            new_opens += 1
        elif event.event == "clicked":
            new_status = "clicked"
            new_clicks += 1
        elif event.event in ["bounced", "dropped", "blocked"]:
            new_status = "bounced"
        elif event.event == "spamreport":
            new_status = "spam"
        elif event.event == "unsubscribe":
            new_status = "unsubscribed"
        
        # Update the email log
        cursor.execute("""
            UPDATE tenant_email_logs
            SET status = %s, 
                opens_count = %s, 
                clicks_count = %s,
                status_updated_at = %s
            WHERE id = %s
        """, (new_status, new_opens, new_clicks, datetime.now(), log_id))
        
        # Insert webhook event record
        cursor.execute("""
            INSERT INTO email_webhook_events 
            (tenant_id, log_id, sendgrid_message_id, event_type, event_data, processed_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            tenant_id,
            log_id, 
            event.sg_message_id,
            event.event,
            json.dumps(event.dict()),
            datetime.now()
        ))
        
        conn.commit()
        
        # Update tenant stats if significant event
        if event.event in ["delivered", "bounced", "opened", "clicked"]:
            await update_tenant_email_stats(tenant_id, event.event)
        
        logger.info(f"Processed {event.event} event for message {event.sg_message_id}")
        
        # Record metrics if available
        if METRICS_AVAILABLE:
            MetricsCollector.record_webhook_event(event.event, tenant_id)
            
        # Track cost for successful delivery
        if event.event == "delivered":
            await cost_monitoring_service.track_email_cost(
                tenant_id=tenant_id,
                email_count=1,
                email_type="transactional"
            )
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to process email event: {e}")
        raise
    finally:
        conn.close()

async def update_tenant_email_stats(tenant_id: int, event_type: str):
    """
    Update tenant-level email statistics
    
    Args:
        tenant_id: Tenant ID
        event_type: Type of email event (delivered, bounced, opened, clicked)
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Get current month stats
        cursor.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE status = 'delivered') as delivered_count,
                COUNT(*) FILTER (WHERE status = 'bounced') as bounced_count,
                COUNT(*) FILTER (WHERE status = 'opened') as opened_count,
                COUNT(*) FILTER (WHERE status = 'clicked') as clicked_count,
                COUNT(*) as total_count
            FROM tenant_email_logs
            WHERE tenant_id = %s 
            AND DATE_TRUNC('month', sent_at) = DATE_TRUNC('month', CURRENT_DATE)
        """, (tenant_id,))
        
        stats = cursor.fetchone()
        
        if stats and stats["total_count"] > 0:
            delivered_count = stats["delivered_count"] or 0
            bounced_count = stats["bounced_count"] or 0
            opened_count = stats["opened_count"] or 0
            clicked_count = stats["clicked_count"] or 0
            total_count = stats["total_count"]
            
            # Calculate rates
            delivery_rate = (delivered_count / total_count) * 100 if total_count > 0 else 0
            bounce_rate = (bounced_count / total_count) * 100 if total_count > 0 else 0
            open_rate = (opened_count / delivered_count) * 100 if delivered_count > 0 else 0
            click_rate = (clicked_count / delivered_count) * 100 if delivered_count > 0 else 0
            
            # Update subuser stats
            cursor.execute("""
                UPDATE tenant_sendgrid_subusers
                SET bounce_rate = %s,
                    reputation_score = %s,
                    updated_at = NOW()
                WHERE tenant_id = %s
            """, (bounce_rate, delivery_rate, tenant_id))
            
            conn.commit()
            
            logger.info(f"Updated stats for tenant {tenant_id}: delivery={delivery_rate:.1f}%, bounce={bounce_rate:.1f}%, open={open_rate:.1f}%")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to update tenant stats: {e}")
    finally:
        conn.close()

# ============================================
# WEBHOOK MANAGEMENT
# ============================================

@router.get("/sendgrid/status")
async def webhook_status():
    """Get webhook processing status and recent events"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Get recent webhook events
        cursor.execute("""
            SELECT event_type, COUNT(*) as count
            FROM email_webhook_events
            WHERE processed_at > NOW() - INTERVAL '24 hours'
            GROUP BY event_type
            ORDER BY count DESC
        """)
        
        recent_events = []
        for row in cursor.fetchall():
            recent_events.append({
                "event_type": row["event_type"],
                "count": row["count"]
            })
        
        # Get total processed today
        cursor.execute("""
            SELECT COUNT(*) as total_today
            FROM email_webhook_events
            WHERE DATE(processed_at) = CURRENT_DATE
        """)
        
        total_today = cursor.fetchone()["total_today"] or 0
        
        return {
            "status": "active",
            "verification_enabled": bool(settings.SENDGRID_WEBHOOK_VERIFICATION_KEY),
            "events_processed_today": total_today,
            "recent_events": recent_events,
            "webhook_url": f"{settings.BASE_URL}/api/webhooks/sendgrid/events" if hasattr(settings, 'BASE_URL') else None
        }
        
    except Exception as e:
        logger.error(f"Failed to get webhook status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get webhook status")
    finally:
        conn.close()

@router.post("/sendgrid/test")
async def test_webhook():
    """Test webhook processing with sample data"""
    sample_event = {
        "email": "test@example.com",
        "timestamp": int(datetime.now().timestamp()),
        "event": "delivered",
        "sg_message_id": "test-message-id-123",
        "sg_event_id": "test-event-id-123",
        "smtp-id": "<test@example.com>",
        "category": ["test"]
    }
    
    try:
        event = EmailEvent(**sample_event)
        await process_email_event(event)
        
        return {
            "status": "success",
            "message": "Test webhook event processed successfully",
            "event": sample_event
        }
        
    except Exception as e:
        logger.error(f"Test webhook failed: {e}")
        return {
            "status": "error", 
            "message": f"Test webhook failed: {str(e)}",
            "event": sample_event
        }
