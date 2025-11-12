#!/usr/bin/env python3
"""
SendGrid Email Service Integration
Provides enterprise-grade email delivery with tracking and analytics
"""

import logging
import os
import json
from typing import Dict, List, Any, Optional
from datetime import datetime
import asyncio
import aiohttp
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class EmailAttachment:
    """Email attachment data"""
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"

@dataclass
class EmailRecipient:
    """Email recipient data"""
    email: str
    name: Optional[str] = None

@dataclass
class EmailTemplate:
    """Email template data"""
    template_id: str
    dynamic_data: Dict[str, Any]

class SendGridService:
    """
    SendGrid email service for transactional and marketing emails
    Supports templates, attachments, and delivery tracking
    """

    def __init__(self, api_key: Optional[str] = None, verified_sender: Optional[str] = None):
        self.api_key = api_key or os.getenv("SENDGRID_API_KEY")
        env_verified_sender = os.getenv("SENDGRID_VERIFIED_SENDER")
        self.verified_sender = verified_sender or env_verified_sender or ""
        self.base_url = "https://api.sendgrid.com/v3"
        self.session = None
        self._is_configured = bool(self.api_key) and bool(self.verified_sender)

    async def initialize(self):
        """Initialize SendGrid service"""
        if not self.api_key or not self.verified_sender:
            logger.warning("⚠️ SendGrid service not fully configured - email features disabled")
            return False

        # Create HTTP session
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=300,
            use_dns_cache=True
        )

        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        )

        # Test API connectivity
        try:
            health_status = await self.get_health_status()
            if health_status.get("status") == "healthy":
                logger.info("✅ SendGrid service initialized successfully")
                return True
            else:
                logger.error(f"❌ SendGrid initialization failed: {health_status.get('error')}")
                return False

        except Exception as e:
            logger.error(f"❌ SendGrid initialization error: {e}")
            return False

    @property
    def is_configured(self) -> bool:
        """Check if SendGrid is properly configured"""
        return self._is_configured and self.session is not None

    async def send_email(self,
                        to_recipients: List[EmailRecipient],
                        subject: str,
                        html_content: Optional[str] = None,
                        text_content: Optional[str] = None,
                        from_email: Optional[str] = None,
                        from_name: Optional[str] = None,
                        cc_recipients: Optional[List[EmailRecipient]] = None,
                        bcc_recipients: Optional[List[EmailRecipient]] = None,
                        attachments: Optional[List[EmailAttachment]] = None,
                        template: Optional[EmailTemplate] = None,
                        custom_args: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Send email via SendGrid API
        """
        if not self.is_configured:
            return {
                "success": False,
                "error": "SendGrid not configured",
                "message_id": None
            }

        try:
            # Prepare email payload
            payload = {
                "personalizations": [{
                    "to": [{"email": r.email, "name": r.name} for r in to_recipients]
                }],
                "from": {
                    "email": from_email or self.verified_sender,
                    "name": from_name or "System"
                },
                "subject": subject
            }

            # Add CC recipients
            if cc_recipients:
                payload["personalizations"][0]["cc"] = [
                    {"email": r.email, "name": r.name} for r in cc_recipients
                ]

            # Add BCC recipients
            if bcc_recipients:
                payload["personalizations"][0]["bcc"] = [
                    {"email": r.email, "name": r.name} for r in bcc_recipients
                ]

            # Add content
            if template:
                # Use dynamic template
                payload["template_id"] = template.template_id
                payload["personalizations"][0]["dynamic_template_data"] = template.dynamic_data
            else:
                # Use static content
                content = []
                if text_content:
                    content.append({"type": "text/plain", "value": text_content})
                if html_content:
                    content.append({"type": "text/html", "value": html_content})

                if not content:
                    raise ValueError("Either content or template must be provided")

                payload["content"] = content

            # Add attachments
            if attachments:
                payload["attachments"] = []
                for attachment in attachments:
                    import base64
                    payload["attachments"].append({
                        "content": base64.b64encode(attachment.content).decode(),
                        "filename": attachment.filename,
                        "type": attachment.content_type
                    })

            # Add custom tracking arguments
            if custom_args:
                payload["custom_args"] = custom_args

            # Add tracking settings
            payload["tracking_settings"] = {
                "click_tracking": {"enable": True},
                "open_tracking": {"enable": True},
                "subscription_tracking": {"enable": False}
            }

            # Send email
            async with self.session.post(f"{self.base_url}/mail/send", json=payload) as response:
                if response.status == 202:
                    # Extract message ID from headers
                    message_id = response.headers.get("X-Message-Id", "unknown")

                    logger.info(f"Email sent successfully to {len(to_recipients)} recipients. Message ID: {message_id}")

                    return {
                        "success": True,
                        "message_id": message_id,
                        "status_code": response.status,
                        "recipients": len(to_recipients)
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"SendGrid API error {response.status}: {error_text}")

                    return {
                        "success": False,
                        "error": f"API error {response.status}",
                        "details": error_text,
                        "message_id": None
                    }

        except Exception as e:
            logger.error(f"Send email error: {e}")
            return {
                "success": False,
                "error": str(e),
                "message_id": None
            }

    async def send_template_email(self,
                                to_recipients: List[EmailRecipient],
                                template_id: str,
                                dynamic_data: Dict[str, Any],
                                from_email: Optional[str] = None,
                                custom_args: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Send email using SendGrid dynamic template"""
        template = EmailTemplate(template_id=template_id, dynamic_data=dynamic_data)

        return await self.send_email(
            to_recipients=to_recipients,
            subject="",  # Template handles subject
            template=template,
            from_email=from_email,
            custom_args=custom_args
        )

    async def get_delivery_status(self, message_id: str) -> Dict[str, Any]:
        """Get email delivery status by message ID"""
        if not self.is_configured:
            return {"error": "SendGrid not configured"}

        try:
            # Query activity API
            url = f"{self.base_url}/messages/{message_id}"

            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "message_id": message_id,
                        "status": data.get("status", "unknown"),
                        "events": data.get("events", []),
                        "delivered_at": data.get("delivered_at"),
                        "opened_at": data.get("opened_at"),
                        "clicked_at": data.get("clicked_at")
                    }
                else:
                    return {
                        "error": f"API error {response.status}",
                        "message_id": message_id
                    }

        except Exception as e:
            logger.error(f"Get delivery status error: {e}")
            return {"error": str(e), "message_id": message_id}

    async def validate_email_address(self, email: str) -> Dict[str, Any]:
        """Validate email address using SendGrid validation API"""
        if not self.is_configured:
            return {"error": "SendGrid not configured"}

        try:
            url = f"{self.base_url}/validations/email"
            payload = {"email": email}

            async with self.session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "email": email,
                        "is_valid": data.get("verdict", {}).get("result") == "Valid",
                        "score": data.get("verdict", {}).get("score", 0),
                        "local": data.get("local"),
                        "host": data.get("host"),
                        "suggestion": data.get("suggestion"),
                        "checks": data.get("checks", {})
                    }
                else:
                    error_text = await response.text()
                    return {
                        "error": f"Validation API error {response.status}",
                        "details": error_text,
                        "email": email
                    }

        except Exception as e:
            logger.error(f"Email validation error: {e}")
            return {"error": str(e), "email": email}

    async def get_templates(self) -> List[Dict[str, Any]]:
        """Get list of dynamic templates"""
        if not self.is_configured:
            return []

        try:
            url = f"{self.base_url}/templates"

            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("templates", [])
                else:
                    logger.error(f"Get templates error {response.status}")
                    return []

        except Exception as e:
            logger.error(f"Get templates error: {e}")
            return []

    async def create_contact_list(self, list_name: str, contacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create a contact list for marketing campaigns"""
        if not self.is_configured:
            return {"error": "SendGrid not configured"}

        try:
            # First create the list
            list_payload = {"name": list_name}

            async with self.session.post(f"{self.base_url}/marketing/lists", json=list_payload) as response:
                if response.status != 201:
                    error_text = await response.text()
                    return {"error": f"List creation failed: {error_text}"}

                list_data = await response.json()
                list_id = list_data["id"]

            # Add contacts to the list
            if contacts:
                contact_payload = {
                    "list_ids": [list_id],
                    "contacts": contacts
                }

                async with self.session.put(f"{self.base_url}/marketing/contacts", json=contact_payload) as response:
                    if response.status == 202:
                        return {
                            "success": True,
                            "list_id": list_id,
                            "list_name": list_name,
                            "contact_count": len(contacts)
                        }
                    else:
                        error_text = await response.text()
                        return {"error": f"Contact upload failed: {error_text}"}

            return {
                "success": True,
                "list_id": list_id,
                "list_name": list_name,
                "contact_count": 0
            }

        except Exception as e:
            logger.error(f"Create contact list error: {e}")
            return {"error": str(e)}

    async def get_health_status(self) -> Dict[str, Any]:
        """Get SendGrid service health status"""
        if not self.api_key:
            return {
                "status": "not_configured",
                "configured": False,
                "error": "API key not provided"
            }

        if not self.session:
            return {
                "status": "not_initialized",
                "configured": True,
                "error": "Session not initialized"
            }

        try:
            # Test API with a simple request
            async with self.session.get(f"{self.base_url}/user/profile") as response:
                if response.status == 200:
                    profile = await response.json()
                    return {
                        "status": "healthy",
                        "configured": True,
                        "api_key_valid": True,
                        "username": profile.get("username", "unknown"),
                        "email": profile.get("email", "unknown")
                    }
                elif response.status == 401:
                    return {
                        "status": "unauthorized",
                        "configured": True,
                        "api_key_valid": False,
                        "error": "Invalid API key"
                    }
                else:
                    return {
                        "status": "error",
                        "configured": True,
                        "error": f"API returned status {response.status}"
                    }

        except Exception as e:
            return {
                "status": "connection_error",
                "configured": True,
                "error": str(e)
            }

    async def get_usage_stats(self) -> Dict[str, Any]:
        """Get SendGrid usage statistics"""
        if not self.is_configured:
            return {"error": "SendGrid not configured"}

        try:
            # Get current month stats
            from datetime import date
            today = date.today()
            start_date = today.replace(day=1).strftime("%Y-%m-%d")
            end_date = today.strftime("%Y-%m-%d")

            url = f"{self.base_url}/stats"
            params = {
                "start_date": start_date,
                "end_date": end_date,
                "aggregated_by": "day"
            }

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()

                    # Calculate totals
                    totals = {
                        "requests": 0,
                        "delivered": 0,
                        "bounces": 0,
                        "spam_reports": 0,
                        "opens": 0,
                        "clicks": 0
                    }

                    for day_stats in data:
                        stats = day_stats.get("stats", [{}])[0].get("metrics", {})
                        for key in totals.keys():
                            totals[key] += stats.get(key, 0)

                    return {
                        "period": f"{start_date} to {end_date}",
                        "totals": totals,
                        "daily_stats": data
                    }
                else:
                    return {"error": f"Stats API error {response.status}"}

        except Exception as e:
            logger.error(f"Get usage stats error: {e}")
            return {"error": str(e)}

    async def close(self):
        """Close SendGrid service"""
        if self.session:
            await self.session.close()
            self.session = None

        logger.info("SendGrid service closed")

# Global SendGrid instance
sendgrid_service = SendGridService()