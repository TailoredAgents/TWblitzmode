"""
Email System Database Migrations
Production-ready schema changes for email automation
"""

import logging
from typing import Optional
from api.mt_db import get_db

logger = logging.getLogger(__name__)

def run_email_migrations(database_url: Optional[str] = None):
    """Execute all email-related database migrations"""
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Check if migrations have already been run
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_name = 'contacts' AND column_name = 'email'
        """)
        
        if cursor.fetchone()[0] > 0:
            logger.info("Email migrations already applied")
            return
        
        logger.info("Running email system migrations...")
        
        # 1. Add email fields to contacts table
        cursor.execute("""
            ALTER TABLE contacts 
            ADD COLUMN IF NOT EXISTS email VARCHAR(255),
            ADD COLUMN IF NOT EXISTS email_confidence FLOAT DEFAULT 0.0 
                CHECK (email_confidence >= 0 AND email_confidence <= 1),
            ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS email_source VARCHAR(50),
            ADD COLUMN IF NOT EXISTS email_last_verified TIMESTAMP
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
            CREATE INDEX IF NOT EXISTS idx_contacts_email_confidence ON contacts(email_confidence);
        """)
        
        # 2. Enhance outreach_queue for email support
        cursor.execute("""
            ALTER TABLE outreach_queue 
            ADD COLUMN IF NOT EXISTS subject VARCHAR(255),
            ADD COLUMN IF NOT EXISTS channel VARCHAR(20) DEFAULT 'linkedin' 
                CHECK (channel IN ('linkedin', 'email')),
            ADD COLUMN IF NOT EXISTS email_status VARCHAR(50),
            ADD COLUMN IF NOT EXISTS send_priority INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS campaign_id INTEGER
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_outreach_channel_status 
            ON outreach_queue(channel, status);
        """)
        
        # 3. Create email_metrics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_metrics (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER NOT NULL,
                tenant_id INTEGER NOT NULL,
                sent_count INTEGER DEFAULT 0,
                bounce_count INTEGER DEFAULT 0,
                open_count INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                click_count INTEGER DEFAULT 0,
                last_sent TIMESTAMP,
                suppressed BOOLEAN DEFAULT FALSE,
                suppression_reason VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_email_metrics_tenant_contact 
            ON email_metrics(tenant_id, contact_id);
            
            CREATE INDEX IF NOT EXISTS idx_email_metrics_suppressed
            ON email_metrics(suppressed);
        """)
        
        # 4. Create tenant_email_settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenant_email_settings (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL UNIQUE,
                from_email VARCHAR(255),
                from_name VARCHAR(255),
                reply_to_email VARCHAR(255),
                sendgrid_api_key_encrypted TEXT,
                cufinder_api_key_encrypted TEXT,
                domain_verified BOOLEAN DEFAULT FALSE,
                spf_verified BOOLEAN DEFAULT FALSE,
                dkim_verified BOOLEAN DEFAULT FALSE,
                dmarc_verified BOOLEAN DEFAULT FALSE,
                warmup_status VARCHAR(50) DEFAULT 'not_started',
                warmup_started_at TIMESTAMP,
                daily_limit INTEGER DEFAULT 20,
                current_reputation_score FLOAT DEFAULT 50.0,
                total_sent INTEGER DEFAULT 0,
                total_bounced INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
            )
        """)
        
        # 5. Create email_campaigns table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_campaigns (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                prospect_id INTEGER NOT NULL,
                name VARCHAR(255),
                status VARCHAR(50) DEFAULT 'draft' 
                    CHECK (status IN ('draft', 'scheduled', 'sending', 'sent', 'paused', 'cancelled')),
                message_type VARCHAR(50) DEFAULT 'warm_intro',
                total_recipients INTEGER DEFAULT 0,
                sent_count INTEGER DEFAULT 0,
                open_count INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                bounce_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                scheduled_for TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (prospect_id) REFERENCES prospects(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_campaigns_tenant_status 
            ON email_campaigns(tenant_id, status);
            
            CREATE INDEX IF NOT EXISTS idx_campaigns_scheduled
            ON email_campaigns(scheduled_for) WHERE scheduled_for IS NOT NULL;
        """)
        
        # 6. Create email_templates table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_templates (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                type VARCHAR(50) DEFAULT 'warm_intro',
                subject_template TEXT,
                body_template TEXT,
                variables JSONB,
                is_active BOOLEAN DEFAULT TRUE,
                usage_count INTEGER DEFAULT 0,
                success_rate FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
            )
        """)
        
        # 7. Create email_webhook_events table for SendGrid webhooks
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_webhook_events (
                id SERIAL PRIMARY KEY,
                event_id VARCHAR(255) UNIQUE,
                message_id VARCHAR(255),
                tenant_id INTEGER,
                email VARCHAR(255),
                event_type VARCHAR(50),
                timestamp TIMESTAMP,
                payload JSONB,
                processed BOOLEAN DEFAULT FALSE,
                processed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_webhook_events_message (message_id),
                INDEX idx_webhook_events_processed (processed, created_at)
            )
        """)
        
        # 8. Create email_suppression_list table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_suppression_list (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                email VARCHAR(255) NOT NULL,
                reason VARCHAR(255),
                type VARCHAR(50) DEFAULT 'manual' 
                    CHECK (type IN ('manual', 'bounce', 'complaint', 'unsubscribe')),
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                UNIQUE KEY unique_tenant_email (tenant_id, email)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_suppression_email 
            ON email_suppression_list(email);
            
            CREATE INDEX IF NOT EXISTS idx_suppression_tenant
            ON email_suppression_list(tenant_id);
        """)
        
        # 9. Create email_ab_tests table for A/B testing
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_ab_tests (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                campaign_id INTEGER NOT NULL,
                variant_name VARCHAR(50),
                subject VARCHAR(255),
                body TEXT,
                sent_count INTEGER DEFAULT 0,
                open_count INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                winner BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                FOREIGN KEY (campaign_id) REFERENCES email_campaigns(id) ON DELETE CASCADE
            )
        """)
        
        # 10. Create email_costs table for tracking expenses
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_costs (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                date DATE NOT NULL,
                service VARCHAR(50) NOT NULL,
                operation VARCHAR(50),
                count INTEGER DEFAULT 0,
                unit_cost DECIMAL(10, 6),
                total_cost DECIMAL(10, 4),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                UNIQUE KEY unique_tenant_date_service (tenant_id, date, service, operation)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_costs_tenant_date
            ON email_costs(tenant_id, date);
        """)
        
        # Create LinkedIn campaign tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS linkedin_campaigns (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                prospect_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                message_type VARCHAR(50) DEFAULT 'direct_introduction',
                status VARCHAR(50) DEFAULT 'draft',
                phantom_container_id VARCHAR(255),
                phantom_id VARCHAR(255),
                delay_between_messages INTEGER DEFAULT 180,
                send_connection_requests BOOLEAN DEFAULT FALSE,
                scheduled_for TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                total_recipients INTEGER DEFAULT 0,
                messages_sent INTEGER DEFAULT 0,
                messages_failed INTEGER DEFAULT 0,
                total_cost DECIMAL(10, 2) DEFAULT 0.00,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                FOREIGN KEY (prospect_id) REFERENCES prospects(id) ON DELETE CASCADE
            )
        """)
        
        create_index_if_not_exists(cursor, "idx_linkedin_campaigns_tenant", "linkedin_campaigns", "tenant_id")
        create_index_if_not_exists(cursor, "idx_linkedin_campaigns_prospect", "linkedin_campaigns", "prospect_id")
        create_index_if_not_exists(cursor, "idx_linkedin_campaigns_status", "linkedin_campaigns", "status")
        create_index_if_not_exists(cursor, "idx_linkedin_campaigns_phantom", "linkedin_campaigns", "phantom_container_id")
        
        # Create LinkedIn campaign messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS linkedin_campaign_messages (
                id SERIAL PRIMARY KEY,
                campaign_id INTEGER NOT NULL,
                introducer_id INTEGER NOT NULL,
                linkedin_url VARCHAR(500),
                message_content TEXT NOT NULL,
                personalization_data JSONB,
                status VARCHAR(50) DEFAULT 'pending',
                sent_at TIMESTAMP,
                error_message TEXT,
                phantom_output JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (campaign_id) REFERENCES linkedin_campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (introducer_id) REFERENCES contacts(id) ON DELETE CASCADE
            )
        """)
        
        create_index_if_not_exists(cursor, "idx_linkedin_messages_campaign", "linkedin_campaign_messages", "campaign_id")
        create_index_if_not_exists(cursor, "idx_linkedin_messages_introducer", "linkedin_campaign_messages", "introducer_id")
        create_index_if_not_exists(cursor, "idx_linkedin_messages_status", "linkedin_campaign_messages", "status")
        
        # Create LinkedIn metrics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS linkedin_metrics (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                campaign_id INTEGER,
                message_id INTEGER,
                event_type VARCHAR(50) NOT NULL,
                linkedin_url VARCHAR(500),
                recipient_name VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cost DECIMAL(10, 4) DEFAULT 0.00,
                metadata JSONB,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                FOREIGN KEY (campaign_id) REFERENCES linkedin_campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES linkedin_campaign_messages(id) ON DELETE CASCADE
            )
        """)
        
        create_index_if_not_exists(cursor, "idx_linkedin_metrics_tenant", "linkedin_metrics", "tenant_id")
        create_index_if_not_exists(cursor, "idx_linkedin_metrics_campaign", "linkedin_metrics", "campaign_id")
        create_index_if_not_exists(cursor, "idx_linkedin_metrics_event", "linkedin_metrics", "event_type")
        create_index_if_not_exists(cursor, "idx_linkedin_metrics_date", "linkedin_metrics", "created_at")
        
        # Create LinkedIn daily usage tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS linkedin_daily_usage (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                usage_date DATE NOT NULL,
                messages_sent INTEGER DEFAULT 0,
                messages_failed INTEGER DEFAULT 0,
                total_cost DECIMAL(10, 2) DEFAULT 0.00,
                phantom_executions INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                UNIQUE(tenant_id, usage_date)
            )
        """)
        
        create_index_if_not_exists(cursor, "idx_linkedin_usage_tenant_date", "linkedin_daily_usage", "tenant_id, usage_date")
        
        conn.commit()
        logger.info("Email and LinkedIn migrations completed successfully")
        
    except Exception as e:
        logger.error(f"Email migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def rollback_email_migrations():
    """Rollback email migrations if needed"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Drop tables in reverse order due to foreign keys
        tables_to_drop = [
            'linkedin_daily_usage',
            'linkedin_metrics',
            'linkedin_campaign_messages',
            'linkedin_campaigns',
            'email_costs',
            'email_ab_tests',
            'email_suppression_list',
            'email_webhook_events',
            'email_templates',
            'email_campaigns',
            'tenant_email_settings',
            'email_metrics'
        ]
        
        for table in tables_to_drop:
            cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        
        # Remove columns from existing tables
        cursor.execute("""
            ALTER TABLE contacts 
            DROP COLUMN IF EXISTS email,
            DROP COLUMN IF EXISTS email_confidence,
            DROP COLUMN IF EXISTS email_verified,
            DROP COLUMN IF EXISTS email_source,
            DROP COLUMN IF EXISTS email_last_verified
        """)
        
        cursor.execute("""
            ALTER TABLE outreach_queue
            DROP COLUMN IF EXISTS subject,
            DROP COLUMN IF EXISTS channel,
            DROP COLUMN IF EXISTS email_status,
            DROP COLUMN IF EXISTS send_priority,
            DROP COLUMN IF EXISTS campaign_id
        """)
        
        conn.commit()
        logger.info("Email migrations rolled back successfully")
        
    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    # Run migrations when executed directly
    run_email_migrations()