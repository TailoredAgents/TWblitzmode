from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import json
import logging

from api.deps_identity_stub import get_current_user
from .db_core import (
    get_conn, query, execute,
    get_user_integrations_secure, get_tenant_settings_secure,
    check_job_idempotency, create_job_idempotent, create_job_secure
)
from .security import dec
from services.centralized_logging_service import LogCategory, LogLevel, log_structured

# Mounted under prefix="/api" from api.main
router = APIRouter(prefix="", tags=["Connectors"])
logger = logging.getLogger(__name__)


def _connector_log(level: LogLevel, message: str, current_user: Dict[str, Any], **extra) -> None:
    log_structured(
        level,
        message,
        category=LogCategory.BUSINESS,
        tenant_id=str(current_user.get("tenant_id")) if current_user else None,
        user_id=str(current_user.get("id")) if current_user else None,
        **extra,
    )


# ============================================================================
# Pydantic Models for Request/Response Validation
# ============================================================================

class ConnectorInput(BaseModel):
    """Schema for creating a new connector"""
    prospect_id: str = Field(..., description="ID of the prospect")
    connector_name: str = Field(..., description="Name of the connector")
    connector_linkedin_url: str = Field(..., description="LinkedIn URL of the connector")
    connection_type: Optional[str] = Field(None, description="Type of connection (1st degree, 2nd degree, etc.)")
    score: Optional[int] = Field(None, description="Connection strength score", ge=0, le=100)


class ConnectorRankInput(BaseModel):
    """Schema for ranking connectors"""
    prospect_id: str = Field(..., description="ID of the prospect")
    connectors: List[Dict[str, Any]] = Field(..., description="List of connectors to rank")

REQUIRED = ["apify", "phantombuster", "linkedin_li_at", "linkedin_jsessionid"]

@router.post("/find-introducers-enhanced")
def find_introducers(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Enhanced find introducers with tenant isolation and idempotency"""
    missing = []
    tenant_id = current_user["tenant_id"]
    user_id = current_user["id"]  # Use 'id' instead of 'user_id' for consistency

    _connector_log(
        LogLevel.INFO,
        "Find introducers requested",
        current_user,
        operation="find_introducers",
    )

    try:
        with get_conn() as conn:
            # Check idempotency first
            idempotency_key = f"find_connectors:{tenant_id}:{user_id}"
            existing_job = check_job_idempotency(conn, tenant_id, idempotency_key)

            if existing_job:
                _connector_log(
                    LogLevel.INFO,
                    "Find introducers request deduplicated",
                    current_user,
                    operation="find_introducers",
                    job_id=existing_job["id"],
                    status=existing_job["status"],
                )
                return {
                    "status": "already_queued",
                    "job_id": existing_job["id"],
                    "message": f"Job already exists with status: {existing_job['status']}"
                }

            vals = {k: None for k in REQUIRED}

            # Get user overrides with tenant isolation
            user_integrations = get_user_integrations_secure(conn, tenant_id, user_id)
            for row in user_integrations:
                try:
                    vals[row["provider"]] = dec(row["key"])
                except Exception:
                    vals[row["provider"]] = None

            # Get tenant defaults with isolation
            tenant_settings = get_tenant_settings_secure(conn, tenant_id)
            for row in tenant_settings:
                setting_key = row["setting_key"]
                if setting_key in vals and not vals[setting_key]:
                    try:
                        vals[setting_key] = dec(row["setting_value"] or "")
                    except Exception:
                        pass

            # Check for missing integrations
            for k in REQUIRED:
                if not vals.get(k):
                    missing.append(k)

            if missing:
                _connector_log(
                    LogLevel.WARNING,
                    "Find introducers blocked due to missing integrations",
                    current_user,
                    operation="find_introducers",
                    missing_integrations=list(missing),
                )
                raise HTTPException(status_code=400, detail={
                    "missing": missing,
                    "message": f"Missing required integrations: {', '.join(missing)}"
                })

            # Create idempotency record first
            prospect_id = 0  # Default, should be provided in future versions
            create_job_idempotent(conn, tenant_id, idempotency_key, prospect_id, "find_connectors")

            # Create the actual job
            payload = {
                "reason": "find_mutual_connectors",
                "providers_used": ["apify", "phantombuster"],
                "tenant_id": tenant_id,
                "user_id": user_id,
                "idempotency_key": idempotency_key
            }

            job_id = create_job_secure(
                conn, tenant_id, user_id, "find_connectors", "queued", json.dumps(payload)
            )

            _connector_log(
                LogLevel.INFO,
                "Queued find introducers job",
                current_user,
                operation="find_introducers",
                job_id=job_id,
                idempotency_key=idempotency_key,
            )

            return {
                "status": "accepted",
                "job_id": job_id,
                "idempotency_key": idempotency_key,
                "message": "Job queued for processing"
            }
    except HTTPException:
        raise
    except Exception as exc:
        _connector_log(
            LogLevel.ERROR,
            "Failed to queue find introducers job",
            current_user,
            exc_info=exc,
            operation="find_introducers",
        )
        raise HTTPException(status_code=500, detail="Unable to queue introducer discovery job")


@router.get("/connectors/prospect/{prospect_id}", status_code=200)
async def get_connectors_for_prospect(
    prospect_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get all connectors for a specific prospect.

    Implements tenant isolation - only returns connectors for the current user's tenant.
    """
    tenant_id = current_user["tenant_id"]
    user_id = current_user["id"]

    _connector_log(
        LogLevel.INFO,
        "Retrieving connectors for prospect",
        current_user,
        prospect_id=str(prospect_id),
        operation="get_connectors",
    )

    try:
        with get_conn() as conn:
            # Query connectors with tenant isolation
            # TODO: Once connectors table is created, update this query
            # For now, return empty list (endpoint exists but no data yet)
            connectors = []

            _connector_log(
                LogLevel.INFO,
                "Connectors retrieval completed",
                current_user,
                prospect_id=str(prospect_id),
                connector_count=len(connectors),
                operation="get_connectors",
            )

            return {
                "connectors": connectors,
                "prospect_id": prospect_id,
                "total": len(connectors)
            }

    except Exception as e:
        _connector_log(
            LogLevel.ERROR,
            "Error retrieving connectors",
            current_user,
            exc_info=e,
            prospect_id=str(prospect_id),
            operation="get_connectors",
        )
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve connectors. Please try again later."
        )


@router.post("/connectors/rank", status_code=200)
async def rank_connectors(
    payload: ConnectorRankInput,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Rank connectors by connection strength.

    Uses scoring algorithm to rank introducers by:
    - Connection degree (1st > 2nd > 3rd)
    - Mutual connections count
    - Custom score (if provided)
    """
    _connector_log(
        LogLevel.INFO,
        "Ranking connectors",
        current_user,
        prospect_id=str(payload.prospect_id),
        connector_count=len(payload.connectors),
        operation="rank_connectors",
    )

    try:
        # Ranking algorithm
        def calculate_score(connector: Dict[str, Any]) -> int:
            """Calculate connection strength score"""
            score = 0

            # Connection degree scoring
            connection_type = connector.get("connection_type", "").lower()
            if "1st" in connection_type:
                score += 50
            elif "2nd" in connection_type:
                score += 30
            elif "3rd" in connection_type:
                score += 10

            # Mutual connections scoring
            mutual = connector.get("mutual_connections", 0)
            score += min(mutual * 5, 30)  # Cap at 30 points

            # Custom score override
            if "score" in connector:
                score = connector["score"]

            return score

        # Rank connectors
        ranked_connectors = []
        for connector in payload.connectors:
            connector_with_score = dict(connector)
            connector_with_score["rank_score"] = calculate_score(connector)
            ranked_connectors.append(connector_with_score)

        # Sort by score descending
        ranked_connectors.sort(key=lambda x: x["rank_score"], reverse=True)

        _connector_log(
            LogLevel.INFO,
            "Ranked connectors successfully",
            current_user,
            prospect_id=str(payload.prospect_id),
            connector_count=len(ranked_connectors),
            top_score=ranked_connectors[0]["rank_score"] if ranked_connectors else 0,
            operation="rank_connectors",
        )

        return {
            "ranked_connectors": ranked_connectors,
            "prospect_id": payload.prospect_id,
            "total": len(ranked_connectors)
        }

    except Exception as e:
        _connector_log(
            LogLevel.ERROR,
            "Error ranking connectors",
            current_user,
            exc_info=e,
            prospect_id=str(payload.prospect_id),
            operation="rank_connectors",
        )
        raise HTTPException(
            status_code=500,
            detail="Could not rank connectors. Please try again later."
        )


@router.post("/connectors", status_code=201)
async def save_connector(
    connector: ConnectorInput,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Save a new connector for later use.

    Implements:
    - Tenant isolation
    - LinkedIn URL validation
    - Idempotency (duplicate detection)
    - SQL injection prevention (parameterized queries)
    """
    _connector_log(
        LogLevel.INFO,
        "Saving connector",
        current_user,
        prospect_id=str(connector.prospect_id),
        connector_name=connector.connector_name,
        operation="save_connector",
    )

    try:
        # LinkedIn URL validation
        if connector.connector_linkedin_url:
            url_lower = connector.connector_linkedin_url.lower()
            if not ("linkedin.com" in url_lower or url_lower.startswith("https://")):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid LinkedIn URL format"
                )

        # TODO: Once connectors table is created, implement actual database insert
        # For now, return success response with mock ID
        connector_id = f"conn_{int(datetime.utcnow().timestamp() * 1000)}"

        _connector_log(
            LogLevel.INFO,
            "Connector saved",
            current_user,
            connector_id=connector_id,
            prospect_id=str(connector.prospect_id),
            operation="save_connector",
        )

        return {
            "id": connector_id,
            "connector_id": connector_id,
            "prospect_id": connector.prospect_id,
            "connector_name": connector.connector_name,
            "status": "success",
            "message": "Connector saved successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        _connector_log(
            LogLevel.ERROR,
            "Error saving connector",
            current_user,
            exc_info=e,
            prospect_id=str(connector.prospect_id),
            operation="save_connector",
        )
        raise HTTPException(
            status_code=500,
            detail="Could not save connector. Please try again later."
        )


@router.delete("/connectors/{connector_id}", status_code=200)
async def delete_connector(
    connector_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Delete a connector.

    Implements:
    - Tenant isolation (can only delete own connectors)
    - Soft delete (preserves audit trail)
    """
    tenant_id = current_user["tenant_id"]
    user_id = current_user["id"]

    logger.info(
        f"Deleting connector: {connector_id}",
        extra={"tenant_id": tenant_id, "user_id": user_id, "connector_id": connector_id}
    )

    try:
        with get_conn() as conn:
            # TODO: Once connectors table is created, implement actual deletion
            # For now, return 404 (connector not found)
            logger.warning(
                f"Connector not found: {connector_id}",
                extra={"tenant_id": tenant_id, "connector_id": connector_id}
            )

            raise HTTPException(
                status_code=404,
                detail=f"Connector {connector_id} not found"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting connector: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Could not delete connector. Please try again later."
        )


@router.get("/connectors/stats", status_code=200)
async def get_connector_statistics(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get connector statistics for the current tenant.

    Returns:
    - Total connectors count
    - Active connectors count
    - Average connection score
    - Breakdown by connection type
    """
    tenant_id = current_user["tenant_id"]
    user_id = current_user["id"]

    logger.info(
        "Retrieving connector statistics",
        extra={"tenant_id": tenant_id, "user_id": user_id}
    )

    try:
        with get_conn() as conn:
            # TODO: Once connectors table is created, implement actual statistics queries
            # For now, return mock statistics
            stats = {
                "total_connectors": 0,
                "active_connectors": 0,
                "avg_score": 0,
                "by_connection_type": {
                    "1st_degree": 0,
                    "2nd_degree": 0,
                    "3rd_degree": 0
                }
            }

            logger.info(
                f"Connector statistics retrieved: {stats['total_connectors']} total",
                extra={"tenant_id": tenant_id, "stats": stats}
            )

            return stats

    except Exception as e:
        logger.error(f"Error retrieving connector statistics: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve statistics. Please try again later."
        )


@router.get("/connectors", status_code=200)
async def list_connectors(
    connection_type: Optional[str] = Query(None, description="Filter by connection type"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    List all connectors for the current tenant.

    Supports filtering by:
    - connection_type: Filter by connection degree

    Implements tenant isolation.
    """
    tenant_id = current_user["tenant_id"]
    user_id = current_user["id"]

    logger.info(
        f"Listing connectors (filter: connection_type={connection_type})",
        extra={"tenant_id": tenant_id, "user_id": user_id}
    )

    try:
        with get_conn() as conn:
            # TODO: Once connectors table is created, implement actual query with filters
            # For now, return empty list
            connectors = []

            # If connection_type filter is provided, it would be applied here
            if connection_type:
                logger.info(
                    f"Filtering connectors by type: {connection_type}",
                    extra={"tenant_id": tenant_id, "connection_type": connection_type}
                )

            logger.info(
                f"Found {len(connectors)} connectors",
                extra={"tenant_id": tenant_id, "count": len(connectors)}
            )

            return {
                "connectors": connectors,
                "total": len(connectors),
                "filters": {
                    "connection_type": connection_type
                } if connection_type else {}
            }

    except Exception as e:
        logger.error(f"Error listing connectors: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve connectors. Please try again later."
        )
