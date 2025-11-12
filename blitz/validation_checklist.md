# Blitz Validation Checklist (Real Providers)

Preflight

- Env set in Render: OPENAI_API_KEY, PRIMARY_MODEL=gpt-4.1, APIFY_TOKEN, CUFINDER_API_KEY, SENDGRID_API_KEY, SENDGRID_VERIFIED_SENDER, DATABASE_URL.
- Frontend env: NEXT_PUBLIC_API_URL, NEXT_PUBLIC_SITE_URL, NEXT_PUBLIC_MASTER_LOGIN_PASSWORD=Tallwave.
- Run `python blitz/scripts/startup_check.py` and confirm PRIMARY_MODEL and DB connected.
- Run provider preflight: `python blitz/scripts/provider_preflight.py` (or call `POST /api/preflight/providers`) and confirm Apify/CUF/SENDGRID green.

E2E Smoke (Production-like)

1) Access → Roster
   - Visit `/` → click Access → enter "Tallwave" → redirected to `/roster`.
   - Add team member (Name + Email). Confirm appears in roster list.

2) Cookie upload & verify
   - Go to `/cookies` → upload li_at (+ optional jsessionid) → status becomes pending → verify → status valid.
   - Status response includes LinkedIn username/account when available.

3) Prospect creation & mutuals (Saswave)
   - Create a test prospect (name/company or LinkedIn URL) in `/prospects`.
   - Run mutuals for that prospect. Confirm connectors appear and ranking is populated.

4) Optional PhantomBuster (approval)
   - Trigger enrichment with approval; ensure detailed confirmation shown; run and confirm additional data recorded.

5) Email send (SendGrid)
   - Trigger Send Introduction Email; confirm detailed confirmation; send to a test inbox.
   - Verify message_id returned; check webhook events and audit entry.

6) Audits & Health
  - Open audit viewer: recent actions listed with correlation_ids and durations.
  - Provider health widget: Apify, CUFinder, SendGrid all green (GET /api/health).
  - Logging: Confirm JSON logs in Render with corr_id present; verify an ERROR path shows error_class and stack sample.

CI Policy Gates

- Build/typecheck/tests run clean.
- Grep checks:
  - No imports of auth/JWT modules.
  - No non-SendGrid email providers present.
  - PhantomBuster not used as primary; approval required.

Rollback Ready

- DB snapshot taken before cutover.
- Ability to disable new service via Render switch if anomaly rate spikes.
