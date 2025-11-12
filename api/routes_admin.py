from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Dict, Any
from pydantic import BaseModel
from datetime import datetime
import logging

from api.deps import get_current_user, get_current_admin
from api.database import get_db
from api.security import hash_password, verify_password
from api.database import _convert_placeholders

logger = logging.getLogger(__name__)

def is_postgresql():
    """Helper function to detect if we're using PostgreSQL"""
    try:
        from api.database import DATABASE_URL
        return DATABASE_URL and DATABASE_URL.startswith(('postgres://', 'postgresql://'))
    except ImportError:
        return False

def upsert_tenant_setting(conn, tenant_id, setting_key, setting_value, encrypted):
    """Database-agnostic upsert for tenant_settings table"""
    # Convert boolean to integer for database compatibility
    encrypted_int = 1 if encrypted else 0
    
    if is_postgresql():
        # PostgreSQL syntax with ON CONFLICT
        return conn.execute("""
            INSERT INTO tenant_settings 
            (tenant_id, setting_key, setting_value, encrypted, created_at, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (tenant_id, setting_key) 
            DO UPDATE SET 
                setting_value = EXCLUDED.setting_value,
                encrypted = EXCLUDED.encrypted,
                updated_at = CURRENT_TIMESTAMP
        """, (tenant_id, setting_key, setting_value, encrypted_int))
    else:
        # SQLite syntax with INSERT OR REPLACE
        return conn.execute("""
            INSERT OR REPLACE INTO tenant_settings 
            (tenant_id, setting_key, setting_value, encrypted, created_at, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (tenant_id, setting_key, setting_value, encrypted_int))

router = APIRouter()

# Pydantic models
class TenantCreate(BaseModel):
    name: str
    status: str = "active"

class TenantUpdate(BaseModel):
    name: str = None
    status: str = None

class UserCreate(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str
    role: str = "user"
    tenant_id: int

class UserUpdate(BaseModel):
    email: str = None
    first_name: str = None
    last_name: str = None
    role: str = None
    is_active: bool = None

class IntegrationSettings(BaseModel):
    apify_token: str = None
    apify_webhook_secret: str = None
    apify_li_cookie_secret_name: str = None
    phantombuster_api_key: str = None
    linkedin_li_at: str = None
    linkedin_jsessionid: str = None
    linkedin_cookies_json: str = None
    sendgrid_api_key: str = None
    sendgrid_from_email: str = None
    sendgrid_from_name: str = None
    openai_api_key: str = None
    cufinder_api_key: str = None
    grok_api_key: str = None

@router.get("/tenants")
async def get_all_tenants(current_user: dict = Depends(get_current_admin)):
    """Get all tenants (admin only)"""
    conn = get_db()
    try:
        cursor = conn.execute("""
            SELECT t.id, t.name, t.status, t.created_at,
                   COUNT(DISTINCT u.id) as user_count,
                   COUNT(DISTINCT p.id) as prospect_count
            FROM tenants t
            LEFT JOIN organizations o ON o.tenant_id = CAST(t.id AS TEXT)
            LEFT JOIN users u ON u.tenant_id = CAST(t.id AS TEXT)
            LEFT JOIN prospects p ON p.organization_id = o.id
            GROUP BY t.id, t.name, t.status, t.created_at
            ORDER BY t.created_at DESC
        """)
        
        tenants = []
        for row in cursor.fetchall():
            tenants.append({
                "id": row["id"],
                "name": row["name"],
                "status": row["status"],
                "created_at": row["created_at"],
                "user_count": row["user_count"],
                "prospect_count": row["prospect_count"]
            })
        
        return {"data": tenants}
    finally:
        conn.close()

@router.post("/tenants")
async def create_tenant(tenant: TenantCreate, current_user: dict = Depends(get_current_admin)):
    """Create a new tenant (admin only)"""
    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO tenants (name, status, created_at)
            VALUES (?, ?, datetime('now'))
        """, (tenant.name, tenant.status))
        
        tenant_id = cursor.lastrowid
        conn.commit()
        
        return {
            "id": tenant_id,
            "name": tenant.name,
            "status": tenant.status,
            "message": "Tenant created successfully"
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@router.put("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: int,
    tenant: TenantUpdate,
    current_user: dict = Depends(get_current_admin)
):
    """Update a tenant (admin only)"""
    conn = get_db()
    try:
        # Build update query dynamically
        updates = []
        params = []
        
        if tenant.name is not None:
            updates.append("name = ?")
            params.append(tenant.name)
        
        if tenant.status is not None:
            updates.append("status = ?")
            params.append(tenant.status)
        
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        params.append(tenant_id)
        query = f"UPDATE tenants SET {', '.join(updates)} WHERE id = ?"
        
        cursor = conn.execute(query, params)
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        return {"message": "Tenant updated successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: int, current_user: dict = Depends(get_current_admin)):
    """Delete a tenant and all associated data (admin only)"""
    # Safety check: prevent deletion of tenant ID 1 (often the default/admin tenant)
    if tenant_id <= 1:
        raise HTTPException(
            status_code=403,
            detail="Cannot delete default tenant (ID 1) for system stability"
        )

    # Safety check: prevent admins from deleting their own tenant
    if tenant_id == current_user.get("tenant_id"):
        raise HTTPException(
            status_code=403,
            detail="Cannot delete your own tenant. Please use a different admin account."
        )

    conn = get_db()
    try:
        # Check if tenant exists
        cursor = conn.execute("SELECT id, name FROM tenants WHERE id = ?", (tenant_id,))
        tenant = cursor.fetchone()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        tenant_name = tenant["name"]
        logger.info(f"Admin {current_user['email']} initiating deletion of tenant {tenant_id} ({tenant_name})")

        # Delete in order of dependencies (gracefully handle missing tables)
        # List only tables that we know exist and have tenant_id columns
        cleanup_queries = [
            ("tenant_settings", "DELETE FROM tenant_settings WHERE tenant_id = ?"),
            ("job_idempotency", "DELETE FROM job_idempotency WHERE tenant_id = ?"),
            ("provider_health", "DELETE FROM provider_health WHERE tenant_id = ?"),
            ("prospect_mutuals", "DELETE FROM prospect_mutuals WHERE tenant_id = ?"),
            ("prospects", "DELETE FROM prospects WHERE tenant_id = ?"),
            ("users", "DELETE FROM users WHERE tenant_id = ?")
        ]

        total_deleted = 0
        for table_name, query in cleanup_queries:
            try:
                # Use database-specific parameter placeholder
                if is_postgresql():
                    query = _convert_placeholders(query)

                result = conn.execute(query, (tenant_id,))
                records_deleted = result.rowcount
                total_deleted += records_deleted

                if records_deleted > 0:
                    logger.info(f"Deleted {records_deleted} records from {table_name} for tenant {tenant_id}")

                    # Safety verification: ensure we didn't accidentally delete from other tenants
                    if table_name in ["tenant_settings", "users", "prospects"]:
                        verify_query = f"SELECT COUNT(*) as count FROM {table_name} WHERE tenant_id != ?"
                        if is_postgresql():
                            verify_query = _convert_placeholders(verify_query)
                        verify_cursor = conn.execute(verify_query, (tenant_id,))
                        other_tenant_count = verify_cursor.fetchone()["count"]
                        logger.info(f"Verification: {table_name} still has {other_tenant_count} records for other tenants")

            except Exception as e:
                # Log but don't fail - table might not exist or have tenant_id column
                logger.info(f"Skipping cleanup of {table_name}: {e}")
                continue

        # Finally delete the tenant record itself
        tenant_delete_query = "DELETE FROM tenants WHERE id = ?"
        if is_postgresql():
            tenant_delete_query = _convert_placeholders(tenant_delete_query)
        conn.execute(tenant_delete_query, (tenant_id,))

        conn.commit()
        logger.info(f"Successfully deleted tenant {tenant_id} ({tenant_name}) with {total_deleted} total records")

        return {
            "message": f"Tenant {tenant_id} ({tenant_name}) and all associated data deleted successfully",
            "records_deleted": total_deleted,
            "tenant_name": tenant_name
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@router.get("/tenants/stats")
async def get_tenant_statistics(current_user: dict = Depends(get_current_admin)):
    """Get aggregate statistics across all tenants (admin only)"""
    conn = get_db()
    try:
        # Get total tenant count
        cursor = conn.execute("SELECT COUNT(*) as total FROM tenants")
        total_tenants = cursor.fetchone()["total"]

        # Get active tenant count
        cursor = conn.execute("SELECT COUNT(*) as active FROM tenants WHERE status = 'active'")
        active_tenants = cursor.fetchone()["active"]

        # Get suspended tenant count
        cursor = conn.execute("SELECT COUNT(*) as suspended FROM tenants WHERE status = 'suspended'")
        suspended_tenants = cursor.fetchone()["suspended"]

        # Get total user count across all tenants
        cursor = conn.execute("SELECT COUNT(*) as total FROM users")
        total_users = cursor.fetchone()["total"]

        # Get total prospect count across all tenants
        cursor = conn.execute("SELECT COUNT(*) as total FROM prospects")
        total_prospects = cursor.fetchone()["total"]

        # Get tenants by status breakdown
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM tenants
            GROUP BY status
        """)
        status_breakdown = {row["status"]: row["count"] for row in cursor.fetchall()}

        stats = {
            "total_tenants": total_tenants,
            "active_tenants": active_tenants,
            "suspended_tenants": suspended_tenants,
            "total_users": total_users,
            "total_prospects": total_prospects,
            "tenants_by_status": status_breakdown
        }

        return {"data": stats}
    except Exception as e:
        logger.error(f"Error fetching tenant statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching statistics: {str(e)}")
    finally:
        conn.close()

@router.get("/tenants/{tenant_id}")
async def get_tenant_by_id(tenant_id: int, current_user: dict = Depends(get_current_admin)):
    """Get specific tenant details by ID (admin only)"""
    conn = get_db()
    try:
        cursor = conn.execute("""
            SELECT t.id, t.name, t.status, t.created_at,
                   COUNT(DISTINCT u.id) as user_count,
                   COUNT(DISTINCT p.id) as prospect_count
            FROM tenants t
            LEFT JOIN users u ON u.tenant_id = t.id
            LEFT JOIN prospects p ON p.tenant_id = t.id
            WHERE t.id = ?
            GROUP BY t.id, t.name, t.status, t.created_at
        """, (tenant_id,))

        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")

        tenant_data = {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "created_at": row["created_at"],
            "user_count": row["user_count"],
            "prospect_count": row["prospect_count"]
        }

        return {"data": tenant_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching tenant {tenant_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching tenant: {str(e)}")
    finally:
        conn.close()

@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(tenant_id: int, current_user: dict = Depends(get_current_admin)):
    """Suspend a tenant (admin only)"""
    # Safety check: prevent suspension of tenant ID 1
    if tenant_id <= 1:
        raise HTTPException(
            status_code=403,
            detail="Cannot suspend default tenant (ID 1) for system stability"
        )

    # Safety check: prevent admins from suspending their own tenant
    if tenant_id == current_user.get("tenant_id"):
        raise HTTPException(
            status_code=403,
            detail="Cannot suspend your own tenant. Please use a different admin account."
        )

    conn = get_db()
    try:
        # Check if tenant exists
        cursor = conn.execute("SELECT id, name, status FROM tenants WHERE id = ?", (tenant_id,))
        tenant = cursor.fetchone()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        if tenant["status"] == "suspended":
            return {"message": f"Tenant {tenant_id} is already suspended"}

        # Update tenant status to suspended
        cursor = conn.execute(
            "UPDATE tenants SET status = 'suspended' WHERE id = ?",
            (tenant_id,)
        )
        conn.commit()

        logger.info(f"Admin {current_user['email']} suspended tenant {tenant_id} ({tenant['name']})")

        return {
            "message": f"Tenant {tenant_id} ({tenant['name']}) suspended successfully",
            "tenant_id": tenant_id,
            "status": "suspended"
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error suspending tenant {tenant_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error suspending tenant: {str(e)}")
    finally:
        conn.close()

@router.post("/tenants/{tenant_id}/reactivate")
async def reactivate_tenant(tenant_id: int, current_user: dict = Depends(get_current_admin)):
    """Reactivate a suspended tenant (admin only)"""
    conn = get_db()
    try:
        # Check if tenant exists
        cursor = conn.execute("SELECT id, name, status FROM tenants WHERE id = ?", (tenant_id,))
        tenant = cursor.fetchone()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        if tenant["status"] == "active":
            return {"message": f"Tenant {tenant_id} is already active"}

        # Update tenant status to active
        cursor = conn.execute(
            "UPDATE tenants SET status = 'active' WHERE id = ?",
            (tenant_id,)
        )
        conn.commit()

        logger.info(f"Admin {current_user['email']} reactivated tenant {tenant_id} ({tenant['name']})")

        return {
            "message": f"Tenant {tenant_id} ({tenant['name']}) reactivated successfully",
            "tenant_id": tenant_id,
            "status": "active"
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error reactivating tenant {tenant_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error reactivating tenant: {str(e)}")
    finally:
        conn.close()

@router.get("/audit-log")
async def get_admin_audit_log(
    current_user: dict = Depends(get_current_admin),
    limit: int = 50,
    offset: int = 0
):
    """Get audit log for admin operations (admin only)"""
    conn = get_db()
    try:
        # Query audit events - filter for admin-related operations
        cursor = conn.execute("""
            SELECT
                id,
                tenant_id,
                user_id,
                event_type,
                action,
                resource_type,
                resource_id,
                severity,
                details,
                created_at
            FROM audit_events
            WHERE resource_type IN ('tenant', 'user', 'tenant_secret', 'integration')
               OR action LIKE '%admin%'
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))

        audit_entries = []
        for row in cursor.fetchall():
            audit_entries.append({
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "user_id": row["user_id"],
                "event_type": row["event_type"],
                "action": row["action"],
                "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "severity": row["severity"],
                "details": row["details"],
                "created_at": row["created_at"],
            })

        # Get total count for pagination
        count_cursor = conn.execute("""
            SELECT COUNT(*) as total
            FROM audit_events
            WHERE resource_type IN ('tenant', 'user', 'tenant_secret', 'integration')
               OR action LIKE '%admin%'
        """)
        total = count_cursor.fetchone()["total"]

        return {
            "audit_log": audit_entries,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(audit_entries)) < total
        }
    except Exception as e:
        logger.error(f"Error fetching admin audit log: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching audit log: {str(e)}")
    finally:
        conn.close()

@router.get("/users")
async def get_all_users(current_user: dict = Depends(get_current_admin)):
    """Get all users across all tenants (admin only)"""
    conn = get_db()
    try:
        cursor = conn.execute("""
            SELECT u.id, u.email, u.first_name, u.last_name, u.role, 
                   u.is_active, u.created_at, u.tenant_id,
                   t.name as tenant_name
            FROM users u
            LEFT JOIN tenants t ON u.tenant_id = t.id
            ORDER BY u.created_at DESC
        """)
        
        users = []
        for row in cursor.fetchall():
            users.append({
                "id": row["id"],
                "email": row["email"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "role": row["role"],
                "is_active": bool(row["is_active"]),  # Use actual column value
                "created_at": row["created_at"],
                "tenant_id": row["tenant_id"],
                "tenant_name": row["tenant_name"]
            })
        
        return {"data": users}
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching users: {str(e)}")
    finally:
        conn.close()

@router.post("/users")
async def create_user(user: UserCreate, current_user: dict = Depends(get_current_admin)):
    """Create a new user (admin only)"""
    conn = get_db()
    try:
        # Check if tenant exists
        cursor = conn.execute("SELECT id FROM tenants WHERE id = ?", (user.tenant_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Check if email already exists
        cursor = conn.execute("SELECT id FROM users WHERE email = ?", (user.email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Email already exists")
        
        # Create user
        password_hash = hash_password(user.password)
        cursor = conn.execute("""
            INSERT INTO users (tenant_id, email, password_hash, first_name, last_name, role, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 1)
        """, (user.tenant_id, user.email, password_hash, user.first_name, user.last_name, user.role))
        
        user_id = cursor.lastrowid
        conn.commit()
        
        return {
            "id": user_id,
            "email": user.email,
            "message": "User created successfully"
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    user: UserUpdate,
    current_user: dict = Depends(get_current_admin)
):
    """Update a user (admin only)"""
    conn = get_db()
    try:
        # Build update query dynamically
        updates = []
        params = []
        
        if user.email is not None:
            updates.append("email = ?")
            params.append(user.email)
        
        if user.first_name is not None:
            updates.append("first_name = ?")
            params.append(user.first_name)
        
        if user.last_name is not None:
            updates.append("last_name = ?")
            params.append(user.last_name)
        
        if user.role is not None:
            updates.append("role = ?")
            params.append(user.role)
        
        if user.is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if user.is_active else 0)
        
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        params.append(user_id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
        
        cursor = conn.execute(query, params)
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {"message": "User updated successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@router.delete("/users/{user_id}")
async def delete_user(user_id: int, current_user: dict = Depends(get_current_admin)):
    """Delete a user (admin only)"""
    conn = get_db()
    try:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {"message": "User deleted successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@router.get("/tenant/default-integrations")
async def get_default_integrations(current_user: dict = Depends(get_current_admin)):
    """Get default integration settings for new tenants (admin only)"""
    conn = get_db()
    try:
        from api.security import dec
        
        cursor = conn.execute("""
            SELECT setting_key, setting_value, encrypted
            FROM tenant_settings
            WHERE tenant_id = ?
        """, (current_user["tenant_id"],))
        
        settings = {}
        for row in cursor.fetchall():
            key = row["setting_key"]
            value = row["setting_value"]
            if row["encrypted"] and value:
                try:
                    value = dec(value)
                except:
                    value = ""
            settings[key] = value
        
        # Add default values for any missing settings
        default_settings = {
            "apify_token": "",
            "apify_webhook_secret": "",
            "phantombuster_api_key": "",
            "linkedin_li_at": "",
            "linkedin_jsessionid": "",
            "linkedin_cookies_json": "",
            "apify_li_cookie_secret_name": "",
            "sendgrid_api_key": "",
            "sendgrid_from_email": "",
            "sendgrid_from_name": "",
            "openai_api_key": "",
            "cufinder_api_key": "",
            "grok_api_key": ""
        }
        
        # Merge default settings with existing settings
        for key, default_value in default_settings.items():
            if key not in settings:
                settings[key] = default_value
        
        return settings
    except Exception as e:
        logger.error(f"Error fetching default integration settings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching integration settings: {str(e)}")
    finally:
        conn.close()

@router.post("/tenant/default-integrations")
async def set_default_integrations(
    settings: dict,
    current_user: dict = Depends(get_current_admin)
):
    """Set default integration settings for new tenants (admin only)"""
    conn = get_db()
    try:
        from api.security import enc
        
        # Define which settings should be encrypted
        encrypted_settings = {
            "apify_token", "apify_webhook_secret", "linkedin_li_at", 
            "linkedin_jsessionid", "linkedin_cookies_json", "cufinder_api_key",
            "sendgrid_api_key", "openai_api_key", "grok_api_key",
            "phantombuster_api_key", "apify_li_cookie_secret_name"
        }
        
        # Save each setting to the current user's tenant
        for key, value in settings.items():
            if value is not None and str(value).strip():  # Only save non-empty values
                encrypted = key in encrypted_settings
                stored_value = enc(str(value)) if encrypted else str(value)
                
                cursor = upsert_tenant_setting(conn, current_user["tenant_id"], key, stored_value, encrypted)
        
        conn.commit()
        logger.info(f"Default integration settings updated for tenant {current_user['tenant_id']}")
        
        return {"message": "Default integration settings updated successfully"}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving default integration settings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error saving integration settings: {str(e)}")
    finally:
        conn.close()

@router.post("/tenant/{tenant_id}/integrations")
async def set_tenant_integrations(
    tenant_id: int,
    settings: IntegrationSettings,
    current_user: dict = Depends(get_current_admin)
):
    """Set integration settings for a tenant (admin only)"""
    conn = get_db()
    try:
        # Check if tenant exists
        cursor = conn.execute("SELECT id FROM tenants WHERE id = ?", (tenant_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Store each non-null setting
        from api.security import enc
        
        settings_dict = settings.dict(exclude_none=True)
        for key, value in settings_dict.items():
            if value:
                encrypted_value = enc(value)
                upsert_tenant_setting(conn, tenant_id, key, encrypted_value, 1)
        
        conn.commit()
        return {"message": f"Integration settings updated for tenant {tenant_id}"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@router.get("/tenant/{tenant_id}/integrations")
async def get_tenant_integrations(
    tenant_id: int,
    current_user: dict = Depends(get_current_admin)
):
    """Get integration settings for a tenant (admin only)"""
    conn = get_db()
    try:
        from api.security import dec
        
        cursor = conn.execute("""
            SELECT setting_key, setting_value, encrypted
            FROM tenant_settings
            WHERE tenant_id = ?
        """, (tenant_id,))
        
        settings = {}
        for row in cursor.fetchall():
            key = row["setting_key"]
            value = row["setting_value"]
            if row["encrypted"] and value:
                try:
                    value = dec(value)
                except:
                    value = ""
            settings[key] = value
        
        return settings
    finally:
        conn.close()

@router.get("/users/{user_id}/integrations")
async def get_user_integrations(
    user_id: int,
    current_user: dict = Depends(get_current_admin)
):
    """Get integration settings for a specific user (admin only)"""
    conn = get_db()
    try:
        from api.security import dec
        
        # First verify user exists and get their tenant_id
        cursor = conn.execute("SELECT tenant_id FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get tenant-level integration settings for this user
        cursor = conn.execute("""
            SELECT setting_key, setting_value, encrypted, created_at, updated_at
            FROM tenant_settings
            WHERE tenant_id = ? AND setting_key IN (
                'apify_token', 'apify_webhook_secret', 'linkedin_li_at', 
                'linkedin_jsessionid', 'linkedin_cookies_json', 'cufinder_api_key',
                'sendgrid_api_key', 'openai_api_key', 'grok_api_key',
                'phantombuster_api_key', 'sendgrid_from_email', 'sendgrid_from_name'
            ) AND setting_value IS NOT NULL AND setting_value != ''
        """, (user_row["tenant_id"],))
        
        integrations = []
        for row in cursor.fetchall():
            provider = row["setting_key"]
            value = row["setting_value"]
            
            # Decrypt if necessary
            if row["encrypted"] and value:
                try:
                    value = dec(value)
                except:
                    value = ""
            
            # Create masked version for security
            if value:
                if len(value) <= 8:
                    masked_key = "*" * len(value)
                else:
                    masked_key = value[:4] + "*" * (len(value) - 8) + value[-4:]
                
                integrations.append({
                    "provider": provider,
                    "key": value,
                    "masked_key": masked_key,
                    "created_at": row["created_at"] or "",
                    "updated_at": row["updated_at"] or row["created_at"] or ""
                })
        
        return {"integrations": integrations}
    finally:
        conn.close()

@router.post("/users/{user_id}/integrations")
async def set_user_integrations(
    user_id: int,
    settings: IntegrationSettings,
    current_user: dict = Depends(get_current_admin)
):
    """Set integration settings for a specific user (admin only)"""
    conn = get_db()
    try:
        # First verify user exists and get their tenant_id
        cursor = conn.execute("SELECT tenant_id FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Set tenant-level integration settings for this user's tenant
        return await set_tenant_integrations(user_row["tenant_id"], settings, current_user)
    finally:
        conn.close()

@router.put("/users/{user_id}/integrations")
async def update_user_integrations(
    user_id: int,
    integration_data: dict,
    current_user: dict = Depends(get_current_admin)
):
    """Update integration settings for a specific user (admin only)"""
    conn = get_db()
    try:
        # First verify user exists and get their tenant_id
        cursor = conn.execute("SELECT tenant_id FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Extract provider and key from the request
        provider = integration_data.get("provider")
        key = integration_data.get("key")
        
        if not provider or not key:
            raise HTTPException(status_code=400, detail="Provider and key are required")
        
        # Define which settings should be encrypted
        encrypted_settings = {
            "apify_token", "apify_webhook_secret", "linkedin_li_at", 
            "linkedin_jsessionid", "linkedin_cookies_json", "cufinder_api_key",
            "sendgrid_api_key", "openai_api_key", "grok_api_key",
            "phantombuster_api_key"
        }
        
        # Save the setting
        from api.security import enc
        encrypted = provider in encrypted_settings
        stored_value = enc(str(key)) if encrypted else str(key)
        
        # Use database-agnostic upsert
        cursor = upsert_tenant_setting(conn, user_row["tenant_id"], provider, stored_value, encrypted)
        
        conn.commit()
        logger.info(f"Integration {provider} updated for user {user_id} (tenant {user_row['tenant_id']})")
        
        return {"message": f"{provider} integration updated successfully"}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating user integration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating integration: {str(e)}")
    finally:
        conn.close()

@router.delete("/users/{user_id}/integrations/{provider}")
async def delete_user_integration(
    user_id: int,
    provider: str,
    current_user: dict = Depends(get_current_admin)
):
    """Delete a specific integration setting for a user (admin only)"""
    conn = get_db()
    try:
        # First verify user exists and get their tenant_id
        cursor = conn.execute("SELECT tenant_id FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete the specific integration setting
        cursor = conn.execute("""
            DELETE FROM tenant_settings 
            WHERE tenant_id = ? AND setting_key = ?
        """, (user_row["tenant_id"], provider))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Integration not found")
        
        conn.commit()
        logger.info(f"Integration {provider} deleted for user {user_id} (tenant {user_row['tenant_id']})")
        
        return {"message": f"{provider} integration deleted successfully"}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting user integration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting integration: {str(e)}")
    finally:
        conn.close()

@router.delete("/users/{user_id}/integrations")
async def delete_user_integrations(
    user_id: int,
    current_user: dict = Depends(get_current_admin)
):
    """Delete/reset integration settings for a specific user (admin only)"""
    conn = get_db()
    try:
        # First verify user exists and get their tenant_id
        cursor = conn.execute("SELECT tenant_id FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete all tenant-level integration settings for this user's tenant
        conn.execute("DELETE FROM tenant_settings WHERE tenant_id = ?", (user_row["tenant_id"],))
        conn.commit()
        
        return {"message": f"Integration settings deleted for user {user_id}"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@router.get("/integration-settings")
async def get_admin_integration_settings(current_user: dict = Depends(get_current_admin)):
    """Get integration settings for admin interface (admin only)"""
    conn = get_db()
    try:
        from api.security import dec
        
        # Get the current user's tenant settings as default
        cursor = conn.execute("""
            SELECT setting_key, setting_value, encrypted
            FROM tenant_settings
            WHERE tenant_id = ?
        """, (current_user["tenant_id"],))
        
        settings = {}
        for row in cursor.fetchall():
            key = row["setting_key"]
            value = row["setting_value"]
            if row["encrypted"] and value:
                try:
                    value = dec(value)
                except:
                    value = ""
            settings[key] = value
        
        # Add default values for any missing settings
        default_settings = {
            "apify_token": "",
            "apify_webhook_secret": "",
            "linkedin_li_at": "",
            "linkedin_jsessionid": "",
            "linkedin_cookies_json": "",
            "cufinder_api_key": "",
            "sendgrid_api_key": "",
            "sendgrid_from_email": "",
            "sendgrid_from_name": "",
            "openai_api_key": "",
            "openai_model": "gpt-4o",
            "grok_api_key": "",
            "daily_email_limit": 500,
            "delay_between_emails": 60,
            "enable_email_queue": True,
            "queue_processing_interval": 30
        }
        
        # Merge default settings with existing settings
        for key, default_value in default_settings.items():
            if key not in settings:
                settings[key] = default_value
        
        return settings
    except Exception as e:
        logger.error(f"Error fetching admin integration settings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching integration settings: {str(e)}")
    finally:
        conn.close()

@router.post("/integration-settings")
async def save_admin_integration_settings(
    settings: dict,
    current_user: dict = Depends(get_current_admin)
):
    """Save integration settings for admin interface (admin only)"""
    conn = get_db()
    try:
        from api.security import enc
        
        # Define which settings should be encrypted
        encrypted_settings = {
            "apify_token", "apify_webhook_secret", "linkedin_li_at", 
            "linkedin_jsessionid", "linkedin_cookies_json", "cufinder_api_key",
            "sendgrid_api_key", "openai_api_key"
        }
        
        # Save each setting
        for key, value in settings.items():
            if value is not None and str(value).strip():  # Only save non-empty values
                encrypted = key in encrypted_settings
                stored_value = enc(str(value)) if encrypted else str(value)
                
                cursor = upsert_tenant_setting(conn, current_user["tenant_id"], key, stored_value, encrypted)
        
        conn.commit()
        logger.info(f"Admin integration settings updated for tenant {current_user['tenant_id']}")
        
        return {"message": "Settings saved successfully"}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving admin integration settings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error saving integration settings: {str(e)}")
    finally:
        conn.close()
