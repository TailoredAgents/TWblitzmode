-- PostgreSQL Migration: Add missing schema components for Setup tab functionality
-- Run this on the external PostgreSQL database

-- 1. Add missing columns to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_email TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS company_domain TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TEXT;

-- 2. Create linkedin_sessions table (completely missing)
CREATE TABLE IF NOT EXISTS linkedin_sessions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER,
    label TEXT,
    li_at_encrypted TEXT NOT NULL,
    jsessionid_encrypted TEXT,
    user_agent TEXT,
    proxy_url TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_verified_at TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 3. Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_linkedin_sessions_tenant_id ON linkedin_sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_sessions_user_id ON linkedin_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_sessions_active ON linkedin_sessions(is_active);

-- 4. Create password reset tokens table for forgot password functionality
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 5. Create index for password reset tokens
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_token ON password_reset_tokens(token);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id ON password_reset_tokens(user_id);

-- 6. Add missing tables that exist in SQLite but not PostgreSQL
CREATE TABLE IF NOT EXISTS introductions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    prospect_id INTEGER,
    connector_id INTEGER,
    status TEXT DEFAULT 'pending',
    message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

CREATE TABLE IF NOT EXISTS prospect_network_matches (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    prospect_id INTEGER,
    connector_id INTEGER,
    connection_strength INTEGER,
    mutual_connections INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

CREATE TABLE IF NOT EXISTS team_members (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER,
    name TEXT,
    linkedin_url TEXT,
    position TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS team_networks (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    team_member_id INTEGER,
    network_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (team_member_id) REFERENCES team_members(id)
);

CREATE TABLE IF NOT EXISTS provider_instances (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    instance_data JSONB,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

CREATE TABLE IF NOT EXISTS profile_warmup_queue (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    linkedin_session_id INTEGER,
    target_profile_url TEXT,
    status TEXT DEFAULT 'pending',
    scheduled_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (linkedin_session_id) REFERENCES linkedin_sessions(id)
);

-- 7. Update user_integrations to match SQLite structure
ALTER TABLE user_integrations ALTER COLUMN user_id SET NOT NULL;

COMMENT ON TABLE linkedin_sessions IS 'Stores user-specific LinkedIn authentication cookies';
COMMENT ON COLUMN linkedin_sessions.user_id IS 'Links LinkedIn session to specific user for user-specific cookie management';
COMMENT ON COLUMN users.sender_email IS 'Default email address for user when sending emails';
COMMENT ON COLUMN users.sender_name IS 'Default sender name for user when sending emails';