"""
Organization Management API Routes
September 2025 - Enterprise Branding and Settings

Provides APIs for organization theme customization, logo management,
and company-wide settings configuration.
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
import boto3
from botocore.exceptions import ClientError

from .deps import get_current_user, get_tenant_repository
from .tenant_repository import TenantRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/organization", tags=["organization"])

class OrganizationTheme(BaseModel):
    """Organization theme settings"""
    primary_color: str
    secondary_color: str
    accent_color: Optional[str] = None
    background_color: Optional[str] = "#ffffff"
    text_color: Optional[str] = "#000000"
    font_family: Optional[str] = "Inter"
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None

    @field_validator('primary_color', 'secondary_color', 'accent_color', 'background_color', 'text_color')
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        if v and not v.startswith('#'):
            raise ValueError('Color must be a valid hex color starting with #')
        if v and len(v) not in [4, 7]:  # #RGB or #RRGGBB
            raise ValueError('Color must be a valid hex color format')
        return v

class OrganizationSettings(BaseModel):
    """Organization settings"""
    company_name: str
    industry: Optional[str] = None
    company_size: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    timezone: Optional[str] = "UTC"
    business_hours_start: Optional[str] = "09:00"
    business_hours_end: Optional[str] = "17:00"
    email_domain: Optional[str] = None

class OrganizationSettingsUpdate(BaseModel):
    """Update organization settings"""
    theme: Optional[OrganizationTheme] = None
    settings: Optional[OrganizationSettings] = None

class OrganizationResponse(BaseModel):
    """Organization response"""
    id: int
    name: str
    theme: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str

@router.get("/settings", response_model=OrganizationResponse)
async def get_organization_settings(
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
):
    """Get organization settings and theme"""

    try:
        # Ensure organizations table exists
        repo.execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id)
            )
            """
        )

        # Insert default organization if none exists for this tenant
        repo.execute(
            """
            INSERT INTO organizations (tenant_id, name, slug, created_at, updated_at)
            SELECT :tenant_id, 'Default Organization', 'default', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (SELECT 1 FROM organizations WHERE tenant_id = :tenant_id)
            """,
            {},
        )

        org_row = repo.fetch_one(
            """
            SELECT id, name, created_at, updated_at
            FROM organizations
            WHERE tenant_id = :tenant_id
            """,
            {},
        )

        if not org_row:
            raise HTTPException(status_code=404, detail="Organization not found")

        organization_id = current_user.get("organization_id") or org_row["id"]

        settings_row = repo.fetch_one(
            """
            SELECT theme_config, general_settings, created_at, updated_at
            FROM organization_settings
            WHERE organization_id = :organization_id AND tenant_id = :tenant_id
            """,
            {"organization_id": organization_id},
        )

        theme = None
        settings = None

        if settings_row:
            settings_dict = dict(settings_row)

            if settings_dict.get("theme_config"):
                try:
                    theme = json.loads(settings_dict["theme_config"])
                except (json.JSONDecodeError, TypeError):
                    theme = None

            if settings_dict.get("general_settings"):
                try:
                    settings = json.loads(settings_dict["general_settings"])
                except (json.JSONDecodeError, TypeError):
                    settings = None

        created_at = org_row["created_at"]
        updated_at = org_row["updated_at"]

        return OrganizationResponse(
            id=org_row["id"],
            name=org_row["name"],
            theme=theme,
            settings=settings,
            created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
            updated_at=updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get organization settings: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve organization settings")

@router.post("/settings")
async def update_organization_settings(
    update_data: OrganizationSettingsUpdate,
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repository),
):
    """Update organization settings and theme"""

    try:
        repo.execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS organization_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                tenant_id INTEGER NOT NULL,
                theme_config TEXT,
                general_settings TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                UNIQUE(organization_id)
            )
            """
        )
        repo.ensure_column(
            "organization_settings",
            "tenant_id",
            "tenant_id INTEGER NOT NULL DEFAULT 0",
        )

        org_row = repo.fetch_one(
            """
            SELECT id
            FROM organizations
            WHERE tenant_id = :tenant_id
            """,
            {},
        )

        if not org_row:
            raise HTTPException(status_code=404, detail="Organization not found")

        organization_id = current_user.get("organization_id") or org_row["id"]

        existing_row = repo.fetch_one(
            """
            SELECT theme_config, general_settings
            FROM organization_settings
            WHERE organization_id = :organization_id AND tenant_id = :tenant_id
            """,
            {"organization_id": organization_id},
        )

        existing_theme: Dict[str, Any] = {}
        existing_settings: Dict[str, Any] = {}

        if existing_row:
            existing_dict = dict(existing_row)

            if existing_dict.get("theme_config"):
                try:
                    existing_theme = json.loads(existing_dict["theme_config"])
                except (json.JSONDecodeError, TypeError):
                    existing_theme = {}

            if existing_dict.get("general_settings"):
                try:
                    existing_settings = json.loads(existing_dict["general_settings"])
                except (json.JSONDecodeError, TypeError):
                    existing_settings = {}

        if update_data.theme:
            existing_theme.update(update_data.theme.dict(exclude_unset=True))

        if update_data.settings:
            existing_settings.update(update_data.settings.dict(exclude_unset=True))

        theme_json = json.dumps(existing_theme) if existing_theme else None
        settings_json = json.dumps(existing_settings) if existing_settings else None

        repo.execute(
            """
            INSERT INTO organization_settings (
                organization_id,
                tenant_id,
                theme_config,
                general_settings
            )
            VALUES (:organization_id, :tenant_id, :theme_config, :general_settings)
            ON CONFLICT(organization_id) DO UPDATE SET
                theme_config = excluded.theme_config,
                general_settings = excluded.general_settings,
                tenant_id = excluded.tenant_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            {
                "organization_id": organization_id,
                "theme_config": theme_json,
                "general_settings": settings_json,
            },
        )

        if update_data.settings and update_data.settings.company_name:
            repo.execute(
                """
                UPDATE organizations
                SET name = :company_name,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :organization_id AND tenant_id = :tenant_id
                """,
                {
                    "organization_id": organization_id,
                    "company_name": update_data.settings.company_name,
                },
            )

        return {"status": "success", "message": "Organization settings updated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update organization settings: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update organization settings")

@router.post("/logo/upload")
async def upload_logo(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """Upload organization logo to S3 and update settings"""

    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Validate file type
    allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml']
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(allowed_types)}"
        )

    # Validate file size (max 5MB)
    max_size = 5 * 1024 * 1024  # 5MB
    file_content = await file.read()
    if len(file_content) > max_size:
        raise HTTPException(status_code=400, detail="File size too large. Maximum 5MB allowed.")

    try:
        # Initialize S3 client (if available)
        s3_client = None
        bucket_name = None

        try:
            import os
            aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
            aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
            bucket_name = os.getenv('AWS_S3_BUCKET', 'vouchlink-ai-organization-assets')

            if aws_access_key and aws_secret_key:
                s3_client = boto3.client(
                    's3',
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_key
                )
        except ImportError:
            logger.warning("boto3 not available, falling back to local storage")

        # Generate file key
        file_extension = file.filename.split('.')[-1] if '.' in file.filename else 'png'
        file_key = f"organizations/{organization_id}/logo.{file_extension}"

        logo_url = None

        if s3_client and bucket_name:
            try:
                # Upload to S3
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=file_key,
                    Body=file_content,
                    ContentType=file.content_type,
                    CacheControl='max-age=31536000',  # 1 year cache
                    ACL='public-read'
                )

                logo_url = f"https://{bucket_name}.s3.amazonaws.com/{file_key}"
                logger.info(f"Logo uploaded to S3: {logo_url}")

            except ClientError as e:
                logger.error(f"S3 upload failed: {e}")
                # Fall through to local storage

        if not logo_url:
            # Local storage fallback
            import os
            upload_dir = "/tmp/organization_assets"
            os.makedirs(upload_dir, exist_ok=True)

            local_path = f"{upload_dir}/org_{organization_id}_logo.{file_extension}"
            with open(local_path, "wb") as f:
                f.write(file_content)

            logo_url = f"/api/organization/assets/org_{organization_id}_logo.{file_extension}"
            logger.info(f"Logo stored locally: {local_path}")

        # Update organization theme with new logo URL
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Get existing theme
            cursor.execute("""
                SELECT theme_config FROM organization_settings WHERE organization_id = ?
            """, (organization_id,))

            existing_row = cursor.fetchone()
            theme_config = {}

            if existing_row and existing_row[0]:
                try:
                    theme_config = json.loads(existing_row[0])
                except (json.JSONDecodeError, TypeError):
                    theme_config = {}

            # Update logo URL
            theme_config['logo_url'] = logo_url

            # Update or insert
            if existing_row:
                cursor.execute("""
                    UPDATE organization_settings
                    SET theme_config = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = ?
                """, (json.dumps(theme_config), organization_id))
            else:
                cursor.execute("""
                    INSERT INTO organization_settings (organization_id, theme_config)
                    VALUES (?, ?)
                """, (organization_id, json.dumps(theme_config)))

            conn.commit()

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
        return {
            "success": True,
            "logo_url": logo_url,
            "message": "Logo uploaded successfully"
        }

    except Exception as e:
        logger.error(f"Logo upload failed: {e}")
        raise HTTPException(status_code=500, detail="Logo upload failed")

@router.delete("/logo")
async def delete_logo(current_user: dict = Depends(get_current_user)):
    """Remove organization logo"""

    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Get existing theme
            cursor.execute("""
                SELECT theme_config FROM organization_settings WHERE organization_id = ?
            """, (organization_id,))

            existing_row = cursor.fetchone()
            if not existing_row or not existing_row[0]:
                return {"success": True, "message": "No logo to remove"}

            try:
                theme_config = json.loads(existing_row[0])
            except (json.JSONDecodeError, TypeError):
                return {"success": True, "message": "No logo to remove"}

            # Remove logo URL
            if 'logo_url' in theme_config:
                del theme_config['logo_url']

            # Update database
            cursor.execute("""
                UPDATE organization_settings
                SET theme_config = ?, updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = ?
            """, (json.dumps(theme_config), organization_id))

            conn.commit()

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
        return {"success": True, "message": "Logo removed successfully"}

    except Exception as e:
        logger.error(f"Logo deletion failed: {e}")
        raise HTTPException(status_code=500, detail="Logo deletion failed")

@router.get("/theme")
async def get_organization_theme(current_user: dict = Depends(get_current_user)):
    """Get organization theme for frontend styling"""

    organization_id = current_user.get("organization_id")
    if not organization_id:
        # Return default theme for users without organization
        return {
            "primary_color": "#3b82f6",
            "secondary_color": "#64748b",
            "background_color": "#ffffff",
            "text_color": "#000000",
            "font_family": "Inter"
        }

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            cursor.execute("""
                SELECT theme_config FROM organization_settings WHERE organization_id = ?
            """, (organization_id,))

            row = cursor.fetchone()

            if row and row[0]:
                try:
                    theme = json.loads(row[0])
                    return theme
                except (json.JSONDecodeError, TypeError):
                    pass

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
        # Return default theme
        return {
            "primary_color": "#3b82f6",
            "secondary_color": "#64748b",
            "background_color": "#ffffff",
            "text_color": "#000000",
            "font_family": "Inter"
        }

    except Exception as e:
        logger.error(f"Failed to get organization theme: {e}")
        # Return default theme on error
        return {
            "primary_color": "#3b82f6",
            "secondary_color": "#64748b",
            "background_color": "#ffffff",
            "text_color": "#000000",
            "font_family": "Inter"
        }
