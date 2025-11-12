import os
from typing import List, Tuple, Dict, Any

os.environ.setdefault("TESTING", "true")

from fastapi.testclient import TestClient  # noqa: E402


def _spy_logger(monkeypatch) -> Tuple[List[Dict[str, Any]], Any]:
    """Monkeypatch api.routes_auth.log_structured to capture calls.

    Returns (events, restore) but pytest monkeypatch handles cleanup automatically.
    """
    events: List[Dict[str, Any]] = []

    import api.routes_auth as routes_auth

    def fake_log_structured(level, message, *args, **kwargs):
        events.append({
            "level": getattr(level, "value", str(level)),
            "message": message,
            "kwargs": kwargs,
        })

    monkeypatch.setattr(routes_auth, "log_structured", fake_log_structured)
    return events, routes_auth


def _make_client():
    from api.main import app
    return TestClient(app)


def test_refresh_missing_token_logs_structured(monkeypatch):
    events, _ = _spy_logger(monkeypatch)
    client = _make_client()

    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401

    # Expect both a received and missing_token event
    messages = [e["message"] for e in events]
    assert "auth.refresh.received" in messages
    assert "auth.refresh.missing_token" in messages


def test_forgot_rate_limited_logs_structured(monkeypatch):
    events, routes_auth = _spy_logger(monkeypatch)
    # Force rate-limit path
    monkeypatch.setattr(routes_auth, "check_reset_rate_limit", lambda ip: False)

    client = _make_client()

    resp = client.post(
        "/api/auth/forgot-password",
        json={"email": "user@example.com", "organization_slug": "acme"},
    )
    assert resp.status_code == 429
    messages = [e["message"] for e in events]
    assert "auth.forgot.received" in messages
    assert "auth.forgot.rate_limited" in messages


def test_me_missing_authorization_logs_structured(monkeypatch):
    events, _ = _spy_logger(monkeypatch)
    client = _make_client()

    resp = client.get("/api/auth/me")
    assert resp.status_code == 401

    messages = [e["message"] for e in events]
    assert "auth.me.received" in messages
    assert "auth.me.missing_authorization" in messages


def test_me_invalid_token_logs_structured(monkeypatch):
    events, _ = _spy_logger(monkeypatch)
    client = _make_client()

    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid"})
    assert resp.status_code == 401

    messages = [e["message"] for e in events]
    assert "auth.me.received" in messages
    assert "auth.me.http_exception" in messages
