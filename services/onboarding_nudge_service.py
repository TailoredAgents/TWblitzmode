"""
Utilities for onboarding nudges and automatic reminder scheduling.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from core.settings import settings
from integrations.sendgrid_client import SendGridClient
from services.audit_logging_service import AuditEventType, AuditSeverity, audit_service

try:  # Optional Prometheus metrics
    from monitoring.vouchlink_metrics import vouchlink_metrics  # type: ignore
except Exception:  # pragma: no cover - metrics are optional in dev
    vouchlink_metrics = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def dispatch_onboarding_nudge(
    *,
    organization: Dict[str, Any],
    stalled_members: List[Dict[str, Any]],
    admin_contacts: List[Dict[str, str]],
    initiated_by: Optional[str],
    current_user_id: Optional[str],
    note: Optional[str] = None,
    auto_triggered: bool = False,
    require_email_service: bool = True,
) -> Dict[str, Any]:
    """
    Send onboarding reminder email to admin contacts and record audit/metrics.
    """
    if not admin_contacts:
        return {
            "notified": 0,
            "errors": ["No admin contacts available"],
            "message": "No admin contacts available.",
        }

    sendgrid_client = SendGridClient(tenant_id=organization["tenant_id"])
    if not sendgrid_client.api_key:
        if require_email_service:
            raise RuntimeError("Email service is not configured")
        return {
            "notified": 0,
            "errors": ["Email service is not configured"],
            "message": "Email service is not configured.",
        }

    template_id = settings.SENDGRID_ONBOARDING_NUDGE_TEMPLATE_ID
    subject = "Team onboarding reminder" if not auto_triggered else "Automatic onboarding reminder"

    dynamic_base = {
        "organization": organization.get("id"),
        "organization_name": organization.get("name"),
        "stalled_count": len(stalled_members),
        "members": [
            {
                "name": member.get("name"),
                "email": member.get("email"),
                "role": member.get("role"),
                "reasons": ", ".join(member.get("reasons", [])),
            }
            for member in stalled_members
        ],
        "note": note or "",
        "auto_triggered": auto_triggered,
        "initiated_by": initiated_by or "system",
    }

    notified = 0
    errors: List[str] = []

    for contact in admin_contacts:
        try:
            result = await sendgrid_client.send_email(
                to_email=contact["email"],
                subject=subject,
                body=(
                    "The following team members still need to finish onboarding:\n"
                    + "\n".join(
                        f"- {member.get('name') or member.get('email') or 'Team member'}: "
                        f"{', '.join(member.get('reasons', []))}"
                        for member in stalled_members
                    )
                ),
                template_id=template_id,
                dynamic_data={
                    **dynamic_base,
                    "admin_name": contact.get("name") or contact["email"],
                }
                if template_id
                else None,
                add_unsubscribe=False,
            )
        except Exception as exc:  # pragma: no cover - defensive path
            logger.error("Failed to send onboarding reminder to %s: %s", contact["email"], exc)
            errors.append(contact["email"])
            continue

        if result.success:
            notified += 1
        else:
            errors.append(f"{contact['email']}: {result.error_message}")

    await audit_service.log_event(
        tenant_id=str(organization["tenant_id"]),
        user_id=current_user_id,
        event_type=AuditEventType.ONBOARDING_NUDGE,
        action="auto" if auto_triggered else "manual",
        resource_type="organization",
        resource_id=str(organization["id"]),
        severity=AuditSeverity.LOW if notified else AuditSeverity.MEDIUM,
        details={
            "notified": notified,
            "stalled_member_count": len(stalled_members),
            "initiated_by": initiated_by,
            "note": note,
            "errors": errors,
            "auto_triggered": auto_triggered,
        },
        success=notified > 0,
    )

    if vouchlink_metrics:
        try:
            vouchlink_metrics.record_auto_nudge(
                organization_id=str(organization["id"]),
                tenant_id=str(organization["tenant_id"]),
                trigger="auto" if auto_triggered else "manual",
                result="success" if notified else ("error" if errors else "skipped"),
            )
        except Exception:  # pragma: no cover - metrics are best-effort
            logger.debug("Failed to record auto nudge metric", exc_info=True)

    message = (
        "Onboarding reminders sent to organization admins."
        if notified
        else "No reminders were sent. Check email configuration."
    )
    if errors:
        message += f" Delivery issues: {', '.join(errors[:3])}"

    return {
        "notified": notified,
        "errors": errors,
        "message": message,
    }


async def maybe_trigger_auto_nudge(
    *,
    organization: Dict[str, Any],
    stalled_members: List[Dict[str, Any]],
    admin_contacts: List[Dict[str, str]],
    billing_details: Dict[str, Any],
    require_email_service: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], bool, Optional[Dict[str, Any]]]:
    """
    Evaluate whether an automatic nudge should fire and update billing metadata.
    Returns (auto_info, updated_billing_details, billing_changed, dispatch_result).
    """
    if vouchlink_metrics:
        try:
            vouchlink_metrics.update_stalled_members(
                organization_id=str(organization["id"]),
                tenant_id=str(organization["tenant_id"]),
                count=len(stalled_members),
            )
        except Exception:  # pragma: no cover - metrics are best-effort
            logger.debug("Failed to update stalled member gauge", exc_info=True)

    auto_meta = dict(billing_details.get("auto_nudge") or {})
    auto_info: Dict[str, Any] = {
        "enabled": bool(settings.COMPANY_PORTAL_AUTO_NUDGE_ENABLED),
        "cooldown_seconds": settings.COMPANY_PORTAL_AUTO_NUDGE_COOLDOWN_SECONDS,
        "last_sent_at": auto_meta.get("last_sent_at"),
    }

    if not settings.COMPANY_PORTAL_AUTO_NUDGE_ENABLED or not stalled_members:
        return auto_info, billing_details, False, None

    cooldown = max(0, settings.COMPANY_PORTAL_AUTO_NUDGE_COOLDOWN_SECONDS)
    last_sent_at = auto_meta.get("last_sent_at")
    last_sent_dt: Optional[datetime] = None
    if last_sent_at:
        try:
            last_sent_dt = datetime.fromisoformat(last_sent_at)
        except ValueError:
            last_sent_dt = None

    should_send = last_sent_dt is None or (datetime.now(timezone.utc) - last_sent_dt).total_seconds() >= cooldown
    if not should_send:
        return auto_info, billing_details, False, None

    dispatch = await dispatch_onboarding_nudge(
        organization=organization,
        stalled_members=stalled_members,
        admin_contacts=admin_contacts,
        initiated_by="system",
        current_user_id=None,
        note="Automatic reminder triggered for stalled onboarding members.",
        auto_triggered=True,
        require_email_service=require_email_service,
    )

    now_iso = _now_iso()
    billing_changed = False
    if dispatch["notified"] > 0:
        auto_meta.update({
            "last_sent_at": now_iso,
            "last_notified": [contact["email"] for contact in admin_contacts],
            "last_message": dispatch["message"],
        })
        auto_info["last_sent_at"] = now_iso
        auto_info["last_notified"] = auto_meta.get("last_notified")
        billing_details["auto_nudge"] = auto_meta
        billing_changed = True
    elif dispatch["errors"]:
        auto_meta["last_error"] = {
            "recorded_at": now_iso,
            "messages": dispatch["errors"],
        }
        billing_details["auto_nudge"] = auto_meta
        auto_info["errors"] = dispatch["errors"]
        billing_changed = True

    return auto_info, billing_details, billing_changed, dispatch