# Schema Blitz Plan (Single-Tenant Tie-in)

Strategy

- Preserve functional tables but simplify to a single tenant/organization. Keep multi-tenant columns for compatibility but constrain them to constants (tenant_id=1, organization_id=1).
- Provide idempotent SQL to create the required tables/columns/indexes if missing. Seed defaults on startup.

Core Entities (Required)

- tenants
  - `id SERIAL PRIMARY KEY`, `name TEXT`, `status TEXT`, `created_at TIMESTAMP DEFAULT now()`
- organizations
  - `id SERIAL PRIMARY KEY`, `tenant_id INT REFERENCES tenants(id)`, `name TEXT`, `slug TEXT UNIQUE`, `status TEXT`, timestamps.
- users
  - `id SERIAL PRIMARY KEY`, `tenant_id INT REFERENCES tenants(id)`, `email CITEXT UNIQUE`, `password_hash TEXT NULL`, `role TEXT DEFAULT 'admin'`, `status TEXT DEFAULT 'active'`, `is_active BOOLEAN DEFAULT TRUE`, timestamps.
- team_members
  - `id SERIAL PRIMARY KEY`, `organization_id INT REFERENCES organizations(id)`, `user_id INT REFERENCES users(id)`, `email CITEXT`, `first_name TEXT`, `last_name TEXT`, `role TEXT DEFAULT 'user'`, `status TEXT DEFAULT 'active'`, `last_login_at TIMESTAMP NULL`, `cookie_status TEXT DEFAULT 'missing'`, timestamps, `UNIQUE (organization_id, email)`.
- linkedin_sessions
  - `id SERIAL PRIMARY KEY`, `tenant_id INT`, `user_id INT`, `team_member_id INT`, `li_at_encrypted BYTEA`, `jsessionid_encrypted BYTEA NULL`, `label TEXT`, `user_agent TEXT`, `is_active BOOLEAN DEFAULT TRUE`, `status TEXT DEFAULT 'active'`, `last_verified_at TIMESTAMP NULL`, `full_name TEXT NULL`, `username TEXT NULL`, timestamps; indexes on `(user_id, is_active)`.
- prospects
  - `id SERIAL PRIMARY KEY`, `organization_id INT`, `company TEXT`, `person_name TEXT`, `title TEXT NULL`, `linkedin_url TEXT NULL`, `status TEXT DEFAULT 'new'`, timestamps.
- connectors
  - `id SERIAL PRIMARY KEY`, `organization_id INT`, `user_id INT NULL`, `linkedin_url TEXT NULL`, `strength DOUBLE PRECISION NULL`, `last_seen_at TIMESTAMP NULL`, `email TEXT NULL`, `email_status TEXT DEFAULT 'not_checked'`, `email_confidence DOUBLE PRECISION NULL`.
- prospect_connectors
  - `prospect_id INT REFERENCES prospects(id)`, `connector_id INT REFERENCES connectors(id)`, `relationship TEXT NULL`, `PRIMARY KEY (prospect_id, connector_id)`.
- prospect_mutuals
  - `id SERIAL PRIMARY KEY`, `prospect_id INT`, `connector_user_id INT NULL`, `provider TEXT`, `status TEXT DEFAULT 'new'`, `ranking_score DOUBLE PRECISION NULL`, `last_action_at TIMESTAMP NULL`, `introduction_id INT NULL`,
  - `mutual_full_name TEXT NULL`, `mutual_linkedin_url TEXT NULL`, `mutual_company TEXT NULL`, `mutual_headline TEXT NULL`, `mutual_email TEXT NULL`, `mutual_email_confidence DOUBLE PRECISION NULL`, `email_enriched_at TIMESTAMP NULL`, `contact_id INT NULL`; indexes by `prospect_id`.
- cufinder_cache
  - `id SERIAL PRIMARY KEY`, `tenant_id INT`, `cache_key TEXT`, `email TEXT NULL`, `confidence DOUBLE PRECISION NULL`, `source TEXT DEFAULT 'cufinder'`, `cached_at TIMESTAMP`, `expires_at TIMESTAMP`, `UNIQUE (tenant_id, cache_key)`.
- audit_events, agent_events (JSONB payloads recommended)
  - minimal columns: `id SERIAL`, `created_at TIMESTAMP DEFAULT now()`, `tenant_id INT`, `actor_id INT NULL`, `event_type TEXT`, `payload JSONB`.

Idempotent SQL Outline (PostgreSQL)

- Create tables IF NOT EXISTS in the order above; add missing columns IF NOT EXISTS.
- Create indexes:
  - `team_members (organization_id, email) UNIQUE`
  - `linkedin_sessions (user_id, is_active)`
  - `prospect_mutuals (prospect_id)`
  - `cufinder_cache (tenant_id, cache_key) UNIQUE`
- Use extensions if available: `CREATE EXTENSION IF NOT EXISTS citext;` for case-insensitive email.

Startup Seed (Single Tenant)

- Ensure rows:
  - tenants: id=1, name='default'
  - organizations: id=1, tenant_id=1, name='default', slug='default'
  - users: id=1, tenant_id=1, email='admin@local', role='admin', is_active=true
- Foreign-key alignment check and fast-fail on mismatch.

Simplifications (Single Tenant)

- Treat `tenant_id` and `organization_id` as constants (1) at write-time.
- Do not create `auth_sessions` or password reset tables.
- Keep `password_hash` present but unused.

Import/Backfill Plan

- Export from current DB: users, team_members, linkedin_sessions, prospects, prospect_mutuals, connectors, prospect_connectors.
- Map all tenant_id/organization_id values to 1; preserve unique emails and LinkedIn URLs; re-index sequences.
- Validate row counts; run uniqueness checks on (organization_id,email) and LinkedIn URL fields; report conflicts.

Verification Checklist

- Required tables exist and contain baseline rows.
- `team_members.cookie_status` present and reflects state transitions.
- `linkedin_sessions` includes username/full_name/is_active/last_verified_at when available.
- Provider invariants pass CI; SendGrid webhook verified.

Idempotent SQL Templates (Sketch)

```sql
-- Enable citext if available
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS tenants (
  id SERIAL PRIMARY KEY,
  name TEXT,
  status TEXT,
  created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS organizations (
  id SERIAL PRIMARY KEY,
  tenant_id INT REFERENCES tenants(id),
  name TEXT,
  slug TEXT UNIQUE,
  status TEXT,
  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP DEFAULT now()
);

-- Repeat CREATE TABLE IF NOT EXISTS for users, team_members, linkedin_sessions, prospects,
-- connectors, prospect_connectors, prospect_mutuals, cufinder_cache, audit_events, agent_events.

-- Add columns IF NOT EXISTS for cookie_status, username, full_name, last_verified_at, etc.

-- Indexes
CREATE UNIQUE INDEX IF NOT EXISTS team_members_org_email_unique
  ON team_members (organization_id, email);
CREATE INDEX IF NOT EXISTS linkedin_sessions_user_active
  ON linkedin_sessions (user_id, is_active);
CREATE INDEX IF NOT EXISTS prospect_mutuals_by_prospect
  ON prospect_mutuals (prospect_id);
CREATE UNIQUE INDEX IF NOT EXISTS cufinder_cache_key_tenant
  ON cufinder_cache (tenant_id, cache_key);
```

Startup Seed SQL

```sql
INSERT INTO tenants (id, name, status)
  VALUES (1, 'default', 'active')
  ON CONFLICT (id) DO NOTHING;

INSERT INTO organizations (id, tenant_id, name, slug, status)
  VALUES (1, 1, 'default', 'default', 'active')
  ON CONFLICT (id) DO NOTHING;

INSERT INTO users (id, tenant_id, email, role, status, is_active)
  VALUES (1, 1, 'admin@local', 'admin', 'active', TRUE)
  ON CONFLICT (id) DO NOTHING;
```

Sequence Reset (Post-Import)

```sql
SELECT setval(pg_get_serial_sequence('users','id'), COALESCE((SELECT MAX(id) FROM users), 1));
-- repeat for other tables with SERIAL PKs
```

Validation Queries

```sql
-- Core presence
SELECT COUNT(*) FROM tenants;  -- expect >= 1
SELECT COUNT(*) FROM organizations; -- expect >= 1
-- Cookie readiness
SELECT column_name FROM information_schema.columns
 WHERE table_name='team_members' AND column_name='cookie_status';
-- Mutuals health
SELECT COUNT(*) FROM prospect_mutuals;
```

Backup & Rollback Note

- Before import/backfill, `pg_dump` the source schema/data for the involved tables.
- Keep a rollback script that truncates only the newly created tables in case of a failed cutover.

