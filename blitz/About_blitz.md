# Blitz Carve-Out Overview

Purpose

- Create a clean, single-tenant Link repo by extracting only the agent’s functional core (chat, tools, cookies, prospects/mutuals, email) and frontends that operate it. Eliminate complex SaaS-era auth and dev-portal baggage that caused logout loops and breaks.

Target Repository

- New project repo (Blitz): https://github.com/TailoredAgents/TWblitzmode.git
- Do not run extraction until approved; this doc and the /blitz scripts assume that URL for the final push.

Guardrails (Non‑Negotiable)

- Security is minimal by design: a universal gate password only (“Tallwave”) at the Access screen. No per-user password auth; no JWT/refresh flows are carried over.
- Saswave (Apify) is the primary mutuals provider; PhantomBuster is secondary and requires explicit user approval per run.
- SendGrid is the only email delivery path for introductions; webhook verification remains enabled.
- Model lock to gpt-4.1 for reasoning. Startup fails if PRIMARY_MODEL ≠ gpt-4.1.

What We Transfer

- Agent brain + tools: master chat agent, tool registry, knowledge base, orchestrators, provider adapters (Apify/CUFinder/PhantomBuster), SendGrid email service.
- UI: Link Chat, Prospects, Cookie Management, minimal Admin/Team (roster list only; no invites/keys), Communication Hub (agents/approvals/events) if useful.
- DB schema/migrations: single-tenant compatible tables for users, team_members, linkedin_sessions, prospects, prospect_mutuals, connectors, prospect_connectors, cufinder_cache, audit/agent events. Idempotent creation scripts.

What We Do Not Transfer

- Any dev portal, seat invites, registration keys, JWT/session auth, password resets, Stripe/billing, or enterprise MGP modules not invoked by Link.

Target Architecture (Single Tenant)

- Frontend: Next.js (existing component set), color scheme unchanged, pages: Access (gate), Roster, Link Chat, Prospects, Cookie Management.
- Backend: FastAPI, Link agent core, minimal identity stub (header/seeded admin) with no auth; provisioning endpoint to add team members; provider orchestrations.
- Data: PostgreSQL single-tenant schema; default tenant/org/admin seeded on startup.
- Observability: structured logs + audit events with correlation IDs; optional WebSocket events.

E2E User Journey (Identical in Spirit to Current)

1) Access gate: user clicks Access and enters “Tallwave”.
2) Roster: user sees public roster and clicks “+ Team member” to add Name + Email (no passwords).
3) Cookie setup: user uploads LinkedIn li_at (+ optional JSESSIONID) in Cookie Management; system validates and confirms account/username.
4) Prospecting: user asks Link to search executives, Link runs web search → optimizes CUFinder lookups → resolves LinkedIn URLs → saves prospects.
5) Mutuals: user runs Apify Saswave mutuals; Link ranks connectors and maps mutuals to teammate and prospect.
6) Optional enrichment: user approves PhantomBuster enrichment for additional data (secondary only).
7) Email: user reviews and approves introduction; Link sends via SendGrid and records message_id + webhook events.

Execution Waves (for the transfer window)

- Wave A: Inventory + allowlist. Finalize the exact files for extraction (backend/services/integrations/core + frontend components) and a minimal env contract.
- Wave B: New repo bootstrap. Next.js app + FastAPI service + Postgres schema migrations + model/policy gates.
- Wave C: Extract + rewire. Copy files, replace auth deps with identity stub, wire endpoints, set UI routes, and fix imports.
- Wave D: Smoke + parity. Run staging with synthetic data, validate E2E flows above, ensure provider policy CI tests pass.
- Wave E: Cutover. Switch to new service; monitor audits/logs; decommission legacy modules.

Environments & Secrets

- Backend: OPENAI_API_KEY, PRIMARY_MODEL=gpt-4.1, APIFY_TOKEN, PHANTOMBUSTER_API_KEY (optional/secondary), CUFINDER_API_KEY, SENDGRID_API_KEY, SENDGRID_VERIFIED_SENDER, DATABASE_URL, ENC_KEY, SECRET_KEY (app-level), webhook secrets.
- Frontend: NEXT_PUBLIC_API_URL, NEXT_PUBLIC_WEBSOCKET_URL, NEXT_PUBLIC_WEBSOCKET_PATH, NEXT_PUBLIC_MASTER_LOGIN_PASSWORD=Tallwave, NEXT_PUBLIC_SITE_URL.

Risk Notes

- Minimal security is deliberate; all destructive actions require explicit in-UI confirmation and are fully audited.
- Keep provider invariants enforced in CI to prevent policy drift.

Accelerators & Additions (Speed, Efficiency, Quality)

- Approvals mini-panel (UI): quick view/approve PhantomBuster and email actions directly from Communication Hub. Speeds decisions and maintains audit trails.
- Provider health widget: small R/Y/G cards for Apify, CUFinder, SendGrid status (key present, last success, error cooldown). Prevents blind debugging.
- Dry-run toggles: PhantomBuster and Corporate Connect “preview” mode to show what would run without external calls; safe by default in staging.
- Audit viewer: table of recent actions with correlation_id, tool, provider, status, duration, and message_id for emails.
- One-click extraction scripts: bundle the allowlist into `scripts/blitz_extract.sh` (filter-repo or archive) and `scripts/blitz_import.sh` for new repo init.
- Docker Compose: `docker-compose.yml` for Postgres + API + Frontend; default envs pre-wired for local smoke (no mocks).
- Makefile targets: `make bootstrap migrate seed run fe be test lint typecheck smoke` to standardize workflows.
- OpenAPI spec: `openapi.yaml` checked into the new repo; generate a typed API client for the frontend (`pnpm gen:api`).
- Seed data pack: a small `seed.json` to populate 2–3 prospects for instant UI verification (real provider runs still required for mutuals/email).
- CI policy gates: grep tests to block any auth/JWT imports, provider policy violations, and non-SendGrid email paths.
- Startup sanity script: `python scripts/startup_check.py` prints model, provider keys present/missing, DB connectivity, and schema deltas.

Render Cutover Speed Plan (48-hour)

- T0–T8h: Bootstrap new repo, apply schema, seed defaults, wire env on Render (API + Frontend), deploy “hello health”.
- T8–T16h: Wire provisioning and cookie routes; validate LinkedIn cookie verification live.
- T16–T24h: Connect Saswave mutuals (1‑prospect test), confirm connectors in Prospects.
- T24–T36h: Enable SendGrid; ship first intro email to test inbox; verify webhook and audits.
- T36–T48h: Harden copy, approvals panel, provider health widget; finalize CI policy tests; client demo.

CodeX Transfer Checklist (Condensed)

1) Confirm allowlist paths and finalize exclusions (no auth, no invites, no dev portal).
2) Run `scripts/blitz_extract.sh` to produce `link-core.bundle` and `link-core.tar`.
3) New repo: initialize, apply `scripts/blitz_import.sh`, commit baseline; add envs to secrets manager.
4) `make migrate seed run` then `make smoke` to validate Access → Roster → Cookies → Mutuals (mock) → Email (mock).
5) Enable real providers one by one; verify audits and health widgets reflect live status.
6) Cutover with a short canary window; monitor error rate and audit anomalies; keep rollback plan ready.
