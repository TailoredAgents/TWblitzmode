"""
Profile Warm-up Service - LinkedIn Profile Visitor for improved message delivery rates
"""

import logging
import csv
import io
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

from api.database import get_db
from core.settings import settings

logger = logging.getLogger(__name__)

class WarmupService:
    """Handle LinkedIn profile warm-up visits before sending introduction messages"""
    
    def queue_profile_warmup(self, prospect_id: int, linkedin_urls: List[str], 
                           delay_hours: int = None, tenant_id: int = None) -> List[Dict]:
        """
        Queue profile visits for warm-up before messaging
        
        Args:
            prospect_id: Prospect ID these profiles are for
            linkedin_urls: List of LinkedIn profile URLs to visit
            delay_hours: Hours to wait before visiting (default from settings)
            tenant_id: Tenant ID for multi-tenant support
            
        Returns:
            List of queued warm-up items
        """
        if delay_hours is None:
            delay_hours = settings.WARMUP_DELAY_HOURS
        
        scheduled_for = (datetime.now() + timedelta(hours=delay_hours)).isoformat()
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                # Get tenant_id from prospect if not provided
                if tenant_id is None and prospect_id:
                    cursor.execute("SELECT tenant_id FROM prospects WHERE id = ?", (prospect_id,))
                    row = cursor.fetchone()
                    if row:
                        tenant_id = row["tenant_id"] if hasattr(row, "__getitem__") else row[0]
                
                # Require tenant_id - don't default to avoid cross-tenant security issues
                if tenant_id is None:
                    logger.error("tenant_id is required for warmup queue - cannot default for security")
                    raise ValueError("tenant_id is required and cannot be determined from prospect_id")
                
                queued_items: List[Dict] = []
                
                for url in linkedin_urls[:settings.WARMUP_VISITOR_TOP_N]:  # Limit to top N
                    cursor.execute(
                        '''
                        SELECT id, status FROM profile_warmup_queue 
                        WHERE linkedin_url = ? AND prospect_id = ? AND tenant_id = ?
                        ORDER BY created_at DESC LIMIT 1
                        ''',
                        (url, prospect_id, tenant_id),
                    )
                    
                    existing = cursor.fetchone()
                    if existing:
                        existing_status = existing["status"] if hasattr(existing, "__getitem__") else existing[1]
                        if existing_status in ['pending', 'visiting', 'completed']:
                            logger.info(f"Profile {url} already queued for warmup, skipping")
                            continue
                    
                    cursor.execute(
                        '''
                        INSERT INTO profile_warmup_queue (
                            tenant_id, prospect_id, linkedin_url, status, scheduled_for, created_at
                        ) VALUES (?, ?, ?, 'pending', ?, ?)
                        ''',
                        (tenant_id, prospect_id, url, scheduled_for, datetime.now().isoformat()),
                    )
                    
                    warmup_id = cursor.lastrowid
                    queued_items.append({
                        'id': warmup_id,
                        'linkedin_url': url,
                        'status': 'pending',
                        'scheduled_for': scheduled_for,
                        'delay_hours': delay_hours
                    })
                    
                    logger.info(f"Queued profile warmup for {url} (ID: {warmup_id})")
            
            if conn:
                conn.commit()
            return queued_items
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error queuing profile warmup: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def execute_scheduled_warmups(self) -> Dict[str, int]:
        """
        Execute profile warm-ups that are scheduled for now or past due
        
        Returns:
            Dict with execution statistics
        """
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                cursor.execute(
                    '''
                    SELECT id, linkedin_url, prospect_id
                    FROM profile_warmup_queue
                    WHERE status = 'pending' 
                    AND scheduled_for <= NOW()
                    ORDER BY scheduled_for ASC
                    LIMIT 20
                    '''
                )
                ready_warmups = cursor.fetchall()

                if not ready_warmups:
                    return {'executed': 0, 'message': 'No warmups ready'}

                warmup_batches: Dict[int, List[Dict[str, Any]]] = {}
                for row in ready_warmups:
                    warmup_id = row["id"] if hasattr(row, "__getitem__") else row[0]
                    linkedin_url = row["linkedin_url"] if hasattr(row, "__getitem__") else row[1]
                    prospect_id = row["prospect_id"] if hasattr(row, "__getitem__") else row[2]
                    warmup_batches.setdefault(prospect_id, []).append({
                        'id': warmup_id,
                        'linkedin_url': linkedin_url
                    })

                executed_count = 0
                errors: List[str] = []

                for prospect_id, warmups in warmup_batches.items():
                    try:
                        result = self._execute_profile_visitor_batch(warmups)
                        if result.get('success'):
                            warmup_ids = [w['id'] for w in warmups]
                            placeholders = ','.join('?' * len(warmup_ids))
                            cursor.execute(
                                f'''
                                UPDATE profile_warmup_queue 
                                SET status = 'visiting', container_id = ?, visited_at = ?
                                WHERE id IN ({placeholders})
                                ''',
                                [result.get('container_id'), datetime.now().isoformat(), *warmup_ids],
                            )

                            executed_count += len(warmups)
                            logger.info(f"Launched profile visitor for {len(warmups)} profiles")
                        else:
                            errors.append(result.get('error', 'Unknown error'))
                    except Exception as batch_error:
                        logger.error(f"Error executing warmup batch for prospect {prospect_id}: {batch_error}")
                        errors.append(str(batch_error))

            if conn:
                conn.commit()
            return {
                'executed': executed_count,
                'errors': errors,
                'batches': len(warmup_batches)
            }
            
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error executing scheduled warmups: {e}")
            return {'executed': 0, 'error': str(e)}
        finally:
            if conn:
                conn.close()
    
    def _execute_profile_visitor_batch(self, warmups: List[Dict]) -> Dict:
        """
        Execute PhantomBuster Profile Visitor for a batch of profiles
        
        Args:
            warmups: List of warmup items with linkedin_url
            
        Returns:
            Dict with success status and container_id
        """
        try:
            from integrations.phantombuster_client import phantombuster_client
            
            # Build CSV payload for PhantomBuster
            csv_content = self._build_profile_visitor_csv(warmups)
            
            # Launch Profile Visitor phantom
            payload = {
                "id": settings.PB_PROFILE_VISITOR_ID,
                "argument": {
                    "spreadsheetUrl": csv_content,
                    "columnName": "profileUrl",
                    "numberOfProfiles": len(warmups),
                    "visitDuration": 15,        # Seconds to spend on each profile
                    "randomizeOrder": True,     # Randomize visit order
                    "randomizeDelay": True,     # Random delays between visits
                    "delayBetweenVisits": 30    # Base delay between visits (seconds)
                }
            }
            
            import requests
            response = requests.post(
                "https://api.phantombuster.com/api/v2/containers/launch",
                headers={"X-Phantombuster-Key-1": phantombuster_client.api_key},
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            
            result = response.json()
            container_id = result.get("containerId")
            
            if container_id:
                logger.info(f"Profile Visitor launched: {container_id}")
                return {"success": True, "containerId": container_id}
            else:
                error_msg = result.get("error", "Unknown error launching Profile Visitor")
                logger.error(f"Failed to launch Profile Visitor: {error_msg}")
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            logger.error(f"Error launching Profile Visitor: {e}")
            return {"success": False, "error": str(e)}
    
    def _build_profile_visitor_csv(self, warmups: List[Dict]) -> str:
        """Build CSV content for PhantomBuster Profile Visitor"""
        try:
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['profileUrl'])
            
            # Write profile URLs
            for warmup in warmups:
                writer.writerow([warmup['linkedin_url']])
            
            csv_content = output.getvalue()
            output.close()
            
            return csv_content
            
        except Exception as e:
            logger.error(f"Error building Profile Visitor CSV: {e}")
            return ""
    
    def update_warmup_status(self, container_id: str, status: str, error: str = None):
        """
        Update warm-up status based on PhantomBuster webhook/results
        
        Args:
            container_id: PhantomBuster container ID
            status: New status ('completed', 'failed')
            error: Error message if failed
        """
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                update_data = [status, datetime.now().isoformat()]
                query = '''
                    UPDATE profile_warmup_queue 
                    SET status = ?, visited_at = ?
                '''

                if error:
                    query += ', error = ?'
                    update_data.append(error)

                query += ' WHERE container_id = ?'
                update_data.append(container_id)

                cursor.execute(query, update_data)
                updated_count = cursor.rowcount

            if conn:
                conn.commit()

            if updated_count > 0:
                logger.info(f"Updated {updated_count} warmup items to status: {status}")

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error updating warmup status: {e}")
        finally:
            if conn:
                conn.close()
    
    def get_warmup_status(self, prospect_id: int) -> Dict:
        """Get warm-up status for a prospect"""
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                cursor.execute(
                    '''
                    SELECT status, COUNT(*) as count
                    FROM profile_warmup_queue
                    WHERE prospect_id = ?
                    GROUP BY status
                    ''',
                    (prospect_id,),
                )
                status_rows = cursor.fetchall()

                cursor.execute(
                    '''
                    SELECT linkedin_url, status, scheduled_for, visited_at
                    FROM profile_warmup_queue
                    WHERE prospect_id = ?
                    ORDER BY created_at DESC
                    LIMIT 10
                    ''',
                    (prospect_id,),
                )
                recent_rows = cursor.fetchall()

            status_counts = {}
            for row in status_rows:
                key = row["status"] if hasattr(row, "__getitem__") else row[0]
                value = row["count"] if hasattr(row, "__getitem__") else row[1]
                status_counts[key] = value

            recent_warmups = []
            for row in recent_rows:
                linkedin_url = row["linkedin_url"] if hasattr(row, "__getitem__") else row[0]
                status = row["status"] if hasattr(row, "__getitem__") else row[1]
                scheduled_for = row["scheduled_for"] if hasattr(row, "__getitem__") else row[2]
                visited_at = row["visited_at"] if hasattr(row, "__getitem__") else row[3]
                recent_warmups.append({
                    'linkedin_url': linkedin_url,
                    'status': status,
                    'scheduled_for': scheduled_for,
                    'visited_at': visited_at
                })

            return {
                'status_counts': status_counts,
                'recent_warmups': recent_warmups,
                'total_queued': sum(status_counts.values())
            }

        except Exception as e:
            logger.error(f"Error getting warmup status: {e}")
            return {'status_counts': {}, 'recent_warmups': []}
        finally:
            if conn:
                conn.close()
    
    def is_warmup_completed(self, linkedin_url: str, prospect_id: int) -> bool:
        """Check if warm-up is completed for a specific profile"""
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                cursor.execute(
                    '''
                    SELECT 1 FROM profile_warmup_queue
                    WHERE linkedin_url = ?
                      AND prospect_id = ?
                      AND status = 'completed'
                      AND visited_at > NOW() - INTERVAL '7 days'
                    LIMIT 1
                    ''',
                    (linkedin_url, prospect_id),
                )
                result = cursor.fetchone()

            return result is not None

        except Exception as e:
            logger.error(f"Error checking warmup completion: {e}")
            return False
        finally:
            if conn:
                conn.close()

# Global service instance  
warmup_service = WarmupService()
