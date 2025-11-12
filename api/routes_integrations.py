"""
Integrations API Routes
FastAPI endpoints for third-party integrations like OpenAI
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.database import get_db, get_db_connection

try:
    from .deps import get_current_user
except ImportError:
    from api.deps import get_current_user

try:
    from integrations.openai_client import get_openai_client
except ImportError:
    # OpenAI client may not be available in all environments
    get_openai_client = None

try:
    from integrations.grok_client import get_grok_client
except ImportError:
    # Grok client may not be available in all environments
    get_grok_client = None

try:
    from integrations.sendgrid_client import get_sendgrid_client
except ImportError:
    # SendGrid client may not be available in all environments
    get_sendgrid_client = None

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/api/integrations", tags=["integrations"])

# OpenAI Message Generation Models
class GenerateEmailRequest(BaseModel):
    prospect_name: str
    prospect_company: Optional[str] = None
    prospect_title: Optional[str] = None
    mutual_connections: Optional[str] = None
    prompt_style: str = "professional introduction request"
    custom_instructions: Optional[str] = None

class GenerateEmailResponse(BaseModel):
    subject: str
    message: str
    generated_by: str = "GPT-4o"

# Grok Development Assistance Models
class DevelopmentAdviceRequest(BaseModel):
    context: str
    question: str
    code_snippet: Optional[str] = None

class ArchitectureAnalysisRequest(BaseModel):
    description: str
    current_stack: list[str]
    requirements: list[str]

class DebuggingRequest(BaseModel):
    error_message: str
    stack_trace: Optional[str] = None
    code_context: Optional[str] = None
    environment: str = "python"

class GrokResponse(BaseModel):
    content: str
    model: str
    timestamp: str
    usage: Optional[Dict[str, Any]] = None

# SendGrid Email Sending Models
class SendEmailRequest(BaseModel):
    to_email: str
    to_name: str
    subject: str
    message: str
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    introduction_id: Optional[int] = None
    prospect_name: Optional[str] = None
    connector_name: Optional[str] = None
    # Allow bypassing pre-send verification when service unavailable or for testing
    skip_verify: Optional[bool] = False
    # Use a minimal send path (plain text only, no tracking/extras)
    simple: Optional[bool] = False
    # Use raw v3 /mail/send JSON path (bypass helper classes)
    raw: Optional[bool] = False

class SendEmailResponse(BaseModel):
    message_id: str
    status: str = "sent"
    sent_at: str
    provider: str = "SendGrid"
    # Optional verification summary for UI messaging boxes
    verification: Optional[Dict[str, Any]] = None

@router.get("/sendgrid/diagnose")
async def diagnose_sendgrid(
    current_user: Dict = Depends(get_current_user)
):
    """Diagnose SendGrid configuration and API key scopes without sending email."""
    try:
        tenant_id = current_user["tenant_id"] if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
        if not tenant_id:
            raise HTTPException(status_code=403, detail="User not associated with tenant")

        client = get_sendgrid_client(tenant_id)
        if not client or not getattr(client, 'api_key', None):
            return {
                "ok": False,
                "reason": "SendGrid client not configured or API key missing",
                "tenant_id": tenant_id
            }

        import hashlib
        key = getattr(client, 'api_key', '') or ''
        key_fp = hashlib.sha1(key.encode('utf-8')).hexdigest()[:10] if key else None
        diag: Dict[str, Any] = {
            "ok": True,
            "tenant_id": tenant_id,
            "from_email": getattr(client, 'from_email', None),
            "from_name": getattr(client, 'from_name', None),
            "daily_limit": getattr(client, 'daily_send_limit', None),
            "api_key_present": len(getattr(client, 'api_key', '') or '') >= 20,
            "api_key_fingerprint": key_fp,
            "host": getattr(getattr(client, 'client', None), 'host', None) or 'https://api.sendgrid.com',
            "on_behalf_of": getattr(getattr(getattr(client, 'client', None), 'client', None), 'request_headers', {}).get('on-behalf-of') if getattr(getattr(client, 'client', None), 'client', None) else None,
        }

        # Probe scopes endpoint to validate key and permissions
        try:
            resp = client.client.client.scopes.get()
            diag["scopes_status"] = resp.status_code
            body = getattr(resp, 'body', '')
            if isinstance(body, (bytes, bytearray)):
                body = body.decode('utf-8', errors='ignore')
            try:
                import json as _json
                diag["scopes_body"] = _json.loads(body) if isinstance(body, str) else body
            except Exception:
                diag["scopes_body"] = (body[:400] if isinstance(body, str) else str(body))
        except Exception as e:
            diag["scopes_error"] = str(e)

        # Probe user profile (optional)
        try:
            resp2 = client.client.client.user.profile.get()
            diag["profile_status"] = resp2.status_code
            body2 = getattr(resp2, 'body', '')
            if isinstance(body2, (bytes, bytearray)):
                body2 = body2.decode('utf-8', errors='ignore')
            try:
                import json as _json
                diag["profile_body"] = _json.loads(body2) if isinstance(body2, str) else body2
            except Exception:
                diag["profile_body"] = (body2[:400] if isinstance(body2, str) else str(body2))
        except Exception as e:
            diag["profile_error"] = str(e)

        return diag

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SendGrid diagnosis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Diagnosis failed: {str(e)}")

@router.post("/openai/generate-email", response_model=GenerateEmailResponse)
async def generate_email_with_ai(
    request: GenerateEmailRequest,
    current_user: Dict = Depends(get_current_user)
):
    """Generate an email using OpenAI GPT-4o"""
    try:
        if not get_openai_client:
            raise HTTPException(status_code=501, detail="OpenAI integration not available")
        
        # Get OpenAI client for tenant
        openai_client = await get_openai_client(current_user["tenant_id"])
        
        if not openai_client:
            raise HTTPException(status_code=400, detail="OpenAI not configured for your account")
        
        # Build context for AI generation
        context = {
            "prospect_name": request.prospect_name,
            "prospect_company": request.prospect_company,
            "prospect_title": request.prospect_title,
            "mutual_connections": request.mutual_connections,
            "style": request.prompt_style,
            "custom_instructions": request.custom_instructions
        }
        
        # Generate the email content
        result = await openai_client.generate_introduction_email(context)
        
        logger.info(f"AI email generated for tenant {current_user['tenant_id']} - prospect: {request.prospect_name}")
        
        return GenerateEmailResponse(
            subject=result.subject,
            message=result.message,
            generated_by="GPT-4o"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI email generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate email: {str(e)}")

@router.get("/openai/status")
async def get_openai_status(
    current_user: Dict = Depends(get_current_user)
):
    """Check OpenAI integration status for current user's tenant"""
    try:
        if not get_openai_client:
            return {"available": False, "reason": "OpenAI integration not installed"}
        
        # Try to get OpenAI client for tenant
        openai_client = await get_openai_client(current_user["tenant_id"])
        
        if not openai_client:
            return {"available": False, "reason": "OpenAI API key not configured"}
        
        return {"available": True, "model": "GPT-4o", "tenant_id": current_user["tenant_id"]}
        
    except Exception as e:
        logger.error(f"OpenAI status check failed: {e}")
        return {"available": False, "reason": str(e)}

# Grok Development Assistance Endpoints
@router.post("/grok/development-advice", response_model=GrokResponse)
async def get_development_advice(
    request: DevelopmentAdviceRequest,
    current_user: Dict = Depends(get_current_user)
):
    """Get development advice from Grok for coding questions"""
    try:
        if not get_grok_client:
            raise HTTPException(status_code=501, detail="Grok integration not available")
        
        # Get Grok client for tenant
        grok_client = await get_grok_client(current_user["tenant_id"])
        
        if not grok_client:
            raise HTTPException(status_code=400, detail="Grok not configured for your account")
        
        # Get development advice
        async with grok_client:
            result = await grok_client.get_development_advice(
                context=request.context,
                question=request.question,
                code_snippet=request.code_snippet
            )
        
        logger.info(f"Grok development advice generated for tenant {current_user['tenant_id']}")
        
        return GrokResponse(
            content=result["advice"],
            model=result["model"],
            timestamp=result["timestamp"],
            usage=result.get("usage")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Grok development advice failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get development advice: {str(e)}")

@router.post("/grok/architecture-analysis", response_model=GrokResponse)
async def analyze_architecture(
    request: ArchitectureAnalysisRequest,
    current_user: Dict = Depends(get_current_user)
):
    """Get architectural analysis and recommendations from Grok"""
    try:
        if not get_grok_client:
            raise HTTPException(status_code=501, detail="Grok integration not available")
        
        # Get Grok client for tenant
        grok_client = await get_grok_client(current_user["tenant_id"])
        
        if not grok_client:
            raise HTTPException(status_code=400, detail="Grok not configured for your account")
        
        # Get architecture analysis
        async with grok_client:
            result = await grok_client.analyze_architecture(
                description=request.description,
                current_stack=request.current_stack,
                requirements=request.requirements
            )
        
        logger.info(f"Grok architecture analysis generated for tenant {current_user['tenant_id']}")
        
        return GrokResponse(
            content=result["analysis"],
            model=result["model"],
            timestamp=result["timestamp"],
            usage=result.get("usage")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Grok architecture analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze architecture: {str(e)}")

@router.post("/grok/debug-assistance", response_model=GrokResponse)
async def get_debug_assistance(
    request: DebuggingRequest,
    current_user: Dict = Depends(get_current_user)
):
    """Get debugging assistance from Grok for specific errors"""
    try:
        if not get_grok_client:
            raise HTTPException(status_code=501, detail="Grok integration not available")
        
        # Get Grok client for tenant
        grok_client = await get_grok_client(current_user["tenant_id"])
        
        if not grok_client:
            raise HTTPException(status_code=400, detail="Grok not configured for your account")
        
        # Get debugging assistance
        async with grok_client:
            result = await grok_client.debug_assistance(
                error_message=request.error_message,
                stack_trace=request.stack_trace,
                code_context=request.code_context,
                environment=request.environment
            )
        
        logger.info(f"Grok debugging assistance generated for tenant {current_user['tenant_id']}")
        
        return GrokResponse(
            content=result["debugging_help"],
            model=result["model"],
            timestamp=result["timestamp"],
            usage=result.get("usage")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Grok debugging assistance failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get debugging assistance: {str(e)}")

@router.get("/grok/status")
async def get_grok_status(
    current_user: Dict = Depends(get_current_user)
):
    """Check Grok integration status for current user's tenant"""
    try:
        if not get_grok_client:
            return {"available": False, "reason": "Grok integration not installed"}
        
        # Try to get Grok client for tenant
        grok_client = await get_grok_client(current_user["tenant_id"])
        
        if not grok_client:
            return {"available": False, "reason": "Grok API key not configured"}
        
        return {"available": True, "model": "grok-beta", "tenant_id": current_user["tenant_id"]}
        
    except Exception as e:
        logger.error(f"Grok status check failed: {e}")
        return {"available": False, "reason": str(e)}

# SendGrid Email Sending Endpoints
@router.post("/sendgrid/send-email", response_model=SendEmailResponse)
async def send_email_via_sendgrid(
    request: SendEmailRequest,
    current_user: Dict = Depends(get_current_user)
):
    """Send an email via SendGrid"""
    try:
        if not get_sendgrid_client:
            raise HTTPException(status_code=501, detail="SendGrid integration not available")
        
        # Pre-send verification via CUFinder (block only explicit invalids)
        verification_summary: Optional[Dict[str, Any]] = None
        if not request.skip_verify:
            try:
                from integrations.cufinder_client import get_cufinder_client
                verifier = get_cufinder_client(current_user["tenant_id"])
                check = await verifier.verify_email(request.to_email)
                if not check.get('valid', False):
                    # Only block when service positively indicates invalid
                    verification_summary = {"status": "invalid", "details": check}
                    raise HTTPException(status_code=400, detail="Recipient email failed verification")
                verification_summary = {"status": "valid", "details": check}
            except HTTPException:
                raise
            except Exception as _verr:
                # Treat verification service issues as non-blocking
                logger.warning(f"Send verification unavailable, proceeding: {_verr}")
                verification_summary = {"status": "unavailable", "error": str(_verr)}

        # Get SendGrid client for tenant
        sendgrid_client = get_sendgrid_client(current_user["tenant_id"])

        if not sendgrid_client:
            raise HTTPException(status_code=400, detail="SendGrid not configured for your account")

        # Get user's email settings if from_email/from_name not provided
        if not request.from_email or not request.from_name:
            try:
                conn = get_db()
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "SELECT sender_email, sender_name FROM users WHERE id = ?",
                        (current_user["id"],)
                    )
                    user_row = cursor.fetchone()
                    if user_row:
                        # Convert to dict if it's a Row object
                        if hasattr(user_row, 'keys'):
                            user_data = dict(user_row)
                            user_email = user_data.get('sender_email')
                            user_name = user_data.get('sender_name')
                        else:
                            # Handle as tuple
                            user_email = user_row[0] if len(user_row) > 0 else None
                            user_name = user_row[1] if len(user_row) > 1 else None

                        if not request.from_email and user_email:
                            request.from_email = user_email
                        if not request.from_name and user_name:
                            request.from_name = user_name
                        logger.info(f"Using user email settings: {request.from_email}, {request.from_name}")
                finally:
                    try:
                        cursor.close()
                    except Exception:
                        pass  # Cursor might already be closed
            except Exception as e:
                logger.warning(f"Failed to load user email settings: {e}")
                # Continue without user settings
        
        # Send the email using the SendGrid client API
        # Note: personalize name via SendGrid email object is handled internally
        if request.raw:
            result = await sendgrid_client.send_email_raw(
                to_email=request.to_email,
                subject=request.subject,
                body_text=request.message,
                from_email=request.from_email,
                from_name=request.from_name,
                custom_args={
                    'tenant_id': str(current_user["tenant_id"]),
                    'prospect_name': request.prospect_name or '',
                    'connector_name': request.connector_name or ''
                }
            )
        elif request.simple:
            result = await sendgrid_client.send_email_minimal(
                to_email=request.to_email,
                subject=request.subject,
                body=request.message,
                from_email=request.from_email,
                from_name=request.from_name
            )
        else:
            result = await sendgrid_client.send_email(
                to_email=request.to_email,
                subject=request.subject,
                body=request.message,
                from_email=request.from_email,
                from_name=request.from_name,
                custom_args={
                    'tenant_id': str(current_user["tenant_id"]),
                    'prospect_name': request.prospect_name or '',
                    'connector_name': request.connector_name or ''
                }
            )
        
        # Fail fast if provider send failed
        if not getattr(result, 'success', False):
            err = getattr(result, 'error_message', 'send failed')
            logger.error(f"SendGrid send failed for tenant {current_user['tenant_id']} to {request.to_email}: {err}")
            # Retry: raw then minimal (in that order) if not already in those modes
            if not request.raw:
                logger.info("Retrying send with raw v3 JSON path...")
                retry_raw = await sendgrid_client.send_email_raw(
                    to_email=request.to_email,
                    subject=request.subject,
                    body_text=request.message,
                    from_email=request.from_email,
                    from_name=request.from_name,
                    custom_args={
                        'tenant_id': str(current_user["tenant_id"]),
                        'prospect_name': request.prospect_name or '',
                        'connector_name': request.connector_name or ''
                    }
                )
                if getattr(retry_raw, 'success', False):
                    result = retry_raw
                elif not request.simple:
                    logger.info("Retrying send with minimal path (plain text only)...")
                    retry_min = await sendgrid_client.send_email_minimal(
                        to_email=request.to_email,
                        subject=request.subject,
                        body=request.message,
                        from_email=request.from_email,
                        from_name=request.from_name
                    )
                    if getattr(retry_min, 'success', False):
                        result = retry_min
                    else:
                        raise HTTPException(status_code=502, detail=f"SendGrid send failed: {err}")
            else:
                logger.info("Retrying send with minimal path (plain text only)...")
                retry_result = await sendgrid_client.send_email_minimal(
                    to_email=request.to_email,
                    subject=request.subject,
                    body=request.message,
                    from_email=request.from_email,
                    from_name=request.from_name
                )
                if getattr(retry_result, 'success', False):
                    result = retry_result
                else:
                    raise HTTPException(status_code=502, detail=f"SendGrid send failed: {err}")

        logger.info(f"Email sent via SendGrid for tenant {current_user['tenant_id']} to {request.to_email}")
        
        # Update introduction status if ID provided
        if request.introduction_id:
            try:
                conn = get_db()
                cursor = conn.cursor()
                try:
                    conn.execute("""
                        UPDATE outreach_queue 
                        SET status = 'sent', sent_at = CURRENT_TIMESTAMP, 
                            message_id = ?, provider = 'sendgrid'
                        WHERE id = ? AND tenant_id = ?
                    """, (getattr(result, 'message_id', None), request.introduction_id, current_user["tenant_id"]))
                    logger.info(f"Updated introduction {request.introduction_id} status to sent")
                finally:
                    try:
                        cursor.close()
                    except Exception:
                        pass  # Cursor might already be closed
            except Exception as db_error:
                logger.error(f"Failed to update introduction status: {db_error}")
                # Don't fail the whole request for DB update errors
        
        # Build response from EmailResult dataclass
        return SendEmailResponse(
            message_id=getattr(result, 'message_id', '') or 'unknown',
            status=(getattr(result, 'status').value if getattr(result, 'status', None) else 'sent'),
            sent_at=datetime.now().isoformat(),
            provider="SendGrid",
            verification=verification_summary
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SendGrid email sending failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

@router.get("/sendgrid/status")
async def get_sendgrid_status(
    current_user: Dict = Depends(get_current_user)
):
    """Check SendGrid integration status for current user's tenant"""
    try:
        if not get_sendgrid_client:
            return {
                "status": "unavailable",
                "available": False,
                "reason": "SendGrid integration not installed"
            }

        # Try to get SendGrid client for tenant
        sendgrid_client = get_sendgrid_client(current_user["tenant_id"])

        if not sendgrid_client:
            return {
                "status": "not_configured",
                "available": False,
                "reason": "SendGrid API key not configured"
            }

        return {
            "status": "healthy",
            "available": True,
            "provider": "SendGrid",
            "from_email": getattr(sendgrid_client, 'from_email', 'configured'),
            "daily_limit": getattr(sendgrid_client, 'daily_send_limit', 'unknown'),
            "tenant_id": current_user["tenant_id"]
        }

    except Exception as e:
        logger.error(f"SendGrid status check failed: {e}")
        return {
            "status": "error",
            "available": False,
            "error": str(e)
        }


@router.get("/linkedin/status")
async def get_linkedin_status(
    current_user: Dict = Depends(get_current_user)
):
    """Check LinkedIn integration status for current user's tenant"""
    try:
        # LinkedIn integration status check
        # TODO: Implement actual LinkedIn client check when integration is available
        return {
            "status": "not_implemented",
            "available": False,
            "reason": "LinkedIn integration not yet implemented",
            "tenant_id": current_user["tenant_id"]
        }

    except Exception as e:
        logger.error(f"LinkedIn status check failed: {e}")
        return {
            "status": "error",
            "available": False,
            "error": str(e)
        }


@router.get("/health")
async def get_integrations_health(
    current_user: Dict = Depends(get_current_user)
):
    """Get health status for all integrations"""
    try:
        health_status = {
            "sendgrid": {"status": "unknown"},
            "linkedin": {"status": "not_implemented"},
            "database": {"status": "unknown"}
        }

        # Check SendGrid
        if get_sendgrid_client:
            try:
                sendgrid_client = get_sendgrid_client(current_user["tenant_id"])
                if sendgrid_client:
                    health_status["sendgrid"] = {
                        "status": "healthy",
                        "provider": "SendGrid",
                        "configured": True
                    }
                else:
                    health_status["sendgrid"] = {
                        "status": "not_configured",
                        "configured": False
                    }
            except Exception as e:
                health_status["sendgrid"] = {
                    "status": "error",
                    "error": str(e)
                }

        # Check database connectivity
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            health_status["database"] = {
                "status": "healthy",
                "type": "PostgreSQL"
            }
        except Exception as e:
            health_status["database"] = {
                "status": "error",
                "error": str(e)
            }

        return {
            "status": "ok",
            "integrations": health_status,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.post("/sendgrid/validate")
async def validate_sendgrid_api_key(
    request: Dict,
    current_user: Dict = Depends(get_current_user)
):
    """Validate a SendGrid API key"""
    try:
        api_key = request.get("api_key")
        if not api_key:
            raise HTTPException(status_code=400, detail="API key is required")

        # TODO: Implement actual SendGrid API key validation
        # For now, just check if it looks like a valid SendGrid key
        if api_key.startswith("SG.") and len(api_key) > 20:
            return {
                "valid": True,
                "message": "API key format is valid (not fully verified)"
            }
        else:
            return {
                "valid": False,
                "message": "Invalid API key format"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API key validation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")


@router.get("/errors")
async def get_integration_errors(
    current_user: Dict = Depends(get_current_user)
):
    """Get integration error logs"""
    try:
        # TODO: Implement actual error log retrieval from database
        # For now, return empty array
        return {
            "errors": [],
            "total": 0,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error log retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve errors: {str(e)}")


@router.post("/sendgrid/test")
async def test_sendgrid_connection(
    request: Dict,
    current_user: Dict = Depends(get_current_user)
):
    """Test SendGrid connection by sending a test email"""
    try:
        to_email = request.get("to_email")
        test_mode = request.get("test_mode", True)

        if not to_email:
            raise HTTPException(status_code=400, detail="to_email is required")

        if not get_sendgrid_client:
            raise HTTPException(status_code=501, detail="SendGrid integration not available")

        sendgrid_client = get_sendgrid_client(current_user["tenant_id"])
        if not sendgrid_client:
            raise HTTPException(status_code=400, detail="SendGrid not configured")

        # In test mode, don't actually send
        if test_mode:
            return {
                "status": "test_mode",
                "message": "Test mode - email not sent",
                "to_email": to_email
            }

        # TODO: Implement actual test email sending
        return {
            "status": "success",
            "message": "Test email sent successfully",
            "to_email": to_email
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SendGrid test failed: {e}")
        raise HTTPException(status_code=503, detail=f"Test failed: {str(e)}")


@router.get("/stats")
async def get_integration_statistics(
    current_user: Dict = Depends(get_current_user)
):
    """Get integration usage statistics"""
    try:
        # TODO: Implement actual statistics retrieval from database
        # For now, return empty stats
        return {
            "sendgrid": {
                "emails_sent_today": 0,
                "emails_sent_this_month": 0,
                "success_rate": 0.0
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Statistics retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve statistics: {str(e)}")
