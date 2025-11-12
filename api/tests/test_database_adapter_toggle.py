from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import api.database as database


class _DummyCursor:
    def __init__(self) -> None:
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        return None


class _DummyConnection:
    def __init__(self) -> None:
        self.cursor_calls = 0
        self.closed = 0
        self.commits = 0
        self.rollbacks = 0
        self._cursor = _DummyCursor()

    def cursor(self, *args, **kwargs):
        self.cursor_calls += 1
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


@pytest.fixture
def dummy_native(monkeypatch):
    dummy_conn = _DummyConnection()

    if "psycopg2" not in sys.modules:
        stub_extras = SimpleNamespace(DictCursor=object)
        monkeypatch.setitem(sys.modules, "psycopg2", SimpleNamespace(extras=stub_extras))
        monkeypatch.setitem(sys.modules, "psycopg2.extras", stub_extras)

    def fake_get_db():
        fake_get_db.called = True  # type: ignore[attr-defined]
        return dummy_conn

    fake_get_db.called = False  # type: ignore[attr-defined]

    monkeypatch.setattr(database, "using_native_adapter", lambda: True)
    monkeypatch.setitem(sys.modules, "api.mt_db", SimpleNamespace(get_db=fake_get_db))

    yield dummy_conn, fake_get_db


def test_get_db_uses_native_path(dummy_native):
    dummy_conn, fake_get_db = dummy_native

    compat = database.get_db()
    assert fake_get_db.called is True  # type: ignore[attr-defined]
    assert getattr(compat, "_conn", None) is dummy_conn

    compat.close()
    assert dummy_conn.closed == 1


def test_get_db_connection_native_wraps_underlying(dummy_native):
    dummy_conn, fake_get_db = dummy_native

    with database.get_db_connection() as ctx:
        assert ctx.connection is dummy_conn
        cursor = ctx.connection.cursor()
        cursor.execute("SELECT 1")

    assert fake_get_db.called is True  # type: ignore[attr-defined]
    assert dummy_conn.commits == 1
    assert dummy_conn.rollbacks == 0
    assert dummy_conn.closed == 1
