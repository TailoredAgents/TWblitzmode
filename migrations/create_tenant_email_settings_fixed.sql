-- Create tenant_email_settings table if it doesn't exist
-- Note: Using tenant_id as INT without FK since this is multi-tenant by convention
CREATE TABLE IF NOT EXISTS tenant_email_settings (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    sendgrid_api_key_encrypted TEXT,
    from_email VARCHAR(255),
    from_name VARCHAR(255),
    domain_verified BOOLEAN DEFAULT FALSE,
    daily_limit INTEGER DEFAULT 100,
    warmup_status VARCHAR(50) DEFAULT 'pending',
    warmup_started_at TIMESTAMP,
    total_sent INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_tenant_email_settings_tenant UNIQUE (tenant_id)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_tenant_email_settings_tenant_id ON tenant_email_settings(tenant_id);

-- Create email_costs table if it doesn't exist
CREATE TABLE IF NOT EXISTS email_costs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    date DATE NOT NULL,
    service VARCHAR(50) NOT NULL,
    operation VARCHAR(50) NOT NULL,
    count INTEGER DEFAULT 0,
    unit_cost DECIMAL(10,4) DEFAULT 0.001,
    total_cost DECIMAL(10,4) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_email_costs_unique UNIQUE (tenant_id, date, service, operation)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_email_costs_tenant_date ON email_costs(tenant_id, date);

-- Create email_suppression_list table if it doesn't exist
CREATE TABLE IF NOT EXISTS email_suppression_list (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    email VARCHAR(255) NOT NULL,
    reason VARCHAR(255),
    type VARCHAR(50),
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    CONSTRAINT uk_email_suppression_unique UNIQUE (tenant_id, email, reason)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_email_suppression_tenant_email ON email_suppression_list(tenant_id, email);

-- Create email_webhook_events table if it doesn't exist
CREATE TABLE IF NOT EXISTS email_webhook_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(255),
    message_id VARCHAR(255),
    tenant_id INTEGER NOT NULL,
    email VARCHAR(255),
    event_type VARCHAR(50),
    timestamp TIMESTAMP,
    payload JSONB,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_email_webhook_tenant_email ON email_webhook_events(tenant_id, email);
CREATE INDEX IF NOT EXISTS idx_email_webhook_message_id ON email_webhook_events(message_id);

-- Create tenant_sendgrid_subusers table if it doesn't exist
CREATE TABLE IF NOT EXISTS tenant_sendgrid_subusers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    subuser_username VARCHAR(255),
    subuser_api_key_encrypted TEXT,
    subuser_created_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_sendgrid_subusers_tenant UNIQUE (tenant_id)
);

-- Create tenant_domain_authentication table if it doesn't exist
CREATE TABLE IF NOT EXISTS tenant_domain_authentication (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    domain VARCHAR(255) NOT NULL,
    sendgrid_domain_id INTEGER,
    required_dns_records JSONB,
    auth_status VARCHAR(50) DEFAULT 'pending',
    verified_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_domain_auth_unique UNIQUE (tenant_id, domain)
);

-- Create tenant_email_logs table if it doesn't exist
CREATE TABLE IF NOT EXISTS tenant_email_logs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    recipient_email VARCHAR(255),
    subject TEXT,
    from_domain VARCHAR(255),
    status VARCHAR(50),
    cost DECIMAL(10,4) DEFAULT 0.001,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_email_logs_tenant_created ON tenant_email_logs(tenant_id, created_at);
