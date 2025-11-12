# Frontend Blitz Plan (Link UI)

Repository

- Target repo for Blitz project: https://github.com/TailoredAgents/TWblitzmode.git
- Extraction will point the frontend there after approval.

Scope

- Deliver a minimal Next.js frontend that preserves the current look/feel and Link workflows with a universal Access gate, roster self-service, Link Chat, Prospects, and Cookie Management.

Pages & Routes

- `/` – Landing with “Access” button. Clicking opens password gate modal.
- `/access` – Universal password screen (client-side check): input must equal “Tallwave”. On success, set `localStorage.blitz_access = "true"` and redirect to `/roster`.
- `/roster` – Public roster list with “+ Team member” form (Name, Email). Calls backend provisioning endpoint; immediately lists the new member.
- `/chat` – Link Chat UI (existing `LinkChat.tsx`); tool suggestions, confirmations (standard/detailed/destructive), upbeat/agentic tone.
- `/prospects` – Prospects view (existing `ProspectsView.tsx`) showing saved prospects and mutuals.
- `/cookies` – Cookie Management (LinkedIn cookie upload/validate/status), JSON display for li_at/JSESSIONID (existing Settings cookie panel extracted as standalone page).

Color & Components

- Reuse current color scheme/design tokens; carry `Sidebar.tsx`, shared layout, and typography exactly.
- Carry `ErrorBoundary` and minimal UI states.

Key Components to Extract

- Link Chat: `frontend/src/components/LinkChat.tsx`
- Prospects: `frontend/src/components/ProspectsView.tsx`
- Email (optional surface within Prospects): `frontend/src/components/EmailManagement.tsx`
- Cookie Management (slice from Settings): cookie panel portions of `frontend/src/components/Settings.tsx`
- Comm Hub (optional but recommended): `frontend/src/components/communication-hub/**`, `frontend/src/components/CommunicationHub.tsx`
- Shell: `frontend/src/components/Sidebar.tsx`, `frontend/src/app/layout.tsx`
- API client/types: `frontend/src/services/api.ts`, `frontend/src/types/**`
- Realtime: `frontend/src/services/websocket.ts`, `frontend/src/lib/websocketUrl.ts`, `frontend/src/services/agentLogger.ts`
- Contexts: `frontend/src/contexts/I18nContext.tsx`, `frontend/src/contexts/ThemeContext.tsx`

Access Gate (Minimal Security)

- Gate password: “Tallwave”.
- Client-side check only; store `localStorage.blitz_access = "true"` on success.
- On any protected page (roster/chat/prospects/cookies), redirect to `/access` if the flag is missing.

Roster Self-Service UX

- Inline form with fields: Name (required), Email (required). No password.
- Submit calls `POST /api/provisioning/add-team-member` (see backend doc). On success, append to roster list.

Cookie Management UX

- Inputs: li_at (required), JSESSIONID (optional), label (optional), user-agent (optional).
- Actions: Upload (POST), Verify (POST), Status (GET). Display current status and last verified at; show validated LinkedIn username/account.

Chat & Tools UX

- Tool prompts and confirmations:
  - Standard confirmations for search/mutuals; detailed confirmations for PhantomBuster runs; destructive confirmations for deletes.
- Always show which provider will be used (Saswave primary; PhantomBuster secondary with approval only; SendGrid for email).

Prospects UX

- Display prospects created via web search + CUFinder enrichment + LinkedIn URL resolve.
- Show mutuals summary and top-ranked connectors per prospect; link to send intro email action (opens a confirm modal).

Environment Variables (Frontend)

- `NEXT_PUBLIC_API_URL` – API base URL.
- `NEXT_PUBLIC_WEBSOCKET_URL` and `NEXT_PUBLIC_WEBSOCKET_PATH` – optional realtime endpoints.
- `NEXT_PUBLIC_MASTER_LOGIN_PASSWORD=Tallwave` – used by the Access screen (for copy and guard UI only).
- `NEXT_PUBLIC_SITE_URL` – absolute site URL.

Testing & Smoke (No Mocks)

- Unit: LinkChat helper tests, websocket URL normalization, API client request shaping.
- Smoke (Render or local against real API): Access → Roster → Add member → Upload cookies (real) → Run Saswave mutuals for 1 prospect → SendGrid email to test inbox → Verify Prospects and audits.
- E2E (optional): Playwright/Cypress targeting the deployed Render environment with controlled inputs.

Removal Checklist (Do NOT carry)

- `frontend/src/components/admin/tabs/RegistrationKeysTab.tsx`
- Any “invites”, “registration keys”, or dev-portal references.
- Traditional login/logout flows.

Implementation Checklist (Fast Path)

- Scaffold pages: Access, Roster, Chat, Prospects, Cookies; wire Sidebar links.
- Add route guard hook `useAccessGate()` reading `localStorage.blitz_access` and redirecting to `/access` when missing.
- Extract cookie panel from Settings into `/cookies` page with Upload, Verify, Status calls.
- Point API client base to `NEXT_PUBLIC_API_URL`; add `X-Correlation-Id` header per request.
- Add lightweight approvals mini-panel: list pending tool confirmations with Confirm/Cancel actions.
- Add provider health widget: fetch `GET /api/health` (preferred) or `/api/providers/health` and display R/Y/G with brief summaries; link errors to audits.
- Add audit viewer: fetch `/api/audit/recent` and show last 50 events with search by correlation_id.

OpenAPI Contract (Frontend Expectations)

- Provision: `POST /api/provisioning/add-team-member { name, email, li_at?, jsessionid? } → { user_id, team_member_id? }`
- Cookies: `GET /api/cookies/status`, `POST /api/cookies/upload`, `POST /api/cookies/verify`
- Prospects: `GET /api/prospects`, `POST /api/prospects`
- Mutuals: `POST /api/mutuals/run`, `POST /api/mutuals/enrich` (requires `approval_id`)
- Email: `POST /api/email/send` (SendGrid only), `POST /api/webhooks/sendgrid` (backend-only)
- Providers: `GET /api/providers/health`
- Health: `GET /api/health` (preferred for widgets)
- Audits: `GET /api/audit/recent?limit=50`

Performance & Quality

- Code-split heavy pages (Chat/Prospects) with dynamic imports; keep Above-The-Fold light.
- Disable websockets via `NEXT_PUBLIC_DISABLE_WEBSOCKET=true` for fast local smoke; enable for staging/prod.
- Add error states and toasts for cookie validation failures and provider downtimes.
- Ensure a11y on forms/buttons; use existing design tokens.

Developer Speed Aids

- NPM scripts: `dev`, `type-check`, `lint`, `test`, `smoke:fe`.
- API client codegen: add `pnpm gen:api` that reads `openapi.yaml` and generates types/hooks.

Render Deployment Notes

- Static hosting recommended for simplicity; ensure Next config supports `next export` if used.
- Configure `NEXT_PUBLIC_API_URL` to the Render API service URL.
- Verify Access gate redirect and page guards in the deployed environment (no login flows).
