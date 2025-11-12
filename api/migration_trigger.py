#!/usr/bin/env python3
"""
Simple migration trigger that can be run via HTTP endpoint
"""
import os
import traceback

# Set database URL
os.environ['DATABASE_URL'] = "postgresql://vouchlink_ai_user:G0cKKzLekD8EYygLMkymwoKlU3wdBqhk@dpg-d2f3ne2li9vc73bf5gg0-a.oregon-postgres.render.com/VouchLink-AIVouchLink AI"

def run_migration():
    """Run the database migration with error handling"""
    try:
        print("🔧 Starting database migration...")
        
        # Import here to ensure DATABASE_URL is set
        from api.mt_db import get_db
        
        conn = get_db()
        cursor = conn.cursor()
        
        print("✅ Connected to database")
        
        # First check if we're actually connected to PostgreSQL
        cursor.execute("SELECT version()")
        version = cursor.fetchone()
        print(f"📊 Database version: {version[0] if version else 'Unknown'}")
        
        if 'PostgreSQL' not in str(version[0]) if version else True:
            raise Exception("Not connected to PostgreSQL - migration cannot proceed")
        
        # Check if constraint already exists
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.table_constraints
            WHERE constraint_name = 'job_idempotency_tenant_id_idempotency_key_key'
            AND table_name = 'job_idempotency'
        """)
        
        result = cursor.fetchone()
        constraint_exists = result and result[0] > 0
        
        if constraint_exists:
            print("✅ Constraint already exists - migration not needed")
            return {"status": "success", "message": "Constraint already exists"}
        
        print("📋 Adding unique constraint...")
        
        # Add the constraint
        cursor.execute("""
            ALTER TABLE job_idempotency 
            ADD CONSTRAINT job_idempotency_tenant_id_idempotency_key_key 
            UNIQUE (tenant_id, idempotency_key)
        """)
        
        # Add performance indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_idempotency_tenant_key 
            ON job_idempotency (tenant_id, idempotency_key)
        """)
        
        conn.commit()
        
        print("🎉 Migration completed successfully!")
        return {"status": "success", "message": "Migration completed successfully"}
        
    except Exception as e:
        error_msg = str(e)
        stack_trace = traceback.format_exc()
        print(f"❌ Migration failed: {error_msg}")
        print(f"📋 Stack trace: {stack_trace}")
        
        if 'conn' in locals():
            conn.rollback()
            
        return {"status": "error", "message": error_msg, "trace": stack_trace}
        
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    result = run_migration()
    print(f"Final result: {result}")