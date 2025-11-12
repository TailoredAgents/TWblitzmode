"""
Tenant-aware data access layer.

Centralises database access so every query executed against multi-tenant tables
requires an explicit tenant scope. This module should be the only entry-point
for new persistence code inside the API layer.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

from .mt_db import get_db

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import only used for table metadata
    from services.tenant_isolation_service import (  # type: ignore
        TenantIsolationService,
    )

    _MULTI_TENANT_TABLES = set(TenantIsolationService.MULTI_TENANT_TABLES.keys())
    _SYSTEM_TABLES = set(TenantIsolationService.SYSTEM_TABLES)
except Exception:  # pragma: no cover - fallback if service unavailable
    _MULTI_TENANT_TABLES = {
        "tenants",
        "users",
        "organizations",
        "organization_settings",
        "team_members",
        "prospects",
        "prospect_mutuals",
        "job_runs",
        "job_idempotency",
        "linkedin_sessions",
        "cookie_jars",
        "user_integrations",
        "user_preferences",
        "tenant_settings",
        "outreach_queue",
        "audit_events",
    }
    _SYSTEM_TABLES: set[str] = {
        "alembic_version",
        "migration_history",
    }


class TenantIsolationError(RuntimeError):
    """Raised when a query violates tenant isolation guarantees."""


class TenantRepository:
    """
    Tenant-scoped repository layered on top of the sqlite3 / PostgreSQL
    connection returned by ``get_db``.
    """

    def __init__(
        self,
        tenant_id: int,
        *,
        organization_id: Optional[int] = None,
        connection: Optional[sqlite3.Connection] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.organization_id = organization_id
        self._conn = connection or get_db()
        self._conn.row_factory = sqlite3.Row
        logger.debug("TenantRepository initialised for tenant %s", tenant_id)

    # ------------------------------------------------------------------ #
    # context manager helpers
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "TenantRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - context cleanup
        self.close()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            logger.debug("TenantRepository connection closed for tenant %s", self.tenant_id)

    # ------------------------------------------------------------------ #
    # DDL helpers
    # ------------------------------------------------------------------ #
    def ensure_column(self, table: str, column: str, ddl_fragment: str) -> None:
        """Ensure a table contains the specified column."""

        if not self.table_has_column(table, column):
            logger.info("Adding missing column %s.%s", table, column)
            try:
                cursor = self._conn.cursor()
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {ddl_fragment}")
                self._conn.commit()
            except Exception:
                logger.error(
                    "[TenantRepository.ensure_column] Failed to add column %s.%s",
                    table,
                    column,
                    exc_info=True,
                )
                self._reset_connection_on_error()
                raise

    def table_has_column(self, table: str, column: str) -> bool:
        try:
            cursor = self._conn.execute(f"PRAGMA table_info({table})")
            return any(row[1] == column for row in cursor.fetchall())
        except Exception:
            logger.debug(
                "[TenantRepository.table_has_column] Failed PRAGMA lookup for %s.%s",
                table,
                column,
                exc_info=True,
            )
            self._reset_connection_on_error()
            return False

    def execute_ddl(self, sql: str) -> None:
        logger.debug("Executing DDL: %s", sql.splitlines()[0])
        try:
            cursor = self._conn.cursor()
            cursor.execute(sql)
            self._conn.commit()
        except Exception:
            logger.error("[TenantRepository.execute_ddl] DDL failed", exc_info=True)
            self._reset_connection_on_error()
            raise

    # ------------------------------------------------------------------ #
    # Data access helpers
    # ------------------------------------------------------------------ #
    def fetch_one(self, sql: str, params: Optional[Mapping[str, Any]] = None):
        logger.debug(f"[TenantRepository.fetch_one] Executing query: {sql[:200]}, params: {params}")
        try:
            cursor = self._execute(sql, params)
            result = cursor.fetchone()
            logger.debug(f"[TenantRepository.fetch_one] Query returned: {result is not None}")
            return result
        except Exception as e:
            logger.error(
                f"[TenantRepository.fetch_one] Query failed: {type(e).__name__}: {str(e)}",
                exc_info=True
            )
            raise

    def fetch_all(self, sql: str, params: Optional[Mapping[str, Any]] = None):
        cursor = self._execute(sql, params)
        return cursor.fetchall()

    def execute(self, sql: str, params: Optional[Mapping[str, Any]] = None) -> int:
        cursor = self._execute(sql, params)
        self._conn.commit()
        return cursor.rowcount

    def insert_and_get_id(
        self, sql: str, params: Optional[Mapping[str, Any]] = None
    ) -> int:
        cursor = self._execute(sql, params)
        self._conn.commit()
        return getattr(cursor, "lastrowid", 0)

    def executemany(
        self, sql: str, param_list: Iterable[Mapping[str, Any]]
    ) -> int:
        validated_sql = self._assert_tenant_scope(sql)
        cursor = self._conn.cursor()
        enriched_params = [self._bind_params(validated_sql, params) for params in param_list]
        try:
            cursor.executemany(validated_sql, enriched_params)
            self._conn.commit()
            return cursor.rowcount
        except Exception:
            logger.error("[TenantRepository.executemany] Execution failed", exc_info=True)
            self._reset_connection_on_error()
            raise

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _execute(
        self, sql: str, params: Optional[Mapping[str, Any]] = None
    ) -> sqlite3.Cursor:
        try:
            validated_sql = self._assert_tenant_scope(sql)
            bound_params = self._bind_params(validated_sql, params or {})
            cursor = self._conn.cursor()
            logger.debug(f"[TenantRepository._execute] Executing: {validated_sql[:200]}")
            cursor.execute(validated_sql, bound_params)
            logger.debug(f"[TenantRepository._execute] Execution successful")
            return cursor
        except Exception as e:
            logger.error(
                f"[TenantRepository._execute] Execution failed: {type(e).__name__}: {str(e)}",
                exc_info=True
            )
            logger.error(f"[TenantRepository._execute] Failed SQL: {sql[:500]}")
            logger.error(f"[TenantRepository._execute] Failed params: {params}")
            self._reset_connection_on_error()
            raise

    def _reset_connection_on_error(self) -> None:
        """Rollback the current transaction and ensure future queries can succeed."""
        conn = getattr(self, "_conn", None)
        if conn is None:
            return
        try:
            rollback = getattr(conn, "rollback", None)
            if callable(rollback):
                rollback()
                return
        except Exception:
            logger.debug("[TenantRepository] Rollback failed, attempting to replace connection", exc_info=True)
        try:
            close = getattr(conn, "close", None)
            if callable(close):
                close()
        except Exception:
            logger.debug("[TenantRepository] Failed to close poisoned connection", exc_info=True)
        try:
            self._conn = get_db()
            logger.debug("TenantRepository connection refreshed after failure for tenant %s", self.tenant_id)
        except Exception:
            logger.exception("TenantRepository failed to obtain fresh connection after error")

    def _assert_tenant_scope(self, sql: str) -> str:
        normalized = _normalize_sql(sql)

        if not normalized:  # pragma: no cover - defensive guard
            raise TenantIsolationError("Empty SQL statement is not permitted")

        statement = normalized.split(" ", 1)[0]

        if statement in {"pragma", "create", "alter", "drop", "vacuum"}:
            return sql

        referenced_tables = {
            table
            for table in _MULTI_TENANT_TABLES
            if re.search(rf"\b{table}\b", normalized)
        } - _SYSTEM_TABLES

        if not referenced_tables:
            return sql

        if "tenant_id" not in normalized:
            raise TenantIsolationError(
                f"Query references multi-tenant tables {sorted(referenced_tables)} "
                "without tenant_id filter"
            )

        if statement == "select" and " where " in normalized:
            where_clause = normalized.split(" where ", 1)[1]
            if "tenant_id" not in where_clause:
                raise TenantIsolationError(
                    "SELECT statements must include tenant_id predicate in WHERE clause"
                )
        elif statement in {"update", "delete"}:
            if " where " not in normalized or "tenant_id" not in normalized.split(" where ", 1)[1]:
                raise TenantIsolationError(
                    f"{statement.upper()} statements must constrain tenant_id in WHERE clause"
                )
        elif statement == "insert":
            if "tenant_id" not in normalized.split("values", 1)[0]:
                raise TenantIsolationError(
                    "INSERT statements must supply tenant_id column"
                )

        return sql

    def _bind_params(
        self, sql: str, params: Mapping[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(params, Mapping):
            raise TenantIsolationError("Parameters must be provided as a mapping")

        bound: Dict[str, Any] = dict(params)

        if ":tenant_id" in sql or "?tenant_id" in sql:
            bound.setdefault("tenant_id", self.tenant_id)

        if ":organization_id" in sql and self.organization_id is not None:
            bound.setdefault("organization_id", self.organization_id)

        return bound


@contextmanager
def tenant_repository(
    tenant_id: int, *, organization_id: Optional[int] = None
) -> Iterator[TenantRepository]:
    repo = TenantRepository(tenant_id, organization_id=organization_id)
    try:
        yield repo
    finally:
        repo.close()


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().lower()
