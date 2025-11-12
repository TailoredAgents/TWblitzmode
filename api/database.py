"""
Database connection module supporting both SQLite and PostgreSQL
Automatically detects database type from DATABASE_URL
"""
import os
import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Union
from contextlib import contextmanager, nullcontext
import time
import random

from scripts.utils.postgres import DEFAULT_TEST_DSN, resolve_required_dsn
from src.services.database_mode import (
    describe_db_mode,
    get_db_mode,
    is_legacy_mode,
    is_native_mode,
)
from src.services.database_logging import (
    log_query_failure,
    log_query_success,
    scoped_query_context,
    start_query_log,
)

_COLUMN_CACHE: Dict[tuple[int, str, str, str], bool] = {}
_INSERT_REGEX = re.compile(
    r"INSERT\s+INTO\s+(?P<table>(?:\"[^\"]+\"|\w+)(?:\.(?:\"[^\"]+\"|\w+))?)\s*(?:\((?P<columns>[^)]+)\))?",
    re.IGNORECASE,
)


def clear_column_cache():
    """Clear the global column cache. Useful for testing or after schema changes."""
    global _COLUMN_CACHE
    _COLUMN_CACHE.clear()


def _convert_placeholders(query: str) -> str:
    """Convert SQLite-style ? placeholders to psycopg2 %s placeholders while respecting string literals."""
    result: List[str] = []
    in_single = False
    in_double = False
    i = 0
    length = len(query)

    while i < length:
        char = query[i]
        if char == "'" and not in_double:
            result.append(char)
            if in_single:
                # Handle escaped single quotes ''
                if i + 1 < length and query[i + 1] == "'":
                    result.append("'")
                    i += 2
                    continue
                in_single = False
            else:
                in_single = True
            i += 1
            continue
        if char == '"' and not in_single:
            result.append(char)
            if in_double:
                if i + 1 < length and query[i + 1] == '"':
                    result.append('"')
                    i += 2
                    continue
                in_double = False
            else:
                in_double = True
            i += 1
            continue
        if char == "?" and not in_single and not in_double:
            result.append("%s")
            i += 1
            continue

        if char == ":" and not in_single and not in_double:
            # Preserve PostgreSQL type casts (e.g., ::json)
            if i + 1 < length and query[i + 1] == ":":
                result.append("::")
                i += 2
                continue

            j = i + 1
            if j < length and (query[j].isalpha() or query[j] == "_"):
                while j < length and (query[j].isalnum() or query[j] in ("_", "$")):
                    j += 1

                name = query[i + 1 : j]
                if name:
                    result.append(f"%({name})s")
                    i = j
                    continue

            # Not a recognized named parameter; fall through

        result.append(char)
        i += 1

    return "".join(result)


def _normalize_identifier(identifier: str) -> tuple[str, str]:
    """Split table identifier into schema and table segments."""
    identifier = identifier.strip()
    if identifier.startswith('"') and identifier.endswith('"'):
        identifier = identifier[1:-1]

    if "." in identifier:
        schema, table = identifier.split(".", 1)
    else:
        schema, table = "public", identifier

    schema = schema.strip('"').lower()
    table = table.strip('"').lower()
    return schema, table


def _table_has_column(connection, schema: str, table: str, column: str) -> bool:
    """Check whether a PostgreSQL table defines a specific column, with caching."""
    # Column caching is DISABLED by default to prevent schema change issues.
    # To enable caching (minimal performance benefit), set ENABLE_COLUMN_CACHE=true
    use_cache = os.environ.get("ENABLE_COLUMN_CACHE", "").lower() in ("1", "true", "yes")

    cache_key = (id(connection), schema.lower(), table.lower(), column.lower())
    if use_cache and cache_key in _COLUMN_CACHE:
        return _COLUMN_CACHE[cache_key]

    exists = False
    try:
        with connection.cursor() as meta_cursor:
            meta_cursor.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s AND column_name = %s
                LIMIT 1
                """,
                (schema, table, column),
            )
            exists = meta_cursor.fetchone() is not None
    except Exception:
        exists = False

    if use_cache:
        _COLUMN_CACHE[cache_key] = exists
    return exists


def _prepare_postgres_query(cursor, query: str) -> tuple[str, bool]:
    """Convert placeholders and optionally append RETURNING id when safe."""
    import logging
    logger = logging.getLogger(__name__)

    converted_query = _convert_placeholders(query)
    logger.debug(f"[_prepare_postgres_query] Original query: {query[:200]}")
    logger.debug(f"[_prepare_postgres_query] Converted query: {converted_query[:200]}")

    stripped = converted_query.lstrip()
    upper = stripped.upper()

    if not upper.startswith("INSERT") or "RETURNING" in upper:
        logger.debug(f"[_prepare_postgres_query] Skipping RETURNING append (not INSERT or already has RETURNING)")
        return converted_query, False

    match = _INSERT_REGEX.match(stripped)
    if not match:
        return converted_query, False

    table_identifier = match.group("table")
    columns_segment = match.group("columns")
    schema, table = _normalize_identifier(table_identifier)

    column_names: List[str] = []
    if columns_segment:
        column_names = [col.strip().strip('"') for col in columns_segment.split(",") if col.strip()]

    has_id_column = any(col.lower() == "id" for col in column_names)
    if not has_id_column:
        try:
            connection = cursor.connection
        except AttributeError:
            connection = None
        if connection is None or not _table_has_column(connection, schema, table, "id"):
            return converted_query, False

    prepared = converted_query.rstrip().rstrip(";")
    final_query = f"{prepared} RETURNING id"
    logger.debug(f"[_prepare_postgres_query] Final query with RETURNING: {final_query[:200]}")
    return final_query, True

class PostgresCursorCompat:
    """Cursor compatibility wrapper that applies tenant-safe query conversions."""

    def __init__(self, cursor):
        self._cursor = cursor
        self._lastrowid = None
        self._logs_queries = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.close()
        finally:
            return False

    def execute(
        self,
        query: str,
        params=None,
        *,
        query_label: Optional[str] = None,
        query_metadata: Optional[Mapping[str, Any]] = None,
    ):
        import logging
        logger = logging.getLogger(__name__)

        prepared_query, appended_returning = _prepare_postgres_query(self._cursor, query)
        self._lastrowid = None

        logger.debug(f"[PostgresCursorCompat.execute] Prepared query: {prepared_query[:200]}")
        logger.debug(f"[PostgresCursorCompat.execute] Params: {params}")

        tenant_id = getattr(getattr(self._cursor, "connection", None), "tenant_id", None)
        context_guard = (
            scoped_query_context(label=query_label, metadata=query_metadata)
            if (query_label or query_metadata)
            else nullcontext()
        )

        with context_guard:
            query_context = start_query_log(
                prepared_query,
                params if params is not None else (),
                tenant_id=tenant_id,
                origin="PostgresCursorCompat.execute",
                label=query_label,
                metadata=query_metadata,
            )

            try:
                if params is None:
                    self._cursor.execute(prepared_query)
                else:
                    self._cursor.execute(prepared_query, params)
            except Exception as e:
                log_query_failure(query_context, e)
                logger.error(
                    f"[PostgresCursorCompat.execute] Query execution failed: {type(e).__name__}: {str(e)}"
                )
                logger.error(f"[PostgresCursorCompat.execute] Failed query: {prepared_query[:500]}")
                logger.error(f"[PostgresCursorCompat.execute] Connection status: {self._cursor.connection.status}")
                try:
                    logger.warning("[PostgresCursorCompat.execute] Attempting transaction rollback")
                    self._cursor.connection.rollback()
                    logger.info("[PostgresCursorCompat.execute] Rollback successful")
                except Exception as rollback_error:  # pragma: no cover - defensive rollback
                    logger.error(
                        f"[PostgresCursorCompat.execute] Rollback failed: {type(rollback_error).__name__}: {str(rollback_error)}"
                    )
                raise

        if appended_returning:
            result = self._cursor.fetchone()
            if isinstance(result, dict):
                self._lastrowid = result.get("id")
            elif isinstance(result, (tuple, list)):
                self._lastrowid = result[0] if result else None
            else:
                self._lastrowid = result

        log_query_success(query_context, rowcount=getattr(self._cursor, "rowcount", None))

        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._lastrowid


    @property
    def description(self):
        return self._cursor.description

    def close(self):
        self._cursor.close()

class Psycopg2Compat:
    """
    Minimal adapter so existing code that does:
        conn.execute(...).fetchone()/fetchall()
        conn.commit()
        conn.close()
    still works on psycopg2.
    """
    def __init__(self, conn):
        self._conn = conn
        self._cur = None
        self._lastrowid = None

    def cursor(self):
        """Return a compatibility cursor that converts ? to %s"""
        import psycopg2.extras
        try:
            real_cursor = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        except TypeError:
            real_cursor = self._conn.cursor()
        return PostgresCursorCompat(real_cursor)

    def execute(
        self,
        query: str,
        params=None,
        *,
        query_label: Optional[str] = None,
        query_metadata: Optional[Mapping[str, Any]] = None,
    ):
        compat_cursor = self.cursor()
        compat_cursor.execute(
            query,
            params,
            query_label=query_label,
            query_metadata=query_metadata,
        )
        self._cur = compat_cursor
        self._lastrowid = compat_cursor.lastrowid
        return self  # allow chaining .fetchone() / .fetchall()

    def fetchone(self):
        return self._cur.fetchone() if self._cur else None

    def fetchall(self):
        return self._cur.fetchall() if self._cur else []

    @property
    def rowcount(self):
        return self._cur.rowcount if self._cur else -1

    @property
    def lastrowid(self):
        # Return the stored lastrowid from RETURNING clause
        return getattr(self, "_lastrowid", None)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            if self._cur:
                self._cur.close()
        finally:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()

logger = logging.getLogger(__name__)

# Freeze the current rollout mode so we can toggle adapters during the refactor.
DB_COMPAT_MODE = get_db_mode()
logger.debug("api.database activated with DB_COMPAT_MODE=%s", describe_db_mode())


def using_legacy_adapter() -> bool:
    """Return True when the shim layer should stay in place."""
    return is_legacy_mode()


def using_native_adapter() -> bool:
    """Return True when callers can opt into the native PostgreSQL adapter."""
    return is_native_mode()

# Database URL from environment
DATABASE_URL = resolve_required_dsn("DATABASE_URL", "TEST_DATABASE_URL", default=DEFAULT_TEST_DSN)


class _ConnectionContext:
    """Wrapper that exposes a ``connection`` attribute for legacy call sites."""

    __slots__ = ("_compat", "connection")

    def __init__(self, compat: Psycopg2Compat):
        self._compat = compat
        self.connection = getattr(compat, "_conn", None)

    def __getattr__(self, item):
        return getattr(self._compat, item)

    def commit(self):
        return self._compat.commit()

    def rollback(self):
        return self._compat.rollback()

    def close(self):
        return self._compat.close()


class DatabaseConnection:
    """Unified database connection for SQLite and PostgreSQL"""
    
    def __init__(self, url: str = DATABASE_URL):
        self.url = self._normalize_url(url)
        self.is_postgres = self._is_postgres(self.url)
        self.connection = None
        
    def _normalize_url(self, url: str) -> str:
        """Normalize database URL"""
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql://", 1)
        if not url.startswith("postgresql://"):
            raise RuntimeError(
                f"DatabaseConnection only supports PostgreSQL DSNs, received '{url}'"
            )
        return url
    
    def _is_postgres(self, url: str) -> bool:
        """Check if URL is for PostgreSQL"""
        return url.startswith("postgresql://") or url.startswith("postgres://")
    
    def connect(self):
        """Create database connection"""
        max_retries = 5

        try:
            import psycopg2
            import psycopg2.extras
        except ImportError as exc:  # pragma: no cover - environment misconfiguration
            raise RuntimeError(
                "psycopg2 is required for PostgreSQL connectivity. Install with 'pip install psycopg2-binary'."
            ) from exc

        for attempt in range(max_retries):
            try:
                self.connection = psycopg2.connect(
                    self.url,
                    cursor_factory=psycopg2.extras.RealDictCursor,
                )
                self.connection.autocommit = False
                logger.info("Connected to PostgreSQL database")
                return self.connection
            except psycopg2.Error as exc:
                if attempt < max_retries - 1:
                    wait_time = (2**attempt) + random.uniform(0, 1)
                    logger.warning(
                        "Database connection attempt %s failed: %s. Retrying in %.1fs...",
                        attempt + 1,
                        exc,
                        wait_time,
                    )
                    time.sleep(wait_time)
                    continue
                raise

    def execute(
        self,
        query: str,
        params: Optional[tuple] = None,
        *,
        query_label: Optional[str] = None,
        query_metadata: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        """Execute a query with PostgreSQL compatibility conversions."""
        if not self.connection:
            self.connect()

        query = self._convert_to_postgres(query)
        if params:
            query = self._convert_placeholders(query)

        cursor = self.connection.cursor()
        tenant_id = getattr(self.connection, "tenant_id", None)
        context_guard = (
            scoped_query_context(label=query_label, metadata=query_metadata)
            if (query_label or query_metadata)
            else nullcontext()
        )

        with context_guard:
            query_context = start_query_log(
                query,
                params or (),
                tenant_id=tenant_id,
                origin="DatabaseConnection.execute",
                label=query_label,
                metadata=query_metadata,
            )

            try:
                cursor.execute(query, params or ())
            except Exception as e:
                log_query_failure(query_context, e)
                logger.error(
                    f"[DatabaseConnection.execute] Query execution failed: {type(e).__name__}: {str(e)}"
                )
                logger.error(f"[DatabaseConnection.execute] Failed query: {query[:500]}")
                logger.error(f"[DatabaseConnection.execute] Connection status: {self.connection.status}")
                try:
                    logger.warning("[DatabaseConnection.execute] Attempting transaction rollback")
                    self.connection.rollback()
                    logger.info("[DatabaseConnection.execute] Rollback successful")
                except Exception as rollback_error:  # pragma: no cover - defensive rollback
                    logger.error(
                        f"[DatabaseConnection.execute] Rollback failed: {type(rollback_error).__name__}: {str(rollback_error)}"
                    )
                raise

        log_query_success(query_context, rowcount=getattr(cursor, "rowcount", None))
        return cursor
    
    def fetchone(self, query: str, params: Optional[tuple] = None) -> Optional[Dict]:
        """Fetch one row as dictionary"""
        cursor = self.execute(query, params)
        result = cursor.fetchone()
        if result is None:
            return None
        return dict(result)
    
    def fetchall(self, query: str, params: Optional[tuple] = None) -> List[Dict]:
        """Fetch all rows as list of dictionaries"""
        cursor = self.execute(query, params)
        results = cursor.fetchall()
        return [dict(row) for row in results]
    
    def commit(self):
        """Commit transaction"""
        if self.connection:
            self.connection.commit()
    
    def rollback(self):
        """Rollback transaction"""
        if self.connection:
            self.connection.rollback()
    
    def close(self):
        """Close connection"""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def _convert_to_postgres(self, query: str) -> str:
        """Convert SQLite SQL to PostgreSQL SQL"""
        # Common conversions
        conversions = {
            "datetime('now')": "NOW()",
            "CURRENT_TIMESTAMP": "NOW()",
            "INTEGER PRIMARY KEY": "SERIAL PRIMARY KEY",
            "AUTOINCREMENT": "",
            "PRAGMA": "-- PRAGMA",  # Comment out SQLite pragmas
        }
        
        for sqlite_syntax, pg_syntax in conversions.items():
            query = query.replace(sqlite_syntax, pg_syntax)
        
        return query

    def _convert_placeholders(self, query: str) -> str:
        """Shim: delegate to shared placeholder conversion helper."""
        return _convert_placeholders(query)
    
    @property
    def lastrowid(self) -> Optional[int]:
        """Get last inserted row ID"""
        cursor = self.connection.cursor()
        cursor.execute("SELECT lastval()")
        row = cursor.fetchone()
        return row[0] if row else None


@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    compat = _native_get_db() if using_native_adapter() else _legacy_get_db()
    context = _ConnectionContext(compat)
    try:
        yield context
        context.commit()
    except Exception as exc:
        try:
            from fastapi import HTTPException as _FastAPIHTTPException  # type: ignore
        except ImportError:  # pragma: no cover - defensive
            skip_rollback = False
        else:
            skip_rollback = isinstance(exc, _FastAPIHTTPException)

        if not skip_rollback:
            context.rollback()
        raise
    finally:
        context.close()


def get_db():
    """Get database connection (compatible with existing code)"""
    compat = _native_get_db() if using_native_adapter() else _legacy_get_db()
    return compat


def _legacy_get_db() -> Psycopg2Compat:
    """Return a Psycopg2Compat wrapper for legacy callers."""
    connection = DatabaseConnection()
    connection.connect()
    return Psycopg2Compat(connection.connection)


def _native_get_db() -> Psycopg2Compat:
    """Return a compat wrapper backed by the native connection pool."""
    try:
        from api.mt_db import get_db as _mt_get_db  # Local import to avoid circular load issues
    except ImportError as exc:  # pragma: no cover - defensive
        raise RuntimeError("api.mt_db must be available when DB_COMPAT_MODE=native") from exc
    native_connection = _mt_get_db()
    return Psycopg2Compat(native_connection)


# PostgreSQL schema (converted from SQLite)
POSTGRES_SCHEMA = """
-- Tenants table
CREATE TABLE IF NOT EXISTS tenants (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Users table
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  tenant_id INTEGER,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  first_name TEXT,
  last_name TEXT,
  role TEXT NOT NULL DEFAULT 'user',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- Add tenant_id column if it doesn't exist (for backwards compatibility)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_name = 'users' AND column_name = 'tenant_id'
  ) THEN
    ALTER TABLE users ADD COLUMN tenant_id INTEGER;
    -- Set default tenant for existing users
    UPDATE users SET tenant_id = 1 WHERE tenant_id IS NULL;
  END IF;
END$$;
CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Prospects table with proper timestamps
CREATE TABLE IF NOT EXISTS prospects (
  id SERIAL PRIMARY KEY,
  tenant_id INTEGER,
  user_id INTEGER,
  full_name TEXT,
  linkedin_url TEXT NOT NULL,
  linkedin_handle TEXT,
  company TEXT,
  headline TEXT,
  location TEXT,
  last_checked_at TIMESTAMPTZ,
  linkedin_aco_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  UNIQUE(tenant_id, linkedin_url)
);
CREATE INDEX IF NOT EXISTS idx_prospects_tenant ON prospects(tenant_id);
CREATE INDEX IF NOT EXISTS idx_prospects_user ON prospects(user_id);
CREATE INDEX IF NOT EXISTS idx_prospects_linkedin ON prospects(linkedin_url);
CREATE UNIQUE INDEX IF NOT EXISTS uq_prospects_tenant_handle ON prospects(tenant_id, linkedin_handle);
CREATE INDEX IF NOT EXISTS idx_prospects_linkedin_handle ON prospects(linkedin_handle);

-- User integrations table
CREATE TABLE IF NOT EXISTS user_integrations (
  id SERIAL PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  user_id INTEGER,
  provider TEXT NOT NULL,
  key TEXT,
  encrypted INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_user_integrations_tenant ON user_integrations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_integrations_user ON user_integrations(user_id);

-- Tenant settings table
CREATE TABLE IF NOT EXISTS tenant_settings (
  id SERIAL PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  setting_key TEXT NOT NULL,
  setting_value TEXT,
  encrypted INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  UNIQUE(tenant_id, setting_key)
);
CREATE INDEX IF NOT EXISTS idx_tenant_settings ON tenant_settings(tenant_id);

-- Job runs table
CREATE TABLE IF NOT EXISTS job_runs (
  id SERIAL PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  user_id INTEGER,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  external_id TEXT,
  metadata_json TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_job_runs_tenant ON job_runs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_job_runs_status ON job_runs(status);

-- Prospect mutuals table
CREATE TABLE IF NOT EXISTS prospect_mutuals (
  id SERIAL PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  prospect_id INTEGER NOT NULL,
  mutual_full_name TEXT NOT NULL,
  mutual_linkedin_url TEXT NOT NULL,
  mutual_headline TEXT,
  mutual_company TEXT,
  network_distance TEXT,
  scraped_via TEXT NOT NULL DEFAULT 'unknown',
  scraped_at TIMESTAMPTZ DEFAULT NOW(),
  run_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  FOREIGN KEY (prospect_id) REFERENCES prospects(id) ON DELETE CASCADE,
  UNIQUE(prospect_id, mutual_linkedin_url)
);
CREATE INDEX IF NOT EXISTS idx_mutuals_tenant ON prospect_mutuals(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mutuals_prospect ON prospect_mutuals(prospect_id);

-- Outreach queue table
CREATE TABLE IF NOT EXISTS outreach_queue (
  id SERIAL PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  prospect_id INTEGER NOT NULL,
  mutual_id INTEGER,
  message_template TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  scheduled_for TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  FOREIGN KEY (prospect_id) REFERENCES prospects(id) ON DELETE CASCADE,
  FOREIGN KEY (mutual_id) REFERENCES prospect_mutuals(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_outreach_tenant ON outreach_queue(tenant_id);
CREATE INDEX IF NOT EXISTS idx_outreach_prospect ON outreach_queue(prospect_id);
CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach_queue(status);

-- Create updated_at trigger function (safe to replace)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Add triggers for updated_at (idempotent - only create if they don't exist)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'update_users_updated_at'
  ) THEN
    CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'update_prospects_updated_at'
  ) THEN
    CREATE TRIGGER update_prospects_updated_at
    BEFORE UPDATE ON prospects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'update_user_integrations_updated_at'
  ) THEN
    CREATE TRIGGER update_user_integrations_updated_at
    BEFORE UPDATE ON user_integrations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'update_tenant_settings_updated_at'
  ) THEN
    CREATE TRIGGER update_tenant_settings_updated_at
    BEFORE UPDATE ON tenant_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
  END IF;
END$$;
"""


def ensure_timestamps_and_trigger(conn, table: str):
    """Add created_at/updated_at and ensure trigger keeps updated_at fresh"""
    # Ensure created_at / updated_at exist
    conn.execute(f"""
        ALTER TABLE IF EXISTS {table}
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    """)
    conn.execute(f"""
        ALTER TABLE IF EXISTS {table}
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    """)

    # Create or replace the trigger function (named dollar-quote to avoid quoting issues)
    conn.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $func$
        BEGIN
          NEW.updated_at = NOW();
          RETURN NEW;
        END;
        $func$ LANGUAGE plpgsql
    """)

    # Make trigger idempotent by drop+create
    conn.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table}")
    conn.execute(f"""
        CREATE TRIGGER update_{table}_updated_at
        BEFORE UPDATE ON {table}
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

def ensure_enum(conn, typname: str, values: list):
    """Create enum type if it doesn't exist"""
    row = conn.execute("SELECT 1 FROM pg_type WHERE typname=%s", (typname,)).fetchone()
    if not row:
        values_str = ', '.join(f"'{v}'" for v in values)
        conn.execute(f"CREATE TYPE {typname} AS ENUM ({values_str})")

def ensure_core_tables(conn):
    """Create missing core tables for the application"""
    # Add linkedin_handle column for better uniqueness
    try:
        conn.execute("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS linkedin_handle TEXT")
    except:
        pass
    
    # Backfill handles from existing URLs
    try:
        conn.execute(r"""
            UPDATE prospects 
            SET linkedin_handle = LOWER(
                REGEXP_REPLACE(
                    REGEXP_REPLACE(linkedin_url, '^https?://(www\.)?linkedin\.com/in/', ''),
                    '/+$', ''
                )
            )
            WHERE linkedin_handle IS NULL AND linkedin_url IS NOT NULL
        """)
    except:
        pass
    
    # Remove duplicates before creating unique index
    try:
        conn.execute("""
            WITH duplicates AS (
                SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY tenant_id, linkedin_handle ORDER BY id) AS rn
                FROM prospects
                WHERE linkedin_handle IS NOT NULL
            )
            DELETE FROM prospects
            WHERE id IN (
                SELECT id FROM duplicates WHERE rn > 1
            )
        """)
    except:
        pass
    
    # Create unique index on tenant + handle (more reliable than URL)
    try:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_prospects_tenant_handle
            ON prospects(tenant_id, linkedin_handle)
        """)
    except:
        pass  # May fail if there are duplicates - handle manually if needed

    # contacts (introducers directory)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER,
            full_name TEXT NOT NULL,
            email TEXT,
            linkedin_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_contacts_tenant ON contacts(tenant_id)")

    # mutual_connections (results from Apify)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mutual_connections (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER,
            prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
            connector_name TEXT NOT NULL,
            connector_profile_url TEXT,
            connector_linkedin_id TEXT,
            shared_connection_count INTEGER,
            raw JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_mutual_connections_prospect ON mutual_connections(prospect_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_mutual_connections_tenant ON mutual_connections(tenant_id)")

    # outreach_queue (tracks who will intro whom)
    ensure_enum(conn, "outreach_status", ["queued", "sent", "failed", "skipped"])
    conn.execute("""
        CREATE TABLE IF NOT EXISTS outreach_queue (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER,
            prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
            contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            message_template TEXT,
            linkedin_url TEXT,
            message TEXT,
            provider TEXT,
            container_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_outreach_queue_tenant ON outreach_queue(tenant_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_outreach_queue_prospect ON outreach_queue(prospect_id)")

    # timestamps + update triggers on all write-heavy tables
    for table in ("users", "prospects", "contacts", "mutual_connections", "outreach_queue"):
        ensure_timestamps_and_trigger(conn, table)

def ensure_jobs_tables(conn):
    """Create job_runs and job_idempotency tables for orchestrator"""
    # job_runs table (matches SQLite schema)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_runs (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER,
            provider TEXT NOT NULL,
            job_type TEXT NOT NULL,
            external_id TEXT,
            prospect_id INTEGER,
            status TEXT NOT NULL,
            result_count INTEGER DEFAULT 0,
            error_message TEXT,
            input_data TEXT,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            webhook_received_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
            FOREIGN KEY (prospect_id) REFERENCES prospects(id) ON DELETE CASCADE
        )
    """)
    
    # Ensure provider column exists (in case table exists but column is missing)
    try:
        conn.execute("ALTER TABLE job_runs ADD COLUMN IF NOT EXISTS provider TEXT")
    except:
        pass  # Column might already exist
    
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_runs_tenant ON job_runs(tenant_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_runs_external ON job_runs(external_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_runs_prospect ON job_runs(prospect_id)")

    # job_idempotency table (matches SQLite schema)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_idempotency (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER,
            idempotency_key TEXT NOT NULL UNIQUE,
            prospect_id INTEGER,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result_data TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
            FOREIGN KEY (prospect_id) REFERENCES prospects(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_idempotency_tenant ON job_idempotency(tenant_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_idempotency_key ON job_idempotency(idempotency_key)")
    
    # Add updated_at triggers for both tables
    ensure_timestamps_and_trigger(conn, "job_runs")
    ensure_timestamps_and_trigger(conn, "job_idempotency")

def bootstrap_postgres_schema(conn):
    """Complete PostgreSQL schema bootstrap for backwards compatibility"""
    try:
        # Run the comprehensive migration script if it exists
        import os
        migration_file = os.path.join(os.path.dirname(__file__), '..', 'migrations', 'fix_production_schema.sql')
        if os.path.exists(migration_file):
            logger.info("Running production schema migration...")
            with open(migration_file, 'r') as f:
                migration_sql = f.read()
            
            # Split into individual statements and execute
            statements = [s.strip() for s in migration_sql.split(';') if s.strip() and not s.strip().startswith('--')]
            for i, statement in enumerate(statements, 1):
                try:
                    conn.execute(statement)
                    logger.debug(f"Executed migration statement {i}/{len(statements)}")
                except Exception as e:
                    # Log but continue - some statements may fail if already applied
                    logger.debug(f"Migration statement {i} warning: {e}")
        
        # Also run the existing bootstrap functions
        # Columns your app expects
        conn.execute("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS tenant_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users(tenant_id)")
        
        # Create all core tables
        ensure_core_tables(conn)
        
        # Create job tables required by orchestrator
        ensure_jobs_tables(conn)
        
        conn.commit()
        logger.info("PostgreSQL schema bootstrap completed successfully")
    except Exception as e:
        logger.warning(f"PostgreSQL schema bootstrap failed: {e}")
        # Don't fail startup, just log the issue

def is_postgres_db() -> bool:
    """Check if we're using PostgreSQL"""
    db_url = DATABASE_URL
    return db_url.startswith("postgresql://") or db_url.startswith("postgres://")

class AgentEventsDatabase:
    """Database operations for agent events"""

    def __init__(self, connection=None):
        self.connection = connection or DatabaseConnection()

    def create_agent_event(self, event_data: Dict[str, Any]) -> int:
        """Create a new agent event and return the ID"""
        if not self.connection.connection:
            self.connection.connect()

        if self.connection.is_postgres:
            cursor = self.connection.connection.cursor()
            cursor.execute("""
                INSERT INTO agent_events (
                    event_id, session_id, event_type, agent_id, level, message, suggestion,
                    tenant_id, user_id, workflow_id, task_id, metadata, organization_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                event_data.get('event_id'),
                event_data.get('session_id'),
                event_data.get('event_type'),
                event_data.get('agent_id'),
                event_data.get('level'),
                event_data.get('message'),
                event_data.get('suggestion'),
                event_data.get('tenant_id'),
                event_data.get('user_id'),
                event_data.get('workflow_id'),
                event_data.get('task_id'),
                event_data.get('metadata', '{}'),
                event_data.get('organization_id')
            ))
            result = cursor.fetchone()
            return result[0] if result else None
        else:
            cursor = self.connection.connection.cursor()
            cursor.execute("""
                INSERT INTO agent_events (
                    event_id, session_id, event_type, agent_id, level, message, suggestion,
                    tenant_id, user_id, workflow_id, task_id, metadata, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_data.get('event_id'),
                event_data.get('session_id'),
                event_data.get('event_type'),
                event_data.get('agent_id'),
                event_data.get('level'),
                event_data.get('message'),
                event_data.get('suggestion'),
                event_data.get('tenant_id'),
                event_data.get('user_id'),
                event_data.get('workflow_id'),
                event_data.get('task_id'),
                event_data.get('metadata', '{}'),
                event_data.get('organization_id')
            ))
            return cursor.lastrowid

    def get_agent_events(self, organization_id: int, limit: int = 50, offset: int = 0,
                        filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get agent events with optional filtering"""
        if not self.connection.connection:
            self.connection.connect()

        where_conditions = ["organization_id = ?"]
        params = [organization_id]

        if filters:
            if filters.get('agent_id'):
                where_conditions.append("agent_id = ?")
                params.append(filters['agent_id'])

            if filters.get('event_type'):
                where_conditions.append("event_type = ?")
                params.append(filters['event_type'])

            if filters.get('level'):
                where_conditions.append("level = ?")
                params.append(filters['level'])

        where_clause = " AND ".join(where_conditions)

        query = f"""
            SELECT * FROM agent_events
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """

        params.extend([limit, offset])

        cursor = self.connection.connection.cursor()

        if self.connection.is_postgres:
            converted_query = _convert_placeholders(query)
            cursor.execute(converted_query, params)
            return [dict(row) for row in cursor.fetchall()]
        else:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_agent_event_by_id(self, event_id: str, organization_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific agent event by ID"""
        if not self.connection.connection:
            self.connection.connect()

        query = """
            SELECT * FROM agent_events
            WHERE event_id = ? AND organization_id = ?
        """

        cursor = self.connection.connection.cursor()

        if self.connection.is_postgres:
            converted_query = _convert_placeholders(query)
            cursor.execute(converted_query, (event_id, organization_id))
            result = cursor.fetchone()
            return dict(result) if result else None
        else:
            cursor.execute(query, (event_id, organization_id))
            result = cursor.fetchone()
            return dict(result) if result else None

    def count_agent_events(self, organization_id: int, filters: Optional[Dict[str, Any]] = None) -> int:
        """Count agent events for pagination."""
        if not self.connection.connection:
            self.connection.connect()

        where_conditions = ["organization_id = ?"]
        params = [organization_id]

        if filters:
            if filters.get("agent_id"):
                where_conditions.append("agent_id = ?")
                params.append(filters["agent_id"])
            if filters.get("event_type"):
                where_conditions.append("event_type = ?")
                params.append(filters["event_type"])
            if filters.get("level"):
                where_conditions.append("level = ?")
                params.append(filters["level"])

        where_clause = " AND ".join(where_conditions)
        query = f"SELECT COUNT(*) FROM agent_events WHERE {where_clause}"

        cursor = self.connection.connection.cursor()
        if self.connection.is_postgres:
            converted_query = _convert_placeholders(query)
            cursor.execute(converted_query, params)
        else:
            cursor.execute(query, params)

        result = cursor.fetchone()
        return int(result[0]) if result else 0

    def get_events_summary(self, organization_id: int) -> Dict[str, Any]:
        """Get summary statistics for agent events"""
        if not self.connection.connection:
            self.connection.connect()

        # Get event counts by level (last 24 hours)
        level_query = """
            SELECT level, COUNT(*) as count
            FROM agent_events
            WHERE organization_id = ? AND created_at > datetime('now', '-24 hours')
            GROUP BY level
        """

        # Get event counts by type (last 24 hours)
        type_query = """
            SELECT event_type, COUNT(*) as count
            FROM agent_events
            WHERE organization_id = ? AND created_at > datetime('now', '-24 hours')
            GROUP BY event_type
            ORDER BY count DESC
            LIMIT 10
        """

        # Get active agents (last 1 hour)
        agent_query = """
            SELECT agent_id, COUNT(*) as event_count, MAX(created_at) as last_activity
            FROM agent_events
            WHERE organization_id = ? AND created_at > datetime('now', '-1 hour')
            GROUP BY agent_id
            ORDER BY last_activity DESC
        """

        if self.connection.is_postgres:
            level_query = _convert_placeholders(level_query).replace(
                "datetime('now', '-24 hours')",
                "NOW() - INTERVAL '24 hours'",
            )
            type_query = _convert_placeholders(type_query).replace(
                "datetime('now', '-24 hours')",
                "NOW() - INTERVAL '24 hours'",
            )
            agent_query = _convert_placeholders(agent_query).replace(
                "datetime('now', '-1 hour')",
                "NOW() - INTERVAL '1 hour'",
            )

        cursor = self.connection.connection.cursor()

        # Level counts
        cursor.execute(level_query, (organization_id,))
        level_counts = {row[0]: row[1] for row in cursor.fetchall()}

        # Type counts
        cursor.execute(type_query, (organization_id,))
        type_counts = [{"event_type": row[0], "count": row[1]} for row in cursor.fetchall()]

        # Active agents
        cursor.execute(agent_query, (organization_id,))
        active_agents = [{"agent_id": row[0], "event_count": row[1], "last_activity": row[2]}
                        for row in cursor.fetchall()]

        return {
            "level_counts": level_counts,
            "top_event_types": type_counts,
            "active_agents": active_agents
        }

def run_migrations():
    """Deprecated: Alembic manages migrations at startup via entrypoint.

    This stub remains for backward compatibility; it no-ops and logs an info
    message to avoid duplicate/legacy schema management.
    """
    logger.info("run_migrations() is deprecated; Alembic upgrade runs at startup. Skipping.")
