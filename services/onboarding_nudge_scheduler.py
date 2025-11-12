"""
Background scheduler that periodically evaluates automatic onboarding nudges.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.settings import settings
from services.onboarding_nudge_service import maybe_trigger_auto_nudge
from .company_portal_service import (
    list_admin_contact_emails,
    load_billing_details,
    save_billing_details,
    summarize_onboarding_progress,
)
from api.db_core import get_conn, query

logger = logging.getLogger(__name__)


class OnboardingNudgeScheduler:
    """Async scheduler for automatic onboarding nudges."""

    def __init__(self, interval_minutes: Optional[int] = None):
        configured_interval = interval_minutes or settings.COMPANY_PORTAL_AUTO_NUDGE_INTERVAL_MINUTES
        self.interval_minutes = max(5, configured_interval)
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self.is_running:
            logger.warning("Onboarding nudge scheduler already running")
            return
        self.is_running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Onboarding nudge scheduler started (interval=%s minutes)", self.interval_minutes)

    async def stop(self) -> None:
        if not self.is_running:
            return
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Onboarding nudge scheduler stopped")

    async def _loop(self) -> None:
        while self.is_running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Onboarding nudge scheduler error: %s", exc, exc_info=True)
            await asyncio.sleep(self.interval_minutes * 60)

    async def run_once(self) -> Dict[str, Any]:
        """Run a single evaluation cycle."""
        summary: Dict[str, Any] = {
            "organizations_evaluated": 0,
            "nudges_dispatched": 0,
            "errors": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with get_conn() as conn:
            rows = query(
                conn,
                """
                SELECT id, tenant_id, name
                FROM organizations
                WHERE status IS NULL OR status NOT IN ('archived', 'inactive')
                """,
            )
            organizations = [dict(row) for row in rows]

        for organization in organizations:
            summary["organizations_evaluated"] += 1
            organization_id = organization["id"]

            try:
                with get_conn() as conn:
                    progress = summarize_onboarding_progress(conn, organization_id)
                    stalled_members = progress.get("stalled_members", [])
                    if not stalled_members:
                        continue

                    admin_contacts = list_admin_contact_emails(conn, organization_id)
                    billing_details = load_billing_details(conn, organization_id)

                    auto_info, updated_billing, changed, dispatch = await maybe_trigger_auto_nudge(
                        organization=organization,
                        stalled_members=stalled_members,
                        admin_contacts=admin_contacts,
                        billing_details=billing_details,
                        require_email_service=False,
                    )

                    if changed:
                        save_billing_details(conn, organization_id, updated_billing)

                    if dispatch and dispatch.get("notified"):
                        summary["nudges_dispatched"] += 1
                        logger.info(
                            "Automatic onboarding nudge dispatched",
                            extra={
                                "organization_id": organization_id,
                                "tenant_id": organization["tenant_id"],
                                "notified": dispatch["notified"],
                                "stalled_members": len(stalled_members),
                            },
                        )

                    logger.debug(
                        "Auto nudge evaluation for org %s complete (message=%s)",
                        organization_id,
                        (dispatch or {}).get("message"),
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Failed auto nudge evaluation for org %s: %s", organization_id, exc, exc_info=True)
                summary["errors"].append({"organization_id": organization_id, "error": str(exc)})

        return summary

    async def status(self) -> Dict[str, Any]:
        """Expose scheduler status for monitoring endpoints."""
        next_run = datetime.now(timezone.utc) + timedelta(minutes=self.interval_minutes)
        return {
            "running": self.is_running,
            "interval_minutes": self.interval_minutes,
            "next_run_eta": next_run.isoformat(),
        }


onboarding_nudge_scheduler = OnboardingNudgeScheduler()