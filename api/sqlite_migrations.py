"""
SQLite-specific migration runner for local development
"""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

def run_sqlite_migrations(db_path: str = "data/multi_tenant.db"):
    """Run SQLite-specific migrations to ensure schema is up to date"""
    
    # Ensure data directory exists
    Path("data").mkdir(exist_ok=True)
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        cursor = conn.cursor()
        
        logger.info(f"Running SQLite migrations on: {db_path}")
        
        # 1. Create daily_quotas table if missing
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_quotas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    daily_limit INTEGER NOT NULL DEFAULT 25,
                    items_processed INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (tenant_id, date)
                )
            """)
            logger.info("✓ daily_quotas table ensured")
        except Exception as e:
            logger.warning(f"daily_quotas table warning: {e}")
        
        # 2. Add missing columns to existing tables
        try:
            # Add items_processed to daily_quotas if it exists but column is missing
            cursor.execute("PRAGMA table_info(daily_quotas)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'items_processed' not in columns:
                cursor.execute("ALTER TABLE daily_quotas ADD COLUMN items_processed INTEGER NOT NULL DEFAULT 0")
                logger.info("✓ Added items_processed column to daily_quotas")
        except Exception as e:
            logger.warning(f"items_processed column warning: {e}")
        
        # 3. Create unique index for outreach_queue to prevent duplicates
        try:
            # First check if outreach_queue table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='outreach_queue'")
            if cursor.fetchone():
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_queue_tenant_prospect_connector
                    ON outreach_queue (tenant_id, prospect_id, LOWER(connector_linkedin))
                    WHERE connector_linkedin IS NOT NULL
                """)
                logger.info("✓ Unique constraint on outreach_queue (tenant_id, prospect_id, connector_linkedin) ensured")
            else:
                logger.warning("outreach_queue table does not exist - skipping constraint")
        except Exception as e:
            logger.warning(f"outreach_queue unique constraint warning: {e}")
        
        # 4. Ensure job_idempotency has proper unique constraint
        try:
            # First check if job_idempotency table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_idempotency'")
            if cursor.fetchone():
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_job_idempotency_tenant_key
                    ON job_idempotency (tenant_id, idempotency_key)
                """)
                logger.info("✓ Unique constraint on job_idempotency (tenant_id, idempotency_key) ensured")
            else:
                logger.warning("job_idempotency table does not exist - skipping constraint")
        except Exception as e:
            logger.warning(f"job_idempotency unique constraint warning: {e}")
        
        # 5. Add status columns to prospect_mutuals if missing
        try:
            cursor.execute("PRAGMA table_info(prospect_mutuals)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'status' not in columns:
                cursor.execute("ALTER TABLE prospect_mutuals ADD COLUMN status TEXT DEFAULT 'new' CHECK (status IN ('new','queued','contacted','failed'))")
                logger.info("✓ Added status column to prospect_mutuals")
                
            if 'last_action_at' not in columns:
                cursor.execute("ALTER TABLE prospect_mutuals ADD COLUMN last_action_at TIMESTAMP")
                logger.info("✓ Added last_action_at column to prospect_mutuals")
                
            if 'introduction_id' not in columns:
                cursor.execute("ALTER TABLE prospect_mutuals ADD COLUMN introduction_id INTEGER")
                logger.info("✓ Added introduction_id column to prospect_mutuals")
                
        except Exception as e:
            logger.warning(f"prospect_mutuals columns warning: {e}")
        
        # 6. Create indexes for performance
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_quotas_tenant_date ON daily_quotas (tenant_id, date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_outreach_queue_status ON outreach_queue (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prospect_mutuals_status ON prospect_mutuals (status)")
            logger.info("✓ Performance indexes ensured")
        except Exception as e:
            logger.warning(f"Performance indexes warning: {e}")
        
        conn.commit()
        conn.close()
        
        logger.info("✅ SQLite migrations completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"SQLite migration failed: {e}")
        return False

if __name__ == "__main__":
    # Run migrations when script is executed directly
    run_sqlite_migrations()