"""
Enhanced Idempotency Service with Tenant Validation
Critical security fix for multi-tenant job isolation
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from api.database import get_db

logger = logging.getLogger(__name__)


class IdempotencyService:
    """Secure idempotency service with tenant isolation"""

    def __init__(self):
        self.database_url = None  # preserved for compatibility with legacy consumers

    def generate_key(self, tenant_id: int, operation: str, params: Dict[str, Any]) -> str:
        """Generate idempotency key with tenant isolation"""
        # Include tenant_id in key to prevent cross-tenant conflicts
        key_data = {
            "tenant_id": tenant_id,
            "operation": operation,
            "params": sorted(params.items())
        }
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_string.encode()).hexdigest()

    async def check_or_create_job(self,
                                  tenant_id: int,
                                  idempotency_key: str,
                                  job_data: Dict[str, Any]) -> Optional[str]:
        """Check for existing job or create new one with tenant validation"""
        with get_db() as conn:
            # Check existing job with tenant filter
            existing = conn.execute(
                "SELECT id, status FROM job_idempotency WHERE tenant_id = %s AND idempotency_key = %s",
                (tenant_id, idempotency_key)
            ).fetchone()

            if existing:
                logger.info(f"Idempotent job found: {existing['id']}")
                return existing["id"]

            # Create new job with tenant isolation
            job_id = conn.execute("""
                INSERT INTO job_runs (tenant_id, user_id, type, status, payload, external_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                tenant_id,
                job_data.get("user_id"),
                job_data.get("type"),
                "queued",
                json.dumps(job_data.get("payload", {})),
                idempotency_key
            )).lastrowid

            # Create idempotency record
            conn.execute("""
                INSERT INTO job_idempotency (tenant_id, idempotency_key, job_id, status)
                VALUES (%s, %s, %s, 'created')
            """, (tenant_id, idempotency_key, job_id))

            conn.commit()
            logger.info(f"Created new idempotent job: {job_id}")
            return str(job_id)

# Global service instance
idempotency_service = IdempotencyService()
