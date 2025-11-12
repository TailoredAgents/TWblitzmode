"""
Subscription-aware feature gating service.

Provides helpers to determine whether premium capabilities like Corporate
Connect are available for a given tenant based on their subscribed tier.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Union

from core.settings import settings

try:
    from api.database import get_db
except ImportError as exc:  # pragma: no cover - optional dependency during docs builds
    raise ImportError("api.database is required for subscription feature service") from exc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeatureMatrix:
    """Static mapping of subscription tiers to feature availability."""

    features_by_tier: Dict[str, Dict[str, bool]]

    def for_tier(self, tier: str) -> Dict[str, bool]:
        normalized = (tier or "default").lower()
        return self.features_by_tier.get(normalized, self.features_by_tier.get("default", {}))


class SubscriptionFeatureService:
    """Resolve per-tenant feature availability from subscription metadata."""

    _matrix = FeatureMatrix(
        features_by_tier={
            "default": {
                "corporate_connect": False,
                "cookie_vault_admin": False,
                "cookie_collection": False,
            },
            "starter": {
                "corporate_connect": False,
                "cookie_vault_admin": False,
                "cookie_collection": False,
            },
            "growth": {
                "corporate_connect": False,
                "cookie_vault_admin": False,
                "cookie_collection": False,
            },
            "professional": {
                "corporate_connect": False,
                "cookie_vault_admin": False,
                "cookie_collection": False,
            },
            "enterprise": {
                "corporate_connect": True,
                "cookie_vault_admin": True,
                "cookie_collection": True,
            },
            "custom": {
                "corporate_connect": True,
                "cookie_vault_admin": True,
                "cookie_collection": True,
            },
        }
    )

    def __init__(self) -> None:
        self._logger = logger.getChild(self.__class__.__name__)

    def is_feature_enabled(self, tenant_id: Optional[Union[int, str]], feature: str) -> bool:
        """Return True when the requested feature is enabled for the tenant."""

        tenant_features = self.get_features_for_tenant(tenant_id)
        value = tenant_features.get(feature)
        return bool(value) if value is not None else False

    def get_features_for_tenant(self, tenant_id: Optional[Union[int, str]]) -> Dict[str, bool]:
        """
        Return the feature flag mapping for the provided tenant.

        When tenant_id is None or no subscription record exists we fall back to
        the default tier mapping which disables premium capabilities.
        """

        if settings.CLIENT_NAME.lower() == "tallwave":
            return {
                "corporate_connect": True,
                "cookie_vault_admin": True,
                "cookie_collection": True,
            }

        tier = self._determine_subscription_tier(tenant_id)
        return self._matrix.for_tier(tier).copy()

    # Internal helpers -------------------------------------------------

    def _determine_subscription_tier(self, tenant_id: Optional[Union[int, str]]) -> str:
        """Lookup the subscription tier for the tenant."""

        if tenant_id is None:
            return "default"

        normalized_tenant: Union[int, str]
        if isinstance(tenant_id, int):
            normalized_tenant = tenant_id
        else:
            candidate = str(tenant_id).strip()
            if not candidate:
                return "default"
            if candidate.isdigit():
                try:
                    normalized_tenant = int(candidate)
                except ValueError:
                    normalized_tenant = candidate
            else:
                normalized_tenant = candidate

        try:
            conn = get_db()
        except Exception as exc:  # pragma: no cover - database bootstrap failures
            self._logger.warning(
                "Unable to connect to database for tenant %s: %s", tenant_id, exc
            )
            return "default"

        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT subscription_tier FROM organizations WHERE tenant_id = ?",
                (normalized_tenant,),
            )
            row = cursor.fetchone()
            if not row:
                self._logger.debug("No organization record found for tenant %s", tenant_id)
                return "default"

            # sqlite3.Row supports both dict-style and attribute access; guard for tuples.
            if isinstance(row, dict):
                raw_tier = row.get("subscription_tier")
            else:
                try:
                    raw_tier = row["subscription_tier"]  # type: ignore[index]
                except (TypeError, KeyError):
                    raw_tier = row[0] if row else None  # type: ignore[index]

            if not raw_tier:
                return "default"

            return str(raw_tier).lower()
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.warning(
                "Failed to determine subscription tier for tenant %s (normalized=%s): %s",
                tenant_id,
                normalized_tenant,
                exc,
            )
            return "default"
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover - defensive close
                pass


subscription_feature_service = SubscriptionFeatureService()
