-- User Preferences Table
-- Per-user customization and settings

CREATE TABLE IF NOT EXISTS user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL,

    -- UI Preferences
    theme VARCHAR(20) DEFAULT 'light',
    sidebar_collapsed BOOLEAN DEFAULT FALSE,
    dashboard_layout VARCHAR(50) DEFAULT 'default',
    default_view VARCHAR(50) DEFAULT 'dashboard',

    -- Notification Preferences
    email_notifications BOOLEAN DEFAULT TRUE,
    email_digest_frequency VARCHAR(20) DEFAULT 'daily',
    browser_notifications BOOLEAN DEFAULT TRUE,
    notification_sound BOOLEAN DEFAULT TRUE,
    notification_types JSONB DEFAULT '{"workflow": true, "approval": true, "system": true}',

    -- Workflow Preferences
    default_workflow_priority VARCHAR(20) DEFAULT 'normal',
    auto_approve_low_risk BOOLEAN DEFAULT FALSE,
    preferred_connectors JSONB DEFAULT '[]',

    -- Communication Preferences
    preferred_contact_method VARCHAR(50) DEFAULT 'email',
    signature TEXT,
    email_from_name VARCHAR(255),

    -- Display Preferences
    items_per_page INTEGER DEFAULT 25,
    date_format VARCHAR(20) DEFAULT 'YYYY-MM-DD',
    time_format VARCHAR(20) DEFAULT '12h',
    timezone VARCHAR(50) DEFAULT 'UTC',
    language VARCHAR(10) DEFAULT 'en',

    -- Privacy Settings
    profile_visibility VARCHAR(20) DEFAULT 'team',
    activity_visibility VARCHAR(20) DEFAULT 'team',
    share_analytics BOOLEAN DEFAULT TRUE,

    -- Advanced Settings
    api_rate_limit INTEGER DEFAULT 100,
    webhook_url TEXT,
    custom_fields JSONB DEFAULT '{}',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_user_preferences_user UNIQUE (user_id)
);

CREATE INDEX idx_user_preferences_user ON user_preferences(user_id);
CREATE INDEX idx_user_preferences_tenant ON user_preferences(tenant_id);

-- User Activity Log: Track user actions for analytics
CREATE TABLE IF NOT EXISTS user_activity_log (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL,
    activity_type VARCHAR(100) NOT NULL,
    activity_data JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    session_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_user_activity_log_user ON user_activity_log(user_id);
CREATE INDEX idx_user_activity_log_tenant ON user_activity_log(tenant_id);
CREATE INDEX idx_user_activity_log_type ON user_activity_log(activity_type);
CREATE INDEX idx_user_activity_log_created ON user_activity_log(created_at DESC);
CREATE INDEX idx_user_activity_log_session ON user_activity_log(session_id);

-- User Saved Searches: Save frequently used searches
CREATE TABLE IF NOT EXISTS user_saved_searches (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL,
    search_name VARCHAR(255) NOT NULL,
    search_type VARCHAR(50) NOT NULL,
    search_criteria JSONB NOT NULL,
    is_default BOOLEAN DEFAULT FALSE,
    use_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_user_saved_searches_user ON user_saved_searches(user_id);
CREATE INDEX idx_user_saved_searches_tenant ON user_saved_searches(tenant_id);
CREATE INDEX idx_user_saved_searches_type ON user_saved_searches(search_type);

-- User Bookmarks: Bookmark important items
CREATE TABLE IF NOT EXISTS user_bookmarks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL,
    bookmark_type VARCHAR(50) NOT NULL,
    entity_id INTEGER NOT NULL,
    notes TEXT,
    tags JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_bookmarks UNIQUE (user_id, bookmark_type, entity_id)
);

CREATE INDEX idx_user_bookmarks_user ON user_bookmarks(user_id);
CREATE INDEX idx_user_bookmarks_tenant ON user_bookmarks(tenant_id);
CREATE INDEX idx_user_bookmarks_type_entity ON user_bookmarks(bookmark_type, entity_id);

-- Comments
COMMENT ON TABLE user_preferences IS 'Per-user customization and settings';
COMMENT ON TABLE user_activity_log IS 'Audit trail of all user actions';
COMMENT ON TABLE user_saved_searches IS 'User-saved search queries for quick access';
COMMENT ON TABLE user_bookmarks IS 'User bookmarks for prospects, campaigns, etc.';
