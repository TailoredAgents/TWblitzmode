"""
Outreach Service - PostgreSQL-backed warm introduction queue management.
All persistence flows rely on the shared Zero-Mock Postgres utilities.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from scripts.utils.postgres import (
    DEFAULT_TEST_DSN,
    postgres_connection,
    resolve_required_dsn,
)
from services.mutuals_service import normalize_linkedin_url

logger = logging.getLogger(__name__)


class OutreachService:
    """Service for managing LinkedIn outreach queue and message delivery."""

    def __init__(self, *, database_url: Optional[str] = None):
        self.daily_message_limit = 25  # Conservative LinkedIn limit
        self.min_message_delay = 300  # 5 minutes between messages (seconds)
        self.max_retry_attempts = 2
        self._database_url = database_url

    # ------------------------------------------------------------------
    # Internal helpers
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

    @staticmethod
    def _placeholder_array(identifier_count: int) -> sql.SQL:
        """Construct a SQL placeholder list for IN/ANY style updates."""
        return sql.SQL(", ").join(sql.Placeholder() for _ in range(identifier_count))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def queue_outreach(
        self,
        introducers: Iterable[Dict[str, Any]],
        prospect: Dict[str, Any],
        template_name: str = "intro_default",
        auto_approve: bool = False,
        tenant_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Queue outreach messages for introducers."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required for multi-tenant isolation")

        introducer_list = list(introducers)
        if not introducer_list:
            return []

        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT body FROM message_templates WHERE name = %s AND active = TRUE",
                    (template_name,),
                )
                template_row = cursor.fetchone()
                if not template_row:
                    raise ValueError(f"Template '{template_name}' not found")

                template_body = template_row["body"]
                queued_items: List[Dict[str, Any]] = []

                for introducer in introducer_list:
                    linkedin_url = normalize_linkedin_url(introducer.get("linkedin_url", ""))
                    if not linkedin_url:
                        logger.info("Skipping introducer without LinkedIn URL: %s", introducer)
                        continue

                    if self._is_in_do_not_contact(cursor, linkedin_url):
                        logger.info("Skipping %s - in do-not-contact list", introducer.get("full_name"))
                        continue

                    if not self._within_daily_limit(cursor, tenant_id):
                        logger.warning("Daily message limit reached, queuing without auto-approval")
                        auto_approve = False

                    message = self._render_template(template_body, introducer, prospect)
                    status = "ready_to_send" if auto_approve else "pending_approval"
                    approved_at = datetime.now(timezone.utc) if auto_approve else None

                    # Avoid duplicate queue entries for the same prospect/linkedin URL.
                    cursor.execute(
                        """
                        SELECT id
                        FROM outreach_queue
                        WHERE tenant_id = %s
                          AND prospect_id = %s
                          AND linkedin_url = %s
                          AND status IN ('pending_approval', 'ready_to_send', 'launched')
                        """,
                        (tenant_id, prospect["id"], linkedin_url),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        logger.debug(
                            "Outreach already queued for tenant=%s, prospect=%s, linkedin=%s",
                            tenant_id,
                            prospect["id"],
                            linkedin_url,
                        )
                        continue

                    cursor.execute(
                        """
                        INSERT INTO outreach_queue (
                            tenant_id,
                            prospect_id,
                            contact_id,
                            linkedin_url,
                            channel,
                            message,
                            status,
                            approved_at,
                            created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        RETURNING id
                        """,
                        (
                            tenant_id,
                            prospect["id"],
                            introducer.get("contact_id") or introducer.get("id"),
                            linkedin_url,
                            self._determine_channel(linkedin_url),
                            message,
                            status,
                            approved_at,
                        ),
                    )
                    row = cursor.fetchone()

                    queued_items.append(
                        {
                            "id": row["id"],
                            "contact_id": introducer.get("contact_id") or introducer.get("id"),
                            "introducer_name": introducer.get("full_name"),
                            "message": message,
                            "status": status,
                            "channel": self._determine_channel(linkedin_url),
                        }
                    )

        return queued_items

    def get_pending_approval(
        self,
        limit: int = 10,
        *,
        tenant_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return outreach items awaiting approval."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required to fetch pending outreach approvals")

        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        oq.id,
                        oq.message,
                        oq.channel,
                        oq.created_at,
                        c.full_name AS introducer_name,
                        c.linkedin_url AS introducer_url,
                        p.full_name AS prospect_name,
                        p.company AS prospect_company
                    FROM outreach_queue oq
                    JOIN contacts c ON oq.contact_id = c.id
                    JOIN prospects p ON oq.prospect_id = p.id
                    WHERE oq.status = 'pending_approval' AND oq.tenant_id = %s
                    ORDER BY oq.created_at ASC
                    LIMIT %s
                    """,
                    (tenant_id, limit),
                )
                rows = cursor.fetchall()
                return [
                    {
                        "id": row["id"],
                        "message": row["message"],
                        "channel": row["channel"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "introducer_name": row["introducer_name"],
                        "introducer_url": row["introducer_url"],
                        "prospect_name": row["prospect_name"],
                        "prospect_company": row["prospect_company"],
                    }
                    for row in rows
                ]

    def approve_outreach(
        self,
        queue_ids: List[int],
        *,
        tenant_id: Optional[int] = None,
    ) -> Dict[str, int]:
        """Approve outreach items for sending."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required to approve outreach")

        if not queue_ids:
            return {"approved": 0}

        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE outreach_queue
                    SET status = 'ready_to_send',
                        approved_at = NOW()
                    WHERE tenant_id = %s
                      AND status = 'pending_approval'
                      AND id = ANY(%s)
                    """,
                    (tenant_id, queue_ids),
                )
                approved_count = cursor.rowcount or 0
        return {"approved": approved_count}

    def send_ready_outreach(self, *, tenant_id: Optional[int] = None) -> Dict[str, Any]:
        """Send all ready outreach messages via PhantomBuster."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required to send outreach")

        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        oq.id,
                        oq.linkedin_url,
                        oq.message,
                        oq.channel,
                        c.full_name AS introducer_name
                    FROM outreach_queue oq
                    JOIN contacts c ON oq.contact_id = c.id
                    WHERE oq.status = 'ready_to_send'
                      AND oq.tenant_id = %s
                    ORDER BY oq.approved_at ASC
                    LIMIT %s
                    """,
                    (tenant_id, min(10, self.daily_message_limit)),
                )
                ready_items = cursor.fetchall()

                if not ready_items:
                    return {"sent": 0, "message": "No items ready to send"}

                linkedin_dm_items = [
                    {
                        "id": row["id"],
                        "profileUrl": row["linkedin_url"],
                        "message": row["message"],
                        "name": row["introducer_name"],
                    }
                    for row in ready_items
                    if row["channel"] == "linkedin_dm"
                ]

                results = {"sent": 0, "launched": 0, "errors": []}
                if linkedin_dm_items:
                    batch_result = self._send_linkedin_dm_batch(cursor, linkedin_dm_items, tenant_id)
                    results["sent"] += batch_result.get("sent", 0)
                    results["launched"] += batch_result.get("launched", 0)
                    results["errors"].extend(batch_result.get("errors", []))

        return results

    def get_outreach_status(
        self,
        prospect_id: Optional[int] = None,
        *,
        tenant_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get outreach status summary."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required to inspect outreach status")

        with self._connection() as conn:
            with conn.cursor() as cursor:
                params: List[Any] = [tenant_id]
                query = """
                    SELECT status, COUNT(*) AS count
                    FROM outreach_queue
                    WHERE tenant_id = %s
                """
                if prospect_id is not None:
                    query += " AND prospect_id = %s"
                    params.append(prospect_id)
                query += " GROUP BY status"

                cursor.execute(query, params)
                status_counts = {
                    row["status"]: int(row["count"] or 0)
                    for row in cursor.fetchall()
                }

                cursor.execute(
                    """
                    SELECT
                        oq.status,
                        oq.sent_at,
                        oq.error_message,
                        c.full_name AS introducer_name,
                        p.full_name AS prospect_name
                    FROM outreach_queue oq
                    JOIN contacts c ON oq.contact_id = c.id
                    JOIN prospects p ON oq.prospect_id = p.id
                    WHERE oq.tenant_id = %s
                      AND oq.created_at > NOW() - INTERVAL '7 days'
                    ORDER BY oq.created_at DESC
                    LIMIT 20
                    """,
                    (tenant_id,),
                )
                recent_activity = [
                    {
                        "status": row["status"],
                        "sent_at": row["sent_at"].isoformat() if row["sent_at"] else None,
                        "error": row["error_message"],
                        "introducer_name": row["introducer_name"],
                        "prospect_name": row["prospect_name"],
                    }
                    for row in cursor.fetchall()
                ]

                messages_sent_today = self._get_daily_send_count(cursor, tenant_id)

        return {
            "status_counts": status_counts,
            "recent_activity": recent_activity,
            "daily_limit": self.daily_message_limit,
            "messages_sent_today": messages_sent_today,
        }

    # ------------------------------------------------------------------
    # Supporting helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _render_template(template: str, introducer: Dict[str, Any], prospect: Dict[str, Any]) -> str:
        """Render message template with merge fields."""
        try:
            first_name = (introducer.get("full_name") or "").split()[0] or "there"
            at_company = f" at {prospect['company']}" if prospect.get("company") else ""
            message = template.replace("{{firstName}}", first_name)
            message = message.replace("{{prospectName}}", prospect.get("full_name", "the prospect"))
            message = message.replace("{{atCompany}}", at_company)
            return message
        except Exception:
            logger.exception("Error rendering outreach template; returning original body")
            return template

    @staticmethod
    def _determine_channel(linkedin_url: str) -> str:
        """Determine message channel based on LinkedIn URL format."""
        if "/sales/lead/" in linkedin_url or "/sales/people/" in linkedin_url:
            return "linkedin_sales_nav"
        return "linkedin_dm"

    @staticmethod
    def _is_in_do_not_contact(cursor, linkedin_url: str) -> bool:
        """Check if LinkedIn URL is in do-not-contact list."""
        if not linkedin_url:
            return True
        cursor.execute(
            "SELECT 1 FROM do_not_contact WHERE linkedin_url = %s",
            (linkedin_url,),
        )
        return cursor.fetchone() is not None

    def _within_daily_limit(self, cursor, tenant_id: int) -> bool:
        """Check if we're within daily message limits."""
        count = self._get_daily_send_count(cursor, tenant_id)
        return count < self.daily_message_limit

    @staticmethod
    def _get_daily_send_count(cursor, tenant_id: int) -> int:
        """Get number of messages sent today for a tenant."""
        cursor.execute(
            """
            SELECT COUNT(*) AS sent_count
            FROM outreach_queue
            WHERE tenant_id = %s
              AND status IN ('sent', 'launched')
              AND sent_at IS NOT NULL
              AND sent_at::date = CURRENT_DATE
            """,
            (tenant_id,),
        )
        row = cursor.fetchone() or {"sent_count": 0}
        return int(row.get("sent_count") or 0)

    def _send_linkedin_dm_batch(
        self,
        cursor,
        items: List[Dict[str, Any]],
        tenant_id: int,
    ) -> Dict[str, Any]:
        """Send LinkedIn DM batch via PhantomBuster."""
        if not items:
            return {"launched": 0, "sent": 0, "errors": []}

        try:
            from integrations.phantombuster_client import phantombuster_client
        except ImportError:
            logger.error("PhantomBuster client not available for outreach sending")
            return {"launched": 0, "sent": 0, "errors": ["phantombuster_client_missing"]}

        payload = [{"profileUrl": item["profileUrl"], "message": item["message"]} for item in items]

        try:
            container_result = phantombuster_client.launch_message_sender_linkedin(payload)
        except Exception as exc:  # pragma: no cover - external service failure
            logger.exception("Failed to invoke PhantomBuster client")
            return {"launched": 0, "sent": 0, "errors": [str(exc)]}

        if not container_result.get("success"):
            error_msg = container_result.get("error", "Unknown PhantomBuster error")
            logger.error("Failed to launch LinkedIn DM batch: %s", error_msg)
            return {"launched": 0, "sent": 0, "errors": [error_msg]}

        container_id = container_result.get("containerId")
        item_ids = [item["id"] for item in items]
        timestamp = datetime.now(timezone.utc)

        cursor.execute(
            """
            UPDATE outreach_queue
            SET status = 'launched',
                container_id = %s,
                sent_at = %s
            WHERE tenant_id = %s
              AND id = ANY(%s)
            """,
            (container_id, timestamp, tenant_id, item_ids),
        )

        logger.info("Launched LinkedIn DM batch with %s messages (Container: %s)", len(items), container_id)
        return {"launched": len(items), "sent": 0, "container_id": container_id, "errors": []}


outreach_service = OutreachService()
