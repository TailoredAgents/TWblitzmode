#!/usr/bin/env python3
"""
Operational utilities for managing auth_sessions.

Usage examples:
  - List sessions by tenant:
      ./scripts/ops_sessions.py list --tenant 1

  - Revoke a user's sessions (all):
      ./scripts/ops_sessions.py revoke --tenant 1 --user 42

  - Revoke a specific session:
      ./scripts/ops_sessions.py revoke --tenant 1 --user 42 --session abcd1234

Requires DATABASE_URL in the environment and psycopg2-binary installed.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Any


def _connect():
    try:
        import psycopg2
        import psycopg2.extras
    except Exception as exc:  # pragma: no cover
        print("psycopg2-binary is required: pip install psycopg2-binary", file=sys.stderr)
        raise

    dsn = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set")

    if dsn.startswith("postgres://"):
        dsn = dsn.replace("postgres://", "postgresql://", 1)

    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True
    return conn


def cmd_list(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            sql = [
                "SELECT id, tenant_id, user_id, session_id, token_version, expires_at, revoked_at, updated_at",
                "FROM auth_sessions",
                "WHERE tenant_id = %s",
            ]
            params: list[Any] = [args.tenant]
            if args.user:
                sql.append("AND user_id = %s")
                params.append(args.user)
            sql.append("ORDER BY updated_at DESC NULLS LAST, id DESC LIMIT 200")
            cur.execute(" ".join(sql), tuple(params))
            rows = cur.fetchall() or []
        for r in rows:
            revoked = bool(r.get("revoked_at"))
            print(
                f"id={r['id']} tenant={r['tenant_id']} user={r['user_id']} session={r['session_id']} ver={r['token_version']} ",
                f"expires={r['expires_at']} revoked={revoked} updated={r['updated_at']}",
            )
        return 0
    finally:
        conn.close()


def cmd_revoke(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if args.session:
                cur.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = NOW()
                    WHERE tenant_id = %s AND user_id = %s AND session_id = %s AND revoked_at IS NULL
                    """,
                    (args.tenant, args.user, args.session),
                )
            else:
                cur.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = NOW()
                    WHERE tenant_id = %s AND user_id = %s AND revoked_at IS NULL
                    """,
                    (args.tenant, args.user),
                )
        print("revocation complete")
        return 0
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Manage auth_sessions")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List sessions")
    p_list.add_argument("--tenant", type=int, required=True)
    p_list.add_argument("--user", type=int)
    p_list.set_defaults(func=cmd_list)

    p_revoke = sub.add_parser("revoke", help="Revoke sessions")
    p_revoke.add_argument("--tenant", type=int, required=True)
    p_revoke.add_argument("--user", type=int, required=True)
    p_revoke.add_argument("--session", type=str)
    p_revoke.set_defaults(func=cmd_revoke)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))

