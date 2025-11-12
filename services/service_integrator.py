#!/usr/bin/env python3
"""
Service Integration Layer
Coordinates all external services with proper error handling and fallbacks
"""

import logging
import asyncio
import os
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass

from .redis_service import redis_service
from .sendgrid_service import sendgrid_service, EmailRecipient
from .rate_limiting_service import RateLimitingService

logger = logging.getLogger(__name__)

@dataclass
class ServiceHealth:
    """Service health status"""
    name: str
    status: str
    connected: bool
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class ServiceIntegrator:
    """
    Coordinates all external services with proper initialization,
    health checking, and graceful degradation
    """

    def __init__(self):
        self.services = {}
        self.health_status = {}
        self.rate_limiter = None
        self._initialized = False

    async def initialize_all_services(self) -> Dict[str, bool]:
        """Initialize all external services"""
        logger.info("🚀 Initializing all external services...")

        initialization_results = {}

        # Initialize Redis
        try:
            redis_result = await redis_service.initialize()
            initialization_results["redis"] = redis_result
            self.services["redis"] = redis_service
            logger.info(f"Redis initialization: {'✅ Success' if redis_result else '❌ Failed'}")
        except Exception as e:
            logger.error(f"Redis initialization error: {e}")
            initialization_results["redis"] = False

        # Initialize SendGrid
        try:
            sendgrid_result = await sendgrid_service.initialize()
            initialization_results["sendgrid"] = sendgrid_result
            self.services["sendgrid"] = sendgrid_service
            logger.info(f"SendGrid initialization: {'✅ Success' if sendgrid_result else '❌ Failed'}")
        except Exception as e:
            logger.error(f"SendGrid initialization error: {e}")
            initialization_results["sendgrid"] = False

        # Initialize Rate Limiter (depends on Redis)
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self.rate_limiter = RateLimitingService(redis_url=redis_url)
            rate_limit_result = await self.rate_limiter.initialize()
            initialization_results["rate_limiter"] = rate_limit_result
            self.services["rate_limiter"] = self.rate_limiter
            logger.info(f"Rate Limiter initialization: {'✅ Success' if rate_limit_result else '❌ Failed'}")
        except Exception as e:
            logger.error(f"Rate Limiter initialization error: {e}")
            initialization_results["rate_limiter"] = False

        self._initialized = True

        # Log overall status
        successful_services = sum(1 for success in initialization_results.values() if success)
        total_services = len(initialization_results)

        logger.info(f"🎯 Service initialization complete: {successful_services}/{total_services} services online")

        return initialization_results

    async def check_all_health(self) -> Dict[str, ServiceHealth]:
        """Check health of all services"""
        health_results = {}

        # Check Redis health
        try:
            redis_health = await redis_service.get_health_status()
            health_results["redis"] = ServiceHealth(
                name="Redis",
                status=redis_health.get("status", "unknown"),
                connected=redis_health.get("connected", False),
                error=redis_health.get("error"),
                details=redis_health
            )
        except Exception as e:
            health_results["redis"] = ServiceHealth(
                name="Redis",
                status="error",
                connected=False,
                error=str(e)
            )

        # Check SendGrid health
        try:
            sendgrid_health = await sendgrid_service.get_health_status()
            health_results["sendgrid"] = ServiceHealth(
                name="SendGrid",
                status=sendgrid_health.get("status", "unknown"),
                connected=sendgrid_health.get("configured", False),
                error=sendgrid_health.get("error"),
                details=sendgrid_health
            )
        except Exception as e:
            health_results["sendgrid"] = ServiceHealth(
                name="SendGrid",
                status="error",
                connected=False,
                error=str(e)
            )

        # Check Rate Limiter health
        if self.rate_limiter:
            try:
                rate_limit_health = await self.rate_limiter.get_health_status()
                health_results["rate_limiter"] = ServiceHealth(
                    name="Rate Limiter",
                    status=rate_limit_health.get("status", "unknown"),
                    connected=rate_limit_health.get("connected", False),
                    error=rate_limit_health.get("error"),
                    details=rate_limit_health
                )
            except Exception as e:
                health_results["rate_limiter"] = ServiceHealth(
                    name="Rate Limiter",
                    status="error",
                    connected=False,
                    error=str(e)
                )

        self.health_status = health_results
        return health_results

    async def send_notification_email(self,
                                    recipient_email: str,
                                    subject: str,
                                    html_content: str,
                                    text_content: Optional[str] = None,
                                    organization_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Send notification email with caching and rate limiting
        """
        # Check rate limit if enabled
        if self.rate_limiter and organization_id:
            rate_limit_key = f"email_notifications:org:{organization_id}"
            is_allowed, remaining = await self.rate_limiter.check_rate_limit(
                rate_limit_key,
                limit=50,  # 50 emails per hour per organization
                window=3600
            )

            if not is_allowed:
                logger.warning(f"Email rate limit exceeded for organization {organization_id}")
                return {
                    "success": False,
                    "error": "Rate limit exceeded",
                    "rate_limit_remaining": remaining
                }

        # Send email via SendGrid
        recipients = [EmailRecipient(email=recipient_email)]

        result = await sendgrid_service.send_email(
            to_recipients=recipients,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            custom_args={"organization_id": str(organization_id)} if organization_id else None
        )

        # Cache email delivery status if successful
        if result.get("success") and result.get("message_id"):
            cache_key = f"email_delivery:{result['message_id']}"
            cache_data = {
                "recipient": recipient_email,
                "subject": subject,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "organization_id": organization_id,
                "status": "sent"
            }
            await redis_service.set_json(cache_key, cache_data, ttl=86400)  # Cache for 24 hours

        return result

    async def cache_api_response(self,
                                cache_key: str,
                                data: Dict[str, Any],
                                ttl: int = 3600) -> bool:
        """Cache API response with fallback handling"""
        try:
            return await redis_service.set_json(cache_key, data, ttl)
        except Exception as e:
            logger.warning(f"Cache write failed for key {cache_key}: {e}")
            return False

    async def get_cached_api_response(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached API response with fallback handling"""
        try:
            return await redis_service.get_json(cache_key)
        except Exception as e:
            logger.warning(f"Cache read failed for key {cache_key}: {e}")
            return None

    async def validate_email_with_cache(self, email: str) -> Dict[str, Any]:
        """Validate email with caching"""
        # Check cache first
        cached_result = await redis_service.get_cached_email_validation(email)
        if cached_result:
            logger.debug(f"Email validation cache hit for {email}")
            return cached_result

        # Validate with SendGrid
        validation_result = await sendgrid_service.validate_email_address(email)

        # Cache the result
        if not validation_result.get("error"):
            await redis_service.cache_email_validation(
                email,
                validation_result.get("is_valid", False),
                validation_result,
                ttl=3600  # Cache for 1 hour
            )

        return validation_result

    async def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive status of all services"""
        health_status = await self.check_all_health()

        # Count healthy services
        healthy_count = sum(1 for health in health_status.values() if health.connected)
        total_count = len(health_status)

        # Calculate overall health score
        health_score = (healthy_count / total_count * 100) if total_count > 0 else 0

        # Determine overall status
        overall_status = "healthy" if health_score >= 80 else "degraded" if health_score >= 50 else "critical"

        return {
            "overall_status": overall_status,
            "health_score": health_score,
            "healthy_services": healthy_count,
            "total_services": total_count,
            "services": {name: {
                "status": health.status,
                "connected": health.connected,
                "error": health.error
            } for name, health in health_status.items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "initialized": self._initialized
        }

    async def send_system_alert(self,
                              alert_type: str,
                              message: str,
                              details: Optional[Dict[str, Any]] = None,
                              organization_id: Optional[int] = None):
        """Send system alert via email"""
        admin_email = os.getenv("ADMIN_EMAIL")
        if not admin_email:
            logger.error("Cannot send system alert without ADMIN_EMAIL configured")
            return

        alert_subject = f"System Alert: {alert_type}"
        alert_html = f"""
        <html>
        <body>
            <h2>System Alert</h2>
            <p><strong>Type:</strong> {alert_type}</p>
            <p><strong>Message:</strong> {message}</p>
            <p><strong>Timestamp:</strong> {datetime.now(timezone.utc).isoformat()}</p>

            {f'<p><strong>Organization ID:</strong> {organization_id}</p>' if organization_id else ''}

            {f'<h3>Details:</h3><pre>{details}</pre>' if details else ''}
        </body>
        </html>
        """

        alert_text = f"""
        System Alert: {alert_type}

        Message: {message}
        Timestamp: {datetime.now(timezone.utc).isoformat()}
        {f'Organization ID: {organization_id}' if organization_id else ''}

        {f'Details: {details}' if details else ''}
        """

        try:
            result = await self.send_notification_email(
                recipient_email=admin_email,
                subject=alert_subject,
                html_content=alert_html,
                text_content=alert_text,
                organization_id=organization_id
            )

            if result.get("success"):
                logger.info(f"System alert sent successfully: {alert_type}")
            else:
                logger.error(f"Failed to send system alert: {result.get('error')}")

        except Exception as e:
            logger.error(f"System alert sending error: {e}")

    async def graceful_shutdown(self):
        """Gracefully shutdown all services"""
        logger.info("🔄 Shutting down all services...")

        shutdown_tasks = []

        # Add shutdown tasks for all services
        if redis_service.is_connected:
            shutdown_tasks.append(redis_service.close())

        if sendgrid_service.is_configured:
            shutdown_tasks.append(sendgrid_service.close())

        if self.rate_limiter:
            shutdown_tasks.append(self.rate_limiter.close())

        # Execute all shutdowns concurrently
        if shutdown_tasks:
            await asyncio.gather(*shutdown_tasks, return_exceptions=True)

        logger.info("✅ All services shut down gracefully")

# Global service integrator instance
service_integrator = ServiceIntegrator()