# Link Blitz — Single‑Tenant Agent (TWblitzmode)

Purpose

- Clean, single‑tenant deployment of Link (chat, tools, cookies, prospects/mutuals, email) with minimal access gate and production‑grade observability.
- Policies: Saswave/Apify is primary for mutuals; PhantomBuster is secondary and approval‑gated; SendGrid is the only email path; model lock to `gpt-4.1`.

What’s Included

- API (FastAPI) with correlation‑aware JSON logging and health/preflight endpoints.
- Frontend (Next.js) — Access gate → Roster → Cookies → Chat → Prospects.
- Provider adapters for Apify (Saswave), CUFinder, PhantomBuster (secondary), SendGrid.
- Schema/migrations guidance for single‑tenant Postgres.
- CI policy gates and E2E validation checklist.

Quick Start (Local)

- Prereqs: Python 3.11+, Node 18+, Postgres 15+, (optional) Docker.
- Env (copy from `/blitz/secrets_template.env`):
  - `PRIMARY_MODEL=gpt-4.1`, `OPENAI_API_KEY`, `APIFY_TOKEN`, `CUFINDER_API_KEY`, `SENDGRID_API_KEY`, `SENDGRID_VERIFIED_SENDER`, `DATABASE_URL`.
  - Frontend: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_MASTER_LOGIN_PASSWORD=Tallwave`.
- Install:
  - `pip install -r requirements.txt` (or `make bootstrap`)
  - `cd frontend && npm ci`
- Migrate DB: `python -m api.run_migrations` (or `make migrate`)
- Start API: `uvicorn api.main:app --host 0.0.0.0 --port 8888` (or `make be`)
- Start FE: `cd frontend && npm run dev` (or `make fe`)

Health & Preflight

- `GET /api/health` — overall status (providers, schema, version, model).
- `POST /api/preflight/providers` — low‑cost provider checks (Apify, CUFinder, SendGrid, PhantomBuster).
- Startup sanity: `python blitz/scripts/startup_check.py`.
- Provider preflight: `python blitz/scripts/provider_preflight.py`.

Policies (enforced in code/CI)

- SendGrid‑only email paths.
- PhantomBuster is secondary and requires explicit approval.
- Saswave is the default path for mutuals.
- Minimal Access gate (universal password) on FE — no JWT/session auth.

E2E Smoke (Real Providers)

- Access → Roster → Add team member → Upload/Verify cookie → Run Saswave (1 prospect) → SendGrid email → Verify audits and health.
- Full checklist: `/blitz/validation_checklist.md`.

Logging & Observability

- JSON logs in production: set `LOG_FORMAT=json` and `LOG_LEVEL=INFO`.
- Correlation ID: FE sends `X-Correlation-Id`; API echoes header; providers are logged with `corr_id` and `run_id/message_id`.
- Health widget should call `GET /api/health`.
- Details: `/blitz/logging_observability.md` and examples in `/blitz/examples/api/*`.

Deploy on Render

- Use `/blitz/render_blueprint.yaml` to create API, FE, and managed Postgres.
- Set env vars in Render from `/blitz/secrets_template.env` (never commit secrets).

CI

- Add `/blitz/examples/ci/ci.yml` to `.github/workflows/ci.yml`.
- Policy gates: no legacy auth imports, SendGrid‑only, Phantom secondary, no `print()` in backend, optional provider preflight.

Docs

- Operational docs live in `/blitz`:
  - Overview, Backend/Frontend plans, Schema tie‑in, Logging plan, Validation checklist, Codex execution guide.

License / Attribution

- Fill per organization policies.
