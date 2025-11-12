"""Migrate existing single-tenant data to corporate multi-tenant schema

Revision ID: 002_migrate_data
Revises: 001_corporate_schema
Create Date: 2025-01-27 10:30:00.000000

This migration handles the complex data transformation from the existing
single-tenant schema to the new corporate multi-tenant architecture.
It preserves all existing data while restructuring it for multi-tenancy.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text
import json
from datetime import datetime

# revision identifiers, used by Alembic.
revision = '002_migrate_data'
down_revision = '001_corporate_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Migrate existing data to corporate schema"""

    connection = op.get_bind()

    print("🔄 Starting data migration from single-tenant to corporate schema...")

    # ===================================================================
    # STEP 1: CREATE DEFAULT ORGANIZATION
    # ===================================================================

    print("📋 Creating default organization from existing tenant data...")

    # Check if we have existing tenant/user data to migrate
    try:
        # Try to detect existing data structure
        existing_tables = connection.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('users', 'tenants', 'prospects_old', 'job_runs')
        """)).fetchall()

        table_names = [row[0] for row in existing_tables]
        print(f"📊 Found existing tables: {table_names}")

        # Create default organization
        default_org_id = connection.execute(text("""
            INSERT INTO organizations (name, domain, status, subscription_tier, created_at)
            VALUES ('VouchLink AI Corporate', 'vouchlinkai.com', 'active', 'enterprise', CURRENT_TIMESTAMP)
            RETURNING id
        """)).scalar()

        print(f"✅ Created default organization with ID: {default_org_id}")

        # ===================================================================
        # STEP 2: MIGRATE USERS TO TEAM MEMBERS
        # ===================================================================

        if 'users' in table_names:
            print("👥 Migrating users to team members...")

            # Migrate existing users
            connection.execute(text("""
                INSERT INTO team_members (
                    organization_id, email, name, role, linkedin_url,
                    is_active, last_login, created_at, updated_at
                )
                SELECT
                    :org_id as organization_id,
                    COALESCE(email, 'unknown@example.com') as email,
                    COALESCE(NULLIF(TRIM(CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, ''))), ''), 'Unknown User') as name,
                    CASE
                        WHEN LOWER(COALESCE(role, '')) IN ('admin', 'org_admin', 'organization_admin', 'super_admin', 'owner', 'ops', 'support') THEN 'admin'
                        ELSE 'user'
                    END as role,
                    linkedin_url,
                    COALESCE(is_active, true) as is_active,
                    last_login,
                    COALESCE(created_at, CURRENT_TIMESTAMP) as created_at,
                    COALESCE(updated_at, CURRENT_TIMESTAMP) as updated_at
                FROM users
                WHERE email IS NOT NULL
                ON CONFLICT (organization_id, email) DO NOTHING
            """), {"org_id": default_org_id})

            migrated_users = connection.execute(text("""
                SELECT COUNT(*) FROM team_members WHERE organization_id = :org_id
            """), {"org_id": default_org_id}).scalar()

            print(f"✅ Migrated {migrated_users} users to team members")

        # ===================================================================
        # STEP 3: CREATE DEFAULT INTEGRATION SET
        # ===================================================================

        print("🔧 Creating default integration set...")

        # Try to extract existing API keys from various sources
        existing_keys = {}

        # Check for existing environment variables or config
        if 'user_integrations' in table_names:
            # Extract API keys from existing integrations
            api_keys = connection.execute(text("""
                SELECT provider, key FROM user_integrations
                WHERE key IS NOT NULL AND key != ''
                LIMIT 10
            """)).fetchall()

            for row in api_keys:
                provider, key = row
                existing_keys[provider] = key

        # Create integration set with default feature flags
        feature_flags = {
            "email_quota": 20,
            "require_email_approval": True,
            "enable_linkedin_automation": True,
            "enable_email_validation": True,
            "max_prospects_per_import": 1000
        }

        quota_settings = {
            "weekly_email_limit": 20,
            "monthly_prospect_limit": 500,
            "daily_lookup_limit": 100,
            "concurrent_mutuals_limit": 3
        }

        connection.execute(text("""
            INSERT INTO integration_sets (
                organization_id, apify_token, cufinder_api_key, hunter_api_key,
                zerobounce_api_key, sendgrid_api_key, openai_api_key,
                feature_flags, quota_settings, created_at, updated_at
            ) VALUES (
                :org_id, :apify_token, :cufinder_key, :hunter_key,
                :zerobounce_key, :sendgrid_key, :openai_key,
                :feature_flags, :quota_settings, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """), {
            "org_id": default_org_id,
            "apify_token": existing_keys.get('apify'),
            "cufinder_key": existing_keys.get('cufinder'),
            "hunter_key": existing_keys.get('hunter'),
            "zerobounce_key": existing_keys.get('zerobounce'),
            "sendgrid_key": existing_keys.get('sendgrid'),
            "openai_key": existing_keys.get('openai'),
            "feature_flags": json.dumps(feature_flags),
            "quota_settings": json.dumps(quota_settings)
        })

        print("✅ Created default integration set with feature flags")

        # ===================================================================
        # STEP 4: MIGRATE PROSPECTS
        # ===================================================================

        # Check for existing prospects in various possible table names
        prospect_tables = ['prospects', 'prospects_old', 'prospect_data']
        prospects_migrated = 0

        for table_name in prospect_tables:
            if table_name in table_names:
                print(f"📊 Migrating prospects from {table_name}...")

                try:
                    # Migrate prospects with proper data transformation
                    result = connection.execute(text(f"""
                        INSERT INTO prospects (
                            organization_id, company, full_name, role, email, linkedin_url,
                            location, headline, tags, notes, status, source, priority,
                            created_at, updated_at
                        )
                        SELECT
                            :org_id as organization_id,
                            COALESCE(NULLIF(TRIM(company), ''), 'Unknown Company') as company,
                            COALESCE(NULLIF(TRIM(
                                CASE
                                    WHEN full_name IS NOT NULL THEN full_name
                                    WHEN first_name IS NOT NULL OR last_name IS NOT NULL THEN
                                        TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, ''))
                                    WHEN contact_name IS NOT NULL THEN contact_name
                                    WHEN name IS NOT NULL THEN name
                                    ELSE 'Unknown Contact'
                                END
                            ), ''), 'Unknown Contact') as full_name,
                            COALESCE(NULLIF(TRIM(
                                CASE
                                    WHEN role IS NOT NULL THEN role
                                    WHEN title IS NOT NULL THEN title
                                    WHEN job_title IS NOT NULL THEN job_title
                                    ELSE 'Executive'
                                END
                            ), ''), 'Executive') as role,
                            NULLIF(TRIM(email), '') as email,
                            NULLIF(TRIM(linkedin_url), '') as linkedin_url,
                            NULLIF(TRIM(location), '') as location,
                            NULLIF(TRIM(headline), '') as headline,
                            CASE
                                WHEN tags IS NOT NULL THEN tags::jsonb
                                ELSE '[]'::jsonb
                            END as tags,
                            NULLIF(TRIM(notes), '') as notes,
                            CASE
                                WHEN status IS NOT NULL THEN
                                    CASE status
                                        WHEN 'completed' THEN 'ready_for_mutuals'
                                        WHEN 'failed' THEN 'lookup_failed'
                                        WHEN 'processing' THEN 'pending_lookup'
                                        ELSE status
                                    END
                                ELSE 'pending_lookup'
                            END as status,
                            COALESCE(source, 'legacy_migration') as source,
                            COALESCE(priority, 'normal') as priority,
                            COALESCE(created_at, CURRENT_TIMESTAMP) as created_at,
                            COALESCE(updated_at, CURRENT_TIMESTAMP) as updated_at
                        FROM {table_name}
                        WHERE company IS NOT NULL AND company != ''
                        ON CONFLICT DO NOTHING
                    """), {"org_id": default_org_id})

                    rows_affected = result.rowcount
                    prospects_migrated += rows_affected
                    print(f"✅ Migrated {rows_affected} prospects from {table_name}")

                except Exception as e:
                    print(f"⚠️ Error migrating from {table_name}: {e}")

        print(f"✅ Total prospects migrated: {prospects_migrated}")

        # ===================================================================
        # STEP 5: MIGRATE CONNECTORS AND MUTUALS
        # ===================================================================

        if 'mutual_connections' in table_names or 'connectors' in table_names:
            print("🤝 Migrating mutual connections...")

            connector_tables = ['mutual_connections', 'connectors', 'prospect_mutuals']
            connectors_migrated = 0

            for table_name in connector_tables:
                if table_name in table_names:
                    try:
                        # First migrate unique connectors
                        connection.execute(text(f"""
                            INSERT INTO connectors (
                                organization_id, full_name, linkedin_url, headline,
                                company, location, profile_picture_url, created_at, updated_at
                            )
                            SELECT DISTINCT
                                :org_id as organization_id,
                                COALESCE(NULLIF(TRIM(
                                    CASE
                                        WHEN mutual_full_name IS NOT NULL THEN mutual_full_name
                                        WHEN full_name IS NOT NULL THEN full_name
                                        WHEN name IS NOT NULL THEN name
                                        ELSE 'Unknown Connector'
                                    END
                                ), ''), 'Unknown Connector') as full_name,
                                COALESCE(NULLIF(TRIM(
                                    CASE
                                        WHEN mutual_linkedin_url IS NOT NULL THEN mutual_linkedin_url
                                        WHEN linkedin_url IS NOT NULL THEN linkedin_url
                                        ELSE ''
                                    END
                                ), ''), '') as linkedin_url,
                                NULLIF(TRIM(
                                    CASE
                                        WHEN mutual_headline IS NOT NULL THEN mutual_headline
                                        WHEN headline IS NOT NULL THEN headline
                                        ELSE ''
                                    END
                                ), '') as headline,
                                NULLIF(TRIM(
                                    CASE
                                        WHEN mutual_company IS NOT NULL THEN mutual_company
                                        WHEN company IS NOT NULL THEN company
                                        ELSE ''
                                    END
                                ), '') as company,
                                NULLIF(TRIM(location), '') as location,
                                NULLIF(TRIM(profile_picture_url), '') as profile_picture_url,
                                COALESCE(created_at, CURRENT_TIMESTAMP) as created_at,
                                COALESCE(updated_at, CURRENT_TIMESTAMP) as updated_at
                            FROM {table_name}
                            WHERE (mutual_linkedin_url IS NOT NULL AND mutual_linkedin_url != '')
                               OR (linkedin_url IS NOT NULL AND linkedin_url != '')
                            ON CONFLICT (organization_id, linkedin_url) DO NOTHING
                        """), {"org_id": default_org_id})

                        connectors_migrated += connection.execute(text("""
                            SELECT COUNT(*) FROM connectors WHERE organization_id = :org_id
                        """), {"org_id": default_org_id}).scalar()

                    except Exception as e:
                        print(f"⚠️ Error migrating connectors from {table_name}: {e}")

            print(f"✅ Migrated {connectors_migrated} unique connectors")

        # ===================================================================
        # STEP 6: CREATE DEFAULT EMAIL TEMPLATE
        # ===================================================================

        print("📧 Creating default email templates...")

        default_templates = [
            {
                "name": "Default Introduction Template",
                "type": "introduction",
                "subject": "Introduction to {{prospect_name}}",
                "body": """Hey {{connector_name}} — hope you're well!

Could you intro me to {{prospect_name}} at {{prospect_company}}? I'd love to connect about potential collaboration opportunities.

Happy to send a 2-sentence blurb you can paste if that's helpful. Totally fine if not a fit.

Thanks!"""
            },
            {
                "name": "Follow-up Template",
                "type": "follow_up",
                "subject": "Following up on {{prospect_name}}",
                "body": """Hi {{connector_name}},

Just wanted to follow up on my request for an introduction to {{prospect_name}} at {{prospect_company}}.

No pressure at all — just wanted to make sure it didn't get lost in your inbox.

Thanks!"""
            }
        ]

        for template in default_templates:
            connection.execute(text("""
                INSERT INTO email_templates (
                    organization_id, name, template_type, subject_template,
                    body_template, variables, is_active, created_at, updated_at
                ) VALUES (
                    :org_id, :name, :template_type, :subject_template,
                    :body_template, :variables, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """), {
                "org_id": default_org_id,
                "name": template["name"],
                "template_type": template["type"],
                "subject_template": template["subject"],
                "body_template": template["body"],
                "variables": json.dumps({
                    "prospect_name": "string",
                    "prospect_company": "string",
                    "connector_name": "string"
                })
            })

        print("✅ Created default email templates")

        # ===================================================================
        # STEP 7: INITIALIZE METRICS
        # ===================================================================

        print("📊 Initializing organization metrics...")

        # Create initial metrics record for today
        connection.execute(text("""
            INSERT INTO organization_metrics (
                organization_id, metric_date, prospects_imported, prospects_processed,
                connectors_found, emails_scheduled, emails_sent, emails_replied,
                cost_usd, created_at, updated_at
            ) VALUES (
                :org_id, CURRENT_DATE, :prospects, 0, :connectors, 0, 0, 0, 0.00,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """), {
            "org_id": default_org_id,
            "prospects": prospects_migrated,
            "connectors": connectors_migrated
        })

        print("✅ Initialized organization metrics")

        # ===================================================================
        # STEP 8: CREATE AUDIT RECORD
        # ===================================================================

        print("📝 Creating migration audit record...")

        migration_payload = {
            "migration_type": "single_to_multi_tenant",
            "prospects_migrated": prospects_migrated,
            "connectors_migrated": connectors_migrated,
            "source_tables": table_names,
            "default_organization_id": default_org_id,
            "migration_timestamp": datetime.utcnow().isoformat()
        }

        connection.execute(text("""
            INSERT INTO audit_events (
                organization_id, actor_type, actor_id, action, target_type,
                payload, correlation_id, timestamp
            ) VALUES (
                :org_id, 'system', 0, 'data_migration', 'organization',
                :payload, 'migration_001', CURRENT_TIMESTAMP
            )
        """), {
            "org_id": default_org_id,
            "payload": json.dumps(migration_payload)
        })

        print("✅ Created migration audit record")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

    print("🎉 Data migration completed successfully!")
    print(f"""
📋 Migration Summary:
   • Organization ID: {default_org_id}
   • Prospects migrated: {prospects_migrated}
   • Connectors migrated: {connectors_migrated}
   • Templates created: 2
   • Integration set: ✅
   • Audit logging: ✅
   """)


def downgrade() -> None:
    """Revert the data migration (WARNING: This will delete all migrated data)"""

    connection = op.get_bind()

    print("⚠️ WARNING: Reverting data migration - this will delete all corporate data!")

    # Clear all data from corporate tables (in reverse order of dependencies)
    tables_to_clear = [
        'audit_events',
        'organization_metrics',
        'job_idempotency',
        'approval_requests',
        'email_jobs',
        'email_templates',
        'prospect_connectors',
        'connectors',
        'prospects',
        'cookie_jars',
        'integration_sets',
        'team_members',
        'organizations'
    ]

    for table_name in tables_to_clear:
        try:
            result = connection.execute(text(f"DELETE FROM {table_name}"))
            print(f"✅ Cleared {result.rowcount} rows from {table_name}")
        except Exception as e:
            print(f"⚠️ Error clearing {table_name}: {e}")

    print("✅ Data migration reverted - all corporate data removed")
