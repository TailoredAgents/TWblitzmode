"""
Webhook Retry Scheduler - Background task to process failed webhooks
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

logger = logging.getLogger(__name__)

class WebhookScheduler:
    """Background scheduler for webhook retry processing"""
    
    def __init__(self):
        self.is_running = False
        self.task = None
        self.retry_interval_minutes = 5  # Check every 5 minutes
        
    async def start(self):
        """Start the webhook retry scheduler"""
        if self.is_running:
            logger.warning("Webhook scheduler already running")
            return
        
        self.is_running = True
        self.task = asyncio.create_task(self._scheduler_loop())
        logger.info("Webhook scheduler started")
    
    async def stop(self):
        """Stop the webhook retry scheduler"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        logger.info("Webhook scheduler stopped")
    
    async def _scheduler_loop(self):
        """Main scheduler loop"""
        while self.is_running:
            try:
                await self._process_webhook_retries()
                await asyncio.sleep(self.retry_interval_minutes * 60)  # Convert to seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    async def _process_webhook_retries(self):
        """Process webhooks scheduled for retry"""
        try:
            from webhooks.webhook_handler import webhook_handler
            
            result = await webhook_handler.process_webhook_retries()
            
            if result.get('summary', {}).get('total_processed', 0) > 0:
                logger.info(f"Processed {result['summary']['total_processed']} webhook retries")
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing webhook retries: {e}")
            return {"status": "error", "error": str(e)}
    
    async def get_scheduler_status(self) -> Dict[str, Any]:
        """Get current scheduler status"""
        return {
            "is_running": self.is_running,
            "retry_interval_minutes": self.retry_interval_minutes,
            "next_check_at": (datetime.now() + timedelta(minutes=self.retry_interval_minutes)).isoformat(),
            "status_checked_at": datetime.now().isoformat()
        }

# Global scheduler instance
webhook_scheduler = WebhookScheduler()