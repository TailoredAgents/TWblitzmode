# Codex Execution Guide — Blitz Migration (TWblitzmode)

Audience

- This guide instructs Codex (coding agent) to execute the Blitz carve‑out and stand‑up of the new single‑tenant Link project in https://github.com/TailoredAgents/TWblitzmode.git.
- Follow steps exactly; request explicit approval before any destructive action or cross‑repo file transfer.

Source and Target

- Source repo (legacy): the current project containing /blitz assets and Link code.
- Target repo (Blitz): https://github.com/TailoredAgents/TWblitzmode.git (empty or minimal scaffold).

Hard Rules

- Do NOT run extraction without explicit user approval.
- Do NOT copy secrets into VCS. Configure secrets in Render or local env only.
- Enforce provider policies: Saswave/Apify = primary, PhantomBuster = secondary with approval, SendGrid‑only email.

Prerequisites

- Linux/macOS shell with git, Python 3.11, Node 18+, Docker (optional), ripgrep.
- Provider secrets available (not in Git): OPENAI_API_KEY, APIFY_TOKEN, CUFINDER_API_KEY, SENDGRID_API_KEY, SENDGRID_VERIFIED_SENDER, ENC_KEY, SECRET_KEY.

Plan Overview (what Codex will do)

1) Prepare artifacts (on source repo) — wait for approval
2) Initialize the new repo and import artifacts
3) Wire logging middleware + health/preflight routes
4) Apply schema/migrations and seed default tenant/org/admin
5) Configure Render services + secrets; deploy API + Frontend
6) Run startup sanity and provider preflight checks
7) Execute E2E smoke (real providers)
8) Enable CI policy gates; finalize docs

Key Reference Files (source repo)

- Blitz overview: blitz/About_blitz.md:1
- Frontend plan: blitz/frontend_blitz.md:1
- Backend plan: blitz/Backend_and_Link_tie_in.md:1
- Schema plan: blitz/Schema_tie_in.md:1
- Validation checklist: blitz/validation_checklist.md:1
- Logging plan: blitz/logging_observability.md:1
- Render blueprint: blitz/render_blueprint.yaml:1
- Extraction/import scripts: blitz/scripts/blitz_extract.sh:1, blitz/scripts/blitz_import.sh:1
- Startup sanity and preflight: blitz/scripts/startup_check.py:1, blitz/scripts/provider_preflight.py:1
- Health routes + logging middleware: blitz/examples/api/health_routes.py:1, blitz/examples/api/logging_middleware.py:1
- App startup integration: blitz/examples/api/app_startup_integration.md:1
- CI workflow template: blitz/examples/ci/ci.yml:1

Step‑by‑Step

A) Prepare artifacts (Source) — approval required

- Ask for approval to generate transfer artifacts. On approval, run:
  - `bash blitz/scripts/blitz_extract.sh`
  - Result: `.blitz-out/link-core.tar` (no history) and `.blitz-out/link-core.bundle` (history‑preserving)
- Confirm no secrets are included in Git; do not push artifacts to public remotes.

B) Initialize target repo (TWblitzmode)

- Clone/create the target repo (empty main branch):
  - `git clone https://github.com/TailoredAgents/TWblitzmode.git`
  - `cd TWblitzmode`
- Import artifacts (choose one):
  - History‑preserving: `../<source>/.blitz-out/link-core.bundle` via `git pull ../.blitz-out/link-core.bundle`
  - No history: extract `../<source>/.blitz-out/link-core.tar` and commit
- Add the following support assets if not present:
  - OpenAPI: copy `blitz/openapi.yaml`
  - Logging middleware: `blitz/examples/api/logging_middleware.py`
  - Health routes: `blitz/examples/api/health_routes.py`
  - Render blueprint: `blitz/render_blueprint.yaml`
  - Makefile and Compose: `blitz/Makefile.example`, `blitz/docker-compose.yml`
  - CI: `blitz/examples/ci/ci.yml`
  - Provider preflight + startup check: `blitz/scripts/provider_preflight.py`, `blitz/scripts/startup_check.py`

C) Wire logging + health endpoints

- Follow: blitz/examples/api/app_startup_integration.md:1
  - Import and register `logging_middleware` and `health_router` in `api/main.py`
  - Ensure `SERVICE_NAME`, `SERVICE_VERSION` envs are set; `LOG_FORMAT=json` in production
- SendGrid and Apify correlation (when wiring providers):
  - Use `custom_args.corr_id` (see blitz/examples/api/sendgrid_correlation_example.py:1)
  - Include `meta.corr_id` in Apify inputs (see blitz/examples/api/apify_input_example.json:1)

D) Schema & migrations

- Use instructions in blitz/Schema_tie_in.md:1 to create/alter required tables (idempotent).
- Seed default tenant/org/admin via startup sanity or a one‑time SQL insert.

E) Configure Render (no mocks)

- Use blitz/render_blueprint.yaml:1 to create:
  - Postgres DB, Web Service for API (Docker), Web Service for Frontend (Node)
- Set secrets per blitz/secrets_template.env:1 (in Render env, not Git)
- Deploy API: `uvicorn api.main:app --host 0.0.0.0 --port 8888`
- Deploy Frontend: `npm ci && npm run build && npm run start`

F) Startup sanity + preflight

- Run: `python blitz/scripts/startup_check.py` (from API container or local)
- Call: `GET /api/health` — expect status=healthy or degraded with details
- Run: `python blitz/scripts/provider_preflight.py` or `POST /api/preflight/providers`

G) E2E smoke (real providers)

- Follow blitz/validation_checklist.md:1
  - Access → Roster → Add member → Cookies upload+verify → Saswave mutuals (1 prospect) → SendGrid email → Verify audits and health
- Verify logs in Render are JSON and include `corr_id` for all steps

H) CI policy gates

- Add GitHub Actions from blitz/examples/ci/ci.yml:1
- Ensure grep checks for:
  - No legacy auth/JWT imports
  - SendGrid‑only email path enforced
  - PhantomBuster secondary‑only with approval
  - No `print()` in backend; enforce logger usage

I) Finalize docs

- Copy or tailor these documents into the new repo’s `/blitz` folder for future operations:
  - About_blitz.md, Backend_and_Link_tie_in.md, frontend_blitz.md, Schema_tie_in.md, logging_observability.md, validation_checklist.md

Approvals & Safety

- Always request approval before running any cross‑repo copy or destructive command.
- Never commit secrets; verify env keys via `/api/health` and preflight.
- Keep a rollback plan (Render deploy history + DB snapshot).

Success Criteria

- `/api/health` shows healthy/degraded with correct model and provider statuses
- E2E smoke completes in < 30 minutes with green audits and valid SendGrid webhook events
- CI gates pass; logs and audits contain `corr_id` end‑to‑end

Rollback

- Revert to previous Render deploy; disable Blitz services if anomaly rate spikes; restore DB snapshot if any data changes were introduced.

