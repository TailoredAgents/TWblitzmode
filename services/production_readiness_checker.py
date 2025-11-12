"""
Production Readiness Checker for VouchLink Link System
Validates system configuration, security, and deployment readiness

Features:
- Configuration validation
- Security assessment
- Performance benchmarking
- Dependency verification
- Environment validation
- Deployment checklist verification
"""

import os
import sys
import json
import logging
import asyncio
import importlib
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import subprocess
import pkg_resources

logger = logging.getLogger(__name__)

class CheckSeverity(Enum):
    """Severity levels for readiness checks"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

class CheckStatus(Enum):
    """Status of readiness checks"""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIP = "skip"

@dataclass
class ReadinessCheck:
    """Individual readiness check result"""
    name: str
    category: str
    status: CheckStatus
    severity: CheckSeverity
    message: str
    details: Optional[Dict[str, Any]] = None
    fix_suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "status": self.status.value,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
            "fix_suggestion": self.fix_suggestion
        }

class ProductionReadinessChecker:
    """
    Comprehensive production readiness checker for VouchLink Link system

    Validates all aspects of the system for production deployment including
    configuration, security, performance, and operational requirements.
    """

    def __init__(self):
        self.checks: List[ReadinessCheck] = []
        self.categories = [
            "environment",
            "configuration",
            "security",
            "dependencies",
            "services",
            "database",
            "monitoring",
            "logging",
            "performance",
            "deployment"
        ]

    async def run_all_checks(self) -> Dict[str, Any]:
        """Run all production readiness checks"""
        logger.info("Starting production readiness assessment...")

        self.checks = []

        # Run checks by category
        await self._check_environment()
        await self._check_configuration()
        await self._check_security()
        await self._check_dependencies()
        await self._check_services()
        await self._check_database()
        await self._check_monitoring()
        await self._check_logging()
        await self._check_performance()
        await self._check_deployment()

        # Generate summary
        summary = self._generate_summary()

        logger.info(f"Production readiness check completed. Status: {summary['overall_status']}")
        return summary

    async def _check_environment(self):
        """Check environment configuration"""
        category = "environment"

        # Check Python version
        python_version = sys.version_info
        if python_version >= (3, 8):
            self.checks.append(ReadinessCheck(
                name="python_version",
                category=category,
                status=CheckStatus.PASS,
                severity=CheckSeverity.CRITICAL,
                message=f"Python version {python_version.major}.{python_version.minor}.{python_version.micro} is supported",
                details={"version": f"{python_version.major}.{python_version.minor}.{python_version.micro}"}
            ))
        else:
            self.checks.append(ReadinessCheck(
                name="python_version",
                category=category,
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=f"Python version {python_version.major}.{python_version.minor} is not supported",
                details={"version": f"{python_version.major}.{python_version.minor}.{python_version.micro}"},
                fix_suggestion="Upgrade to Python 3.8 or higher"
            ))

        # Check environment variables
        required_env_vars = [
            "OPENAI_API_KEY",
            "NEXT_PUBLIC_API_URL",
            "DATABASE_URL"
        ]

        for env_var in required_env_vars:
            if os.getenv(env_var):
                self.checks.append(ReadinessCheck(
                    name=f"env_var_{env_var.lower()}",
                    category=category,
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Environment variable {env_var} is set",
                    details={"variable": env_var}
                ))
            else:
                self.checks.append(ReadinessCheck(
                    name=f"env_var_{env_var.lower()}",
                    category=category,
                    status=CheckStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Environment variable {env_var} is not set",
                    details={"variable": env_var},
                    fix_suggestion=f"Set {env_var} environment variable"
                ))

        # Check optional environment variables
        optional_env_vars = [
            "NEXT_PUBLIC_WS_URL",
            "REDIS_URL",
            "LOG_LEVEL"
        ]

        for env_var in optional_env_vars:
            if os.getenv(env_var):
                self.checks.append(ReadinessCheck(
                    name=f"optional_env_{env_var.lower()}",
                    category=category,
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.LOW,
                    message=f"Optional environment variable {env_var} is set",
                    details={"variable": env_var}
                ))
            else:
                self.checks.append(ReadinessCheck(
                    name=f"optional_env_{env_var.lower()}",
                    category=category,
                    status=CheckStatus.WARNING,
                    severity=CheckSeverity.LOW,
                    message=f"Optional environment variable {env_var} is not set",
                    details={"variable": env_var},
                    fix_suggestion=f"Consider setting {env_var} for enhanced functionality"
                ))

    async def _check_configuration(self):
        """Check system configuration"""
        category = "configuration"

        # Check if all agent services can be imported
        agent_services = [
            "master_chat_agent",
            "conversation_context_manager",
            "chat_security_filter",
            "chat_audit_logger",
            "chat_tool_registry",
            "browser_service"
        ]

        for service in agent_services:
            try:
                module = importlib.import_module(f"services.{service}")
                self.checks.append(ReadinessCheck(
                    name=f"import_{service}",
                    category=category,
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Service {service} imports successfully",
                    details={"service": service}
                ))
            except ImportError as e:
                self.checks.append(ReadinessCheck(
                    name=f"import_{service}",
                    category=category,
                    status=CheckStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Service {service} import failed: {str(e)}",
                    details={"service": service, "error": str(e)},
                    fix_suggestion=f"Fix import issues for {service}"
                ))

        # Check configuration files exist
        config_files = [
            "package.json",
            "next.config.js"
        ]

        for config_file in config_files:
            if os.path.exists(config_file):
                self.checks.append(ReadinessCheck(
                    name=f"config_file_{config_file.replace('.', '_')}",
                    category=category,
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.MEDIUM,
                    message=f"Configuration file {config_file} exists",
                    details={"file": config_file}
                ))
            else:
                self.checks.append(ReadinessCheck(
                    name=f"config_file_{config_file.replace('.', '_')}",
                    category=category,
                    status=CheckStatus.FAIL,
                    severity=CheckSeverity.MEDIUM,
                    message=f"Configuration file {config_file} not found",
                    details={"file": config_file},
                    fix_suggestion=f"Create {config_file} configuration file"
                ))

    async def _check_security(self):
        """Check security configuration"""
        category = "security"

        # Check if security filter is properly configured
        try:
            from services.chat_security_filter import chat_security_filter

            # Check security level
            security_level = chat_security_filter.security_level.value
            if security_level in ["HIGH", "PARANOID"]:
                self.checks.append(ReadinessCheck(
                    name="security_level",
                    category=category,
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Security level is appropriately set to {security_level}",
                    details={"level": security_level}
                ))
            else:
                self.checks.append(ReadinessCheck(
                    name="security_level",
                    category=category,
                    status=CheckStatus.WARNING,
                    severity=CheckSeverity.HIGH,
                    message=f"Security level {security_level} may be too low for production",
                    details={"level": security_level},
                    fix_suggestion="Set security level to HIGH or PARANOID for production"
                ))

        except ImportError:
            self.checks.append(ReadinessCheck(
                name="security_filter_import",
                category=category,
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message="Security filter service not available",
                fix_suggestion="Ensure chat_security_filter service is properly implemented"
            ))

        # Check for sensitive data in environment
        env_vars_to_check = os.environ.keys()
        exposed_secrets = []

        for var in env_vars_to_check:
            value = os.getenv(var, "")
            if any(keyword in var.upper() for keyword in ["KEY", "SECRET", "TOKEN", "PASSWORD"]):
                if len(value) > 0 and not value.startswith("$"):  # Not a placeholder
                    exposed_secrets.append(var)

        if exposed_secrets:
            self.checks.append(ReadinessCheck(
                name="environment_secrets",
                category=category,
                status=CheckStatus.WARNING,
                severity=CheckSeverity.HIGH,
                message=f"Found {len(exposed_secrets)} potential secrets in environment",
                details={"secret_vars": exposed_secrets},
                fix_suggestion="Ensure sensitive environment variables are properly managed"
            ))
        else:
            self.checks.append(ReadinessCheck(
                name="environment_secrets",
                category=category,
                status=CheckStatus.PASS,
                severity=CheckSeverity.HIGH,
                message="No obvious secrets found in environment variables"
            ))

    async def _check_dependencies(self):
        """Check required dependencies"""
        category = "dependencies"

        # Check critical Python packages
        critical_packages = [
            "fastapi",
            "openai",
            "psutil",
            "asyncio"
        ]

        for package in critical_packages:
            try:
                version = pkg_resources.get_distribution(package).version
                self.checks.append(ReadinessCheck(
                    name=f"package_{package}",
                    category=category,
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Package {package} is installed (v{version})",
                    details={"package": package, "version": version}
                ))
            except pkg_resources.DistributionNotFound:
                self.checks.append(ReadinessCheck(
                    name=f"package_{package}",
                    category=category,
                    status=CheckStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Critical package {package} is not installed",
                    details={"package": package},
                    fix_suggestion=f"Install {package} using pip install {package}"
                ))

        # Check Node.js dependencies
        if os.path.exists("package.json"):
            try:
                result = subprocess.run(["npm", "list", "--depth=0"],
                                      capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    self.checks.append(ReadinessCheck(
                        name="npm_dependencies",
                        category=category,
                        status=CheckStatus.PASS,
                        severity=CheckSeverity.HIGH,
                        message="npm dependencies are properly installed"
                    ))
                else:
                    self.checks.append(ReadinessCheck(
                        name="npm_dependencies",
                        category=category,
                        status=CheckStatus.FAIL,
                        severity=CheckSeverity.HIGH,
                        message="npm dependencies check failed",
                        details={"error": result.stderr},
                        fix_suggestion="Run 'npm install' to install dependencies"
                    ))
            except (subprocess.TimeoutExpired, FileNotFoundError):
                self.checks.append(ReadinessCheck(
                    name="npm_dependencies",
                    category=category,
                    status=CheckStatus.WARNING,
                    severity=CheckSeverity.MEDIUM,
                    message="Could not check npm dependencies (npm not found or timeout)",
                    fix_suggestion="Ensure Node.js and npm are installed"
                ))

    async def _check_services(self):
        """Check service availability"""
        category = "services"

        # Check if services can be instantiated
        services_to_check = [
            ("master_chat_agent", "services.master_chat_agent"),
            ("monitoring_service", "services.link_monitoring_service"),
            ("browser_service", "services.browser_service")
        ]

        for service_name, module_path in services_to_check:
            try:
                module = importlib.import_module(module_path)
                # Try to access the service instance
                if hasattr(module, service_name):
                    service = getattr(module, service_name)
                    self.checks.append(ReadinessCheck(
                        name=f"service_{service_name}",
                        category=category,
                        status=CheckStatus.PASS,
                        severity=CheckSeverity.CRITICAL,
                        message=f"Service {service_name} is available and instantiated",
                        details={"service": service_name}
                    ))
                else:
                    self.checks.append(ReadinessCheck(
                        name=f"service_{service_name}",
                        category=category,
                        status=CheckStatus.FAIL,
                        severity=CheckSeverity.CRITICAL,
                        message=f"Service {service_name} instance not found in module",
                        details={"service": service_name},
                        fix_suggestion=f"Ensure {service_name} is properly instantiated"
                    ))
            except Exception as e:
                self.checks.append(ReadinessCheck(
                    name=f"service_{service_name}",
                    category=category,
                    status=CheckStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Service {service_name} check failed: {str(e)}",
                    details={"service": service_name, "error": str(e)},
                    fix_suggestion=f"Fix issues with {service_name} service"
                ))

    async def _check_database(self):
        """Check database configuration"""
        category = "database"

        database_url = os.getenv("DATABASE_URL")
        if database_url:
            # Parse database URL
            if database_url.startswith("postgresql://"):
                self.checks.append(ReadinessCheck(
                    name="database_url_format",
                    category=category,
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.CRITICAL,
                    message="Database URL format is valid (PostgreSQL)",
                    details={"url_type": "postgresql"}
                ))
            else:
                self.checks.append(ReadinessCheck(
                    name="database_url_format",
                    category=category,
                    status=CheckStatus.WARNING,
                    severity=CheckSeverity.MEDIUM,
                    message=f"Database URL format may not be optimal: {database_url[:20]}...",
                    details={"url_type": "unknown"},
                    fix_suggestion="Consider using PostgreSQL for production"
                ))

            # Check if URL contains sensitive data
            if "localhost" in database_url or "127.0.0.1" in database_url:
                self.checks.append(ReadinessCheck(
                    name="database_location",
                    category=category,
                    status=CheckStatus.WARNING,
                    severity=CheckSeverity.MEDIUM,
                    message="Database appears to be local (localhost)",
                    fix_suggestion="Use external database service for production"
                ))
            else:
                self.checks.append(ReadinessCheck(
                    name="database_location",
                    category=category,
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.MEDIUM,
                    message="Database appears to be external (production-ready)"
                ))

    async def _check_monitoring(self):
        """Check monitoring configuration"""
        category = "monitoring"

        try:
            from services.link_monitoring_service import link_monitoring_service

            # Check if monitoring service is working
            status = await link_monitoring_service.get_system_status()

            self.checks.append(ReadinessCheck(
                name="monitoring_service",
                category=category,
                status=CheckStatus.PASS,
                severity=CheckSeverity.HIGH,
                message="Monitoring service is operational",
                details={"service_status": status.get("status", "unknown")}
            ))

            # Check if health checks are configured
            health_checks = status.get("health_checks", {})
            if len(health_checks) >= 5:
                self.checks.append(ReadinessCheck(
                    name="health_checks",
                    category=category,
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.HIGH,
                    message=f"Health checks configured ({len(health_checks)} checks)",
                    details={"check_count": len(health_checks)}
                ))
            else:
                self.checks.append(ReadinessCheck(
                    name="health_checks",
                    category=category,
                    status=CheckStatus.WARNING,
                    severity=CheckSeverity.MEDIUM,
                    message=f"Limited health checks configured ({len(health_checks)} checks)",
                    details={"check_count": len(health_checks)},
                    fix_suggestion="Configure additional health checks for comprehensive monitoring"
                ))

        except Exception as e:
            self.checks.append(ReadinessCheck(
                name="monitoring_service",
                category=category,
                status=CheckStatus.FAIL,
                severity=CheckSeverity.HIGH,
                message=f"Monitoring service check failed: {str(e)}",
                details={"error": str(e)},
                fix_suggestion="Ensure monitoring service is properly configured"
            ))

    async def _check_logging(self):
        """Check logging configuration"""
        category = "logging"

        # Check log level configuration
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        if log_level in ["INFO", "WARNING", "ERROR"]:
            self.checks.append(ReadinessCheck(
                name="log_level",
                category=category,
                status=CheckStatus.PASS,
                severity=CheckSeverity.MEDIUM,
                message=f"Log level is appropriately set to {log_level}",
                details={"level": log_level}
            ))
        elif log_level == "DEBUG":
            self.checks.append(ReadinessCheck(
                name="log_level",
                category=category,
                status=CheckStatus.WARNING,
                severity=CheckSeverity.MEDIUM,
                message="Log level DEBUG may be too verbose for production",
                details={"level": log_level},
                fix_suggestion="Consider setting LOG_LEVEL to INFO for production"
            ))

        # Check if audit logging is configured
        try:
            from services.chat_audit_logger import chat_audit_logger
            self.checks.append(ReadinessCheck(
                name="audit_logging",
                category=category,
                status=CheckStatus.PASS,
                severity=CheckSeverity.HIGH,
                message="Audit logging service is available",
                details={"service": "chat_audit_logger"}
            ))
        except ImportError:
            self.checks.append(ReadinessCheck(
                name="audit_logging",
                category=category,
                status=CheckStatus.FAIL,
                severity=CheckSeverity.HIGH,
                message="Audit logging service not available",
                fix_suggestion="Ensure audit logging service is properly implemented"
            ))

    async def _check_performance(self):
        """Check performance configuration"""
        category = "performance"

        # Basic performance checks
        import psutil

        # CPU count
        cpu_count = psutil.cpu_count()
        if cpu_count >= 2:
            self.checks.append(ReadinessCheck(
                name="cpu_cores",
                category=category,
                status=CheckStatus.PASS,
                severity=CheckSeverity.MEDIUM,
                message=f"Adequate CPU cores available ({cpu_count} cores)",
                details={"cpu_count": cpu_count}
            ))
        else:
            self.checks.append(ReadinessCheck(
                name="cpu_cores",
                category=category,
                status=CheckStatus.WARNING,
                severity=CheckSeverity.MEDIUM,
                message=f"Limited CPU cores ({cpu_count} cores)",
                details={"cpu_count": cpu_count},
                fix_suggestion="Consider upgrading to instance with more CPU cores"
            ))

        # Memory
        memory = psutil.virtual_memory()
        memory_gb = memory.total / (1024**3)
        if memory_gb >= 2:
            self.checks.append(ReadinessCheck(
                name="memory_size",
                category=category,
                status=CheckStatus.PASS,
                severity=CheckSeverity.MEDIUM,
                message=f"Adequate memory available ({memory_gb:.1f} GB)",
                details={"memory_gb": round(memory_gb, 1)}
            ))
        else:
            self.checks.append(ReadinessCheck(
                name="memory_size",
                category=category,
                status=CheckStatus.WARNING,
                severity=CheckSeverity.MEDIUM,
                message=f"Limited memory available ({memory_gb:.1f} GB)",
                details={"memory_gb": round(memory_gb, 1)},
                fix_suggestion="Consider upgrading to instance with more memory"
            ))

    async def _check_deployment(self):
        """Check deployment configuration"""
        category = "deployment"

        # Check if we're in a containerized environment
        if os.path.exists("/.dockerenv") or os.getenv("KUBERNETES_SERVICE_HOST"):
            self.checks.append(ReadinessCheck(
                name="containerized_environment",
                category=category,
                status=CheckStatus.PASS,
                severity=CheckSeverity.INFO,
                message="Running in containerized environment",
                details={"containerized": True}
            ))
        else:
            self.checks.append(ReadinessCheck(
                name="containerized_environment",
                category=category,
                status=CheckStatus.WARNING,
                severity=CheckSeverity.LOW,
                message="Not running in containerized environment",
                details={"containerized": False},
                fix_suggestion="Consider containerizing for production deployment"
            ))

        # Check for production indicators
        node_env = os.getenv("NODE_ENV", "").lower()
        if node_env == "production":
            self.checks.append(ReadinessCheck(
                name="node_env",
                category=category,
                status=CheckStatus.PASS,
                severity=CheckSeverity.MEDIUM,
                message="NODE_ENV is set to production",
                details={"node_env": node_env}
            ))
        else:
            self.checks.append(ReadinessCheck(
                name="node_env",
                category=category,
                status=CheckStatus.WARNING,
                severity=CheckSeverity.MEDIUM,
                message=f"NODE_ENV is set to '{node_env}', not 'production'",
                details={"node_env": node_env},
                fix_suggestion="Set NODE_ENV=production for production deployment"
            ))

    def _generate_summary(self) -> Dict[str, Any]:
        """Generate readiness assessment summary"""
        # Count checks by status
        status_counts = {status.value: 0 for status in CheckStatus}
        severity_counts = {severity.value: 0 for severity in CheckSeverity}
        category_counts = {category: {"pass": 0, "fail": 0, "warning": 0, "skip": 0}
                          for category in self.categories}

        critical_failures = []
        high_priority_issues = []

        for check in self.checks:
            status_counts[check.status.value] += 1
            severity_counts[check.severity.value] += 1
            category_counts[check.category][check.status.value] += 1

            if check.status == CheckStatus.FAIL and check.severity == CheckSeverity.CRITICAL:
                critical_failures.append(check)
            elif check.status in [CheckStatus.FAIL, CheckStatus.WARNING] and check.severity == CheckSeverity.HIGH:
                high_priority_issues.append(check)

        # Determine overall readiness
        if critical_failures:
            overall_status = "NOT_READY"
            readiness_score = 0
        elif len(high_priority_issues) > 3:
            overall_status = "NEEDS_ATTENTION"
            readiness_score = 40
        elif status_counts["fail"] > 0 or len(high_priority_issues) > 0:
            overall_status = "PARTIALLY_READY"
            readiness_score = 70
        else:
            overall_status = "READY"
            readiness_score = 95

        # Calculate detailed readiness score
        total_checks = len(self.checks)
        if total_checks > 0:
            weighted_score = 0
            for check in self.checks:
                if check.status == CheckStatus.PASS:
                    weight = {"critical": 10, "high": 7, "medium": 5, "low": 3, "info": 1}[check.severity.value]
                    weighted_score += weight
                elif check.status == CheckStatus.WARNING:
                    weight = {"critical": 5, "high": 3, "medium": 2, "low": 1, "info": 0}[check.severity.value]
                    weighted_score += weight
                # FAIL contributes 0 to score

            max_possible_score = sum(
                {"critical": 10, "high": 7, "medium": 5, "low": 3, "info": 1}[check.severity.value]
                for check in self.checks
            )

            if max_possible_score > 0:
                readiness_score = int((weighted_score / max_possible_score) * 100)

        return {
            "overall_status": overall_status,
            "readiness_score": readiness_score,
            "assessment_time": datetime.now(timezone.utc).isoformat(),
            "total_checks": total_checks,
            "status_summary": status_counts,
            "severity_summary": severity_counts,
            "category_summary": category_counts,
            "critical_failures": [check.to_dict() for check in critical_failures],
            "high_priority_issues": [check.to_dict() for check in high_priority_issues],
            "all_checks": [check.to_dict() for check in self.checks],
            "recommendations": self._generate_recommendations(critical_failures, high_priority_issues)
        }

    def _generate_recommendations(self, critical_failures: List[ReadinessCheck],
                                high_priority_issues: List[ReadinessCheck]) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []

        if critical_failures:
            recommendations.append("🚨 CRITICAL: Address all critical failures before production deployment")
            for failure in critical_failures[:3]:  # Top 3
                if failure.fix_suggestion:
                    recommendations.append(f"• {failure.fix_suggestion}")

        if high_priority_issues:
            recommendations.append("⚠️ HIGH PRIORITY: Resolve high-priority issues for optimal production readiness")
            for issue in high_priority_issues[:3]:  # Top 3
                if issue.fix_suggestion:
                    recommendations.append(f"• {issue.fix_suggestion}")

        if not critical_failures and not high_priority_issues:
            recommendations.extend([
                "✅ System appears ready for production deployment",
                "• Continue monitoring system health after deployment",
                "• Set up alerting for key metrics",
                "• Plan regular security audits"
            ])

        return recommendations

# Global readiness checker instance
production_readiness_checker = ProductionReadinessChecker()