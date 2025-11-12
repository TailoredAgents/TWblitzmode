"""
Email API Routes
FastAPI endpoints for email enrichment, campaigns, and analytics
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, EmailStr, FieldValidationInfo, field_validator
import asyncio

from api.database import get_db
from api.deps_identity_stub import get_current_user

try:
    from services.email_service import email_service
    from services.error_classifier import error_classifier
except ImportError:
    # Services may not be available in all environments
    email_service = None
    error_classifier = None

try:
    from core.settings import settings
except ImportError:
    settings = None


logger = logging.getLogger(__name__)

# Initialize router (prefix will be added by main app)
router = APIRouter(prefix="/email", tags=["email"])

# Pydantic models for request/response validation
class EmailEnrichmentRequest(BaseModel):
    contact_ids: List[int]
    force_refresh: bool = False
    min_confidence: float = 0.0
    # Optional overrides to improve enrichment quality from UI
    override_company: Optional[str] = None
    override_company_domain: Optional[str] = None
    
    @field_validator('contact_ids')
    def validate_contact_ids(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("At least one contact ID is required")
        if len(v) > 100:
            raise ValueError("Maximum 100 contacts per request")
        return v

class EmailEnrichmentResponse(BaseModel):
    enriched_count: int
    failed_count: int
    already_had_email: int
    high_confidence: int
    low_confidence: int
    suppressed: int
    total_cost: float
    results: List[Dict]

# Request/Response models for mutual connection enrichment
class MutualConnectionEnrichmentRequest(BaseModel):
    connections: List[Dict]  # Array of connection objects from frontend
    
class MutualConnectionEnrichmentResponse(BaseModel):
    success: bool
    enriched: List[Dict]
    failed: List[Dict]
    total_cost: float

class EmailCampaignRequest(BaseModel):
    prospect_id: int
    introducer_ids: List[int]
    message_type: str = "warm_intro"
    use_ai_generation: bool = True
    channel_preference: str = "email_first"
    schedule_send: Optional[datetime] = None
    ab_test: bool = False
    
    @field_validator('message_type')
    def validate_message_type(cls, v: str) -> str:
        allowed_types = ['warm_intro', 'follow_up', 'direct_outreach', 'referral_request', 'thank_you', 're_engagement']
        if v not in allowed_types:
            raise ValueError(f"Message type must be one of: {allowed_types}")
        return v
    
    @field_validator('channel_preference')
    def validate_channel_preference(cls, v: str) -> str:
        allowed_prefs = ['email_only', 'linkedin_only', 'email_first', 'linkedin_first', 'hybrid']
        if v not in allowed_prefs:
            raise ValueError(f"Channel preference must be one of: {allowed_prefs}")
        return v

class EmailCampaignResponse(BaseModel):
    id: int
    prospect_id: int
    prospect_name: str
    total_messages: int
    status: str
    messages: List[Dict]

class EmailSettingsRequest(BaseModel):
    from_email: Optional[EmailStr] = None
    from_name: Optional[str] = None
    reply_to_email: Optional[EmailStr] = None
    sendgrid_api_key: Optional[str] = None
    cufinder_api_key: Optional[str] = None
    daily_limit: Optional[int] = None
    
    @field_validator('daily_limit')
    def validate_daily_limit(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 1 or v > 10000):
            raise ValueError("Daily limit must be between 1 and 10000")
        return v

class EmailSettingsResponse(BaseModel):
    success: bool
    domain_verification: Optional[Dict] = None
    message: Optional[str] = None

class MetricsResponse(BaseModel):
    overall_stats: Dict
    rates: Dict
    today: Dict
    warmup: Dict
    weekly_data: List[Dict]
    campaigns: List[Dict]
    costs: Dict

# Lightweight endpoint: list mutuals with saved emails for a prospect
@router.get("/mutuals/{prospect_id}")
async def list_mutuals_with_emails(
    prospect_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Return mutual connections for a prospect including any saved connector emails.
    """
    try:
        tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
        if not tenant_id:
            raise HTTPException(status_code=403, detail="User not associated with tenant")

        cursor = db.cursor()
        cursor.execute(
            """
            SELECT 
                id AS mutual_id,
                mutual_full_name AS connector_name,
                mutual_company AS connector_company,
                mutual_headline AS connector_title,
                mutual_linkedin_url AS connector_linkedin_url,
                mutual_email,
                mutual_email_confidence,
                email_enriched_at,
                contact_id
            FROM prospect_mutuals
            WHERE tenant_id = %s AND prospect_id = %s
            ORDER BY ranking_score DESC NULLS LAST, scraped_at DESC NULLS LAST, id DESC
            """,
            (tenant_id, prospect_id)
        )
        rows = cursor.fetchall() or []
        # Normalize to plain dicts
        def to_dict(row):
            if isinstance(row, dict):
                return row
            # sqlite3.Row -> dict by keys if available
            try:
                return {k: row[idx] for idx, k in enumerate(["mutual_id","connector_name","connector_company","connector_title","connector_linkedin_url","mutual_email","mutual_email_confidence","email_enriched_at","contact_id"]) }
            except Exception:
                return {
                    "mutual_id": row[0],
                    "connector_name": row[1],
                    "connector_company": row[2],
                    "connector_title": row[3],
                    "connector_linkedin_url": row[4],
                    "mutual_email": row[5],
                    "mutual_email_confidence": row[6],
                    "email_enriched_at": row[7],
                    "contact_id": row[8],
                }

        return {
            "success": True,
            "prospect_id": prospect_id,
            "count": len(rows),
            "mutuals": [to_dict(r) for r in rows]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list mutuals with emails: {e}")
        raise HTTPException(status_code=500, detail="Failed to list mutuals")

# Backfill: populate contacts from prospect_mutuals.saved emails and link contact_id
@router.post("/mutuals/backfill-contacts")
async def backfill_mutuals_to_contacts(
    prospect_id: Optional[int] = Query(None),
    dry_run: bool = Query(False),
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    One-off utility to create/update contacts from saved mutual emails and link contact_id on mutuals.
    - Filters by current tenant; optionally by a specific prospect.
    - Idempotent: looks up by linkedin_url, then by email.
    """
    try:
        tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
        if not tenant_id:
            raise HTTPException(status_code=403, detail="User not associated with tenant")

        cursor = db.cursor()
        params = [tenant_id]
        where = "tenant_id = %s AND COALESCE(TRIM(mutual_email),'') <> '' AND (contact_id IS NULL OR contact_id = 0)"
        if prospect_id is not None:
            where += " AND prospect_id = %s"
            params.append(prospect_id)

        cursor.execute(
            f"""
            SELECT id, mutual_full_name, mutual_company, mutual_headline, mutual_linkedin_url,
                   mutual_email, mutual_email_confidence, prospect_id
            FROM prospect_mutuals
            WHERE {where}
            ORDER BY id ASC
            """, params
        )
        rows = cursor.fetchall() or []

        stats = {
            'tenant_id': tenant_id,
            'prospect_id': prospect_id,
            'scanned': len(rows),
            'created_contacts': 0,
            'updated_contacts': 0,
            'linked_mutuals': 0,
            'skipped_missing_email': 0,
            'errors': 0,
            'dry_run': dry_run
        }

        for row in rows:
            # Normalize row to dict
            r = row if isinstance(row, dict) else {
                'id': row[0], 'mutual_full_name': row[1], 'mutual_company': row[2], 'mutual_headline': row[3],
                'mutual_linkedin_url': row[4], 'mutual_email': row[5], 'mutual_email_confidence': row[6], 'prospect_id': row[7]
            }
            mutual_id = r['id']
            full_name = r.get('mutual_full_name')
            company = r.get('mutual_company')
            title = r.get('mutual_headline')
            linkedin_url = r.get('mutual_linkedin_url')
            email = r.get('mutual_email')
            conf = r.get('mutual_email_confidence') or 0.0

            if not email:
                stats['skipped_missing_email'] += 1
                continue

            try:
                contact_id = None
                # Lookup by linkedin_url first
                if linkedin_url:
                    cursor.execute(
                        "SELECT id FROM contacts WHERE tenant_id = %s AND linkedin_url = %s",
                        (tenant_id, linkedin_url)
                    )
                    rowc = cursor.fetchone()
                    if rowc:
                        contact_id = rowc['id'] if isinstance(rowc, dict) else rowc[0]
                # Fallback lookup by email
                if not contact_id:
                    cursor.execute(
                        "SELECT id FROM contacts WHERE tenant_id = %s AND LOWER(email) = LOWER(%s)",
                        (tenant_id, email)
                    )
                    rowc = cursor.fetchone()
                    if rowc:
                        contact_id = rowc['id'] if isinstance(rowc, dict) else rowc[0]

                now = datetime.now()
                # Insert if not found
                if not contact_id:
                    if dry_run:
                        stats['created_contacts'] += 1
                    else:
                        cursor.execute(
                            """
                            INSERT INTO contacts(tenant_id, full_name, email, linkedin_url, company, title, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (tenant_id, full_name, email, linkedin_url, company, title, now, now)
                        )
                        contact_id = cursor.lastrowid if hasattr(cursor, 'lastrowid') and cursor.lastrowid else None
                        if not contact_id:
                            # Fetch again to be safe
                            if linkedin_url:
                                cursor.execute("SELECT id FROM contacts WHERE tenant_id = %s AND linkedin_url = %s", (tenant_id, linkedin_url))
                            else:
                                cursor.execute("SELECT id FROM contacts WHERE tenant_id = %s AND LOWER(email) = LOWER(%s)", (tenant_id, email))
                            rowc = cursor.fetchone()
                            if rowc:
                                contact_id = rowc['id'] if isinstance(rowc, dict) else rowc[0]
                        stats['created_contacts'] += 1
                else:
                    # Update existing
                    if not dry_run:
                        cursor.execute(
                            """
                            UPDATE contacts
                            SET full_name = COALESCE(%s, full_name),
                                email = COALESCE(%s, email),
                                company = COALESCE(%s, company),
                                title = COALESCE(%s, title),
                                linkedin_url = COALESCE(%s, linkedin_url),
                                updated_at = %s
                            WHERE id = %s AND tenant_id = %s
                            """,
                            (full_name, email, company, title, linkedin_url, now, contact_id, tenant_id)
                        )
                        # Best-effort: try to update confidence metrics if columns exist
                        try:
                            cursor.execute(
                                "UPDATE contacts SET email_confidence = %s, email_last_verified = %s WHERE id = %s AND tenant_id = %s",
                                (conf, now, contact_id, tenant_id)
                            )
                        except Exception:
                            pass
                    stats['updated_contacts'] += 1

                # Link back to mutuals
                if contact_id and not dry_run:
                    cursor.execute(
                        "UPDATE prospect_mutuals SET contact_id = %s, email_enriched_at = COALESCE(email_enriched_at, %s) WHERE id = %s AND tenant_id = %s",
                        (contact_id, now, mutual_id, tenant_id)
                    )
                    stats['linked_mutuals'] += 1

                if not dry_run:
                    db.commit()

            except Exception as e:
                stats['errors'] += 1
                logger.warning(f"Backfill failed for mutual_id {mutual_id}: {e}")
                # continue processing others

        return {"success": True, **stats}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        raise HTTPException(status_code=500, detail="Backfill failed")

# Email enrichment endpoints
@router.post("/enrich", response_model=EmailEnrichmentResponse)
async def enrich_emails(
    request: EmailEnrichmentRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Enrich contacts with email addresses using CUFinder
    Supports both contact table IDs and mutual connection keys from frontend
    """
    try:
        logger.info(f"🔍 [EMAIL DEBUG] Starting email enrichment for {len(request.contact_ids)} identifiers")
        logger.info(f"🔍 [EMAIL DEBUG] Request payload: {request.dict()}")
        logger.info(f"🔍 [EMAIL DEBUG] Contact IDs: {request.contact_ids}")
        logger.info(f"🔍 [EMAIL DEBUG] current_user type: {type(current_user)}")
        logger.info(f"🔍 [EMAIL DEBUG] current_user content: {current_user}")
        
        # Fix current_user access - it's a dict, not an object
        tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
        user_id = current_user.get('id') if isinstance(current_user, dict) else getattr(current_user, 'id', None)
        
        logger.info(f"🔍 [EMAIL DEBUG] Extracted tenant_id: {tenant_id}, user_id: {user_id}")
        
        # Check if user has permission for email operations
        if not tenant_id:
            logger.error(f"❌ [EMAIL DEBUG] No tenant_id found in current_user: {current_user}")
            raise HTTPException(status_code=403, detail="User not associated with tenant")
        
        # Check if this is a mutual connection enrichment request (frontend "Find Email" button)
        # Frontend sends connection keys like "123-https://linkedin.com/in/person" or "123-John Doe"
        # OR simple integer IDs from prospect_mutuals table
        logger.info(f"🔍 [EMAIL DEBUG] Analyzing contact_ids to detect mutual connection request:")
        for i, contact_id in enumerate(request.contact_ids):
            logger.info(f"🔍 [EMAIL DEBUG] contact_id[{i}]: {contact_id} (type: {type(contact_id)})")
        
        # Check for complex connection keys (original format)
        is_complex_mutual_request = any(
            isinstance(contact_id, str) and '-' in contact_id and (
                'linkedin.com' in contact_id or 
                any(char.isalpha() for char in contact_id.split('-', 1)[1] if len(contact_id.split('-', 1)) > 1)
            )
            for contact_id in request.contact_ids
        )
        
        # Check if these might be prospect_mutuals IDs (integers from frontend)
        # If contacts table is empty but we're getting integer IDs, likely from prospect_mutuals
        is_prospect_mutuals_request = False
        if not is_complex_mutual_request and all(isinstance(id, int) for id in request.contact_ids):
            try:
                cursor = db.cursor()
                # Check if any of these IDs exist in prospect_mutuals for this tenant
                placeholders = ','.join(['%s'] * len(request.contact_ids))
                cursor.execute(f"""
                    SELECT COUNT(*) as count
                    FROM prospect_mutuals 
                    WHERE id IN ({placeholders}) AND tenant_id = %s
                """, request.contact_ids + [tenant_id])
                pm_count = cursor.fetchone()['count']
                
                # Check if they exist in contacts table
                cursor.execute(f"""
                    SELECT COUNT(*) as count
                    FROM contacts 
                    WHERE id IN ({placeholders}) AND tenant_id = %s
                """, request.contact_ids + [tenant_id])
                contacts_count = cursor.fetchone()['count']
                
                logger.info(f"🔍 [EMAIL DEBUG] ID analysis - prospect_mutuals: {pm_count}, contacts: {contacts_count}")
                
                # If found in prospect_mutuals but not in contacts, route to mutual connections
                if pm_count > 0 and contacts_count == 0:
                    is_prospect_mutuals_request = True
                    logger.info("🔍 [EMAIL DEBUG] ⚡ DETECTED: prospect_mutuals IDs (not contact IDs)")
                
            except Exception as e:
                logger.warning(f"❌ [EMAIL DEBUG] Failed to analyze ID types: {e}")
        
        logger.info(f"🔍 [EMAIL DEBUG] is_complex_mutual_request: {is_complex_mutual_request}")
        logger.info(f"🔍 [EMAIL DEBUG] is_prospect_mutuals_request: {is_prospect_mutuals_request}")
        
        if is_complex_mutual_request:
            # Handle complex mutual connection enrichment
            logger.info("🔍 [EMAIL DEBUG] ⚡ ROUTING TO COMPLEX MUTUAL CONNECTION ENRICHMENT")
            return await _enrich_mutual_connections_from_keys(
                connection_keys=request.contact_ids,
                min_confidence=request.min_confidence,
                current_user=current_user,
                db=db
            )
        elif is_prospect_mutuals_request:
            # Handle prospect_mutuals IDs enrichment
            logger.info("🔍 [EMAIL DEBUG] ⚡ ROUTING TO PROSPECT_MUTUALS ID ENRICHMENT")
            return await _enrich_prospect_mutuals_by_ids(
                mutual_ids=request.contact_ids,
                min_confidence=request.min_confidence,
                current_user=current_user,
                db=db,
                force_refresh=request.force_refresh,
                override_company=request.override_company,
                override_company_domain=request.override_company_domain
            )
        else:
            # Handle standard contact table enrichment
            logger.info(f"🔍 [EMAIL DEBUG] Standard contact table enrichment for tenant {tenant_id}")
            
            # Validate contacts belong to user's tenant with detailed debugging
            logger.info(f"🔍 [EMAIL DEBUG] Validating {len(request.contact_ids)} contact_ids for tenant {tenant_id}")
            logger.info(f"🔍 [EMAIL DEBUG] Contact IDs to validate: {request.contact_ids}")
            
            try:
                cursor = db.cursor()
                logger.info(f"🔍 [EMAIL DEBUG] Database cursor created successfully")
                
                # Debug the query parameters and detect database type
                contact_ids_tuple = tuple(request.contact_ids)
                logger.info(f"🔍 [EMAIL DEBUG] Query parameters:")
                logger.info(f"   - contact_ids_tuple: {contact_ids_tuple}")
                logger.info(f"   - tenant_id: {tenant_id}")
                
                # Detect database type and use appropriate syntax
                import sqlite3
                is_sqlite = isinstance(db, sqlite3.Connection)
                logger.info(f"🔍 [EMAIL DEBUG] Database type: {'SQLite' if is_sqlite else 'PostgreSQL'}")
                
                # PostgreSQL-specific comprehensive debugging
                if not is_sqlite:
                    logger.info("🔍 [PG DEBUG] PostgreSQL-specific debugging:")
                    
                    try:
                        # Log the actual SQL that will be executed with mogrify
                        if len(request.contact_ids) == 1:
                            sql_query = "SELECT COUNT(*) FROM contacts WHERE id = %s AND tenant_id = %s"
                            params = (request.contact_ids[0], tenant_id)
                        else:
                            sql_query = "SELECT COUNT(*) FROM contacts WHERE id IN %s AND tenant_id = %s"
                            params = (contact_ids_tuple, tenant_id)
                        
                        try:
                            mogrified = cursor.mogrify(sql_query, params)
                            logger.info(f"🔍 [PG DEBUG] Mogrified SQL: {mogrified.decode() if isinstance(mogrified, bytes) else mogrified}")
                        except Exception as e:
                            logger.info(f"🔍 [PG DEBUG] Mogrify failed: {e}")
                        
                        # Check table exists
                        cursor.execute("SELECT tablename FROM pg_tables WHERE tablename = 'contacts'")
                        table_exists = cursor.fetchone()
                        logger.info(f"🔍 [PG DEBUG] Table 'contacts' exists: {bool(table_exists)}")
                        
                        # Check table structure
                        cursor.execute("""
                            SELECT column_name, data_type, is_nullable 
                            FROM information_schema.columns 
                            WHERE table_name = 'contacts' 
                            ORDER BY ordinal_position
                        """)
                        columns = cursor.fetchall()
                        logger.info(f"🔍 [PG DEBUG] Table 'contacts' columns:")
                        for col in columns:
                            logger.info(f"  - {col['column_name']}: {col['data_type']} (nullable: {col['is_nullable']})")
                        
                        # Check total contacts in database
                        cursor.execute("SELECT COUNT(*) as total FROM contacts")
                        total_contacts = cursor.fetchone()['total']
                        logger.info(f"🔍 [PG DEBUG] Total contacts in database: {total_contacts}")
                        
                        # Check contacts in this tenant
                        cursor.execute("SELECT COUNT(*) as total FROM contacts WHERE tenant_id = %s", (tenant_id,))
                        tenant_contacts = cursor.fetchone()['total']
                        logger.info(f"🔍 [PG DEBUG] Total contacts in tenant {tenant_id}: {tenant_contacts}")
                        
                        # Check specific contact without tenant filter
                        if len(request.contact_ids) == 1:
                            cursor.execute("SELECT id, tenant_id FROM contacts WHERE id = %s", (request.contact_ids[0],))
                            contact_any_tenant = cursor.fetchone()
                            if contact_any_tenant:
                                logger.info(f"🔍 [PG DEBUG] Contact {request.contact_ids[0]} found in tenant: {contact_any_tenant['tenant_id']}")
                            else:
                                logger.info(f"🔍 [PG DEBUG] Contact {request.contact_ids[0]} does not exist in any tenant")
                        
                        # Check all contacts in the tenant for comparison
                        cursor.execute("SELECT id FROM contacts WHERE tenant_id = %s LIMIT 10", (tenant_id,))
                        sample_contacts = cursor.fetchall()
                        sample_ids = [row['id'] for row in sample_contacts]
                        logger.info(f"🔍 [PG DEBUG] Sample contact IDs in tenant {tenant_id}: {sample_ids}")
                        
                    except Exception as debug_error:
                        logger.error(f"🔍 [PG DEBUG] Debug queries failed: {debug_error}")
                
                if is_sqlite:
                    # SQLite syntax: Use ? placeholders
                    placeholders = ','.join(['?' for _ in request.contact_ids])
                    query = f"""
                        SELECT COUNT(*) as count
                        FROM contacts 
                        WHERE id IN ({placeholders}) AND tenant_id = ?
                    """
                    params = list(request.contact_ids) + [tenant_id]
                    logger.info(f"🔍 [EMAIL DEBUG] SQLite query: {query}")
                    logger.info(f"🔍 [EMAIL DEBUG] SQLite params: {params}")
                    cursor.execute(query, params)
                else:
                    # PostgreSQL syntax: Use %s placeholders with proper tuple formatting
                    # Handle single element tuples properly for PostgreSQL
                    if len(request.contact_ids) == 1:
                        # Single element: use = instead of IN for better PostgreSQL compatibility
                        cursor.execute("""
                            SELECT COUNT(*) as count
                            FROM contacts 
                            WHERE id = %s AND tenant_id = %s
                        """, (request.contact_ids[0], tenant_id))
                    else:
                        # Multiple elements: use IN with tuple
                        cursor.execute("""
                            SELECT COUNT(*) as count
                            FROM contacts 
                            WHERE id IN %s AND tenant_id = %s
                        """, (contact_ids_tuple, tenant_id))
                
                logger.info(f"✅ [EMAIL DEBUG] Contact validation query executed successfully")
                
                contact_count_result = cursor.fetchone()
                logger.info(f"🔍 [EMAIL DEBUG] Query result: {contact_count_result}")
                
                contact_count = contact_count_result['count'] if contact_count_result else 0
                logger.info(f"🔍 [EMAIL DEBUG] Validation results:")
                logger.info(f"   - contacts found in DB: {contact_count}")
                logger.info(f"   - contacts requested: {len(request.contact_ids)}")
                logger.info(f"   - validation passed: {contact_count == len(request.contact_ids)}")
                
                if contact_count != len(request.contact_ids):
                    # Find out which specific contacts are missing/not accessible
                    logger.error(f"❌ [EMAIL DEBUG] Contact validation failed!")
                    
                    try:
                        # Apply same PostgreSQL fix for the missing contacts query
                        if len(request.contact_ids) == 1:
                            cursor.execute("""
                                SELECT id FROM contacts 
                                WHERE id = %s AND tenant_id = %s
                            """, (request.contact_ids[0], tenant_id))
                        else:
                            cursor.execute("""
                                SELECT id FROM contacts 
                                WHERE id IN %s AND tenant_id = %s
                            """, (contact_ids_tuple, tenant_id))
                        found_contacts = [row['id'] for row in cursor.fetchall()]
                        missing_contacts = [cid for cid in request.contact_ids if cid not in found_contacts]
                        
                        logger.error(f"❌ [EMAIL DEBUG] Missing/inaccessible contacts analysis:")
                        logger.error(f"   - requested contacts: {request.contact_ids}")
                        logger.error(f"   - found contacts: {found_contacts}")
                        logger.error(f"   - missing contacts: {missing_contacts}")
                        
                        # Check if missing contacts exist in other tenants
                        if missing_contacts:
                            cursor.execute("""
                                SELECT id, tenant_id FROM contacts 
                                WHERE id IN %s
                            """, (tuple(missing_contacts),))
                            other_tenant_contacts = cursor.fetchall()
                            
                            if other_tenant_contacts:
                                logger.error(f"❌ [EMAIL DEBUG] Found missing contacts in other tenants:")
                                for contact in other_tenant_contacts:
                                    logger.error(f"   - contact_id {contact['id']} belongs to tenant_id {contact['tenant_id']}")
                            else:
                                logger.error(f"❌ [EMAIL DEBUG] Missing contacts don't exist in any tenant")
                        
                    except Exception as analysis_error:
                        logger.error(f"❌ [EMAIL DEBUG] Failed to analyze missing contacts: {analysis_error}")
                    
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Some contacts not found or not accessible. Found {contact_count}/{len(request.contact_ids)} contacts."
                    )
                    
            except HTTPException:
                raise
            except Exception as db_error:
                logger.error(f"❌ [EMAIL DEBUG] CRITICAL: Database error during contact validation!")
                logger.error(f"❌ [EMAIL DEBUG] DB error type: {type(db_error).__name__}")
                logger.error(f"❌ [EMAIL DEBUG] DB error message: {str(db_error)}")
                logger.error(f"❌ [EMAIL DEBUG] DB error traceback:", exc_info=True)
                raise HTTPException(
                    status_code=500, 
                    detail=f"Database error during contact validation: {str(db_error)}"
                )
            
            # Execute enrichment
            results = await email_service.enrich_contacts(
                contact_ids=request.contact_ids,
                tenant_id=tenant_id,
                force_refresh=request.force_refresh,
                min_confidence=request.min_confidence,
                db=db
            )

            if results.get("status") == "configuration_required":
                message = results.get("message") or "CUFinder email enrichment is not configured for this tenant."
                logger.warning(f"CUFinder enrichment disabled for tenant {tenant_id}: {message}")
                raise HTTPException(status_code=503, detail=message)

            # Log success
            logger.info(f"Enrichment completed: {results['enriched_count']}/{len(request.contact_ids)} contacts enriched")
            
            return EmailEnrichmentResponse(**results)
        
    except HTTPException as http_e:
        logger.error(f"❌ [EMAIL ENRICH DEBUG] HTTP Exception caught:")
        logger.error(f"   - status_code: {http_e.status_code}")
        logger.error(f"   - detail: {http_e.detail}")
        raise
    except Exception as e:
        logger.error(f"❌ [EMAIL ENRICH DEBUG] CRITICAL: Unexpected error in enrich_emails!")
        logger.error(f"❌ [EMAIL ENRICH DEBUG] Error type: {type(e).__name__}")
        logger.error(f"❌ [EMAIL ENRICH DEBUG] Error message: {str(e)}")
        logger.error(f"❌ [EMAIL ENRICH DEBUG] Full traceback:", exc_info=True)
        
        # Enhanced error recording
        try:
            if error_classifier:
                # Extract tenant_id for error recording
                tenant_id_for_error = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
                logger.info(f"📊 [EMAIL ENRICH DEBUG] Recording error for tenant_id: {tenant_id_for_error}")
                error_classifier.record_provider_error(
                    'email_service', 'enrichment_error', str(e), tenant_id_for_error
                )
                logger.info(f"✅ [EMAIL ENRICH DEBUG] Error recorded successfully")
        except Exception as error_record_failure:
            logger.error(f"⚠️ [EMAIL ENRICH DEBUG] Failed to record error: {error_record_failure}")
        
        raise HTTPException(status_code=500, detail=f"Email enrichment failed: {str(e)}")

# Helper function for mutual connection enrichment from frontend keys
async def _enrich_mutual_connections_from_keys(
    connection_keys: List[str],
    min_confidence: float,
    current_user,
    db
) -> EmailEnrichmentResponse:
    """
    Helper function to enrich mutual connections using connection keys from frontend
    Frontend sends keys like: "123-https://linkedin.com/in/person" or "123-John Doe"
    """
    logger.info(f"🔍 [MUTUAL DEBUG] Enriching mutual connections from {len(connection_keys)} connection keys")
    logger.info(f"🔍 [MUTUAL DEBUG] Connection keys: {connection_keys}")
    logger.info(f"🔍 [MUTUAL DEBUG] Min confidence: {min_confidence}")
    logger.info(f"🔍 [MUTUAL DEBUG] current_user type: {type(current_user)}")
    logger.info(f"🔍 [MUTUAL DEBUG] current_user content: {current_user}")
    
    # Get CUFinder client for tenant
    from integrations.cufinder_client import get_cufinder_client
    tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
    logger.info(f"🔍 [MUTUAL DEBUG] Extracted tenant_id: {tenant_id}")
    
    cufinder = get_cufinder_client(tenant_id, fail_on_missing=False)
    if not cufinder.is_configured:
        reason = cufinder.configuration_reason or "CUFinder email enrichment is not configured for this tenant."
        logger.error(f"❌ [MUTUAL DEBUG] CUFinder disabled for tenant {tenant_id}: {reason}")
        raise HTTPException(status_code=503, detail=reason)
    logger.info("🔍 [MUTUAL DEBUG] CUFinder client retrieved successfully")
    
    enriched_count = 0
    failed_count = 0
    high_confidence_count = 0
    low_confidence_count = 0
    total_cost = 0.0
    results = []
    
    # Get mutual connections service
    from services.mutuals_service import mutuals_service
    
    for connection_key in connection_keys:
        logger.info(f"🔍 [MUTUAL DEBUG] Processing connection_key: {connection_key}")
        try:
            # Parse connection key: "prospectId-connectorInfo"
            parts = connection_key.split('-', 1)
            logger.info(f"🔍 [MUTUAL DEBUG] Split parts: {parts}")
            if len(parts) != 2:
                logger.warning(f"❌ [MUTUAL DEBUG] Invalid connection key format: {connection_key}")
                failed_count += 1
                results.append({
                    'connection_key': connection_key,
                    'success': False,
                    'error': 'Invalid key format'
                })
                continue
                
            prospect_id, connector_info = parts
            logger.info(f"🔍 [MUTUAL DEBUG] Parsed - prospect_id: {prospect_id}, connector_info: {connector_info}")
            
            # Get mutual connections for this specific prospect
            try:
                logger.info(f"🔍 [MUTUAL DEBUG] Getting mutual connections for prospect_id: {prospect_id}, tenant_id: {tenant_id}")
                prospect_connections = mutuals_service.get_all_mutual_connections(
                    prospect_id=int(prospect_id), 
                    limit=100,  # Get more to ensure we find the right one
                    tenant_id=tenant_id
                )
                logger.info(f"🔍 [MUTUAL DEBUG] Retrieved {len(prospect_connections)} mutual connections")
            except Exception as e:
                logger.warning(f"❌ [MUTUAL DEBUG] Failed to get mutual connections for prospect {prospect_id}: {e}")
                failed_count += 1
                results.append({
                    'connection_key': connection_key,
                    'success': False,
                    'error': f'Failed to get connections: {str(e)}'
                })
                continue
            
            # Find the matching mutual connection (fix field name mapping)
            matching_connection = None
            logger.info(f"🔍 [MUTUAL DEBUG] Searching for matching connection with connector_info: {connector_info}")
            for i, connection in enumerate(prospect_connections):
                logger.info(f"🔍 [MUTUAL DEBUG] Connection {i}: linkedin_url={connection.get('linkedin_url')}, name={connection.get('full_name')}")
                if (connection.get('linkedin_url') == connector_info or 
                    connection.get('full_name') == connector_info):
                    matching_connection = connection
                    logger.info(f"🔍 [MUTUAL DEBUG] Found matching connection at index {i}: {matching_connection}")
                    break
            
            if not matching_connection:
                logger.warning(f"❌ [MUTUAL DEBUG] No matching mutual connection found for key: {connection_key}")
                logger.info(f"🔍 [MUTUAL DEBUG] Available connections: {[c.get('full_name') for c in prospect_connections]}")
                failed_count += 1
                results.append({
                    'connection_key': connection_key,
                    'success': False,
                    'error': 'Connection not found'
                })
                continue
            
            # Extract connection details for CUFinder (fix field name mapping)
            connector_name = matching_connection.get('full_name', '')
            connector_company = matching_connection.get('company', '')
            connector_linkedin_url = matching_connection.get('linkedin_url', '')
            
            logger.info(f"🔍 [MUTUAL DEBUG] Extracted connection details:")
            logger.info(f"🔍 [MUTUAL DEBUG] - connector_name: {connector_name}")
            logger.info(f"🔍 [MUTUAL DEBUG] - connector_company: {connector_company}")
            logger.info(f"🔍 [MUTUAL DEBUG] - connector_linkedin_url: {connector_linkedin_url}")
            
            if not connector_name:
                logger.error(f"❌ [MUTUAL DEBUG] Missing connector name for {connection_key}")
                failed_count += 1
                results.append({
                    'connection_key': connection_key,
                    'success': False,
                    'error': 'Missing connector name'
                })
                continue
            
            logger.info(f"🔍 [MUTUAL DEBUG] Starting enrichment for: {connector_name} at {connector_company}")
            
            # Call CUFinder for email enrichment (priority order)
            enrichment_result = None

            if connector_linkedin_url:
                # Try LinkedIn URL first (most accurate)
                logger.info(f"🔍 [MUTUAL DEBUG] Trying LinkedIn URL enrichment: {connector_linkedin_url}")
                enrichment_result = await cufinder.enrich_email(
                    linkedin_url=connector_linkedin_url,
                    full_name=connector_name,
                    company=connector_company
                )
                logger.info(f"🔍 [MUTUAL DEBUG] LinkedIn URL result: {enrichment_result}")
            elif connector_name and connector_company:
                # Try name + company
                logger.info(f"🔍 [MUTUAL DEBUG] Trying name+company enrichment: {connector_name} at {connector_company}")
                enrichment_result = await cufinder.enrich_email(
                    full_name=connector_name,
                    company=connector_company
                )
                logger.info(f"🔍 [MUTUAL DEBUG] Name+company result: {enrichment_result}")
            elif connector_company:
                # Try company domain as last resort
                logger.info(f"🔍 [MUTUAL DEBUG] Trying domain enrichment: {connector_company}")
                enrichment_result = await cufinder.enrich_email(
                    company=connector_company,
                    full_name=connector_name
                )
                logger.info(f"🔍 [MUTUAL DEBUG] Domain result: {enrichment_result}")
            else:
                logger.warning(f"❌ [MUTUAL DEBUG] No enrichment strategy available - missing company info")
            
            if enrichment_result and enrichment_result.email:
                confidence = enrichment_result.confidence
                email = enrichment_result.email
                
                logger.info(f"✅ [MUTUAL DEBUG] Email found: {email} with confidence: {confidence}")
                
                enriched_count += 1
                total_cost += enrichment_result.cost  # Use actual cost from result
                
                if confidence >= min_confidence:
                    high_confidence_count += 1
                    logger.info(f"✅ [MUTUAL DEBUG] High confidence email ({confidence} >= {min_confidence})")
                else:
                    low_confidence_count += 1
                    logger.info(f"⚠️ [MUTUAL DEBUG] Low confidence email ({confidence} < {min_confidence})")
                
                result_entry = {
                    'connection_key': connection_key,
                    'success': True,
                    'email': email,
                    'confidence': confidence,
                    'source': enrichment_result.source,
                    'connector_name': connector_name,
                    'connector_company': connector_company
                }
                results.append(result_entry)
                logger.info(f"✅ [MUTUAL DEBUG] Added successful result: {result_entry}")
                
                logger.info(f"✅ Found email for {connector_name}: {email} (confidence: {confidence})")
            else:
                logger.warning(f"❌ [MUTUAL DEBUG] No email in enrichment result: {enrichment_result}")
                failed_count += 1
                error_message = enrichment_result.error_message if enrichment_result else 'No email found'
                result_entry = {
                    'connection_key': connection_key,
                    'success': False,
                    'error': error_message
                }
                results.append(result_entry)
                logger.info(f"❌ [MUTUAL DEBUG] Added failed result: {result_entry}")
                logger.info(f"❌ No email found for {connector_name}")
                
        except Exception as e:
            logger.error(f"Enrichment failed for connection key {connection_key}: {e}")
            failed_count += 1
            results.append({
                'connection_key': connection_key,
                'success': False,
                'error': str(e)
            })
    
    # Record cost tracking
    if total_cost > 0:
        try:
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO email_costs (tenant_id, date, service, operation, count, unit_cost, total_cost)
                VALUES (%s, %s, 'cufinder', 'enrichment', %s, %s, %s)
                ON CONFLICT(tenant_id, date, service, operation) DO UPDATE SET 
                    count = email_costs.count + EXCLUDED.count,
                    total_cost = email_costs.total_cost + EXCLUDED.total_cost
            """, (
                tenant_id, datetime.now().date(),
                enriched_count, 0.03, total_cost
            ))
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to record enrichment cost: {e}")
    
    logger.info(f"Mutual connection enrichment completed: {enriched_count} enriched, {failed_count} failed, cost: ${total_cost}")
    
    return EmailEnrichmentResponse(
        enriched_count=enriched_count,
        failed_count=failed_count,
        already_had_email=0,
        high_confidence=high_confidence_count,
        low_confidence=low_confidence_count,
        suppressed=0,
        total_cost=total_cost,
        results=results
    )

# Helper function for prospect_mutuals ID enrichment (new function to handle the ID namespace issue)
async def _enrich_prospect_mutuals_by_ids(
    mutual_ids: List[int],
    min_confidence: float,
    current_user,
    db,
    force_refresh: bool = False,
    override_company: Optional[str] = None,
    override_company_domain: Optional[str] = None
) -> EmailEnrichmentResponse:
    """
    Helper function to enrich mutual connections using prospect_mutuals table IDs
    This handles the ID namespace mismatch where frontend passes prospect_mutuals.id
    """
    logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Enriching {len(mutual_ids)} prospect_mutuals by IDs")
    logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Mutual IDs: {mutual_ids}")
    logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Min confidence: {min_confidence}")
    
    # Get CUFinder client for tenant with enhanced error handling
    from integrations.cufinder_client import get_cufinder_client
    tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
    logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Extracted tenant_id: {tenant_id}")
    
    try:
        cufinder = get_cufinder_client(tenant_id, fail_on_missing=False)
    except Exception as e:
        logger.error(f"❌ [PROSPECT_MUTUALS DEBUG] Failed to create CUFinder client: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize CUFinder client: {str(e)}"
        )

    if not cufinder.is_configured:
        reason = cufinder.configuration_reason or "CUFinder email enrichment is not configured for this tenant."
        logger.error(f"❌ [PROSPECT_MUTUALS DEBUG] CUFinder disabled for tenant {tenant_id}: {reason}")
        raise HTTPException(status_code=503, detail=reason)

    logger.info("✅ [PROSPECT_MUTUALS DEBUG] CUFinder client retrieved successfully")
    
    enriched_count = 0
    failed_count = 0
    high_confidence_count = 0
    low_confidence_count = 0
    total_cost = 0.0
    results = []
    
    try:
        cursor = db.cursor()
        
        # Get mutual connections from prospect_mutuals table using the IDs
        placeholders = ','.join(['%s'] * len(mutual_ids))
        cursor.execute(f"""
            SELECT 
                id,
                mutual_full_name,
                mutual_linkedin_url,
                mutual_headline,
                mutual_company,
                prospect_id,
                mutual_email,
                mutual_email_confidence,
                email_enriched_at
            FROM prospect_mutuals 
            WHERE id IN ({placeholders}) AND tenant_id = %s
        """, mutual_ids + [tenant_id])
        
        mutual_records = cursor.fetchall()
        logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Retrieved {len(mutual_records)} mutual records from database")
        
        for record in mutual_records:
            mutual_id = record['id']
            connector_name = record['mutual_full_name']
            connector_linkedin_url = record['mutual_linkedin_url']
            connector_company = record['mutual_company']
            connector_headline = record['mutual_headline']
            prospect_id = record['prospect_id']

            # Apply UI-provided overrides when present
            if override_company:
                connector_company = override_company
            
            logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Processing mutual ID {mutual_id}: {connector_name}")
            
            try:
                # If we already have a saved email at/above the requested confidence, reuse it (unless force_refresh)
                saved_email = record.get('mutual_email') if isinstance(record, dict) else record['mutual_email']
                saved_conf = record.get('mutual_email_confidence') if isinstance(record, dict) else record['mutual_email_confidence']
                if (not force_refresh) and saved_email and (saved_conf or 0) >= (min_confidence or 0):
                    logger.info(f"✅ [PROSPECT_MUTUALS DEBUG] Using saved email for mutual_id {mutual_id}: {saved_email} (conf: {saved_conf})")
                    enriched_count += 1
                    if saved_conf >= min_confidence:
                        high_confidence_count += 1
                    else:
                        low_confidence_count += 1
                    # Ensure a contact record exists and link it
                    try:
                        cursor_link = db.cursor()
                        now = datetime.now()
                        if connector_linkedin_url:
                            # Safe upsert by linkedin_url without requiring unique index
                            cursor_link.execute(
                                """
                                INSERT INTO contacts (tenant_id, full_name, email, linkedin_url, company, title, created_at, updated_at)
                                SELECT %s, %s, %s, %s, %s, %s, %s, %s
                                WHERE NOT EXISTS (
                                    SELECT 1 FROM contacts WHERE tenant_id = %s AND linkedin_url = %s
                                )
                                """,
                                (tenant_id, connector_name, saved_email, connector_linkedin_url, connector_company, connector_headline, now, now,
                                 tenant_id, connector_linkedin_url)
                            )
                            cursor_link.execute(
                                "SELECT id FROM contacts WHERE tenant_id = %s AND linkedin_url = %s",
                                (tenant_id, connector_linkedin_url)
                            )
                        else:
                            email_norm2 = (saved_email or '').lower() or None
                            cursor_link.execute(
                                """
                                INSERT INTO contacts (tenant_id, full_name, email, company, title, created_at, updated_at)
                                SELECT %s, %s, %s, %s, %s, %s, %s
                                WHERE NOT EXISTS (
                                    SELECT 1 FROM contacts WHERE tenant_id = %s AND email = %s
                                )
                                """,
                                (tenant_id, connector_name, email_norm2, connector_company, connector_headline, now, now,
                                 tenant_id, email_norm2)
                            )
                            cursor_link.execute(
                                "SELECT id FROM contacts WHERE tenant_id = %s AND email = %s",
                                (tenant_id, email_norm2)
                            )
                        contact_row2 = cursor_link.fetchone()
                        if contact_row2:
                            contact_id2 = contact_row2['id'] if isinstance(contact_row2, dict) else contact_row2[0]
                            cursor_link.execute(
                                "UPDATE prospect_mutuals SET contact_id = %s WHERE id = %s AND tenant_id = %s",
                                (contact_id2, mutual_id, tenant_id)
                            )
                            db.commit()
                            logger.info(f"🔗 [PROSPECT_MUTUALS DEBUG] Linked existing saved email to contact_id {contact_id2} for mutual_id {mutual_id}")
                    except Exception as link_existing_err:
                        logger.warning(f"⚠️ [PROSPECT_MUTUALS DEBUG] Failed to ensure contact for saved email mutual_id {mutual_id}: {link_existing_err}")
                    results.append({
                        'mutual_id': mutual_id,
                        'contact_id': mutual_id,
                        'success': True,
                        'email': saved_email,
                        'confidence': float(saved_conf or 0),
                        'source': 'database',
                        'connector_name': connector_name,
                        'connector_company': connector_company,
                        'prospect_id': prospect_id
                    })
                    # Skip CUFinder call to save credits
                    continue

                # Call CUFinder for email enrichment (priority order)
                enrichment_result = None
                
                if connector_linkedin_url:
                    # Try LinkedIn URL first (most accurate)
                    logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Trying LinkedIn URL enrichment: {connector_linkedin_url}")
                    enrichment_result = await cufinder.enrich_email(
                        linkedin_url=connector_linkedin_url,
                        full_name=connector_name,
                        company=connector_company,
                        company_domain=override_company_domain,
                        title=connector_headline
                    )
                    logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] LinkedIn URL result: {enrichment_result}")
                elif connector_name and (connector_company or override_company_domain):
                    # Try name + company
                    logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Trying name+company enrichment: {connector_name} at {connector_company}")
                    enrichment_result = await cufinder.enrich_email(
                        full_name=connector_name,
                        company=connector_company,
                        title=connector_headline,
                        company_domain=override_company_domain
                    )
                    logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Name+company result: {enrichment_result}")
                elif connector_company or override_company_domain:
                    # Try company domain as last resort
                    logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Trying domain enrichment: {override_company_domain or connector_company}")
                    enrichment_result = await cufinder.enrich_email(
                        company=connector_company,
                        company_domain=override_company_domain,
                        full_name=connector_name
                    )
                    logger.info(f"🔍 [PROSPECT_MUTUALS DEBUG] Domain result: {enrichment_result}")
                else:
                    logger.warning(f"❌ [PROSPECT_MUTUALS DEBUG] No enrichment strategy available - missing company info")
                
                if enrichment_result and enrichment_result.email:
                    confidence = enrichment_result.confidence
                    email = enrichment_result.email
                    
                    logger.info(f"✅ [PROSPECT_MUTUALS DEBUG] Email found: {email} with confidence: {confidence}")
                    
                    enriched_count += 1
                    total_cost += enrichment_result.cost  # Use actual cost from result
                    
                    if confidence >= min_confidence:
                        high_confidence_count += 1
                        logger.info(f"✅ [PROSPECT_MUTUALS DEBUG] High confidence email ({confidence} >= {min_confidence})")
                    else:
                        low_confidence_count += 1
                        logger.info(f"⚠️ [PROSPECT_MUTUALS DEBUG] Low confidence email ({confidence} < {min_confidence})")
                    
                    # Persist enriched email on the mutual record to avoid re-enrichment next time
                    try:
                        cursor2 = db.cursor()
                        cursor2.execute(
                            """
                            UPDATE prospect_mutuals
                            SET mutual_email = %s,
                                mutual_email_confidence = %s,
                                email_enriched_at = %s
                            WHERE id = %s AND tenant_id = %s
                            """,
                            (email, confidence, datetime.now(), mutual_id, tenant_id)
                        )
                        db.commit()
                        logger.info(f"💾 [PROSPECT_MUTUALS DEBUG] Saved email for mutual_id {mutual_id} in DB")
                    except Exception as persist_err:
                        logger.warning(f"⚠️ [PROSPECT_MUTUALS DEBUG] Failed to persist email for mutual_id {mutual_id}: {persist_err}")

                    # Upsert into contacts and link back to prospect_mutuals.contact_id
                    try:
                        cursor3 = db.cursor()
                        now = datetime.now()
                        # Primary upsert by linkedin_url; fallback by email
                        if connector_linkedin_url:
                            cursor3.execute(
                                """
                                INSERT INTO contacts (tenant_id, full_name, email, linkedin_url, company, title, created_at, updated_at)
                                SELECT %s, %s, %s, %s, %s, %s, %s, %s
                                WHERE NOT EXISTS (
                                    SELECT 1 FROM contacts WHERE tenant_id = %s AND linkedin_url = %s
                                )
                                """,
                                (tenant_id, connector_name, email, connector_linkedin_url, connector_company, connector_headline, now, now,
                                 tenant_id, connector_linkedin_url)
                            )
                        else:
                            email_norm = (email or '').lower() or None
                            cursor3.execute(
                                """
                                INSERT INTO contacts (tenant_id, full_name, email, company, title, created_at, updated_at)
                                SELECT %s, %s, %s, %s, %s, %s, %s
                                WHERE NOT EXISTS (
                                    SELECT 1 FROM contacts WHERE tenant_id = %s AND email = %s
                                )
                                """,
                                (tenant_id, connector_name, email_norm, connector_company, connector_headline, now, now,
                                 tenant_id, email_norm)
                            )
                        # Fetch contact id
                        if connector_linkedin_url:
                            cursor3.execute(
                                "SELECT id FROM contacts WHERE tenant_id = %s AND linkedin_url = %s",
                                (tenant_id, connector_linkedin_url)
                            )
                        else:
                            cursor3.execute(
                                "SELECT id FROM contacts WHERE tenant_id = %s AND email = %s",
                                (tenant_id, email_norm)
                            )
                        contact_row = cursor3.fetchone()
                        if contact_row and ('id' in contact_row or isinstance(contact_row, dict)):
                            contact_id = contact_row['id'] if isinstance(contact_row, dict) else contact_row[0]
                            # Link back to prospect_mutuals
                            cursor3.execute(
                                "UPDATE prospect_mutuals SET contact_id = %s WHERE id = %s AND tenant_id = %s",
                                (contact_id, mutual_id, tenant_id)
                            )
                        db.commit()
                        logger.info(f"🔗 [PROSPECT_MUTUALS DEBUG] Linked mutual_id {mutual_id} to contact_id {contact_row['id'] if isinstance(contact_row, dict) else (contact_row[0] if contact_row else None)}")
                    except Exception as link_err:
                        logger.warning(f"⚠️ [PROSPECT_MUTUALS DEBUG] Failed to upsert/link contact for mutual_id {mutual_id}: {link_err}")

                    result_entry = {
                        'mutual_id': mutual_id,
                        'contact_id': mutual_id,  # For compatibility with frontend expectations
                        'success': True,
                        'email': email,
                        'confidence': confidence,
                        'source': enrichment_result.source,
                        'connector_name': connector_name,
                        'connector_company': connector_company,
                        'prospect_id': prospect_id
                    }
                    results.append(result_entry)
                    logger.info(f"✅ [PROSPECT_MUTUALS DEBUG] Added successful result: {result_entry}")
                    
                    logger.info(f"✅ Found email for {connector_name}: {email} (confidence: {confidence})")
                else:
                    # No email found from enrichment; record failure
                    failed_count += 1
                    error_message = (enrichment_result.error_message if enrichment_result else 'No email found')
                    result_entry = {
                        'mutual_id': mutual_id,
                        'contact_id': mutual_id,
                        'success': False,
                        'error': error_message,
                        'connector_name': connector_name,
                        'connector_company': connector_company,
                        'prospect_id': prospect_id
                    }
                    results.append(result_entry)
                    logger.info(f"❌ [PROSPECT_MUTUALS DEBUG] Added failed result: {result_entry}")
                    logger.info(f"❌ No email found for {connector_name}")
            except Exception as e:
                logger.error(f"Enrichment failed for mutual ID {mutual_id}: {e}")
                failed_count += 1
                results.append({
                    'mutual_id': mutual_id,
                    'contact_id': mutual_id,  # For compatibility with frontend expectations
                    'success': False,
                    'error': str(e),
                    'connector_name': connector_name,
                    'prospect_id': prospect_id
                })
    
    except Exception as e:
        logger.error(f"❌ [PROSPECT_MUTUALS DEBUG] Failed to query prospect_mutuals: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query mutual connections: {str(e)}")
    
    # Record cost tracking
    if total_cost > 0:
        try:
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO email_costs (tenant_id, date, service, operation, count, unit_cost, total_cost)
                VALUES (%s, %s, 'cufinder', 'enrichment', %s, %s, %s)
                ON CONFLICT(tenant_id, date, service, operation) DO UPDATE SET 
                    count = email_costs.count + EXCLUDED.count,
                    total_cost = email_costs.total_cost + EXCLUDED.total_cost
            """, (
                tenant_id, datetime.now().date(),
                enriched_count, 0.03, total_cost
            ))
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to record enrichment cost: {e}")
    
    logger.info(f"Prospect mutuals enrichment completed: {enriched_count} enriched, {failed_count} failed, cost: ${total_cost}")
    
    return EmailEnrichmentResponse(
        enriched_count=enriched_count,
        failed_count=failed_count,
        already_had_email=0,
        high_confidence=high_confidence_count,
        low_confidence=low_confidence_count,
        suppressed=0,
        total_cost=total_cost,
        results=results
    )

@router.post("/enrich-connections", response_model=MutualConnectionEnrichmentResponse)
async def enrich_mutual_connections(
    request: MutualConnectionEnrichmentRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Enrich mutual connections directly with email addresses using CUFinder
    This endpoint is designed for the frontend "Find Email" functionality
    """
    try:
        logger.info(f"Starting mutual connections enrichment for {len(request.connections)} connections")
        
        tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
        if not tenant_id:
            raise HTTPException(status_code=403, detail="User not associated with tenant")
        
        # Check if email service is available
        if not email_service:
            raise HTTPException(status_code=503, detail="Email service not available")
        
        # Get CUFinder client for tenant
        from integrations.cufinder_client import get_cufinder_client
        cufinder = get_cufinder_client(tenant_id, fail_on_missing=False)
        if not cufinder.is_configured:
            reason = cufinder.configuration_reason or "CUFinder email enrichment is not configured for this tenant."
            logger.error(f"CUFinder disabled for tenant {tenant_id}: {reason}")
            raise HTTPException(status_code=503, detail=reason)
        
        enriched_results = []
        failed_results = []
        total_cost = 0.0
        
        for connection_data in request.connections:
            try:
                # Extract connection details
                connector_name = connection_data.get('connector_name', '')
                connector_company = connection_data.get('connector_company', '')
                connector_linkedin_url = connection_data.get('connector_linkedin_url', '')
                
                if not connector_name:
                    failed_results.append({
                        'connection': connection_data,
                        'error': 'Missing connector name'
                    })
                    continue
                
                logger.info(f"Enriching: {connector_name} at {connector_company}")
                
                # Call CUFinder for email enrichment
                # Priority: LinkedIn URL > Name + Company > Company domain
                enrichment_result = None
                
                if connector_linkedin_url:
                    # Try LinkedIn URL first (most accurate)
                    enrichment_result = await cufinder.find_email_by_linkedin(connector_linkedin_url)
                elif connector_name and connector_company:
                    # Try name + company
                    enrichment_result = await cufinder.find_email_by_name_company(
                        first_name=connector_name.split()[0],
                        last_name=' '.join(connector_name.split()[1:]) if len(connector_name.split()) > 1 else '',
                        company=connector_company
                    )
                elif connector_company:
                    # Try company domain as last resort
                    enrichment_result = await cufinder.find_email_by_domain(connector_company)
                
                if enrichment_result and enrichment_result.get('email'):
                    enriched_results.append({
                        'connection': connection_data,
                        'email': enrichment_result['email'],
                        'confidence': enrichment_result.get('confidence', 0),
                        'source': enrichment_result.get('source', 'cufinder')
                    })
                    
                    # Track cost (assuming $0.03 per successful enrichment based on pricing in frontend)
                    total_cost += 0.03
                    
                    logger.info(f"✅ Found email for {connector_name}: {enrichment_result['email']} (confidence: {enrichment_result.get('confidence', 0)})")
                else:
                    failed_results.append({
                        'connection': connection_data,
                        'error': 'No email found'
                    })
                    logger.info(f"❌ No email found for {connector_name}")
                
            except Exception as e:
                logger.error(f"Enrichment failed for connection {connection_data.get('connector_name', 'unknown')}: {e}")
                failed_results.append({
                    'connection': connection_data,
                    'error': str(e)
                })
        
        # Record cost tracking
        if total_cost > 0:
            cursor = db.cursor()
            try:
                cursor.execute("""
                    INSERT INTO email_costs (tenant_id, date, service, operation, count, unit_cost, total_cost)
                    VALUES (%s, %s, 'cufinder', 'enrichment', %s, %s, %s)
                    ON CONFLICT(tenant_id, date, service, operation) DO UPDATE SET 
                        count = count + %s,
                        total_cost = total_cost + %s
                """, (
                    tenant_id, datetime.now().date(),
                    len(enriched_results), 0.03, total_cost,
                    len(enriched_results), total_cost
                ))
                db.commit()
            except Exception as e:
                logger.warning(f"Failed to record enrichment cost: {e}")
        
        logger.info(f"Enrichment completed: {len(enriched_results)} enriched, {len(failed_results)} failed, cost: ${total_cost}")
        
        return MutualConnectionEnrichmentResponse(
            success=True,
            enriched=enriched_results,
            failed=failed_results,
            total_cost=total_cost
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Mutual connections enrichment failed: {e}")
        
        if error_classifier:
            error_classifier.record_provider_error(
                'cufinder', 'enrichment_error', str(e), tenant_id
            )
        
        raise HTTPException(status_code=500, detail="Mutual connections enrichment failed")

@router.get("/enrichment/status")
async def get_enrichment_status(
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Get current enrichment status and quotas
    """
    try:
        cursor = db.cursor()
        
        # Get enrichment stats for today
        cursor.execute("""
            SELECT 
                COUNT(*) as enriched_today,
                SUM(CASE WHEN email_confidence >= 0.85 THEN 1 ELSE 0 END) as high_confidence_today
            FROM contacts
            WHERE tenant_id = %s
            AND DATE(email_last_verified) = DATE(%s)
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None), datetime.now()))
        
        today_stats = cursor.fetchone()
        
        # Get cost for today
        cursor.execute("""
            SELECT COALESCE(SUM(total_cost), 0) as cost_today
            FROM email_costs
            WHERE tenant_id = %s
            AND service = 'cufinder'
            AND date = DATE(%s)
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None), datetime.now()))
        
        cost_stats = cursor.fetchone()
        
        return {
            'enriched_today': today_stats['enriched_today'] if today_stats else 0,
            'high_confidence_today': today_stats['high_confidence_today'] if today_stats else 0,
            'cost_today': float(cost_stats['cost_today']) if cost_stats else 0.0,
            'daily_limit': 1000,  # Could be configurable per tenant
            'remaining_quota': max(0, 1000 - (today_stats['enriched_today'] if today_stats else 0))
        }
        
    except Exception as e:
        logger.error(f"Failed to get enrichment status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get enrichment status")

# AI Message generation endpoint
class MessageGenerationRequest(BaseModel):
    prospect_name: str
    prospect_company: Optional[str] = None
    connector_name: str
    connector_title: Optional[str] = None
    connector_company: Optional[str] = None
    message_type: str = "warm_intro"
    channel: str = "linkedin"
    custom_prompt: Optional[str] = None  # New field for custom user prompts
    
    @field_validator('message_type')
    def validate_message_type(cls, v: str) -> str:
        allowed_types = ['warm_intro', 'follow_up', 'direct_outreach', 'referral_request', 'thank_you', 're_engagement', 'custom']
        if v not in allowed_types:
            raise ValueError(f"Message type must be one of: {allowed_types}")
        return v
    
    @field_validator('channel')
    def validate_channel(cls, v: str) -> str:
        allowed_channels = ['linkedin', 'email']
        if v not in allowed_channels:
            raise ValueError(f"Channel must be one of: {allowed_channels}")
        return v
    
    @field_validator('custom_prompt')
    def validate_custom_prompt(cls, v: Optional[str], info: FieldValidationInfo) -> Optional[str]:
        # If message_type is 'custom', custom_prompt is required
        data = info.data or {}
        if data.get('message_type') == 'custom' and (not v or v.strip() == ''):
            raise ValueError("custom_prompt is required when message_type is 'custom'")
        # Limit custom prompt length
        if v and len(v) > 2000:
            raise ValueError("custom_prompt must be 2000 characters or less")
        return v

class MessageGenerationResponse(BaseModel):
    generated_message: str
    tokens_used: int
    cost: float
    generation_time_ms: int
    personalization_score: float

@router.post("/generate-message", response_model=MessageGenerationResponse)
async def generate_ai_message(
    request: MessageGenerationRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Generate AI-powered personalized introduction message
    """
    try:
        # 🚀 SURGICAL DEBUGGING START - AI Message Generation
        logger.info(f"🚀 [AI GEN DEBUG] AI message generation request initiated")
        logger.info(f"🔍 [AI GEN DEBUG] Request parameters:")
        logger.info(f"   - prospect_name: {request.prospect_name}")
        logger.info(f"   - prospect_company: {request.prospect_company}")
        logger.info(f"   - connector_name: {request.connector_name}")
        logger.info(f"   - connector_title: {request.connector_title}")
        logger.info(f"   - connector_company: {request.connector_company}")
        logger.info(f"   - message_type: {request.message_type}")
        logger.info(f"   - channel: {request.channel}")
        
        # 🔍 SURGICAL DEBUGGING - Custom Prompt Feature
        if request.custom_prompt:
            logger.info(f"🎨 [CUSTOM PROMPT DEBUG] Custom prompt feature activated!")
            logger.info(f"🎨 [CUSTOM PROMPT DEBUG] Message type: {request.message_type}")
            logger.info(f"🎨 [CUSTOM PROMPT DEBUG] Custom prompt analysis:")
            logger.info(f"   - Length: {len(request.custom_prompt)} characters")
            logger.info(f"   - Word count: {len(request.custom_prompt.split())}")
            logger.info(f"   - Contains 'write': {'write' in request.custom_prompt.lower()}")
            logger.info(f"   - Contains 'mention': {'mention' in request.custom_prompt.lower()}")
            logger.info(f"   - Contains question marks: {'?' in request.custom_prompt}")
            logger.info(f"   - First 150 chars: {request.custom_prompt[:150]}{'...' if len(request.custom_prompt) > 150 else ''}")
            logger.info(f"🎨 [CUSTOM PROMPT DEBUG] Validation status:")
            logger.info(f"   - Message type is 'custom': {request.message_type == 'custom'}")
            logger.info(f"   - Prompt provided: {bool(request.custom_prompt)}")
            logger.info(f"   - Length within limits: {len(request.custom_prompt) <= 2000}")
        else:
            if request.message_type == 'custom':
                logger.error(f"❌ [CUSTOM PROMPT DEBUG] CRITICAL: message_type is 'custom' but no custom_prompt provided!")
            else:
                logger.info(f"📝 [CUSTOM PROMPT DEBUG] Using standard predefined prompt for message_type: {request.message_type}")
        
        # Debug current_user structure with full detail
        logger.info(f"🔍 [AI GEN DEBUG] current_user analysis:")
        logger.info(f"   - type: {type(current_user)}")
        logger.info(f"   - is_dict: {isinstance(current_user, dict)}")
        if isinstance(current_user, dict):
            logger.info(f"   - keys: {list(current_user.keys())}")
            for key, value in current_user.items():
                logger.info(f"   - {key}: {value}")
        else:
            logger.info(f"   - attributes: {dir(current_user) if hasattr(current_user, '__dict__') else 'No attributes'}")
            
        # Safe tenant_id extraction with detailed debugging
        tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
        user_id = current_user.get('id') if isinstance(current_user, dict) else getattr(current_user, 'id', None)
        
        logger.info(f"🔍 [AI GEN DEBUG] Extracted identifiers:")
        logger.info(f"   - tenant_id: {tenant_id} (type: {type(tenant_id)})")
        logger.info(f"   - user_id: {user_id} (type: {type(user_id)})")
        
        if not tenant_id:
            logger.error(f"❌ [AI GEN DEBUG] CRITICAL: No tenant_id found")
            logger.error(f"❌ [AI GEN DEBUG] current_user full dump: {current_user}")
            raise HTTPException(status_code=403, detail="User not associated with tenant")
        
        # Get OpenAI client with detailed debugging
        logger.info(f"🔧 [AI GEN DEBUG] Attempting to get OpenAI client for tenant_id: {tenant_id}")
        try:
            from integrations.openai_client import get_openai_client
            logger.info(f"✅ [AI GEN DEBUG] OpenAI client module imported successfully")
            
            openai_client = await get_openai_client(tenant_id=tenant_id)
            logger.info(f"🔧 [AI GEN DEBUG] OpenAI client call completed")
            logger.info(f"🔧 [AI GEN DEBUG] OpenAI client result: {openai_client} (type: {type(openai_client)})")
            
        except Exception as client_error:
            logger.error(f"❌ [AI GEN DEBUG] CRITICAL: OpenAI client creation failed!")
            logger.error(f"❌ [AI GEN DEBUG] Client error type: {type(client_error).__name__}")
            logger.error(f"❌ [AI GEN DEBUG] Client error message: {str(client_error)}")
            logger.error(f"❌ [AI GEN DEBUG] Client error traceback:", exc_info=True)
            raise HTTPException(
                status_code=500, 
                detail=f"OpenAI client creation failed: {str(client_error)}"
            )
        
        if not openai_client:
            logger.error(f"❌ [AI GEN DEBUG] OpenAI client is None - integration not configured")
            raise HTTPException(
                status_code=400, 
                detail="OpenAI integration not configured for this tenant"
            )
        
        logger.info(f"✅ [AI GEN DEBUG] OpenAI client obtained successfully")
        logger.info(f"🔧 [AI GEN DEBUG] OpenAI client attributes:")
        if hasattr(openai_client, '__dict__'):
            for attr_name, attr_value in openai_client.__dict__.items():
                if 'api_key' not in attr_name.lower():  # Don't log API keys
                    logger.info(f"   - {attr_name}: {attr_value}")
                else:
                    logger.info(f"   - {attr_name}: ***hidden***")
        
        # Generate message with detailed debugging
        logger.info(f"📝 [AI GEN DEBUG] Starting message generation...")
        import time
        start_time = time.time()
        
        try:
            logger.info(f"📝 [AI GEN DEBUG] Calling generate_introduction_message with parameters:")
            logger.info(f"   - prospect_name: '{request.prospect_name}'")
            logger.info(f"   - prospect_company: '{request.prospect_company or ''}'")
            logger.info(f"   - connector_name: '{request.connector_name}'")
            logger.info(f"   - connector_title: '{request.connector_title or ''}'")
            logger.info(f"   - connector_company: '{request.connector_company or ''}'")
            logger.info(f"   - message_type: '{request.message_type}'")
            logger.info(f"   - channel: '{request.channel}'")
            logger.info(f"   - custom_prompt: {'Present' if request.custom_prompt else 'None'}")
            if request.custom_prompt:
                logger.info(f"   - custom_prompt_length: {len(request.custom_prompt)} chars")
            
            result = await openai_client.generate_introduction_message(
                prospect_name=request.prospect_name,
                prospect_company=request.prospect_company or "",
                connector_name=request.connector_name,
                connector_title=request.connector_title or "",
                connector_company=request.connector_company or "",
                message_type=request.message_type,
                channel=request.channel,
                custom_prompt=request.custom_prompt  # Pass custom prompt to OpenAI client
            )
            
            generation_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"✅ [AI GEN DEBUG] Message generation completed successfully!")
            logger.info(f"📝 [AI GEN DEBUG] Generation time: {generation_time_ms}ms")
            
            # Debug the result structure
            logger.info(f"📝 [AI GEN DEBUG] Result analysis:")
            logger.info(f"   - result type: {type(result)}")
            if hasattr(result, '__dict__'):
                for attr_name, attr_value in result.__dict__.items():
                    if attr_name == 'message':
                        logger.info(f"   - {attr_name}: {str(attr_value)[:100]}...")
                    else:
                        logger.info(f"   - {attr_name}: {attr_value}")
            elif isinstance(result, dict):
                for key, value in result.items():
                    if key == 'message':
                        logger.info(f"   - {key}: {str(value)[:100]}...")
                    else:
                        logger.info(f"   - {key}: {value}")
            else:
                logger.info(f"   - result: {str(result)[:200]}...")
                
        except Exception as gen_error:
            logger.error(f"❌ [AI GEN DEBUG] CRITICAL: Message generation failed!")
            logger.error(f"❌ [AI GEN DEBUG] Generation error type: {type(gen_error).__name__}")
            logger.error(f"❌ [AI GEN DEBUG] Generation error message: {str(gen_error)}")
            logger.error(f"❌ [AI GEN DEBUG] Generation error traceback:", exc_info=True)
            raise HTTPException(
                status_code=500, 
                detail=f"Message generation failed: {str(gen_error)}"
            )
        
        # Track usage/cost with detailed debugging
        logger.info(f"💰 [AI GEN DEBUG] Recording cost tracking...")
        if tenant_id:
            try:
                logger.info(f"💰 [AI GEN DEBUG] Cost details:")
                logger.info(f"   - tenant_id: {tenant_id}")
                logger.info(f"   - result.cost: {result.cost}")
                logger.info(f"   - date: {datetime.now().date()}")
                
                cursor = db.cursor()
                cursor.execute("""
                    INSERT INTO email_costs (tenant_id, date, service, operation, count, unit_cost, total_cost)
                    VALUES (%s, %s, 'openai', 'message_generation', %s, %s, %s)
                    ON CONFLICT(tenant_id, date, service, operation) DO UPDATE SET 
                        count = email_costs.count + EXCLUDED.count,
                        total_cost = email_costs.total_cost + EXCLUDED.total_cost
                """, (
                    tenant_id, datetime.now().date(),
                    1, result.cost, result.cost
                ))
                db.commit()
                logger.info(f"✅ [AI GEN DEBUG] Cost tracking recorded successfully")
                
            except Exception as cost_error:
                logger.error(f"⚠️ [AI GEN DEBUG] Cost tracking failed (non-critical):")
                logger.error(f"   - error type: {type(cost_error).__name__}")
                logger.error(f"   - error message: {str(cost_error)}")
                logger.error(f"   - cost error traceback:", exc_info=True)
        
        # Prepare response with detailed debugging
        logger.info(f"📤 [AI GEN DEBUG] Preparing response...")
        try:
            response = MessageGenerationResponse(
                generated_message=result.message,
                tokens_used=result.tokens_used,
                cost=result.cost,
                generation_time_ms=generation_time_ms,
                personalization_score=result.personalization_score
            )
            logger.info(f"✅ [AI GEN DEBUG] Response created successfully")
            logger.info(f"📤 [AI GEN DEBUG] Response message length: {len(response.generated_message)} characters")
            logger.info(f"📤 [AI GEN DEBUG] Response tokens: {response.tokens_used}")
            logger.info(f"📤 [AI GEN DEBUG] Response cost: ${response.cost}")
            return response
            
        except Exception as response_error:
            logger.error(f"❌ [AI GEN DEBUG] CRITICAL: Response creation failed!")
            logger.error(f"❌ [AI GEN DEBUG] Response error type: {type(response_error).__name__}")
            logger.error(f"❌ [AI GEN DEBUG] Response error message: {str(response_error)}")
            logger.error(f"❌ [AI GEN DEBUG] Response error traceback:", exc_info=True)
            raise HTTPException(
                status_code=500, 
                detail=f"Response creation failed: {str(response_error)}"
            )
        
    except HTTPException as http_e:
        logger.error(f"❌ [AI GEN DEBUG] HTTP Exception caught:")
        logger.error(f"   - status_code: {http_e.status_code}")
        logger.error(f"   - detail: {http_e.detail}")
        raise
    except Exception as e:
        logger.error(f"❌ [AI GEN DEBUG] CRITICAL: Unexpected error in generate_ai_message!")
        logger.error(f"❌ [AI GEN DEBUG] Error type: {type(e).__name__}")
        logger.error(f"❌ [AI GEN DEBUG] Error message: {str(e)}")
        logger.error(f"❌ [AI GEN DEBUG] Full traceback:", exc_info=True)
        
        # Enhanced error recording
        try:
            if error_classifier:
                # Extract tenant_id for error recording
                tenant_id_for_error = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
                logger.info(f"📊 [AI GEN DEBUG] Recording error for tenant_id: {tenant_id_for_error}")
                error_classifier.record_provider_error(
                    'openai', 'message_generation_failed', str(e), 
                    tenant_id_for_error
                )
                logger.info(f"✅ [AI GEN DEBUG] Error recorded successfully")
        except Exception as error_record_failure:
            logger.error(f"⚠️ [AI GEN DEBUG] Failed to record error: {error_record_failure}")
        
        raise HTTPException(status_code=500, detail=f"AI message generation failed: {str(e)}")

# Campaign management endpoints
@router.post("/campaign/create", response_model=EmailCampaignResponse)
async def create_email_campaign(
    request: EmailCampaignRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Create email campaign with AI-generated messages
    """
    try:
        # Validate prospect belongs to user's tenant
        cursor = db.cursor()
        cursor.execute("""
            SELECT id FROM prospects 
            WHERE id = %s AND tenant_id = %s
        """, (request.prospect_id, current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)))
        
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Prospect not found")
        
        # Validate introducers belong to user's tenant
        tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
        
        # Apply same PostgreSQL fix for introducer validation
        import sqlite3
        is_sqlite = isinstance(db, sqlite3.Connection)
        
        if is_sqlite:
            # SQLite syntax: Use ? placeholders
            placeholders = ','.join(['?' for _ in request.introducer_ids])
            query = f"""
                SELECT COUNT(*) as count
                FROM contacts 
                WHERE id IN ({placeholders}) AND tenant_id = ?
            """
            params = list(request.introducer_ids) + [tenant_id]
            cursor.execute(query, params)
        else:
            # PostgreSQL syntax: Handle single vs multiple elements
            if len(request.introducer_ids) == 1:
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM contacts 
                    WHERE id = %s AND tenant_id = %s
                """, (request.introducer_ids[0], tenant_id))
            else:
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM contacts 
                    WHERE id IN %s AND tenant_id = %s
                """, (tuple(request.introducer_ids), tenant_id))
        
        contact_count = cursor.fetchone()['count']
        if contact_count != len(request.introducer_ids):
            raise HTTPException(
                status_code=400, 
                detail="Some introducers not found or not accessible"
            )
        
        # Create campaign
        campaign = await email_service.create_campaign(
            prospect_id=request.prospect_id,
            introducer_ids=request.introducer_ids,
            tenant_id=current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),
            user_id=current_user.get('id') if isinstance(current_user, dict) else getattr(current_user, 'id', None),
            message_type=request.message_type,
            use_ai=request.use_ai_generation,
            channel_preference=request.channel_preference,
            schedule_send=request.schedule_send,
            ab_test=request.ab_test,
            db=db
        )
        
        # If scheduled, queue for background processing
        if request.schedule_send:
            background_tasks.add_task(
                _process_scheduled_campaign,
                campaign['id'],
                current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
            )
        
        logger.info(f"Campaign {campaign['id']} created with {campaign['total_messages']} messages")
        
        return EmailCampaignResponse(**campaign)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Campaign creation failed: {e}")
        raise HTTPException(status_code=500, detail="Campaign creation failed")

@router.get("/campaign/{campaign_id}/preview")
async def preview_campaign(
    campaign_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Preview campaign messages before sending
    """
    try:
        # Verify campaign ownership
        cursor = db.cursor()
        cursor.execute("""
            SELECT id FROM email_campaigns
            WHERE id = %s AND tenant_id = %s
        """, (campaign_id, current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)))
        
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        preview = await email_service.get_campaign_preview(
            campaign_id=campaign_id,
            tenant_id=current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),
            db=db
        )
        
        return preview
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Campaign preview failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate preview")

@router.post("/campaign/{campaign_id}/send")
async def send_campaign(
    campaign_id: int,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
    test_mode: bool = Query(False, description="Send in test mode (emails not actually sent)")
):
    """
    Send email campaign
    """
    try:
        # Verify campaign ownership and status
        cursor = db.cursor()
        cursor.execute("""
            SELECT id, status FROM email_campaigns
            WHERE id = %s AND tenant_id = %s
        """, (campaign_id, current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)))
        
        campaign = cursor.fetchone()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        if campaign['status'] not in ['draft', 'scheduled']:
            raise HTTPException(
                status_code=400, 
                detail=f"Campaign cannot be sent, current status: {campaign['status']}"
            )
        
        # Execute send in background
        background_tasks.add_task(
            _send_campaign_background,
            campaign_id,
            current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),
            test_mode
        )
        
        return {
            "status": "queued",
            "campaign_id": campaign_id,
            "test_mode": test_mode,
            "message": "Campaign queued for sending"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Campaign send failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to queue campaign")

@router.get("/campaign/{campaign_id}/status")
async def get_campaign_status(
    campaign_id: int,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Get campaign status and statistics
    """
    try:
        cursor = db.cursor()
        
        # Get campaign details
        cursor.execute("""
            SELECT * FROM email_campaigns
            WHERE id = %s AND tenant_id = %s
        """, (campaign_id, current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)))
        
        campaign = cursor.fetchone()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Get message status breakdown
        cursor.execute("""
            SELECT 
                status,
                email_status,
                COUNT(*) as count
            FROM outreach_queue
            WHERE campaign_id = %s
            GROUP BY status, email_status
        """, (campaign_id,))
        
        status_breakdown = cursor.fetchall()
        
        return {
            'campaign': dict(campaign),
            'status_breakdown': [dict(s) for s in status_breakdown]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get campaign status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get campaign status")

# Analytics and metrics endpoints
@router.get("/metrics/dashboard", response_model=MetricsResponse)
async def get_email_metrics(
    days: int = Query(30, ge=1, le=365, description="Number of days to include in metrics"),
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Get comprehensive email metrics for dashboard
    """
    try:
        date_from = datetime.now() - timedelta(days=days)
        date_to = datetime.now()
        
        metrics = await email_service.get_tenant_metrics(
            tenant_id=current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),
            date_from=date_from,
            date_to=date_to,
            db=db
        )
        
        return MetricsResponse(**metrics)
        
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve metrics")

@router.get("/campaigns")
async def list_campaigns(
    status: Optional[str] = Query(None, description="Filter by campaign status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    List email campaigns for tenant
    """
    try:
        cursor = db.cursor()
        
        # Build query
        where_clause = "WHERE tenant_id = %s"
        params = [current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)]
        
        if status:
            where_clause += " AND status = %s"
            params.append(status)
        
        cursor.execute(f"""
            SELECT 
                c.*,
                p.full_name as prospect_name,
                p.company as prospect_company
            FROM email_campaigns c
            JOIN prospects p ON c.prospect_id = p.id
            {where_clause}
            ORDER BY c.created_at DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        
        campaigns = cursor.fetchall()
        
        # Get total count
        cursor.execute(f"""
            SELECT COUNT(*) as total
            FROM email_campaigns c
            {where_clause}
        """, params)
        
        total = cursor.fetchone()['total']
        
        return {
            'campaigns': [dict(c) for c in campaigns],
            'total': total,
            'limit': limit,
            'offset': offset
        }
        
    except Exception as e:
        logger.error(f"Failed to list campaigns: {e}")
        raise HTTPException(status_code=500, detail="Failed to list campaigns")

# Settings and configuration endpoints
@router.put("/settings", response_model=EmailSettingsResponse)
async def update_email_settings(
    settings_request: EmailSettingsRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Update tenant email settings
    """
    try:
        # Check if user is admin
        user_role = current_user.get('role') if isinstance(current_user, dict) else getattr(current_user, 'role', None)
        if user_role not in ['admin', 'owner']:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        # Filter out None values
        settings_dict = {k: v for k, v in settings_request.dict().items() if v is not None}
        
        if not settings_dict:
            raise HTTPException(status_code=400, detail="No settings provided")
        
        result = await email_service.update_tenant_settings(
            tenant_id=current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),
            settings=settings_dict,
            db=db
        )
        
        return EmailSettingsResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update settings")

@router.get("/settings")
async def get_email_settings(
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Get current email settings for tenant
    """
    try:
        cursor = db.cursor()
        cursor.execute("""
            SELECT 
                from_email, from_name, reply_to_email, domain_verified,
                spf_verified, dkim_verified, dmarc_verified,
                warmup_status, daily_limit, current_reputation_score,
                total_sent, total_bounced
            FROM tenant_email_settings
            WHERE tenant_id = %s
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),))
        
        settings = cursor.fetchone()
        
        if not settings:
            return {
                'configured': False,
                'message': 'Email settings not configured'
            }
        
        return {
            'configured': True,
            'settings': dict(settings)
        }
        
    except Exception as e:
        logger.error(f"Failed to get settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve settings")

@router.post("/verify-domain")
async def verify_domain(
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Initiate or check domain verification
    """
    try:
        user_role = current_user.get('role') if isinstance(current_user, dict) else getattr(current_user, 'role', None)
        if user_role not in ['admin', 'owner']:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        cursor = db.cursor()
        cursor.execute("""
            SELECT from_email FROM tenant_email_settings
            WHERE tenant_id = %s
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),))
        
        settings = cursor.fetchone()
        if not settings or not settings['from_email']:
            raise HTTPException(status_code=400, detail="No sender email configured")
        
        domain = settings['from_email'].split('@')[1]
        
        # Use SendGrid client to verify domain
        from integrations.sendgrid_client import get_sendgrid_client
        sendgrid = get_sendgrid_client(current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None))
        
        verification_result = await sendgrid.verify_domain(domain)
        
        return verification_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Domain verification failed: {e}")
        raise HTTPException(status_code=500, detail="Domain verification failed")

# Webhook endpoints
@router.post("/webhook/sendgrid")
async def handle_sendgrid_webhook(
    events: List[Dict[str, Any]],
    background_tasks: BackgroundTasks,
    db=Depends(get_db)
):
    """
    Handle SendGrid webhook events
    """
    try:
        logger.info(f"Received {len(events)} webhook events from SendGrid")
        
        # Process events in background
        background_tasks.add_task(_process_webhook_events, events)
        
        return {"received": len(events)}
        
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

# Suppression list endpoints
@router.post("/suppression/add")
async def add_to_suppression_list(
    email: EmailStr,
    reason: str,
    suppression_type: str = "manual",
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Add email to suppression list
    """
    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO email_suppression_list (tenant_id, email, reason, type, added_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE reason = %s, type = %s
        """, (
            current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None), email, reason, suppression_type,
            datetime.now(), reason, suppression_type
        ))
        
        db.commit()
        
        return {"success": True, "message": f"Email {email} added to suppression list"}
        
    except Exception as e:
        logger.error(f"Failed to add to suppression list: {e}")
        raise HTTPException(status_code=500, detail="Failed to add to suppression list")

@router.get("/suppression/list")
async def get_suppression_list(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Get suppression list for tenant
    """
    try:
        cursor = db.cursor()
        cursor.execute("""
            SELECT email, reason, type, added_at
            FROM email_suppression_list
            WHERE tenant_id = %s
            ORDER BY added_at DESC
            LIMIT %s OFFSET %s
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None), limit, offset))
        
        suppressed = cursor.fetchall()
        
        # Get total count
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM email_suppression_list
            WHERE tenant_id = %s
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),))
        
        total = cursor.fetchone()['total']
        
        return {
            'suppressed_emails': [dict(s) for s in suppressed],
            'total': total,
            'limit': limit,
            'offset': offset
        }
        
    except Exception as e:
        logger.error(f"Failed to get suppression list: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve suppression list")

# Background task functions
async def _send_campaign_background(campaign_id: int, tenant_id: int, test_mode: bool = False):
    """Background task to send campaign"""
    try:
        stats = await email_service.send_campaign(
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            test_mode=test_mode
        )
        logger.info(f"Campaign {campaign_id} sent: {stats.sent}/{stats.total_recipients}")
    except Exception as e:
        logger.error(f"Background campaign send failed: {e}")

async def _process_scheduled_campaign(campaign_id: int, tenant_id: int):
    """Background task to process scheduled campaign"""
    try:
        # Wait until scheduled time
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            SELECT scheduled_for FROM email_campaigns
            WHERE id = %s AND tenant_id = %s
        """, (campaign_id, tenant_id))
        
        campaign = cursor.fetchone()
        db.close()
        
        if campaign and campaign['scheduled_for']:
            wait_seconds = (campaign['scheduled_for'] - datetime.now()).total_seconds()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            
            # Send campaign
            await _send_campaign_background(campaign_id, tenant_id)
            
    except Exception as e:
        logger.error(f"Scheduled campaign processing failed: {e}")

async def _process_webhook_events(events: List[Dict]):
    """Background task to process webhook events"""
    try:
        for event in events:
            await email_service.process_webhook_event(event)
    except Exception as e:
        logger.error(f"Webhook event processing failed: {e}")

# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check for email service"""
    try:
        # Check database connection
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT 1")
        db.close()
        
        # Could add checks for external services here
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {
                "database": "connected",
                "email_service": "ready"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

# Admin endpoints for email settings management  
admin_router = APIRouter(prefix="/admin/email", tags=["admin-email"])

class EmailSettingsRequest(BaseModel):
    sendgrid_api_key: Optional[str] = None
    sendgrid_domain: Optional[str] = None
    cufinder_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    daily_send_limit: Optional[int] = None
    warmup_enabled: Optional[bool] = None
    warmup_daily_increase: Optional[int] = None
    warmup_max_per_day: Optional[int] = None
    bounce_threshold: Optional[int] = None
    suppress_bounces: Optional[bool] = None
    suppress_complaints: Optional[bool] = None
    suppress_unsubscribes: Optional[bool] = None
    cost_alert_threshold: Optional[int] = None
    enrichment_confidence_threshold: Optional[float] = None

class DomainVerificationRequest(BaseModel):
    domain: str

@admin_router.get("/diagnostics/providers")
async def diagnostics_providers(
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Return provider diagnostics for the current tenant (OpenAI, CUFinder)."""
    try:
        tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
        if not tenant_id:
            raise HTTPException(status_code=403, detail="Tenant context required")

        # Resolve OpenAI client and basic status
        openai_info = {"ready": False, "model": None, "key_present": False}
        try:
            from integrations.openai_client import get_openai_client
            client = await get_openai_client(tenant_id)
            openai_info.update({
                "ready": True,
                "model": getattr(client, 'model', None),
            })
            # We don't expose keys; just flag presence
            openai_info["key_present"] = True
        except Exception as e:
            openai_info["error"] = str(e)

        # CUFinder key presence
        cufinder_info = {"ready": False, "key_present": False}
        try:
            from integrations.apify_client import get_tenant_integration_settings
            settings = get_tenant_integration_settings(tenant_id)
            cufinder_key = settings.get('cufinder_api_key')
            cufinder_info["key_present"] = bool(cufinder_key and cufinder_key.strip())
            if cufinder_info["key_present"]:
                # Try constructing client without making a network call
                from integrations.cufinder_client import get_cufinder_client
                try:
                    client = get_cufinder_client(tenant_id, fail_on_missing=False)
                    if client.is_configured:
                        cufinder_info["ready"] = True
                    else:
                        cufinder_info["error"] = client.configuration_reason
                except Exception as exc:
                    cufinder_info["error"] = str(exc)
        except Exception as e:
            cufinder_info["error"] = str(e)

        # Provider health last errors
        providers_health = {}
        try:
            cursor = db.cursor()
            # Get last 5 records per provider
            cursor.execute(
                """
                SELECT provider, error_type, error_count, cooldown_until, last_error_at
                FROM provider_health
                WHERE tenant_id = ?
                ORDER BY last_error_at DESC
                LIMIT 20
                """,
                (tenant_id,)
            )
            rows = cursor.fetchall()
            for row in rows:
                prov = row['provider']
                providers_health.setdefault(prov, []).append({
                    'error_type': row['error_type'],
                    'error_count': row['error_count'],
                    'cooldown_until': row['cooldown_until'],
                    'last_error_at': row['last_error_at']
                })
        except Exception as e:
            providers_health = {"error": str(e)}

        # cufinder_cache table existence
        cache_exists = False
        try:
            cursor = db.cursor()
            cursor.execute("SELECT 1 FROM cufinder_cache LIMIT 1")
            _ = cursor.fetchone()
            cache_exists = True
        except Exception:
            cache_exists = False

        return {
            'tenant_id': tenant_id,
            'openai': openai_info,
            'cufinder': {**cufinder_info, 'cache_table_exists': cache_exists},
            'provider_health': providers_health
        }
    except Exception as e:
        logger.error(f"Diagnostics failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get provider diagnostics")

@admin_router.get("/readiness")
async def readiness_check(
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Quick readiness check for OpenAI and CUFinder for the tenant."""
    tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
    openai_ready = False
    cufinder_ready = False
    cache_ok = False
    details = {}

    try:
        from integrations.openai_client import get_openai_client
        client = await get_openai_client(tenant_id)
        openai_ready = bool(client and getattr(client, 'model', None))
        details['openai_model'] = getattr(client, 'model', None)
    except Exception as e:
        details['openai_error'] = str(e)

    try:
        from integrations.apify_client import get_tenant_integration_settings
        s = get_tenant_integration_settings(tenant_id)
        # Consider CUFinder ready if a key is configured; avoid failing readiness on init errors
        cufinder_ready = bool((s.get('cufinder_api_key') or '').strip())
        if not cufinder_ready:
            details['cufinder_error'] = 'No CUFinder API key configured for tenant'
    except Exception as e:
        details['cufinder_error'] = str(e)

    try:
        cursor = db.cursor()
        cursor.execute("SELECT 1 FROM cufinder_cache LIMIT 1")
        _ = cursor.fetchone()
        cache_ok = True
    except Exception:
        cache_ok = False

    # Attempt to create cufinder_cache table if missing (PostgreSQL-safe)
    if not cache_ok:
        try:
            # Load migration SQL
            migration_sql = None
            for p in ['migrations/013_add_cufinder_cache_postgresql.sql', 'create_cufinder_cache_table.sql']:
                try:
                    with open(p, 'r') as f:
                        migration_sql = f.read()
                        break
                except Exception:
                    continue
            if migration_sql:
                for stmt in [s.strip() for s in migration_sql.split(';') if s.strip()]:
                    try:
                        cursor = db.cursor()
                        cursor.execute(stmt)
                    except Exception as e:
                        # Ignore already-exists statements
                        if 'already exists' not in str(e).lower():
                            details['cufinder_cache_migration_warning'] = str(e)
                # Re-check existence
                cursor = db.cursor()
                cursor.execute("SELECT 1 FROM cufinder_cache LIMIT 1")
                _ = cursor.fetchone()
                cache_ok = True
        except Exception as e:
            details['cufinder_cache_migration_error'] = str(e)

    return {
        'tenant_id': tenant_id,
        'openai_ready': openai_ready,
        'cufinder_ready': cufinder_ready,
        'cufinder_cache_table_exists': cache_ok,
        'details': details
    }

@admin_router.get("/settings")
async def get_admin_email_settings(
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Get admin email settings for tenant"""
    try:
        # Check admin permissions
        user_role = current_user.get('role') if isinstance(current_user, dict) else getattr(current_user, 'role', None)
        if user_role not in ['admin', 'owner']:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        # Get tenant settings from encrypted storage
        from integrations.sendgrid_client import get_tenant_integration_settings
        
        settings = get_tenant_integration_settings(current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None))
        
        # Get email configuration from tenant_email_settings
        cursor = db.cursor()
        cursor.execute("""
            SELECT 
                daily_limit, warmup_enabled, warmup_daily_increase, warmup_max_per_day,
                bounce_threshold, current_reputation_score, domain_verified
            FROM tenant_email_settings
            WHERE tenant_id = %s
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),))
        
        email_config = cursor.fetchone()
        
        # Combine settings (mask sensitive data)
        response = {
            'sendgrid_api_key': '***' if settings.get('sendgrid_api_key') else None,
            'sendgrid_domain': settings.get('sendgrid_domain'),
            'sendgrid_verified': email_config['domain_verified'] if email_config else False,
            'cufinder_api_key': '***' if settings.get('cufinder_api_key') else None,
            'openai_api_key': '***' if settings.get('openai_api_key') else None,
            'daily_send_limit': email_config['daily_limit'] if email_config else 50,
            'warmup_enabled': email_config['warmup_enabled'] if email_config else True,
            'warmup_daily_increase': email_config['warmup_daily_increase'] if email_config else 5,
            'warmup_max_per_day': email_config['warmup_max_per_day'] if email_config else 100,
            'bounce_threshold': email_config['bounce_threshold'] if email_config else 5,
            'suppress_bounces': True,  # Default to True for safety
            'suppress_complaints': True,
            'suppress_unsubscribes': True,
            'cost_alert_threshold': 100,
            'enrichment_confidence_threshold': 0.7
        }
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get admin settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve admin settings")

@admin_router.post("/settings")
async def save_admin_email_settings(
    settings_request: EmailSettingsRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Save admin email settings for tenant"""
    try:
        # Check admin permissions
        user_role = current_user.get('role') if isinstance(current_user, dict) else getattr(current_user, 'role', None)
        if user_role not in ['admin', 'owner']:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        # Save encrypted settings (API keys)
        from integrations.sendgrid_client import save_tenant_integration_settings
        
        encrypted_settings = {}
        if settings_request.sendgrid_api_key:
            encrypted_settings['sendgrid_api_key'] = settings_request.sendgrid_api_key
        if settings_request.sendgrid_domain:
            encrypted_settings['sendgrid_domain'] = settings_request.sendgrid_domain
        if settings_request.cufinder_api_key:
            encrypted_settings['cufinder_api_key'] = settings_request.cufinder_api_key
        if settings_request.openai_api_key:
            encrypted_settings['openai_api_key'] = settings_request.openai_api_key
            
        if encrypted_settings:
            save_tenant_integration_settings(current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None), encrypted_settings)
        
        # Save email configuration settings
        cursor = db.cursor()
        
        # Upsert tenant_email_settings
        cursor.execute("""
            INSERT INTO tenant_email_settings (
                tenant_id, daily_limit, warmup_enabled, warmup_daily_increase, 
                warmup_max_per_day, bounce_threshold, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                daily_limit = COALESCE(%s, daily_limit),
                warmup_enabled = COALESCE(%s, warmup_enabled),
                warmup_daily_increase = COALESCE(%s, warmup_daily_increase),
                warmup_max_per_day = COALESCE(%s, warmup_max_per_day),
                bounce_threshold = COALESCE(%s, bounce_threshold),
                updated_at = %s
        """, (
            current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),
            settings_request.daily_send_limit,
            settings_request.warmup_enabled,
            settings_request.warmup_daily_increase,
            settings_request.warmup_max_per_day,
            settings_request.bounce_threshold,
            datetime.now(),
            # For UPDATE clause
            settings_request.daily_send_limit,
            settings_request.warmup_enabled,
            settings_request.warmup_daily_increase,
            settings_request.warmup_max_per_day,
            settings_request.bounce_threshold,
            datetime.now()
        ))
        
        db.commit()
        
        return {"success": True, "message": "Email settings saved successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save admin settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to save admin settings")

@admin_router.get("/domain-status")
async def get_domain_status(
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Get domain verification and warmup status"""
    try:
        # Check admin permissions
        user_role = current_user.get('role') if isinstance(current_user, dict) else getattr(current_user, 'role', None)
        if user_role not in ['admin', 'owner']:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        cursor = db.cursor()
        cursor.execute("""
            SELECT 
                from_email,
                domain_verified,
                dkim_verified,
                spf_verified,
                current_reputation_score,
                warmup_status,
                daily_limit,
                total_sent
            FROM tenant_email_settings
            WHERE tenant_id = %s
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),))
        
        settings = cursor.fetchone()
        
        if not settings or not settings['from_email']:
            return {
                "domain": None,
                "verified": False,
                "dkim_verified": False,
                "spf_verified": False,
                "reputation_score": 0,
                "warmup_status": "not_started",
                "daily_volume": 0
            }
        
        domain = settings['from_email'].split('@')[1] if '@' in settings['from_email'] else settings['from_email']
        
        # Get today's send volume
        cursor.execute("""
            SELECT COUNT(*) as daily_volume
            FROM email_metrics
            WHERE tenant_id = %s AND DATE(sent_at) = CURDATE()
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),))
        
        volume_data = cursor.fetchone()
        daily_volume = volume_data['daily_volume'] if volume_data else 0
        
        return {
            "domain": domain,
            "verified": bool(settings['domain_verified']),
            "dkim_verified": bool(settings['dkim_verified']),
            "spf_verified": bool(settings['spf_verified']),
            "reputation_score": int(settings['current_reputation_score'] or 0),
            "warmup_status": settings['warmup_status'] or "not_started",
            "daily_volume": daily_volume
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get domain status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get domain status")

@admin_router.get("/usage-stats")
async def get_usage_stats(
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Get email usage statistics for tenant"""
    try:
        cursor = db.cursor()
        
        # Get today's stats
        cursor.execute("""
            SELECT 
                COUNT(CASE WHEN event_type = 'sent' AND DATE(created_at) = CURDATE() THEN 1 END) as emails_sent_today,
                COUNT(CASE WHEN event_type = 'sent' AND MONTH(created_at) = MONTH(NOW()) THEN 1 END) as emails_sent_month,
                SUM(CASE WHEN DATE(created_at) = CURDATE() THEN cost ELSE 0 END) as cost_today,
                SUM(CASE WHEN MONTH(created_at) = MONTH(NOW()) THEN cost ELSE 0 END) as cost_month
            FROM email_metrics
            WHERE tenant_id = %s
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),))
        
        email_stats = cursor.fetchone()
        
        # Get enrichment stats
        cursor.execute("""
            SELECT 
                COUNT(CASE WHEN DATE(enriched_at) = CURDATE() THEN 1 END) as enrichments_today,
                COUNT(CASE WHEN DATE(created_at) = CURDATE() THEN 1 END) as api_calls_today
            FROM contacts
            WHERE tenant_id = %s AND enriched_at IS NOT NULL
        """, (current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None),))
        
        enrichment_stats = cursor.fetchone()
        
        return {
            "emails_sent_today": email_stats['emails_sent_today'] or 0,
            "emails_sent_month": email_stats['emails_sent_month'] or 0,
            "enrichments_today": enrichment_stats['enrichments_today'] or 0,
            "cost_today": float(email_stats['cost_today'] or 0),
            "cost_month": float(email_stats['cost_month'] or 0),
            "api_calls_today": enrichment_stats['api_calls_today'] or 0
        }
        
    except Exception as e:
        logger.error(f"Failed to get usage stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get usage stats")

@admin_router.post("/test-api-key")
async def test_api_key(
    service: str,
    api_key: str,
    current_user=Depends(get_current_user)
):
    """Test API key for external services"""
    try:
        # Check admin permissions
        user_role = current_user.get('role') if isinstance(current_user, dict) else getattr(current_user, 'role', None)
        if user_role not in ['admin', 'owner']:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        if service == "sendgrid":
            from integrations.sendgrid_client import SendGridClient
            client = SendGridClient(api_key=api_key)
            result = await client.test_api_key()
            
        elif service == "cufinder":
            from integrations.cufinder_client import CUFinderClient
            client = CUFinderClient(api_key=api_key)
            result = await client.test_api_key()
            
        elif service == "openai":
            from integrations.openai_client import OpenAIEmailClient
            client = OpenAIEmailClient(api_key=api_key)
            result = await client.test_api_key()
            
        else:
            raise HTTPException(status_code=400, detail="Invalid service")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API key test failed for {service}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to test {service} API key")

@admin_router.post("/verify-domain")
async def verify_domain(
    request: DomainVerificationRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Verify domain for email sending"""
    try:
        # Check admin permissions
        user_role = current_user.get('role') if isinstance(current_user, dict) else getattr(current_user, 'role', None)
        if user_role not in ['admin', 'owner']:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        from integrations.sendgrid_client import get_sendgrid_client
        sendgrid = get_sendgrid_client(current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None))
        
        if not sendgrid:
            raise HTTPException(status_code=400, detail="SendGrid not configured")
        
        # Initiate domain verification
        result = await sendgrid.verify_domain(request.domain)
        
        # Update database with verification status
        cursor = db.cursor()
        cursor.execute("""
            UPDATE tenant_email_settings 
            SET domain_verified = %s, updated_at = %s
            WHERE tenant_id = %s
        """, (result.get('success', False), datetime.now(), current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)))
        
        db.commit()
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Domain verification failed: {e}")
        raise HTTPException(status_code=500, detail="Domain verification failed")

@admin_router.post("/reset-warmup")
async def reset_warmup(
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Reset domain warmup status"""
    try:
        # Check admin permissions
        user_role = current_user.get('role') if isinstance(current_user, dict) else getattr(current_user, 'role', None)
        if user_role not in ['admin', 'owner']:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        cursor = db.cursor()
        cursor.execute("""
            UPDATE tenant_email_settings 
            SET 
                warmup_status = 'not_started',
                current_reputation_score = 0,
                total_sent = 0,
                total_bounced = 0,
                updated_at = %s
            WHERE tenant_id = %s
        """, (datetime.now(), current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)))
        
        db.commit()
        
        return {"success": True, "message": "Domain warmup has been reset"}
        
    except Exception as e:
        logger.error(f"Warmup reset failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset warmup")

# Simple Email Send Models
class EmailSendRequest(BaseModel):
    to: EmailStr
    subject: str
    message: str
    from_email: Optional[EmailStr] = None
    from_name: Optional[str] = None
    # Optional bypass for pre-send verification
    skip_verify: Optional[bool] = False

@router.post("/send")
async def send_email(
    request: EmailSendRequest,
    current_user: Dict = Depends(get_current_user)
):
    """Send a single email via SendGrid"""
    try:
        # 🚀 SURGICAL DEBUGGING START - Send Email Function
        logger.info(f"🚀 [SEND EMAIL DEBUG] Email send request initiated")
        logger.info(f"🔍 [SEND EMAIL DEBUG] Request details - To: {request.to}, Subject: {request.subject[:50]}...")
        logger.info(f"🔍 [SEND EMAIL DEBUG] From: {request.from_email} ({request.from_name})")
        logger.info(f"🔍 [SEND EMAIL DEBUG] Message length: {len(request.message)} characters")
        
        # Debug current_user structure
        logger.info(f"🔍 [SEND EMAIL DEBUG] current_user type: {type(current_user)}")
        logger.info(f"🔍 [SEND EMAIL DEBUG] current_user keys: {list(current_user.keys()) if isinstance(current_user, dict) else 'Not a dict'}")
        
        # Safe tenant_id extraction
        tenant_id = current_user.get('tenant_id') if isinstance(current_user, dict) else getattr(current_user, 'tenant_id', None)
        user_id = current_user.get('id') if isinstance(current_user, dict) else getattr(current_user, 'id', None)
        
        logger.info(f"🔍 [SEND EMAIL DEBUG] Extracted tenant_id: {tenant_id}, user_id: {user_id}")
        
        if not tenant_id:
            logger.error(f"❌ [SEND EMAIL DEBUG] No tenant_id found in current_user")
            raise HTTPException(status_code=400, detail="User tenant information missing")
        
        # Verify recipient email before sending unless bypassed
        if not request.skip_verify:
            try:
                from integrations.cufinder_client import get_cufinder_client
                verifier = get_cufinder_client(tenant_id, fail_on_missing=False)
                if verifier.is_configured:
                    v = await verifier.verify_email(request.to)
                    if not v.get('valid', False):
                        # Only block when verifier explicitly marks invalid
                        raise HTTPException(status_code=400, detail="Recipient email failed verification")
                else:
                    logger.warning(
                        "Skipping recipient verification for tenant %s: %s",
                        tenant_id,
                        verifier.configuration_reason or "CUFinder not configured",
                    )
            except HTTPException:
                raise
            except Exception as _verr:
                logger.warning(f"Verification unavailable, proceeding: {_verr}")

        # Get SendGrid client for tenant
        logger.info(f"🔧 [SEND EMAIL DEBUG] Getting SendGrid client for tenant {tenant_id}")
        from integrations.sendgrid_client import get_sendgrid_client
        sendgrid = get_sendgrid_client(tenant_id)
        
        if not sendgrid:
            logger.error(f"❌ [SEND EMAIL DEBUG] SendGrid not configured for tenant {tenant_id}")
            raise HTTPException(status_code=400, detail="SendGrid not configured for your account")
        
        logger.info(f"✅ [SEND EMAIL DEBUG] SendGrid client obtained successfully for tenant {tenant_id}")
        logger.info(f"🔧 [SEND EMAIL DEBUG] SendGrid client type: {type(sendgrid)}")
        
        # Debug SendGrid configuration
        logger.info(f"🔧 [SEND EMAIL DEBUG] SendGrid from_email: {sendgrid.from_email}")
        logger.info(f"🔧 [SEND EMAIL DEBUG] SendGrid from_name: {sendgrid.from_name}")
        logger.info(f"🔧 [SEND EMAIL DEBUG] SendGrid daily_send_limit: {sendgrid.daily_send_limit}")
        
        # Send the email
        logger.info(f"📧 [SEND EMAIL DEBUG] Initiating email send via SendGrid...")
        logger.info(f"📧 [SEND EMAIL DEBUG] Final email parameters:")
        logger.info(f"   - to_email: {request.to}")
        logger.info(f"   - subject: {request.subject}")
        logger.info(f"   - from_email: {request.from_email}")
        logger.info(f"   - from_name: {request.from_name}")
        logger.info(f"   - html_content length: {len(request.message)}")
        
        result = await sendgrid.send_email(
            to_email=request.to,
            subject=request.subject,
            html_content=request.message,
            from_email=request.from_email,
            from_name=request.from_name
        )
        
        if not getattr(result, 'success', False):
            err = getattr(result, 'error_message', 'send failed')
            logger.error(f"❌ [SEND EMAIL DEBUG] SendGrid send failed for tenant {tenant_id}: {err}")
            raise HTTPException(status_code=502, detail=f"SendGrid send failed: {err}")

        logger.info(f"✅ [SEND EMAIL DEBUG] Email sent successfully!")
        logger.info(f"📧 [SEND EMAIL DEBUG] SendGrid response: {result}")
        logger.info(f"🎉 [SEND EMAIL DEBUG] Email sent successfully to {request.to} for tenant {tenant_id}")
        
        return {
            "success": True,
            "message": "Email sent successfully",
            "message_id": getattr(result, 'message_id', None),
            "to": request.to
        }
        
    except HTTPException as http_e:
        logger.error(f"❌ [SEND EMAIL DEBUG] HTTP Exception: {http_e.detail} (status: {http_e.status_code})")
        raise
    except Exception as e:
        logger.error(f"❌ [SEND EMAIL DEBUG] Unexpected error in send_email: {type(e).__name__}: {str(e)}")
        logger.error(f"❌ [SEND EMAIL DEBUG] Full error details:", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")
