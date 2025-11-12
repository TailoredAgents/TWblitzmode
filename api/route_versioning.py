"""
Route Versioning and Namespace Management
September 2025 - Master Game Plan Infrastructure

Provides versioning and conflict resolution for API routes to ensure
backward compatibility while adding Master Game Plan functionality.
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.routing import APIRoute
from typing import Dict, Any, Callable, Optional
import logging
from enum import Enum

logger = logging.getLogger(__name__)

class APIVersion(Enum):
    """API version enumeration"""
    V1 = "v1"
    V2_MGP = "v2/mgp"  # Master Game Plan namespace

class RouteNamespace(Enum):
    """Route namespace enumeration"""
    LEGACY = "legacy"
    MASTER_GAME_PLAN = "mgp"
    SHARED = "shared"

class RouteVersioningMiddleware:
    """Middleware to handle API versioning and namespace routing"""

    def __init__(self):
        self.route_mappings: Dict[str, Dict[str, Any]] = {}
        self.deprecated_routes: Dict[str, str] = {}
        self.namespace_prefixes = {
            RouteNamespace.LEGACY: "/api",
            RouteNamespace.MASTER_GAME_PLAN: "/api/v2/mgp",
            RouteNamespace.SHARED: "/api/shared"
        }

    def register_route_mapping(
        self,
        legacy_path: str,
        mgp_path: str,
        deprecation_date: Optional[str] = None
    ):
        """Register a route mapping from legacy to MGP"""
        self.route_mappings[legacy_path] = {
            "mgp_path": mgp_path,
            "deprecation_date": deprecation_date,
            "namespace": RouteNamespace.MASTER_GAME_PLAN
        }

    def add_deprecated_route(self, path: str, replacement: str):
        """Mark a route as deprecated with replacement suggestion"""
        self.deprecated_routes[path] = replacement

    async def __call__(self, request: Request, call_next):
        """Process request through versioning middleware"""

        # Get the request path
        path = request.url.path

        # Check for deprecated routes
        if path in self.deprecated_routes:
            logger.warning(f"Deprecated route accessed: {path}")
            # Add deprecation header
            response = await call_next(request)
            response.headers["X-API-Deprecated"] = "true"
            response.headers["X-API-Replacement"] = self.deprecated_routes[path]
            return response

        # Check for route mappings (optional redirect/guidance)
        if path in self.route_mappings:
            mapping = self.route_mappings[path]
            logger.info(f"Legacy route {path} has MGP equivalent: {mapping['mgp_path']}")
            # Add header suggesting MGP alternative
            response = await call_next(request)
            response.headers["X-MGP-Alternative"] = mapping['mgp_path']
            return response

        # Process normally
        return await call_next(request)

class NamespaceRouter:
    """Router with namespace isolation for conflict prevention"""

    def __init__(self, namespace: RouteNamespace):
        self.namespace = namespace
        self.prefix = self._get_prefix(namespace)
        self.routes: Dict[str, APIRoute] = {}

    def _get_prefix(self, namespace: RouteNamespace) -> str:
        """Get URL prefix for namespace"""
        prefixes = {
            RouteNamespace.LEGACY: "/api",
            RouteNamespace.MASTER_GAME_PLAN: "/api/v2/mgp",
            RouteNamespace.SHARED: "/api/shared"
        }
        return prefixes.get(namespace, "/api")

    def add_route(self, path: str, endpoint: Callable, methods: list, **kwargs):
        """Add route with namespace prefix"""
        full_path = f"{self.prefix}{path}"
        route = APIRoute(full_path, endpoint, methods=methods, **kwargs)
        self.routes[full_path] = route
        logger.info(f"Registered {self.namespace.value} route: {full_path}")
        return route

# Global route versioning middleware instance
route_versioning = RouteVersioningMiddleware()

# Namespace routers
legacy_router = NamespaceRouter(RouteNamespace.LEGACY)
mgp_router = NamespaceRouter(RouteNamespace.MASTER_GAME_PLAN)
shared_router = NamespaceRouter(RouteNamespace.SHARED)

def register_legacy_mgp_mappings():
    """Register mappings between legacy and MGP routes"""

    # Route mappings for backward compatibility guidance
    mappings = [
        ("/api/prospects", "/api/v2/mgp/companies"),
        ("/api/prospects/{prospect_id}", "/api/v2/mgp/executives/{executive_id}"),
        ("/api/team-members", "/api/v2/mgp/team-members"),
        ("/api/mutual-connections", "/api/v2/mgp/connections"),
        ("/api/connectors", "/api/v2/mgp/automation/status")
    ]

    for legacy_path, mgp_path in mappings:
        route_versioning.register_route_mapping(
            legacy_path,
            mgp_path,
            deprecation_date="2025-12-31"
        )

    logger.info(f"Registered {len(mappings)} legacy-to-MGP route mappings")

def setup_route_versioning(app: FastAPI):
    """Set up route versioning for the FastAPI app"""

    # Add versioning middleware
    app.middleware("http")(route_versioning)

    # Register route mappings
    register_legacy_mgp_mappings()

    # Add version info endpoint
    @app.get("/api/version")
    async def get_api_version():
        return {
            "version": "2.0",
            "legacy_support": True,
            "master_game_plan": True,
            "namespaces": {
                "legacy": "/api",
                "mgp": "/api/v2/mgp",
                "shared": "/api/shared"
            },
            "deprecation_info": route_versioning.deprecated_routes
        }

    logger.info("Route versioning system initialized")

# Utility functions for route conflict detection
def detect_route_conflicts(app: FastAPI) -> Dict[str, Any]:
    """Detect potential route conflicts in the application"""

    conflicts = []
    all_routes = {}

    # Collect all routes
    for route in app.routes:
        if hasattr(route, 'path'):
            path = route.path
            methods = getattr(route, 'methods', ['GET'])

            for method in methods:
                route_key = f"{method}:{path}"
                if route_key in all_routes:
                    conflicts.append({
                        "path": path,
                        "method": method,
                        "existing_route": all_routes[route_key],
                        "conflicting_route": route
                    })
                else:
                    all_routes[route_key] = route

    return {
        "total_routes": len(all_routes),
        "conflicts": conflicts,
        "conflict_count": len(conflicts)
    }

def validate_namespace_isolation() -> Dict[str, Any]:
    """Validate that namespace isolation is working correctly"""

    validation_results = {
        "namespaces_configured": True,
        "prefix_conflicts": [],
        "isolation_status": "healthy"
    }

    # Check for prefix conflicts
    prefixes = [
        "/api",           # Legacy
        "/api/v2/mgp",    # Master Game Plan
        "/api/shared"     # Shared
    ]

    # Validate no overlapping prefixes
    for i, prefix1 in enumerate(prefixes):
        for j, prefix2 in enumerate(prefixes[i+1:], i+1):
            if prefix1.startswith(prefix2) or prefix2.startswith(prefix1):
                if prefix1 != prefix2:  # Allow exact matches
                    validation_results["prefix_conflicts"].append({
                        "prefix1": prefix1,
                        "prefix2": prefix2
                    })

    if validation_results["prefix_conflicts"]:
        validation_results["isolation_status"] = "conflicts_detected"

    return validation_results