-- Email Campaign Management Tables
-- Comprehensive email campaign tracking and template management

-- Email Templates: Reusable email templates
CREATE TABLE IF NOT EXISTS email_templates (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER,
    name VARCHAR(255) NOT NULL,
    subject_template TEXT NOT NULL,
    body_template TEXT NOT NULL,
    template_type VARCHAR(50) DEFAULT 'introduction',
    variables JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_email_templates_tenant_name UNIQUE (tenant_id, name)
);

CREATE INDEX idx_email_templates_tenant ON email_templates(tenant_id);
CREATE INDEX idx_email_templates_org ON email_templates(organization_id);
CREATE INDEX idx_email_templates_type ON email_templates(template_type);
CREATE INDEX idx_email_templates_active ON email_templates(is_active);

-- Email Campaigns: Campaign orchestration
CREATE TABLE IF NOT EXISTS email_campaigns (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER,
    campaign_name VARCHAR(255) NOT NULL,
    campaign_type VARCHAR(50) DEFAULT 'outreach',
    template_id INTEGER REFERENCES email_templates(id) ON DELETE SET NULL,
    status VARCHAR(50) DEFAULT 'draft',
    target_segment JSONB,
    send_schedule TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    total_recipients INTEGER DEFAULT 0,
    total_sent INTEGER DEFAULT 0,
    total_delivered INTEGER DEFAULT 0,
    total_opened INTEGER DEFAULT 0,
    total_clicked INTEGER DEFAULT 0,
    total_bounced INTEGER DEFAULT 0,
    total_unsubscribed INTEGER DEFAULT 0,
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_email_campaigns_tenant ON email_campaigns(tenant_id);
CREATE INDEX idx_email_campaigns_org ON email_campaigns(organization_id);
CREATE INDEX idx_email_campaigns_status ON email_campaigns(status);
CREATE INDEX idx_email_campaigns_schedule ON email_campaigns(send_schedule);
CREATE INDEX idx_email_campaigns_created ON email_campaigns(created_at DESC);

-- Email Messages: Individual email tracking
CREATE TABLE IF NOT EXISTS email_messages (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER,
    campaign_id INTEGER REFERENCES email_campaigns(id) ON DELETE CASCADE,
    template_id INTEGER REFERENCES email_templates(id) ON DELETE SET NULL,
    recipient_email VARCHAR(255) NOT NULL,
    recipient_name VARCHAR(255),
    recipient_type VARCHAR(50) DEFAULT 'prospect',
    recipient_id INTEGER,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    provider VARCHAR(50) DEFAULT 'sendgrid',
    provider_message_id VARCHAR(255),
    scheduled_at TIMESTAMP,
    sent_at TIMESTAMP,
    delivered_at TIMESTAMP,
    opened_at TIMESTAMP,
    clicked_at TIMESTAMP,
    bounced_at TIMESTAMP,
    bounce_reason TEXT,
    unsubscribed_at TIMESTAMP,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_email_messages_tenant ON email_messages(tenant_id);
CREATE INDEX idx_email_messages_org ON email_messages(organization_id);
CREATE INDEX idx_email_messages_campaign ON email_messages(campaign_id);
CREATE INDEX idx_email_messages_recipient ON email_messages(recipient_email);
CREATE INDEX idx_email_messages_status ON email_messages(status);
CREATE INDEX idx_email_messages_sent ON email_messages(sent_at DESC);
CREATE INDEX idx_email_messages_provider_id ON email_messages(provider_message_id);
CREATE INDEX idx_email_messages_recipient_type_id ON email_messages(recipient_type, recipient_id);

-- Email Interactions: Click and open tracking
CREATE TABLE IF NOT EXISTS email_interactions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
    interaction_type VARCHAR(50) NOT NULL,
    interaction_data JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    interaction_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_email_interactions_message ON email_interactions(message_id);
CREATE INDEX idx_email_interactions_type ON email_interactions(interaction_type);
CREATE INDEX idx_email_interactions_at ON email_interactions(interaction_at DESC);

-- Email Sequences: Automated email sequences
CREATE TABLE IF NOT EXISTS email_sequences (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER,
    sequence_name VARCHAR(255) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    trigger_type VARCHAR(50) DEFAULT 'manual',
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_email_sequences_tenant ON email_sequences(tenant_id);
CREATE INDEX idx_email_sequences_org ON email_sequences(organization_id);
CREATE INDEX idx_email_sequences_active ON email_sequences(is_active);

-- Email Sequence Steps: Individual steps in sequences
CREATE TABLE IF NOT EXISTS email_sequence_steps (
    id SERIAL PRIMARY KEY,
    sequence_id INTEGER NOT NULL REFERENCES email_sequences(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    template_id INTEGER REFERENCES email_templates(id) ON DELETE SET NULL,
    delay_days INTEGER DEFAULT 0,
    delay_hours INTEGER DEFAULT 0,
    send_time_preference VARCHAR(20) DEFAULT 'any',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sequence_steps UNIQUE (sequence_id, step_number)
);

CREATE INDEX idx_email_sequence_steps_sequence ON email_sequence_steps(sequence_id);
CREATE INDEX idx_email_sequence_steps_template ON email_sequence_steps(template_id);

-- Email Sequence Enrollments: Track who's in which sequence
CREATE TABLE IF NOT EXISTS email_sequence_enrollments (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    sequence_id INTEGER NOT NULL REFERENCES email_sequences(id) ON DELETE CASCADE,
    recipient_email VARCHAR(255) NOT NULL,
    recipient_type VARCHAR(50) DEFAULT 'prospect',
    recipient_id INTEGER,
    current_step INTEGER DEFAULT 1,
    status VARCHAR(50) DEFAULT 'active',
    enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_sent_at TIMESTAMP,
    completed_at TIMESTAMP,
    paused_at TIMESTAMP,
    unsubscribed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_email_sequence_enrollments_tenant ON email_sequence_enrollments(tenant_id);
CREATE INDEX idx_email_sequence_enrollments_sequence ON email_sequence_enrollments(sequence_id);
CREATE INDEX idx_email_sequence_enrollments_recipient ON email_sequence_enrollments(recipient_email);
CREATE INDEX idx_email_sequence_enrollments_status ON email_sequence_enrollments(status);

-- Comments
COMMENT ON TABLE email_templates IS 'Reusable email templates with variable substitution';
COMMENT ON TABLE email_campaigns IS 'Email campaign orchestration and bulk sending';
COMMENT ON TABLE email_messages IS 'Individual email tracking with delivery status';
COMMENT ON TABLE email_interactions IS 'Email open and click tracking';
COMMENT ON TABLE email_sequences IS 'Automated email drip sequences';
COMMENT ON TABLE email_sequence_steps IS 'Individual steps in email sequences';
COMMENT ON TABLE email_sequence_enrollments IS 'Recipients enrolled in email sequences';
