"""
Queue Worker Service for Production Deployment
Background service for processing Redis message queues
"""
import asyncio
import logging
import signal
import sys
from typing import Optional
import os
from datetime import datetime, timezone

from .redis_queue import message_queue
from .workflow_handlers import workflow_handlers
from services.centralized_logging_service import LogCategory, LogLevel, log_structured

_DEFAULT_LOG_FILE = "/tmp/vouchlink_queue_worker.log"
_log_file = os.getenv("QUEUE_WORKER_LOG_FILE", _DEFAULT_LOG_FILE)
_log_dir = os.path.dirname(_log_file) or "."
os.makedirs(_log_dir, exist_ok=True)

logger = logging.getLogger(__name__)
_file_handler = logging.FileHandler(_log_file)
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(_file_handler)


def _worker_log(level: LogLevel, message: str, **extra) -> None:
    log_structured(
        level,
        message,
        category=LogCategory.SYSTEM,
        service="queue_worker",
        **extra,
    )

class QueueWorkerService:
    """
    Production queue worker service
    Handles graceful shutdown, monitoring, and error recovery
    """

    def __init__(self):
        self.running = False
        self.worker_task: Optional[asyncio.Task] = None
        self.shutdown_event = asyncio.Event()

    async def start(self):
        """Start the queue worker service"""
        logger.info("Starting VouchLink AI Queue Worker Service")
        _worker_log(LogLevel.INFO, "Queue worker starting", running=self.running)

        try:
            # Initialize message queue connection
            await message_queue.connect()
            logger.info("Connected to Redis message queue")
            _worker_log(LogLevel.INFO, "Connected to Redis", redis_url=getattr(message_queue, "redis_url", "default"))

            # Register all workflow handlers
            await workflow_handlers.register_all_handlers()
            logger.info("Registered workflow handlers")
            _worker_log(LogLevel.INFO, "Workflow handlers registered")

            # Start the consumer
            self.running = True
            self.worker_task = asyncio.create_task(self._run_worker())

            # Setup signal handlers for graceful shutdown
            self._setup_signal_handlers()

            # Wait for shutdown signal
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"Failed to start worker service: {e}")
            _worker_log(LogLevel.ERROR, "Queue worker failed to start", exc_info=e)
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Stop the queue worker service gracefully"""
        logger.info("Stopping queue worker service...")
        _worker_log(LogLevel.INFO, "Stopping queue worker")

        self.running = False

        if self.worker_task and not self.worker_task.done():
            # Stop the consumer
            await message_queue.stop_consumer()

            # Wait for current tasks to complete (max 30 seconds)
            try:
                await asyncio.wait_for(self.worker_task, timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Worker task did not complete within timeout, forcing shutdown")
                self.worker_task.cancel()
                _worker_log(LogLevel.WARNING, "Worker task cancellation forced due to timeout")

        # Disconnect from Redis
        await message_queue.disconnect()
        logger.info("Queue worker service stopped")
        _worker_log(LogLevel.INFO, "Queue worker stopped")

    async def _run_worker(self):
        """Main worker loop"""
        try:
            _worker_log(LogLevel.INFO, "Queue worker loop starting")
            # Start consuming messages with optimized settings
            await message_queue.start_consumer(
                batch_size=20,  # Process up to 20 messages per batch
                timeout_ms=5000  # 5 second timeout for blocking reads
            )
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            _worker_log(LogLevel.ERROR, "Worker loop error", exc_info=e)
        finally:
            logger.info("Worker loop terminated")
            _worker_log(LogLevel.INFO, "Queue worker loop terminated")

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown")
            asyncio.create_task(self._shutdown())
            _worker_log(LogLevel.WARNING, "Signal received", signal=signum)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    async def _shutdown(self):
        """Trigger shutdown event"""
        self.shutdown_event.set()
        _worker_log(LogLevel.INFO, "Shutdown event set")

    async def get_health_status(self) -> dict:
        """Get worker health status for monitoring"""
        try:
            queue_stats = await message_queue.get_queue_stats()
            return {
                "status": "healthy" if self.running else "stopped",
                "worker_running": self.running,
                "redis_connected": message_queue.redis is not None,
                "queue_stats": queue_stats,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            _worker_log(LogLevel.ERROR, "Queue worker health check failed", exc_info=e)
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

# Global worker service instance
worker_service = QueueWorkerService()

async def main():
    """Main entry point for running the worker service"""
    try:
        await worker_service.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Worker service error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Run the worker service
    asyncio.run(main())
