"""
PostgreSQL-only database helpers for the company portal runtime.

This module replaces the legacy sqlite implementation and routes all
operations through psycopg2 connections obtained from the shared Postgres
utility helpers.  It preserves the public API consumed throughout the
codebase while ensuring queries execute with positional (`%s`) placeholders
and provide sqlite-style row compatibility (index- and key-based access)
via ``DictCursor`` rows.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from time import perf_counter
from typing import Any, Iterable, Iterator, List, Optional, Sequence, Tuple

from psycopg2.extras import DictCursor, DictRow
from psycopg2.extensions import connection as PsycopgConnection

from core.settings import settings

try:
    from services.database_monitoring import log_slow_query
except ImportError:  # pragma: no cover - fallback when running from src/ layout
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parent.parent
    SRC = ROOT / "src"
    for entry in (SRC, ROOT):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    from src.services.database_monitoring import log_slow_query  # type: ignore

from scripts.utils.postgres import (
    DEFAULT_TEST_DSN,
    postgres_connection,
    resolve_required_dsn,
)
from .tenant_context import get_tenant
from .query_converter import convert_params, convert_query

logger = logging.getLogger(__name__)

SLOW_QUERY_THRESHOLD_MS = getattr(settings, "DATABASE_SLOW_QUERY_THRESHOLD_MS", None)

ALLOWED_TABLES = {
    "tenants",
    "users",
    "tenant_settings",
    "user_integrations",
    "user_preferences",
    "prospects",
    "job_runs",
    "organizations",
    "billing_plans",
    "team_members",
    "connectors",
    "team_member_connectors",
    "prospect_connectors",
    "registration_keys",
    "registration_key_shares",
    "cookie_jars",
    "cookie_events",
    "billing_events",
    "ai_assistants",
}

TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _resolve_dsn() -> str:
    """Resolve the PostgreSQL DSN used for portal operations."""
    return resolve_required_dsn("DATABASE_URL", "TEST_DATABASE_URL", default=DEFAULT_TEST_DSN)


def validate_table_name(table_name: str) -> bool:
    """Ensure only approved table names are used in dynamic queries."""
    if not table_name:
        return False
    if table_name in ALLOWED_TABLES:
        return True
    if not TABLE_NAME_PATTERN.match(table_name):
        return False
    logger.warning("Rejecting unapproved table name '%s'", table_name)
    return False


def _log_query_duration(
    sql: str,
    params: Optional[Sequence[Any]],
    duration_ms: float,
    *,
    error: Optional[str] = None,
) -> None:
    """Emit slow query telemetry when the configured threshold is exceeded."""
    if SLOW_QUERY_THRESHOLD_MS and duration_ms >= SLOW_QUERY_THRESHOLD_MS:
        try:
            log_slow_query(sql, params, duration_ms, error=error)
        except Exception:  # pragma: no cover - telemetry failures must not break flow
            logger.debug("Failed to emit slow-query telemetry", exc_info=True)


ConnectionLike = PsycopgConnection


@contextmanager
def get_conn(*, tenant_id: Optional[Any] = None) -> Iterator[ConnectionLike]:
    """
    Context manager that yields a psycopg2 connection configured with
    ``DictCursor`` rows so callers can access results via index or column name.
    """
    dsn = _resolve_dsn()
    resolved_tenant = tenant_id if tenant_id is not None else get_tenant()

    with postgres_connection(dsn, cursor_factory=DictCursor) as conn:
        try:
            if resolved_tenant is not None:
                # Store tenant_id directly on connection object (conn.info is read-only)
                conn.tenant_id = str(resolved_tenant)  # type: ignore[attr-defined]
                # Set GUCs for RLS policies used by corporate schema and legacy policies
                try:
                    with conn.cursor() as _gcur:
                        _gcur.execute("SELECT set_config('app.current_organization_id', %s, true)", (str(resolved_tenant),))
                        _gcur.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(resolved_tenant),))
                except Exception:
                    # Do not fail connection acquisition if GUC setting fails
                    logger.debug("Failed to set tenant GUCs on connection", exc_info=True)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def init_db() -> None:
    """
    Historical sqlite helper; retained for API compatibility.

    PostgreSQL environments rely on the migration engine (`run_migrations.py`)
    so this function becomes a no-op aside from the informational log.
    """
    logger.info("PostgreSQL environment detected - migrations handled via Alembic runner.")


def _prepare_statement(sql: str) -> str:
    """Normalize SQL for psycopg2 execution."""
    statement = convert_query(sql)
    # Commented-out PRAGMA statements are returned as "-- ..." - skip execution.
    if statement.strip().startswith("--"):
        logger.debug("Skipping commented statement: %s", statement.strip())
        return ""
    return statement


def query(conn: ConnectionLike, sql: str, params: Tuple[Any, ...] = ()) -> List[DictRow]:
    """Execute a SELECT statement and return DictCursor rows."""
    statement = _prepare_statement(sql)
    if not statement:
        return []

    parameters = tuple(convert_params(tuple(params)))
    start = perf_counter()

    with conn.cursor() as cursor:
        cursor.execute(statement, parameters)
        rows = cursor.fetchall()

    duration_ms = (perf_counter() - start) * 1000
    _log_query_duration(statement, parameters, duration_ms)
    return rows


def execute(conn: ConnectionLike, sql: str, params: Tuple[Any, ...] = ()) -> Any:
    """
    Execute a data-modifying statement.

    Returns the first column from a RETURNING clause when present; otherwise
    falls back to the cursor rowcount.
    """
    statement = _prepare_statement(sql)
    if not statement:
        return 0

    parameters = tuple(convert_params(tuple(params)))
    start = perf_counter()

    with conn.cursor() as cursor:
        cursor.execute(statement, parameters)
        result: Any = None
        if cursor.description:
            fetched = cursor.fetchone()
            if fetched is not None:
                result = fetched[0] if len(fetched) == 1 else fetched
        if result is None:
            result = cursor.rowcount

    duration_ms = (perf_counter() - start) * 1000
    _log_query_duration(statement, parameters, duration_ms)
    return result


def execute_many(conn: ConnectionLike, sql: str, params_list: Iterable[Tuple[Any, ...]]) -> int:
    """Execute a statement for a sequence of parameter sets."""
    statement = _prepare_statement(sql)
    if not statement:
        return 0

    converted_params = [tuple(convert_params(tuple(p))) for p in params_list]
    start = perf_counter()

    with conn.cursor() as cursor:
        cursor.executemany(statement, converted_params)
        affected = cursor.rowcount

    duration_ms = (perf_counter() - start) * 1000
    _log_query_duration(statement, converted_params, duration_ms)
    return affected


def ensure_team_member_connector(
    conn: ConnectionLike,
    organization_id: int,
    team_member_id: int,
    connector_id: int,
    relationship_type: str = "primary",
    source: str = "manual",
) -> Optional[int]:
    """
    Upsert a team_member_connector record and return its identifier.
    """
    normalized_relationship = relationship_type or "primary"
    normalized_source = source or "manual"

    insert_sql = """
        INSERT INTO team_member_connectors (
            organization_id,
            team_member_id,
            connector_id,
            relationship_type,
            source,
            created_at,
            updated_at,
            last_seen_at
        )
        VALUES (%s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), NOW(), NOW(), NOW())
        ON CONFLICT (organization_id, team_member_id, connector_id)
        DO UPDATE SET
            relationship_type = COALESCE(
                NULLIF(EXCLUDED.relationship_type, ''),
                team_member_connectors.relationship_type
            ),
            source = CASE
                WHEN team_member_connectors.source IS NULL
                     OR team_member_connectors.source = ''
                     OR team_member_connectors.source = 'unknown'
                THEN COALESCE(NULLIF(EXCLUDED.source, ''), team_member_connectors.source)
                ELSE team_member_connectors.source
            END,
            last_seen_at = NOW(),
            updated_at = NOW()
        RETURNING id
    """

    connector_id_value = execute(
        conn,
        insert_sql,
        (
            organization_id,
            team_member_id,
            connector_id,
            normalized_relationship,
            normalized_source,
        ),
    )

    if connector_id_value:
        return int(connector_id_value)

    fetch_sql = """
        SELECT id
        FROM team_member_connectors
        WHERE organization_id = %s AND team_member_id = %s AND connector_id = %s
    """
    rows = query(conn, fetch_sql, (organization_id, team_member_id, connector_id))
    if rows:
        row = rows[0]
        return int(row[0]) if isinstance(row, Sequence) else int(row["id"])
    return None


def query_tenant(conn: ConnectionLike, sql: str, tenant_id: int, params: Tuple[Any, ...] = ()) -> List[DictRow]:
    """Execute a tenant-scoped SELECT query."""
    tenant_sql = f"{sql} AND tenant_id = ?" if "WHERE" in sql.upper() else f"{sql} WHERE tenant_id = ?"
    return query(conn, tenant_sql, params + (tenant_id,))


def execute_tenant(conn: ConnectionLike, sql: str, tenant_id: int, params: Tuple[Any, ...] = ()) -> Any:
    """Execute a tenant-scoped data-modifying query."""
    if sql.upper().startswith("INSERT"):
        return execute(conn, sql, params)
    tenant_sql = f"{sql} AND tenant_id = ?" if "WHERE" in sql.upper() else f"{sql} WHERE tenant_id = ?"
    return execute(conn, tenant_sql, params + (tenant_id,))


def get_prospects_secure(
    conn: ConnectionLike,
    tenant_id: int,
    user_id: Optional[int] = None,
    status: Optional[str] = None,
) -> List[DictCursor]:
    """Return prospects constrained to a tenant (and optionally user/status)."""
    sql = "SELECT * FROM prospects WHERE tenant_id = ?"
    params: List[Any] = [tenant_id]

    if user_id:
        sql += " AND user_id = ?"
        params.append(user_id)

    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY created_at DESC"
    return query(conn, sql, tuple(params))


def get_user_integrations_secure(
    conn: ConnectionLike,
    tenant_id: int,
    user_id: int,
    provider: Optional[str] = None,
) -> List[DictCursor]:
    """Return user integrations for a tenant with optional provider filter."""
    sql = "SELECT provider, key FROM user_integrations WHERE tenant_id = ? AND user_id = ?"
    params: List[Any] = [tenant_id, user_id]

    if provider:
        sql += " AND provider = ?"
        params.append(provider)

    return query(conn, sql, tuple(params))


def get_tenant_settings_secure(
    conn: ConnectionLike,
    tenant_id: int,
    setting_key: Optional[str] = None,
) -> List[DictCursor]:
    """Return tenant settings for the specified tenant."""
    sql = "SELECT setting_key, setting_value FROM tenant_settings WHERE tenant_id = ?"
    params: List[Any] = [tenant_id]

    if setting_key:
        sql += " AND setting_key = ?"
        params.append(setting_key)

    return query(conn, sql, tuple(params))


def create_job_secure(
    conn: ConnectionLike,
    tenant_id: int,
    user_id: int,
    job_type: str,
    status: str,
    payload: str,
) -> int:
    """Insert a job_runs record and return the new identifier."""
    sql = """
        INSERT INTO job_runs (tenant_id, user_id, type, status, payload, created_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        RETURNING id
    """
    job_id = execute(conn, sql, (tenant_id, user_id, job_type, status, payload))
    return int(job_id)


def check_job_idempotency(conn: ConnectionLike, tenant_id: int, idempotency_key: str) -> Optional[DictRow]:
    """Return job idempotency record for given tenant/idempotency key."""
    sql = "SELECT id, status FROM job_idempotency WHERE tenant_id = ? AND idempotency_key = ?"
    rows = query(conn, sql, (tenant_id, idempotency_key))
    return rows[0] if rows else None


def create_job_idempotent(
    conn: ConnectionLike,
    tenant_id: int,
    idempotency_key: str,
    prospect_id: int,
    job_type: str,
) -> Optional[int]:
    """Insert or upsert a job idempotency record and return its identifier."""
    insert_sql = """
        INSERT INTO job_idempotency (
            tenant_id,
            idempotency_key,
            prospect_id,
            job_type,
            status,
            created_at
        )
        VALUES (%s, %s, %s, %s, 'pending', NOW())
        ON CONFLICT (tenant_id, idempotency_key)
        DO NOTHING
        RETURNING id
    """
    inserted = execute(conn, insert_sql, (tenant_id, idempotency_key, prospect_id, job_type))
    if inserted:
        return int(inserted)

    existing_sql = """
        SELECT id
        FROM job_idempotency
        WHERE tenant_id = %s AND idempotency_key = %s
    """
    rows = query(conn, existing_sql, (tenant_id, idempotency_key))
    if rows:
        row = rows[0]
        return int(row[0]) if isinstance(row, Sequence) else int(row["id"])
    return None
