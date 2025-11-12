"""
Compatibility WebSocket endpoints for legacy Link chat clients.

The dashboard currently dials /ws/agent_chat with a JWT query parameter.
Production only exposes /api/agent-events/ws, so this shim validates the
token, extracts tenant context, and forwards the connection to the shared
agent event broadcaster.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from fastapi import APIRouter, WebSocket
from fastapi.exceptions import HTTPException
from starlette import status
from starlette.websockets import WebSocketState

from api.auth import decode_token
from api.routes_agent_events import stream_agent_events_websocket

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket-compat"])


@dataclass
class WebSocketIdentity:
    user_id: str
    organization_id: int


async def _close_with_policy_violation(websocket: WebSocket, detail: str) -> None:
    """Safely close the connection when auth/inputs are invalid."""
    if websocket.client_state != WebSocketState.DISCONNECTED:
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except RuntimeError:
            # Connection might already be closed by the client
            pass
    logger.warning("Rejecting /ws/agent_chat connection: %s", detail)


def _extract_token_from_request(websocket: WebSocket) -> Optional[str]:
    query_token = websocket.query_params.get("token")
    if query_token:
        return query_token

    auth_header = websocket.headers.get("authorization")
    if auth_header:
        scheme, _, credentials = auth_header.partition(" ")
        if scheme.lower() == "bearer" and credentials:
            return credentials.strip()
    return None


def _coerce_organization_id(candidates: Sequence[Optional[str]]) -> int:
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return 1


async def _resolve_identity(
    websocket: WebSocket,
    tenant_path: Optional[str],
    user_path: Optional[str],
) -> Optional[WebSocketIdentity]:
    token = _extract_token_from_request(websocket)
    if not token:
        await _close_with_policy_violation(websocket, "Missing auth token")
        return None

    try:
        payload = decode_token(token)
    except HTTPException as exc:
        await _close_with_policy_violation(websocket, exc.detail or "Invalid token")
        return None

    resolved_user = (
        websocket.query_params.get("user_id")
        or user_path
        or payload.get("user_id")
        or "anonymous"
    )

    organization_id = _coerce_organization_id(
        (
            websocket.query_params.get("organization_id"),
            tenant_path,
            payload.get("tenant_id"),
            payload.get("organization_id"),
        )
    )

    return WebSocketIdentity(user_id=str(resolved_user), organization_id=organization_id)


async def _handle_agent_chat_websocket(
    websocket: WebSocket,
    tenant_path: Optional[str],
    user_path: Optional[str],
) -> None:
    identity = await _resolve_identity(websocket, tenant_path, user_path)
    if not identity:
        return

    logger.info(
        "Link chat compatibility connection accepted (user=%s org=%s)",
        identity.user_id,
        identity.organization_id,
    )
    await stream_agent_events_websocket(
        websocket,
        identity.user_id,
        identity.organization_id,
    )


@router.websocket("/ws/agent_chat")
@router.websocket("/ws/agent_chat/{tenant_id}")
@router.websocket("/ws/agent_chat/{tenant_id}/{user_hint}")
async def websocket_agent_chat(
    websocket: WebSocket,
    tenant_id: Optional[str] = None,
    user_hint: Optional[str] = None,
) -> None:
    """
    Legacy-compatible WebSocket endpoint.

    Supports the original /ws/agent_chat path plus optional tenant/user segments,
    ensuring older dashboards connect without reconfiguration.
    """
    await _handle_agent_chat_websocket(websocket, tenant_id, user_hint)
