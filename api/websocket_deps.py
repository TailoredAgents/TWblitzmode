"""
WebSocket Authentication Dependencies for FastAPI
Provides WebSocket-compatible authentication using existing JWT infrastructure.

Features:
- Token-based WebSocket authentication via query parameters
- Integration with existing user authentication system
- Tenant isolation and user context extraction
- Error handling for invalid or expired tokens
"""

import logging
from typing import Dict, Any
from fastapi import WebSocket, HTTPException, status
from .security import decode_token

logger = logging.getLogger(__name__)

async def get_current_user_websocket(websocket: WebSocket) -> Dict[str, Any]:
    """
    Authenticate WebSocket connection using token from query parameters

    Args:
        websocket: FastAPI WebSocket connection

    Returns:
        User dictionary with id, tenant_id, email, etc.

    Raises:
        HTTPException: If token is missing, invalid, or user not found
    """
    try:
        # Extract token from query parameters
        token = websocket.query_params.get("token")
        if not token:
            logger.warning("WebSocket connection attempted without token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token required for WebSocket connection"
            )

        # Decode and validate token using existing security infrastructure
        try:
            payload = decode_token(token)
        except Exception as e:
            logger.warning(f"Invalid WebSocket token: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get user data from database using existing connection
        from .mt_db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            user_id = payload.get("user_id")
            if not user_id:
                logger.warning("Token missing user_id")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token missing user_id"
                )

            # Query user data (compatible with existing database schema)
            cur.execute(
                "SELECT id, tenant_id, email, first_name, last_name, role FROM users WHERE id = ?",
                (user_id,)
            )
            user_row = cur.fetchone()

            if not user_row:
                logger.warning(f"User not found for WebSocket connection: {user_id}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found"
                )

            tenant_id = user_row["tenant_id"]
            requested_org = websocket.query_params.get("organization_id")

            org_id = None
            subscription_tier = None
            try:
                cur.execute(
                    "SELECT id, subscription_tier FROM organizations WHERE tenant_id = ?",
                    (str(tenant_id),)
                )
                org_row = cur.fetchone()
                if org_row:
                    org_id = org_row["id"]
                    subscription_tier = org_row["subscription_tier"]
            except Exception as org_error:
                logger.debug("Failed to fetch organization for tenant %s: %s", tenant_id, org_error)

            if org_id is None and requested_org:
                try:
                    org_id = int(requested_org)
                except (TypeError, ValueError):
                    logger.debug("Ignoring non-numeric organization_id query param: %s", requested_org)

            if org_id is None:
                org_id = tenant_id

            # Return user dict compatible with existing auth system
            user_data = {
                "id": user_row["id"],
                "user_id": user_row["id"],  # Alias for backward compatibility
                "tenant_id": tenant_id,
                "organization_id": org_id,
                "email": user_row["email"],
                "first_name": user_row["first_name"],
                "last_name": user_row["last_name"],
                "role": user_row["role"],
                "subscription_tier": subscription_tier,
            }

            logger.info(
                "WebSocket authenticated: user_id=%s, tenant_id=%s, organization_id=%s",
                user_data["id"],
                tenant_id,
                org_id,
            )
            return user_data

        finally:
            conn.close()

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error during WebSocket authentication: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service error"
        )

async def get_websocket_user_context(websocket: WebSocket) -> tuple[int, int]:
    """
    Get user and organization IDs for WebSocket connection

    Args:
        websocket: FastAPI WebSocket connection

    Returns:
        Tuple of (user_id, organization_id)
    """
    user = await get_current_user_websocket(websocket)
    return user["id"], user["organization_id"]

def extract_websocket_token(websocket: WebSocket) -> str:
    """
    Extract and validate token from WebSocket query parameters

    Args:
        websocket: FastAPI WebSocket connection

    Returns:
        JWT token string

    Raises:
        HTTPException: If token is missing or invalid format
    """
    token = websocket.query_params.get("token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token required in query parameters: ?token=your_jwt_token"
        )

    return token.strip()
