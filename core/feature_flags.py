from __future__ import annotations

"""Runtime feature flag utilities."""

import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Optional

from core.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_FLAGS: Dict[str, bool] = {
    "corporate_connect": False,
    "link_autonomy": False,
    "risk_scoring_v2": False,
    "agent_experiments": False,
}


def _parse_env_flags(raw_flags: str | None) -> Dict[str, bool]:
    if not raw_flags:
        return {}

    try:
        parsed = json.loads(raw_flags)
        if isinstance(parsed, dict):
            return {str(k): bool(v) for k, v in parsed.items()}
    except json.JSONDecodeError:
        pass

    # Support simple comma separated list (flag=true)
    result: Dict[str, bool] = {}
    for item in raw_flags.split(","):
        item = item.strip()
        if not item:
            continue

        if "=" in item:
            name, value = item.split("=", 1)
            result[name.strip()] = value.strip().lower() in {"1", "true", "yes", "on"}
        else:
            result[item] = True
    return result


@lru_cache(maxsize=1)
def get_feature_flags() -> Dict[str, bool]:
    """Merge default flags with environment/settings based overrides."""

    merged = DEFAULT_FLAGS.copy()
    raw = settings.FEATURE_FLAGS or os.getenv("FEATURE_FLAGS")
    merged.update(_parse_env_flags(raw))

    if settings.ENVIRONMENT == "production":
        # Production safety: disable experimental flags unless explicitly enabled
        for key in ("agent_experiments", "link_autonomy"):
            merged.setdefault(key, False)
    return merged


def feature_flag_payload(tenant_id: Optional[int] = None) -> Dict[str, object]:
    """Return structured payload for API and logging."""

    flags = get_feature_flags()

    if tenant_id is not None:
        try:
            from services.subscription_feature_service import subscription_feature_service

            tenant_features = subscription_feature_service.get_features_for_tenant(tenant_id)
            for feature, allowed in tenant_features.items():
                current = flags.get(feature, False)

                if allowed:
                    flags[feature] = True
                else:
                    # Enforce subscription restrictions even if globally enabled.
                    flags[feature] = False if feature in DEFAULT_FLAGS or current else current
        except Exception as exc:  # pragma: no cover - defensive logging
            # Avoid raising from feature flag evaluation; log for observability.
            logger.warning("Failed to evaluate tenant feature flags for %s: %s", tenant_id, exc)

    return {
        "flags": flags,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "source": "tenant" if tenant_id is not None else "env",
    }


def is_feature_enabled(flag: str) -> bool:
    """Helper for service modules."""

    return bool(get_feature_flags().get(flag, False))


def refresh_feature_flags() -> None:
    """Invalidate cache (used in tests or admin tooling)."""

    get_feature_flags.cache_clear()
