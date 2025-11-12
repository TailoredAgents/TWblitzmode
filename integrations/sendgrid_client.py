"""
SendGrid Email Service Client
Production-ready email sending with tracking and compliance
"""

import asyncio
import logging
import json
import hmac
import hashlib
import base64
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, Email, To, Content, Attachment, 
    FileContent, FileName, FileType, Disposition,
    Personalization, TrackingSettings, ClickTracking,
    OpenTracking, SubscriptionTracking, Ganalytics,
    FooterSettings, MailSettings, SandBoxMode, Category, CustomArg
)

from core.settings import settings
from services.error_classifier import error_classifier
from api.mt_db import get_db
from services.centralized_logging_service import LogCategory, LogLevel, log_structured

logger = logging.getLogger(__name__)


_SENDGRID_CONTEXT: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "sendgrid_operation_context",
    default=None,
)


@contextmanager
def sendgrid_operation_context(**metadata: Any):
    token = _SENDGRID_CONTEXT.set({k: v for k, v in metadata.items() if v is not None})
    try:
        yield
    finally:
        _SENDGRID_CONTEXT.reset(token)


def update_sendgrid_context(**metadata: Any) -> None:
    ctx = _SENDGRID_CONTEXT.get()
    if ctx is None:
        return
    for key, value in metadata.items():
        if value is not None:
            ctx[key] = value


def _safe_hash(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _sendgrid_log(level: LogLevel, message: str, tenant_id: Optional[int], **extra) -> None:
    exc_info = extra.pop("exc_info", False)
    context = _SENDGRID_CONTEXT.get()
    if context:
        for key, value in context.items():
            extra.setdefault(key, value)
    log_structured(
        level,
        message,
        category=LogCategory.BUSINESS,
        tenant_id=str(tenant_id) if tenant_id is not None else None,
        provider="sendgrid",
        exc_info=exc_info,
        **extra,
    )

class EmailStatus(Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    DROPPED = "dropped"
    SPAM_REPORT = "spam_report"
    UNSUBSCRIBED = "unsubscribed"
    DEFERRED = "deferred"
    FAILED = "failed"

@dataclass
class EmailResult:
    success: bool
    message_id: Optional[str] = None
    status: EmailStatus = EmailStatus.QUEUED
    error_message: Optional[str] = None
    response_code: Optional[int] = None
    cost: float = 0.0

class SendGridClient:
    """
    SendGrid API client for transactional and marketing emails
    Docs: https://docs.sendgrid.com/
    """
    
    def __init__(self, api_key: Optional[str] = None, tenant_id: Optional[int] = None):
        """Initialize the SendGrid client.

        Be resilient if multi-tenant email tables are missing in Postgres by
        falling back to environment defaults instead of crashing. This avoids
        500s when `tenant_email_settings` has not yet been migrated.
        """
        # Resolve API key with safe fallback
        resolved_api_key = None
        try:
            resolved_api_key = api_key or self._get_api_key_for_tenant(tenant_id)
        except Exception as e:
            logger.warning(f"Falling back to default SendGrid API key; settings lookup failed: {e}")
            resolved_api_key = api_key or settings.SENDGRID_API_KEY

        # Finalize API key (strip to avoid whitespace issues)
        self.api_key = (resolved_api_key or "").strip()
        self.tenant_id = tenant_id
        
        # Determine regional base URL and subuser delegation from integration settings or env
        base_url = getattr(settings, 'SENDGRID_API_BASE_URL', None)
        subuser = None
        try:
            from integrations.apify_client import get_tenant_integration_settings
            integ = get_tenant_integration_settings(tenant_id) if tenant_id else {}
            if isinstance(integ, dict):
                # Prefer explicit base URL; else map region 'eu' -> EU host
                base_url = integ.get('sendgrid_base_url') or base_url
                region = (integ.get('sendgrid_region') or '').lower()
                if not base_url and region == 'eu':
                    base_url = 'https://api.eu.sendgrid.com'
                subuser = integ.get('sendgrid_on_behalf_of') or integ.get('sendgrid_subuser')
        except Exception as _:
            pass
        # Default to global if not specified
        base_url = base_url or 'https://api.sendgrid.com'

        # Initialize client with explicit host
        try:
            self.client = SendGridAPIClient(api_key=self.api_key, host=base_url)
        except TypeError:
            # Older library versions may not accept host kwarg
            self.client = SendGridAPIClient(self.api_key)
            try:
                # Best-effort set internal host
                if hasattr(self.client, 'host'):
                    setattr(self.client, 'host', base_url)
            except Exception:
                pass
        # Set On-Behalf-Of header if configured (subuser send)
        try:
            if subuser:
                self.client.client.request_headers['on-behalf-of'] = subuser
        except Exception:
            pass
        
        # Get tenant-specific settings (safe fallback)
        try:
            self.from_email, self.from_name = self._get_tenant_sender_info(tenant_id)
        except Exception as e:
            logger.warning(f"Falling back to default sender; settings lookup failed: {e}")
            self.from_email, self.from_name = settings.DEFAULT_FROM_EMAIL, settings.DEFAULT_FROM_NAME
        
        # Rate limiting
        try:
            self.daily_send_limit = self._get_daily_limit(tenant_id)
        except Exception as e:
            logger.warning(f"Using default daily limit; lookup failed: {e}")
            self.daily_send_limit = 100
        try:
            self.sent_today = self._get_sent_today_count()
        except Exception as e:
            logger.warning(f"Using 0 sent_today; lookup failed: {e}")
            self.sent_today = 0
        
        # Per-minute rate limiting for SendGrid API (600 emails/minute max)
        self.rate_limit_per_minute = 500  # Conservative limit
        self.sent_this_minute = 0
        self.minute_reset_time = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=1)
        
        # Sandbox mode for testing
        self.sandbox_mode = settings.ENVIRONMENT == "development"
    
    def verify_webhook_signature(self, payload: bytes, signature: str, timestamp: str) -> bool:
        """
        Verify SendGrid webhook signature properly
        
        Args:
            payload: Raw request body bytes
            signature: X-SendGrid-Signature header value
            timestamp: X-SendGrid-Timestamp header value
            
        Returns:
            True if signature is valid
        """
        try:
            # Get webhook verification key from settings
            verification_key = getattr(settings, 'SENDGRID_WEBHOOK_VERIFICATION_KEY', None)
            if not verification_key:
                logger.warning("SENDGRID_WEBHOOK_VERIFICATION_KEY not configured - skipping verification")
                # In production, this should return False for security
                return getattr(settings, 'ENVIRONMENT', 'production') == 'development'
            
            # Parse SendGrid signature format: "v1,signature,timestamp"
            sig_parts = signature.split(',')
            if len(sig_parts) != 3:
                logger.warning("Invalid signature format - expected v1,signature,timestamp")
                return False
                
            version, sig, sig_timestamp = sig_parts
            if version != 'v1':
                logger.warning(f"Unsupported signature version: {version}")
                return False
                
            # Verify timestamp is recent (within 10 minutes)
            try:
                sig_time = int(sig_timestamp)
                current_time = int(datetime.now().timestamp())
                if abs(current_time - sig_time) > 600:  # 10 minutes
                    logger.warning("Webhook signature timestamp too old")
                    return False
            except ValueError:
                logger.warning("Invalid signature timestamp")
                return False
            
            # Build signed payload for verification: timestamp + payload
            signed_payload = sig_timestamp.encode() + payload
            
            # Compute expected signature using HMAC-SHA256
            expected_signature = hmac.new(
                verification_key.encode(),
                signed_payload,
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures using constant-time comparison
            is_valid = hmac.compare_digest(sig, expected_signature)
            
            if not is_valid:
                logger.warning("SendGrid webhook signature verification failed")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {e}")
            return False
        
    def _get_api_key_for_tenant(self, tenant_id: int) -> str:
        """Get tenant-specific SendGrid API key"""
        if not tenant_id:
            return settings.SENDGRID_API_KEY
        
        # 1) Try tenant_email_settings (encrypted)
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT sendgrid_api_key_encrypted 
                FROM tenant_email_settings 
                WHERE tenant_id = %s
            """, (tenant_id,))
            result = cursor.fetchone()
            conn.close()
            if result:
                # Convert to dict if it's not already
                if hasattr(result, '_asdict'):
                    result = result._asdict()
                elif hasattr(result, 'keys') and hasattr(result, 'values'):
                    result = dict(result)

                # Check for API key
                key_val = None
                if hasattr(result, 'get'):
                    key_val = result.get('sendgrid_api_key_encrypted')
                elif isinstance(result, dict):
                    key_val = result.get('sendgrid_api_key_encrypted')

                if key_val:
                    from api.security import dec
                    return dec(key_val)
        except Exception as e:
            logger.info(f"tenant_email_settings lookup failed, will try integration settings: {e}")
        
        # 2) Try integration settings (unencrypted), same source used by CUFinder
        try:
            from integrations.apify_client import get_tenant_integration_settings
            integ = get_tenant_integration_settings(tenant_id)
            if isinstance(integ, dict):
                key = integ.get('sendgrid_api_key')
                if key:
                    return key.strip()
            else:
                logger.info(f"integration settings returned non-dict ({type(integ)}); falling back to env")
        except Exception as e:
            logger.info(f"integration settings lookup failed, will try env: {e}")
        
        # 3) Fall back to environment
        return settings.SENDGRID_API_KEY
    
    def _get_tenant_sender_info(self, tenant_id: int) -> tuple:
        """Get tenant-specific sender information"""
        if not tenant_id:
            return settings.DEFAULT_FROM_EMAIL, settings.DEFAULT_FROM_NAME
        
        # 1) Try tenant_email_settings
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT from_email, from_name, domain_verified 
                FROM tenant_email_settings 
                WHERE tenant_id = %s
            """, (tenant_id,))
            result = cursor.fetchone()
            conn.close()
            if result:
                # Convert to dict if it's not already
                if hasattr(result, '_asdict'):
                    result = result._asdict()
                elif hasattr(result, 'keys') and hasattr(result, 'values'):
                    result = dict(result)

                # Check if result is dict-like and domain is verified
                if hasattr(result, 'get') and result.get('domain_verified'):
                    return result.get('from_email') or settings.DEFAULT_FROM_EMAIL, result.get('from_name') or settings.DEFAULT_FROM_NAME
                elif isinstance(result, dict) and result.get('domain_verified'):
                    return result.get('from_email') or settings.DEFAULT_FROM_EMAIL, result.get('from_name') or settings.DEFAULT_FROM_NAME
        except Exception as e:
            logger.info(f"tenant_email_settings sender lookup failed, will try integration settings: {e}")
        
        # 2) Try integration settings keys
        try:
            from integrations.apify_client import get_tenant_integration_settings
            integ = get_tenant_integration_settings(tenant_id)
            if isinstance(integ, dict):
                fe = integ.get('sendgrid_from_email')
                fn = integ.get('sendgrid_from_name')
                if fe or fn:
                    return fe or settings.DEFAULT_FROM_EMAIL, fn or settings.DEFAULT_FROM_NAME
            else:
                logger.info(f"integration sender returned non-dict ({type(integ)}); using defaults")
        except Exception as e:
            logger.info(f"integration sender lookup failed, using defaults: {e}")
        
        return settings.DEFAULT_FROM_EMAIL, settings.DEFAULT_FROM_NAME
    
    def _get_daily_limit(self, tenant_id: int) -> int:
        """Get daily sending limit based on warmup status"""
        if not tenant_id:
            return 100
            
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT daily_limit, warmup_status, warmup_started_at 
                FROM tenant_email_settings 
                WHERE tenant_id = %s
            """, (tenant_id,))
            result = cursor.fetchone()
            conn.close()
            if not result:
                return 20

            # Convert to dict if it's not already
            if hasattr(result, '_asdict'):
                result = result._asdict()
            elif hasattr(result, 'keys') and hasattr(result, 'values'):
                result = dict(result)

            # Calculate warmup limit if in warmup period
            warmup_status = None
            warmup_started_at = None
            daily_limit = 100

            if hasattr(result, 'get'):
                warmup_status = result.get('warmup_status')
                warmup_started_at = result.get('warmup_started_at')
                daily_limit = result.get('daily_limit', 100)
            elif isinstance(result, dict):
                warmup_status = result.get('warmup_status')
                warmup_started_at = result.get('warmup_started_at')
                daily_limit = result.get('daily_limit', 100)

            if warmup_status == 'warming' and warmup_started_at:
                days_warming = (datetime.now() - warmup_started_at).days
                if days_warming < 7:
                    return 20
                elif days_warming < 14:
                    return 50
                elif days_warming < 30:
                    return 100
                else:
                    # Graduate from warmup
                    try:
                        self._update_warmup_status('completed')
                    except Exception as e:
                        logger.info(f"Failed to update warmup status: {e}")
                    return 500
            return daily_limit
        except Exception as e:
            logger.info(f"tenant_email_settings daily limit lookup failed, using default: {e}")
            return 100
    
    def _get_sent_today_count(self) -> int:
        """Get count of emails sent today for this tenant"""
        if not self.tenant_id:
            return 0

        conn = get_db()
        cursor = conn.cursor()

        # Detect database type and use appropriate placeholder
        is_postgresql = hasattr(conn, 'info') and 'postgresql' in str(type(conn)).lower()
        placeholder = '%s' if is_postgresql else '?'

        cursor.execute(f"""
            SELECT COALESCE(count, 0) as count
            FROM email_costs
            WHERE tenant_id = {placeholder}
            AND service = 'sendgrid'
            AND operation = 'send'
            AND date = {placeholder}
        """, (self.tenant_id, datetime.now().date()))
        
        result = cursor.fetchone()
        conn.close()

        if result:
            # Convert to dict if it's not already
            if hasattr(result, '_asdict'):
                result = result._asdict()
            elif hasattr(result, 'keys') and hasattr(result, 'values'):
                result = dict(result)

            if hasattr(result, 'get'):
                return result.get('count', 0)
            elif isinstance(result, dict):
                return result.get('count', 0)
            elif hasattr(result, '__getitem__'):
                return result[0] if len(result) > 0 else 0

        return 0
    
    def _update_warmup_status(self, status: str):
        """Update warmup status in database"""
        if not self.tenant_id:
            return
            
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tenant_email_settings 
                SET warmup_status = %s, updated_at = %s
                WHERE tenant_id = %s
            """, (status, datetime.now(), self.tenant_id))
            conn.commit()
            conn.close()
        except Exception as e:
            # Non-fatal if table doesn't exist yet
            logger.info(f"Warmup status update skipped (missing schema?): {e}")
    
    def _check_suppression_list(self, email: str) -> bool:
        """Check if email is on suppression list"""
        if not self.tenant_id:
            return False
            
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM email_suppression_list 
                WHERE tenant_id = %s AND email = %s 
                AND (expires_at IS NULL OR expires_at > %s)
            """, (self.tenant_id, email, datetime.now()))
            result = cursor.fetchone()
            conn.close()
            return result is not None
        except Exception as e:
            # If table doesn't exist yet, treat as not suppressed
            logger.debug(f"Suppression list lookup skipped: {e}")
            return False
    
    def _track_send(self, email: str, message_id: str, cost: float = 0.001):
        """Track email send for analytics and billing"""
        if not self.tenant_id:
            return
            
        try:
            conn = get_db()
            cursor = conn.cursor()
            # Update costs (idempotent upsert by unique constraint)
            cursor.execute("""
                INSERT INTO email_costs (tenant_id, date, service, operation, count, unit_cost, total_cost)
                VALUES (%s, %s, 'sendgrid', 'send', 1, %s, %s)
                ON CONFLICT(tenant_id, date, service, operation) DO UPDATE SET 
                    count = email_costs.count + 1,
                    total_cost = email_costs.total_cost + EXCLUDED.total_cost
            """, (
                self.tenant_id,
                datetime.now().date(),
                cost,
                cost
            ))
            # Update tenant-level stats if table exists
            try:
                cursor.execute("""
                    UPDATE tenant_email_settings 
                    SET total_sent = COALESCE(total_sent, 0) + 1,
                        updated_at = %s
                    WHERE tenant_id = %s
                """, (datetime.now(), self.tenant_id))
            except Exception as inner:
                logger.debug(f"Skip tenant_email_settings stats update: {inner}")
            conn.commit()
            conn.close()
        except Exception as e:
            logger.info(f"Skipping cost tracking (missing schema?): {e}")
        
        # Increment daily and per-minute send counters
        self.sent_today += 1
        self.sent_this_minute += 1
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        body_html: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[Dict]] = None,
        categories: Optional[List[str]] = None,
        custom_args: Optional[Dict] = None,
        send_at: Optional[int] = None,
        track_opens: bool = True,
        track_clicks: bool = True,
        add_unsubscribe: bool = True,
        template_id: Optional[str] = None,
        dynamic_data: Optional[Dict[str, Any]] = None,
    ) -> EmailResult:
        """
        Send a single email with full tracking and compliance.
        """

        recipient_hash = _safe_hash(to_email)
        subject_hash = _safe_hash(subject or "")
        context_metadata = {
            "sendgrid_operation": "send_single_email",
            "sendgrid_operation_id": uuid.uuid4().hex,
            "sendgrid_recipient_hash": recipient_hash,
            "sendgrid_subject_hash": subject_hash,
            "sendgrid_template_id": template_id or "none",
        }
        if categories:
            context_metadata["sendgrid_categories"] = ",".join(sorted(categories))

        with sendgrid_operation_context(**context_metadata):
            return await self._send_email_inner(
                to_email=to_email,
                subject=subject,
                body=body,
                body_html=body_html,
                from_email=from_email,
                from_name=from_name,
                reply_to=reply_to,
                cc=cc,
                bcc=bcc,
                attachments=attachments,
                categories=categories,
                custom_args=custom_args,
                send_at=send_at,
                track_opens=track_opens,
                track_clicks=track_clicks,
                add_unsubscribe=add_unsubscribe,
                template_id=template_id,
                dynamic_data=dynamic_data,
                recipient_hash=recipient_hash,
                subject_hash=subject_hash,
            )

    async def _send_email_inner(
        self,
        to_email: str,
        subject: str,
        body: str,
        body_html: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[Dict]] = None,
        categories: Optional[List[str]] = None,
        custom_args: Optional[Dict] = None,
        send_at: Optional[int] = None,
        track_opens: bool = True,
        track_clicks: bool = True,
        add_unsubscribe: bool = True,
        template_id: Optional[str] = None,
        dynamic_data: Optional[Dict[str, Any]] = None,
        *,
        recipient_hash: Optional[str],
        subject_hash: Optional[str],
    ) -> EmailResult:
        """Internal implementation for send_email with rich logging."""
        _sendgrid_log(
            LogLevel.INFO,
            "SendGrid send requested",
            self.tenant_id,
            recipient=recipient_hash,
            subject_hash=subject_hash,
            template_id=template_id,
            categories=categories or [],
        )
        
        # Check daily limit
        if self.sent_today >= self.daily_send_limit:
            _sendgrid_log(
                LogLevel.WARNING,
                "SendGrid daily limit reached",
                self.tenant_id,
                limit=self.daily_send_limit,
                recipient=recipient_hash,
            )
            return EmailResult(
                success=False,
                status=EmailStatus.FAILED,
                error_message=f"Daily limit reached ({self.daily_send_limit})"
            )
        
        # Check per-minute rate limiting
        current_time = datetime.now()
        current_minute = current_time.replace(second=0, microsecond=0)
        
        # Reset minute counter if we're in a new minute
        if current_minute >= self.minute_reset_time:
            self.sent_this_minute = 0
            self.minute_reset_time = current_minute + timedelta(minutes=1)
        
        # Check minute limit
        if self.sent_this_minute >= self.rate_limit_per_minute:
            _sendgrid_log(
                LogLevel.WARNING,
                "SendGrid per-minute rate limit reached",
                self.tenant_id,
                limit=self.rate_limit_per_minute,
                recipient=recipient_hash,
            )
            return EmailResult(
                success=False,
                status=EmailStatus.FAILED,
                error_message=f"Per-minute rate limit reached ({self.rate_limit_per_minute}/min)"
            )
        
        # Check suppression list
        if self._check_suppression_list(to_email):
            logger.info(f"Email {to_email} is on suppression list")
            _sendgrid_log(
                LogLevel.INFO,
                "SendGrid suppression list drop",
                self.tenant_id,
                recipient=recipient_hash,
            )
            return EmailResult(
                success=False,
                status=EmailStatus.DROPPED,
                error_message="Recipient on suppression list"
            )
        
        try:
            # Create message
            message = Mail()
            
            # Set sender
            message.from_email = Email(
                from_email or self.from_email,
                from_name or self.from_name
            )
            
            # Set recipient and personalization
            personalization = Personalization()
            personalization.add_to(Email(to_email))
            
            # Add CC/BCC if provided
            if cc:
                for cc_email in cc:
                    personalization.add_cc(Email(cc_email))
            if bcc:
                for bcc_email in bcc:
                    personalization.add_bcc(Email(bcc_email))
            
            # Content / template handling
            use_template = bool(template_id)
            if use_template:
                message.template_id = template_id
                if subject is not None:
                    message.subject = str(subject)
            else:
                message.subject = str(subject) if subject is not None else ""
                if body_html:
                    message.add_content(Content("text/html", str(body_html)))
                message.add_content(Content("text/plain", str(body or "")))
            
            # Set reply-to
            if reply_to:
                message.reply_to = Email(reply_to)
            
            # Add attachments
            if attachments:
                for att in attachments:
                    if not isinstance(att, dict):
                        logger.debug(f"Skipping attachment not dict: {type(att)}")
                        continue
                    if 'content' not in att or 'filename' not in att:
                        logger.debug("Skipping attachment missing required keys")
                        continue
                    attachment = Attachment()
                    attachment.file_content = FileContent(att['content'])
                    attachment.file_type = FileType(att.get('type', 'application/octet-stream'))
                    attachment.file_name = FileName(att['filename'])
                    attachment.disposition = Disposition('attachment')
                    message.add_attachment(attachment)
            
            # Set categories for filtering using helper method
            try:
                if categories:
                    for cat in categories:
                        if cat:
                            message.add_category(Category(str(cat)))
                elif self.tenant_id:
                    message.add_category(Category(f"tenant_{self.tenant_id}"))
            except Exception as cat_err:
                logger.debug(f"Skipping categories due to helper error: {cat_err}")
            
            # Add custom arguments for tracking at personalization level (prefer dict mapping)
            try:
                if custom_args and isinstance(custom_args, dict):
                    args_map = {str(k): str(v) for k, v in custom_args.items()}
                    if hasattr(personalization, 'custom_args') and isinstance(getattr(personalization, 'custom_args', None), dict):
                        try:
                            personalization.custom_args.update(args_map)
                        except Exception:
                            setattr(personalization, 'custom_args', {**(getattr(personalization, 'custom_args', {}) or {}), **args_map})
                    else:
                        # Fallback to helper if mapping is not available
                        for k, v in args_map.items():
                            personalization.add_custom_arg(CustomArg(k, v))
                elif self.tenant_id:
                    try:
                        if hasattr(personalization, 'custom_args') and isinstance(getattr(personalization, 'custom_args', None), dict):
                            personalization.custom_args['tenant_id'] = str(self.tenant_id)
                        else:
                            personalization.add_custom_arg(CustomArg('tenant_id', str(self.tenant_id)))
                    except Exception:
                        pass
            except Exception as ca_err:
                logger.debug(f"Skipping custom_args due to helper error: {ca_err}")
            
            # Configure tracking (best effort)
            try:
                tracking_settings = TrackingSettings()
                tracking_settings.click_tracking = ClickTracking(track_clicks, track_clicks)
                tracking_settings.open_tracking = OpenTracking(track_opens)
                if add_unsubscribe:
                    tracking_settings.subscription_tracking = SubscriptionTracking(
                        enable=True,
                        text="Unsubscribe",
                        html="<a href='<%unsubscribe%>'>Unsubscribe</a>"
                    )
                message.tracking_settings = tracking_settings
            except Exception as _ts_err:
                logger.debug(f"Skipping tracking settings due to error: {_ts_err}")
            
            # Add footer with compliance info
            try:
                if add_unsubscribe:
                    footer_settings = FooterSettings()
                    footer_settings.enable = True
                    footer_settings.text = "Sent by VouchLink AI AI | <%unsubscribe%>"
                    footer_settings.html = "<p>Sent by VouchLink AI AI | <a href='<%unsubscribe%>'>Unsubscribe</a></p>"
                    message.footer_settings = footer_settings
            except Exception as _fs_err:
                logger.debug(f"Skipping footer settings due to error: {_fs_err}")
            
            # Attach personalization (after custom args)
            if use_template and dynamic_data:
                try:
                    personalization.dynamic_template_data = dynamic_data
                except Exception as exc:
                    logger.debug(f"Skipping dynamic template data due to error: {exc}")
            message.add_personalization(personalization)

            # Set sandbox mode for testing
            if self.sandbox_mode:
                mail_settings = MailSettings()
                mail_settings.sandbox_mode = SandBoxMode(enable=True)
                message.mail_settings = mail_settings
                logger.info("Sending in sandbox mode (not actually sent)")
            
            # Schedule send if requested
            if send_at:
                message.send_at = send_at
            
            # Send the email asynchronously using thread pool
            _sendgrid_log(
                LogLevel.INFO,
                "SendGrid send in-flight",
                self.tenant_id,
                recipient=recipient_hash,
                template_id=template_id,
            )
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self.client.send, message)
            
            # Parse response
            if response.status_code in [200, 201, 202]:
                # Be defensive: some client versions expose headers as string
                message_id = None
                headers = getattr(response, 'headers', None)
                try:
                    if headers is not None:
                        if hasattr(headers, 'get'):
                            # dict-like
                            message_id = headers.get('X-Message-Id') or headers.get('x-message-id')
                        elif isinstance(headers, str):
                            for line in headers.splitlines():
                                k, sep, v = line.partition(':')
                                if sep and k.strip().lower() == 'x-message-id':
                                    message_id = v.strip()
                                    break
                except Exception:
                    # ignore header parsing issues
                    pass
                
                # Track the send
                self._track_send(to_email, message_id)

                update_sendgrid_context(
                    sendgrid_message_id=message_id,
                    sendgrid_status_code=response.status_code,
                )

                # Record success
                if self.tenant_id:
                    error_classifier.record_provider_success('sendgrid', self.tenant_id)

                _sendgrid_log(
                    LogLevel.INFO,
                    "SendGrid send succeeded",
                    self.tenant_id,
                    recipient=recipient_hash,
                    message_id=message_id,
                    status_code=response.status_code,
                )

                return EmailResult(
                    success=True,
                    message_id=message_id,
                    status=EmailStatus.SENT,
                    response_code=response.status_code,
                    cost=0.001  # Approximate cost per email
                )
            else:
                body_preview = response.body[:400] if isinstance(response.body, (bytes, bytearray)) else str(response.body)[:400]
                error_msg = f"SendGrid error: {response.status_code} - {body_preview}"

                if self.tenant_id:
                    error_classifier.record_provider_error(
                        'sendgrid', 'send_failed', error_msg, self.tenant_id
                    )

                update_sendgrid_context(
                    sendgrid_status_code=response.status_code,
                    sendgrid_error_message=error_msg,
                )

                _sendgrid_log(
                    LogLevel.ERROR,
                    "SendGrid send returned non-success status",
                    self.tenant_id,
                    recipient=recipient_hash,
                    status_code=response.status_code,
                    response_preview=body_preview,
                )

                return EmailResult(
                    success=False,
                    status=EmailStatus.FAILED,
                    error_message=error_msg,
                    response_code=response.status_code
                )
                
        except Exception as e:
            logger.error(f"SendGrid send failed: {e}")
            update_sendgrid_context(sendgrid_exception=str(e))
            _sendgrid_log(
                LogLevel.ERROR,
                "SendGrid send exception",
                self.tenant_id,
                recipient=recipient_hash,
                exc_info=e,
            )
            # Fallback: minimal message (text-only, no tracking/custom args/categories)
            try:
                message2 = Mail()
                message2.from_email = Email(
                    from_email or self.from_email,
                    from_name or self.from_name
                )
                personalization2 = Personalization()
                personalization2.add_to(Email(to_email))
                message2.add_personalization(personalization2)
                message2.subject = subject
                message2.add_content(Content("text/plain", body or ""))
                loop = asyncio.get_event_loop()
                response2 = await loop.run_in_executor(None, self.client.send, message2)
                if response2.status_code in [200, 201, 202]:
                    # Record success even via fallback
                    if self.tenant_id:
                        error_classifier.record_provider_success('sendgrid', self.tenant_id)
                    update_sendgrid_context(
                        sendgrid_status_code=response2.status_code,
                        sendgrid_fallback_success=True,
                    )
                    _sendgrid_log(
                        LogLevel.WARNING,
                        "SendGrid fallback send succeeded",
                        self.tenant_id,
                        recipient=recipient_hash,
                        status_code=response2.status_code,
                    )
                    return EmailResult(
                        success=True,
                        message_id=None,
                        status=EmailStatus.SENT,
                        response_code=response2.status_code,
                        cost=0.001
                    )
                else:
                    if self.tenant_id:
                        error_classifier.record_provider_error('sendgrid', 'send_failed', f"fallback {response2.status_code}", self.tenant_id)
            except Exception as e2:
                logger.error(f"SendGrid fallback send failed: {e2}")
                update_sendgrid_context(sendgrid_fallback_exception=str(e2))
                _sendgrid_log(
                    LogLevel.ERROR,
                    "SendGrid fallback send exception",
                    self.tenant_id,
                    recipient=recipient_hash,
                    exc_info=e2,
                )
            # Record primary error
            if self.tenant_id:
                error_classifier.record_provider_error(
                    'sendgrid', 'send_exception', str(e), self.tenant_id
                )
            return EmailResult(success=False, status=EmailStatus.FAILED, error_message=str(e))

    async def send_email_minimal(
        self,
        to_email: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None
    ) -> EmailResult:
        """
        Minimal plain-text send with no optional helpers.
        Useful to bypass helper compatibility issues while diagnosing provider errors.
        """
        try:
            message = Mail()
            message.from_email = Email(
                from_email or self.from_email,
                from_name or self.from_name
            )
            personalization = Personalization()
            personalization.add_to(Email(to_email))
            message.add_personalization(personalization)
            message.subject = str(subject) if subject is not None else ""
            message.add_content(Content("text/plain", str(body or "")))

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self.client.send, message)
            if response.status_code in [200, 201, 202]:
                message_id = None
                headers = getattr(response, 'headers', None)
                if headers is not None and hasattr(headers, 'get'):
                    message_id = headers.get('X-Message-Id') or headers.get('x-message-id')
                if self.tenant_id:
                    error_classifier.record_provider_success('sendgrid', self.tenant_id)
                # Track minimal sends as well
                self._track_send(to_email, message_id)
                return EmailResult(success=True, message_id=message_id, status=EmailStatus.SENT, response_code=response.status_code, cost=0.001)
            else:
                err = f"SendGrid error: {response.status_code} - {response.body}"
                if self.tenant_id:
                    error_classifier.record_provider_error('sendgrid', 'send_failed', err, self.tenant_id)
                return EmailResult(success=False, status=EmailStatus.FAILED, error_message=err, response_code=response.status_code)
        except Exception as e:
            logger.error(f"SendGrid minimal send failed: {e}")
            if self.tenant_id:
                error_classifier.record_provider_error('sendgrid', 'send_exception', str(e), self.tenant_id)
            return EmailResult(success=False, status=EmailStatus.FAILED, error_message=str(e))

    async def send_email_raw(
        self,
        to_email: str,
        subject: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        categories: Optional[List[str]] = None,
        custom_args: Optional[Dict] = None
    ) -> EmailResult:
        """
        Send using direct v3 JSON request body to /v3/mail/send, bypassing helper classes.
        This is useful to capture provider-native errors and avoid any SDK helper quirks.
        """
        try:
            fe = from_email or self.from_email
            fn = from_name or self.from_name
            content: List[Dict[str, str]] = []
            if body_html:
                content.append({"type": "text/html", "value": str(body_html)})
            # Always include text/plain (SendGrid recommends at least one content)
            content.append({"type": "text/plain", "value": str(body_text or body_html or "")})

            personalization: Dict[str, Any] = {
                "to": [{"email": to_email}],
            }
            if custom_args and isinstance(custom_args, dict):
                personalization["custom_args"] = {str(k): str(v) for k, v in custom_args.items()}

            request_body: Dict[str, Any] = {
                "personalizations": [personalization],
                "from": {"email": fe, **({"name": fn} if fn else {})},
                "subject": str(subject or ""),
                "content": content,
            }
            if categories:
                request_body["categories"] = [str(c) for c in categories if c]

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self.client.client.mail.send.post, request_body)

            if response.status_code in [200, 201, 202]:
                # message id typically in headers
                message_id = None
                headers = getattr(response, 'headers', None)
                if headers is not None and hasattr(headers, 'get'):
                    message_id = headers.get('X-Message-Id') or headers.get('x-message-id')
                if self.tenant_id:
                    error_classifier.record_provider_success('sendgrid', self.tenant_id)
                self._track_send(to_email, message_id)
                return EmailResult(success=True, message_id=message_id, status=EmailStatus.SENT, response_code=response.status_code, cost=0.001)

            # Non-2xx: parse response body for clearer error
            body_raw = getattr(response, 'body', '')
            try:
                if isinstance(body_raw, (bytes, bytearray)):
                    body_raw = body_raw.decode('utf-8', errors='ignore')
                err_json = json.loads(body_raw) if isinstance(body_raw, str) else {}
                err_msg = None
                if isinstance(err_json, dict):
                    errs = err_json.get('errors')
                    if isinstance(errs, list) and errs:
                        first = errs[0]
                        if isinstance(first, dict):
                            err_msg = first.get('message') or first.get('description')
                error_msg = f"SendGrid error: {response.status_code} - {err_msg or body_raw}"
            except Exception:
                error_msg = f"SendGrid error: {response.status_code} - {body_raw}"

            if self.tenant_id:
                error_classifier.record_provider_error('sendgrid', 'send_failed', error_msg, self.tenant_id)
            return EmailResult(success=False, status=EmailStatus.FAILED, error_message=error_msg, response_code=response.status_code)

        except Exception as e:
            logger.error(f"SendGrid raw v3 send failed: {e}")
            if self.tenant_id:
                error_classifier.record_provider_error('sendgrid', 'send_exception', str(e), self.tenant_id)
            return EmailResult(success=False, status=EmailStatus.FAILED, error_message=str(e))
    
    async def send_batch(
        self,
        recipients: List[Dict],
        subject: str,
        body_template: str,
        personalization_data: Optional[Dict] = None
    ) -> List[EmailResult]:
        """
        Send batch emails with personalization
        """
        results = []
        
        for recipient in recipients:
            # Personalize content
            personalized_body = body_template
            if personalization_data and recipient.get('id') in personalization_data:
                data = personalization_data[recipient['id']]
                for key, value in data.items():
                    personalized_body = personalized_body.replace(f"{{{key}}}", str(value))
            
            # Send individual email
            result = await self.send_email(
                to_email=recipient['email'],
                subject=subject,
                body=personalized_body,
                custom_args={'recipient_id': str(recipient.get('id', ''))}
            )
            
            results.append(result)
            
            # Stop if hitting limits
            if not result.success and "limit" in result.error_message.lower():
                break
        
        return results

    async def send_password_reset_email(
        self,
        to_email: str,
        reset_url: str,
        expires_minutes: int = 15
    ) -> EmailResult:
        """
        Send password reset email with secure link
        """
        subject = "Tailored Agents AI • Reset Your VouchLink Password"
        template_id = getattr(settings, "SENDGRID_PASSWORD_RESET_TEMPLATE_ID", None)
        support_email = getattr(settings, "SUPPORT_CONTACT_EMAIL", None) or self.from_email

        if template_id:
            return await self.send_email(
                to_email=to_email,
                subject=subject,
                body="Reset your password",
                template_id=template_id,
                dynamic_data={
                    "reset_url": reset_url,
                    "expires_minutes": expires_minutes,
                    "support_email": support_email,
                },
                add_unsubscribe=False,
            )

        # HTML email template
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Reset Your Password</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background-color: #f5f5f5; }}
                .container {{ max-width: 600px; margin: 0 auto; background-color: white; }}
                .header {{ background: linear-gradient(135deg, #1f2937, #374151); color: white; padding: 40px 30px; text-align: center; }}
                .logo {{ display: inline-flex; align-items: center; margin-bottom: 10px; }}
                .logo-icon {{ width: 32px; height: 32px; background-color: #fbbf24; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: black; font-weight: bold; font-size: 18px; margin-right: 12px; }}
                .content {{ padding: 40px 30px; }}
                .button {{ display: inline-block; background-color: #000; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: 600; margin: 20px 0; }}
                .button:hover {{ background-color: #374151; }}
                .footer {{ background-color: #f9fafb; padding: 30px; text-align: center; color: #6b7280; font-size: 14px; }}
                .security-notice {{ background-color: #fef3c7; border-left: 4px solid #f59e0b; padding: 16px; margin: 20px 0; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">
                        <div class="logo-icon">T</div>
                        <div>
                            <div style="font-size: 24px; font-weight: bold;">VouchLink AI</div>
                            <div style="font-size: 14px; color: #d1d5db;">Powered by Tailored Agents AI</div>
                        </div>
                    </div>
                </div>

                <div class="content">
                    <h2 style="color: #1f2937; margin-bottom: 20px;">Reset Your Password</h2>

                    <p style="color: #4b5563; line-height: 1.6;">
                        We received a request to reset the password for your VouchLink AI account.
                        Tailored Agents AI secures this process with a one-time, time-boxed link. Click the button below to create a new password:
                    </p>

                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{reset_url}" class="button">Reset Password</a>
                    </div>

                    <div class="security-notice">
                        <strong>Security Notice:</strong>
                        <ul style="margin: 8px 0; padding-left: 20px;">
                            <li>This link will expire in {expires_minutes} minutes</li>
                            <li>It can only be used once</li>
                            <li>If you didn't request this reset, please ignore this email</li>
                        </ul>
                    </div>

                    <p style="color: #6b7280; font-size: 14px; margin-top: 30px;">
                        If you're having trouble clicking the button, copy and paste this URL into your browser:<br>
                        <a href="{reset_url}" style="color: #2563eb; word-break: break-all;">{reset_url}</a>
                    </p>
                </div>

                <div class="footer">
                    <p>This automated message was sent by Tailored Agents AI on behalf of VouchLink AI. For help, contact {support_email}.</p>
                    <p>© {datetime.now().year} Tailored Agents AI · VouchLink AI. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        # Plain text fallback
        text_body = f"""
        Reset Your VouchLink AI Password

        We received a request to reset the password for your VouchLink AI account.

        Click this link to create a new password:
        {reset_url}

        SECURITY NOTICE:
        - This link will expire in {expires_minutes} minutes
        - It can only be used once
        - If you didn't request this reset, please ignore this email

        If the link doesn't work, copy and paste this URL into your browser:
        {reset_url}

        ---
        This is an automated email from VouchLink AI. Please do not reply.
        © {datetime.now().year} VouchLink AI. All rights reserved.
        """

        return await self.send_email(
            to_email=to_email,
            subject=subject,
            body=text_body,
            body_html=html_body,
            categories=["password_reset"],
            custom_args={"email_type": "password_reset"},
            track_opens=False,  # Don't track opens for security emails
            track_clicks=True,  # But do track clicks for security monitoring
            add_unsubscribe=False  # Don't add unsubscribe to security emails
        )

    async def verify_domain(self, domain: str) -> Dict:
        """
        Initiate domain verification process
        Returns DNS records to add
        """
        try:
            # SendGrid domain authentication API
            response = self.client.client.whitelabel.domains.post(
                request_body={
                    "domain": domain,
                    "subdomain": "em",
                    "automatic_security": True,
                    "custom_spf": False,
                    "default": True
                }
            )
            
            if response.status_code == 201:
                data = json.loads(response.body)
                return {
                    'status': 'pending',
                    'domain_id': data['id'],
                    'dns_records': data['dns']
                }
            
            return {
                'status': 'error',
                'message': f"Failed to initiate verification: {response.body}"
            }
            
        except Exception as e:
            logger.error(f"Domain verification failed: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    async def check_domain_verification(self, domain_id: int) -> Dict:
        """Check domain verification status"""
        try:
            response = self.client.client.whitelabel.domains._(domain_id).validate.post()
            
            if response.status_code == 200:
                data = json.loads(response.body)
                return {
                    'verified': data['valid'],
                    'validation_results': data['validation_results']
                }
            
            return {'verified': False, 'error': response.body}
            
        except Exception as e:
            logger.error(f"Verification check failed: {e}")
            return {'verified': False, 'error': str(e)}
    
    async def add_to_suppression(
        self,
        email: str,
        reason: str,
        suppression_type: str = 'manual'
    ):
        """Add email to suppression list"""
        if not self.tenant_id:
            return
            
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO email_suppression_list (tenant_id, email, reason, type, added_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(tenant_id, email, reason) DO UPDATE SET reason = EXCLUDED.reason, type = EXCLUDED.type
            """, (
                self.tenant_id, email, reason, suppression_type,
                datetime.now()
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Skipping suppression add (missing schema?): {e}")
    
    async def process_webhook_event(self, event: Dict):
        """Process SendGrid webhook events"""
        event_type = event.get('event')
        email = event.get('email')
        
        if not email:
            return
        
        # Map events to our status enum
        status_mapping = {
            'delivered': EmailStatus.DELIVERED,
            'open': EmailStatus.OPENED,
            'click': EmailStatus.CLICKED,
            'bounce': EmailStatus.BOUNCED,
            'dropped': EmailStatus.DROPPED,
            'spamreport': EmailStatus.SPAM_REPORT,
            'unsubscribe': EmailStatus.UNSUBSCRIBED,
            'deferred': EmailStatus.DEFERRED
        }
        
        status = status_mapping.get(event_type)
        if not status:
            return
        
        # Update email metrics
        if self.tenant_id:
            conn = get_db()
            cursor = conn.cursor()
            
            # Get contact ID from email
            cursor.execute("""
                SELECT id FROM contacts 
                WHERE email = %s AND tenant_id = %s
            """, (email, self.tenant_id))
            
            contact = cursor.fetchone()
            if contact:
                # Convert to dict if it's not already
                if hasattr(contact, '_asdict'):
                    contact = contact._asdict()
                elif hasattr(contact, 'keys') and hasattr(contact, 'values'):
                    contact = dict(contact)

                # Get contact ID
                contact_id = None
                if hasattr(contact, 'get'):
                    contact_id = contact.get('id')
                elif isinstance(contact, dict):
                    contact_id = contact.get('id')
                elif hasattr(contact, '__getitem__'):
                    contact_id = contact[0] if len(contact) > 0 else None

                if contact_id:
                    # Update metrics based on event
                    if status == EmailStatus.DELIVERED:
                        cursor.execute("""
                            UPDATE email_metrics
                            SET sent_count = sent_count + 1
                            WHERE contact_id = %s AND tenant_id = %s
                        """, (contact_id, self.tenant_id))
                    
                    elif status == EmailStatus.OPENED:
                        cursor.execute("""
                            UPDATE email_metrics
                            SET open_count = open_count + 1
                            WHERE contact_id = %s AND tenant_id = %s
                        """, (contact_id, self.tenant_id))

                    elif status == EmailStatus.CLICKED:
                        cursor.execute("""
                            UPDATE email_metrics
                            SET click_count = click_count + 1
                            WHERE contact_id = %s AND tenant_id = %s
                        """, (contact_id, self.tenant_id))

                    elif status == EmailStatus.BOUNCED:
                        cursor.execute("""
                            UPDATE email_metrics
                            SET bounce_count = bounce_count + 1
                            WHERE contact_id = %s AND tenant_id = %s
                        """, (contact_id, self.tenant_id))
                    
                    # Add to suppression list
                    await self.add_to_suppression(email, 'bounced', 'bounce')
                    
                elif status == EmailStatus.SPAM_REPORT:
                    # Add to suppression list
                    await self.add_to_suppression(email, 'spam report', 'complaint')
                    
                elif status == EmailStatus.UNSUBSCRIBED:
                    # Add to suppression list
                    await self.add_to_suppression(email, 'unsubscribed', 'unsubscribe')
            
            # Store raw webhook event
            cursor.execute("""
                INSERT INTO email_webhook_events 
                (event_id, message_id, tenant_id, email, event_type, timestamp, payload, processed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
            """, (
                event.get('sg_event_id'),
                event.get('sg_message_id'),
                self.tenant_id,
                email,
                event_type,
                datetime.fromtimestamp(event.get('timestamp', 0)),
                json.dumps(event)
            ))
            
            conn.commit()
            conn.close()

# Singleton instance management
_sendgrid_clients = {}

def get_sendgrid_client(tenant_id: Optional[int] = None) -> SendGridClient:
    """Get or create SendGrid client for tenant"""
    existing = _sendgrid_clients.get(tenant_id)
    if existing is None:
        _sendgrid_clients[tenant_id] = SendGridClient(tenant_id=tenant_id)
        return _sendgrid_clients[tenant_id]

    # Detect API key changes at runtime and refresh the client to avoid stale 401s
    try:
        resolved = existing._get_api_key_for_tenant(tenant_id) if tenant_id else settings.SENDGRID_API_KEY
        if resolved and resolved != existing.api_key:
            logger.info(f"SendGrid API key updated for tenant {tenant_id}; refreshing client")
            _sendgrid_clients[tenant_id] = SendGridClient(tenant_id=tenant_id)
    except Exception as e:
        logger.debug(f"SendGrid client refresh check failed: {e}")

    return _sendgrid_clients[tenant_id]
