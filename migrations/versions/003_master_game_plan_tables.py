"""Master Game Plan additional tables

Revision ID: 003_master_game_plan_tables
Revises: 002_migrate_existing_data
Create Date: 2025-01-27 12:00:00.000000

This migration adds the specific Master Game Plan tables to complement the existing
corporate schema, providing dedicated structures for company tracking, executive
profiles, connection management, and automation settings.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_master_game_plan_tables'
down_revision = '002_migrate_data'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create Master Game Plan specific tables"""

    # ===================================================================
    # COMPANIES TABLE - Master Game Plan Company Tracking
    # ===================================================================

    op.create_table('companies',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('domain', sa.String(255), nullable=True),
        sa.Column('website', sa.String(500), nullable=True),
        sa.Column('industry', sa.String(100), nullable=True),
        sa.Column('size', sa.String(50), nullable=True),  # startup, small, medium, large, enterprise
        sa.Column('employee_count', sa.Integer(), nullable=True),
        sa.Column('revenue_range', sa.String(50), nullable=True),
        sa.Column('headquarters', sa.String(255), nullable=True),
        sa.Column('founded_year', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('linkedin_company_url', sa.String(500), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='active'),  # active, paused, completed
        sa.Column('automation_enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('target_titles', postgresql.JSONB(), nullable=True),  # List of target executive titles
        sa.Column('priority', sa.String(20), nullable=False, default='medium'),  # high, medium, low
        sa.Column('tags', postgresql.JSONB(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('last_processed_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'name', name='uq_companies_org_name'),
        sa.Index('idx_companies_domain', 'domain'),
        sa.Index('idx_companies_industry', 'industry'),
        sa.Index('idx_companies_size', 'size'),
        sa.Index('idx_companies_status', 'status'),
        sa.Index('idx_companies_automation', 'automation_enabled'),
        sa.Index('idx_companies_priority', 'priority')
    )

    # ===================================================================
    # EXECUTIVES TABLE - Master Game Plan Executive Profiles
    # ===================================================================

    op.create_table('executives',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('first_name', sa.String(100), nullable=True),
        sa.Column('last_name', sa.String(100), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('seniority_level', sa.String(50), nullable=True),  # c_level, vp, director, manager
        sa.Column('department', sa.String(100), nullable=True),  # marketing, technology, sales, operations
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('email_status', sa.String(50), nullable=True),  # verified, unverified, invalid, bounced
        sa.Column('email_confidence_score', sa.Float(), nullable=True),  # 0.0 - 1.0
        sa.Column('linkedin_url', sa.String(500), nullable=True),
        sa.Column('linkedin_profile_id', sa.String(100), nullable=True),
        sa.Column('location', sa.String(255), nullable=True),
        sa.Column('headline', sa.Text(), nullable=True),
        sa.Column('about', sa.Text(), nullable=True),
        sa.Column('profile_picture_url', sa.String(500), nullable=True),
        sa.Column('experience_years', sa.Integer(), nullable=True),
        sa.Column('previous_companies', postgresql.JSONB(), nullable=True),
        sa.Column('education', postgresql.JSONB(), nullable=True),
        sa.Column('skills', postgresql.JSONB(), nullable=True),
        sa.Column('data_source', sa.String(100), nullable=False, default='manual'),  # linkedin, clearbit, apollo, manual
        sa.Column('data_quality_score', sa.Float(), nullable=True),  # 0.0 - 1.0
        sa.Column('verification_status', sa.String(50), nullable=False, default='unverified'),
        sa.Column('last_verified_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='active'),  # active, processed, invalid
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'company_id', 'email', name='uq_executives_org_company_email'),
        sa.Index('idx_executives_title', 'title'),
        sa.Index('idx_executives_seniority', 'seniority_level'),
        sa.Index('idx_executives_department', 'department'),
        sa.Index('idx_executives_email_status', 'email_status'),
        sa.Index('idx_executives_linkedin', 'linkedin_profile_id'),
        sa.Index('idx_executives_verification', 'verification_status'),
        sa.Index('idx_executives_data_source', 'data_source')
    )

    # ===================================================================
    # CONNECTIONS TABLE - Master Game Plan Mutual Connections
    # ===================================================================

    op.create_table('connections',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('executive_id', sa.Integer(), nullable=False),
        sa.Column('team_member_id', sa.Integer(), nullable=False),
        sa.Column('connector_full_name', sa.String(255), nullable=False),
        sa.Column('connector_linkedin_url', sa.String(500), nullable=False),
        sa.Column('connector_title', sa.String(255), nullable=True),
        sa.Column('connector_company', sa.String(255), nullable=True),
        sa.Column('connector_location', sa.String(255), nullable=True),
        sa.Column('connector_profile_picture_url', sa.String(500), nullable=True),
        sa.Column('connection_degree', sa.Integer(), nullable=False, default=2),  # 1st, 2nd, 3rd degree
        sa.Column('shared_connections_count', sa.Integer(), nullable=False, default=0),
        sa.Column('mutual_context', sa.Text(), nullable=True),
        sa.Column('relationship_notes', sa.Text(), nullable=True),
        sa.Column('connection_source', sa.String(100), nullable=False, default='apify'),  # apify, linkedin, manual
        sa.Column('discovery_method', sa.String(100), nullable=True),  # mutual_search, profile_scrape, import
        sa.Column('last_interaction_date', sa.TIMESTAMP(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='discovered'),  # discovered, contacted, responded, converted
        sa.Column('outreach_status', sa.String(50), nullable=True),  # pending, sent, delivered, opened, clicked
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['executive_id'], ['executives.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_member_id'], ['team_members.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'executive_id', 'team_member_id', 'connector_linkedin_url',
                          name='uq_connections_exec_member_connector'),
        sa.Index('idx_connections_degree', 'connection_degree'),
        sa.Index('idx_connections_count', 'shared_connections_count'),
        sa.Index('idx_connections_status', 'status'),
        sa.Index('idx_connections_outreach', 'outreach_status'),
        sa.Index('idx_connections_source', 'connection_source')
    )

    # ===================================================================
    # CONNECTOR_RANKINGS TABLE - Master Game Plan Connection Scoring
    # ===================================================================

    op.create_table('connector_rankings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=False),
        sa.Column('executive_id', sa.Integer(), nullable=False),
        sa.Column('team_member_id', sa.Integer(), nullable=False),
        sa.Column('overall_score', sa.Float(), nullable=False, default=0.0),  # 0.0 - 100.0
        sa.Column('rank', sa.Integer(), nullable=True),  # 1-N ranking within executive
        sa.Column('relationship_strength_score', sa.Float(), nullable=True),  # 0.0 - 100.0
        sa.Column('industry_relevance_score', sa.Float(), nullable=True),  # 0.0 - 100.0
        sa.Column('geographic_proximity_score', sa.Float(), nullable=True),  # 0.0 - 100.0
        sa.Column('seniority_match_score', sa.Float(), nullable=True),  # 0.0 - 100.0
        sa.Column('response_likelihood_score', sa.Float(), nullable=True),  # 0.0 - 100.0
        sa.Column('timing_score', sa.Float(), nullable=True),  # 0.0 - 100.0
        sa.Column('scoring_factors', postgresql.JSONB(), nullable=True),  # Detailed breakdown
        sa.Column('ranking_algorithm_version', sa.String(50), nullable=False, default='v1.0'),
        sa.Column('confidence_interval', sa.Float(), nullable=True),  # Statistical confidence
        sa.Column('explanation', sa.Text(), nullable=True),  # Human-readable explanation
        sa.Column('last_calculated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['executive_id'], ['executives.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_member_id'], ['team_members.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'connection_id', name='uq_connector_rankings_connection'),
        sa.Index('idx_connector_rankings_score', 'overall_score', postgresql_using='btree'),
        sa.Index('idx_connector_rankings_rank', 'executive_id', 'rank'),
        sa.Index('idx_connector_rankings_algorithm', 'ranking_algorithm_version'),
        sa.Index('idx_connector_rankings_calculated', 'last_calculated_at')
    )

    # ===================================================================
    # COMPANY_SETTINGS TABLE - Master Game Plan Automation Configuration
    # ===================================================================

    op.create_table('company_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('automation_enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('auto_executive_discovery', sa.Boolean(), nullable=False, default=True),
        sa.Column('auto_email_enrichment', sa.Boolean(), nullable=False, default=True),
        sa.Column('auto_mutual_connections', sa.Boolean(), nullable=False, default=True),
        sa.Column('auto_ranking_calculation', sa.Boolean(), nullable=False, default=True),
        sa.Column('max_executives_per_company', sa.Integer(), nullable=False, default=5),
        sa.Column('max_connections_per_executive', sa.Integer(), nullable=False, default=10),
        sa.Column('min_connection_score_threshold', sa.Float(), nullable=False, default=50.0),
        sa.Column('target_seniority_levels', postgresql.JSONB(), nullable=True),  # c_level, vp, director
        sa.Column('target_departments', postgresql.JSONB(), nullable=True),  # marketing, technology, sales
        sa.Column('excluded_titles', postgresql.JSONB(), nullable=True),  # Titles to exclude
        sa.Column('geographic_preferences', postgresql.JSONB(), nullable=True),  # Location preferences
        sa.Column('industry_filters', postgresql.JSONB(), nullable=True),  # Industry targeting
        sa.Column('automation_schedule', postgresql.JSONB(), nullable=True),  # When to run automation
        sa.Column('notification_settings', postgresql.JSONB(), nullable=True),  # Alert preferences
        sa.Column('email_template_preferences', postgresql.JSONB(), nullable=True),  # Template settings
        sa.Column('data_retention_days', sa.Integer(), nullable=False, default=365),
        sa.Column('privacy_compliance_level', sa.String(50), nullable=False, default='standard'),  # strict, standard, minimal
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'company_id', name='uq_company_settings_org_company'),
        sa.Index('idx_company_settings_automation', 'automation_enabled'),
        sa.Index('idx_company_settings_active', 'is_active')
    )

    # ===================================================================
    # AUTOMATION_JOBS TABLE - Master Game Plan Job Tracking
    # ===================================================================

    op.create_table('automation_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=True),
        sa.Column('job_type', sa.String(100), nullable=False),  # company_automation, executive_discovery, email_enrichment
        sa.Column('job_status', sa.String(50), nullable=False, default='pending'),  # pending, running, completed, failed, cancelled
        sa.Column('priority', sa.String(20), nullable=False, default='normal'),  # high, normal, low
        sa.Column('progress_percentage', sa.Float(), nullable=False, default=0.0),  # 0.0 - 100.0
        sa.Column('items_total', sa.Integer(), nullable=True),
        sa.Column('items_processed', sa.Integer(), nullable=False, default=0),
        sa.Column('items_successful', sa.Integer(), nullable=False, default=0),
        sa.Column('items_failed', sa.Integer(), nullable=False, default=0),
        sa.Column('job_parameters', postgresql.JSONB(), nullable=True),  # Input parameters
        sa.Column('job_results', postgresql.JSONB(), nullable=True),  # Output results
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details', postgresql.JSONB(), nullable=True),
        sa.Column('started_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('completed_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('estimated_completion_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),  # team_member_id
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['team_members.id'], ondelete='SET NULL'),
        sa.Index('idx_automation_jobs_status', 'job_status'),
        sa.Index('idx_automation_jobs_type', 'job_type'),
        sa.Index('idx_automation_jobs_priority', 'priority'),
        sa.Index('idx_automation_jobs_created', 'created_at'),
        sa.Index('idx_automation_jobs_org_status', 'organization_id', 'job_status')
    )


def downgrade() -> None:
    """Drop Master Game Plan specific tables"""

    op.drop_table('automation_jobs')
    op.drop_table('company_settings')
    op.drop_table('connector_rankings')
    op.drop_table('connections')
    op.drop_table('executives')
    op.drop_table('companies')