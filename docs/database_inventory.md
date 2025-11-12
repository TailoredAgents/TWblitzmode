Database Inventory and Production Readiness Map

Overview
- Primary RDBMS: PostgreSQL (Render managed DB). SQLite used only for local/dev fallbacks in a few legacy utilities.
- Migration frameworks: Alembic (authoritative corporate multi‑tenant schema) plus numerous SQL/runner scripts used historically. There is drift between these paths that we must reconcile.
- Drivers: psycopg2, asyncpg. No active SQLAlchemy ORM models; migrations use Alembic operations directly.

Database Modules (connections, adapters, runners)
- `scripts/utils/postgres.py:1` — DSN resolution, lightweight psycopg2 connection context, no‑op migration shim.
- `api/database.py:399` — PostgreSQL adapter (placeholder conversion, RETURNING id append, query logging). Contains bootstrap paths and compat helpers.
- `api/mt_db.py:1` — Postgres‑only “compat” bridge for legacy `get_db()`; connection pool wrapper; runs schema bootstrap via `bootstrap_postgres_schema`.
- `api/db_core.py:1` — Postgres helpers for the company portal (safe table allowlist, slow query telemetry, `get_conn()` context manager).
- `core/db.py:1` — Ensures schema via utils shim; DSN resolution.
- `api/run_migrations.py:1` — Ad‑hoc migration runner creating many tables/indices (historical, duplicates parts of schema).
- `api/sqlite_migrations.py:1` — Local dev migrations for SQLite only.
- `migrations/env.py:1` — Alembic environment; overrides `sqlalchemy.url` from `DATABASE_URL`.
- `alembic.ini:1` — Alembic config (contains hard‑coded DSN; env override exists in env.py but we should sanitize).

Direct DB Consumers (psycopg2 / asyncpg)
- psycopg2: `services/mutuals_service.py:1`, `services/outreach_service.py:1`, `services/executive_lookup_service.py:30` (also asyncpg), `api/mt_db.py:1`, `api/database.py:398`, `api/db_core.py:1`.
- asyncpg: `services/mutuals_orchestrator_service.py:33`, `services/approval_queue_service.py:15`, `services/performance_optimization_service.py:14`, `services/workflow_persistence_service.py:27`, `services/environment_validation_service.py:16`, `api/simple_mgp_routes.py:45`.

Security and Tenancy
- Row Level Security policies
  - Alembic 001 enables RLS using `organization_id = current_setting('app.current_organization_id')::integer` for multi‑tenant tables (`migrations/versions/001_initial_corporate_schema.py:309`).
  - SQL migration sets RLS using `current_setting('app.current_tenant_id', true)::INTEGER` (`migrations/security/001_row_level_security.sql:1`).
  - NOTE: Two different GUC keys in use (`app.current_organization_id` vs `app.current_tenant_id`) and two different tenant key columns across tables (`organization_id` vs `tenant_id`). This is a critical inconsistency to resolve.

Alembic Corporate Multi‑Tenant Schema (authoritative)
- File: `migrations/versions/001_initial_corporate_schema.py:1`
  - organizations (`:30`)
    - id, name, domain, industry, size, status, subscription_tier, created_at, updated_at, metadata
  - team_members (`:44`)
    - id, organization_id (FK→organizations), email, name, role, linkedin_url, is_active, last_login, created_at, updated_at
  - integration_sets (`:64`)
    - id, organization_id (FK), apify_token, apify_actor_id, cufinder_api_key, sendgrid_api_key, openai_api_key, feature_flags, quota_settings, created_at, updated_at
  - cookie_jars (`:83`)
    - id, organization_id (FK), team_member_id (FK→team_members), encrypted_cookies, encryption_key_id, checksum, status, expires_at, created_at, updated_at
  - prospects (`:104`)
    - id, organization_id (FK), company, full_name, role, email, linkedin_url, location, headline, about, company_size, industry, tags, notes, status, source, priority, processed_at, created_at, updated_at
  - connectors (`:132`)
    - id, organization_id (FK), full_name, linkedin_url (unique per org), headline, company, location, profile_picture_url, email, email_status, email_confidence, created_at, updated_at
  - prospect_connectors (`:153`)
    - id, organization_id (FK), prospect_id (FK), connector_id (FK), team_member_id (FK), connection_degree, relationship_strength, ranking_score, rank, reason_codes, mutual_context, shared_experiences, created_at, updated_at
  - email_templates (`:182`)
    - id, organization_id (FK), name, template_type, subject_template, body_template, variables, is_active, created_at, updated_at
  - email_jobs (`:198`, `:200`)
    - id, organization_id (FK), prospect_connector_id (FK), email_subject, email_content, recipient_email, sender_team_member_id (FK), scheduled_at, sent_at, state, tracking_data, error_message, created_at, updated_at
  - approval_requests (`:226`)
    - id, organization_id (FK), email_job_id (FK), approval_type, content_preview, requestor_type, requestor_id, approver_id (FK), status, decision_reason, created_at, approved_at, expires_at
  - job_idempotency (`:252`)
    - id, organization_id (FK), idempotency_key (unique per org), job_type, job_payload, status, result, created_at, completed_at
  - organization_metrics (`:273`)
    - id, organization_id (FK), metric_date, prospects_imported, prospects_processed, connectors_found, emails_scheduled, emails_sent, emails_replied, cost_usd, created_at, updated_at
  - audit_events (`:296`)
    - id, organization_id (FK), actor_type, actor_id, action, target_type, target_id, payload, ip_address, user_agent, correlation_id, timestamp
  - RLS enablement and policies for multi‑tenant tables (`:309`).

- File: `migrations/versions/003_master_game_plan_tables.py:1`
  - companies (`:29`)
    - id, organization_id (FK), name, domain, website, industry, size, employee_count, revenue_range, headquarters, founded_year, description, linkedin_company_url, status, automation_enabled, target_titles, priority, tags, notes, last_processed_at, created_at, updated_at
  - executives (`:66`)
    - id, organization_id (FK), company_id (FK), full_name, first_name, last_name, title, seniority_level, department, email, email_status, email_confidence_score, linkedin_url, linkedin_profile_id, location, headline, about, profile_picture_url, experience_years, previous_companies, education, skills, data_source, verification_status, verification_details, enriched_at, last_verified_at, tags, notes, created_at, updated_at
  - connections (`:113`)
    - id, organization_id (FK), executive_id (FK), team_member_id (FK), connector_full_name, connector_linkedin_url, connector_title, connector_company, connector_location, connector_profile_picture_url, connection_degree, shared_connections_count, mutual_context, relationship_notes, connection_source, discovery_method, last_interaction_date, status, outreach_status, created_at, updated_at
  - connector_rankings (`:151`)
    - id, organization_id (FK), connection_id (FK), executive_id (FK), team_member_id (FK), overall_score, rank, relationship_strength_score, industry_relevance_score, geographic_proximity_score, seniority_match_score, response_likelihood_score, timing_score, scoring_factors, ranking_algorithm_version, confidence_interval, explanation, last_calculated_at, created_at, updated_at
  - company_settings (`:187`)
    - id, organization_id (FK), company_id (FK), automation_enabled, auto_executive_discovery, auto_email_enrichment, auto_mutual_connections, auto_ranking_calculation, max_executives_per_company, max_connections_per_executive, min_connection_score_threshold, target_seniority_levels, target_departments, excluded_titles, geographic_preferences, industry_filters, automation_schedule, notification_settings, email_template_preferences, data_retention_days, privacy_compliance_level, is_active, created_at, updated_at
  - automation_jobs (`:223`)
    - id, organization_id (FK), company_id (FK nullable), job_type, job_status, priority, progress_percentage, items_total, items_processed, items_successful, items_failed, job_parameters, job_results, error_message, error_details, started_at, completed_at, estimated_completion_at, created_by (FK→team_members), created_at, updated_at

- File: `migrations/versions/004_database_normalization.py:1`
  - team_member_connectors (new) (`:22`)
    - id, organization_id (FK), team_member_id (FK), connector_id (FK), relationship_type, source, is_primary, notes, created_at, created_by_id (FK), updated_at, updated_by_id (FK), archived_at, archived_by_id (FK), archived_reason, last_seen_at
  - connectors (alter) (`:64`)
    - Adds: tenant_id, first_name, last_name, current_company, current_title, shared_connections_count, created_by_id, updated_by_id, archived_at, archived_by_id, archived_reason, last_verified_at
  - prospect_connectors (alter) (`:98`)
    - Adds: tenant_id, team_member_connector_id (FK→team_member_connectors), source, status_reason, algorithm_version, confidence_score, last_seen_at, created_by_id, updated_by_id, archived_at, archived_by_id, archived_reason
  - Backfills and index additions; cleans temporary server defaults (`:240`+).

Legacy/Ad‑hoc Schema (runner + SQL migrations)
- `api/run_migrations.py:1` creates/ensures:
  - tenant_settings (`:54`)
    - id, tenant_id, setting_key, setting_value, encrypted, created_at, updated_at
  - job_idempotency (`:72`) — single‑tenant style (tenant_id) version
    - id, tenant_id, idempotency_key, prospect_id, job_type, status, run_id, result_data, created_at, updated_at, completed_at
  - job_runs (`:99`)
    - id, tenant_id, user_id, job_type, status, external_id, prospect_id, result_count, error_message, input_data, started_at, completed_at, webhook_received_at, created_at, updated_at, provider, cache_expires_at, idempotency_key
  - provider_health (`:127`) — provider cooldowns and error telemetry
  - outreach_queue (`:165`) — pending approvals and sending
  - auth_sessions (`:210`) — refresh token sessions (tenant, user, session_id, token hash, expiry, revoked, etc.)
  - daily_quotas (`:268`) — per‑tenant daily usage
  - prospects (`:293`) — single‑tenant style version (tenant_id, minimal columns)
  - contacts (`:328`)
  - prospect_mutuals (`:369`) — mutual connectors table used by services
  - users (`:411`) — single‑tenant style (tenant_id + email unique constraints)
  - cufinder_cache (`:447`)
  - dev_mfa_tokens (`:803`), dev_sessions (`:822`), billing_plans (`:844`)
  - Additional DDL: unique constraints, indices, triggers, backfills.

- SQL migration files under `migrations/` (selected highlights)
  - `migrations/create_critical_missing_tables.sql:1`
    - tenants, feature_flags, feature_flag_history, feature_evaluations, api_usage, webhook_records, webhook_delivery_attempts, linkedin_campaigns, linkedin_campaign_messages, linkedin_metrics, linkedin_daily_usage, ai_workflows, ai_assistants, managed_accounts
  - `migrations/postgresql_add_missing_schema.sql:1`
    - linkedin_sessions, password_reset_tokens, introductions, prospect_network_matches, team_members, team_networks, provider_instances, profile_warmup_queue
  - `migrations/create_enterprise_workflow_persistence_fixed.sql:1`
    - event_store, process_snapshots, saga_state, outbox_events, workflow_states, workflow_queues, workflow_queue_metadata; views: active_workflows, workflow_queue_summary
  - `migrations/add_agent_events_table.sql:1`
    - agent_events (actionable suggestions, metadata, timestamps)
  - `migrations/create_user_preferences_table.sql:1`
    - user_preferences, user_activity_log, user_saved_searches, user_bookmarks
  - `migrations/019_fix_user_preferences_schema.sql:1` — preferences JSONB column + unique constraint update
  - `migrations/012_add_status_columns_prospect_mutuals.sql:1` — status/last_action/ranking/provider on prospect_mutuals + indexes
  - `migrations/security/001_row_level_security.sql:1` — RLS enablement across tables using `tenant_id` GUC
  - Plus numerous targeted fixes/indexes: see `add_performance_indexes.sql`, `add_existing_schema_indexes.sql`, `add_linkedin_handle.sql`, `fix_approval_requests_schema.sql`, `extend_approval_queue_for_mgp.sql`, `018_company_portal_schema.sql`, `020_wave3_enhancements.sql`.

Compatibility Views
- `migrations/create_compatibility_views.sql:1`
  - accounts → managed_accounts, audit_logs → audit_events, account_users → team_members, account_features → feature_flags, dashboards → dashboard_configurations.

Key Tables Used By Agent Operations (with columns)
- connectors (corporate) — `migrations/versions/001_initial_corporate_schema.py:132` (+ altered in `004_database_normalization.py`)
  - id, organization_id, full_name, first_name, last_name, linkedin_url, headline, company, current_company, current_title, location, profile_picture_url, email, email_status, email_confidence, shared_connections_count, created_by_id, updated_by_id, archived_at, archived_by_id, archived_reason, last_verified_at, created_at, updated_at
- prospects (corporate) — `migrations/versions/001_initial_corporate_schema.py:104`
  - id, organization_id, company, full_name, role, email, linkedin_url, location, headline, about, company_size, industry, tags, notes, status, source, priority, processed_at, created_at, updated_at
- prospect_connectors — `migrations/versions/001_initial_corporate_schema.py:153` (+ altered in `004_database_normalization.py`)
  - id, organization_id, tenant_id, prospect_id, connector_id, team_member_id, team_member_connector_id, connection_degree, relationship_strength, ranking_score, rank, reason_codes, mutual_context, shared_experiences, source, status_reason, algorithm_version, confidence_score, last_seen_at, created_by_id, updated_by_id, archived_at, archived_by_id, archived_reason, created_at, updated_at
- team_member_connectors — `migrations/versions/004_database_normalization.py:22`
  - id, organization_id, team_member_id, connector_id, relationship_type, source, is_primary, notes, created_at, created_by_id, updated_at, updated_by_id, archived_at, archived_by_id, archived_reason, last_seen_at
- email_jobs — `migrations/versions/001_initial_corporate_schema.py:198`
  - id, organization_id, prospect_connector_id, email_subject, email_content, recipient_email, sender_team_member_id, scheduled_at, sent_at, state, tracking_data, error_message, created_at, updated_at
- approval_requests — `migrations/versions/001_initial_corporate_schema.py:226`
  - id, organization_id, email_job_id, approval_type, content_preview, requestor_type, requestor_id, approver_id, status, decision_reason, created_at, approved_at, expires_at
- job_idempotency (corporate) — `migrations/versions/001_initial_corporate_schema.py:252`
  - id, organization_id, idempotency_key, job_type, job_payload, status, result, created_at, completed_at
- audit_events — `migrations/versions/001_initial_corporate_schema.py:296`
  - id, organization_id, actor_type, actor_id, action, target_type, target_id, payload, ip_address, user_agent, correlation_id, timestamp
- prospect_mutuals (legacy single‑tenant) — `api/run_migrations.py:369`, plus status columns in `:585` and `migrations/012_add_status_columns_prospect_mutuals.sql:1`
  - id, tenant_id, prospect_id, mutual_full_name, mutual_linkedin_url, mutual_headline, mutual_company, network_distance, scraped_via, scraped_at, run_id, status, ranking_score, last_action_at, introduction_id, provider, created_at, updated_at

Config and DSN Usage (Production Risks)
- Hard‑coded DSNs present and must be removed:
  - `alembic.ini:56` (hard‑coded Render DSN)
  - `api/migration_trigger.py:9`, `api/simple_migration.py:19` (sets `DATABASE_URL` to a Render DSN)
  - Multiple services default to Render DSN when env var is missing (e.g., `services/master_game_plan_orchestrator.py:119`, `services/database_performance_service.py:67`, `services/workflow_persistence_service.py:919`).
- Env resolution is otherwise standardised via `scripts/utils/postgres.resolve_required_dsn()` and `core/settings.py:44`.

Drift, Collisions, and Gaps (must address for production)
- Dual tenancy keys and RLS
  - Mix of `organization_id` (corporate Alembic) and `tenant_id` (legacy). RLS policies use both `app.current_organization_id` and `app.current_tenant_id`. This mismatch will cause incorrect isolation or query failures.
- Duplicate table names with different shapes
  - `prospects` and `job_idempotency` exist in both corporate and single‑tenant forms with different columns.
- Multiple migration paths
  - Alembic vs `api/run_migrations.py` vs `api/database.POSTGRES_SCHEMA` vs ad‑hoc SQL files. This increases drift and non‑determinism. Choose Alembic as source of truth and port required tables as Alembic revisions.
- Inconsistent timestamp types
  - TIMESTAMP (no TZ) vs TIMESTAMPTZ across migrations. Standardise to TIMESTAMPTZ for audit/temporal data.
- Absolute paths in migration helpers
  - `migrations/execute_mgp_migration.py` references an absolute path to another repo; remove/replace with local Alembic flow.
- Auth/session and users/team_members overlap
  - Corporate schema has team_members linked to organizations; legacy has `users` with `tenant_id`. Define authoritative user model and map/harden join semantics.

Recommended Next Actions
- Unify tenancy: pick `organization_id` plus `app.current_organization_id` or `tenant_id` plus `app.current_tenant_id`, then refactor migrations and code accordingly. Provide a compatibility view for the other term temporarily.
- Make Alembic the single migration mechanism. Fold essential tables from `api/run_migrations.py` and SQL files into Alembic revisions (auth_sessions, daily_quotas, prospect_mutuals, provider_health, outreach_queue, users, cufinder_cache, etc.).
- Remove all hard‑coded DSNs; require `DATABASE_URL` everywhere. Sanitise `alembic.ini` (keep blank; rely on env via `migrations/env.py`).
- Standardise temporal columns to TIMESTAMPTZ and ensure `updated_at` triggers uniformly exist. Align default values and constraints.
- Finalise RLS setup in one place; ensure policies align to the chosen tenant key and are enabled/forced on all multi‑tenant tables.
- Add migrations to backfill or adapt data to the unified schema (e.g., move single‑tenant `prospects` → corporate `prospects` with organization mapping).
- Add startup health checks and connection pool settings (timeouts, max connections) and set `statement_timeout` at the DB level if needed.

Notes
- This inventory lists every table, module, and primary schema source in the repo with direct file references for full column/type details. For large SQL files defining many feature tables (developer portal, workflow persistence, analytics), see the referenced files to drill into every column/type.
