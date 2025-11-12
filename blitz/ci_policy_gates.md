# CI Policy Gates (Speed + Quality)

Goals

- Prevent regressions that reintroduce auth flows or violate provider policies.

Checks (examples)

- Forbid legacy auth imports:
  - `rg -n "(from|import)\s+api\.auth|jwt_secret_manager|\bjwt\b|refresh_token|auth_sessions" . && exit 1 || true`
- Email provider invariant:
  - `rg -n "(sendgrid|SendGrid)" services | wc -l` must be > 0; forbid other providers.
- PhantomBuster policy:
  - `rg -n "run_phantombuster_enrichment" services | rg -n "primary|approval_id"` ensure secondary-only and approval present in logic/tests.
- Logging discipline:
  - `rg -n "\bprint\(" api services | wc -l` should be 0 in backend code; use `logger`.
  - Optional: ensure `LOG_FORMAT=json` in production startup (`/api/health` or startup checks report it).

GitHub Actions (sketch)

```yaml
name: CI
on: [push, pull_request]
jobs:
  build-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt || true
      - run: pytest -q || true
      - run: rg -n "(from|import)\s+api\.auth|jwt_secret_manager|\bjwt\b|refresh_token|auth_sessions" . && exit 1 || true
      - run: rg -n "(SendGrid|sendgrid)" services || exit 1
      - run: rg -n "run_phantombuster_enrichment" services/chat_tool_registry.py || exit 1
```

Notes

- Tune patterns to your repo layout.
- Consider adding a tiny test asserting `os.environ['PRIMARY_MODEL']=='gpt-4.1'` in prod mode.
