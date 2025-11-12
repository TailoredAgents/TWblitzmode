from __future__ import annotations

"""
AsyncPG RLS helpers: acquire connections with tenant GUCs set.

Use acquire_conn(dsn, tenant) for direct connections, and acquire_pool_conn(pool, tenant)
when working with an asyncpg pool. Both context managers set:
  - app.current_tenant_id
  - app.current_organization_id
and yield an asyncpg.Connection.
"""

from typing import Optional

import asyncpg


class _ConnCtx:
    def __init__(self, dsn: str, tenant: Optional[str]):
        self.dsn = dsn
        self.tenant = str(tenant) if tenant is not None else None
        self.conn: Optional[asyncpg.Connection] = None

    async def __aenter__(self) -> asyncpg.Connection:
        self.conn = await asyncpg.connect(self.dsn)
        if self.tenant:
            try:
                await self.conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", self.tenant)
                await self.conn.execute("SELECT set_config('app.current_organization_id', $1, true)", self.tenant)
            except Exception:
                pass
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.conn:
            await self.conn.close()


def acquire_conn(dsn: str, tenant: Optional[str | int]):
    return _ConnCtx(dsn, str(tenant) if tenant is not None else None)


class _PoolConnCtx:
    def __init__(self, pool: asyncpg.Pool, tenant: Optional[str]):
        self.pool = pool
        self.tenant = str(tenant) if tenant is not None else None
        self.conn: Optional[asyncpg.Connection] = None

    async def __aenter__(self) -> asyncpg.Connection:
        self.conn = await self.pool.acquire()
        if self.tenant:
            try:
                await self.conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", self.tenant)
                await self.conn.execute("SELECT set_config('app.current_organization_id', $1, true)", self.tenant)
            except Exception:
                pass
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.conn:
            try:
                await self.pool.release(self.conn)
            except Exception:
                pass


def acquire_pool_conn(pool: asyncpg.Pool, tenant: Optional[str | int]):
    return _PoolConnCtx(pool, str(tenant) if tenant is not None else None)

