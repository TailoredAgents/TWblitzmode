"""
Enhanced SendGrid Multi-Tenant Client (Phase 2)
Provides automatic subuser management and domain authentication
"""

import logging
import json
import secrets
import string
import time
from typing import Optional, Dict, List, Any
from datetime import datetime
from dataclasses import dataclass

# import requests  # Not used in current implementation
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from core.settings import settings
from api.mt_db import get_db
from api.security import enc, dec
from services.cost_monitoring_service import cost_monitoring_service

# Import metrics if available
try:
    from monitoring.prometheus_metrics import MetricsCollector, track_email_processing
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False

logger = logging.getLogger(__name__)

@dataclass
class SubuserCreationResult:
    success: bool
    subuser_username: Optional[str] = None
    api_key: Optional[str] = None
    error_message: Optional[str] = None

@dataclass
class DomainAuthenticationResult:
    success: bool
    domain: str
    dns_records: Optional[List[Dict]] = None
    verification_status: str = "pending"
    error_message: Optional[str] = None

class EnhancedSendGridClient:
    """
    Enhanced SendGrid client with multi-tenant subuser management
    Provides automatic tenant isolation and domain authentication
    """
    
    def __init__(self, parent_api_key: Optional[str] = None):
        """Initialize with parent SendGrid account API key"""
        self.parent_api_key = parent_api_key or settings.SENDGRID_API_KEY
        self.client = SendGridAPIClient(self.parent_api_key)
        
    # ============================================
    # SUBUSER MANAGEMENT
    # ============================================
    
    async def create_tenant_subuser(self, tenant_id: int, tenant_name: str, tenant_email: str) -> SubuserCreationResult:
        """
        Create a dedicated SendGrid subuser for a tenant
        
        Args:
            tenant_id: Tenant ID from database
            tenant_name: Display name for the tenant
            tenant_email: Contact email for the subuser account
            
        Returns:
            SubuserCreationResult with success status and credentials
        """
        try:
            # Generate unique username
            timestamp = int(time.time())
            subuser_username = f"tenant_{tenant_id}_{timestamp}"
            
            # Generate secure password
            password = self._generate_secure_password()
            
            # Create subuser via SendGrid API
            subuser_data = {
                "username": subuser_username,
                "email": tenant_email,
                "password": password,
                "ips": []  # Start with shared IPs
            }
            
            response = self.client.client.subusers.post(request_body=subuser_data)
            
            if response.status_code == 201:
                # Create API key for the subuser
                api_key = await self._create_subuser_api_key(subuser_username)
                
                if api_key:
                    # Store in database
                    await self._store_subuser_credentials(tenant_id, subuser_username, api_key)
                    
                    logger.info(f"Successfully created subuser for tenant {tenant_id}: {subuser_username}")
                    return SubuserCreationResult(
                        success=True,
                        subuser_username=subuser_username,
                        api_key=api_key
                    )
                else:
                    return SubuserCreationResult(
                        success=False,
                        error_message="Failed to create API key for subuser"
                    )
            else:
                error_msg = f"SendGrid API error: {response.status_code} - {response.body}"
                logger.error(f"Failed to create subuser for tenant {tenant_id}: {error_msg}")
                return SubuserCreationResult(
                    success=False,
                    error_message=error_msg
                )
                
        except Exception as e:
            logger.error(f"Exception creating subuser for tenant {tenant_id}: {e}")
            return SubuserCreationResult(
                success=False,
                error_message=str(e)
            )
    
    async def _create_subuser_api_key(self, subuser_username: str) -> Optional[str]:
        """Create API key for subuser with appropriate permissions"""
        try:
            # Switch to subuser context
            headers = {"On-Behalf-Of": subuser_username}
            
            api_key_data = {
                "name": f"tenant_key_{int(time.time())}",
                "scopes": [
                    "mail.send",
                    "sender_verification_eligible",
                    "2fa_exempt",
                    "stats.read"
                ]
            }
            
            response = self.client.client.api_keys.post(
                request_body=api_key_data,
                request_headers=headers
            )
            
            if response.status_code == 201:
                # Parse response body safely
                body = response.body
                if isinstance(body, str):
                    body = json.loads(body)
                elif isinstance(body, (bytes, bytearray)):
                    body = json.loads(body.decode('utf-8'))
                return body.get("api_key") if isinstance(body, dict) else None
            return None
            
        except Exception as e:
            logger.error(f"Failed to create API key for subuser {subuser_username}: {e}")
            return None
    
    async def _store_subuser_credentials(self, tenant_id: int, username: str, api_key: str):
        """Store subuser credentials in database"""
        encrypted_api_key = enc(api_key)
        
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO tenant_sendgrid_subusers 
                (tenant_id, subuser_username, subuser_api_key_encrypted, subuser_created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    subuser_username = EXCLUDED.subuser_username,
                    subuser_api_key_encrypted = EXCLUDED.subuser_api_key_encrypted,
                    subuser_created_at = EXCLUDED.subuser_created_at
            """, (tenant_id, username, encrypted_api_key, datetime.now()))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"Failed to store subuser credentials for tenant {tenant_id}: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    # ============================================
    # DOMAIN AUTHENTICATION
    # ============================================
    
    async def setup_domain_authentication(self, tenant_id: int, domain: str) -> DomainAuthenticationResult:
        """
        Set up domain authentication for a tenant
        
        Args:
            tenant_id: Tenant ID
            domain: Domain to authenticate (e.g., "clientcompany.com")
            
        Returns:
            DomainAuthenticationResult with DNS records and status
        """
        try:
            # Get subuser for tenant
            subuser_username = await self._get_tenant_subuser(tenant_id)
            if not subuser_username:
                return DomainAuthenticationResult(
                    success=False,
                    domain=domain,
                    error_message="Tenant does not have a subuser. Create subuser first."
                )
            
            # Create domain authentication via SendGrid API
            headers = {"On-Behalf-Of": subuser_username}
            
            # Use automated security (recommended)
            domain_data = {
                "domain": domain,
                "automatic_security": True,
                "default": True
            }
            
            response = self.client.client.whitelabel.domains.post(
                request_body=domain_data,
                request_headers=headers
            )
            
            if response.status_code == 201:
                # Parse response body safely
                body = response.body
                if isinstance(body, str):
                    body = json.loads(body)
                elif isinstance(body, (bytes, bytearray)):
                    body = json.loads(body.decode('utf-8'))
                
                domain_id = body.get("id") if isinstance(body, dict) else None
                dns_records = body.get("dns", {}) if isinstance(body, dict) else {}
                
                # Store domain authentication info
                await self._store_domain_authentication(
                    tenant_id, domain, domain_id, dns_records
                )
                
                # Format DNS records for client
                formatted_records = self._format_dns_records(dns_records)
                
                logger.info(f"Domain authentication setup for tenant {tenant_id}: {domain}")
                return DomainAuthenticationResult(
                    success=True,
                    domain=domain,
                    dns_records=formatted_records,
                    verification_status="pending"
                )
            else:
                error_msg = f"SendGrid domain auth error: {response.status_code} - {response.body}"
                return DomainAuthenticationResult(
                    success=False,
                    domain=domain,
                    error_message=error_msg
                )
                
        except Exception as e:
            logger.error(f"Exception setting up domain auth for tenant {tenant_id}: {e}")
            return DomainAuthenticationResult(
                success=False,
                domain=domain,
                error_message=str(e)
            )
    
    async def verify_domain_authentication(self, tenant_id: int, domain: str) -> DomainAuthenticationResult:
        """Check if domain authentication has been completed"""
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Get domain authentication details
            cursor.execute("""
                SELECT sendgrid_domain_id, required_dns_records
                FROM tenant_domain_authentication
                WHERE tenant_id = %s AND domain = %s
            """, (tenant_id, domain))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return DomainAuthenticationResult(
                    success=False,
                    domain=domain,
                    error_message="Domain authentication not found"
                )
            
            domain_id = result["sendgrid_domain_id"]
            
            # Check verification status via SendGrid API
            subuser_username = await self._get_tenant_subuser(tenant_id)
            headers = {"On-Behalf-Of": subuser_username}
            
            response = self.client.client.whitelabel.domains._(domain_id).get(
                request_headers=headers
            )
            
            if response.status_code == 200:
                verification_data = response.body
                is_verified = verification_data.get("valid", False)
                
                if is_verified:
                    # Update database
                    await self._update_domain_verification_status(tenant_id, domain, "verified")
                    
                return DomainAuthenticationResult(
                    success=True,
                    domain=domain,
                    verification_status="verified" if is_verified else "pending"
                )
            else:
                return DomainAuthenticationResult(
                    success=False,
                    domain=domain,
                    error_message="Failed to check verification status"
                )
                
        except Exception as e:
            logger.error(f"Exception verifying domain auth for tenant {tenant_id}: {e}")
            return DomainAuthenticationResult(
                success=False,
                domain=domain,
                error_message=str(e)
            )
    
    # ============================================
    # TENANT EMAIL SENDING
    # ============================================
    
    @track_email_processing("send_email") if METRICS_AVAILABLE else lambda f: f
    async def send_email_for_tenant(self, tenant_id: int, to_email: str, subject: str, 
                                  body_html: str, body_text: str, from_name: str = None) -> Dict[str, Any]:
        """
        Send email using tenant's dedicated subuser
        
        Args:
            tenant_id: Tenant ID
            to_email: Recipient email
            subject: Email subject
            body_html: HTML email body
            body_text: Plain text email body  
            from_name: Sender name (optional)
            
        Returns:
            Dict with sending result
        """
        try:
            # Get tenant's subuser API key
            subuser_api_key = await self._get_tenant_subuser_api_key(tenant_id)
            if not subuser_api_key:
                return {"success": False, "error": "Tenant subuser not found"}
            
            # Get tenant's authenticated domain
            from_email = await self._get_tenant_from_email(tenant_id)
            
            # Create SendGrid client with subuser API key
            tenant_client = SendGridAPIClient(subuser_api_key)
            
            # Create email
            message = Mail(
                from_email=(from_email, from_name or "VouchLink AI AI"),
                to_emails=to_email,
                subject=subject,
                html_content=body_html,
                plain_text_content=body_text
            )
            
            # Send email
            response = tenant_client.send(message)
            
            # Parse response more carefully
            status_code = response.status_code
            body = response.body
            headers = response.headers
            
            # Handle string body response (Fix for 'str' object has no attribute 'get')
            body_dict = {}
            if body:
                try:
                    if isinstance(body, str):
                        body_dict = json.loads(body)
                    elif isinstance(body, (bytes, bytearray)):
                        body_dict = json.loads(body.decode('utf-8'))
                    else:
                        body_dict = body if isinstance(body, dict) else {}
                except json.JSONDecodeError:
                    logger.error(f"Non-JSON response body: {body}")
                    body_dict = {"raw_body": str(body)}
            
            if status_code in [202, 200]:
                # Log successful send
                await self._log_email_send(tenant_id, to_email, subject, from_email, "sent")
                
                # Safely get message ID from headers
                message_id = None
                if headers:
                    if hasattr(headers, 'get'):
                        message_id = headers.get("X-Message-Id")
                    elif isinstance(headers, dict):
                        message_id = headers.get("X-Message-Id")
                
                return {
                    "success": True,
                    "message_id": message_id,
                    "status_code": status_code
                }
            else:
                # Extract error message from response body
                error_msg = f"SendGrid error: {status_code}"
                if body_dict:
                    errors = body_dict.get('errors', [])
                    if errors and isinstance(errors, list):
                        error_msg = errors[0].get('message', error_msg) if isinstance(errors[0], dict) else error_msg
                
                logger.error(f"Failed to send email for tenant {tenant_id}: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "details": body_dict
                }
                
        except Exception as e:
            logger.error(f"Exception sending email for tenant {tenant_id}: {e}")
            return {"success": False, "error": str(e)}
    
    # ============================================
    # HELPER METHODS
    # ============================================
    
    def _generate_secure_password(self, length: int = 16) -> str:
        """Generate secure password for subuser"""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    async def _get_tenant_subuser(self, tenant_id: int) -> Optional[str]:
        """Get subuser username for tenant"""
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
    
    async def _get_tenant_subuser_api_key(self, tenant_id: int) -> Optional[str]:
        """Get decrypted subuser API key for tenant"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT subuser_api_key_encrypted
            FROM tenant_sendgrid_subusers
            WHERE tenant_id = %s
        """, (tenant_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result["subuser_api_key_encrypted"]:
            return dec(result["subuser_api_key_encrypted"])
        return None
    
    async def _get_tenant_from_email(self, tenant_id: int) -> str:
        """Get tenant's authenticated from email or fallback"""
        conn = get_db()
        cursor = conn.cursor()
        
        # Try to get authenticated domain
        cursor.execute("""
            SELECT tda.domain, tes.from_email
            FROM tenant_domain_authentication tda
            LEFT JOIN tenant_email_settings tes ON tda.tenant_id = tes.tenant_id
            WHERE tda.tenant_id = %s AND tda.auth_status = 'verified'
            ORDER BY tda.verified_at DESC
            LIMIT 1
        """, (tenant_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result["domain"]:
            # Use authenticated domain
            return f"assistant@{result['domain']}"
        elif result and result["from_email"]:
            # Use configured from email
            return result["from_email"]
        else:
            # Fallback to default
            return settings.DEFAULT_FROM_EMAIL
    
    def _format_dns_records(self, dns_records: Dict) -> List[Dict]:
        """Format DNS records for client display"""
        formatted = []
        
        # Handle CNAME records (Automated Security)
        for record in dns_records.get("cname_records", []):
            formatted.append({
                "type": "CNAME",
                "name": record.get("host"),
                "value": record.get("data"),
                "ttl": "300"
            })
        
        # Handle TXT records (Manual setup)
        for record in dns_records.get("txt_records", []):
            formatted.append({
                "type": "TXT", 
                "name": record.get("host"),
                "value": record.get("data"),
                "ttl": "300"
            })
        
        return formatted
    
    async def _store_domain_authentication(self, tenant_id: int, domain: str, 
                                         domain_id: int, dns_records: Dict):
        """Store domain authentication details in database"""
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO tenant_domain_authentication
                (tenant_id, domain, sendgrid_domain_id, required_dns_records, auth_status)
                VALUES (%s, %s, %s, %s, 'pending')
                ON CONFLICT (tenant_id, domain) DO UPDATE SET
                    sendgrid_domain_id = EXCLUDED.sendgrid_domain_id,
                    required_dns_records = EXCLUDED.required_dns_records,
                    auth_status = 'pending'
            """, (tenant_id, domain, domain_id, json.dumps(dns_records)))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"Failed to store domain auth for tenant {tenant_id}: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    async def _update_domain_verification_status(self, tenant_id: int, domain: str, status: str):
        """Update domain verification status"""
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE tenant_domain_authentication
                SET auth_status = %s, verified_at = %s
                WHERE tenant_id = %s AND domain = %s
            """, (status, datetime.now() if status == "verified" else None, tenant_id, domain))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"Failed to update domain status for tenant {tenant_id}: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    async def _log_email_send(self, tenant_id: int, to_email: str, subject: str, 
                            from_email: str, status: str):
        """Log email send for analytics"""
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO tenant_email_logs
                (tenant_id, recipient_email, subject, from_domain, status, cost)
                VALUES (%s, %s, %s, %s, %s, 0.001)
            """, (tenant_id, to_email, subject, from_email.split('@')[1], status))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"Failed to log email send for tenant {tenant_id}: {e}")
        finally:
            conn.close()

# Factory function for easy import
def get_enhanced_sendgrid_client() -> EnhancedSendGridClient:
    """Get enhanced SendGrid client instance"""
    return EnhancedSendGridClient()


def get_sendgrid_multi_tenant_client() -> EnhancedSendGridClient:
    """Backward compatible factory for legacy imports"""
    return get_enhanced_sendgrid_client()


SendGridMultiTenantClient = EnhancedSendGridClient
