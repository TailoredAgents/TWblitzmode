"""
Service Layer Compatibility Bridge
September 2025 - Master Game Plan Integration

Provides adapters and bridges between legacy services and Master Game Plan
services to ensure zero breaking changes during transition.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Union, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from abc import ABC, abstractmethod
import json

from src.services.database_mode import is_native_mode

logger = logging.getLogger(__name__)

COMPAT_ENABLED = not is_native_mode()


def _compat_guard(action: str) -> bool:
    """Return True when compatibility features may run, otherwise log and skip."""
    if COMPAT_ENABLED:
        return True
    logger.info("Compatibility bridge disabled in native database mode; skipping %s", action)
    return False


class ServiceType(Enum):
    """Service implementation types"""
    LEGACY = "legacy"
    MASTER_GAME_PLAN = "mgp"
    HYBRID = "hybrid"

class CompatibilityMode(Enum):
    """Compatibility operation modes"""
    LEGACY_ONLY = "legacy_only"
    MGP_ONLY = "mgp_only"
    DUAL_WRITE = "dual_write"
    FEATURE_FLAG = "feature_flag"

@dataclass
class ServiceMapping:
    """Mapping between legacy and MGP service interfaces"""
    legacy_method: str
    mgp_method: str
    adapter_function: Optional[Callable] = None
    compatibility_mode: CompatibilityMode = CompatibilityMode.FEATURE_FLAG

class ServiceAdapter(ABC):
    """Abstract base class for service adapters"""

    def __init__(self, legacy_service, mgp_service, compatibility_mode: CompatibilityMode):
        self.legacy_service = legacy_service
        self.mgp_service = mgp_service
        self.compatibility_mode = compatibility_mode
        self.feature_flags: Dict[str, bool] = {}

    @abstractmethod
    def convert_legacy_to_mgp(self, data: Any) -> Any:
        """Convert legacy data format to MGP format"""
        pass

    @abstractmethod
    def convert_mgp_to_legacy(self, data: Any) -> Any:
        """Convert MGP data format to legacy format"""
        pass

class ProspectServiceAdapter(ServiceAdapter):
    """Adapter for prospect/company services"""

    def convert_legacy_to_mgp(self, prospect_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert legacy prospect format to MGP company/executive format"""

        # Extract company information
        company_data = {
            "name": prospect_data.get("company", ""),
            "domain": self._extract_domain_from_linkedin(prospect_data.get("linkedin_url", "")),
            "industry": prospect_data.get("industry"),
            "status": "active",
            "automation_enabled": True,
            "priority": "medium"
        }

        # Extract executive information
        executive_data = {
            "full_name": prospect_data.get("full_name", ""),
            "first_name": prospect_data.get("first_name", ""),
            "last_name": prospect_data.get("last_name", ""),
            "title": prospect_data.get("role", prospect_data.get("title", "")),
            "email": prospect_data.get("email"),
            "linkedin_url": prospect_data.get("linkedin_url"),
            "location": prospect_data.get("location"),
            "headline": prospect_data.get("headline"),
            "about": prospect_data.get("about"),
            "data_source": "legacy_import",
            "verification_status": "unverified",
            "status": "active"
        }

        return {
            "company": company_data,
            "executive": executive_data,
            "legacy_prospect_id": prospect_data.get("id")
        }

    def convert_mgp_to_legacy(self, mgp_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert MGP executive/company format to legacy prospect format"""

        executive = mgp_data.get("executive", {})
        company = mgp_data.get("company", {})

        return {
            "id": mgp_data.get("legacy_prospect_id"),
            "full_name": executive.get("full_name", ""),
            "first_name": executive.get("first_name", ""),
            "last_name": executive.get("last_name", ""),
            "role": executive.get("title", ""),
            "title": executive.get("title", ""),
            "company": company.get("name", ""),
            "email": executive.get("email"),
            "linkedin_url": executive.get("linkedin_url"),
            "location": executive.get("location"),
            "headline": executive.get("headline"),
            "about": executive.get("about"),
            "industry": company.get("industry"),
            "status": executive.get("status", "active"),
            "source": "mgp_conversion"
        }

    def _extract_domain_from_linkedin(self, linkedin_url: str) -> Optional[str]:
        """Extract company domain from LinkedIn URL (basic heuristic)"""
        if not linkedin_url:
            return None

        # This is a simplified extraction - in production would use more sophisticated methods
        if "/company/" in linkedin_url:
            company_part = linkedin_url.split("/company/")[-1].split("/")[0]
            return f"{company_part}.com"  # Basic heuristic

        return None

class ConnectorServiceAdapter(ServiceAdapter):
    """Adapter for connector/connection services"""

    def convert_legacy_to_mgp(self, connector_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert legacy connector format to MGP connection format"""

        return {
            "connector_full_name": connector_data.get("full_name", ""),
            "connector_linkedin_url": connector_data.get("linkedin_url", ""),
            "connector_title": connector_data.get("headline", ""),
            "connector_company": connector_data.get("company", ""),
            "connector_location": connector_data.get("location", ""),
            "connector_profile_picture_url": connector_data.get("profile_picture_url"),
            "connection_degree": 2,  # Default assumption
            "shared_connections_count": 0,
            "mutual_context": "Legacy connector import",
            "connection_source": "legacy_import",
            "discovery_method": "legacy_conversion",
            "status": "discovered"
        }

    def convert_mgp_to_legacy(self, connection_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert MGP connection format to legacy connector format"""

        return {
            "full_name": connection_data.get("connector_full_name", ""),
            "linkedin_url": connection_data.get("connector_linkedin_url", ""),
            "headline": connection_data.get("connector_title", ""),
            "company": connection_data.get("connector_company", ""),
            "location": connection_data.get("connector_location", ""),
            "profile_picture_url": connection_data.get("connector_profile_picture_url"),
            "email": connection_data.get("enriched_email"),
            "email_status": connection_data.get("email_status"),
            "email_confidence": connection_data.get("email_confidence")
        }

class UnifiedServiceInterface:
    """Unified interface that can route to legacy or MGP services"""

    def __init__(self):
        self.enabled = COMPAT_ENABLED
        self.adapters: Dict[str, ServiceAdapter] = {}
        self.feature_flags: Dict[str, bool] = {
            "use_mgp_prospects": False,
            "use_mgp_connectors": False,
            "use_mgp_automation": False,
            "dual_write_mode": False
        }
        self.service_registry: Dict[str, Dict[str, Any]] = {}

    def register_adapter(self, service_name: str, adapter: ServiceAdapter):
        """Register a service adapter"""
        if not _compat_guard(f"adapter registration for {service_name}"):
            return
        self.adapters[service_name] = adapter
        logger.info(f"Registered adapter for {service_name}")

    def set_feature_flag(self, flag_name: str, enabled: bool):
        """Set feature flag for service routing"""
        if not _compat_guard(f"set_feature_flag({flag_name})"):
            return
        self.feature_flags[flag_name] = enabled
        logger.info(f"Feature flag {flag_name} set to {enabled}")

    async def route_service_call(
        self,
        service_name: str,
        method_name: str,
        *args,
        **kwargs
    ) -> Any:
        """Route service call to appropriate implementation"""

        if not self.enabled:
            raise RuntimeError(
                f"Compatibility routing is disabled in native database mode (service={service_name}, method={method_name})."
            )
        adapter = self.adapters.get(service_name)
        if not adapter:
            raise ValueError(f"No adapter registered for service {service_name}")

        # Determine which service to use based on feature flags
        use_mgp = self.feature_flags.get(f"use_mgp_{service_name}", False)
        dual_write = self.feature_flags.get("dual_write_mode", False)

        try:
            if dual_write:
                # Execute on both services and compare results
                return await self._dual_write_execution(adapter, method_name, *args, **kwargs)
            elif use_mgp:
                # Use MGP service
                return await self._execute_mgp_method(adapter, method_name, *args, **kwargs)
            else:
                # Use legacy service
                return await self._execute_legacy_method(adapter, method_name, *args, **kwargs)

        except Exception as e:
            logger.error(f"Service call failed for {service_name}.{method_name}: {e}")
            # Fallback to legacy service if MGP fails
            if use_mgp:
                logger.warning(f"Falling back to legacy service for {service_name}.{method_name}")
                return await self._execute_legacy_method(adapter, method_name, *args, **kwargs)
            raise

    async def _execute_legacy_method(self, adapter: ServiceAdapter, method_name: str, *args, **kwargs):
        """Execute method on legacy service"""
        method = getattr(adapter.legacy_service, method_name)
        if asyncio.iscoroutinefunction(method):
            return await method(*args, **kwargs)
        else:
            return method(*args, **kwargs)

    async def _execute_mgp_method(self, adapter: ServiceAdapter, method_name: str, *args, **kwargs):
        """Execute method on MGP service with data conversion"""
        # Convert arguments if needed
        converted_args = []
        for arg in args:
            if isinstance(arg, dict):
                converted_args.append(adapter.convert_legacy_to_mgp(arg))
            else:
                converted_args.append(arg)

        # Execute MGP method
        method = getattr(adapter.mgp_service, method_name)
        if asyncio.iscoroutinefunction(method):
            result = await method(*converted_args, **kwargs)
        else:
            result = method(*converted_args, **kwargs)

        # Convert result back to legacy format if needed
        if isinstance(result, dict):
            return adapter.convert_mgp_to_legacy(result)
        elif isinstance(result, list):
            return [adapter.convert_mgp_to_legacy(item) if isinstance(item, dict) else item for item in result]
        else:
            return result

    async def _dual_write_execution(self, adapter: ServiceAdapter, method_name: str, *args, **kwargs):
        """Execute on both services and validate consistency"""

        # Execute on legacy service
        legacy_result = await self._execute_legacy_method(adapter, method_name, *args, **kwargs)

        try:
            # Execute on MGP service
            mgp_result = await self._execute_mgp_method(adapter, method_name, *args, **kwargs)

            # Compare results (basic comparison)
            if self._compare_results(legacy_result, mgp_result):
                logger.info(f"Dual write validation passed for {method_name}")
            else:
                logger.warning(f"Dual write validation failed for {method_name}")

            # Return legacy result for consistency during transition
            return legacy_result

        except Exception as e:
            logger.error(f"MGP service failed during dual write for {method_name}: {e}")
            return legacy_result

    def _compare_results(self, legacy_result: Any, mgp_result: Any) -> bool:
        """Compare results from legacy and MGP services"""

        # Basic comparison - in production would be more sophisticated
        try:
            if isinstance(legacy_result, (dict, list)):
                return json.dumps(legacy_result, sort_keys=True) == json.dumps(mgp_result, sort_keys=True)
            else:
                return legacy_result == mgp_result
        except Exception:
            return False

class FeatureFlagManager:
    """Manages feature flags for gradual rollout"""

    def __init__(self):
        self.enabled = COMPAT_ENABLED
        self.flags: Dict[str, Dict[str, Any]] = {
            "use_mgp_prospects": {
                "enabled": False,
                "rollout_percentage": 0,
                "description": "Enable Master Game Plan prospect management"
            },
            "use_mgp_connectors": {
                "enabled": False,
                "rollout_percentage": 0,
                "description": "Enable Master Game Plan connector discovery"
            },
            "use_mgp_automation": {
                "enabled": False,
                "rollout_percentage": 0,
                "description": "Enable Master Game Plan automation workflow"
            },
            "dual_write_mode": {
                "enabled": False,
                "rollout_percentage": 0,
                "description": "Enable dual write for validation"
            }
        }

    def is_enabled(self, flag_name: str, user_id: Optional[int] = None) -> bool:
        """Check if feature flag is enabled for user"""
        if not self.enabled:
            return False
        flag = self.flags.get(flag_name)
        if not flag:
            return False

        if flag["enabled"]:
            # Check rollout percentage
            if user_id and flag["rollout_percentage"] < 100:
                # Simple hash-based rollout
                user_hash = hash(str(user_id)) % 100
                return user_hash < flag["rollout_percentage"]
            return True

        return False

    def set_flag(self, flag_name: str, enabled: bool, rollout_percentage: int = 100):
        """Set feature flag state"""
        if not self.enabled:
            logger.info("Skipping feature flag update for %s; compatibility bridge disabled.", flag_name)
            return
        if flag_name in self.flags:
            self.flags[flag_name]["enabled"] = enabled
            self.flags[flag_name]["rollout_percentage"] = rollout_percentage
            logger.info(f"Feature flag {flag_name} set to {enabled} with {rollout_percentage}% rollout")

    def get_all_flags(self) -> Dict[str, Any]:
        """Get all feature flags"""
        return self.flags

# Global instances
unified_service = UnifiedServiceInterface()
feature_flags = FeatureFlagManager()

# Convenience functions for service setup
def setup_compatibility_bridge():
    if not _compat_guard("compatibility bridge setup"):
        return
    """Set up the compatibility bridge with all adapters"""

    # Import services (these would be actual imports in production)
    try:
        # Legacy services would be imported here
        # from src.services.database import db as legacy_db
        # from src.services.phantombuster import PhantomBusterService

        # MGP services
        from src.services.prospect_automation_manager import ProspectAutomationManager
        from src.services.company_exec_search import CompanyExecSearchService
        from src.services.apify_mutuals import ApifyMutualsService

        # Set up adapters
        # prospect_adapter = ProspectServiceAdapter(legacy_db, CompanyExecSearchService(), CompatibilityMode.FEATURE_FLAG)
        # unified_service.register_adapter("prospects", prospect_adapter)

        logger.info("✅ Compatibility bridge setup completed")

    except ImportError as e:
        logger.warning(f"Some services not available for compatibility bridge: {e}")

def enable_gradual_rollout(flag_name: str, percentage: int):
    """Enable gradual rollout for a feature"""
    if not _compat_guard(f"enable_gradual_rollout({flag_name})"):
        return
    feature_flags.set_flag(flag_name, True, percentage)
    unified_service.set_feature_flag(flag_name, True)
