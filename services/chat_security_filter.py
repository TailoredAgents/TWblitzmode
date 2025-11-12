"""
Advanced Security Filtering Service for Link Master Chat Agent
Provides comprehensive data redaction, tenant isolation, and security enforcement

Features:
- Advanced pattern matching for sensitive data
- Configurable redaction rules per organization
- Service name obfuscation (hides Apify, PhantomBuster, etc.)
- Security violation detection and alerting
- Audit trail for all redacted content
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Set, Optional, Any, Tuple

logger = logging.getLogger(__name__)

class SecurityLevel(Enum):
    """Security filtering levels"""
    LOW = "low"        # Basic API key filtering
    MEDIUM = "medium"  # Standard production filtering
    HIGH = "high"      # Maximum security with service obfuscation
    PARANOID = "paranoid"  # Redact everything potentially sensitive

class ViolationType(Enum):
    """Types of security violations"""
    API_KEY_EXPOSURE = "api_key_exposure"
    TOKEN_LEAK = "token_leak"
    SERVICE_NAME_EXPOSURE = "service_name_exposure"
    INTERNAL_URL_EXPOSURE = "internal_url_exposure"
    DATABASE_INFO_LEAK = "database_info_leak"
    CREDENTIAL_EXPOSURE = "credential_exposure"
    PII_LEAK = "pii_leak"

@dataclass
class SecurityViolation:
    """Security violation detection result"""
    violation_type: ViolationType
    severity: str  # low, medium, high, critical
    pattern_matched: str
    original_text: str
    redacted_text: str
    confidence: float
    context: str
    timestamp: datetime

@dataclass
class FilterResult:
    """Result of security filtering operation"""
    filtered_text: str
    violations: List[SecurityViolation]
    redactions_count: int
    security_score: float  # 0-100, higher is more secure

class ChatSecurityFilter:
    """
    Advanced security filtering for chat responses

    Provides multi-layered security filtering with configurable rules,
    tenant-specific policies, and comprehensive audit logging.
    """

    def __init__(self, security_level: SecurityLevel = SecurityLevel.HIGH):
        self.security_level = security_level
        self.violation_history: List[SecurityViolation] = []
        self.global_custom_patterns = self._load_global_patterns()
        self.tenant_custom_patterns: Dict[int, List[str]] = {}
        self._load_tenant_patterns_from_env()

        # Enhanced sensitive patterns with categorization
        self.sensitive_patterns = {
            # API Keys and Tokens
            "openai_keys": [
                r"sk-[a-zA-Z0-9-_]{32,}",  # OpenAI API keys
                r"sk-proj-[a-zA-Z0-9-_]{32,}",  # OpenAI project keys
            ],
            "bearer_tokens": [
                r"Bearer\s+[a-zA-Z0-9-_.]{20,}",  # Bearer tokens
                r"Authorization:\s*Bearer\s+[a-zA-Z0-9-_.]{20,}",
            ],
            "generic_tokens": [
                r"(?i)(?:api[_-]?key|token|secret)[\"']?\s*[:=]\s*[\"']?([a-zA-Z0-9-_]{16,})[\"']?",
                r"(?i)(?:password|pwd)[\"']?\s*[:=]\s*[\"']?([^\s\"']{8,})[\"']?",
            ],

            # Service Names (obfuscate third-party services)
            "service_names": [
                r"(?i)\b(apify|phantombuster|scrapfly|brightdata|proxycrawl)\b",
                r"(?i)\b(linkedin\s*scraper|profile\s*scraper|data\s*scraper)\b",
                r"(?i)\b(automation\s*tool|scraping\s*service|data\s*extraction)\b",
            ],

            # Internal URLs and endpoints
            "internal_urls": [
                r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):\d+",
                r"https?://.*\.internal\b",
                r"https?://.*\.local\b",
                r"(?i)\b(?:staging|dev|test|admin)\.[\w.-]+\.\w+",
            ],

            # Database and connection strings
            "database_info": [
                r"(?i)(?:postgresql|mysql|mongodb|redis)://[^\s]+",
                r"(?i)(?:host|server|database|db)[\"']?\s*[:=]\s*[\"']?([^\s\"']+)[\"']?",
                r"(?i)(?:connection[_-]?string|dsn)[\"']?\s*[:=]\s*[\"']?([^\s\"']+)[\"']?",
            ],

            # Personal identifiable information
            "pii_patterns": [
                r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
                r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",  # Credit card
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email (in some contexts)
            ]
        }

        # Service name replacements for obfuscation
        self.service_replacements = {
            "apify": "external data service",
            "phantombuster": "automation platform",
            "scrapfly": "data collection service",
            "brightdata": "proxy service",
            "proxycrawl": "web crawling service",
            "linkedin scraper": "professional network tool",
            "profile scraper": "contact discovery tool",
            "data scraper": "information gathering tool",
            "automation tool": "workflow automation",
            "scraping service": "data collection platform",
            "data extraction": "information processing"
        }

        logger.info(f"ChatSecurityFilter initialized with {security_level.value} security level")

    def filter_response(
        self,
        text: str,
        organization_id: int,
        user_id: int,
        context: str = "chat_response"
    ) -> FilterResult:
        """
        Filter text for security violations and apply redactions

        Args:
            text: Text to filter
            organization_id: Tenant organization ID
            user_id: User ID for audit trail
            context: Context of the filtering (chat_response, search_result, etc.)

        Returns:
            FilterResult with filtered text and violation details
        """
        if not text or not text.strip():
            return FilterResult(
                filtered_text=text,
                violations=[],
                redactions_count=0,
                security_score=100.0
            )

        filtered_text = text
        violations = []
        redactions_count = 0

        # Apply security filters based on level
        if self.security_level in [SecurityLevel.MEDIUM, SecurityLevel.HIGH, SecurityLevel.PARANOID]:
            filtered_text, pattern_violations = self._filter_sensitive_patterns(filtered_text, context)
            violations.extend(pattern_violations)
            redactions_count += len(pattern_violations)

        if self.security_level in [SecurityLevel.HIGH, SecurityLevel.PARANOID]:
            filtered_text, service_violations = self._filter_service_names(filtered_text, context)
            violations.extend(service_violations)
            redactions_count += len(service_violations)

        # Apply additional global patterns
        if self.global_custom_patterns:
            filtered_text, custom_global = self._apply_custom_patterns(
                filtered_text,
                self.global_custom_patterns,
                context,
                "global_custom"
            )
            violations.extend(custom_global)
            redactions_count += len(custom_global)

        # Apply tenant-specific patterns
        tenant_patterns = (
            self.tenant_custom_patterns.get(organization_id)
            or self.tenant_custom_patterns.get(str(organization_id))
        )
        if tenant_patterns:
            filtered_text, tenant_violations = self._apply_custom_patterns(
                filtered_text,
                tenant_patterns,
                context,
                f"tenant_{organization_id}"
            )
            violations.extend(tenant_violations)
            redactions_count += len(tenant_violations)

        if self.security_level == SecurityLevel.PARANOID:
            filtered_text, paranoid_violations = self._filter_paranoid_patterns(filtered_text, context)
            violations.extend(paranoid_violations)
            redactions_count += len(paranoid_violations)

        # Calculate security score
        security_score = self._calculate_security_score(text, violations)

        # Store violations for audit
        self.violation_history.extend(violations)

        # Log security events
        if violations:
            self._log_security_events(violations, organization_id, user_id, context)

        return FilterResult(
            filtered_text=filtered_text,
            violations=violations,
            redactions_count=redactions_count,
            security_score=security_score
        )

    def register_tenant_patterns(self, organization_id: int, patterns: List[str]):
        """Register custom redaction patterns for a specific tenant."""
        sanitized = [pattern for pattern in patterns if pattern]
        if sanitized:
            self.tenant_custom_patterns[organization_id] = sanitized
        elif organization_id in self.tenant_custom_patterns:
            del self.tenant_custom_patterns[organization_id]

    def _load_global_patterns(self) -> List[str]:
        """Load extra patterns from environment configuration."""
        extra_patterns = os.getenv("CHAT_SECURITY_EXTRA_PATTERNS", "")
        patterns = [
            pattern.strip()
            for pattern in extra_patterns.split(",")
            if pattern.strip()
        ]
        return patterns

    def _load_tenant_patterns_from_env(self) -> None:
        """Load tenant-specific pattern overrides from environment configuration."""
        raw_overrides = os.getenv("CHAT_SECURITY_TENANT_PATTERNS")
        if not raw_overrides:
            return

        try:
            overrides = json.loads(raw_overrides)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive logging
            logger.warning(f"Invalid CHAT_SECURITY_TENANT_PATTERNS payload: {exc}")
            return

        if not isinstance(overrides, dict):
            logger.warning("CHAT_SECURITY_TENANT_PATTERNS must be a JSON object of tenant_id -> [patterns]")
            return

        for tenant_key, patterns in overrides.items():
            if not isinstance(patterns, list):
                continue

            sanitized = [pattern for pattern in patterns if isinstance(pattern, str) and pattern]
            if not sanitized:
                continue

            try:
                normalized_key = int(tenant_key)
            except (TypeError, ValueError):
                normalized_key = tenant_key  # Fallback to string key if not numeric

            self.tenant_custom_patterns[normalized_key] = sanitized

    def _apply_custom_patterns(
        self,
        text: str,
        patterns: List[str],
        context: str,
        label: str
    ) -> Tuple[str, List[SecurityViolation]]:
        """Apply additional regex patterns for tenant or global redactions."""
        if not patterns:
            return text, []

        filtered_text = text
        violations: List[SecurityViolation] = []

        for pattern in patterns:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                logger.debug(f"Ignoring invalid custom pattern: {pattern}")
                continue

            def replacer(match: re.Match) -> str:
                original_text = match.group(0)
                redacted_text = "[REDACTED]"
                violations.append(SecurityViolation(
                    violation_type=ViolationType.CREDENTIAL_EXPOSURE,
                    severity="high",
                    pattern_matched=pattern,
                    original_text=original_text,
                    redacted_text=redacted_text,
                    confidence=0.85,
                    context=f"{context}:{label}",
                    timestamp=datetime.now(timezone.utc)
                ))
                return redacted_text

            filtered_text = compiled.sub(replacer, filtered_text)

        return filtered_text, violations

    def _filter_sensitive_patterns(self, text: str, context: str) -> Tuple[str, List[SecurityViolation]]:
        """Filter known sensitive patterns (API keys, tokens, etc.)"""
        filtered_text = text
        violations = []

        for category, patterns in self.sensitive_patterns.items():
            if category == "service_names":  # Handle separately
                continue

            for pattern in patterns:
                matches = list(re.finditer(pattern, filtered_text, re.IGNORECASE | re.MULTILINE))

                for match in matches:
                    original = match.group(0)

                    # Create appropriate redaction
                    if category == "openai_keys":
                        redacted = "[OPENAI_KEY_REDACTED]"
                        violation_type = ViolationType.API_KEY_EXPOSURE
                        severity = "critical"
                    elif category == "bearer_tokens":
                        redacted = "[BEARER_TOKEN_REDACTED]"
                        violation_type = ViolationType.TOKEN_LEAK
                        severity = "high"
                    elif category == "generic_tokens":
                        redacted = "[CREDENTIAL_REDACTED]"
                        violation_type = ViolationType.CREDENTIAL_EXPOSURE
                        severity = "high"
                    elif category == "internal_urls":
                        redacted = "[INTERNAL_URL_REDACTED]"
                        violation_type = ViolationType.INTERNAL_URL_EXPOSURE
                        severity = "medium"
                    elif category == "database_info":
                        redacted = "[DATABASE_INFO_REDACTED]"
                        violation_type = ViolationType.DATABASE_INFO_LEAK
                        severity = "high"
                    elif category == "pii_patterns":
                        redacted = "[PII_REDACTED]"
                        violation_type = ViolationType.PII_LEAK
                        severity = "high"
                    else:
                        redacted = "[REDACTED]"
                        violation_type = ViolationType.CREDENTIAL_EXPOSURE
                        severity = "medium"

                    # Apply redaction
                    filtered_text = filtered_text.replace(original, redacted, 1)

                    # Record violation
                    violation = SecurityViolation(
                        violation_type=violation_type,
                        severity=severity,
                        pattern_matched=pattern,
                        original_text=original,
                        redacted_text=redacted,
                        confidence=0.9,
                        context=context,
                        timestamp=datetime.now(timezone.utc)
                    )
                    violations.append(violation)

        return filtered_text, violations

    def _filter_service_names(self, text: str, context: str) -> Tuple[str, List[SecurityViolation]]:
        """Filter and obfuscate third-party service names"""
        filtered_text = text
        violations = []

        for pattern in self.sensitive_patterns["service_names"]:
            matches = list(re.finditer(pattern, filtered_text, re.IGNORECASE))

            for match in matches:
                original = match.group(0).lower().strip()

                # Find appropriate replacement
                replacement = "external service"
                for service_name, replacement_text in self.service_replacements.items():
                    if service_name in original:
                        replacement = replacement_text
                        break

                # Apply replacement
                filtered_text = re.sub(pattern, replacement, filtered_text, flags=re.IGNORECASE)

                # Record violation
                violation = SecurityViolation(
                    violation_type=ViolationType.SERVICE_NAME_EXPOSURE,
                    severity="medium",
                    pattern_matched=pattern,
                    original_text=original,
                    redacted_text=replacement,
                    confidence=0.8,
                    context=context,
                    timestamp=datetime.now(timezone.utc)
                )
                violations.append(violation)

        return filtered_text, violations

    def _filter_paranoid_patterns(self, text: str, context: str) -> Tuple[str, List[SecurityViolation]]:
        """Apply paranoid-level filtering for maximum security"""
        filtered_text = text
        violations = []

        # Additional paranoid patterns
        paranoid_patterns = [
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",  # IP addresses
            r"\b[a-f0-9]{32,}\b",  # Long hex strings (potential hashes)
            r"\b[A-Z0-9]{20,}\b",  # Long uppercase alphanumeric (potential IDs)
            r"(?i)\b(?:admin|root|administrator|system|service)@[\w.-]+",  # Admin emails
        ]

        for pattern in paranoid_patterns:
            matches = list(re.finditer(pattern, filtered_text))

            for match in matches:
                original = match.group(0)
                redacted = "[SENSITIVE_DATA_REDACTED]"

                filtered_text = filtered_text.replace(original, redacted, 1)

                violation = SecurityViolation(
                    violation_type=ViolationType.CREDENTIAL_EXPOSURE,
                    severity="low",
                    pattern_matched=pattern,
                    original_text=original,
                    redacted_text=redacted,
                    confidence=0.6,
                    context=context,
                    timestamp=datetime.now(timezone.utc)
                )
                violations.append(violation)

        return filtered_text, violations

    def _calculate_security_score(self, original_text: str, violations: List[SecurityViolation]) -> float:
        """Calculate security score based on violations found"""
        if not original_text.strip():
            return 100.0

        if not violations:
            return 100.0

        # Calculate penalty based on violation severity
        penalty = 0
        for violation in violations:
            if violation.severity == "critical":
                penalty += 30
            elif violation.severity == "high":
                penalty += 20
            elif violation.severity == "medium":
                penalty += 10
            elif violation.severity == "low":
                penalty += 5

        # Apply confidence weighting
        weighted_penalty = sum(v.confidence *
                             (30 if v.severity == "critical" else
                              20 if v.severity == "high" else
                              10 if v.severity == "medium" else 5)
                             for v in violations)

        score = max(0.0, 100.0 - weighted_penalty)
        return score

    def _log_security_events(
        self,
        violations: List[SecurityViolation],
        organization_id: int,
        user_id: int,
        context: str
    ):
        """Log security violations for audit trail"""
        try:
            from .agent_logger import agent_logger, AgentEventType, LogLevel

            for violation in violations:
                # Determine log level based on severity
                if violation.severity == "critical":
                    log_level = LogLevel.ERROR
                elif violation.severity == "high":
                    log_level = LogLevel.WARNING
                else:
                    log_level = LogLevel.INFO

                # Log the security event
                agent_logger.log_event(
                    event_type=AgentEventType.SECURITY_VIOLATION,
                    level=log_level,
                    agent_id="chat_security_filter",
                    session_id=f"security_{organization_id}_{user_id}",
                    details={
                        "violation_type": violation.violation_type.value,
                        "severity": violation.severity,
                        "context": context,
                        "organization_id": organization_id,
                        "user_id": user_id,
                        "pattern_matched": violation.pattern_matched,
                        "confidence": violation.confidence,
                        "timestamp": violation.timestamp.isoformat()
                    }
                )

        except Exception as e:
            logger.error(f"Failed to log security event: {e}")

    def get_violation_summary(self, organization_id: int = None) -> Dict[str, Any]:
        """Get summary of security violations for monitoring"""
        relevant_violations = self.violation_history
        if organization_id:
            # Filter would require additional context storage
            pass

        summary = {
            "total_violations": len(relevant_violations),
            "by_type": {},
            "by_severity": {},
            "recent_violations": []
        }

        # Group by type and severity
        for violation in relevant_violations:
            vtype = violation.violation_type.value
            severity = violation.severity

            summary["by_type"][vtype] = summary["by_type"].get(vtype, 0) + 1
            summary["by_severity"][severity] = summary["by_severity"].get(severity, 0) + 1

        # Add recent violations (last 10)
        recent = sorted(relevant_violations, key=lambda v: v.timestamp, reverse=True)[:10]
        summary["recent_violations"] = [
            {
                "type": v.violation_type.value,
                "severity": v.severity,
                "timestamp": v.timestamp.isoformat(),
                "context": v.context
            }
            for v in recent
        ]

        return summary

    def configure_organization_rules(self, organization_id: int, rules: Dict[str, Any]):
        """Configure organization-specific security rules"""
        # Implementation for per-tenant security configuration
        # This would be stored in database and cached
        logger.info(f"Configuring security rules for organization {organization_id}: {rules}")

# Global security filter instance
chat_security_filter = ChatSecurityFilter()