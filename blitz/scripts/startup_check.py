#!/usr/bin/env python3
"""
Blitz Startup Sanity Check
- Validates critical environment variables
- Attempts DB connectivity (PostgreSQL) if psycopg2 is available
- Prints minimal schema presence checks when possible
"""
import os
import sys
import json

REQUIRED_ENVS = [
    "OPENAI_API_KEY",
    "PRIMARY_MODEL",
    "APIFY_TOKEN",
    "CUFINDER_API_KEY",
    "SENDGRID_API_KEY",
    "SENDGRID_VERIFIED_SENDER",
    "DATABASE_URL",
]

def main() -> int:
    print("[blitz] Environment check:")
    missing = []
    report = {"env": {}, "db": {"connected": False, "errors": []}, "schema": {}}

    for key in REQUIRED_ENVS:
        present = bool(os.getenv(key))
        report["env"][key] = "present" if present else "missing"
        if not present:
            missing.append(key)

    # Model enforcement
    model = os.getenv("PRIMARY_MODEL", "").strip()
    report["env"]["PRIMARY_MODEL_value"] = model
    if model and model != "gpt-4.1":
        report["env"]["PRIMARY_MODEL_warning"] = "PRIMARY_MODEL should be gpt-4.1"

    dsn = os.getenv("DATABASE_URL", "")
    if dsn:
        try:
            import psycopg2  # type: ignore
            conn = psycopg2.connect(dsn)
            cur = conn.cursor()
            report["db"]["connected"] = True
            # Minimal presence checks
            for table in ("tenants", "organizations", "users", "team_members"):
                try:
                    cur.execute(f"SELECT to_regclass('{table}');")
                    exists = cur.fetchone()[0] is not None
                    report["schema"][table] = "present" if exists else "missing"
                except Exception as e:
                    report["schema"][table] = f"error: {e}"
            cur.close()
            conn.close()
        except Exception as e:  # psycopg2 missing or connection error
            report["db"]["errors"].append(str(e))

    print(json.dumps(report, indent=2))
    if missing:
        print("[blitz] Missing envs:", ", ".join(missing), file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

