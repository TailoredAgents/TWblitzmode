"""
Simple migration endpoint that works without psycopg2 issues
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from .deps import get_current_user

router = APIRouter(prefix="/api/simple")

@router.post("/run-migration")
def run_simple_migration(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Run database migration - ADMIN ONLY"""
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    
    import os
    
    # Set the database URL directly
    os.environ['DATABASE_URL'] = "postgresql://vouchlink_ai_user:G0cKKzLekD8EYygLMkymwoKlU3wdBqhk@dpg-d2f3ne2li9vc73bf5gg0-a.oregon-postgres.render.com/VouchLink-AIVouchLink AI"
    
    try:
        from .mt_db import get_db
        
        conn = get_db()
        
        # Check if we got a PostgreSQL connection by testing a PostgreSQL-specific command
        cursor = conn.cursor()
        
        # Test PostgreSQL connection
        try:
            cursor.execute("SELECT current_database()")
            db_name = cursor.fetchone()
            if not db_name or db_name[0] != 'VouchLink AI':
                raise Exception(f"Connected to wrong database: {db_name}")
        except Exception as e:
            if "no such function" in str(e):
                raise Exception("Connected to SQLite instead of PostgreSQL - psycopg2 not available")
            raise e
        
        # Check if constraint exists using information_schema (more reliable)
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.table_constraints
            WHERE constraint_name = 'job_idempotency_tenant_id_idempotency_key_key'
              AND table_name = 'job_idempotency'
        """)
        
        constraint_count = cursor.fetchone()
        if constraint_count and constraint_count[0] > 0:
            return {"status": "success", "message": "Constraint already exists"}
        
        # Remove duplicates first
        cursor.execute("""
            DELETE FROM job_idempotency a
            USING job_idempotency b
            WHERE a.ctid < b.ctid
              AND a.tenant_id = b.tenant_id
              AND a.idempotency_key = b.idempotency_key
        """)
        
        # Add constraint
        cursor.execute("""
            ALTER TABLE job_idempotency 
            ADD CONSTRAINT job_idempotency_tenant_id_idempotency_key_key 
            UNIQUE (tenant_id, idempotency_key)
        """)
        
        # Add indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_idempotency_tenant_key 
            ON job_idempotency (tenant_id, idempotency_key)
        """)
        
        conn.commit()
        
        return {
            "status": "success", 
            "message": "Migration completed successfully. Added unique constraint and indexes."
        }
        
    except Exception as e:
        error_msg = str(e)
        if 'conn' in locals():
            conn.rollback()
        
        # Provide helpful error messages
        if "psycopg2" in error_msg or "PostgreSQL driver not available" in error_msg:
            return {
                "status": "error",
                "message": "PostgreSQL driver not available in production. Please run this SQL manually in Render console: ALTER TABLE job_idempotency ADD CONSTRAINT job_idempotency_tenant_id_idempotency_key_key UNIQUE (tenant_id, idempotency_key);",
                "sql_command": "ALTER TABLE job_idempotency ADD CONSTRAINT job_idempotency_tenant_id_idempotency_key_key UNIQUE (tenant_id, idempotency_key);"
            }
        else:
            raise HTTPException(500, f"Migration failed: {error_msg}")
        
    finally:
        if 'conn' in locals():
            conn.close()