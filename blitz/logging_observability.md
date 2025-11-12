# Blitz Logging & Observability Plan

Goals

- Pinpoint issues fast with consistent, structured logs and audits across API, providers, and UI.
- Make every significant action traceable via correlation IDs and audit events.
- Keep noise low with level discipline, sampling, and redaction.

Principles

- JSON logs only in production (`LOG_FORMAT=json`), human-readable in dev.
- End-to-end correlation: generate/propagate `X-Correlation-Id` from FE → API → providers → audits.
- Clear separation:
  - Logs = transport/debug/telemetry (JSON to stdout).
  - Audits = canonical business events (persisted to `audit_events`).
- No PII in logs; only audit payloads store necessary business context.

Log Schema (JSON)

- Common keys: `ts` (ISO8601), `level`, `msg`, `logger`, `corr_id`, `tenant_id`, `org_id`, `user_id`, `route`, `method`, `status`, `latency_ms`, `tool_id`, `provider`, `run_id`, `error`, `error_class`, `retry`, `env`, `version`.
- Provider telemetry: `provider`, `endpoint`, `status_code`, `duration_ms`, `cost_estimate`, `rate_limited`.
- Security redact: `redactions` count; never include cookie values, tokens, or li_at.

Backend Implementation Guidance

- Logging config
  - Use Python logging with JSON formatter (or `structlog`) switched by `LOG_FORMAT=json`.
  - Respect `LOG_LEVEL` env (default INFO in prod, DEBUG only locally).
- Correlation ID middleware
  - Read `X-Correlation-Id` or generate UUIDv4; attach to `request.state.corr_id`; include in every log and audit.
- Request logs
  - On completion: `route`, `method`, `status`, `latency_ms`, `corr_id`, `tenant/org/user`.
  - Sampling for 2xx at INFO (e.g., 1:20 if noisy); always log 4xx/5xx at WARNING/ERROR.
- Exception handler
  - Catch unhandled exceptions; log `error`, `error_class`, `trace_sample`, `corr_id`; return sanitized error response.
- Tool and provider wrappers
  - Before/after logs: `tool_id`, parameters hash (not raw), `provider`, `run_id`, `duration_ms`, `status`, `retry`.
  - Map to audits: `AI_TOOL_START/END/ERROR`, `EXTERNAL_API_CALL`, `EMAIL_SENT`.
- Email
  - Log `message_id`, recipients count, SendGrid status; link webhook events via `message_id`.

Frontend Implementation Guidance

- Correlation ID
  - Generate on page load; store in memory and include in API requests as `X-Correlation-Id`.
- Agent logger
  - Keep client-side console logs minimal; ship significant UI events to API (agent events endpoint) tied to `corr_id`.
- Sensitive UI
  - Never echo cookies or secrets to console.

Audit Events

- Table: `audit_events(id, created_at, tenant_id, actor_id, event_type, payload_jsonb)`.
- Emit for: provisioning, cookie upload/verify, mutuals runs, enrichments, email send, webhook events, deletes, undo actions.
- Ensure `corr_id` is included in `payload_jsonb`.

Dashboards & Queries

- Render Logs or external drain (Datadog/ELK/Logtail).
- Example searches:
  - `level:ERROR AND corr_id:<id>` – drill-down on a specific flow.
  - `provider:apify AND status:ERROR` – provider errors view.
- SQL examples:
  - Recent emails: `SELECT created_at, payload->>'message_id' FROM audit_events WHERE event_type='EMAIL_SENT' ORDER BY 1 DESC LIMIT 50;`
  - Recent tool errors: `SELECT created_at, payload->>'tool_id', payload->>'error' FROM audit_events WHERE event_type='AI_TOOL_ERROR' ORDER BY 1 DESC LIMIT 50;`

Examples to copy

- Logging middleware: `blitz/examples/api/logging_middleware.py:1`
- Health routes: `blitz/examples/api/health_routes.py:1`
- SendGrid custom_args corr_id: `blitz/examples/api/sendgrid_correlation_example.py:1`
- Apify meta.corr_id input: `blitz/examples/api/apify_input_example.json:1`

Redaction & Safety

- Redact patterns: `(?i)li_at|jsessionid|authorization|api_key|token` before logging.
- Count redactions per log line in `redactions`.
- Never log request bodies for endpoints accepting cookies or secrets.

Sampling & Rate Control

- Enable request log sampling (e.g., 5%) for high-throughput paths.
- Always log WARN/ERROR without sampling.

Render Setup

- Configure a Log Drain if needed (Datadog/Logtail/ELK). Keep STDOUT JSON logs enabled.
- Env suggestions: `LOG_FORMAT=json`, `LOG_LEVEL=INFO`, `LOG_SAMPLE_RATE=0.05`.

Quality Gates

- CI lint to flag `print(` uses in backend; prefer `logger.*`.
- Test confirms `X-Correlation-Id` round-trips through at least one API path and appears in audits.

On-Call Quick Steps

1) Grab `corr_id` from UI or error page.
2) Search logs for `corr_id` to reconstruct flow and provider sub-calls.
3) Cross-reference `audit_events` by `corr_id` to confirm business effect.
4) Check provider health widget and `/api/health` for system status.

Quick Implementation Checklist (Wire This During Build)

- WebSockets
  - Include `corr_id`, `tenant_id`, `user_id` in join/leave/error events and server broadcasts.
  - On the client, reuse the same `corr_id` used for HTTP calls when establishing the socket.
- Provider metadata wiring
  - SendGrid: include `custom_args: { corr_id: '<value>' }` on send; ensure webhook payloads round‑trip `corr_id` and map back to audits.
  - Apify: add `meta: { corr_id: '<value>' }` in actor input if supported; always log actor `run_id` and link it to `corr_id`.
  - CUFinder/PhantomBuster: log request intent with `corr_id` and record any returned job/run identifier for traceability.
- Service/version fields
  - Inject `service` (e.g., `link-api`, `link-frontend`) and `version` (git SHA) into every log line; add to `/api/health` response.
- DB visibility
  - Set `DATABASE_SLOW_QUERY_THRESHOLD_MS` and log slow queries with `corr_id`.
  - Log migration steps and durations at startup (INFO) with a final summary.
- Log drain
  - Configure a Render log drain (Datadog/Logtail/ELK). Keep JSON to stdout for portability.
- Alerting (optional but recommended)
  - Alert on spikes in `level:ERROR`, provider error rates, and SendGrid bounce/blocked events (via webhook counts).
