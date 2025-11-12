from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from .deps import get_current_user
from .db_core import get_conn, query, execute

router = APIRouter()

class IntroductionIn(BaseModel):
    prospect_id: int
    team_member_id: int
    introduction_message: Optional[str] = None

@router.get("/introductions")
def list_introductions(current_user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Get all introductions for the current user's tenant"""
    with get_conn() as conn:
        # Check if the introductions table exists
        try:
            # This is a safe query that will work with your existing data structure
            # Adjust table/column names based on your actual schema
            rows = query(conn, """
                SELECT 
                    id, prospect_id, status, created_at,
                    introduction_message, team_member_name, team_member_email
                FROM introductions 
                WHERE tenant_id = ? 
                ORDER BY created_at DESC
            """, (current_user["tenant_id"],))
            
            return [dict(zip([
                "id", "prospect_id", "status", "created_date",
                "introduction_message", "team_member_name", "team_member_email"
            ], r)) for r in rows]
            
        except Exception:
            # If introductions table doesn't exist, return empty list
            return []

@router.post("/introductions/bulk-update")
def bulk_update_introductions(
    body: dict, 
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Bulk update introduction statuses"""
    ids = body.get("ids", [])
    status = body.get("status")
    
    if not ids or not status:
        raise HTTPException(400, "ids and status are required")
    
    with get_conn() as conn:
        try:
            # Update only introductions that belong to this tenant
            placeholders = ",".join("?" * len(ids))
            execute(conn, f"""
                UPDATE introductions 
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders}) AND tenant_id = ?
            """, [status] + ids + [current_user["tenant_id"]])
            
            return {"success": True, "updated": len(ids)}
        except Exception as e:
            raise HTTPException(500, f"Failed to update introductions: {str(e)}")

@router.post("/create-introduction")
def create_introduction(
    body: IntroductionIn,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Create a new introduction"""
    with get_conn() as conn:
        try:
            execute(conn, """
                INSERT INTO introductions (
                    tenant_id, user_id, prospect_id, team_member_id, 
                    introduction_message, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'draft', CURRENT_TIMESTAMP)
            """, (
                current_user["tenant_id"], current_user["id"],
                body.prospect_id, body.team_member_id, 
                body.introduction_message
            ))
            return {"success": True}
        except Exception as e:
            raise HTTPException(500, f"Failed to create introduction: {str(e)}")