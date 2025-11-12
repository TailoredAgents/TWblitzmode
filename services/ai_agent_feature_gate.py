"""
AI Agent feature gating utilities.
Centralizes logic for determining whether multi-agent workflows
are enabled globally or for a specific tenant.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.settings import settings

logger = logging.getLogger(__name__)

FEATURE_FLAG_ID = "ai_agents_enabled"


async def is_ai_agents_enabled(tenant_id: Optional[int] = None) -> bool:
    """
    Determine whether AI agent orchestration is enabled.
    Preference order:
      1. Feature flag evaluation (if rollout manager available)
      2. Static OPENAI_AGENTS_ENABLED setting
    """
    # Try dynamic flag evaluation when rollout infrastructure is available.
    try:
        from rollout.feature_flag_manager import feature_flag_manager

        if tenant_id is not None:
            result = await feature_flag_manager.evaluate_flag(
                FEATURE_FLAG_ID,
                user_id=None,
                organization_id=tenant_id,
                context={"feature": "ai_agents"}
            )
            if isinstance(result, dict):
                enabled = result.get("enabled")
                if enabled is not None:
                    return bool(enabled)
        else:
            # Fall back to cached global flag state.
            flag = feature_flag_manager.flags_cache.get(FEATURE_FLAG_ID)
            if flag and hasattr(flag, "enabled_percentage"):
                return flag.enabled_percentage > 0
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Feature flag evaluation for AI agents failed: %s", exc)

    return bool(settings.OPENAI_AGENTS_ENABLED)
