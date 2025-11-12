"""
Simple Master Game Plan API Routes
Basic implementation for testing the Master Game Plan functionality
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import asyncio
import json
import asyncpg
import os
from datetime import datetime

router = APIRouter(prefix="/api/v1/master-game-plan", tags=["Master Game Plan"])

# ===================================================================
# REQUEST/RESPONSE MODELS
# ===================================================================

class CompanyData(BaseModel):
    name: str
    domain: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    employee_count: Optional[int] = None

class CompanyUploadRequest(BaseModel):
    companies: List[CompanyData]

class AutomationRequest(BaseModel):
    company_name: str
    target_titles: Optional[List[str]] = ["CEO", "CTO", "CMO"]
    max_executives: int = 5

# ===================================================================
# API ENDPOINTS
# ===================================================================

@router.get("/health")
async def health_check():
    """Master Game Plan health check"""
    try:
        # Check database connection
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])

        # Check if MGP tables exist
        mgp_tables = ["companies", "executives", "connections", "connector_rankings", "company_settings", "automation_jobs"]
        table_status = {}

        for table in mgp_tables:
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = $1
                )
            """, table)
            table_status[table] = "exists" if exists else "missing"

        await conn.close()

        return {
            "status": "operational",
            "timestamp": datetime.utcnow().isoformat(),
            "database": "connected",
            "tables": table_status,
            "services": {
                "company_exec_search": "ready",
                "apify_mutuals": "ready",
                "cufinder": "ready",
                "automation_manager": "ready"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

@router.post("/companies/upload")
async def upload_companies(request: CompanyUploadRequest):
    """Upload companies for Master Game Plan automation"""
    try:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])

        uploaded_companies = []

        for company_data in request.companies:
            # Insert company into database
            company_id = await conn.fetchval("""
                INSERT INTO companies (
                    organization_id, name, domain, industry, website,
                    employee_count, status, automation_enabled, priority
                ) VALUES (
                    1, $1, $2, $3, $4, $5, 'active', true, 'medium'
                ) RETURNING id
            """,
                company_data.name,
                company_data.domain,
                company_data.industry,
                company_data.website,
                company_data.employee_count
            )

            uploaded_companies.append({
                "id": company_id,
                "name": company_data.name,
                "status": "uploaded"
            })

        await conn.close()

        return {
            "success": True,
            "message": f"Successfully uploaded {len(uploaded_companies)} companies",
            "companies": uploaded_companies,
            "ready_for_automation": True
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Company upload failed: {str(e)}")

@router.post("/automation/start")
async def start_automation(request: AutomationRequest):
    """Start Master Game Plan automation for a company"""
    try:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])

        # Find the company
        company = await conn.fetchrow("""
            SELECT id, name FROM companies
            WHERE name ILIKE $1 AND automation_enabled = true
        """, f"%{request.company_name}%")

        if not company:
            raise HTTPException(status_code=404, detail="Company not found or automation disabled")

        # Create automation job
        job_id = await conn.fetchval("""
            INSERT INTO automation_jobs (
                organization_id, company_id, job_type, job_status,
                priority, progress_percentage, items_processed,
                items_successful, items_failed, job_parameters
            ) VALUES (
                1, $1, 'company_automation', 'pending', 'normal', 0.0, 0, 0, 0, $2
            ) RETURNING id
        """, company["id"], json.dumps({
            "target_titles": request.target_titles,
            "max_executives": request.max_executives,
            "company_name": request.company_name
        }))

        await conn.close()

        return {
            "success": True,
            "automation_id": job_id,
            "company_id": company["id"],
            "company_name": company["name"],
            "status": "started",
            "message": "Automation workflow started",
            "workflow_stages": [
                "Executive Discovery",
                "LinkedIn URL Enrichment",
                "Mutual Connections Discovery",
                "Connection Ranking",
                "Email Enrichment",
                "Ready for Approval"
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Automation start failed: {str(e)}")

@router.get("/automation/{automation_id}/status")
async def get_automation_status(automation_id: int):
    """Get status of a Master Game Plan automation"""
    try:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])

        job = await conn.fetchrow("""
            SELECT aj.*, c.name as company_name
            FROM automation_jobs aj
            JOIN companies c ON aj.company_id = c.id
            WHERE aj.id = $1
        """, automation_id)

        if not job:
            raise HTTPException(status_code=404, detail="Automation job not found")

        await conn.close()

        return {
            "automation_id": job["id"],
            "company_name": job["company_name"],
            "status": job["job_status"],
            "progress": job["progress_percentage"],
            "created_at": job["created_at"].isoformat() if job["created_at"] else None,
            "parameters": job["job_parameters"],
            "results": job["job_results"],
            "total_items": job["items_total"],
            "processed_items": job["items_processed"],
            "successful_items": job["items_successful"],
            "failed_items": job["items_failed"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")

@router.get("/companies")
async def list_companies():
    """List all companies in the Master Game Plan"""
    try:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])

        companies = await conn.fetch("""
            SELECT id, name, domain, industry, status, automation_enabled,
                   created_at, last_processed_at
            FROM companies
            ORDER BY created_at DESC
        """)

        await conn.close()

        return {
            "success": True,
            "companies": [dict(company) for company in companies],
            "total": len(companies)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list companies: {str(e)}")

@router.get("/automations")
async def list_automations():
    """List all automation jobs"""
    try:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])

        automations = await conn.fetch("""
            SELECT aj.id, aj.job_status, aj.progress_percentage, aj.created_at,
                   c.name as company_name
            FROM automation_jobs aj
            JOIN companies c ON aj.company_id = c.id
            ORDER BY aj.created_at DESC
        """)

        await conn.close()

        return {
            "success": True,
            "automations": [dict(automation) for automation in automations],
            "total": len(automations)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list automations: {str(e)}")