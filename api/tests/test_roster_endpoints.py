from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest  # type: ignore[import-not-found]
from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    from api.main import app
    return TestClient(app)


class _StubCursor:
    def __init__(self, executed: List[str], count_value: int = 0) -> None:
        self._executed = executed
        self._fetchone_result: Dict[str, Any] | None = None
        self._rows: List[Dict[str, Any]] = []
        self._count_value = count_value

    def __enter__(self) -> "_StubCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: Tuple[Any, ...] | None = None) -> "_StubCursor":
        normalized = " ".join(sql.lower().split())
        self._executed.append(normalized)
        if "count(" in normalized and "from users" in normalized:
            self._fetchone_result = {"c": self._count_value}
        else:
            # Roster query returns two rows
            self._rows = [
                {"id": 2, "first_name": "A", "last_name": "User", "last_login_at": None},
                {"id": 1, "first_name": "B", "last_name": "Admin", "last_login_at": None},
            ]
            self._fetchone_result = None
        return self

    def fetchone(self) -> Dict[str, Any] | None:
        return self._fetchone_result

    def fetchall(self) -> List[Dict[str, Any]]:
        return list(self._rows)


class _StubConn:
    def __init__(self, executed: List[str], count_value: int = 0) -> None:
        self._executed = executed
        self._count_value = count_value

    def cursor(self) -> _StubCursor:
        return _StubCursor(self._executed, count_value=self._count_value)


class _StubConnCtx:
    def __init__(self, executed: List[str], count_value: int = 0) -> None:
        self._conn = _StubConn(executed, count_value=count_value)

    def __enter__(self) -> _StubConn:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_roster_requires_tenant_header() -> None:
    client = _make_client()
    resp = client.get("/api/auth/login/roster")
    assert resp.status_code == 400
    payload = resp.json()
    assert "detail" in payload


def test_roster_query_filters_inactive_and_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: List[str] = []

    import api.routes_auth as routes_auth

    def fake_get_db_connection():
        return _StubConnCtx(executed)

    monkeypatch.setattr(routes_auth, "get_db_connection", fake_get_db_connection)

    client = _make_client()
    resp = client.get("/api/auth/login/roster", headers={"X-Organization-Id": "1"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("users"), list)

    # Ensure the roster query contains our filters and ordering
    roster_sql = next((s for s in executed if "from users" in s and "order by" in s), "")
    assert "where is_active = true" in roster_sql
    assert "order by last_login_at desc nulls last, id desc" in roster_sql


def test_roster_health_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: List[str] = []
    import api.routes_auth as routes_auth

    def fake_get_db_connection():
        return _StubConnCtx(executed, count_value=3)

    monkeypatch.setattr(routes_auth, "get_db_connection", fake_get_db_connection)

    client = _make_client()
    resp = client.get("/api/auth/login/roster/health", headers={"X-Organization-Id": "7"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("tenant") == "7"
    assert payload.get("count") == 3
    assert payload.get("ok") is True


def test_roster_health_missing_header() -> None:
    client = _make_client()
    resp = client.get("/api/auth/login/roster/health")
    assert resp.status_code == 400
    payload = resp.json()
    assert "detail" in payload

