-- Company Portal schema upgrade
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    domain TEXT,
    billing_details TEXT,
    subscription_tier TEXT DEFAULT 'starter',
    max_team_members INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    stripe_product_id TEXT,
    stripe_price_id TEXT,
    subscription_status TEXT,
    billing_status TEXT,
    trial_ends_at DATETIME,
    current_period_end DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    email TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    role TEXT DEFAULT 'member',
    status TEXT DEFAULT 'active',
    password_hash TEXT,
    last_login_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organization_id, email)
);

CREATE TABLE IF NOT EXISTS registration_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    lookup_hash TEXT NOT NULL UNIQUE,
    key_hash TEXT NOT NULL,
    key_salt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unused',
    assigned_team_member_id INTEGER REFERENCES team_members(id) ON DELETE SET NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    used_at DATETIME,
    released_at DATETIME,
    expires_at DATETIME,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_modified_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS cookie_jars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    encrypted_payload TEXT NOT NULL,
    encryption_salt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_validated_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organization_id, user_id)
);

CREATE TABLE IF NOT EXISTS billing_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    stripe_event_id TEXT,
    payload TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_slug ON organizations(slug);
CREATE INDEX IF NOT EXISTS idx_organizations_status ON organizations(status);
CREATE INDEX IF NOT EXISTS idx_organizations_stripe_customer ON organizations(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_organizations_subscription_status ON organizations(subscription_status);
CREATE INDEX IF NOT EXISTS idx_team_members_org_status ON team_members(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_registration_keys_org_status ON registration_keys(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_registration_keys_lookup ON registration_keys(lookup_hash);
CREATE INDEX IF NOT EXISTS idx_cookie_jars_org_status ON cookie_jars(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_billing_events_org_created_at ON billing_events(organization_id, created_at);

ALTER TABLE users ADD COLUMN IF NOT EXISTS accepted_terms_at DATETIME;
ALTER TABLE team_members ADD COLUMN IF NOT EXISTS accepted_terms_at DATETIME;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS stripe_product_id TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS stripe_price_id TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS subscription_status TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS billing_status TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS trial_ends_at DATETIME;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS current_period_end DATETIME;

COMMIT;
