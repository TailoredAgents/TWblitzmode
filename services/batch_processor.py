"""
Batch Processor - Orchestrates batch execution with daily limits and scheduling
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from api.database import get_db
from services.batch_service import batch_service, BatchType
from core.settings import settings

logger = logging.getLogger(__name__)

class BatchProcessor:
    """Manages automatic batch processing with respect for daily limits and scheduling"""
    
    def __init__(self):
        self.is_running = False
        self.current_batches = {}  # Track running batches per type
        self._lock = asyncio.Lock()  # Prevent race conditions
    
    async def process_pending_batches(self, user_id: int = 1) -> Dict[str, Any]:
        """
        Process all pending batches respecting daily limits and concurrency
        
        Returns:
            Summary of processing results
        """
        async with self._lock:
            if self.is_running:
                return {'status': 'already_running', 'message': 'Batch processor already running'}
            
            self.is_running = True
        results = {
            'processed_batches': [],
            'skipped_batches': [],
            'errors': [],
            'summary': {}
        }
        
        try:
            logger.info(f"Starting batch processing for user {user_id}")
            
            # Process each batch type in priority order
            batch_priorities = [
                BatchType.OUTREACH_MESSAGES,  # Highest priority (time-sensitive)
                BatchType.WARM_UP_VISITS,     # Medium priority (preparation)
                BatchType.PROFILE_SCRAPING    # Lowest priority (data collection)
            ]
            
            for batch_type in batch_priorities:
                try:
                    batch_result = await self._process_batch_type(batch_type, user_id)
                    results['processed_batches'].extend(batch_result['processed'])
                    results['skipped_batches'].extend(batch_result['skipped'])
                    results['errors'].extend(batch_result['errors'])
                    
                    # Add delay between batch types to avoid overwhelming LinkedIn
                    await asyncio.sleep(60)  # 1 minute between different batch types
                    
                except Exception as e:
                    logger.error(f"Error processing {batch_type.value} batches: {e}")
                    results['errors'].append({
                        'batch_type': batch_type.value,
                        'error': str(e),
                        'timestamp': datetime.now().isoformat()
                    })
            
            # Generate summary
            results['summary'] = {
                'total_processed': len(results['processed_batches']),
                'total_skipped': len(results['skipped_batches']),
                'total_errors': len(results['errors']),
                'processing_time_minutes': 0,  # Would track actual time
                'daily_quotas': batch_service.get_user_daily_summary(user_id)
            }
            
            logger.info(f"Batch processing completed: {results['summary']}")
            return results
            
        except Exception as e:
            logger.error(f"Fatal error in batch processing: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'processed_batches': results['processed_batches'],
                'summary': results.get('summary', {})
            }
        finally:
            self.is_running = False
    
    async def _process_batch_type(self, batch_type: BatchType, user_id: int) -> Dict[str, List]:
        """Process all pending batches for a specific type"""
        processed = []
        skipped = []
        errors = []
        
        try:
            # Check daily quota first
            quota_check = batch_service.check_daily_quota(user_id, batch_type, 1)
            if not quota_check['can_proceed']:
                logger.info(f"Daily quota exceeded for {batch_type.value}: {quota_check}")
                skipped.append({
                    'batch_type': batch_type.value,
                    'reason': 'daily_quota_exceeded',
                    'quota_info': quota_check
                })
                return {'processed': processed, 'skipped': skipped, 'errors': errors}
            
            # Check concurrency limits
            if self._get_running_batch_count(batch_type) >= batch_service.batch_limits[batch_type].max_concurrent:
                logger.info(f"Concurrency limit reached for {batch_type.value}")
                skipped.append({
                    'batch_type': batch_type.value,
                    'reason': 'concurrency_limit_reached'
                })
                return {'processed': processed, 'skipped': skipped, 'errors': errors}
            
            # Get items ready for batch processing
            ready_items = batch_service.get_batch_ready_items(batch_type, user_id)
            
            if not ready_items:
                logger.info(f"No items ready for {batch_type.value} processing")
                return {'processed': processed, 'skipped': skipped, 'errors': errors}
            
            # Check quota for actual number of items
            item_count = len(ready_items)
            quota_check = batch_service.check_daily_quota(user_id, batch_type, item_count)
            
            if not quota_check['can_proceed']:
                # Trim items to fit within quota
                available_quota = quota_check['remaining']
                if available_quota > 0:
                    ready_items = ready_items[:available_quota]
                    logger.info(f"Trimmed {batch_type.value} batch to {len(ready_items)} items to fit quota")
                else:
                    skipped.append({
                        'batch_type': batch_type.value,
                        'reason': 'no_quota_remaining',
                        'quota_info': quota_check
                    })
                    return {'processed': processed, 'skipped': skipped, 'errors': errors}
            
            # Create and execute batch
            batch_id = batch_service.create_batch(batch_type, ready_items, user_id)
            
            if batch_id:
                # Track running batch
                self.current_batches[batch_type] = batch_id
                
                logger.info(f"Executing batch {batch_id} with {len(ready_items)} {batch_type.value} items")
                
                # Execute batch
                execution_result = batch_service.execute_batch(batch_id)
                
                # Remove from tracking
                self.current_batches.pop(batch_type, None)
                
                if execution_result['success']:
                    processed.append({
                        'batch_id': batch_id,
                        'batch_type': batch_type.value,
                        'items_processed': execution_result['processed'],
                        'container_id': execution_result.get('container_id'),
                        'completed_at': datetime.now().isoformat()
                    })
                else:
                    errors.append({
                        'batch_id': batch_id,
                        'batch_type': batch_type.value,
                        'error': execution_result.get('error', 'Unknown execution error'),
                        'failed_at': datetime.now().isoformat()
                    })
            else:
                errors.append({
                    'batch_type': batch_type.value,
                    'error': 'Failed to create batch',
                    'items_count': len(ready_items)
                })
        
        except Exception as e:
            logger.error(f"Error processing {batch_type.value} batch: {e}")
            errors.append({
                'batch_type': batch_type.value,
                'error': str(e),
                'exception_at': datetime.now().isoformat()
            })
        
        return {'processed': processed, 'skipped': skipped, 'errors': errors}
    
    def _get_running_batch_count(self, batch_type: BatchType) -> int:
        """Get number of currently running batches for this type"""
        # In a real implementation, this would query the database for running batches
        return 1 if batch_type in self.current_batches else 0
    
    async def schedule_batch_processing(self) -> None:
        """
        Run continuous batch processing with intelligent scheduling
        This would typically run as a background task
        """
        logger.info("Starting scheduled batch processing")
        
        while True:
            try:
                # Process batches for default user
                await self.process_pending_batches(user_id=1)
                
                # Wait before next processing cycle
                # Schedule more frequently during business hours
                current_hour = datetime.now().hour
                
                if 9 <= current_hour <= 17:  # Business hours - more frequent
                    sleep_minutes = settings.BATCH_MIN_DELAY_MINUTES
                else:  # Off hours - less frequent
                    sleep_minutes = settings.BATCH_MIN_DELAY_MINUTES * 2
                
                logger.info(f"Batch processing cycle complete. Sleeping for {sleep_minutes} minutes...")
                await asyncio.sleep(sleep_minutes * 60)
                
            except Exception as e:
                logger.error(f"Error in scheduled batch processing: {e}")
                # Wait longer on error to avoid rapid failure loops
                await asyncio.sleep(300)  # 5 minutes
    
    def check_batch_health(self, user_id: int = 1) -> Dict[str, Any]:
        """Check the health of batch processing queues"""
        try:
            health_report = {
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'queue_stats': {},
                'daily_quotas': batch_service.get_user_daily_summary(user_id),
                'issues': []
            }
            
            # Check queue backlogs for each batch type
            for batch_type in BatchType:
                ready_items = batch_service.get_batch_ready_items(batch_type, user_id, limit=100)
                overdue_items = [
                    item for item in ready_items 
                    if 'scheduled_for' in item and 
                    datetime.fromisoformat(item['scheduled_for']) < datetime.now() - timedelta(hours=1)
                ]
                
                health_report['queue_stats'][batch_type.value] = {
                    'ready_items': len(ready_items),
                    'overdue_items': len(overdue_items),
                    'is_running': batch_type in self.current_batches
                }
                
                # Flag issues
                if len(overdue_items) > 10:
                    health_report['issues'].append({
                        'type': 'overdue_backlog',
                        'batch_type': batch_type.value,
                        'overdue_count': len(overdue_items),
                        'severity': 'high' if len(overdue_items) > 50 else 'medium'
                    })
                
                # Check if quota is nearly exhausted
                quota_info = health_report['daily_quotas'].get(batch_type.value, {})
                if quota_info.get('percentage_used', 0) > 90:
                    health_report['issues'].append({
                        'type': 'quota_exhaustion',
                        'batch_type': batch_type.value,
                        'usage_percentage': quota_info['percentage_used'],
                        'severity': 'high'
                    })
            
            # Overall health status
            if health_report['issues']:
                high_severity_issues = [i for i in health_report['issues'] if i['severity'] == 'high']
                health_report['status'] = 'critical' if high_severity_issues else 'warning'
            
            return health_report
            
        except Exception as e:
            logger.error(f"Error checking batch health: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def get_batch_statistics(self, days_back: int = 7, user_id: int = 1) -> Dict[str, Any]:
        """Get batch processing statistics for the last N days"""
        try:
            cutoff_timestamp = datetime.now() - timedelta(days=days_back)
            cutoff_date = cutoff_timestamp.date()

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 
                            batch_type,
                            status,
                            COUNT(*) AS count,
                            AVG(success_count) AS avg_success,
                            SUM(success_count) AS total_success,
                            SUM(error_count) AS total_errors
                        FROM processing_batches 
                        WHERE user_id = ?
                          AND created_at > ?
                        GROUP BY batch_type, status
                        """,
                        (user_id, cutoff_timestamp),
                    )
                    batch_rows = cursor.fetchall()

                    cursor.execute(
                        """
                        SELECT 
                            batch_type,
                            date,
                            items_processed,
                            daily_limit
                        FROM daily_quotas 
                        WHERE user_id = ?
                          AND date >= ?
                        ORDER BY date DESC
                        """,
                        (user_id, cutoff_date),
                    )
                    quota_rows = cursor.fetchall()
            finally:
                conn.close()

            batch_stats: Dict[str, Dict[str, Any]] = {}
            for row in batch_rows:
                batch_type = row["batch_type"] if hasattr(row, "__getitem__") else row[0]
                status = row["status"] if hasattr(row, "__getitem__") else row[1]
                count = row["count"] if hasattr(row, "__getitem__") else row[2]
                avg_success = row["avg_success"] if hasattr(row, "__getitem__") else row[3]
                total_success = row["total_success"] if hasattr(row, "__getitem__") else row[4]
                total_errors = row["total_errors"] if hasattr(row, "__getitem__") else row[5]

                stats = {
                    'count': count,
                    'avg_success': round(avg_success or 0, 2),
                    'total_success': total_success or 0,
                    'total_errors': total_errors or 0
                }
                batch_stats.setdefault(batch_type, {})[status] = stats

            quota_history: Dict[str, List[Dict[str, Any]]] = {}
            for row in quota_rows:
                batch_type = row["batch_type"] if hasattr(row, "__getitem__") else row[0]
                date = row["date"] if hasattr(row, "__getitem__") else row[1]
                items_processed = row["items_processed"] if hasattr(row, "__getitem__") else row[2]
                daily_limit = row["daily_limit"] if hasattr(row, "__getitem__") else row[3]

                utilization_pct = round((items_processed / daily_limit) * 100, 1) if daily_limit else 0.0
                quota_history.setdefault(batch_type, []).append({
                    'date': date,
                    'items_processed': items_processed,
                    'daily_limit': daily_limit,
                    'utilization_pct': utilization_pct
                })

            return {
                'period_days': days_back,
                'batch_statistics': batch_stats,
                'quota_history': quota_history,
                'generated_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting batch statistics: {e}")
            return {
                'error': str(e),
                'generated_at': datetime.now().isoformat()
            }

# Global batch processor instance
batch_processor = BatchProcessor()
