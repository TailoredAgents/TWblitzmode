"""
Organization-wide cookie collection workflow helper.

Provides aggregation of team cookie coverage, identifies missing or stale jars,
records audit events, and returns structured summaries for Link chat responses.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from api.db_core import get_conn as portal_get_conn, query as portal_query
from api.cookie_service import (
    list_cookie_statuses,
    summarize_cookie_health,
    record_cookie_event,
)

logger = logging.getLogger(__name__)


class CookieCollectionWorkflow:
    """Aggregate cookie coverage and log reminders for organization tenants."""

    def __init__(self, expiring_window_days: Optional[int] = None) -> None:
        window_env = os.getenv("COOKIE_COLLECTION_EXPIRING_WINDOW_DAYS")
        if expiring_window_days is not None:
            self.expiring_window_days = expiring_window_days
        elif window_env and window_env.isdigit():
            self.expiring_window_days = int(window_env)
        else:
            self.expiring_window_days = 7

    async def collect_for_org(self, organization_id: int, requested_by: int) -> Dict[str, Any]:
        """Return cookie coverage summary and log any required follow-up events."""

        summary: Dict[str, Any] = {
            "organization_id": organization_id,
            "requested_by": requested_by,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "total_team_members": 0,
                "tracked_jars": 0,
                "valid": 0,
                "pending": 0,
                "invalid": 0,
                "expired": 0,
            },
            "health_totals": {},
            "missing_members": [],
            "rotation_required": [],
            "expiring_soon": [],
            "events_logged": 0,
            "expiring_window_days": self.expiring_window_days,
        }

        events_logged = 0

        try:
            with portal_get_conn() as conn:
                team_rows = portal_query(
                    conn,
                    """
                    SELECT tm.id, tm.user_id, tm.email, tm.first_name, tm.last_name, tm.role, tm.status
                    FROM team_members tm
                    WHERE tm.organization_id = ?
                    ORDER BY lower(COALESCE(tm.first_name || ' ' || tm.last_name, tm.email, ''))
                    """,
                    (organization_id,),
                )

                cookie_rows = list_cookie_statuses(conn, organization_id)
                health_totals = summarize_cookie_health(conn, organization_id)

                summary["counts"]["total_team_members"] = len(team_rows)
                summary["counts"]["tracked_jars"] = len(cookie_rows)
                summary["counts"]["valid"] = sum(1 for row in cookie_rows if (row.get("status") or "").lower() == "valid")
                summary["counts"]["pending"] = sum(1 for row in cookie_rows if (row.get("status") or "").lower() == "pending")
                summary["counts"]["invalid"] = sum(1 for row in cookie_rows if (row.get("status") or "").lower() == "invalid")
                summary["counts"]["expired"] = sum(1 for row in cookie_rows if (row.get("status") or "").lower() == "expired")
                summary["health_totals"] = health_totals

                cookies_by_user = {
                    row.get("user_id"): row for row in cookie_rows if row.get("user_id") is not None
                }

                cookie_inventory: List[Dict[str, Any]] = []
                for record in cookie_rows:
                    entry = self._build_cookie_entry(record)
                    entry.update(
                        {
                            "status_detail": record.get("status_detail"),
                            "last_used_at": record.get("last_used_at"),
                            "usage_count": record.get("usage_count", 0),
                            "error_count": record.get("error_count", 0),
                            "vault_item_present": bool(record.get("vault_item_id")),
                            "locked_by": record.get("locked_by"),
                            "lock_expires_at": record.get("lock_expires_at"),
                        }
                    )
                    cookie_inventory.append(entry)

                summary["cookie_inventory"] = cookie_inventory

                missing_members: List[Dict[str, Any]] = []
                for record in team_rows:
                    user_id = record.get("user_id")
                    if not user_id or cookies_by_user.get(user_id):
                        continue
                    entry = self._build_team_entry(record)
                    missing_members.append(entry)
                    events_logged += await self._record_event_safe(
                        conn,
                        organization_id=organization_id,
                        user_id=user_id,
                        jar_id=None,
                        event_type="collection_requested",
                        status="pending",
                        message="Link requested a new LinkedIn cookie upload.",
                        metadata={
                            "requested_by": requested_by,
                            "source": "link_chat",
                        },
                    )

                rotation_required: List[Dict[str, Any]] = []
                for record in cookie_rows:
                    status = (record.get("status") or "").lower()
                    if status in {"invalid", "expired"}:
                        entry = self._build_cookie_entry(record)
                        rotation_required.append(entry)
                        if entry.get("user_id") is not None and entry.get("jar_id") is not None:
                            events_logged += await self._record_event_safe(
                                conn,
                                organization_id=organization_id,
                                user_id=entry["user_id"],
                                jar_id=entry["jar_id"],
                                event_type="rotation_required",
                                status="warning",
                                message="Cookie rotation required — current jar is invalid or expired.",
                                metadata={
                                    "requested_by": requested_by,
                                    "source": "link_chat",
                                },
                            )

                expiring_soon: List[Dict[str, Any]] = []
                now = datetime.now(timezone.utc)
                threshold = now + timedelta(days=self.expiring_window_days)
                for record in cookie_rows:
                    if (record.get("status") or "").lower() != "valid":
                        continue
                    expires_at = self._parse_datetime(record.get("expires_at"))
                    if expires_at and now <= expires_at <= threshold:
                        entry = self._build_cookie_entry(record, expires_at)
                        expiring_soon.append(entry)

                summary["missing_members"] = missing_members
                summary["rotation_required"] = rotation_required
                summary["expiring_soon"] = expiring_soon

        except Exception as exc:
            logger.error("Cookie collection workflow error for org %s: %s", organization_id, exc)
            raise

        summary["events_logged"] = events_logged
        return summary

    async def _record_event_safe(
        self,
        conn,
        *,
        organization_id: int,
        user_id: Optional[int],
        jar_id: Optional[int],
        event_type: str,
        status: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Best-effort wrapper for cookie event logging."""

        if user_id is None:
            return 0

        try:
            await record_cookie_event(
                conn,
                organization_id=organization_id,
                user_id=user_id,
                jar_id=jar_id,
                event_type=event_type,
                status=status,
                message=message,
                metadata=metadata,
            )
            return 1
        except Exception as exc:
            logger.debug(
                "Skipping cookie event logging for org %s user %s: %s",
                organization_id,
                user_id,
                exc,
            )
            return 0

    def _build_team_entry(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise team member details for summaries."""

        display_name = self._format_display_name(
            record.get("first_name"),
            record.get("last_name"),
            record.get("email"),
            record.get("user_id"),
        )

        return {
            "team_member_id": record.get("id"),
            "user_id": record.get("user_id"),
            "email": record.get("email"),
            "display_name": display_name,
            "role": record.get("role"),
            "status": record.get("status"),
        }

    def _build_cookie_entry(
        self,
        record: Dict[str, Any],
        expires_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Normalise cookie jar details for summaries."""

        display_name = self._format_display_name(
            record.get("first_name"),
            record.get("last_name"),
            record.get("email"),
            record.get("user_id"),
        )

        expires_value = expires_at or self._parse_datetime(record.get("expires_at"))
        validated_value = self._parse_datetime(record.get("last_validated_at"))

        return {
            "jar_id": record.get("id"),
            "user_id": record.get("user_id"),
            "email": record.get("email"),
            "display_name": display_name,
            "status": record.get("status"),
            "expires_at": expires_value.isoformat() if expires_value else record.get("expires_at"),
            "last_validated_at": validated_value.isoformat() if validated_value else record.get("last_validated_at"),
        }

    @staticmethod
    def _format_display_name(
        first_name: Optional[str],
        last_name: Optional[str],
        email: Optional[str],
        user_id: Optional[int],
    ) -> str:
        """Create a display-friendly identifier for reporting."""

        name_parts = [part for part in [first_name, last_name] if part]
        if name_parts:
            return " ".join(name_parts)
        if email:
            return email
        if user_id is not None:
            return f"user {user_id}"
        return "unknown user"

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Parse ISO datetime values from database rows."""

        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None


cookie_collection_workflow = CookieCollectionWorkflow()