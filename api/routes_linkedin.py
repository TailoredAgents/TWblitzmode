# api/routes_linkedin.py
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from .mt_db import get_db
from .security import enc, dec
from .deps import get_current_user
from services.linkedin_service import linkedin_service, LinkedInCampaignRequest
from services.linkedin_cookie_verifier import verify_linkedin_cookies, VerificationStatus

router = APIRouter(prefix="/api/integrations/linkedin", tags=["linkedin"])

class CookieUpsert(BaseModel):
    label: Optional[str] = None
    li_at: str
    jsessionid: Optional[str] = None
    user_agent: Optional[str] = None
    proxy_url: Optional[str] = None

class CookieVerificationRequest(BaseModel):
    li_at: str
    jsessionid: str
    label: Optional[str] = None

class CookieVerificationResponse(BaseModel):
    success: bool
    status: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    profile_url: Optional[str] = None
    error_message: Optional[str] = None

def _tenant_id_from_request(request: Request) -> int:
    # Expect your auth to set x-tenant-id or include tenant_id in JWT injected by auth middleware
    # Fallback: header for now (Claude can wire JWT decode here if needed)
    hdr = request.headers.get("x-tenant-id")
    if hdr and hdr.isdigit():
        return int(hdr)
    # As a safe fallback for now, use 1 (admin tenant). Claude: replace with real JWT decode.
    return 1

def _user_id_from_request(request: Request) -> int:
    # Extract user_id from JWT token injected by auth middleware
    # Fallback to header for compatibility
    hdr = request.headers.get("x-user-id")
    if hdr and hdr.isdigit():
        return int(hdr)
    # Safe fallback for now, use 1 (admin user)
    return 1

@router.post("/cookies")
def upsert_cookie(body: CookieUpsert, current_user: dict = Depends(get_current_user)):
    tid = current_user["tenant_id"]
    uid = current_user["id"]
    conn = get_db()
    cursor = conn.cursor()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO linkedin_sessions(tenant_id,user_id,label,li_at_encrypted,jsessionid_encrypted,user_agent,proxy_url,is_active,last_verified_at)
               VALUES(?,?,?,?,?,?,?,1,NULL)""",
            (tid, uid, body.label, enc(body.li_at), enc(body.jsessionid) if body.jsessionid else None, body.user_agent, body.proxy_url)
        )
        conn.commit()
        return {"status": "ok"}

    finally:
        try:
            cursor.close()
        except Exception:
            pass  # Cursor might already be closed
@router.get("/cookies")
def list_cookies(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    tenant_id = current_user["tenant_id"]
    conn = get_db()
    cursor = conn.cursor()
    try:
        cur = conn.execute(
            "SELECT id,label,is_active,last_verified_at,created_at FROM linkedin_sessions WHERE user_id=? AND tenant_id=? ORDER BY id DESC",
            (uid, tenant_id)
        )
        rows = [dict(row) for row in cur.fetchall()]
        return {"items": rows}

    finally:
        try:
            cursor.close()
        except Exception:
            pass  # Cursor might already be closed
@router.post("/cookies/{cookie_id}/activate")
def activate_cookie(cookie_id: int, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    tenant_id = current_user["tenant_id"]
    conn = get_db()
    cursor = conn.cursor()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE linkedin_sessions SET is_active=0 WHERE user_id=? AND tenant_id=?", (uid, tenant_id))
        cur.execute("UPDATE linkedin_sessions SET is_active=1 WHERE id=? AND user_id=? AND tenant_id=?", (cookie_id, uid, tenant_id))
        conn.commit()
        return {"status": "ok"}

    finally:
        try:
            cursor.close()
        except Exception:
            pass  # Cursor might already be closed
@router.post("/verify-cookie", response_model=CookieVerificationResponse)
async def verify_cookie(
    data: CookieVerificationRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Verify LinkedIn cookies and extract user profile information

    This endpoint validates LinkedIn li_at and jsessionid cookies by performing
    a stealth login and extracting the user's profile information including
    username and full name.
    """
    try:
        tenant_id = current_user["tenant_id"]
        user_id = current_user["id"]

        # Perform cookie verification
        result = await verify_linkedin_cookies(
            li_at=data.li_at,
            jsessionid=data.jsessionid,
            tenant_id=tenant_id,
            user_id=user_id
        )

        # If verification successful, save/update the session in database
        if result.status == VerificationStatus.VALID:
            conn = get_db()
            cursor = conn.cursor()
            try:
                cur = conn.cursor()

                # Check if user already has a session
                cur.execute(
                    "SELECT id FROM linkedin_sessions WHERE user_id=? AND tenant_id=?",
                    (user_id, tenant_id)
                )
                existing_session = cur.fetchone()

                if existing_session:
                    # Update existing session
                    cur.execute(
                        """UPDATE linkedin_sessions
                           SET li_at_encrypted=?, jsessionid_encrypted=?,
                               username=?, full_name=?, is_active=1,
                               last_verified_at=?, label=?
                           WHERE user_id=? AND tenant_id=?""",
                        (
                            enc(data.li_at),
                            enc(data.jsessionid),
                            result.username,
                            result.full_name,
                            datetime.utcnow(),
                            data.label or result.full_name,
                            user_id,
                            tenant_id
                        )
                    )
                else:
                    # Create new session
                    cur.execute(
                        """INSERT INTO linkedin_sessions
                           (tenant_id, user_id, label, li_at_encrypted, jsessionid_encrypted,
                            username, full_name, is_active, last_verified_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                        (
                            tenant_id,
                            user_id,
                            data.label or result.full_name,
                            enc(data.li_at),
                            enc(data.jsessionid),
                            result.username,
                            result.full_name,
                            datetime.utcnow()
                        )
                    )

                conn.commit()

            finally:
                try:
                    cursor.close()
                except Exception:
                    pass  # Cursor might already be closed
        return CookieVerificationResponse(
            success=result.status == VerificationStatus.VALID,
            status=result.status.value,
            username=result.username,
            full_name=result.full_name,
            profile_url=result.profile_url,
            error_message=result.error_message
        )

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Cookie verification failed: {str(e)}"
        )

# LinkedIn Campaign Management Endpoints

class LinkedInCampaignCreate(BaseModel):
    prospect_id: int
    introducer_ids: List[int]
    message_type: str = "direct_introduction"
    delay_between_messages: int = 180
    send_connection_requests: bool = False
    scheduled_for: Optional[datetime] = None
    custom_message_context: Optional[str] = None

class LinkedInCampaignResponse(BaseModel):
    campaign_id: int
    status: str
    total_recipients: int
    messages_sent: int
    messages_failed: int
    total_cost: float
    phantom_container_id: str
    estimated_completion: Optional[datetime] = None

@router.post("/campaigns", response_model=LinkedInCampaignResponse)
async def create_linkedin_campaign(campaign_data: LinkedInCampaignCreate, request: Request):
    """Create a new LinkedIn messaging campaign"""
    try:
        tenant_id = _tenant_id_from_request(request)
        user_id = request.state.user.id if hasattr(request.state, 'user') else 1
        
        # Create campaign request
        campaign_request = LinkedInCampaignRequest(
            prospect_id=campaign_data.prospect_id,
            introducer_ids=campaign_data.introducer_ids,
            message_type=campaign_data.message_type,
            delay_between_messages=campaign_data.delay_between_messages,
            send_connection_requests=campaign_data.send_connection_requests,
            scheduled_for=campaign_data.scheduled_for,
            custom_message_context=campaign_data.custom_message_context
        )
        
        # Create campaign
        result = await linkedin_service.create_linkedin_campaign(
            request=campaign_request,
            tenant_id=tenant_id,
            user_id=user_id
        )
        
        return LinkedInCampaignResponse(**result.__dict__)
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/campaigns/{campaign_id}/launch", response_model=LinkedInCampaignResponse)
async def launch_linkedin_campaign(campaign_id: int, request: Request):
    """Launch a drafted LinkedIn campaign"""
    try:
        tenant_id = _tenant_id_from_request(request)
        
        result = await linkedin_service.launch_linkedin_campaign(
            campaign_id=campaign_id,
            tenant_id=tenant_id
        )
        
        return LinkedInCampaignResponse(**result.__dict__)
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/campaigns/{campaign_id}/status")
async def get_campaign_status(campaign_id: int, request: Request):
    """Get LinkedIn campaign status"""
    try:
        tenant_id = _tenant_id_from_request(request)
        
        status = await linkedin_service.get_campaign_status(
            campaign_id=campaign_id,
            tenant_id=tenant_id
        )
        
        return status
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/campaigns/{campaign_id}/stop")
async def stop_linkedin_campaign(campaign_id: int, request: Request):
    """Stop a running LinkedIn campaign"""
    try:
        tenant_id = _tenant_id_from_request(request)
        
        result = await linkedin_service.stop_campaign(
            campaign_id=campaign_id,
            tenant_id=tenant_id
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/campaigns")
async def list_linkedin_campaigns(request: Request):
    """List LinkedIn campaigns for tenant"""
    try:
        tenant_id = _tenant_id_from_request(request)
        
        conn = get_db()
        cursor = conn.cursor()
        try:
            
            cursor.execute("""
                SELECT c.*, p.full_name as prospect_name
                FROM linkedin_campaigns c
                JOIN prospects p ON c.prospect_id = p.id
                WHERE c.tenant_id = %s
                ORDER BY c.created_at DESC
            """, (tenant_id,))
            
            campaigns = cursor.fetchall()
            
            return {"campaigns": [dict(campaign) for campaign in campaigns]}
            
        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/usage/daily")
async def get_daily_usage(request: Request):
    """Get daily LinkedIn usage statistics"""
    try:
        tenant_id = _tenant_id_from_request(request)
        
        usage = await linkedin_service.get_daily_linkedin_usage(tenant_id)
        
        return usage
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/test")
async def test_phantombuster_connection(request: Request):
    """Test PhantomBuster connection and LinkedIn session"""
    try:
        from integrations.phantombuster_linkedin_client import get_phantombuster_linkedin_client
        
        tenant_id = _tenant_id_from_request(request)
        
        client = get_phantombuster_linkedin_client(tenant_id)
        result = await client.test_connection()
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
