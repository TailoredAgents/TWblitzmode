"""
Phase 2: Enhanced Multi-Tenant Email API Routes
Provides subuser management and domain authentication endpoints
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

from api.database import get_db
from api.deps import get_current_user
from integrations.sendgrid_multi_tenant_client import get_enhanced_sendgrid_client

router = APIRouter(prefix="/api/email-mt", tags=["Multi-Tenant Email"])

# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class CreateSubuserRequest(BaseModel):
    tenant_name: str
    tenant_email: str
    
    @field_validator('tenant_email')
    def validate_email(cls, v: str) -> str:
        if '@' not in v:
            raise ValueError('Invalid email address')
        return v

class SetupDomainRequest(BaseModel):
    domain: str
    
    @field_validator('domain')
    def validate_domain(cls, v: str) -> str:
        if '.' not in v or ' ' in v:
            raise ValueError('Invalid domain format')
        return v

class SendTenantEmailRequest(BaseModel):
    to_email: str
    subject: str
    body_html: str
    body_text: Optional[str] = None
    from_name: Optional[str] = "VouchLink AI AI Assistant"

class SubuserResponse(BaseModel):
    success: bool
    subuser_username: Optional[str] = None
    message: str
    created_at: Optional[datetime] = None

class DomainAuthResponse(BaseModel):
    success: bool
    domain: str
    dns_records: Optional[List[Dict[str, str]]] = None
    verification_status: str
    message: str
    instructions: Optional[str] = None

class TenantEmailStatsResponse(BaseModel):
    tenant_id: int
    emails_sent_today: int
    emails_sent_this_month: int
    bounce_rate: float
    open_rate: float
    daily_limit: int
    monthly_limit: int

# ============================================
# SUBUSER MANAGEMENT ENDPOINTS
# ============================================

@router.post("/subuser/create", response_model=SubuserResponse)
async def create_tenant_subuser(
    request: CreateSubuserRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a dedicated SendGrid subuser for the current tenant
    
    This provides complete email isolation - separate API keys, 
    statistics, and reputation management.
    """
    tenant_id = current_user["tenant_id"]
    
    # Check if tenant already has a subuser
    existing_subuser = await _get_existing_subuser(tenant_id)
    if existing_subuser:
        raise HTTPException(
            status_code=400,
            detail=f"Tenant already has subuser: {existing_subuser}"
        )
    
    # Create subuser
    enhanced_client = get_enhanced_sendgrid_client()
    result = await enhanced_client.create_tenant_subuser(
        tenant_id=tenant_id,
        tenant_name=request.tenant_name,
        tenant_email=request.tenant_email
    )
    
    if result.success:
        return SubuserResponse(
            success=True,
            subuser_username=result.subuser_username,
            message="Subuser created successfully! You now have isolated email sending.",
            created_at=datetime.now()
        )
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create subuser: {result.error_message}"
        )

@router.get("/subuser/status", response_model=Dict[str, Any])
async def get_subuser_status(current_user: dict = Depends(get_current_user)):
    """Get current tenant's subuser status and details"""
    tenant_id = current_user["tenant_id"]
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT subuser_username, status, subuser_created_at, 
               monthly_email_limit, current_month_sent, reputation_score
        FROM tenant_sendgrid_subusers
        WHERE tenant_id = %s
    """, (tenant_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            "has_subuser": True,
            "subuser_username": result["subuser_username"],
            "status": result["status"],
            "created_at": result["subuser_created_at"],
            "monthly_limit": result["monthly_email_limit"],
            "emails_sent_this_month": result["current_month_sent"],
            "reputation_score": float(result["reputation_score"]) if result["reputation_score"] else None
        }
    else:
        return {
            "has_subuser": False,
            "message": "No dedicated subuser found. Create one for better email isolation."
        }

# ============================================
# DOMAIN AUTHENTICATION ENDPOINTS  
# ============================================

@router.post("/domain/setup", response_model=DomainAuthResponse)
async def setup_domain_authentication(
    request: SetupDomainRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Set up domain authentication for professional email sending
    
    This allows emails to be sent from @yourdomain.com instead of 
    showing "via sendgrid.net" which improves deliverability.
    """
    tenant_id = current_user["tenant_id"]
    
    # Check if tenant has subuser
    if not await _get_existing_subuser(tenant_id):
        raise HTTPException(
            status_code=400,
            detail="Please create a subuser first before setting up domain authentication"
        )
    
    # Setup domain authentication
    enhanced_client = get_enhanced_sendgrid_client()
    result = await enhanced_client.setup_domain_authentication(
        tenant_id=tenant_id,
        domain=request.domain
    )
    
    if result.success:
        instructions = f"""
        To complete domain authentication for {request.domain}:

        1. Log into your domain DNS provider (e.g., GoDaddy, Cloudflare, Route53)
        2. Add the following DNS records:
        
        {_format_dns_instructions(result.dns_records)}
        
        3. Wait 24-48 hours for DNS propagation
        4. Use the verification endpoint to check status
        
        Once verified, emails will be sent from your custom domain!
        """
        
        return DomainAuthResponse(
            success=True,
            domain=request.domain,
            dns_records=result.dns_records,
            verification_status="pending",
            message="Domain authentication setup initiated",
            instructions=instructions
        )
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to setup domain authentication: {result.error_message}"
        )

@router.post("/domain/verify/{domain}")
async def verify_domain_authentication(
    domain: str,
    current_user: dict = Depends(get_current_user)
):
    """Check if domain authentication DNS records have been configured correctly"""
    tenant_id = current_user["tenant_id"]
    
    enhanced_client = get_enhanced_sendgrid_client()
    result = await enhanced_client.verify_domain_authentication(
        tenant_id=tenant_id,
        domain=domain
    )
    
    if result.success:
        status_message = {
            "verified": "✅ Domain authentication verified! Emails will now be sent from your custom domain.",
            "pending": "⏳ DNS records not yet propagated. Please wait 24-48 hours and try again.",
            "failed": "❌ DNS records not configured correctly. Please check your DNS settings."
        }
        
        return {
            "success": True,
            "domain": domain,
            "status": result.verification_status,
            "message": status_message.get(result.verification_status, "Unknown status"),
            "is_verified": result.verification_status == "verified"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify domain: {result.error_message}"
        )

@router.get("/domain/list")
async def list_tenant_domains(current_user: dict = Depends(get_current_user)):
    """Get list of domains configured for this tenant"""
    tenant_id = current_user["tenant_id"]
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT domain, auth_status, verified_at, created_at
        FROM tenant_domain_authentication
        WHERE tenant_id = %s
        ORDER BY created_at DESC
    """, (tenant_id,))
    
    domains = []
    for row in cursor.fetchall():
        domains.append({
            "domain": row["domain"],
            "status": row["auth_status"],
            "verified_at": row["verified_at"],
            "created_at": row["created_at"],
            "is_verified": row["auth_status"] == "verified"
        })
    
    conn.close()
    
    return {"domains": domains}

# ============================================
# ENHANCED EMAIL SENDING
# ============================================

@router.post("/send")
async def send_tenant_email(
    request: SendTenantEmailRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Send email using tenant's dedicated subuser for better deliverability
    
    This uses the tenant's isolated SendGrid account and authenticated domain
    for professional email sending with improved inbox delivery rates.
    """
    tenant_id = current_user["tenant_id"]
    
    # Check daily limits
    if not await _check_sending_limits(tenant_id):
        raise HTTPException(
            status_code=429,
            detail="Daily email sending limit reached. Upgrade your plan for higher limits."
        )
    
    # Send email
    enhanced_client = get_enhanced_sendgrid_client()
    result = await enhanced_client.send_email_for_tenant(
        tenant_id=tenant_id,
        to_email=request.to_email,
        subject=request.subject,
        body_html=request.body_html,
        body_text=request.body_text or request.body_html,  # Fallback to HTML
        from_name=request.from_name
    )
    
    if result["success"]:
        return {
            "success": True,
            "message_id": result.get("message_id"),
            "message": "Email sent successfully using your dedicated email infrastructure"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send email: {result['error']}"
        )

# ============================================
# ANALYTICS AND STATS
# ============================================

@router.get("/stats", response_model=TenantEmailStatsResponse)
async def get_tenant_email_stats(current_user: dict = Depends(get_current_user)):
    """Get detailed email statistics for this tenant"""
    tenant_id = current_user["tenant_id"]
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get today's stats
    cursor.execute("""
        SELECT COUNT(*) as emails_today
        FROM tenant_email_logs
        WHERE tenant_id = %s AND DATE(sent_at) = CURRENT_DATE
    """, (tenant_id,))
    emails_today = cursor.fetchone()["emails_today"]
    
    # Get this month's stats
    cursor.execute("""
        SELECT COUNT(*) as emails_month,
               AVG(CASE WHEN status IN ('bounced', 'dropped') THEN 1.0 ELSE 0.0 END) as bounce_rate,
               AVG(CASE WHEN status = 'opened' THEN 1.0 ELSE 0.0 END) as open_rate
        FROM tenant_email_logs
        WHERE tenant_id = %s 
        AND DATE_TRUNC('month', sent_at) = DATE_TRUNC('month', CURRENT_DATE)
    """, (tenant_id,))
    month_stats = cursor.fetchone()
    
    # Get limits
    cursor.execute("""
        SELECT daily_email_limit, monthly_email_limit
        FROM tenant_email_plans
        WHERE tenant_id = %s
    """, (tenant_id,))
    limits = cursor.fetchone()
    
    conn.close()
    
    return TenantEmailStatsResponse(
        tenant_id=tenant_id,
        emails_sent_today=emails_today,
        emails_sent_this_month=month_stats["emails_month"] or 0,
        bounce_rate=float(month_stats["bounce_rate"] or 0) * 100,
        open_rate=float(month_stats["open_rate"] or 0) * 100,
        daily_limit=limits["daily_email_limit"] if limits else 50,
        monthly_limit=limits["monthly_email_limit"] if limits else 1000
    )

# ============================================
# HELPER FUNCTIONS
# ============================================

async def _get_existing_subuser(tenant_id: int) -> Optional[str]:
    """Check if tenant already has a subuser"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT subuser_username
        FROM tenant_sendgrid_subusers
        WHERE tenant_id = %s
    """, (tenant_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result["subuser_username"] if result else None

async def _check_sending_limits(tenant_id: int) -> bool:
    """Check if tenant can send more emails today"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get daily limit and today's sent count
    cursor.execute("""
        SELECT tep.daily_email_limit,
               COALESCE(daily_sent.count, 0) as sent_today
        FROM tenant_email_plans tep
        LEFT JOIN (
            SELECT COUNT(*) as count
            FROM tenant_email_logs
            WHERE tenant_id = %s AND DATE(sent_at) = CURRENT_DATE
        ) daily_sent ON true
        WHERE tep.tenant_id = %s
    """, (tenant_id, tenant_id))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        # Default limit if no plan configured
        return True
    
    return result["sent_today"] < result["daily_email_limit"]

def _format_dns_instructions(dns_records: List[Dict[str, str]]) -> str:
    """Format DNS records into human-readable instructions"""
    if not dns_records:
        return "No DNS records provided"
    
    instructions = []
    for i, record in enumerate(dns_records, 1):
        instructions.append(f"""
        Record {i}:
        Type: {record.get('type', 'CNAME')}
        Name: {record.get('name', '')}
        Value: {record.get('value', '')}
        TTL: {record.get('ttl', '300')} (or leave default)
        """)
    
    return "\n".join(instructions)
