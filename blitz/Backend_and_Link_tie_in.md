# Backend Blitz Plan (Link Core + Tie-ins)

Repository

- Target repo for the new project: https://github.com/TailoredAgents/TWblitzmode.git
- Note: Do not start extraction yet; this plan references that URL for the eventual push.

Principles

- No legacy auth. Replace all `get_current_user`/JWT flows with a lightweight identity stub. The only “security” is the frontend Access gate (universal password “Tallwave”). Server accepts requests without tokens.
- Preserve Link functionality and policies: Saswave (Apify) primary; PhantomBuster secondary with explicit user approval; SendGrid-only email.
- Keep startup sanity to seed the single-tenant default (tenant_id=1, organization_id=1, admin user record) to avoid FK issues.

Runtime Stack

- FastAPI app with Link modules extracted from the current repo:
  - Agent brain + KB: `services/master_chat_agent.py`, `services/link_tallwave_knowledge_base.py`
  - Tool registry: `services/chat_tool_registry.py` (confirmations, undo admin-only can be kept but treated as confirmation-only)
  - Orchestrators: `services/orchestrator.py`, `services/mutuals_orchestrator_service.py`, `services/external_api_orchestrator.py`
  - Providers: `integrations/apify_client.py`, `integrations/cufinder_client.py`, `integrations/phantombuster_client.py`, `services/sendgrid_service.py`
  - Email enrichment: `services/email_enrichment_service.py`
  - Observability/Audit: `services/audit_logging_service.py`, `services/database_logging.py`, `services/request_context.py`

Identity Stub (No Auth)

- New module `api/deps_identity_stub.py`:
  - `get_current_user()` returns a dict with fields: `{ id: 1, email: 'admin@local', role: 'admin', tenant_id: 1, organization_id: 1 }` unless overridden by headers (`X-Debug-User-Id`, `X-Role`, `X-Org-Id`).
  - `get_current_admin()` ensures role is effectively admin (same stub; only used for destructive actions’ confirmation copy).
  - All Link routes import from this stub instead of `api.deps`.

HTTP API Surface (Minimal)

- Provisioning (replaces add-team-member):
  - `POST /api/provisioning/add-team-member` → body: `{ name, email, li_at?, jsessionid?, label?, user_agent? }` → creates `users`, `team_members`, optional `linkedin_sessions`. Returns `{ user_id, team_member_id? }`.
- Cookies:
  - `GET /api/cookies/status` → current status for org.
  - `POST /api/cookies/upload` → store encrypted li_at (+ optional jsessionid), mark status pending, trigger verify.
  - `POST /api/cookies/verify` → runs `LinkedInCookieVerifier` if available; sets `team_members.cookie_status` (‘valid’/‘missing’/‘failed’); returns username/account when verifiable.
- Prospects & Mutuals:
  - `POST /api/prospects` → create/search prospect (name/company/linkedin_url); Link agent can call.
  - `GET /api/prospects` → list.
  - `POST /api/mutuals/run` → runs Saswave (Apify) for provided prospect(s); requires explicit user confirmation (tool confirmation serves as UX gate).
  - `POST /api/mutuals/enrich` → optional PhantomBuster enrichment, body must include `approval_id` and references to prospect or mutual.
- Email:
  - `POST /api/email/send` → SendGrid only; returns `{ message_id }`. Confirmation dialog precedes call in UI/tooling.
  - `POST /api/webhooks/sendgrid` → verified webhook to map events to `message_id`.
- Agentic Operations:
  - `POST /api/ai/chat` or keep existing routes for tool orchestration; ensure dependency uses identity stub.

Provider Policies (Enforced)

- Mutually exclusive providers:
  - Mutuals: Apify (Saswave) is the default path. PhantomBuster MUST NOT run as primary.
  - Enrichment: PhantomBuster requires `approval_id` and is logged as secondary.
  - Email: Only SendGrid paths are compiled and routable.

Startup Sanity

- Ensure presence of: tenants(1), organizations(1), users(1 admin), foreign keys aligned.
- Assert `PRIMARY_MODEL=gpt-4.1`; abort otherwise.
- Validate provider keys availability and log degraded modes (e.g., missing CUFinder key → queued enrichment but not fatal).

Auditing & Logs

- Correlation ID middleware (reads/sets `X-Correlation-Id`).
- Audit each tool/action: start/end/error with provider, run_id, latency_ms, and actor (from stub identity).
- Email: record `EMAIL_SENT` with `message_id` and webhook delivery/open/bounce events.

Provider Metadata & Correlation (Must Wire)

- SendGrid
  - On send, include `custom_args: { corr_id: '<uuid>' }` and optionally `tenant_id`, `org_id`.
  - Ensure webhook handlers read back `custom_args.corr_id` and attach it to audits so email lifecycle events correlate with the initial send.
- Apify (Saswave)
  - Include a `meta.corr_id` (if supported by actor input) or pass a `corr_id` field in input JSON; always log the returned `run_id` and map it to `corr_id`.
- CUFinder
  - Log enrichment attempts with `corr_id`, cache decision (hit/miss), and cost/confidence when available.
- PhantomBuster
  - Log `approval_id`, enrichment type, and any run identifier; explicitly note `secondary_only=true` in the log payload for policy traceability.

CI/Policy Tests (New Repo)

- Fail if imports include legacy auth (`api/auth.py`, `jwt`, `refresh_token`, `auth_sessions`).
- Fail if PhantomBuster is invoked as primary or without `approval_id`.
- Fail if any email send path != SendGrid.
- Optional: schema presence check behind env flag.

Env Vars (Backend)

- OPENAI_API_KEY, PRIMARY_MODEL=gpt-4.1
- APIFY_TOKEN, PHANTOMBUSTER_API_KEY (secondary only), CUFINDER_API_KEY
- SENDGRID_API_KEY, SENDGRID_VERIFIED_SENDER, SENDGRID_WEBHOOK_VERIFICATION_KEY
- DATABASE_URL, ENC_KEY, SECRET_KEY (app key), APP_BASE_URL, APIFY/SENDGRID/PHANTOM webhook secrets

Extraction Notes

- Replace `from api.deps import get_current_user/get_current_admin` → `from api.deps_identity_stub import ...` across Link routes.
- Exclude `api/auth.py`, `api/security.py`, `jwt_secret_manager.py`, refresh/registration/keys modules.
- Keep `api/database.py`, `api/db_core.py`, `api/startup_sanity.py`, `api/startup_checks.py` (pruned for model/policy checks only).

OpenAPI (Key Endpoints – Draft)

- POST `/api/provisioning/add-team-member`
  - req: `{ name: string, email: string, li_at?: string, jsessionid?: string, label?: string, user_agent?: string }`
  - res: `{ success: boolean, user_id: number, team_member_id?: number }`
- Cookies
  - GET `/api/cookies/status` → `{ status: 'valid'|'missing'|'failed'|'pending', last_verified_at?: string, username?: string }`
  - POST `/api/cookies/upload` → `{ status, message }`
  - POST `/api/cookies/verify` → `{ status, username?, account_name? }`
- Prospects
  - GET `/api/prospects` → `{ data: Prospect[] }`
  - POST `/api/prospects` → `{ id: number }`
- Mutuals
  - POST `/api/mutuals/run` → `{ job_id: string }`
  - POST `/api/mutuals/enrich` → `{ success: boolean }` (requires `approval_id`)
- Email
  - POST `/api/email/send` → `{ message_id: string }`
- Providers
  - GET `/api/providers/health` → `{ apify: Health, cufinder: Health, sendgrid: Health, phantom: Health }`
- Audits
  - GET `/api/audit/recent?limit=50` → `{ events: AuditEvent[] }`

Health & Preflight Endpoints

- GET `/api/health` → overall status with sub-sections:
  - `status`: healthy | degraded | error
  - `version`, `model`
  - `providers`: `{ apify, cufinder, sendgrid, phantom }` each with fields like `{ configured: bool, ok: bool, last_error?: string }`
  - `schema`: presence map of critical tables `{ users: "present", team_members: "present", ... }`

- POST `/api/preflight/providers` (low‑cost, live checks)
  - optional body `{ include: ["apify", "cufinder", "sendgrid", "phantom"] }`
  - returns `{ apify: {...}, cufinder: {...}, sendgrid: {...}, phantom: {...} }` with brief timings and hints.
  - Examples:
    - Apify: token validation + simple actor listing
    - CUFinder: quick account/info request
    - SendGrid: `/user/profile` probe
    - PhantomBuster: token validation only (since secondary)

Code Examples

- Logging middleware ready to copy: `blitz/examples/api/logging_middleware.py:1`
- Health routes skeleton: `blitz/examples/api/health_routes.py:1`
- SendGrid payload with corr_id: `blitz/examples/api/sendgrid_correlation_example.py:1`
- Apify input with meta.corr_id: `blitz/examples/api/apify_input_example.json:1`

Identity Stub (Sketch)

```python
# api/deps_identity_stub.py
from fastapi import Header

def get_current_user(x_debug_user_id: int | None = Header(default=None, alias="X-Debug-User-Id"),
                     x_role: str | None = Header(default=None, alias="X-Role"),
                     x_org_id: int | None = Header(default=None, alias="X-Org-Id")):
    return {
        "id": x_debug_user_id or 1,
        "email": "admin@local",
        "role": (x_role or "admin").lower(),
        "tenant_id": 1,
        "organization_id": x_org_id or 1,
    }

def get_current_admin(user = None):  # wired with Depends(get_current_user)
    return get_current_user()  # rely on UI confirmations for destructive ops
```

Compose & Makefile (Bootstrap)

- docker-compose.yml: services for postgres, api, frontend (optional redis).
- Makefile targets:
  - `bootstrap` (install deps), `migrate`, `seed`, `run` (api), `fe` (frontend), `be` (backend),
    `test`, `lint`, `typecheck`, `smoke` (calls scripted API/FE smoke).

Testing Plan

- Unit: provider adapter wiring, tool registry confirmation logic, identity stub.
- Policy CI: block non-SendGrid email paths; block Phantom as primary; forbid auth/JWT imports.
- Smoke (real providers, low volume): provision → cookies upload (real verify if available) → run mutuals (Apify) on one prospect → send email (SendGrid) to a test inbox → verify webhook/audit.

Render Deployment (No Mocks)

- API (Web Service using Dockerfile):
  - Build command: `docker build -t link-api .`
  - Start command: `uvicorn api.main:app --host 0.0.0.0 --port 8888` (or gunicorn/uvicorn workers)
  - Health check: `GET /api/health` (add if missing; current `api/main.py` exposes a root health JSON)
  - Env vars: set OPENAI_API_KEY, PRIMARY_MODEL=gpt-4.1, APIFY_TOKEN, CUFINDER_API_KEY, SENDGRID_API_KEY, SENDGRID_VERIFIED_SENDER, DATABASE_URL, ENC_KEY, SECRET_KEY; optional PHANTOMBUSTER_API_KEY.
  - Networking: expose port 8888.

- Frontend (Static or Web Service):
  - Build: `cd frontend && npm ci && npm run build`
  - If Static: set output export and host as static; else run Next server with Node service.
  - Env: `NEXT_PUBLIC_API_URL` pointing to API service URL, `NEXT_PUBLIC_SITE_URL`, and `NEXT_PUBLIC_MASTER_LOGIN_PASSWORD=Tallwave`.

First-Run (Production Smoke)

1) Add a single teammate via `/api/provisioning/add-team-member`.
2) Upload a valid LinkedIn cookie and verify status = valid.
3) Create a test prospect, run Saswave mutuals (1 target), confirm connectors appear.
4) Send one intro email to a test address; confirm SendGrid message_id and webhook events recorded.
