-- Analytics & Metrics Tables
-- Advanced analytics, dashboards, and performance tracking

-- Organization Metrics: Aggregate org-level analytics
CREATE TABLE IF NOT EXISTS organization_metrics (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER NOT NULL,
    metric_date DATE NOT NULL,

    -- User Activity Metrics
    active_users INTEGER DEFAULT 0,
    new_users INTEGER DEFAULT 0,
    total_logins INTEGER DEFAULT 0,

    -- Workflow Metrics
    workflows_started INTEGER DEFAULT 0,
    workflows_completed INTEGER DEFAULT 0,
    workflows_failed INTEGER DEFAULT 0,
    avg_workflow_duration_seconds DECIMAL(10,2),

    -- Prospect Metrics
    prospects_added INTEGER DEFAULT 0,
    prospects_contacted INTEGER DEFAULT 0,
    prospects_responded INTEGER DEFAULT 0,
    response_rate DECIMAL(5,2),

    -- Introduction Metrics
    introductions_sent INTEGER DEFAULT 0,
    introductions_accepted INTEGER DEFAULT 0,
    introduction_success_rate DECIMAL(5,2),

    -- Email Metrics
    emails_sent INTEGER DEFAULT 0,
    emails_delivered INTEGER DEFAULT 0,
    emails_opened INTEGER DEFAULT 0,
    emails_clicked INTEGER DEFAULT 0,
    email_open_rate DECIMAL(5,2),
    email_click_rate DECIMAL(5,2),

    -- LinkedIn Metrics
    linkedin_profiles_scraped INTEGER DEFAULT 0,
    linkedin_connections_found INTEGER DEFAULT 0,
    linkedin_messages_sent INTEGER DEFAULT 0,

    -- Cost Metrics
    total_api_calls INTEGER DEFAULT 0,
    total_cost_dollars DECIMAL(10,2) DEFAULT 0,
    avg_cost_per_prospect DECIMAL(10,2),

    -- Quality Metrics
    data_quality_score DECIMAL(5,2),
    connector_match_rate DECIMAL(5,2),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_organization_metrics_date UNIQUE (tenant_id, organization_id, metric_date)
);

CREATE INDEX idx_organization_metrics_tenant ON organization_metrics(tenant_id);
CREATE INDEX idx_organization_metrics_org ON organization_metrics(organization_id);
CREATE INDEX idx_organization_metrics_date ON organization_metrics(metric_date DESC);
CREATE INDEX idx_organization_metrics_org_date ON organization_metrics(organization_id, metric_date DESC);

-- Performance Metrics: System performance tracking
CREATE TABLE IF NOT EXISTS performance_metrics (
    id BIGSERIAL PRIMARY KEY,
    tenant_id INTEGER,
    metric_type VARCHAR(100) NOT NULL,
    metric_name VARCHAR(255) NOT NULL,
    metric_value DECIMAL(15,4) NOT NULL,
    metric_unit VARCHAR(50),
    dimensions JSONB DEFAULT '{}',
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_performance_metrics_type ON performance_metrics(metric_type);
CREATE INDEX idx_performance_metrics_name ON performance_metrics(metric_name);
CREATE INDEX idx_performance_metrics_recorded ON performance_metrics(recorded_at DESC);
CREATE INDEX idx_performance_metrics_tenant ON performance_metrics(tenant_id);
CREATE INDEX idx_performance_metrics_type_name_recorded ON performance_metrics(metric_type, metric_name, recorded_at DESC);

-- Dashboard Configurations: Custom user dashboards
CREATE TABLE IF NOT EXISTS dashboard_configurations (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    organization_id INTEGER,
    dashboard_name VARCHAR(255) NOT NULL,
    dashboard_type VARCHAR(50) DEFAULT 'custom',
    layout_config JSONB NOT NULL,
    widgets JSONB DEFAULT '[]',
    is_default BOOLEAN DEFAULT FALSE,
    is_shared BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dashboard_configurations_tenant ON dashboard_configurations(tenant_id);
CREATE INDEX idx_dashboard_configurations_user ON dashboard_configurations(user_id);
CREATE INDEX idx_dashboard_configurations_org ON dashboard_configurations(organization_id);
CREATE INDEX idx_dashboard_configurations_type ON dashboard_configurations(dashboard_type);

-- Report Templates: Saved report definitions
CREATE TABLE IF NOT EXISTS report_templates (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER,
    report_name VARCHAR(255) NOT NULL,
    report_type VARCHAR(50) NOT NULL,
    description TEXT,
    query_definition JSONB NOT NULL,
    visualization_config JSONB,
    schedule VARCHAR(50),
    recipients JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_report_templates_tenant ON report_templates(tenant_id);
CREATE INDEX idx_report_templates_org ON report_templates(organization_id);
CREATE INDEX idx_report_templates_type ON report_templates(report_type);
CREATE INDEX idx_report_templates_active ON report_templates(is_active);

-- Report Executions: Track report generation
CREATE TABLE IF NOT EXISTS report_executions (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES report_templates(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL,
    status VARCHAR(50) DEFAULT 'running',
    execution_time_ms INTEGER,
    row_count INTEGER,
    file_url TEXT,
    error_message TEXT,
    executed_by INTEGER,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_report_executions_template ON report_executions(template_id);
CREATE INDEX idx_report_executions_tenant ON report_executions(tenant_id);
CREATE INDEX idx_report_executions_status ON report_executions(status);
CREATE INDEX idx_report_executions_executed ON report_executions(executed_at DESC);

-- Funnel Analytics: Track conversion funnels
CREATE TABLE IF NOT EXISTS funnel_analytics (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER,
    funnel_name VARCHAR(255) NOT NULL,
    funnel_date DATE NOT NULL,
    stage_1_count INTEGER DEFAULT 0,
    stage_2_count INTEGER DEFAULT 0,
    stage_3_count INTEGER DEFAULT 0,
    stage_4_count INTEGER DEFAULT 0,
    stage_5_count INTEGER DEFAULT 0,
    conversion_rate_1_to_2 DECIMAL(5,2),
    conversion_rate_2_to_3 DECIMAL(5,2),
    conversion_rate_3_to_4 DECIMAL(5,2),
    conversion_rate_4_to_5 DECIMAL(5,2),
    overall_conversion_rate DECIMAL(5,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_funnel_analytics_date UNIQUE (tenant_id, organization_id, funnel_name, funnel_date)
);

CREATE INDEX idx_funnel_analytics_tenant ON funnel_analytics(tenant_id);
CREATE INDEX idx_funnel_analytics_org ON funnel_analytics(organization_id);
CREATE INDEX idx_funnel_analytics_name ON funnel_analytics(funnel_name);
CREATE INDEX idx_funnel_analytics_date ON funnel_analytics(funnel_date DESC);

-- User Engagement Scores: Track user engagement over time
CREATE TABLE IF NOT EXISTS user_engagement_scores (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL,
    score_date DATE NOT NULL,
    login_score DECIMAL(5,2) DEFAULT 0,
    activity_score DECIMAL(5,2) DEFAULT 0,
    feature_usage_score DECIMAL(5,2) DEFAULT 0,
    collaboration_score DECIMAL(5,2) DEFAULT 0,
    overall_score DECIMAL(5,2) DEFAULT 0,
    engagement_tier VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_engagement_date UNIQUE (user_id, score_date)
);

CREATE INDEX idx_user_engagement_scores_user ON user_engagement_scores(user_id);
CREATE INDEX idx_user_engagement_scores_tenant ON user_engagement_scores(tenant_id);
CREATE INDEX idx_user_engagement_scores_date ON user_engagement_scores(score_date DESC);
CREATE INDEX idx_user_engagement_scores_tier ON user_engagement_scores(engagement_tier);

-- Comments
COMMENT ON TABLE organization_metrics IS 'Daily aggregate metrics per organization';
COMMENT ON TABLE performance_metrics IS 'System performance and operational metrics';
COMMENT ON TABLE dashboard_configurations IS 'Custom user dashboard layouts';
COMMENT ON TABLE report_templates IS 'Saved report definitions for scheduled execution';
COMMENT ON TABLE report_executions IS 'History of report generation runs';
COMMENT ON TABLE funnel_analytics IS 'Conversion funnel tracking and analysis';
COMMENT ON TABLE user_engagement_scores IS 'User engagement scoring over time';
