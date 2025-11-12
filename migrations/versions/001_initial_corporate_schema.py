"""Initial corporate multi-tenant schema migration

Revision ID: 001_corporate_schema
Revises:
Create Date: 2025-01-27 10:00:00.000000

This migration creates the complete corporate multi-tenant schema for VouchLink AI,
transitioning from the current single-tenant structure to enterprise-grade
multi-tenant architecture with proper isolation and security.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_corporate_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the complete corporate multi-tenant schema"""

    # ===================================================================
    # ORGANIZATIONS AND TENANCY
    # ===================================================================

    # Organizations table (replaces tenants)
    op.create_table('organizations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('domain', sa.String(255), nullable=True, unique=True),
        sa.Column('industry', sa.String(100), nullable=True),
        sa.Column('size', sa.String(50), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='active'),
        sa.Column('subscription_tier', sa.String(50), nullable=False, default='starter'),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('metadata', postgresql.JSONB(), nullable=True)
    )

    # Team members table (replaces users)
    op.create_table('team_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, default='contributor'),
        sa.Column('linkedin_url', sa.String(500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('last_login', sa.TIMESTAMP(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'email', name='uq_team_members_org_email')
    )

    # ===================================================================
    # INTEGRATION AND AUTHENTICATION
    # ===================================================================

    # Integration sets table (organization-level integrations)
    op.create_table('integration_sets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('apify_token', sa.Text(), nullable=True),  # Encrypted
        sa.Column('apify_actor_id', sa.String(255), nullable=True),
        sa.Column('cufinder_api_key', sa.Text(), nullable=True),  # Encrypted
        sa.Column('hunter_api_key', sa.Text(), nullable=True),  # Encrypted
        sa.Column('zerobounce_api_key', sa.Text(), nullable=True),  # Encrypted
        sa.Column('sendgrid_api_key', sa.Text(), nullable=True),  # Encrypted
        sa.Column('openai_api_key', sa.Text(), nullable=True),  # Encrypted
        sa.Column('feature_flags', postgresql.JSONB(), nullable=True),
        sa.Column('quota_settings', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', name='uq_integration_sets_org')
    )

    # Cookie jars table (encrypted LinkedIn session storage)
    op.create_table('cookie_jars',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('team_member_id', sa.Integer(), nullable=False),
        sa.Column('encrypted_cookies', sa.Text(), nullable=False),  # AES-256-GCM encrypted
        sa.Column('encryption_key_id', sa.String(255), nullable=False),  # KMS key reference
        sa.Column('checksum', sa.String(64), nullable=False),  # SHA-256 checksum
        sa.Column('status', sa.String(50), nullable=False, default='active'),
        sa.Column('expires_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_member_id'], ['team_members.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'team_member_id', name='uq_cookie_jars_org_member')
    )

    # ===================================================================
    # PROSPECTS AND EXECUTIVE DATA
    # ===================================================================

    # Prospects table (enhanced)
    op.create_table('prospects',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('company', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('role', sa.String(255), nullable=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('linkedin_url', sa.String(500), nullable=True),
        sa.Column('location', sa.String(255), nullable=True),
        sa.Column('headline', sa.Text(), nullable=True),
        sa.Column('about', sa.Text(), nullable=True),
        sa.Column('company_size', sa.String(50), nullable=True),
        sa.Column('industry', sa.String(100), nullable=True),
        sa.Column('tags', postgresql.JSONB(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='pending_lookup'),
        sa.Column('source', sa.String(100), nullable=False, default='manual'),
        sa.Column('priority', sa.String(20), nullable=False, default='normal'),
        sa.Column('processed_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.Index('idx_prospects_org_status', 'organization_id', 'status'),
        sa.Index('idx_prospects_company', 'company'),
        sa.Index('idx_prospects_created_at', 'created_at')
    )

    # Connectors table (mutual connections)
    op.create_table('connectors',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('linkedin_url', sa.String(500), nullable=False),
        sa.Column('headline', sa.Text(), nullable=True),
        sa.Column('company', sa.String(255), nullable=True),
        sa.Column('location', sa.String(255), nullable=True),
        sa.Column('profile_picture_url', sa.String(500), nullable=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('email_status', sa.String(50), nullable=True),
        sa.Column('email_confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'linkedin_url', name='uq_connectors_org_linkedin'),
        sa.Index('idx_connectors_email_status', 'email_status'),
        sa.Index('idx_connectors_company', 'company')
    )

    # Prospect-Connector relationships with scoring
    op.create_table('prospect_connectors',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('prospect_id', sa.Integer(), nullable=False),
        sa.Column('connector_id', sa.Integer(), nullable=False),
        sa.Column('team_member_id', sa.Integer(), nullable=True),  # Who knows this connector
        sa.Column('connection_degree', sa.Integer(), nullable=True),  # 1st, 2nd, 3rd degree
        sa.Column('relationship_strength', sa.Float(), nullable=True),  # 0.0 - 1.0
        sa.Column('ranking_score', sa.Float(), nullable=True),  # Composite score
        sa.Column('rank', sa.Integer(), nullable=True),  # 1-5 ranking within prospect
        sa.Column('reason_codes', postgresql.JSONB(), nullable=True),  # Why this score
        sa.Column('mutual_context', sa.Text(), nullable=True),
        sa.Column('shared_experiences', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['prospect_id'], ['prospects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connector_id'], ['connectors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_member_id'], ['team_members.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('organization_id', 'prospect_id', 'connector_id', name='uq_prospect_connectors'),
        sa.Index('idx_prospect_connectors_rank', 'prospect_id', 'rank'),
        sa.Index('idx_prospect_connectors_score', 'ranking_score', postgresql_using='btree')
    )

    # ===================================================================
    # EMAIL AND COMMUNICATION
    # ===================================================================

    # Email templates
    op.create_table('email_templates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('template_type', sa.String(50), nullable=False),  # introduction, follow_up, etc.
        sa.Column('subject_template', sa.Text(), nullable=False),
        sa.Column('body_template', sa.Text(), nullable=False),
        sa.Column('variables', postgresql.JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.Index('idx_email_templates_type', 'template_type', 'is_active')
    )

    # Email jobs (scheduled and sent emails)
    op.create_table('email_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('prospect_connector_id', sa.Integer(), nullable=True),
        sa.Column('email_subject', sa.String(500), nullable=False),
        sa.Column('email_content', sa.Text(), nullable=False),
        sa.Column('recipient_email', sa.String(255), nullable=False),
        sa.Column('sender_team_member_id', sa.Integer(), nullable=True),
        sa.Column('scheduled_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('sent_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('state', sa.String(50), nullable=False, default='queued'),
        sa.Column('tracking_data', postgresql.JSONB(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['prospect_connector_id'], ['prospect_connectors.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['sender_team_member_id'], ['team_members.id'], ondelete='SET NULL'),
        sa.Index('idx_email_jobs_state', 'state'),
        sa.Index('idx_email_jobs_scheduled', 'scheduled_at'),
        sa.Index('idx_email_jobs_org_state', 'organization_id', 'state')
    )

    # ===================================================================
    # APPROVAL AND WORKFLOW
    # ===================================================================

    # Approval requests (September 2025 human-in-the-loop)
    op.create_table('approval_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('email_job_id', sa.Integer(), nullable=True),
        sa.Column('approval_type', sa.String(50), nullable=False),  # email_send, batch_import, etc.
        sa.Column('content_preview', postgresql.JSONB(), nullable=True),
        sa.Column('requestor_type', sa.String(50), nullable=False),  # ai_agent, user, system
        sa.Column('requestor_id', sa.Integer(), nullable=True),
        sa.Column('approver_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='pending'),
        sa.Column('decision_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('approved_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('expires_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['email_job_id'], ['email_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approver_id'], ['team_members.id'], ondelete='SET NULL'),
        sa.Index('idx_approval_requests_status', 'status'),
        sa.Index('idx_approval_requests_org_status', 'organization_id', 'status')
    )

    # ===================================================================
    # QUEUE AND JOB MANAGEMENT
    # ===================================================================

    # Job idempotency (prevent duplicate processing)
    op.create_table('job_idempotency',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('idempotency_key', sa.String(255), nullable=False),
        sa.Column('job_type', sa.String(100), nullable=False),
        sa.Column('job_payload', postgresql.JSONB(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='processing'),
        sa.Column('result', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'idempotency_key', name='uq_job_idempotency'),
        sa.Index('idx_job_idempotency_status', 'status'),
        sa.Index('idx_job_idempotency_type', 'job_type')
    )

    # ===================================================================
    # ANALYTICS AND METRICS
    # ===================================================================

    # Organization metrics (daily/weekly aggregates)
    op.create_table('organization_metrics',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('metric_date', sa.Date(), nullable=False),
        sa.Column('prospects_imported', sa.Integer(), nullable=False, default=0),
        sa.Column('prospects_processed', sa.Integer(), nullable=False, default=0),
        sa.Column('connectors_found', sa.Integer(), nullable=False, default=0),
        sa.Column('emails_scheduled', sa.Integer(), nullable=False, default=0),
        sa.Column('emails_sent', sa.Integer(), nullable=False, default=0),
        sa.Column('emails_replied', sa.Integer(), nullable=False, default=0),
        sa.Column('cost_usd', sa.Numeric(10, 4), nullable=False, default=0),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'metric_date', name='uq_organization_metrics'),
        sa.Index('idx_organization_metrics_date', 'metric_date')
    )

    # ===================================================================
    # AUDIT AND COMPLIANCE
    # ===================================================================

    # Audit events (comprehensive logging)
    op.create_table('audit_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('actor_type', sa.String(50), nullable=False),  # user, system, api, agent
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('target_type', sa.String(50), nullable=True),  # prospect, email, integration
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),  # IPv6 support
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('correlation_id', sa.String(255), nullable=True),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.Index('idx_audit_events_org_timestamp', 'organization_id', 'timestamp'),
        sa.Index('idx_audit_events_action', 'action'),
        sa.Index('idx_audit_events_actor', 'actor_type', 'actor_id'),
        sa.Index('idx_audit_events_correlation', 'correlation_id')
    )

    # ===================================================================
    # ROW LEVEL SECURITY (RLS) POLICIES
    # ===================================================================

    # Enable RLS on all multi-tenant tables
    multi_tenant_tables = [
        'team_members', 'integration_sets', 'cookie_jars', 'prospects',
        'connectors', 'prospect_connectors', 'email_templates', 'email_jobs',
        'approval_requests', 'job_idempotency', 'organization_metrics', 'audit_events'
    ]

    for table_name in multi_tenant_tables:
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")

        # Create RLS policy for organization isolation
        op.execute(f"""
            CREATE POLICY rls_org_isolation_{table_name}
            ON {table_name}
            USING (organization_id = current_setting('app.current_organization_id')::integer)
        """)

    print("✅ Created complete corporate multi-tenant schema with RLS policies")


def downgrade() -> None:
    """Drop the corporate schema and revert to previous state"""

    # Drop all tables in reverse order (respecting foreign key constraints)
    tables_to_drop = [
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

    for table_name in tables_to_drop:
        op.drop_table(table_name)

    print("✅ Dropped all corporate schema tables")