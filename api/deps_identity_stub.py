from __future__ import annotations
from fastapi import Header

def get_current_user(
    x_debug_user_id: int | None = Header(default=None, alias="X-Debug-User-Id"),
    x_role: str | None = Header(default=None, alias="X-Role"),
    x_org_id: int | None = Header(default=None, alias="X-Org-Id"),
):
    return {
        "id": x_debug_user_id or 1,
        "email": "admin@local",
        "role": (x_role or "admin").lower(),
        "tenant_id": 1,
        "organization_id": x_org_id or 1,
    }

def get_current_admin():
    return get_current_user()
