from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import asyncio
import base64
import logging
import uuid

from .deps import get_current_user
from services.automated_workflow_service import auto_process_prospect, MessagePriority
try:  # pragma: no cover - prefer src layout but fall back to legacy paths
    from src.services.csv_processor import CSVProcessor  # type: ignore
except ImportError:
    from services.csv_processor import CSVProcessor  # type: ignore

try:
    from src.services.matching import MatchingService  # type: ignore
    MATCHING_SERVICE_AVAILABLE = True
except ImportError:
    try:
        from services.matching import MatchingService  # type: ignore
        MATCHING_SERVICE_AVAILABLE = True
    except ImportError:  # Matching is optional in minimal deployments
        MatchingService = None  # type: ignore
        MATCHING_SERVICE_AVAILABLE = False

try:
    from src.services.database import db  # type: ignore
except ImportError:
    from services.database import db  # type: ignore

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_organization_id(current_user: Dict[str, Any]) -> int:
    """
    Determine the numeric organization identifier for workflow automation.

    Many legacy flows only persisted a tenant identifier, but the automation
    stack expects an integer organization id for queue routing and cache keys.
    """
    organization_id = current_user.get("organization_id")
    if organization_id is not None:
        try:
            return int(organization_id)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid organization_id '%s' for user %s",
                organization_id,
                current_user.get("id"),
            )
            raise HTTPException(400, "Invalid organization context for user")

    tenant_id = current_user.get("tenant_id")
    if tenant_id is None:
        logger.warning("User %s missing tenant context", current_user.get("id"))
        raise HTTPException(400, "User is not associated with an organization")

    try:
        return int(tenant_id)
    except (TypeError, ValueError):
        logger.warning(
            "Unable to coerce tenant_id '%s' from user %s into organization id",
            tenant_id,
            current_user.get("id"),
        )
        raise HTTPException(400, "Organization context is required for automation")


class ProspectIn(BaseModel):
    full_name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    linkedin_url: Optional[str] = None
    notes: Optional[str] = None
    stage: Optional[str] = None
    source: Optional[str] = None
    confidence_score: Optional[float] = None


class ProspectBulkIn(BaseModel):
    prospects: List[ProspectIn]


class ProspectImportPayload(BaseModel):
    csv_data: str
    import_name: str


CSV_PROCESSOR = CSVProcessor()


def _decode_csv_payload(raw: str) -> str:
    """Decode dashboard CSV payloads that may arrive base64 encoded."""
    if not raw:
        return ""

    candidate = raw.strip()

    try:
        decoded = base64.b64decode(candidate, validate=True)
        if decoded:
            return decoded.decode("utf-8")
    except Exception:
        # Treat as plain text when decoding fails.
        pass

    return candidate


@router.get("/prospects")
async def list_prospects(
    current_user: Dict[str, Any] = Depends(get_current_user),
    search: Optional[str] = None,
    company: Optional[str] = None,
    status: Optional[List[str]] = None,
    priority: Optional[List[str]] = None,
    has_connectors: Optional[bool] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the tenant's prospects with additional filtering options for the dashboard."""

    tenant_id = current_user.get("tenant_id")
    user_id = current_user.get("id")

    if tenant_id is None or user_id is None:
        raise HTTPException(status_code=400, detail="Tenant context is required")

    # Prevent cross-tenant leakage unless explicitly allowed for admins.
    if organization_id is not None:
        normalized_requested = str(organization_id)
        normalized_user_org = str(current_user.get("organization_id") or tenant_id)
        role = (current_user.get("role") or "").lower()
        if normalized_requested != normalized_user_org and role != "admin":
            raise HTTPException(status_code=403, detail="Cross-tenant access is not permitted")

    # Base fetch via shared database helper (keeps SQLite/Postgres support).
    primary_status = "all"
    normalized_status_filters: Optional[List[str]] = None
    if status:
        normalized_status_filters = [value.strip().lower() for value in status if value]
        if len(normalized_status_filters) == 1:
            primary_status = normalized_status_filters[0]

    prospects = await db.get_prospects(
        status=primary_status,
        user_id=int(user_id),
        tenant_id=str(tenant_id),
    )

    # Fallback for multi-status filtering when the core helper can only apply a single value.
    if normalized_status_filters and len(normalized_status_filters) > 1:
        prospects = [
            record
            for record in prospects
            if (record.get("status") or "").strip().lower() in normalized_status_filters
        ]

    search_term = (search or "").strip().lower()
    company_filter = (company or "").strip().lower()
    priority_filters = {value.strip().lower() for value in priority or [] if value}

    # Parse date boundaries if provided (ISO strings from the UI).
    def _parse_date(value: Optional[str]):
        if not value:
            return None
        try:
            from datetime import datetime

            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)

    filtered: List[Dict[str, Any]] = []
    for record in prospects:
        candidate = record.copy()

        # Search across common fields.
        if search_term:
            haystack = " ".join(
                str(candidate.get(field, "") or "").lower()
                for field in ("full_name", "name", "company", "headline", "notes", "linkedin_url")
            )
            if search_term not in haystack:
                continue

        if company_filter:
            company_value = str(candidate.get("company", "") or "").lower()
            if company_filter not in company_value:
                continue

        if priority_filters:
            priority_value = str(candidate.get("priority", "") or "").lower()
            if priority_value not in priority_filters:
                continue

        if has_connectors is not None:
            match_flag = candidate.get("network_match_found")
            connection_count = candidate.get("total_connections") or candidate.get("connections_count")
            has_match = bool(match_flag) or (isinstance(connection_count, (int, float)) and connection_count > 0)
            if has_connectors and not has_match:
                continue
            if has_connectors is False and has_match:
                continue

        if start_dt or end_dt:
            created_value = candidate.get("created_at")
            candidate_dt = _parse_date(created_value)
            if candidate_dt is None:
                # If we cannot parse the timestamp, honour the filter by skipping ambiguous records.
                continue
            if start_dt and candidate_dt < start_dt:
                continue
            if end_dt and candidate_dt > end_dt:
                continue

        filtered.append(candidate)

    logger.debug(
        "Prospect query for tenant %s user %s returned %s records (filtered from %s)",
        tenant_id,
        user_id,
        len(filtered),
        len(prospects),
    )
    return filtered

@router.post("/prospects/add")
async def add_prospect(
    body: ProspectIn,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    tenant_id = current_user.get("tenant_id")
    user_id = current_user.get("id")
    if not tenant_id or not user_id:
        raise HTTPException(status_code=400, detail="Tenant context is required")
    if not body.linkedin_url:
        raise HTTPException(400, "linkedin_url is required")

    tenant_scope = str(tenant_id)
    existing = await db.get_prospect_by_linkedin(body.linkedin_url, tenant_id=tenant_scope)
    if existing:
        raise HTTPException(409, "Prospect already exists for this tenant")

    prospect_payload = {
        "name": body.full_name,
        "company": body.company,
        "title": body.title,
        "linkedin_url": body.linkedin_url,
        "notes": body.notes,
        "stage": body.stage,
        "source": body.source or "manual_add",
        "confidence_score": body.confidence_score,
        "status": "active",
    }

    prospect_id = await db.add_prospect(
        prospect_payload,
        user_id=int(user_id),
        tenant_id=tenant_scope,
    )

    organization_id = _resolve_organization_id(current_user)

    prospect_data = {
        "id": prospect_id,
        "name": body.full_name,
        "title": body.title,
        "company": body.company,
        "linkedin_url": body.linkedin_url,
        "notes": body.notes,
        "tenant_id": current_user["tenant_id"],
        "user_id": current_user["id"],
        "organization_id": organization_id,
        "stage": prospect_payload.get("stage"),
        "source": prospect_payload.get("source"),
        "confidence_score": prospect_payload.get("confidence_score"),
    }

    # Automatically trigger the workflow in the background
    asyncio.create_task(
        _trigger_automated_workflow(
            prospect_data,
            organization_id,
            current_user["id"],
        )
    )

    logger.info(
        "Prospect %s added for tenant %s (organization %s)",
        prospect_id,
        tenant_scope,
        organization_id,
    )

    return {
        "ok": True,
        "prospect_id": prospect_id,
        "workflow_triggered": True,
        "message": f"Prospect {body.full_name} added successfully. Automated processing started.",
    }


@router.post("/prospects/import")
async def import_prospects_from_csv(
    payload: ProspectImportPayload,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Import prospects from CSV data provided by the dashboard uploader."""

    tenant_id = current_user.get("tenant_id")
    user_id = current_user.get("id")

    if tenant_id is None or user_id is None:
        raise HTTPException(status_code=400, detail="Tenant and user context are required to import prospects")

    csv_content = _decode_csv_payload(payload.csv_data)
    prospects, validation = CSV_PROCESSOR.parse_prospects_csv(csv_content)
    for record in prospects:
        record.setdefault("source", "csv_import")

    if not prospects:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "No valid prospects found in CSV upload",
                "details": validation,
            },
        )

    try:
        added_count = await db.add_prospects_batch(
            prospects,
            user_id=int(user_id),
            tenant_id=str(tenant_id),
        )
    except Exception as exc:
        logger.exception("Prospect import failed for tenant %s: %s", tenant_id, exc)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Failed to import prospects"},
        )

    async def _post_import_tasks() -> None:
        if not MATCHING_SERVICE_AVAILABLE:
            return
        try:
            matching_service = MatchingService()  # type: ignore
            await matching_service.find_all_prospect_matches(
                user_id=int(user_id),
                tenant_id=str(tenant_id),
            )
        except Exception as exc:  # pragma: no cover - best-effort enrichment
            logger.warning(
                "Post-import matching failed for tenant %s user %s: %s",
                tenant_id,
                user_id,
                exc,
            )

    if MATCHING_SERVICE_AVAILABLE:
        asyncio.create_task(_post_import_tasks())

    job_id = f"prospect_import_{uuid.uuid4().hex[:12]}"

    return {
        "status": "accepted",
        "data": {
            "job_id": job_id,
            "import_name": payload.import_name,
            "prospects_processed": len(prospects),
            "prospects_imported": added_count,
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []),
        },
    }

async def _trigger_automated_workflow(
    prospect_data: Dict[str, Any],
    organization_id: int,
    user_id: int
):
    """Background task to trigger automated workflow"""
    try:
        workflow_id = await auto_process_prospect(
            prospect_data=prospect_data,
            organization_id=organization_id,
            user_id=user_id,
            priority=MessagePriority.NORMAL
        )
        logger.info(f"🚀 Automated workflow {workflow_id} started for prospect {prospect_data.get('name')}")
    except Exception as e:
        logger.error(f"Failed to trigger automated workflow: {e}")


@router.post("/prospects/{prospect_id}/reprocess")
async def reprocess_prospect(
    prospect_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Re-run automated processing for an existing prospect."""

    tenant_id = current_user.get("tenant_id")
    user_id = current_user.get("id")

    if tenant_id is None or user_id is None:
        raise HTTPException(status_code=400, detail="Tenant context is required to reprocess a prospect")

    prospect = await db.get_prospect_by_id(
        prospect_id=prospect_id,
        tenant_id=str(tenant_id),
        user_id=int(user_id),
    )
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found for the current tenant")

    organization_id = _resolve_organization_id(current_user)
    prospect_payload = {
        "id": prospect_id,
        "name": prospect.get("full_name") or prospect.get("name"),
        "title": prospect.get("headline") or prospect.get("title"),
        "company": prospect.get("company"),
        "linkedin_url": prospect.get("linkedin_url"),
        "notes": prospect.get("notes"),
        "tenant_id": prospect.get("tenant_id") or tenant_id,
        "user_id": user_id,
        "organization_id": organization_id,
    }

    asyncio.create_task(
        _trigger_automated_workflow(
            prospect_payload,
            organization_id,
            int(user_id),
        )
    )

    job_id = f"prospect_reprocess_{prospect_id}_{uuid.uuid4().hex[:8]}"

    return {
        "status": "accepted",
        "data": {
            "job_id": job_id,
            "prospect_id": prospect_id,
            "message": "Prospect reprocessing started",
        },
    }


@router.post("/prospects/bulk-add")
async def bulk_add_prospects(
    payload: ProspectBulkIn,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Add multiple prospects and trigger automated workflows"""

    tenant_id = current_user.get("tenant_id")
    user_id = current_user.get("id")
    if tenant_id is None or user_id is None:
        raise HTTPException(status_code=400, detail="Tenant context is required")

    tenant_scope = str(tenant_id)
    user_scope = int(user_id)

    added_prospects: List[Dict[str, Any]] = []
    skipped_prospects: List[Dict[str, Any]] = []

    for prospect_data in payload.prospects:
        payload_dict = prospect_data.dict()
        linkedin_url = (prospect_data.linkedin_url or "").strip()
        if not linkedin_url:
            skipped_prospects.append(
                {
                    "prospect": payload_dict,
                    "reason": "LinkedIn URL is required",
                }
            )
            continue

        existing = await db.get_prospect_by_linkedin(linkedin_url, tenant_id=tenant_scope)
        if existing:
            skipped_prospects.append(
                {
                    "prospect": payload_dict,
                    "reason": "Prospect already exists",
                }
            )
            continue

        source_value = prospect_data.source or "manual_add"

        new_id = await db.add_prospect(
            {
                "name": prospect_data.full_name,
                "company": prospect_data.company,
                "title": prospect_data.title,
                "linkedin_url": linkedin_url,
                "notes": prospect_data.notes,
                "stage": prospect_data.stage,
                "source": source_value,
                "confidence_score": prospect_data.confidence_score,
                "status": "active",
            },
            user_id=user_scope,
            tenant_id=tenant_scope,
        )

        added_prospects.append(
            {
                "prospect_id": new_id,
                "linkedin_url": linkedin_url,
                "full_name": prospect_data.full_name,
                "title": prospect_data.title,
                "company": prospect_data.company,
                "notes": prospect_data.notes,
                "stage": prospect_data.stage,
                "source": source_value,
                "confidence_score": prospect_data.confidence_score,
            }
        )

    organization_id = _resolve_organization_id(current_user)

    # Trigger bulk automated workflows
    if added_prospects:
        enriched_prospects = [
            {
                **prospect,
                "organization_id": organization_id,
            }
            for prospect in added_prospects
        ]
        asyncio.create_task(
            _trigger_bulk_automated_workflows(
                enriched_prospects,
                organization_id,
                current_user["id"],
            )
        )

    logger.info(f"✅ Bulk added {len(added_prospects)} prospects, skipped {len(skipped_prospects)}")

    return {
        "ok": True,
        "added_count": len(added_prospects),
        "skipped_count": len(skipped_prospects),
        "skipped_prospects": skipped_prospects,
        "workflows_triggered": len(added_prospects),
        "message": f"Successfully added {len(added_prospects)} prospects. Automated processing started for all."
    }

async def _trigger_bulk_automated_workflows(
    prospects_data: List[Dict[str, Any]],
    organization_id: int,
    user_id: int
):
    """Background task to trigger bulk automated workflows"""
    try:
        from services.automated_workflow_service import auto_process_prospects_bulk

        workflow_ids = await auto_process_prospects_bulk(
            prospects_data=prospects_data,
            organization_id=organization_id,
            user_id=user_id,
            priority=MessagePriority.NORMAL
        )
        logger.info(f"🚀 Started {len(workflow_ids)} automated workflows for bulk prospects")
    except Exception as e:
        logger.error(f"Failed to trigger bulk automated workflows: {e}")

@router.get("/prospects/automation-status")
async def get_automation_status(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Get automation status for the current organization"""
    try:
        from services.automated_workflow_service import automated_workflow_service

        organization_id = _resolve_organization_id(current_user)
        status = await automated_workflow_service.get_automation_status(
            organization_id=organization_id
        )

        return {
            "ok": True,
            "automation": status
        }
    except Exception as e:
        logger.error(f"Failed to get automation status: {e}")
        return {
            "ok": False,
            "error": str(e),
            "automation": {
                "automation_enabled": False,
                "active_workflows": 0
            }
        }
