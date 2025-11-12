# Blitz Cutover Playbook (Render)

Objective

- Move Link functionality into the new single-tenant Blitz project and demo in production-like conditions on Render with minimal risk.

Roles

- Lead Engineer (LE): owns code extraction, wiring, and deploy.
- DB Specialist (DB): validates schema/tables and runs backfills.
- Operator (OP): executes E2E smoke and client demo.

Timeline

- T0: Approve allowlist; freeze scope.
- T0–T4h: Create artifacts with `blitz_extract.sh`; initialize `TWblitzmode` using `blitz_import.sh`.
- T4–T8h: Configure Render using `blitz/render_blueprint.yaml`; set secrets; deploy API + Frontend.
- T8–T16h: Wire provisioning and cookies; run startup sanity; verify health.
- T16–T24h: Run Saswave mutuals (single prospect); verify Prospects and audits.
- T24–T36h: Send SendGrid email to test inbox; verify webhook and audits.
- T36–T48h: Hardening (approvals panel, provider health widget), CI policy gates; client demo.

Execution Steps

1) Artifact creation (LE)
   - Run `./blitz/scripts/blitz_extract.sh` in the legacy repo (no secrets scrubbed).
   - Share artifacts internally; do not push to public remotes.

2) New repo init (LE)
   - `./blitz/scripts/blitz_import.sh ./TWblitzmode`
   - Add remote: `git remote add origin https://github.com/TailoredAgents/TWblitzmode.git`
   - `git push -u origin main`

3) Render setup (LE)
   - From `blitz/render_blueprint.yaml`, create services; set env vars (OPENAI_API_KEY, PRIMARY_MODEL=gpt-4.1, APIFY_TOKEN, CUFINDER_API_KEY, SENDGRID_API_KEY, SENDGRID_VERIFIED_SENDER, DATABASE_URL via managed DB connection).
   - Deploy API and Frontend; confirm health endpoints.
   - Run health and preflight:
     - `GET /api/health` must show `status=healthy` or `degraded` (with details) before E2E.
     - `POST /api/preflight/providers` or `python blitz/scripts/provider_preflight.py` to verify provider readiness.

4) DB verification (DB)
   - Apply migrations (idempotent) per `blitz/Schema_tie_in.md`.
   - Confirm tables/columns presence and seed default tenant/org/admin.

5) E2E smoke (OP)
   - Follow `blitz/validation_checklist.md` end-to-end.

6) Hardening (LE)
   - Enable approvals mini-panel, provider health widget, audit viewer.
   - Wire CI using `blitz/ci_policy_gates.md`.

Rollback

- Use Render deploy history to rollback; keep legacy service live until Blitz passes smoke.
- Maintain DB snapshot before any backfill/import.

Success Criteria

- Access → Roster → Cookies → Mutuals → Email completes within 30 minutes on Render with green audits and health.
- CI gates pass; no auth imports; provider policies enforced.
