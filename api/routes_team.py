"""
Team Members Management API Routes
September 2025 - Corporate Team and LinkedIn Cookie Management

Provides APIs for managing team members, their LinkedIn sessions,
and cookie upload functionality for collaborative warm introductions.
"""

import logging
import json
import secrets
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from core.roles import VALID_ROLES, normalize_role

from api.deps_identity_stub import get_current_user, get_current_admin
from .auth import hash_password, role_guard
from .mt_db import get_db
from .security import enc, dec
from services.audit_logging_service import audit_logger, AuditEventType, AuditSeverity
from services.linkedin_cookie_verifier import verify_linkedin_cookies, VerificationStatus
from services.centralized_logging_service import LogCategory, LogLevel, log_structured

logger = logging.getLogger(__name__)

# Mounted under prefix="/api" from api.main
router = APIRouter(prefix="/team", tags=["team"])

TEAM_MANAGER_ROLES = ("admin",)


def _team_log(level: LogLevel, message: str, current_user: dict, **extra) -> None:
    """Emit a structured log for roster/cookie actions."""
    log_structured(
        level,
        message,
        category=LogCategory.BUSINESS,
        tenant_id=str(current_user.get("tenant_id")) if current_user else None,
        user_id=str(current_user.get("id")) if current_user else None,
        **extra,
    )

class TeamMember(BaseModel):
    """Team member data model"""
    email: str
    first_name: str
    last_name: str
    role: str = "user"
    linkedin_url: Optional[str] = None
    position: Optional[str] = None

    @field_validator('linkedin_url')
    def validate_linkedin_url(cls, v: Optional[str]) -> Optional[str]:
        if v and not v.startswith('https://www.linkedin.com/'):
            raise ValueError('LinkedIn URL must start with https://www.linkedin.com/')
        return v

    @field_validator('role')
    def validate_role(cls, v: str) -> str:
        normalized = normalize_role(v)
        if normalized not in VALID_ROLES:
            raise ValueError(f'Role must be one of: {", ".join(sorted(VALID_ROLES))}')
        return normalized

    @field_validator('email')
    def validate_email(cls, v: str) -> str:
        if '@' not in v or '.' not in v:
            raise ValueError('Invalid email format')
        return v

class TeamMemberUpdate(BaseModel):
    """Team member update model"""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    linkedin_url: Optional[str] = None
    position: Optional[str] = None
    email: Optional[str] = None

    @field_validator('role')
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if v == "":
                raise ValueError('Role cannot be empty')
            normalized = normalize_role(v)
            if normalized not in VALID_ROLES:
                raise ValueError(f'Role must be one of: {", ".join(sorted(VALID_ROLES))}')
            return normalized
        return v

class TeamMemberResponse(BaseModel):
    """Team member response model"""
    id: int
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str = "user"
    linkedin_url: Optional[str] = None
    position: Optional[str] = None
    cookie_status: str = "none"
    last_cookie_upload: Optional[str] = None
    created_at: str

class LinkedInCookieUpload(BaseModel):
    """LinkedIn cookie upload model"""
    li_at: str
    jsessionid: Optional[str] = None
    user_agent: Optional[str] = None
    label: Optional[str] = None

@router.get("/members", response_model=List[TeamMemberResponse])
async def get_team_members(current_user: dict = Depends(get_current_user)):
    """Get all team members for the organization"""

    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    _team_log(
        LogLevel.INFO,
        "Fetching team member roster",
        current_user,
        organization_id=str(organization_id),
        operation="list_members",
    )

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Get team members with their LinkedIn cookie status
            cursor.execute("""
                SELECT
                    tm.id,
                    tm.email,
                    tm.first_name,
                    tm.last_name,
                    tm.role,
                    tm.linkedin_profile_url,
                    tm.job_title,
                    tm.created_at,
                    ls.is_active,
                    ls.last_verified_at,
                    ls.created_at as cookie_created_at
                FROM team_members tm
                LEFT JOIN linkedin_sessions ls ON tm.user_id = ls.user_id AND ls.is_active = 1
                WHERE tm.organization_id = ?
                ORDER BY tm.created_at DESC
            """, (organization_id,))

            members = []
            for row in cursor.fetchall():
                row_dict = dict(row)

                # Determine cookie status
                cookie_status = "none"
                last_cookie_upload = None

                if row_dict.get('is_active'):
                    cookie_status = "active"
                    last_cookie_upload = row_dict.get('cookie_created_at')
                elif row_dict.get('cookie_created_at'):
                    cookie_status = "inactive"
                    last_cookie_upload = row_dict.get('cookie_created_at')

                members.append(TeamMemberResponse(
                    id=row_dict['id'],
                    email=row_dict['email'],
                    first_name=row_dict['first_name'],
                    last_name=row_dict['last_name'],
                    role=normalize_role(row_dict['role']),
                    linkedin_url=row_dict.get('linkedin_profile_url'),
                    position=row_dict.get('job_title'),
                    cookie_status=cookie_status,
                    last_cookie_upload=last_cookie_upload,
                    created_at=row_dict['created_at'].isoformat() if row_dict['created_at'] else datetime.utcnow().isoformat()
                ))

            return members

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except Exception as e:
        _team_log(
            LogLevel.ERROR,
            "Failed to fetch team member roster",
            current_user,
            exc_info=e,
            organization_id=str(organization_id),
            operation="list_members",
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve team members")

@router.post("/members", response_model=TeamMemberResponse)
async def create_team_member(
    member: TeamMember,
    current_user: dict = Depends(get_current_admin)
):
    """Create a new team member"""

    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    _team_log(
        LogLevel.INFO,
        "Creating team member",
        current_user,
        organization_id=str(organization_id),
        target_email=member.email,
        operation="create_member",
    )

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Check if member with same email already exists
            cursor.execute("""
                SELECT id FROM team_members
                WHERE organization_id = ? AND email = ?
            """, (organization_id, member.email))

            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="Team member with this email already exists")

            # Create new team member
            cursor.execute("""
                INSERT INTO team_members (
                    organization_id, email, first_name, last_name, role,
                    linkedin_profile_url, job_title, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                organization_id,
                member.email,
                member.first_name,
                member.last_name,
                member.role,
                member.linkedin_url,
                member.position,
                'active',
                datetime.utcnow()
            ))

            member_id = cursor.lastrowid
            conn.commit()

            response_payload = TeamMemberResponse(
                id=member_id,
                email=member.email,
                first_name=member.first_name,
                last_name=member.last_name,
                role=member.role,
                linkedin_url=member.linkedin_url,
                position=member.position,
                cookie_status="none",
                created_at=datetime.utcnow().isoformat()
            )

            await audit_logger.log_event(
                tenant_id=str(organization_id),
                user_id=str(current_user.get("id")),
                event_type=AuditEventType.USER_CREATED,
                action="team_member_created",
                resource_type="team_member",
                resource_id=str(member_id),
                severity=AuditSeverity.MEDIUM,
                details={
                    "email": member.email,
                    "role": member.role,
                    "first_name": member.first_name,
                    "last_name": member.last_name,
                },
                success=True,
            )

            _team_log(
                LogLevel.INFO,
                "Team member created",
                current_user,
                organization_id=str(organization_id),
                member_id=str(member_id),
                target_email=member.email,
                operation="create_member",
            )

            return response_payload

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except HTTPException:
        raise
    except Exception as e:
        _team_log(
            LogLevel.ERROR,
            "Failed to create team member",
            current_user,
            exc_info=e,
            organization_id=str(organization_id),
            target_email=member.email,
            operation="create_member",
        )
        raise HTTPException(status_code=500, detail="Failed to create team member")

@router.put("/members/{member_id}", response_model=TeamMemberResponse)
async def update_team_member(
    member_id: int,
    update_data: TeamMemberUpdate,
    current_user: dict = Depends(role_guard(*TEAM_MANAGER_ROLES))
):
    """Update a team member"""

    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    _team_log(
        LogLevel.INFO,
        "Updating team member",
        current_user,
        organization_id=str(organization_id),
        member_id=str(member_id),
        changes_requested=update_data.model_dump(exclude_none=True),
        operation="update_member",
    )

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Check if member exists and belongs to organization
            cursor.execute("""
                SELECT id, user_id, email, first_name, last_name, role FROM team_members
                WHERE id = ? AND organization_id = ?
            """, (member_id, organization_id))

            member = cursor.fetchone()
            if not member:
                raise HTTPException(status_code=404, detail="Team member not found")

            member_dict = dict(member)
            changes: Dict[str, Dict[str, Any]] = {}

            # Build update query
            update_fields = []
            update_values = []

            if update_data.first_name is not None:
                update_fields.append("first_name = ?")
                update_values.append(update_data.first_name)
                if update_data.first_name != member_dict.get("first_name"):
                    changes["first_name"] = {
                        "old": member_dict.get("first_name"),
                        "new": update_data.first_name,
                    }

            if update_data.last_name is not None:
                update_fields.append("last_name = ?")
                update_values.append(update_data.last_name)
                if update_data.last_name != member_dict.get("last_name"):
                    changes["last_name"] = {
                        "old": member_dict.get("last_name"),
                        "new": update_data.last_name,
                    }

            if update_data.role is not None:
                update_fields.append("role = ?")
                update_values.append(update_data.role)
                if update_data.role != member_dict.get("role"):
                    changes["role"] = {
                        "old": member_dict.get("role"),
                        "new": update_data.role,
                    }
                linked_user_id = member_dict.get("user_id")
                if linked_user_id:
                    try:
                        cursor.execute(
                            """
                            UPDATE users
                            SET role = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (update_data.role, linked_user_id),
                        )
                    except Exception:
                        cursor.execute(
                            """
                            UPDATE users
                            SET role = ?
                            WHERE id = ?
                            """,
                            (update_data.role, linked_user_id),
                        )

            if update_data.email is not None:
                update_fields.append("email = ?")
                update_values.append(update_data.email)
                if update_data.email != member_dict.get("email"):
                    changes["email"] = {
                        "old": member_dict.get("email"),
                        "new": update_data.email,
                    }

            if update_data.linkedin_url is not None:
                update_fields.append("linkedin_profile_url = ?")
                update_values.append(update_data.linkedin_url)

            if update_data.position is not None:
                update_fields.append("job_title = ?")
                update_values.append(update_data.position)

            if update_fields:
                update_values.extend([datetime.utcnow(), member_id, organization_id])
                cursor.execute(f"""
                    UPDATE team_members
                    SET {', '.join(update_fields)}, updated_at = ?
                    WHERE id = ? AND organization_id = ?
                """, update_values)
                conn.commit()

            # Return updated member
            cursor.execute("""
                SELECT
                    tm.id, tm.email, tm.first_name, tm.last_name, tm.role,
                    tm.linkedin_profile_url, tm.job_title, tm.created_at,
                    ls.is_active, ls.created_at as cookie_created_at
                FROM team_members tm
                LEFT JOIN linkedin_sessions ls ON tm.user_id = ls.user_id AND ls.is_active = 1
                WHERE tm.id = ? AND tm.organization_id = ?
            """, (member_id, organization_id))

            updated_member = dict(cursor.fetchone())

            cookie_status = "none"
            if updated_member.get('is_active'):
                cookie_status = "active"
            elif updated_member.get('cookie_created_at'):
                cookie_status = "inactive"

            response_payload = TeamMemberResponse(
                id=updated_member['id'],
                email=updated_member['email'],
                first_name=updated_member['first_name'],
                last_name=updated_member['last_name'],
                role=updated_member['role'],
                linkedin_url=updated_member.get('linkedin_profile_url'),
                position=updated_member.get('job_title'),
                cookie_status=cookie_status,
                created_at=updated_member['created_at'].isoformat() if updated_member['created_at'] else datetime.utcnow().isoformat()
            )

            if changes:
                await audit_logger.log_event(
                    tenant_id=str(organization_id),
                    user_id=str(current_user.get("id")),
                    event_type=AuditEventType.USER_UPDATED,
                    action="team_member_updated",
                    resource_type="team_member",
                    resource_id=str(member_id),
                    severity=AuditSeverity.LOW,
                    details={
                        "changes": changes,
                        "email": updated_member.get("email"),
                    },
                    success=True,
            )

            _team_log(
                LogLevel.INFO,
                "Team member updated",
                current_user,
                organization_id=str(organization_id),
                member_id=str(member_id),
                operation="update_member",
                changes_detected=changes,
            )

            return response_payload

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except HTTPException:
        raise
    except Exception as e:
        _team_log(
            LogLevel.ERROR,
            "Failed to update team member",
            current_user,
            exc_info=e,
            organization_id=str(organization_id),
            member_id=str(member_id),
            operation="update_member",
        )
        raise HTTPException(status_code=500, detail="Failed to update team member")

@router.delete("/members/{member_id}")
async def delete_team_member(
    member_id: int,
    current_user: dict = Depends(get_current_admin)
):
    """Delete a team member"""

    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Check if member exists
            cursor.execute("""
                SELECT id FROM team_members WHERE id = ? AND organization_id = ?
            """, (member_id, organization_id))

            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Team member not found")

            # Delete associated LinkedIn sessions if any
            cursor.execute("""
                DELETE FROM linkedin_sessions
                WHERE user_id IN (
                    SELECT user_id FROM team_members
                    WHERE id = ? AND organization_id = ?
                )
            """, (member_id, organization_id))

            # Delete team member
            cursor.execute("""
                DELETE FROM team_members WHERE id = ? AND organization_id = ?
            """, (member_id, organization_id))

            conn.commit()

            await audit_logger.log_event(
                tenant_id=str(organization_id),
                user_id=str(current_user.get("id")),
                event_type=AuditEventType.USER_DELETED,
                action="team_member_deleted",
                resource_type="team_member",
                resource_id=str(member_id),
                severity=AuditSeverity.MEDIUM,
                details={"member_id": member_id},
                success=True,
            )

            return {"success": True, "message": "Team member deleted successfully"}

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete team member: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete team member")

@router.post("/members/{member_id}/upload-cookies")
async def upload_member_cookies(
    member_id: int,
    cookie_data: LinkedInCookieUpload,
    current_user: dict = Depends(role_guard(*TEAM_MANAGER_ROLES))
):
    """Upload LinkedIn cookies for a team member"""

    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    user_id = current_user.get("id")

    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Check if member exists
            cursor.execute("""
                SELECT id, first_name, last_name, user_id FROM team_members
                WHERE id = ? AND organization_id = ?
            """, (member_id, organization_id))

            member = cursor.fetchone()
            if not member:
                raise HTTPException(status_code=404, detail="Team member not found")

            member_dict = dict(member)

            # Verify the cookies first
            verification_result = await verify_linkedin_cookies(
                li_at=cookie_data.li_at,
                jsessionid=cookie_data.jsessionid,
                tenant_id=organization_id,
                user_id=user_id
            )

            if verification_result.status != VerificationStatus.VALID:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cookie verification failed: {verification_result.error_message}"
                )

            # Deactivate any existing cookies for this member
            if member_dict.get('user_id'):
                cursor.execute("""
                    UPDATE linkedin_sessions
                    SET is_active = 0
                    WHERE user_id = ? AND tenant_id = ?
                """, (member_dict['user_id'], organization_id))

            # Create or get user account for this team member
            team_user_id = member_dict.get('user_id')
            if not team_user_id:
                # Create a system user for this team member
                cursor.execute("""
                    INSERT INTO users (email, password_hash, tenant_id, created_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    f"team.{member_id}@system.local",
                    hash_password(secrets.token_urlsafe(32)),
                    organization_id,
                    datetime.utcnow()
                ))
                team_user_id = cursor.lastrowid

                # Update team member with user_id
                cursor.execute("""
                    UPDATE team_members SET user_id = ? WHERE id = ?
                """, (team_user_id, member_id))

            # Insert new LinkedIn session
            member_name = f"{member_dict.get('first_name', '')} {member_dict.get('last_name', '')}".strip()
            cursor.execute("""
                INSERT INTO linkedin_sessions (
                    tenant_id, user_id, label, li_at_encrypted, jsessionid_encrypted,
                    user_agent, is_active, last_verified_at, created_at, username, full_name
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """, (
                organization_id,
                team_user_id,
                cookie_data.label or f"{member_name} - {datetime.utcnow().strftime('%Y-%m-%d')}",
                enc(cookie_data.li_at),
                enc(cookie_data.jsessionid) if cookie_data.jsessionid else None,
                cookie_data.user_agent,
                datetime.utcnow(),
                datetime.utcnow(),
                verification_result.username,
                verification_result.full_name
            ))

            conn.commit()

            return {
                "success": True,
                "message": f"LinkedIn cookies uploaded successfully for {member_name}",
                "verification_status": "verified",
                "username": verification_result.username,
                "full_name": verification_result.full_name
            }

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload cookies for team member: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload cookies")

@router.get("/members/{member_id}/cookie-status")
async def get_member_cookie_status(
    member_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Get LinkedIn cookie status for a team member"""

    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            cursor.execute("""
                SELECT
                    tm.first_name,
                    tm.last_name,
                    ls.is_active,
                    ls.last_verified_at,
                    ls.created_at,
                    ls.username,
                    ls.full_name,
                    ls.label
                FROM team_members tm
                LEFT JOIN linkedin_sessions ls ON tm.user_id = ls.user_id
                WHERE tm.id = ? AND tm.organization_id = ?
                ORDER BY ls.created_at DESC
                LIMIT 1
            """, (member_id, organization_id))

            result = cursor.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="Team member not found")

            result_dict = dict(result)

            status = "none"
            if result_dict.get('is_active'):
                status = "active"
            elif result_dict.get('created_at'):
                status = "inactive"

            member_name = f"{result_dict.get('first_name', '')} {result_dict.get('last_name', '')}".strip()

            return {
                "member_name": member_name,
                "cookie_status": status,
                "last_verified_at": result_dict.get('last_verified_at'),
                "uploaded_at": result_dict.get('created_at'),
                "username": result_dict.get('username'),
                "full_name": result_dict.get('full_name'),
                "label": result_dict.get('label')
            }

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cookie status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get cookie status")

@router.post("/members/{member_id}/verify-cookies")
async def verify_member_cookies(
    member_id: int,
    current_user: dict = Depends(role_guard(*TEAM_MANAGER_ROLES))
):
    """Verify LinkedIn cookies for a team member"""

    organization_id = current_user.get("organization_id") or current_user.get("tenant_id")
    user_id = current_user.get("id")

    if not organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        conn = get_db()
        cursor = conn.cursor()
        try:

            # Get member and their active cookies
            cursor.execute("""
                SELECT
                    tm.first_name,
                    tm.last_name,
                    ls.li_at_encrypted,
                    ls.jsessionid_encrypted,
                    ls.id as session_id
                FROM team_members tm
                JOIN linkedin_sessions ls ON tm.user_id = ls.user_id
                WHERE tm.id = ? AND tm.organization_id = ? AND ls.is_active = 1
            """, (member_id, organization_id))

            result = cursor.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="No active LinkedIn session found for this team member")

            result_dict = dict(result)
            member_name = f"{result_dict.get('first_name', '')} {result_dict.get('last_name', '')}".strip()

            # Decrypt and verify cookies
            li_at = dec(result_dict['li_at_encrypted'])
            jsessionid = dec(result_dict['jsessionid_encrypted']) if result_dict['jsessionid_encrypted'] else None

            verification_result = await verify_linkedin_cookies(
                li_at=li_at,
                jsessionid=jsessionid,
                tenant_id=organization_id,
                user_id=user_id
            )

            # Update session status based on verification
            if verification_result.status == VerificationStatus.VALID:
                cursor.execute("""
                    UPDATE linkedin_sessions
                    SET last_verified_at = ?, username = ?, full_name = ?
                    WHERE id = ?
                """, (
                    datetime.utcnow(),
                    verification_result.username,
                    verification_result.full_name,
                    result_dict['session_id']
                ))
                conn.commit()

                return {
                    "success": True,
                    "status": "verified",
                    "message": f"Cookies verified successfully for {member_name}",
                    "username": verification_result.username,
                    "full_name": verification_result.full_name
                }
            else:
                cursor.execute("""
                    UPDATE linkedin_sessions SET is_active = 0 WHERE id = ?
                """, (result_dict['session_id'],))
                conn.commit()

                return {
                    "success": False,
                    "status": "invalid",
                    "message": f"Cookie verification failed: {verification_result.error_message}"
                }

        finally:
            try:
                cursor.close()
            except Exception:
                pass  # Cursor might already be closed
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify cookies: {e}")
        raise HTTPException(status_code=500, detail="Failed to verify cookies")
