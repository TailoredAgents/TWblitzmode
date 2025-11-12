"""
Batch Service - PostgreSQL-first batching and quota orchestration.
All persistence strictly targets the shared Postgres utilities to maintain
Zero-Mock parity across environments.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

from psycopg2.extras import RealDictCursor

from core.settings import settings
from scripts.utils.postgres import (
    DEFAULT_TEST_DSN,
    postgres_connection,
    resolve_required_dsn,
)

logger = logging.getLogger(__name__)


class BatchType(Enum):
    WARM_UP_VISITS = "warm_up_visits"
    OUTREACH_MESSAGES = "outreach_messages"
    PROFILE_SCRAPING = "profile_scraping"


@dataclass
class BatchLimits:
    daily_limit: int
    batch_size: int
    min_delay_minutes: int
    max_concurrent: int


class BatchService:
    """Manage batching, rate limiting, and daily quotas with PostgreSQL storage."""

    def __init__(self, *, database_url: Optional[str] = None):
        self.batch_limits: Dict[BatchType, BatchLimits] = {
            BatchType.WARM_UP_VISITS: BatchLimits(
                daily_limit=settings.WARMUP_DAILY_LIMIT,
                batch_size=10,
                min_delay_minutes=15,
                max_concurrent=2,
            ),
            BatchType.OUTREACH_MESSAGES: BatchLimits(
                daily_limit=settings.OUTREACH_DAILY_LIMIT,
                batch_size=5,
                min_delay_minutes=30,
                max_concurrent=1,
            ),
            BatchType.PROFILE_SCRAPING: BatchLimits(
                daily_limit=100,
                batch_size=15,
                min_delay_minutes=10,
                max_concurrent=3,
            ),
        }
        self._database_url = database_url

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _resolve_dsn(self) -> str:
        if not self._database_url:
            self._database_url = resolve_required_dsn(
                "DATABASE_URL",
                "TEST_DATABASE_URL",
                default=DEFAULT_TEST_DSN,
            )
        return self._database_url

    @contextmanager
    def _connection(self):
        dsn = self._resolve_dsn()
        with postgres_connection(dsn, cursor_factory=RealDictCursor) as conn:
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    # ------------------------------------------------------------------
    # Quota management
    # ------------------------------------------------------------------
    def check_daily_quota(
        self,
        user_id: int,
        batch_type: BatchType,
        requested_count: int = 1,
    ) -> Dict[str, Any]:
        """Check if a user has remaining quota for the requested batch type."""
        try:
            limits = self.batch_limits[batch_type]
            today = date.today()

            with self._connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT COALESCE(SUM(items_processed), 0) AS used_today
                        FROM daily_quotas
                        WHERE user_id = %s
                          AND batch_type = %s
                          AND date = %s
                        """,
                        (user_id, batch_type.value, today),
                    )
                    row = cursor.fetchone() or {"used_today": 0}
                    used_today = int(row.get("used_today") or 0)

            remaining = max(0, limits.daily_limit - used_today)
            can_proceed = remaining >= requested_count
            tomorrow = (
                datetime.now(timezone.utc)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1)
            )

            return {
                "can_proceed": can_proceed,
                "used_today": used_today,
                "remaining": remaining,
                "daily_limit": limits.daily_limit,
                "requested": requested_count,
                "reset_at": tomorrow.isoformat(),
                "batch_type": batch_type.value,
            }
        except Exception as exc:
            logger.error("Error checking daily quota: %s", exc)
            return {
                "can_proceed": False,
                "error": str(exc),
                "used_today": 0,
                "remaining": 0,
            }

    def record_usage(
        self,
        user_id: int,
        batch_type: BatchType,
        items_processed: int,
        batch_id: Optional[str] = None,
    ) -> bool:
        """Record usage against the user's daily quota."""
        try:
            today = date.today()
            timestamp = datetime.now(timezone.utc)

            with self._connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO daily_quotas (
                            user_id,
                            batch_type,
                            date,
                            items_processed,
                            last_batch_id,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (user_id, batch_type, date)
                        DO UPDATE SET
                            items_processed = daily_quotas.items_processed + EXCLUDED.items_processed,
                            last_batch_id = EXCLUDED.last_batch_id,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            user_id,
                            batch_type.value,
                            today,
                            items_processed,
                            batch_id,
                            timestamp,
                        ),
                    )
            logger.info(
                "Recorded %s %s usage for user %s",
                items_processed,
                batch_type.value,
                user_id,
            )
            return True
        except Exception as exc:
            logger.error("Error recording usage: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Batch preparation
    # ------------------------------------------------------------------
    def get_batch_ready_items(
        self,
        batch_type: BatchType,
        user_id: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return queued items ready for batch execution."""
        limits = self.batch_limits[batch_type]
        batch_size = limit or limits.batch_size

        try:
            with self._connection() as conn:
                with conn.cursor() as cursor:
                    if batch_type == BatchType.WARM_UP_VISITS:
                        query = [
                            """
                            SELECT
                                id,
                                prospect_id,
                                linkedin_url,
                                scheduled_for,
                                created_at
                            FROM profile_warmup_queue
                            WHERE status = 'pending'
                              AND scheduled_for <= NOW()
                            """
                        ]
                        params: List[Any] = []
                        if user_id is not None:
                            query.append(
                                "AND prospect_id IN (SELECT id FROM prospects WHERE user_id = %s)"
                            )
                            params.append(user_id)
                        query.append("ORDER BY scheduled_for ASC LIMIT %s")
                        params.append(batch_size)
                        cursor.execute(" ".join(query), params)
                        rows = cursor.fetchall()
                        return [
                            {
                                "id": row["id"],
                                "prospect_id": row["prospect_id"],
                                "linkedin_url": row["linkedin_url"],
                                "scheduled_for": row["scheduled_for"].isoformat()
                                if row["scheduled_for"]
                                else None,
                                "created_at": row["created_at"].isoformat()
                                if row["created_at"]
                                else None,
                            }
                            for row in rows
                        ]

                    if batch_type == BatchType.OUTREACH_MESSAGES:
                        query = [
                            """
                            SELECT
                                id,
                                prospect_id,
                                contact_id,
                                linkedin_url,
                                channel,
                                message,
                                template_used,
                                created_at
                            FROM outreach_queue
                            WHERE status = 'ready_to_send'
                              AND (send_after IS NULL OR send_after <= NOW())
                            """
                        ]
                        params = []
                        if user_id is not None:
                            query.append(
                                "AND prospect_id IN (SELECT id FROM prospects WHERE user_id = %s)"
                            )
                            params.append(user_id)
                        query.append("ORDER BY priority DESC, created_at ASC LIMIT %s")
                        params.append(batch_size)
                        cursor.execute(" ".join(query), params)
                        rows = cursor.fetchall()
                        return [
                            {
                                "id": row["id"],
                                "prospect_id": row["prospect_id"],
                                "contact_id": row["contact_id"],
                                "linkedin_url": row["linkedin_url"],
                                "channel": row["channel"],
                                "message": row["message"],
                                "template_used": row.get("template_used"),
                                "created_at": row["created_at"].isoformat()
                                if row["created_at"]
                                else None,
                            }
                            for row in rows
                        ]

            return []
        except Exception as exc:
            logger.error("Error getting batch ready items: %s", exc)
            return []

    def create_batch(
        self,
        batch_type: BatchType,
        items: Iterable[Dict[str, Any]],
        user_id: int,
        priority: str = "normal",
    ) -> Optional[str]:
        """Create a new batch for processing and persist it."""
        items_list = list(items)
        if not items_list:
            return None

        import uuid

        batch_id = f"batch_{batch_type.value}_{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now(timezone.utc)

        try:
            with self._connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO processing_batches (
                            batch_id,
                            batch_type,
                            user_id,
                            status,
                            priority,
                            items_count,
                            created_at,
                            scheduled_for
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            batch_id,
                            batch_type.value,
                            user_id,
                            "pending",
                            priority,
                            len(items_list),
                            timestamp,
                            timestamp,
                        ),
                    )

                    for item in items_list:
                        cursor.execute(
                            """
                            INSERT INTO batch_items (
                                batch_id,
                                item_id,
                                item_type,
                                item_data,
                                status
                            )
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                batch_id,
                                item.get("id"),
                                batch_type.value,
                                json.dumps(item, default=str),
                                "pending",
                            ),
                        )

            logger.info("Created batch %s with %s items", batch_id, len(items_list))
            return batch_id
        except Exception as exc:
            logger.error("Error creating batch: %s", exc)
            return None

    def execute_batch(self, batch_id: str) -> Dict[str, Any]:
        """Execute a persisted batch by delegating to the appropriate handler."""
        try:
            with self._connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT batch_type, user_id, items_count
                        FROM processing_batches
                        WHERE batch_id = %s
                        """,
                        (batch_id,),
                    )
                    batch_row = cursor.fetchone()
                    if not batch_row:
                        return {"success": False, "error": "Batch not found"}

                    batch_type = BatchType(batch_row["batch_type"])
                    user_id = batch_row["user_id"]

                    cursor.execute(
                        """
                        UPDATE processing_batches
                        SET status = 'running',
                            started_at = %s
                        WHERE batch_id = %s
                        """,
                        (datetime.now(timezone.utc), batch_id),
                    )

                    cursor.execute(
                        """
                        SELECT item_id, item_data
                        FROM batch_items
                        WHERE batch_id = %s
                          AND status = 'pending'
                        """,
                        (batch_id,),
                    )
                    items = cursor.fetchall()

            if batch_type == BatchType.WARM_UP_VISITS:
                return self._execute_warmup_batch(batch_id, items, user_id)
            if batch_type == BatchType.OUTREACH_MESSAGES:
                return self._execute_outreach_batch(batch_id, items, user_id)
            return {"success": False, "error": f"Unknown batch type: {batch_type.value}"}
        except Exception as exc:
            logger.error("Error executing batch %s: %s", batch_id, exc)
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Batch execution helpers
    # ------------------------------------------------------------------
    def _execute_warmup_batch(
        self,
        batch_id: str,
        items: Iterable[Dict[str, Any]],
        user_id: int,
    ) -> Dict[str, Any]:
        """Execute warm-up visits batch using the warmup service."""
        from services.warmup_service import warmup_service

        parsed_items: List[Dict[str, Any]] = []
        for row in items:
            payload = self._parse_item_payload(row["item_data"])
            parsed_items.append(
                {
                    "id": row["item_id"],
                    "linkedin_url": payload.get("linkedin_url", f"warmup_{row['item_id']}"),
                }
            )

        try:
            result = warmup_service._execute_profile_visitor_batch(parsed_items)
        except Exception as exc:  # pragma: no cover - external dependency
            logger.exception("Warmup batch execution failed")
            result = {"success": False, "error": str(exc)}

        timestamp = datetime.now(timezone.utc)

        try:
            with self._connection() as conn:
                with conn.cursor() as cursor:
                    if result.get("success"):
                        container_id = result.get("containerId")
                        for item in parsed_items:
                            cursor.execute(
                                """
                                UPDATE profile_warmup_queue
                                SET status = 'visiting',
                                    container_id = %s,
                                    visited_at = %s
                                WHERE id = %s
                                """,
                                (container_id, timestamp, item["id"]),
                            )

                        cursor.execute(
                            """
                            UPDATE processing_batches
                            SET status = 'completed',
                                completed_at = %s,
                                success_count = %s,
                                container_id = %s
                            WHERE batch_id = %s
                            """,
                            (timestamp, len(parsed_items), container_id, batch_id),
                        )

                        self.record_usage(user_id, BatchType.WARM_UP_VISITS, len(parsed_items), batch_id)
                    else:
                        cursor.execute(
                            """
                            UPDATE processing_batches
                            SET status = 'failed',
                                completed_at = %s,
                                error_message = %s
                            WHERE batch_id = %s
                            """,
                            (timestamp, result.get("error"), batch_id),
                        )
        except Exception as exc:
            logger.error("Error updating warmup batch state: %s", exc)

        return {
            "success": result.get("success", False),
            "processed": len(parsed_items),
            "container_id": result.get("containerId"),
            "error": result.get("error"),
        }

    def _execute_outreach_batch(
        self,
        batch_id: str,
        items: Iterable[Dict[str, Any]],
        user_id: int,
    ) -> Dict[str, Any]:
        """Execute outreach batch via PhantomBuster."""
        try:
            from integrations.phantombuster_client import phantombuster_client
        except ImportError:  # pragma: no cover - optional dependency
            logger.error("PhantomBuster client unavailable for outreach batch")
            return {"success": False, "error": "phantombuster_client_missing"}

        parsed_items: List[Dict[str, Any]] = []
        for row in items:
            payload = self._parse_item_payload(row["item_data"])
            parsed_items.append(
                {
                    "id": row["item_id"],
                    "profileUrl": payload.get("linkedin_url", f"profile_{row['item_id']}"),
                    "message": payload.get("message", ""),
                }
            )

        try:
            result = phantombuster_client.launch_message_sender_linkedin(parsed_items)
        except Exception as exc:  # pragma: no cover - external dependency
            logger.exception("Outreach batch execution failed")
            result = {"success": False, "error": str(exc)}

        timestamp = datetime.now(timezone.utc)

        try:
            with self._connection() as conn:
                with conn.cursor() as cursor:
                    if result.get("success"):
                        container_id = result.get("containerId")
                        cursor.execute(
                            """
                            UPDATE outreach_queue
                            SET status = 'sent',
                                sent_at = %s,
                                container_id = %s
                            WHERE id = ANY(%s)
                            """,
                            (
                                timestamp,
                                container_id,
                                [item["id"] for item in parsed_items],
                            ),
                        )

                        cursor.execute(
                            """
                            UPDATE processing_batches
                            SET status = 'completed',
                                completed_at = %s,
                                success_count = %s,
                                container_id = %s
                            WHERE batch_id = %s
                            """,
                            (timestamp, len(parsed_items), container_id, batch_id),
                        )

                        self.record_usage(
                            user_id, BatchType.OUTREACH_MESSAGES, len(parsed_items), batch_id
                        )
                    else:
                        cursor.execute(
                            """
                            UPDATE processing_batches
                            SET status = 'failed',
                                completed_at = %s,
                                error_message = %s
                            WHERE batch_id = %s
                            """,
                            (timestamp, result.get("error"), batch_id),
                        )
        except Exception as exc:
            logger.error("Error updating outreach batch state: %s", exc)

        return {
            "success": result.get("success", False),
            "processed": len(parsed_items),
            "container_id": result.get("containerId"),
            "error": result.get("error"),
        }

    # ------------------------------------------------------------------
    # Reporting utilities
    # ------------------------------------------------------------------
    def get_user_daily_summary(self, user_id: int) -> Dict[str, Any]:
        """Return a per-batch-type summary of today's usage for a user."""
        today = date.today()
        summary: Dict[str, Any] = {}

        try:
            with self._connection() as conn:
                with conn.cursor() as cursor:
                    for batch_type in BatchType:
                        limits = self.batch_limits[batch_type]
                        cursor.execute(
                            """
                            SELECT COALESCE(SUM(items_processed), 0) AS used_today
                            FROM daily_quotas
                            WHERE user_id = %s
                              AND batch_type = %s
                              AND date = %s
                            """,
                            (user_id, batch_type.value, today),
                        )
                        row = cursor.fetchone() or {"used_today": 0}
                        used_today = int(row.get("used_today") or 0)
                        remaining = max(0, limits.daily_limit - used_today)
                        percentage = (
                            round((used_today / limits.daily_limit) * 100, 1)
                            if limits.daily_limit
                            else 0
                        )
                        summary[batch_type.value] = {
                            "used_today": used_today,
                            "daily_limit": limits.daily_limit,
                            "remaining": remaining,
                            "percentage_used": percentage,
                        }
        except Exception as exc:
            logger.error("Error getting daily summary: %s", exc)
            return {}

        total_used = sum(entry["used_today"] for entry in summary.values())
        total_limit = sum(entry["daily_limit"] for entry in summary.values())
        summary["overall"] = {
            "total_used": total_used,
            "total_limit": total_limit,
            "overall_percentage": (
                round((total_used / total_limit) * 100, 1) if total_limit else 0
            ),
        }
        return summary

    def cleanup_old_batches(self, days_old: int = 7) -> int:
        """Remove batch metadata older than the configured threshold."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_old)

        try:
            with self._connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM batch_items
                        WHERE batch_id IN (
                            SELECT batch_id
                            FROM processing_batches
                            WHERE created_at < %s
                        )
                        """,
                        (cutoff,),
                    )

                    cursor.execute(
                        """
                        DELETE FROM processing_batches
                        WHERE created_at < %s
                        """,
                        (cutoff,),
                    )
                    deleted = cursor.rowcount or 0

            logger.info("Cleaned up %s old batch records", deleted)
            return deleted
        except Exception as exc:
            logger.error("Error cleaning up old batches: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_item_payload(raw: Any) -> Dict[str, Any]:
        """Parse stored item payloads, tolerating legacy string formats."""
        if isinstance(raw, dict):
            return raw
        if raw is None:
            return {}
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}


batch_service = BatchService()
