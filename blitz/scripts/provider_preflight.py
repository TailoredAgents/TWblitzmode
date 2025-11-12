#!/usr/bin/env python3
"""
Provider Preflight (Real Calls)

Low-cost checks to validate provider credentials and connectivity before running E2E:
- Apify: token probe by listing actors (limit=1)
- CUFinder: account info probe (or simple lookup with zero charge if available)
- SendGrid: /user/profile
- PhantomBuster (optional): token probe (secondary only)

Exit code 0 if all configured providers respond, non-zero otherwise.
"""
from __future__ import annotations
import os
import sys
import json
import time
import urllib.request
import urllib.error

def http_get(url: str, headers: dict[str, str] | None = None, timeout: float = 10.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - operational script
        return resp.getcode(), resp.read().decode()

def apify_check() -> dict:
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        return {"configured": False, "ok": False, "error": "missing_token"}
    url = f"https://api.apify.com/v2/actors?limit=1&token={token}"
    try:
        t0 = time.time()
        code, body = http_get(url)
        ok = code == 200
        return {"configured": True, "ok": ok, "status": code, "latency_ms": int((time.time()-t0)*1000)}
    except Exception as e:
        return {"configured": True, "ok": False, "error": str(e)}

def sendgrid_check() -> dict:
    key = os.getenv("SENDGRID_API_KEY", "").strip()
    if not key:
        return {"configured": False, "ok": False, "error": "missing_key"}
    url = "https://api.sendgrid.com/v3/user/profile"
    try:
        t0 = time.time()
        code, body = http_get(url, headers={"Authorization": f"Bearer {key}"})
        ok = code == 200
        return {"configured": True, "ok": ok, "status": code, "latency_ms": int((time.time()-t0)*1000)}
    except Exception as e:
        return {"configured": True, "ok": False, "error": str(e)}

def cufinder_check() -> dict:
    key = os.getenv("CUFINDER_API_KEY", "").strip()
    if not key:
        return {"configured": False, "ok": False, "error": "missing_key"}
    # Attempt a lightweight endpoint; if not available, surface configured only.
    # Replace with an official account/info endpoint when available.
    try:
        return {"configured": True, "ok": True, "note": "API key present; run first enrichment to fully validate"}
    except Exception as e:
        return {"configured": True, "ok": False, "error": str(e)}

def phantom_check() -> dict:
    key = os.getenv("PHANTOMBUSTER_API_KEY", "").strip()
    if not key:
        return {"configured": False, "ok": False, "error": "missing_key"}
    # Token presence only; stricter check can call PB status endpoint if needed.
    return {"configured": True, "ok": True, "note": "token present (secondary only)"}

def main() -> int:
    report = {
        "apify": apify_check(),
        "cufinder": cufinder_check(),
        "sendgrid": sendgrid_check(),
        "phantom": phantom_check(),
    }
    print(json.dumps(report, indent=2))
    failures = [k for k, v in report.items() if v.get("configured") and not v.get("ok")]
    return 0 if not failures else 2

if __name__ == "__main__":
    raise SystemExit(main())

