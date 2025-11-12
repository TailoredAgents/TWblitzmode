"""
Mutuals Service - PostgreSQL-backed mutual connection storage and retrieval.
Ensures zero-SQLite fallbacks by relying exclusively on the shared Postgres
utilities and psycopg2 RealDict cursors.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from psycopg2.extras import RealDictCursor

from scripts.utils.postgres import (
    DEFAULT_TEST_DSN,
    postgres_connection,
    resolve_required_dsn,
)


def normalize_linkedin_url(url: str) -> str:
    """Normalise LinkedIn URLs to a canonical profile path."""
    if not url:
        return ""

    clean = url.rstrip("/").split("?", 1)[0].strip()
    if "linkedin.com/in/" not in clean:
        return ""

    return clean


class MutualsService:
    """Service for managing Postgres-backed mutual connection persistence."""

    def __init__(self, *, database_url: Optional[str] = None):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._database_url = database_url

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_dsn(self) -> str:
        if not self._database_url:
            self._database_url = resolve_required_dsn(
                "DATABASE_URL",
                "TEST_DATABASE_URL",
                default=DEFAULT_TEST_DSN,
            )
        return self._database_url

    @staticmethod
    def _serialise_row(row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert datetime instances to ISO strings and ensure mutual_name."""
        serialised: Dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, datetime):
                serialised[key] = value.astimezone(timezone.utc).isoformat()
            else:
                serialised[key] = value

        if not (serialised.get("mutual_name") or "").strip():
            serialised["mutual_name"] = serialised.get("mutual_full_name", "") or ""
        return serialised

    @staticmethod
    def _prepare_entries(
        raw_items: Iterable[Dict[str, Any]],
        *,
        provider: str,
        default_scraped_at: str,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Normalise raw entries and return (valid_entries, error_count)."""
        normalised: List[Dict[str, Any]] = []
        errors = 0

        for item in raw_items:
            mutual_url = normalize_linkedin_url(
                item.get("mutual_linkedin_url")
                or item.get("linkedin_url")
                or item.get("connector_linkedin_url")
                or ""
            )
            if not mutual_url:
                errors += 1
                continue

            full_name = (
                item.get("mutual_full_name")
                or item.get("mutual_name")
                or item.get("full_name")
                or item.get("connector_name")
                or ""
            ).strip()
            if not full_name:
                errors += 1
                continue

            mutual_name = (item.get("mutual_name") or full_name).strip()

            scraped_at_value = item.get("scraped_at") or default_scraped_at

            normalised.append(
                {
                    "mutual_full_name": full_name,
                    "mutual_name": mutual_name,
                    "mutual_linkedin_url": mutual_url,
                    "mutual_headline": (item.get("mutual_headline") or item.get("headline") or "").strip(),
                    "mutual_company": (item.get("mutual_company") or item.get("company") or "").strip(),
                    "network_distance": (
                        item.get("network_distance")
                        or item.get("connection_degree")
                        or ""
                    ).strip(),
                    "scraped_via": provider,
                    "scraped_at": scraped_at_value,
                    "run_id": item.get("run_id"),
                    "provider": item.get("provider") or provider,
                }
            )

        return normalised, errors

    def _persist_mutuals_sync(
        self,
        *,
        tenant_id: int,
        prospect_id: int,
        provider: str,
        run_id: Optional[str],
        items: Iterable[Dict[str, Any]],
    ) -> Dict[str, int]:
        """Persist mutual connections synchronously; returns mutation stats."""
        timestamp = datetime.now(timezone.utc).isoformat()
        entries, normalisation_errors = self._prepare_entries(
            items,
            provider=provider,
            default_scraped_at=timestamp,
        )

        if not entries:
            if normalisation_errors:
                self.logger.warning(
                    "All mutual entries invalid for prospect %s (tenant=%s)",
                    prospect_id,
                    tenant_id,
                )
            return {"stored": 0, "duplicates": 0, "errors": normalisation_errors}

        stored = 0
        duplicates = 0
        errors = normalisation_errors

        dsn = self._resolve_dsn()
        with postgres_connection(dsn, cursor_factory=RealDictCursor) as conn:
            try:
                with conn.cursor() as cursor:
                    for entry in entries:
                        cursor.execute(
                            """
                            INSERT INTO prospect_mutuals (
                                tenant_id,
                                prospect_id,
                                mutual_full_name,
                                mutual_name,
                                mutual_linkedin_url,
                                mutual_headline,
                                mutual_company,
                                network_distance,
                                scraped_via,
                                scraped_at,
                                run_id,
                                provider
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (prospect_id, mutual_linkedin_url) DO NOTHING
                            """,
                            (
                                tenant_id,
                                prospect_id,
                                entry["mutual_full_name"],
                                entry["mutual_name"],
                                entry["mutual_linkedin_url"],
                                entry["mutual_headline"],
                                entry["mutual_company"],
                                entry["network_distance"],
                                entry["scraped_via"],
                                entry["scraped_at"],
                                run_id or entry.get("run_id"),
                                entry["provider"],
                            ),
                        )

                        if cursor.rowcount:
                            stored += 1
                            continue

                        cursor.execute(
                            """
                            UPDATE prospect_mutuals
                            SET
                                mutual_full_name = COALESCE(NULLIF(%s, ''), mutual_full_name),
                                mutual_name = COALESCE(NULLIF(%s, ''), mutual_name),
                                mutual_headline = COALESCE(NULLIF(%s, ''), mutual_headline),
                                mutual_company = COALESCE(NULLIF(%s, ''), mutual_company),
                                network_distance = COALESCE(NULLIF(%s, ''), network_distance),
                                scraped_via = COALESCE(NULLIF(%s, ''), scraped_via),
                                scraped_at = COALESCE(%s, scraped_at),
                                run_id = COALESCE(%s, run_id),
                                provider = COALESCE(NULLIF(%s, ''), provider)
                            WHERE tenant_id = %s
                              AND prospect_id = %s
                              AND mutual_linkedin_url = %s
                            """,
                            (
                                entry["mutual_full_name"],
                                entry["mutual_name"],
                                entry["mutual_headline"],
                                entry["mutual_company"],
                                entry["network_distance"],
                                entry["scraped_via"],
                                entry["scraped_at"],
                                run_id or entry.get("run_id"),
                                entry["provider"],
                                tenant_id,
                                prospect_id,
                                entry["mutual_linkedin_url"],
                            ),
                        )

                        if cursor.rowcount:
                            duplicates += 1
                        else:
                            errors += 1

                conn.commit()
            except Exception:
                conn.rollback()
                self.logger.exception(
                    "Failed to persist mutuals for prospect %s (tenant=%s)",
                    prospect_id,
                    tenant_id,
                )
                raise

        return {"stored": stored, "duplicates": duplicates, "errors": errors}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def store_mutual_connections(
        self,
        prospect_id: int,
        connections: Optional[List[Dict[str, Any]]] = None,
        provider: str = "phantombuster",
        run_id: Optional[str] = None,
        tenant_id: Optional[int] = None,
        **legacy_kwargs: Any,
    ) -> int:
        """Synchronously persist mutual connections; returns number inserted."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required to store mutual connections")

        items = connections if connections is not None else (legacy_kwargs.get("items") or [])
        if legacy_kwargs.get("source"):
            provider = legacy_kwargs["source"]

        result = self._persist_mutuals_sync(
            tenant_id=int(tenant_id),
            prospect_id=prospect_id,
            provider=provider,
            run_id=run_id,
            items=items,
        )
        return result["stored"]

    async def store_prospect_mutuals(
        self,
        prospect_id: int,
        items: List[Dict[str, Any]],
        source: str = "phantombuster",
        run_id: Optional[str] = None,
        tenant_id: int = 1,
    ) -> Dict[str, int]:
        """Async wrapper that persists mutuals using a thread executor."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required to store mutual connections")

        return await asyncio.to_thread(
            self._persist_mutuals_sync,
            tenant_id=int(tenant_id),
            prospect_id=prospect_id,
            provider=source,
            run_id=run_id,
            items=items,
        )

    async def get_prospect_mutuals(
        self,
        prospect_id: int,
        tenant_id: int = 1,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Fetch mutual connections for a prospect."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required to fetch mutual connections")

        def _fetch() -> List[Dict[str, Any]]:
            dsn = self._resolve_dsn()
            with postgres_connection(dsn, cursor_factory=RealDictCursor) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            prospect_id,
                            tenant_id,
                            mutual_full_name,
                            mutual_name,
                            mutual_linkedin_url,
                            mutual_headline,
                            mutual_company,
                            network_distance,
                            scraped_via,
                            scraped_at,
                            run_id,
                            mutual_email,
                            mutual_email_confidence,
                            email_enriched_at,
                            provider
                        FROM prospect_mutuals
                        WHERE prospect_id = %s
                          AND tenant_id = %s
                        ORDER BY scraped_at DESC
                        LIMIT %s
                        """,
                        (prospect_id, int(tenant_id), limit),
                    )
                    return [self._serialise_row(row) for row in cursor.fetchall()]

        return await asyncio.to_thread(_fetch)

    async def update_mutual_email(
        self,
        mutual_id: int,
        email: str,
        confidence: float,
        tenant_id: int = 1,
    ) -> bool:
        """Update email enrichment data for a stored mutual connection."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required to update mutual email")

        def _update() -> bool:
            dsn = self._resolve_dsn()
            with postgres_connection(dsn, cursor_factory=RealDictCursor) as conn:
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            """
                            UPDATE prospect_mutuals
                            SET
                                mutual_email = %s,
                                mutual_email_confidence = %s,
                                email_enriched_at = %s
                            WHERE id = %s
                              AND tenant_id = %s
                            """,
                            (
                                email,
                                confidence,
                                datetime.now(timezone.utc),
                                mutual_id,
                                int(tenant_id),
                            ),
                        )
                        conn.commit()
                        return cursor.rowcount > 0
                except Exception:
                    conn.rollback()
                    raise

        return await asyncio.to_thread(_update)

    async def search_mutuals_by_name(
        self,
        name_query: str,
        tenant_id: int = 1,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search mutual connections by name for a tenant."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required to search mutuals")

        pattern = f"%{name_query.strip()}%"

        def _search() -> List[Dict[str, Any]]:
            dsn = self._resolve_dsn()
            with postgres_connection(dsn, cursor_factory=RealDictCursor) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT DISTINCT
                            id,
                            prospect_id,
                            tenant_id,
                            mutual_full_name,
                            mutual_name,
                            mutual_linkedin_url,
                            mutual_headline,
                            mutual_company,
                            network_distance,
                            scraped_via,
                            scraped_at,
                            mutual_email,
                            mutual_email_confidence,
                            provider
                        FROM prospect_mutuals
                        WHERE tenant_id = %s
                          AND (
                              mutual_name ILIKE %s
                           OR mutual_full_name ILIKE %s
                          )
                        ORDER BY scraped_at DESC
                        LIMIT %s
                        """,
                        (int(tenant_id), pattern, pattern, limit),
                    )
                    return [self._serialise_row(row) for row in cursor.fetchall()]

        return await asyncio.to_thread(_search)

    async def get_mutual_stats(self, tenant_id: int = 1) -> Dict[str, Any]:
        """Return aggregate statistics for a tenant's mutual connections."""
        if tenant_id in (None, "", 0):
            raise ValueError("tenant_id is required to gather stats")

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        def _stats() -> Dict[str, Any]:
            dsn = self._resolve_dsn()
            with postgres_connection(dsn, cursor_factory=RealDictCursor) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            COUNT(*) AS total_mutuals,
                            COUNT(*) FILTER (WHERE mutual_email IS NOT NULL) AS mutuals_with_email,
                            COUNT(DISTINCT prospect_id) AS prospects_with_mutuals,
                            COUNT(*) FILTER (WHERE scraped_at > %s) AS recent_mutuals
                        FROM prospect_mutuals
                        WHERE tenant_id = %s
                        """,
                        (cutoff, int(tenant_id)),
                    )
                    row = cursor.fetchone() or {}
                    return {
                        "total_mutuals": int(row.get("total_mutuals", 0) or 0),
                        "mutuals_with_email": int(row.get("mutuals_with_email", 0) or 0),
                        "prospects_with_mutuals": int(row.get("prospects_with_mutuals", 0) or 0),
                        "recent_mutuals": int(row.get("recent_mutuals", 0) or 0),
                    }

        return await asyncio.to_thread(_stats)


mutuals_service = MutualsService()
