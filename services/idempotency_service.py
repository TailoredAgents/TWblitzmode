"""
Idempotency Service for Job Creation Deduplication
Prevents duplicate job submissions and ensures exactly-once processing
September 2025 - Critical Reliability Enhancement
"""

import os
import json
import hashlib
import logging
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timedelta, date, timezone
from dataclasses import dataclass, asdict
from enum import Enum
import asyncio
import uuid

from api.database import get_db

try:
    import redis  # type: ignore[assignment]
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    redis = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

class IdempotencyStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RUNNING = "running"  # Legacy compatibility
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"

@dataclass
class IdempotencyKey:
    """Idempotency key with metadata"""
    key: str
    tenant_id: str
    user_id: str
    operation_type: str
    resource_id: Optional[str]
    parameters_hash: str
    status: IdempotencyStatus
    job_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: datetime = None
    updated_at: datetime = None
    expires_at: datetime = None
    retry_count: int = 0
    error_message: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc)
        if not self.updated_at:
            self.updated_at = datetime.now(timezone.utc)
        if not self.expires_at:
            self.expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

class IdempotencyService:
    """Enterprise idempotency service with Redis backend and database fallback"""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_client = None
        self._init_redis()

        # Configuration
        self.default_ttl_hours = 24
        self.max_retry_attempts = 3
        self.key_prefix = "idempotency"

    def _init_redis(self):
        """Initialize Redis connection"""
        if redis is None:
            logger.warning("Redis package not available; falling back to database storage for idempotency")
            self._init_database_fallback()
            return
        try:
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Redis connection established for idempotency service")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            # Fallback to database storage
            self._init_database_fallback()

    def _init_database_fallback(self):
        """Initialize database fallback storage"""
        logger.warning("Using database storage for idempotency - Redis recommended for production")

    def _generate_parameters_hash(self, parameters: Dict[str, Any]) -> str:
        """Generate deterministic hash of parameters"""
        # Sort keys for consistent hashing
        sorted_params = json.dumps(parameters, sort_keys=True, default=str)
        return hashlib.sha256(sorted_params.encode()).hexdigest()[:16]

    def _generate_idempotency_key(
        self,
        tenant_id: str,
        user_id: str,
        operation_type: str,
        parameters: Dict[str, Any],
        resource_id: Optional[str] = None
    ) -> str:
        """Generate unique idempotency key"""
        params_hash = self._generate_parameters_hash(parameters)

        # Create composite key
        key_components = [
            self.key_prefix,
            tenant_id,
            user_id,
            operation_type,
            params_hash
        ]

        if resource_id:
            key_components.append(resource_id)

        return ":".join(key_components)

    # Legacy compatibility methods for existing codebase

    def generate_idempotency_key(self, prospect_url: str, job_type: str,
                                include_date: bool = True) -> str:
        """
        Generate idempotency key for a job (legacy compatibility)

        Args:
            prospect_url: LinkedIn profile URL
            job_type: Type of job ('find_introducers', 'warm_up_visits', 'send_outreach')
            include_date: Whether to include today's date (prevents re-running same job today)

        Returns:
            Hash-based idempotency key
        """
        # Use canonical URL normalization to prevent issues with truncated URLs
        try:
            from utils.linkedin_urls import canonical_linkedin_profile_url

            canonical_url = canonical_linkedin_profile_url(prospect_url)
            if canonical_url:
                normalized_url = canonical_url
            else:
                # Fallback to basic normalization if canonicalization fails
                normalized_url = prospect_url.lower().strip()
                if normalized_url.endswith('/'):
                    normalized_url = normalized_url[:-1]
        except ImportError as e:
            logger.warning(f"Could not import canonical_linkedin_profile_url: {e}")
            # Fallback to basic normalization
            normalized_url = prospect_url.lower().strip()
            if normalized_url.endswith('/'):
                normalized_url = normalized_url[:-1]
        except Exception as e:
            logger.warning(f"URL canonicalization failed, using basic normalization: {e}")
            # Fallback to basic normalization
            normalized_url = prospect_url.lower().strip()
            if normalized_url.endswith('/'):
                normalized_url = normalized_url[:-1]

        # Build key components
        key_parts = [normalized_url, job_type]

        if include_date:
            key_parts.append(date.today().isoformat())

        # Create hash
        key_string = '|'.join(key_parts)
        return hashlib.sha256(key_string.encode()).hexdigest()[:16]  # 16-char hash

    def check_job_idempotency(self, prospect_url: str, job_type: str,
                             prospect_id: int = None, tenant_id: int = None) -> Dict[str, Any]:
        """
        Check if job already exists and return cached result if available (legacy compatibility)

        Returns:
            Dict with 'exists', 'status', 'result_data', and 'can_proceed' flags
        """
        try:
            idempotency_key = self.generate_idempotency_key(prospect_url, job_type)

            # Check Redis first
            if self.redis_client:
                cached_data = self.redis_client.get(f"job:{idempotency_key}")
                if cached_data:
                    data = json.loads(cached_data)
                    return self._format_legacy_response(data, idempotency_key)

            # Fallback to database
            return self._check_database_idempotency(idempotency_key, tenant_id, prospect_id)

        except Exception as e:
            logger.error(f"Error checking job idempotency: {e}")
            # On error, allow job to proceed
            return {
                'exists': False,
                'can_proceed': True,
                'idempotency_key': self.generate_idempotency_key(prospect_url, job_type),
                'error': str(e)
            }

    def _check_database_idempotency(self, idempotency_key: str, tenant_id: int, prospect_id: int) -> Dict[str, Any]:
        """Check database for existing job"""
        conn = None
        row: Optional[Dict[str, Any]] = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                cursor.execute(
                    '''
                    SELECT id, prospect_id, status, result_data, created_at, completed_at
                    FROM job_idempotency
                    WHERE tenant_id = ? AND idempotency_key = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    ''',
                    (tenant_id, idempotency_key),
                )
                db_row = cursor.fetchone()
                if db_row:
                    if hasattr(db_row, "_mapping"):
                        row = dict(db_row._mapping)
                    else:
                        columns = [desc[0] for desc in cursor.description] if cursor.description else []
                        row = dict(zip(columns, db_row)) if columns else {
                            "id": db_row[0],
                            "prospect_id": db_row[1],
                            "status": db_row[2],
                            "result_data": db_row[3] if len(db_row) > 3 else None,
                            "created_at": db_row[4] if len(db_row) > 4 else None,
                            "completed_at": db_row[5] if len(db_row) > 5 else None,
                        }
        except Exception as e:
            logger.error(f"Database idempotency check failed: {e}")
            return {
                'exists': False,
                'can_proceed': True,
                'idempotency_key': idempotency_key,
                'error': str(e)
            }
        finally:
            if conn:
                conn.close()

        if not row:
            return {
                'exists': False,
                'can_proceed': True,
                'idempotency_key': idempotency_key,
                'status': None,
                'result_data': None
            }

        existing_prospect_id = row.get("prospect_id")
        status = row.get("status")
        result_data = row.get("result_data")
        completed_at = row.get("completed_at")

        parsed_result = None
        if result_data:
            try:
                parsed_result = json.loads(result_data)
            except Exception as parse_error:
                logger.warning(f"Failed to parse cached result data: {parse_error}")

        if status == 'completed':
            return {
                'exists': True,
                'can_proceed': False,
                'idempotency_key': idempotency_key,
                'status': status,
                'result_data': parsed_result,
                'cached': True,
                'completed_at': completed_at,
                'prospect_id': existing_prospect_id
            }
        if status in ['running', 'in_progress']:
            return {
                'exists': True,
                'can_proceed': False,
                'idempotency_key': idempotency_key,
                'status': status,
                'result_data': None,
                'message': 'Job already in progress'
            }
        if status in ['failed', 'pending']:
            return {
                'exists': True,
                'can_proceed': True,
                'idempotency_key': idempotency_key,
                'status': status,
                'result_data': parsed_result,
                'retry': True
            }

        return {
            'exists': True,
            'can_proceed': False,
            'idempotency_key': idempotency_key,
            'status': status,
            'result_data': parsed_result
        }

    def _format_legacy_response(self, data: Dict[str, Any], idempotency_key: str) -> Dict[str, Any]:
        """Format response for legacy compatibility"""
        status = data.get('status', 'pending')

        if status == 'completed':
            return {
                'exists': True,
                'can_proceed': False,
                'idempotency_key': idempotency_key,
                'status': status,
                'result_data': data.get('result'),
                'cached': True,
                'completed_at': data.get('completed_at'),
                'prospect_id': data.get('prospect_id')
            }
        elif status in ['running', 'in_progress']:
            return {
                'exists': True,
                'can_proceed': False,
                'idempotency_key': idempotency_key,
                'status': status,
                'result_data': None,
                'message': 'Job already in progress'
            }
        else:
            return {
                'exists': True,
                'can_proceed': True,
                'idempotency_key': idempotency_key,
                'status': status,
                'result_data': data.get('result'),
                'retry': status in ['failed', 'pending']
            }

    def create_job_record(self, idempotency_key: str, prospect_id: int, job_type: str, tenant_id: int = None) -> int:
        """
        Create initial job record in pending state (legacy compatibility)

        Returns:
            Job record ID
        """
        try:
            # Store in Redis if available
            if self.redis_client:
                job_data = {
                    'status': 'pending',
                    'prospect_id': prospect_id,
                    'job_type': job_type,
                    'tenant_id': tenant_id,
                    'created_at': datetime.now(timezone.utc).isoformat()
                }
                self.redis_client.setex(
                    f"job:{idempotency_key}",
                    self.default_ttl_hours * 3600,
                    json.dumps(job_data)
                )

            # Also store in database for persistence
            return self._create_database_job_record(idempotency_key, prospect_id, job_type, tenant_id)

        except Exception as e:
            logger.error(f"Error creating job record: {e}")
            return 0

    def _create_database_job_record(self, idempotency_key: str, prospect_id: int, job_type: str, tenant_id: int) -> int:
        """Create job record in database"""
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                if tenant_id is None and prospect_id:
                    cursor.execute("SELECT tenant_id FROM prospects WHERE id = ?", (prospect_id,))
                    row = cursor.fetchone()
                    if row:
                        tenant_id = row["tenant_id"] if hasattr(row, "__getitem__") else row[0]

                if tenant_id is None:
                    tenant_id = 1

                now_iso = datetime.now(timezone.utc).isoformat()

                try:
                    cursor.execute(
                        '''
                        INSERT INTO job_idempotency (
                            tenant_id, idempotency_key, prospect_id, job_type, status, created_at
                        ) VALUES (?, ?, ?, ?, 'pending', ?)
                        ON CONFLICT (tenant_id, idempotency_key) DO UPDATE SET
                            status = 'pending',
                            created_at = EXCLUDED.created_at
                        ''',
                        (tenant_id, idempotency_key, prospect_id, job_type, now_iso),
                    )
                except Exception as constraint_error:
                    if "no unique or exclusion constraint" in str(constraint_error):
                        logger.warning("Database constraint missing - attempting to create it")
                        cursor.execute(
                            '''
                            CREATE UNIQUE INDEX IF NOT EXISTS job_idempotency_tenant_id_idempotency_key_key
                            ON job_idempotency (tenant_id, idempotency_key)
                            '''
                        )
                        conn.commit()
                        cursor.execute(
                            '''
                            INSERT INTO job_idempotency (
                                tenant_id, idempotency_key, prospect_id, job_type, status, created_at
                            ) VALUES (?, ?, ?, ?, 'pending', ?)
                            ON CONFLICT (tenant_id, idempotency_key) DO UPDATE SET
                                status = 'pending',
                                created_at = EXCLUDED.created_at
                            ''',
                            (tenant_id, idempotency_key, prospect_id, job_type, now_iso),
                        )
                    else:
                        raise

                job_id = cursor.lastrowid

            if conn:
                conn.commit()

            logger.info(f"Created job record {job_id} with key {idempotency_key}")
            return job_id

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error creating database job record: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    def update_job_status(self, idempotency_key: str, status: str,
                         result_data: Dict = None) -> bool:
        """
        Update job status and optionally store result data (legacy compatibility)

        Args:
            idempotency_key: Job idempotency key
            status: New status ('running', 'completed', 'failed')
            result_data: Result data to cache (for completed jobs)

        Returns:
            True if update successful
        """
        try:
            # Update Redis if available
            if self.redis_client:
                cached_data = self.redis_client.get(f"job:{idempotency_key}")
                if cached_data:
                    data = json.loads(cached_data)
                    data['status'] = status
                    data['updated_at'] = datetime.now(timezone.utc).isoformat()

                    if result_data:
                        data['result'] = result_data

                    if status in ['completed', 'failed']:
                        data['completed_at'] = datetime.now(timezone.utc).isoformat()

                    self.redis_client.setex(
                        f"job:{idempotency_key}",
                        self.default_ttl_hours * 3600,
                        json.dumps(data)
                    )

            # Update database
            return self._update_database_job_status(idempotency_key, status, result_data)

        except Exception as e:
            logger.error(f"Error updating job status: {e}")
            return False

    def _update_database_job_status(self, idempotency_key: str, status: str, result_data: Dict = None) -> bool:
        """Update job status in database"""
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                result_json = json.dumps(result_data, default=str) if result_data else None
                completed_at = datetime.now(timezone.utc).isoformat() if status in ['completed', 'failed'] else None

                cursor.execute(
                    '''
                    UPDATE job_idempotency
                    SET status = ?, result_data = ?, completed_at = ?, updated_at = ?
                    WHERE idempotency_key = ?
                    ''',
                    (
                        status,
                        result_json,
                        completed_at,
                        datetime.now(timezone.utc).isoformat(),
                        idempotency_key,
                    ),
                )
                rows_updated = cursor.rowcount

            if conn:
                conn.commit()

            if rows_updated > 0:
                logger.info(f"Updated job {idempotency_key} status to {status}")
                return True

            logger.warning(f"No job found with key {idempotency_key}")
            return False

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error updating database job status: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def get_cached_result(self, prospect_url: str, job_type: str,
                         max_age_hours: int = 24, tenant_id: int = None) -> Optional[Dict]:
        """
        Get cached result for a job if it's fresh enough (legacy compatibility)

        Args:
            prospect_url: LinkedIn profile URL
            job_type: Type of job
            max_age_hours: Maximum age of cached result in hours

        Returns:
            Cached result data or None
        """
        try:
            # Default to tenant 1 if not provided
            if tenant_id is None:
                tenant_id = 1

            idempotency_key = self.generate_idempotency_key(prospect_url, job_type)

            # Check Redis first
            if self.redis_client:
                cached_data = self.redis_client.get(f"job:{idempotency_key}")
                if cached_data:
                    data = json.loads(cached_data)
                    if data.get('status') == 'completed' and data.get('result'):
                        # Check age
                        completed_at = datetime.fromisoformat(data.get('completed_at', ''))
                        age_hours = (datetime.now(timezone.utc) - completed_at).total_seconds() / 3600

                        if age_hours <= max_age_hours:
                            result = data['result']
                            result['cached'] = True
                            result['cached_at'] = data.get('completed_at')
                            return result

            # Fallback to database
            return self._get_database_cached_result(idempotency_key, max_age_hours, tenant_id)

        except Exception as e:
            logger.error(f"Error getting cached result: {e}")
            return None

    def _get_database_cached_result(self, idempotency_key: str, max_age_hours: int, tenant_id: int) -> Optional[Dict]:
        """Get cached result from database"""
        conn = None
        row = None
        description = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                interval_value = f"{max_age_hours} hours"
                cursor.execute(
                    '''
                    SELECT result_data, completed_at
                    FROM job_idempotency
                    WHERE tenant_id = ?
                      AND idempotency_key = ?
                      AND status = 'completed'
                      AND completed_at > NOW() - ?::interval
                    ORDER BY completed_at DESC
                    LIMIT 1
                    ''',
                    (tenant_id, idempotency_key, interval_value),
                )
                row = cursor.fetchone()
                description = cursor.description
        except Exception as e:
            logger.error(f"Error getting database cached result: {e}")
            return None
        finally:
            if conn:
                conn.close()

        if not row:
            return None

        if hasattr(row, "_mapping"):
            record = dict(row._mapping)
        else:
            columns = [desc[0] for desc in description] if description else []
            record = dict(zip(columns, row)) if columns else {
                "result_data": row[0],
                "completed_at": row[1] if len(row) > 1 else None,
            }

        result_data = record.get("result_data")
        completed_at = record.get("completed_at")
        if result_data:
            try:
                parsed_result = json.loads(result_data)
                parsed_result['cached'] = True
                parsed_result['cached_at'] = completed_at
                return parsed_result
            except Exception as parse_error:
                logger.warning(f"Failed to parse cached result: {parse_error}")

        return None

    def cleanup_old_jobs(self, days_old: int = 7) -> int:
        """
        Clean up job records older than specified days (legacy compatibility)

        Returns:
            Number of jobs cleaned up
        """
        try:
            cleaned_count = 0

            # Clean up Redis
            if self.redis_client:
                # Redis keys expire automatically, but we can scan for old ones
                logger.debug("Redis keys automatically expire")

            # Clean up database
            cleaned_count += self._cleanup_database_jobs(days_old)

            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} old job records")

            return cleaned_count

        except Exception as e:
            logger.error(f"Error cleaning up old jobs: {e}")
            return 0

    def _cleanup_database_jobs(self, days_old: int) -> int:
        """Clean up old jobs from database"""
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                interval_value = f"{days_old} days"
                cursor.execute(
                    '''
                    DELETE FROM job_idempotency
                    WHERE created_at::timestamp < NOW() - ?::interval
                    ''',
                    (interval_value,),
                )
                deleted_count = cursor.rowcount

            if conn:
                conn.commit()

            return deleted_count

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error cleaning up database jobs: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    async def health_check(self) -> Dict[str, Any]:
        """Health check for idempotency service"""
        try:
            health_status = {
                "status": "healthy",
                "backend": "redis" if self.redis_client else "database",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            if self.redis_client:
                # Test Redis connection
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self.redis_client.ping()
                    )
                    health_status["redis_connected"] = True
                except Exception as e:
                    health_status["redis_connected"] = False
                    health_status["redis_error"] = str(e)
                    health_status["status"] = "degraded"
            else:
                health_status["redis_connected"] = False

            # Test basic operations
            test_key = self.generate_idempotency_key("test://url", "health_check")
            test_result = self.check_job_idempotency("test://url", "health_check", tenant_id=1)

            if test_result.get('can_proceed'):
                health_status["basic_operations"] = "passed"
            else:
                health_status["basic_operations"] = "failed"
                health_status["status"] = "degraded"

            return health_status

        except Exception as e:
            logger.error(f"Idempotency service health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

# Global idempotency service instance
idempotency_service = IdempotencyService()
