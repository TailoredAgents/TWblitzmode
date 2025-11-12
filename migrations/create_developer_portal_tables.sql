-- Developer Portal Tables
-- Self-service developer tools and management

-- Dev Portal Developers: Developer accounts
CREATE TABLE IF NOT EXISTS dev_portal_developers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    company VARCHAR(255),
    role VARCHAR(50) DEFAULT 'developer',
    status VARCHAR(50) DEFAULT 'active',
    api_key_hash TEXT,
    api_key_last_four VARCHAR(4),
    password_hash TEXT,
    mfa_enabled BOOLEAN DEFAULT FALSE,
    mfa_secret TEXT,
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_dev_portal_developers_email UNIQUE (tenant_id, email)
);

CREATE INDEX idx_dev_portal_developers_tenant ON dev_portal_developers(tenant_id);
CREATE INDEX idx_dev_portal_developers_status ON dev_portal_developers(status);
CREATE INDEX idx_dev_portal_developers_email ON dev_portal_developers(email);

-- Dev Portal Codes: Access codes for developer registration
CREATE TABLE IF NOT EXISTS dev_portal_codes (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    code_hash TEXT NOT NULL UNIQUE,
    code_type VARCHAR(50) DEFAULT 'registration',
    max_uses INTEGER DEFAULT 1,
    current_uses INTEGER DEFAULT 0,
    expires_at TIMESTAMP,
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP
);

CREATE INDEX idx_dev_portal_codes_tenant ON dev_portal_codes(tenant_id);
CREATE INDEX idx_dev_portal_codes_type ON dev_portal_codes(code_type);
CREATE INDEX idx_dev_portal_codes_expires ON dev_portal_codes(expires_at);

-- Dev Portal Devices: Trusted devices for developers
CREATE TABLE IF NOT EXISTS dev_portal_devices (
    id SERIAL PRIMARY KEY,
    developer_id INTEGER NOT NULL REFERENCES dev_portal_developers(id) ON DELETE CASCADE,
    device_fingerprint TEXT NOT NULL,
    device_name VARCHAR(255),
    device_type VARCHAR(50),
    browser VARCHAR(100),
    os VARCHAR(100),
    ip_address VARCHAR(45),
    is_trusted BOOLEAN DEFAULT FALSE,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_dev_portal_devices UNIQUE (developer_id, device_fingerprint)
);

CREATE INDEX idx_dev_portal_devices_developer ON dev_portal_devices(developer_id);
CREATE INDEX idx_dev_portal_devices_trusted ON dev_portal_devices(is_trusted);

-- Dev Portal Security Policies: Security settings
CREATE TABLE IF NOT EXISTS dev_portal_security_policies (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    policy_name VARCHAR(255) NOT NULL,
    require_mfa BOOLEAN DEFAULT TRUE,
    max_api_keys_per_dev INTEGER DEFAULT 3,
    api_key_rotation_days INTEGER DEFAULT 90,
    session_timeout_minutes INTEGER DEFAULT 60,
    ip_whitelist JSONB DEFAULT '[]',
    allowed_origins JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dev_portal_security_policies_tenant ON dev_portal_security_policies(tenant_id);
CREATE INDEX idx_dev_portal_security_policies_active ON dev_portal_security_policies(is_active);

-- Dev Portal Backup Codes: 2FA backup codes
CREATE TABLE IF NOT EXISTS dev_portal_backup_codes (
    id SERIAL PRIMARY KEY,
    developer_id INTEGER NOT NULL REFERENCES dev_portal_developers(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    is_used BOOLEAN DEFAULT FALSE,
    used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dev_portal_backup_codes_developer ON dev_portal_backup_codes(developer_id);
CREATE INDEX idx_dev_portal_backup_codes_used ON dev_portal_backup_codes(is_used);

-- Dev Portal WebAuthn Credentials: Passwordless auth
CREATE TABLE IF NOT EXISTS dev_portal_webauthn_credentials (
    id SERIAL PRIMARY KEY,
    developer_id INTEGER NOT NULL REFERENCES dev_portal_developers(id) ON DELETE CASCADE,
    credential_id TEXT NOT NULL UNIQUE,
    public_key TEXT NOT NULL,
    counter BIGINT DEFAULT 0,
    device_type VARCHAR(50),
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP
);

CREATE INDEX idx_dev_portal_webauthn_developer ON dev_portal_webauthn_credentials(developer_id);
CREATE INDEX idx_dev_portal_webauthn_credential ON dev_portal_webauthn_credentials(credential_id);

-- Dev Portal Dual Approvals: Sensitive action approvals
CREATE TABLE IF NOT EXISTS dev_portal_dual_approvals (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    action_data JSONB NOT NULL,
    requested_by INTEGER NOT NULL REFERENCES dev_portal_developers(id),
    status VARCHAR(50) DEFAULT 'pending',
    approved_by INTEGER REFERENCES dev_portal_developers(id),
    rejection_reason TEXT,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP
);

CREATE INDEX idx_dev_portal_dual_approvals_tenant ON dev_portal_dual_approvals(tenant_id);
CREATE INDEX idx_dev_portal_dual_approvals_status ON dev_portal_dual_approvals(status);
CREATE INDEX idx_dev_portal_dual_approvals_requested ON dev_portal_dual_approvals(requested_by);

-- Dev Portal Compliance Exports: Data export requests
CREATE TABLE IF NOT EXISTS dev_portal_compliance_exports (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    developer_id INTEGER REFERENCES dev_portal_developers(id),
    export_type VARCHAR(50) NOT NULL,
    export_format VARCHAR(20) DEFAULT 'json',
    status VARCHAR(50) DEFAULT 'pending',
    file_url TEXT,
    expires_at TIMESTAMP,
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_dev_portal_compliance_exports_tenant ON dev_portal_compliance_exports(tenant_id);
CREATE INDEX idx_dev_portal_compliance_exports_developer ON dev_portal_compliance_exports(developer_id);
CREATE INDEX idx_dev_portal_compliance_exports_status ON dev_portal_compliance_exports(status);

-- Dev Portal Investigation Locks: Investigation mode tracking
CREATE TABLE IF NOT EXISTS dev_portal_investigation_locks (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    locked_by INTEGER NOT NULL REFERENCES dev_portal_developers(id),
    reason TEXT,
    locked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    CONSTRAINT uq_dev_portal_investigation_locks UNIQUE (tenant_id, resource_type, resource_id)
);

CREATE INDEX idx_dev_portal_investigation_locks_tenant ON dev_portal_investigation_locks(tenant_id);
CREATE INDEX idx_dev_portal_investigation_locks_resource ON dev_portal_investigation_locks(resource_type, resource_id);

-- Dev Portal License Events: License usage tracking
CREATE TABLE IF NOT EXISTS dev_portal_license_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    developer_id INTEGER REFERENCES dev_portal_developers(id),
    license_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dev_portal_license_events_tenant ON dev_portal_license_events(tenant_id);
CREATE INDEX idx_dev_portal_license_events_type ON dev_portal_license_events(event_type);
CREATE INDEX idx_dev_portal_license_events_created ON dev_portal_license_events(created_at DESC);

-- Dev Portal Dependency Health: Track dependency status
CREATE TABLE IF NOT EXISTS dev_portal_dependency_health (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    dependency_name VARCHAR(255) NOT NULL,
    dependency_type VARCHAR(50) NOT NULL,
    current_version VARCHAR(50),
    latest_version VARCHAR(50),
    health_status VARCHAR(50) DEFAULT 'healthy',
    vulnerabilities JSONB DEFAULT '[]',
    last_checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_dev_portal_dependency UNIQUE (tenant_id, dependency_name)
);

CREATE INDEX idx_dev_portal_dependency_health_tenant ON dev_portal_dependency_health(tenant_id);
CREATE INDEX idx_dev_portal_dependency_health_status ON dev_portal_dependency_health(health_status);

-- Dev Portal Invitations: Developer invitations
CREATE TABLE IF NOT EXISTS dev_portal_invitations (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'developer',
    invitation_token_hash TEXT NOT NULL,
    invited_by INTEGER REFERENCES dev_portal_developers(id),
    status VARCHAR(50) DEFAULT 'pending',
    expires_at TIMESTAMP,
    accepted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dev_portal_invitations_tenant ON dev_portal_invitations(tenant_id);
CREATE INDEX idx_dev_portal_invitations_email ON dev_portal_invitations(email);
CREATE INDEX idx_dev_portal_invitations_status ON dev_portal_invitations(status);

-- Dev Portal Secrets: Secret management
CREATE TABLE IF NOT EXISTS dev_portal_secrets (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    developer_id INTEGER REFERENCES dev_portal_developers(id),
    secret_name VARCHAR(255) NOT NULL,
    secret_value_encrypted TEXT NOT NULL,
    encryption_key_id VARCHAR(255),
    secret_type VARCHAR(50) DEFAULT 'generic',
    description TEXT,
    expires_at TIMESTAMP,
    last_accessed_at TIMESTAMP,
    rotation_required BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_dev_portal_secrets UNIQUE (tenant_id, secret_name)
);

CREATE INDEX idx_dev_portal_secrets_tenant ON dev_portal_secrets(tenant_id);
CREATE INDEX idx_dev_portal_secrets_developer ON dev_portal_secrets(developer_id);
CREATE INDEX idx_dev_portal_secrets_type ON dev_portal_secrets(secret_type);
CREATE INDEX idx_dev_portal_secrets_expires ON dev_portal_secrets(expires_at);

-- Dev Portal Secret Events: Secret audit log
CREATE TABLE IF NOT EXISTS dev_portal_secret_events (
    id BIGSERIAL PRIMARY KEY,
    secret_id INTEGER NOT NULL REFERENCES dev_portal_secrets(id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    actor_id INTEGER REFERENCES dev_portal_developers(id),
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dev_portal_secret_events_secret ON dev_portal_secret_events(secret_id);
CREATE INDEX idx_dev_portal_secret_events_type ON dev_portal_secret_events(event_type);
CREATE INDEX idx_dev_portal_secret_events_created ON dev_portal_secret_events(created_at DESC);

-- Dev Portal Alert Rules: Custom alerting
CREATE TABLE IF NOT EXISTS dev_portal_alert_rules (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    developer_id INTEGER REFERENCES dev_portal_developers(id),
    rule_name VARCHAR(255) NOT NULL,
    rule_type VARCHAR(50) NOT NULL,
    condition_config JSONB NOT NULL,
    notification_channels JSONB DEFAULT '["email"]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dev_portal_alert_rules_tenant ON dev_portal_alert_rules(tenant_id);
CREATE INDEX idx_dev_portal_alert_rules_developer ON dev_portal_alert_rules(developer_id);
CREATE INDEX idx_dev_portal_alert_rules_type ON dev_portal_alert_rules(rule_type);
CREATE INDEX idx_dev_portal_alert_rules_active ON dev_portal_alert_rules(is_active);

-- Dev Portal Notifications: Notification queue
CREATE TABLE IF NOT EXISTS dev_portal_notifications (
    id SERIAL PRIMARY KEY,
    developer_id INTEGER NOT NULL REFERENCES dev_portal_developers(id) ON DELETE CASCADE,
    notification_type VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    severity VARCHAR(20) DEFAULT 'info',
    is_read BOOLEAN DEFAULT FALSE,
    action_url TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP
);

CREATE INDEX idx_dev_portal_notifications_developer ON dev_portal_notifications(developer_id);
CREATE INDEX idx_dev_portal_notifications_read ON dev_portal_notifications(is_read);
CREATE INDEX idx_dev_portal_notifications_created ON dev_portal_notifications(created_at DESC);

-- Dev Portal Alert Rule Versions: Version history
CREATE TABLE IF NOT EXISTS dev_portal_alert_rule_versions (
    id SERIAL PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES dev_portal_alert_rules(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    condition_config JSONB NOT NULL,
    changed_by INTEGER REFERENCES dev_portal_developers(id),
    change_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_dev_portal_alert_rule_versions UNIQUE (rule_id, version_number)
);

CREATE INDEX idx_dev_portal_alert_rule_versions_rule ON dev_portal_alert_rule_versions(rule_id);

-- Dev Portal Alert Evaluations: Alert evaluation log
CREATE TABLE IF NOT EXISTS dev_portal_alert_evaluations (
    id BIGSERIAL PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES dev_portal_alert_rules(id) ON DELETE CASCADE,
    evaluation_result BOOLEAN NOT NULL,
    evaluation_data JSONB,
    notification_sent BOOLEAN DEFAULT FALSE,
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dev_portal_alert_evaluations_rule ON dev_portal_alert_evaluations(rule_id);
CREATE INDEX idx_dev_portal_alert_evaluations_result ON dev_portal_alert_evaluations(evaluation_result);
CREATE INDEX idx_dev_portal_alert_evaluations_evaluated ON dev_portal_alert_evaluations(evaluated_at DESC);

-- Dev Audit Trail: Comprehensive developer audit log
CREATE TABLE IF NOT EXISTS dev_audit_trail (
    id BIGSERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    developer_id INTEGER REFERENCES dev_portal_developers(id),
    action VARCHAR(255) NOT NULL,
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),
    ip_address VARCHAR(45),
    user_agent TEXT,
    request_id VARCHAR(255),
    response_status INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dev_audit_trail_tenant ON dev_audit_trail(tenant_id);
CREATE INDEX idx_dev_audit_trail_developer ON dev_audit_trail(developer_id);
CREATE INDEX idx_dev_audit_trail_action ON dev_audit_trail(action);
CREATE INDEX idx_dev_audit_trail_resource ON dev_audit_trail(resource_type, resource_id);
CREATE INDEX idx_dev_audit_trail_created ON dev_audit_trail(created_at DESC);

-- Comments
COMMENT ON TABLE dev_portal_developers IS 'Developer accounts in the developer portal';
COMMENT ON TABLE dev_portal_codes IS 'Access codes for developer registration';
COMMENT ON TABLE dev_portal_devices IS 'Trusted devices for developers';
COMMENT ON TABLE dev_portal_security_policies IS 'Security policies for developer portal';
COMMENT ON TABLE dev_portal_backup_codes IS '2FA backup codes for account recovery';
COMMENT ON TABLE dev_portal_webauthn_credentials IS 'WebAuthn/Passkey credentials';
COMMENT ON TABLE dev_portal_dual_approvals IS 'Dual approval workflow for sensitive actions';
COMMENT ON TABLE dev_portal_compliance_exports IS 'GDPR/compliance data export requests';
COMMENT ON TABLE dev_portal_investigation_locks IS 'Resource locks during investigations';
COMMENT ON TABLE dev_portal_license_events IS 'License usage and quota tracking';
COMMENT ON TABLE dev_portal_dependency_health IS 'Dependency health and vulnerability tracking';
COMMENT ON TABLE dev_portal_invitations IS 'Developer invitation management';
COMMENT ON TABLE dev_portal_secrets IS 'Secure secret storage with encryption';
COMMENT ON TABLE dev_portal_secret_events IS 'Audit trail for secret access';
COMMENT ON TABLE dev_portal_alert_rules IS 'Custom alert rule definitions';
COMMENT ON TABLE dev_portal_notifications IS 'In-app notification queue';
COMMENT ON TABLE dev_portal_alert_rule_versions IS 'Alert rule version history';
COMMENT ON TABLE dev_portal_alert_evaluations IS 'Alert evaluation execution log';
COMMENT ON TABLE dev_audit_trail IS 'Comprehensive developer action audit trail';
