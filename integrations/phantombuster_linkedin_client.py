"""
PhantomBuster LinkedIn Messaging Client
Handles LinkedIn message automation via PhantomBuster API
"""

import logging
import asyncio
import aiohttp
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

@dataclass
class LinkedInMessageResult:
    success: bool
    container_id: str
    phantom_id: str
    status: str
    message: str
    cost: float
    estimated_completion: Optional[datetime] = None
    error: Optional[str] = None

@dataclass
class CampaignStatus:
    container_id: str
    status: str  # "running", "completed", "failed", "stopped"
    progress: float  # 0-100
    messages_sent: int
    messages_failed: int
    messages_pending: int
    current_recipient: Optional[str]
    next_message_eta: Optional[datetime]
    completion_time: Optional[datetime]
    error_details: Optional[str]

class PhantomBusterLinkedInClient:
    """
    PhantomBuster client for LinkedIn message automation
    """
    
    LINKEDIN_MESSAGE_SENDER_ID = "phantombuster/linkedin-message-sender"
    BASE_URL = "https://api.phantombuster.com/api/v2"
    RATE_LIMIT_PER_DAY = 300
    COST_PER_MESSAGE = 0.10  # Estimated cost
    
    def __init__(self, api_key: str, linkedin_session_cookie: str):
        self.api_key = api_key
        self.linkedin_session = linkedin_session_cookie
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers={"X-Phantombuster-Key": self.api_key},
            timeout=aiohttp.ClientTimeout(total=300)  # 5 minute timeout
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test PhantomBuster API connection and LinkedIn session"""
        try:
            async with self:
                # Test API connection
                async with self.session.get(f"{self.BASE_URL}/user") as response:
                    if response.status != 200:
                        return {
                            "success": False,
                            "error": f"API connection failed: {response.status}",
                            "linkedin_valid": False
                        }
                
                user_data = await response.json()
                
                # Test LinkedIn session validity by launching a simple phantom
                test_result = await self._test_linkedin_session()
                
                return {
                    "success": True,
                    "api_valid": True,
                    "linkedin_valid": test_result["valid"],
                    "daily_quota_used": test_result.get("quota_used", 0),
                    "daily_quota_remaining": self.RATE_LIMIT_PER_DAY - test_result.get("quota_used", 0),
                    "user_info": user_data.get("data", {})
                }
                
        except Exception as e:
            logger.error(f"PhantomBuster connection test failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "linkedin_valid": False
            }
    
    async def send_linkedin_message(
        self,
        recipient_linkedin_url: str,
        message: str,
        delay_seconds: int = 120,
        send_connection_request: bool = False
    ) -> LinkedInMessageResult:
        """
        Send a LinkedIn message via PhantomBuster
        """
        try:
            async with self:
                # Prepare phantom arguments
                phantom_args = {
                    "profileUrls": [recipient_linkedin_url],
                    "message": message,
                    "sessionCookie": self.linkedin_session,
                    "delayBetweenMessages": delay_seconds,
                    "onlyConnections": not send_connection_request,
                    "disableScraping": True,  # Focus only on messaging
                    "csvName": f"linkedin_messages_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                }
                
                # Launch the phantom
                launch_data = {
                    "id": self.LINKEDIN_MESSAGE_SENDER_ID,
                    "argument": phantom_args,
                    "bonusArgument": {
                        "enableCsvExport": True,
                        "enableScreenshots": False  # Save costs
                    }
                }
                
                async with self.session.post(
                    f"{self.BASE_URL}/phantoms/launch",
                    json=launch_data
                ) as response:
                    
                    if response.status != 200:
                        error_data = await response.json() if response.content_type == 'application/json' else {}
                        return LinkedInMessageResult(
                            success=False,
                            container_id="",
                            phantom_id="",
                            status="failed",
                            message=message,
                            cost=0.0,
                            error=f"Launch failed: {error_data.get('error', f'HTTP {response.status}')}"
                        )
                    
                    result = await response.json()
                    
                    # Extract response data
                    container_id = result.get("containerId", "")
                    phantom_id = result.get("phantomId", "")
                    
                    # Estimate completion time
                    estimated_completion = datetime.now() + timedelta(seconds=delay_seconds + 180)
                    
                    return LinkedInMessageResult(
                        success=True,
                        container_id=container_id,
                        phantom_id=phantom_id,
                        status="running",
                        message=message,
                        cost=self.COST_PER_MESSAGE,
                        estimated_completion=estimated_completion
                    )
                    
        except Exception as e:
            logger.error(f"LinkedIn message sending failed: {e}")
            return LinkedInMessageResult(
                success=False,
                container_id="",
                phantom_id="",
                status="failed",
                message=message,
                cost=0.0,
                error=str(e)
            )
    
    async def send_bulk_linkedin_messages(
        self,
        recipients: List[Dict[str, str]],  # [{"linkedin_url": "...", "name": "...", "message": "..."}]
        delay_between_messages: int = 180,
        batch_delay: int = 600
    ) -> LinkedInMessageResult:
        """
        Send multiple LinkedIn messages with proper delays
        """
        try:
            async with self:
                # Prepare bulk message data
                profile_urls = [r["linkedin_url"] for r in recipients]
                messages = [r["message"] for r in recipients]
                
                phantom_args = {
                    "profileUrls": profile_urls,
                    "messages": messages,  # Different message per recipient
                    "sessionCookie": self.linkedin_session,
                    "delayBetweenMessages": delay_between_messages,
                    "delayBetweenBatches": batch_delay,
                    "onlyConnections": True,
                    "disableScraping": True,
                    "csvName": f"linkedin_bulk_messages_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                }
                
                launch_data = {
                    "id": self.LINKEDIN_MESSAGE_SENDER_ID,
                    "argument": phantom_args
                }
                
                async with self.session.post(
                    f"{self.BASE_URL}/phantoms/launch",
                    json=launch_data
                ) as response:
                    
                    if response.status != 200:
                        error_data = await response.json() if response.content_type == 'application/json' else {}
                        return LinkedInMessageResult(
                            success=False,
                            container_id="",
                            phantom_id="",
                            status="failed",
                            message=f"Bulk message to {len(recipients)} recipients",
                            cost=0.0,
                            error=f"Launch failed: {error_data.get('error', f'HTTP {response.status}')}"
                        )
                    
                    result = await response.json()
                    
                    # Calculate total cost and estimated completion
                    total_cost = len(recipients) * self.COST_PER_MESSAGE
                    total_time = len(recipients) * delay_between_messages
                    estimated_completion = datetime.now() + timedelta(seconds=total_time + 300)
                    
                    return LinkedInMessageResult(
                        success=True,
                        container_id=result.get("containerId", ""),
                        phantom_id=result.get("phantomId", ""),
                        status="running",
                        message=f"Bulk message to {len(recipients)} recipients",
                        cost=total_cost,
                        estimated_completion=estimated_completion
                    )
                    
        except Exception as e:
            logger.error(f"Bulk LinkedIn messaging failed: {e}")
            return LinkedInMessageResult(
                success=False,
                container_id="",
                phantom_id="",
                status="failed",
                message=f"Bulk message to {len(recipients)} recipients",
                cost=0.0,
                error=str(e)
            )
    
    async def get_campaign_status(self, container_id: str) -> CampaignStatus:
        """
        Get the status of a LinkedIn messaging campaign
        """
        try:
            async with self:
                # Fetch container status
                async with self.session.get(
                    f"{self.BASE_URL}/containers/fetch-output",
                    params={"containerId": container_id}
                ) as response:
                    
                    if response.status != 200:
                        return CampaignStatus(
                            container_id=container_id,
                            status="unknown",
                            progress=0.0,
                            messages_sent=0,
                            messages_failed=0,
                            messages_pending=0,
                            current_recipient=None,
                            next_message_eta=None,
                            completion_time=None,
                            error_details=f"Status fetch failed: HTTP {response.status}"
                        )
                    
                    data = await response.json()
                    
                    # Parse container data
                    container_data = data.get("data", {})
                    phantom_status = container_data.get("status", "unknown")
                    progress = container_data.get("progress", 0)
                    
                    # Parse output data for message statistics
                    output_data = container_data.get("output", [])
                    messages_sent = len([msg for msg in output_data if msg.get("messageSent")])
                    messages_failed = len([msg for msg in output_data if msg.get("error")])
                    total_planned = len(output_data) if output_data else 0
                    messages_pending = max(0, total_planned - messages_sent - messages_failed)
                    
                    # Determine current recipient and ETA
                    current_recipient = None
                    next_message_eta = None
                    
                    if phantom_status == "running" and output_data:
                        # Find the current or next recipient
                        for msg in output_data:
                            if not msg.get("messageSent") and not msg.get("error"):
                                current_recipient = msg.get("profileName", msg.get("profileUrl"))
                                # Estimate ETA based on typical delays
                                next_message_eta = datetime.now() + timedelta(seconds=180)
                                break
                    
                    # Determine completion time
                    completion_time = None
                    if phantom_status in ["finished", "completed"]:
                        completion_time = datetime.fromisoformat(
                            container_data.get("endedAt", "").replace("Z", "+00:00")
                        ) if container_data.get("endedAt") else datetime.now()
                    
                    return CampaignStatus(
                        container_id=container_id,
                        status=phantom_status,
                        progress=min(progress, 100.0),
                        messages_sent=messages_sent,
                        messages_failed=messages_failed,
                        messages_pending=messages_pending,
                        current_recipient=current_recipient,
                        next_message_eta=next_message_eta,
                        completion_time=completion_time,
                        error_details=container_data.get("error")
                    )
                    
        except Exception as e:
            logger.error(f"Failed to get campaign status: {e}")
            return CampaignStatus(
                container_id=container_id,
                status="error",
                progress=0.0,
                messages_sent=0,
                messages_failed=0,
                messages_pending=0,
                current_recipient=None,
                next_message_eta=None,
                completion_time=None,
                error_details=str(e)
            )
    
    async def stop_campaign(self, container_id: str) -> Dict[str, Any]:
        """Stop a running LinkedIn messaging campaign"""
        try:
            async with self:
                async with self.session.post(
                    f"{self.BASE_URL}/containers/erase",
                    json={"containerId": container_id}
                ) as response:
                    
                    if response.status == 200:
                        return {"success": True, "message": "Campaign stopped successfully"}
                    else:
                        error_data = await response.json() if response.content_type == 'application/json' else {}
                        return {
                            "success": False,
                            "error": f"Failed to stop campaign: {error_data.get('error', f'HTTP {response.status}')}"
                        }
                        
        except Exception as e:
            logger.error(f"Failed to stop campaign: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_daily_usage(self) -> Dict[str, int]:
        """Get daily LinkedIn message usage statistics"""
        try:
            async with self:
                # Get recent containers to count daily usage
                today = datetime.now().date()
                
                async with self.session.get(f"{self.BASE_URL}/containers") as response:
                    if response.status != 200:
                        return {"messages_sent_today": 0, "quota_remaining": self.RATE_LIMIT_PER_DAY}
                    
                    containers = await response.json()
                    
                    messages_today = 0
                    for container in containers.get("data", []):
                        # Check if container is from today and used LinkedIn messaging
                        if (container.get("phantomId") == self.LINKEDIN_MESSAGE_SENDER_ID and
                            container.get("launchedAt")):
                            
                            launch_date = datetime.fromisoformat(
                                container["launchedAt"].replace("Z", "+00:00")
                            ).date()
                            
                            if launch_date == today:
                                # Count messages from this container
                                output = container.get("output", [])
                                messages_today += len([msg for msg in output if msg.get("messageSent")])
                    
                    return {
                        "messages_sent_today": messages_today,
                        "quota_remaining": max(0, self.RATE_LIMIT_PER_DAY - messages_today)
                    }
                    
        except Exception as e:
            logger.error(f"Failed to get daily usage: {e}")
            return {"messages_sent_today": 0, "quota_remaining": self.RATE_LIMIT_PER_DAY}
    
    async def _test_linkedin_session(self) -> Dict[str, Any]:
        """Test LinkedIn session validity"""
        try:
            # Launch a minimal test phantom to validate session
            test_args = {
                "sessionCookie": self.linkedin_session,
                "profileUrls": ["https://www.linkedin.com/in/test/"],
                "testMode": True,  # Don't actually send messages
                "delayBetweenMessages": 1
            }
            
            launch_data = {
                "id": self.LINKEDIN_MESSAGE_SENDER_ID,
                "argument": test_args
            }
            
            async with self.session.post(
                f"{self.BASE_URL}/phantoms/launch",
                json=launch_data
            ) as response:
                
                if response.status == 200:
                    result = await response.json()
                    # Wait a moment for phantom to start and validate session
                    await asyncio.sleep(5)
                    
                    # Check container status
                    container_id = result.get("containerId")
                    if container_id:
                        status = await self.get_campaign_status(container_id)
                        # Stop the test phantom
                        await self.stop_campaign(container_id)
                        
                        return {
                            "valid": status.status != "error",
                            "quota_used": 0  # Test doesn't count against quota
                        }
                    
                return {"valid": False, "quota_used": 0}
                
        except Exception as e:
            logger.error(f"LinkedIn session test failed: {e}")
            return {"valid": False, "quota_used": 0}


# Factory function for dependency injection
def get_phantombuster_linkedin_client(tenant_id: int) -> PhantomBusterLinkedInClient:
    """
    Factory function to create PhantomBuster LinkedIn client with tenant-specific settings
    """
    try:
        from integrations.sendgrid_client import get_tenant_integration_settings
        
        settings = get_tenant_integration_settings(tenant_id)
        
        api_key = settings.get("phantombuster_api_key")
        linkedin_session = settings.get("linkedin_session_cookie")
        
        if not api_key:
            raise ValueError(f"PhantomBuster API key not configured for tenant {tenant_id}")
        
        if not linkedin_session:
            raise ValueError(f"LinkedIn session cookie not configured for tenant {tenant_id}")
        
        return PhantomBusterLinkedInClient(api_key, linkedin_session)
        
    except Exception as e:
        logger.error(f"Failed to create PhantomBuster LinkedIn client for tenant {tenant_id}: {e}")
        raise