#!/usr/bin/env python3
"""
Environment Variables Validation Service
Comprehensive validation and configuration status for all external dependencies
September 2025 - Production Readiness Enhancement
"""

import os
import logging
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
import httpx
import asyncpg
import redis

logger = logging.getLogger(__name__)

class ServiceStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    NOT_CONFIGURED = "not_configured"
    MISSING = "missing"

class ServicePriority(Enum):
    CRITICAL = "critical"      # Service failure blocks all operations
    HIGH = "high"             # Service failure blocks major features
    MEDIUM = "medium"         # Service failure blocks some features
    LOW = "low"               # Service failure only affects optional features

@dataclass
class ServiceConfig:
    """Configuration for a service dependency"""
    name: str
    description: str
    required_env_vars: List[str]
    optional_env_vars: List[str]
    priority: ServicePriority
    health_check_url: Optional[str] = None
    health_check_method: str = "GET"
    timeout_seconds: int = 10
    validation_function: Optional[callable] = None

@dataclass
class ServiceValidationResult:
    """Result of service validation"""
    name: str
    status: ServiceStatus
    priority: ServicePriority
    configured_vars: List[str]
    missing_vars: List[str]
    health_check_result: Optional[Dict[str, Any]]
    error_message: Optional[str]
    recommendations: List[str]
    last_checked: datetime

class EnvironmentValidationService:
    """
    Comprehensive environment validation for all external dependencies
    """

    def __init__(self):
        self.services_config = self._initialize_services_config()
        self.last_validation_time = None
        self.validation_results = {}

    def _initialize_services_config(self) -> Dict[str, ServiceConfig]:
        """Initialize configuration for all services"""
        return {
            # Database Services
            "postgresql": ServiceConfig(
                name="PostgreSQL Database",
                description="Primary database for application data",
                required_env_vars=["DATABASE_URL"],
                optional_env_vars=["DB_POOL_SIZE", "DB_MAX_CONNECTIONS"],
                priority=ServicePriority.CRITICAL,
                validation_function=self._validate_postgresql
            ),

            "redis": ServiceConfig(
                name="Redis Cache",
                description="Caching and session storage",
                required_env_vars=["REDIS_URL"],
                optional_env_vars=["REDIS_TTL", "REDIS_MAX_CONNECTIONS"],
                priority=ServicePriority.HIGH,
                validation_function=self._validate_redis
            ),

            # External API Services
            "clearbit": ServiceConfig(
                name="Clearbit API",
                description="Company and person data enrichment",
                required_env_vars=["CLEARBIT_API_KEY"],
                optional_env_vars=["CLEARBIT_TIMEOUT"],
                priority=ServicePriority.MEDIUM,
                health_check_url="https://person.clearbit.com/v2/people/find",
                validation_function=self._validate_clearbit
            ),

            "apollo": ServiceConfig(
                name="Apollo API",
                description="Contact discovery and enrichment",
                required_env_vars=["APOLLO_API_KEY"],
                optional_env_vars=["APOLLO_TIMEOUT", "APOLLO_RATE_LIMIT"],
                priority=ServicePriority.MEDIUM,
                health_check_url="https://api.apollo.io/v1/auth/health",
                validation_function=self._validate_apollo
            ),

            "cufinder": ServiceConfig(
                name="CUFinder API",
                description="Email finding and verification",
                required_env_vars=["CUFINDER_API_KEY"],
                optional_env_vars=["CUFINDER_TIMEOUT"],
                priority=ServicePriority.MEDIUM,
                validation_function=self._validate_cufinder
            ),

            "hunter": ServiceConfig(
                name="Hunter API",
                description="Email discovery and verification",
                required_env_vars=["HUNTER_API_KEY"],
                optional_env_vars=["HUNTER_TIMEOUT"],
                priority=ServicePriority.MEDIUM,
                validation_function=self._validate_hunter
            ),

            "sendgrid": ServiceConfig(
                name="SendGrid Email",
                description="Email delivery service",
                required_env_vars=["SENDGRID_API_KEY"],
                optional_env_vars=["SENDGRID_FROM_EMAIL", "SENDGRID_FROM_NAME"],
                priority=ServicePriority.HIGH,
                health_check_url="https://api.sendgrid.com/v3/user/profile",
                validation_function=self._validate_sendgrid
            ),

            "apify": ServiceConfig(
                name="Apify Actors",
                description="LinkedIn scraping and automation",
                required_env_vars=["APIFY_TOKEN"],
                optional_env_vars=["APIFY_ACTOR_ID", "APIFY_TIMEOUT"],
                priority=ServicePriority.MEDIUM,
                validation_function=self._validate_apify
            ),

            "phantombuster": ServiceConfig(
                name="PhantomBuster",
                description="LinkedIn automation and data extraction",
                required_env_vars=["PHANTOMBUSTER_API_KEY"],
                optional_env_vars=["PHANTOMBUSTER_TIMEOUT"],
                priority=ServicePriority.LOW,
                validation_function=self._validate_phantombuster
            ),

            # AI Services
            "openai": ServiceConfig(
                name="OpenAI API",
                description="AI-powered content generation and analysis",
                required_env_vars=["OPENAI_API_KEY"],
                optional_env_vars=["OPENAI_MODEL", "OPENAI_TIMEOUT"],
                priority=ServicePriority.HIGH,
                health_check_url="https://api.openai.com/v1/models",
                validation_function=self._validate_openai
            ),

            "cors_origins": ServiceConfig(
                name="CORS Configuration",
                description="Cross-origin resource sharing settings",
                required_env_vars=[],
                optional_env_vars=["ALLOWED_ORIGINS", "CORS_ALLOW_CREDENTIALS"],
                priority=ServicePriority.MEDIUM,
                validation_function=self._validate_cors
            )
        }

    async def validate_all_services(self) -> Dict[str, ServiceValidationResult]:
        """Validate all configured services"""
        logger.info("🔍 Starting comprehensive environment validation...")

        results = {}
        tasks = []

        # Create validation tasks for all services
        for service_name, config in self.services_config.items():
            tasks.append(self._validate_service(service_name, config))

        # Run all validations concurrently
        validation_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for i, result in enumerate(validation_results):
            service_name = list(self.services_config.keys())[i]

            if isinstance(result, Exception):
                results[service_name] = ServiceValidationResult(
                    name=service_name,
                    status=ServiceStatus.UNHEALTHY,
                    priority=self.services_config[service_name].priority,
                    configured_vars=[],
                    missing_vars=self.services_config[service_name].required_env_vars,
                    health_check_result=None,
                    error_message=str(result),
                    recommendations=[f"Fix validation error: {str(result)}"],
                    last_checked=datetime.now(timezone.utc)
                )
            else:
                results[service_name] = result

        self.validation_results = results
        self.last_validation_time = datetime.now(timezone.utc)

        # Log summary
        self._log_validation_summary(results)

        return results

    async def _validate_service(self, service_name: str, config: ServiceConfig) -> ServiceValidationResult:
        """Validate a single service"""
        try:
            # Check environment variables
            configured_vars = []
            missing_vars = []

            for var in config.required_env_vars:
                if os.getenv(var):
                    configured_vars.append(var)
                else:
                    missing_vars.append(var)

            for var in config.optional_env_vars:
                if os.getenv(var):
                    configured_vars.append(var)

            # Determine base status
            if missing_vars:
                status = ServiceStatus.NOT_CONFIGURED
            else:
                status = ServiceStatus.HEALTHY

            # Run custom validation if available
            health_check_result = None
            if config.validation_function and not missing_vars:
                try:
                    health_check_result = await config.validation_function()
                    if not health_check_result.get("success", False):
                        status = ServiceStatus.UNHEALTHY
                except Exception as e:
                    status = ServiceStatus.DEGRADED
                    health_check_result = {"success": False, "error": str(e)}

            # Generate recommendations
            recommendations = self._generate_recommendations(config, missing_vars, status)

            return ServiceValidationResult(
                name=config.name,
                status=status,
                priority=config.priority,
                configured_vars=configured_vars,
                missing_vars=missing_vars,
                health_check_result=health_check_result,
                error_message=None,
                recommendations=recommendations,
                last_checked=datetime.now(timezone.utc)
            )

        except Exception as e:
            return ServiceValidationResult(
                name=config.name,
                status=ServiceStatus.UNHEALTHY,
                priority=config.priority,
                configured_vars=[],
                missing_vars=config.required_env_vars,
                health_check_result=None,
                error_message=str(e),
                recommendations=[f"Fix validation error: {str(e)}"],
                last_checked=datetime.now(timezone.utc)
            )

    def _generate_recommendations(self, config: ServiceConfig, missing_vars: List[str], status: ServiceStatus) -> List[str]:
        """Generate recommendations for service configuration"""
        recommendations = []

        if missing_vars:
            recommendations.append(f"Configure missing environment variables: {', '.join(missing_vars)}")

        if status == ServiceStatus.NOT_CONFIGURED and config.priority == ServicePriority.CRITICAL:
            recommendations.append("⚠️ This is a CRITICAL service - application may not function without it")

        if status == ServiceStatus.DEGRADED:
            recommendations.append("Service is partially functional - check logs for specific issues")

        if status == ServiceStatus.UNHEALTHY:
            recommendations.append("Service health check failed - verify configuration and network connectivity")

        # Service-specific recommendations
        if config.name == "PostgreSQL Database" and missing_vars:
            recommendations.append("Example: DATABASE_URL=postgresql://user:pass@host:5432/dbname")

        if config.name == "SendGrid Email" and missing_vars:
            recommendations.append("Get API key from https://app.sendgrid.com/settings/api_keys")

        if config.name == "OpenAI API" and missing_vars:
            recommendations.append("Get API key from https://platform.openai.com/api-keys")

        return recommendations

    # Service-specific validation functions

    async def _validate_postgresql(self) -> Dict[str, Any]:
        """Validate PostgreSQL connection"""
        try:
            database_url = os.getenv("DATABASE_URL")
            if not database_url:
                return {"success": False, "error": "DATABASE_URL not configured"}

            # Test connection
            conn = await asyncpg.connect(database_url)
            result = await conn.fetchval("SELECT 1")
            await conn.close()

            return {
                "success": True,
                "connection_test": "passed",
                "version": await self._get_postgresql_version(database_url)
            }

        except Exception as e:
            return {"success": False, "error": f"PostgreSQL connection failed: {str(e)}"}

    async def _validate_redis(self) -> Dict[str, Any]:
        """Validate Redis connection"""
        try:
            redis_url = os.getenv("REDIS_URL")
            if not redis_url:
                return {"success": False, "error": "REDIS_URL not configured"}

            # Test connection
            r = redis.from_url(redis_url)
            r.ping()
            r.close()

            return {"success": True, "connection_test": "passed"}

        except Exception as e:
            return {"success": False, "error": f"Redis connection failed: {str(e)}"}

    async def _validate_sendgrid(self) -> Dict[str, Any]:
        """Validate SendGrid API"""
        try:
            api_key = os.getenv("SENDGRID_API_KEY")
            if not api_key:
                return {"success": False, "error": "SENDGRID_API_KEY not configured"}

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.sendgrid.com/v3/user/profile",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0
                )

                if response.status_code == 200:
                    return {"success": True, "api_test": "passed"}
                else:
                    return {"success": False, "error": f"SendGrid API returned {response.status_code}"}

        except Exception as e:
            return {"success": False, "error": f"SendGrid validation failed: {str(e)}"}

    async def _validate_openai(self) -> Dict[str, Any]:
        """Validate OpenAI API"""
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                return {"success": False, "error": "OPENAI_API_KEY not configured"}

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0
                )

                if response.status_code == 200:
                    models = response.json()
                    return {
                        "success": True,
                        "api_test": "passed",
                        "available_models": len(models.get("data", []))
                    }
                else:
                    return {"success": False, "error": f"OpenAI API returned {response.status_code}"}

        except Exception as e:
            return {"success": False, "error": f"OpenAI validation failed: {str(e)}"}

    async def _validate_clearbit(self) -> Dict[str, Any]:
        """Validate Clearbit API"""
        try:
            api_key = os.getenv("CLEARBIT_API_KEY")
            if not api_key:
                return {"success": False, "error": "CLEARBIT_API_KEY not configured"}

            # Simple API test (won't actually call with test data)
            return {"success": True, "api_key_configured": True}

        except Exception as e:
            return {"success": False, "error": f"Clearbit validation failed: {str(e)}"}

    async def _validate_apollo(self) -> Dict[str, Any]:
        """Validate Apollo API"""
        try:
            api_key = os.getenv("APOLLO_API_KEY")
            if not api_key:
                return {"success": False, "error": "APOLLO_API_KEY not configured"}

            return {"success": True, "api_key_configured": True}

        except Exception as e:
            return {"success": False, "error": f"Apollo validation failed: {str(e)}"}

    async def _validate_cufinder(self) -> Dict[str, Any]:
        """Validate CUFinder API"""
        try:
            api_key = os.getenv("CUFINDER_API_KEY")
            if not api_key:
                return {"success": False, "error": "CUFINDER_API_KEY not configured"}

            return {"success": True, "api_key_configured": True}

        except Exception as e:
            return {"success": False, "error": f"CUFinder validation failed: {str(e)}"}

    async def _validate_hunter(self) -> Dict[str, Any]:
        """Validate Hunter API"""
        try:
            api_key = os.getenv("HUNTER_API_KEY")
            if not api_key:
                return {"success": False, "error": "HUNTER_API_KEY not configured"}

            return {"success": True, "api_key_configured": True}

        except Exception as e:
            return {"success": False, "error": f"Hunter validation failed: {str(e)}"}

    async def _validate_apify(self) -> Dict[str, Any]:
        """Validate Apify API"""
        try:
            token = os.getenv("APIFY_TOKEN")
            if not token:
                return {"success": False, "error": "APIFY_TOKEN not configured"}

            return {"success": True, "api_token_configured": True}

        except Exception as e:
            return {"success": False, "error": f"Apify validation failed: {str(e)}"}

    async def _validate_phantombuster(self) -> Dict[str, Any]:
        """Validate PhantomBuster API"""
        try:
            api_key = os.getenv("PHANTOMBUSTER_API_KEY")
            if not api_key:
                return {"success": False, "error": "PHANTOMBUSTER_API_KEY not configured"}

            return {"success": True, "api_key_configured": True}

        except Exception as e:
            return {"success": False, "error": f"PhantomBuster validation failed: {str(e)}"}

    async def _validate_cors(self) -> Dict[str, Any]:
        """Validate CORS configuration"""
        try:
            origins = os.getenv("ALLOWED_ORIGINS")
            if not origins:
                return {"success": True, "note": "Using default CORS configuration"}

            # Validate origins format
            origin_list = origins.split(",")
            return {"success": True, "origins_count": len(origin_list)}

        except Exception as e:
            return {"success": False, "error": f"CORS validation failed: {str(e)}"}

    async def _get_postgresql_version(self, database_url: str) -> str:
        """Get PostgreSQL version"""
        try:
            conn = await asyncpg.connect(database_url)
            version = await conn.fetchval("SELECT version()")
            await conn.close()
            return version.split()[1] if version else "unknown"
        except Exception:
            return "unknown"

    def _log_validation_summary(self, results: Dict[str, ServiceValidationResult]):
        """Log validation summary"""
        critical_issues = []
        high_issues = []
        total_services = len(results)
        healthy_services = 0

        for service_name, result in results.items():
            if result.status == ServiceStatus.HEALTHY:
                healthy_services += 1
            elif result.priority == ServicePriority.CRITICAL and result.status != ServiceStatus.HEALTHY:
                critical_issues.append(service_name)
            elif result.priority == ServicePriority.HIGH and result.status != ServiceStatus.HEALTHY:
                high_issues.append(service_name)

        logger.info(f"🔍 Environment validation complete: {healthy_services}/{total_services} services healthy")

        if critical_issues:
            logger.error(f"❌ CRITICAL issues found: {', '.join(critical_issues)}")

        if high_issues:
            logger.warning(f"⚠️ HIGH priority issues found: {', '.join(high_issues)}")

        if not critical_issues and not high_issues:
            logger.info("✅ All critical and high-priority services are healthy")

    def get_configuration_status(self) -> Dict[str, Any]:
        """Get overall configuration status"""
        if not self.validation_results:
            return {
                "status": "not_validated",
                "message": "Environment validation has not been run yet"
            }

        critical_healthy = all(
            result.status == ServiceStatus.HEALTHY
            for result in self.validation_results.values()
            if result.priority == ServicePriority.CRITICAL
        )

        high_healthy = all(
            result.status in [ServiceStatus.HEALTHY, ServiceStatus.NOT_CONFIGURED]
            for result in self.validation_results.values()
            if result.priority == ServicePriority.HIGH
        )

        if critical_healthy and high_healthy:
            overall_status = "healthy"
        elif critical_healthy:
            overall_status = "degraded"
        else:
            overall_status = "unhealthy"

        return {
            "status": overall_status,
            "last_validated": self.last_validation_time.isoformat() if self.last_validation_time else None,
            "services": {
                name: {
                    "status": result.status.value,
                    "priority": result.priority.value,
                    "configured_vars": result.configured_vars,
                    "missing_vars": result.missing_vars,
                    "recommendations": result.recommendations
                }
                for name, result in self.validation_results.items()
            }
        }

# Global service instance
environment_validator = EnvironmentValidationService()

async def validate_environment_on_startup():
    """Validate environment during application startup"""
    logger.info("🚀 Running environment validation on startup...")

    results = await environment_validator.validate_all_services()

    # Check for critical failures
    critical_failures = [
        name for name, result in results.items()
        if result.priority == ServicePriority.CRITICAL and result.status != ServiceStatus.HEALTHY
    ]

    if critical_failures:
        error_msg = f"❌ Critical services not configured: {', '.join(critical_failures)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info("✅ Environment validation passed - application ready to start")
    return results
