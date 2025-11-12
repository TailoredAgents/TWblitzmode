from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import pytest  # type: ignore[import-not-found]
from fastapi import HTTPException
from starlette.requests import Request

# Ensure the auth helpers load with deterministic secrets in test environments.
SECRET_VALUE = "test-jwt-secret-key-32-bytes-min!"

os.environ.setdefault("ENC_KEY", "WpMU5mABapY-XJ0rwu1_20AuZlyzDSvEZQK1OkHe4FA=")
os.environ.setdefault("SECRET_KEY", SECRET_VALUE)
os.environ.setdefault("JWT_SECRET", SECRET_VALUE)
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/test_db")
os.environ.setdefault("TEST_DATABASE_URL", "postgresql://localhost/test_db")
os.environ.setdefault("DB_COMPAT_MODE", "native")

from src.services.database_mode import reset_db_mode_cache

reset_db_mode_cache()

import api.deps as deps
import api.mt_db as mt_db


class StubCursor:
    """Cursor stub that records executed statements and returns fixture rows."""

    def __init__(
        self,
        executed: List[Tuple[str, Tuple[Any, ...]]],
        user_row: Dict[str, Any] | None,
        organization_row: Dict[str, Any] | None,
    ) -> None:
        self._executed = executed
        self._user_row = user_row
        self._organization_row = organization_row
        self._next_result: Dict[str, Any] | None = None
        self.closed = False

    def execute(self, sql: str, params: Tuple[Any, ...] | None = None) -> "StubCursor":
        bound_params = tuple(params or ())
        self._executed.append((sql, bound_params))
        normalized = " ".join(sql.lower().split())
        if "from users" in normalized:
            self._next_result = dict(self._user_row) if self._user_row is not None else None
        elif "from organizations" in normalized:
            self._next_result = dict(self._organization_row) if self._organization_row is not None else None
        else:
            self._next_result = None
        return self

    def fetchone(self) -> Dict[str, Any] | None:
        return self._next_result

    def close(self) -> None:
        self.closed = True


class StubConnection:
    """Connection stub that supplies a reusable cursor."""

    def __init__(
        self,
        executed: List[Tuple[str, Tuple[Any, ...]]],
        user_row: Dict[str, Any] | None,
        organization_row: Dict[str, Any] | None,
    ) -> None:
        self._cursor = StubCursor(executed, user_row, organization_row)
        self.rollback_called = False

    def cursor(self) -> StubCursor:
        return self._cursor

    def rollback(self) -> None:
        self.rollback_called = True

    # Compatibility attributes expected by the dependency.
    def commit(self) -> None:  # pragma: no cover - not exercised in this test
        return None

    def close(self) -> None:  # pragma: no cover - not exercised in this test
        return None


@pytest.mark.asyncio
async def test_get_current_user_native_mode_marshal_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the auth dependency against the native-query bridge."""

    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test_db")
    monkeypatch.setenv("DB_COMPAT_MODE", "native")
    reset_db_mode_cache()

    executed: List[Tuple[str, Tuple[Any, ...]]] = []
    user_row = {
        "id": 42,
        "tenant_id": "1",
        "email": "alex@tallwave.com",
        "first_name": "Alex",
        "last_name": "Admin",
        "role": "admin",
    }
    organization_row = {"id": 7, "subscription_tier": "enterprise"}
    stub_connection = StubConnection(executed, user_row, organization_row)

    # Route database lookups through the stub connection.
    monkeypatch.setattr(mt_db, "get_db", lambda tenant_id=None: stub_connection)

    # Provide deterministic token contents and downstream services.
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda token: {"user_id": user_row["id"], "tenant_id": user_row["tenant_id"]},
    )

    async def fake_get_account_by_tenant(tenant_id: str) -> Dict[str, Any]:
        assert tenant_id == user_row["tenant_id"]
        return {"id": 9001, "plan": "enterprise", "billing_status": "trial"}

    monkeypatch.setattr(deps.sqlite_db, "get_account_by_tenant", fake_get_account_by_tenant)

    tenant_tokens: List[str] = []

    def fake_set_tenant(tenant_id: str | None) -> str:
        tenant_tokens.append(tenant_id or "")
        return "tenant-context-token"

    monkeypatch.setattr(deps, "set_tenant", fake_set_tenant)

    scope = {
        "type": "http",
        "path": "/api/auth/test",
        "headers": [(b"authorization", b"Bearer example.jwt")],
    }
    request = Request(scope)

    current_user = await deps.get_current_user(request, authorization="Bearer example.jwt")

    assert current_user["id"] == user_row["id"]
    assert current_user["tenant_id"] == user_row["tenant_id"]
    assert current_user["organization_id"] == organization_row["id"]
    assert current_user["subscription_tier"] == organization_row["subscription_tier"]
    assert current_user["account_id"] == 9001
    assert current_user["account_plan"] == "enterprise"
    assert current_user["billing_status"] == "trial"
    assert request.state.organization_id == organization_row["id"]
    assert request.state.account == {"id": 9001, "plan": "enterprise", "billing_status": "trial"}
    assert request.state.plan == "enterprise"
    assert request.state.billing_status == "trial"
    assert tenant_tokens == [user_row["tenant_id"]]

    # The native bridge should rewrite SQLite placeholders to psycopg-style params.
    assert executed, "Expected authentication queries to run"
    for sql, _ in executed:
        assert "?" not in sql
        assert "%s" in sql

    assert executed[0][1] == (user_row["id"], user_row["tenant_id"])
    assert executed[1][1] == (user_row["tenant_id"],)
    assert stub_connection.rollback_called is False


@pytest.mark.asyncio
async def test_get_current_user_allows_non_active_billing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure suspended billing states do not block authentication."""

    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test_db")
    monkeypatch.setenv("DB_COMPAT_MODE", "native")
    reset_db_mode_cache()

    executed: List[Tuple[str, Tuple[Any, ...]]] = []
    user_row = {
        "id": 55,
        "tenant_id": "42",
        "email": "casey@tallwave.com",
        "first_name": "Casey",
        "last_name": "Wave",
        "role": "user",
    }
    organization_row = {"id": 101, "subscription_tier": "starter"}
    stub_connection = StubConnection(executed, user_row, organization_row)

    monkeypatch.setattr(mt_db, "get_db", lambda tenant_id=None: stub_connection)
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda token: {"user_id": user_row["id"], "tenant_id": user_row["tenant_id"]},
    )

    async def fake_get_account_by_tenant(tenant_id: str) -> Dict[str, Any]:
        assert tenant_id == user_row["tenant_id"]
        return {
            "id": 303,
            "plan": "starter",
            "billing_status": "suspended",
            "managed_by_admin": False,
        }

    monkeypatch.setattr(deps.sqlite_db, "get_account_by_tenant", fake_get_account_by_tenant)
    monkeypatch.setattr(deps, "set_tenant", lambda tenant_id: "tenant-token")

    scope = {
        "type": "http",
        "path": "/api/auth/billing",
        "headers": [(b"authorization", b"Bearer example.jwt")],
    }
    request = Request(scope)

    current_user = await deps.get_current_user(request, authorization="Bearer example.jwt")

    assert current_user["billing_status"] == "suspended"
    assert request.state.billing_status == "suspended"
    assert executed, "Expected user lookup even when billing is suspended"
    assert stub_connection.rollback_called is False


@pytest.mark.asyncio
async def test_get_current_user_rejects_header_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject requests when tenant header conflicts with the token scope."""

    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test_db")
    monkeypatch.setenv("DB_COMPAT_MODE", "native")
    reset_db_mode_cache()

    executed: List[Tuple[str, Tuple[Any, ...]]] = []
    user_row = {
        "id": 77,
        "tenant_id": "1",
        "email": "user@tallwave.com",
        "first_name": "Casey",
        "last_name": "Wave",
        "role": "user",
    }
    stub_connection = StubConnection(executed, user_row, {"id": 7, "subscription_tier": "enterprise"})

    monkeypatch.setattr(mt_db, "get_db", lambda tenant_id=None: stub_connection)
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda token: {"user_id": user_row["id"], "tenant_id": user_row["tenant_id"]},
    )

    async def should_not_run(*args, **kwargs):
        raise AssertionError("Account hydration should not execute on header mismatch")

    monkeypatch.setattr(deps.sqlite_db, "get_account_by_tenant", should_not_run)

    def should_not_set_tenant(_: str | None) -> None:
        raise AssertionError("Tenant context should not be set when header mismatches token")

    monkeypatch.setattr(deps, "set_tenant", should_not_set_tenant)

    scope = {
        "type": "http",
        "path": "/api/auth/header-check",
        "headers": [(b"authorization", b"Bearer example.jwt")],
    }
    request = Request(scope)
    request.state.tenant_header = "2"

    with pytest.raises(HTTPException) as exc_info:
        await deps.get_current_user(request, authorization="Bearer example.jwt")

    assert exc_info.value.status_code == 403
    assert executed, "Expected user lookup to occur before mismatch detection"
    assert stub_connection.rollback_called is False


@pytest.mark.asyncio
async def test_get_current_user_missing_user_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bubble a 401 when the authenticated user no longer exists."""

    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test_db")
    monkeypatch.setenv("DB_COMPAT_MODE", "native")
    reset_db_mode_cache()

    executed: List[Tuple[str, Tuple[Any, ...]]] = []
    stub_connection = StubConnection(executed, user_row=None, organization_row=None)

    monkeypatch.setattr(mt_db, "get_db", lambda tenant_id=None: stub_connection)
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda token: {"user_id": 9999, "tenant_id": "1"},
    )

    async def should_not_run(*args, **kwargs):
        raise AssertionError("Account hydration should not run when user is missing")

    monkeypatch.setattr(deps.sqlite_db, "get_account_by_tenant", should_not_run)

    def should_not_set_tenant(_: str | None) -> None:
        raise AssertionError("Tenant context should not be set when user is missing")

    monkeypatch.setattr(deps, "set_tenant", should_not_set_tenant)

    scope = {
        "type": "http",
        "path": "/api/auth/missing-user",
        "headers": [(b"authorization", b"Bearer example.jwt")],
    }
    request = Request(scope)

    with pytest.raises(HTTPException) as exc_info:
        await deps.get_current_user(request, authorization="Bearer example.jwt")

    assert exc_info.value.status_code == 401
    assert executed and executed[0][0]
    assert stub_connection.rollback_called is False
