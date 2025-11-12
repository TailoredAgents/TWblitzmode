"""
Input Validation Service for VouchLink AI
Implements comprehensive input validation and sanitization.
"""

import re
import html
import urllib.parse
import logging
import bleach
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass
from enum import Enum
import json

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """Validation severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class InputType(Enum):
    """Types of input validation."""
    EMAIL = "email"
    URL = "url"
    HTML = "html"
    SQL = "sql"
    JSON = "json"
    FILENAME = "filename"
    IP_ADDRESS = "ip_address"
    PHONE = "phone"
    LINKEDIN_URL = "linkedin_url"
    PLAIN_TEXT = "plain_text"
    PASSWORD = "password"
    USERNAME = "username"
    COMPANY_NAME = "company_name"
    NAME = "name"


@dataclass
class ValidationResult:
    """Result of input validation."""
    is_valid: bool
    sanitized_value: Any
    original_value: Any
    issues: List[str]
    severity: ValidationSeverity
    input_type: InputType


@dataclass
class ValidationRule:
    """Input validation rule configuration."""
    input_type: InputType
    max_length: Optional[int] = None
    min_length: Optional[int] = None
    pattern: Optional[str] = None
    allowed_chars: Optional[str] = None
    forbidden_chars: Optional[str] = None
    sanitize_html: bool = False
    strip_whitespace: bool = True
    normalize_unicode: bool = True
    case_insensitive: bool = False


class InputValidationService:
    """Service for comprehensive input validation and sanitization."""

    def __init__(self):
        """Initialize the input validation service."""
        self.validation_rules = self._initialize_validation_rules()
        self.xss_patterns = self._initialize_xss_patterns()
        self.sql_injection_patterns = self._initialize_sql_injection_patterns()

        # Configure bleach for HTML sanitization
        self.allowed_tags = [
            'p', 'br', 'strong', 'em', 'u', 'ol', 'ul', 'li', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
        ]
        self.allowed_attributes = {
            'a': ['href', 'title'],
            '*': ['class']
        }

    def _initialize_validation_rules(self) -> Dict[InputType, ValidationRule]:
        """Initialize default validation rules."""
        return {
            InputType.EMAIL: ValidationRule(
                input_type=InputType.EMAIL,
                max_length=254,
                min_length=5,
                pattern=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
                strip_whitespace=True,
                case_insensitive=True
            ),
            InputType.URL: ValidationRule(
                input_type=InputType.URL,
                max_length=2048,
                min_length=7,
                pattern=r'^https?://[^\s/$.?#].[^\s]*$',
                strip_whitespace=True
            ),
            InputType.LINKEDIN_URL: ValidationRule(
                input_type=InputType.LINKEDIN_URL,
                max_length=500,
                min_length=20,
                pattern=r'^https?://(www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+/?$',
                strip_whitespace=True
            ),
            InputType.FILENAME: ValidationRule(
                input_type=InputType.FILENAME,
                max_length=255,
                min_length=1,
                forbidden_chars=r'[<>:"/\\|?*\x00-\x1f]',
                strip_whitespace=True
            ),
            InputType.IP_ADDRESS: ValidationRule(
                input_type=InputType.IP_ADDRESS,
                max_length=45,  # IPv6
                min_length=7,   # IPv4
                strip_whitespace=True
            ),
            InputType.PHONE: ValidationRule(
                input_type=InputType.PHONE,
                max_length=20,
                min_length=10,
                pattern=r'^\+?[1-9]\d{1,14}$',
                strip_whitespace=True
            ),
            InputType.USERNAME: ValidationRule(
                input_type=InputType.USERNAME,
                max_length=50,
                min_length=3,
                pattern=r'^[a-zA-Z0-9_-]+$',
                strip_whitespace=True
            ),
            InputType.PASSWORD: ValidationRule(
                input_type=InputType.PASSWORD,
                max_length=128,
                min_length=8,
                strip_whitespace=False
            ),
            InputType.NAME: ValidationRule(
                input_type=InputType.NAME,
                max_length=100,
                min_length=1,
                pattern=r'^[a-zA-Z\s\'-\.]+$',
                strip_whitespace=True
            ),
            InputType.COMPANY_NAME: ValidationRule(
                input_type=InputType.COMPANY_NAME,
                max_length=200,
                min_length=1,
                forbidden_chars=r'[<>]',
                strip_whitespace=True
            ),
            InputType.PLAIN_TEXT: ValidationRule(
                input_type=InputType.PLAIN_TEXT,
                max_length=10000,
                min_length=0,
                strip_whitespace=True,
                sanitize_html=True
            ),
            InputType.HTML: ValidationRule(
                input_type=InputType.HTML,
                max_length=50000,
                min_length=0,
                sanitize_html=True,
                strip_whitespace=False
            ),
            InputType.JSON: ValidationRule(
                input_type=InputType.JSON,
                max_length=100000,
                min_length=2,
                strip_whitespace=True
            )
        }

    def _initialize_xss_patterns(self) -> List[re.Pattern]:
        """Initialize XSS detection patterns."""
        patterns = [
            re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL),
            re.compile(r'javascript:', re.IGNORECASE),
            re.compile(r'vbscript:', re.IGNORECASE),
            re.compile(r'onload\s*=', re.IGNORECASE),
            re.compile(r'onerror\s*=', re.IGNORECASE),
            re.compile(r'onclick\s*=', re.IGNORECASE),
            re.compile(r'onmouseover\s*=', re.IGNORECASE),
            re.compile(r'<iframe[^>]*>', re.IGNORECASE),
            re.compile(r'<object[^>]*>', re.IGNORECASE),
            re.compile(r'<embed[^>]*>', re.IGNORECASE),
            re.compile(r'eval\s*\(', re.IGNORECASE),
            re.compile(r'expression\s*\(', re.IGNORECASE),
            re.compile(r'url\s*\(\s*["\']?\s*javascript:', re.IGNORECASE),
        ]
        return patterns

    def _initialize_sql_injection_patterns(self) -> List[re.Pattern]:
        """Initialize SQL injection detection patterns."""
        patterns = [
            re.compile(r'\bunion\s+select\b', re.IGNORECASE),
            re.compile(r'\bselect\s+.*\bfrom\b', re.IGNORECASE),
            re.compile(r'\binsert\s+into\b', re.IGNORECASE),
            re.compile(r'\bdelete\s+from\b', re.IGNORECASE),
            re.compile(r'\bdrop\s+table\b', re.IGNORECASE),
            re.compile(r'\bupdate\s+.*\bset\b', re.IGNORECASE),
            re.compile(r'--\s*$', re.MULTILINE),
            re.compile(r'/\*.*?\*/', re.DOTALL),
            re.compile(r"'\s*or\s+'1'\s*=\s*'1", re.IGNORECASE),
            re.compile(r'"\s*or\s+"1"\s*=\s*"1', re.IGNORECASE),
            re.compile(r';\s*drop\s+', re.IGNORECASE),
            re.compile(r';\s*shutdown\s*', re.IGNORECASE),
        ]
        return patterns

    def validate_input(
        self,
        value: Any,
        input_type: InputType,
        custom_rules: Optional[ValidationRule] = None
    ) -> ValidationResult:
        """Validate and sanitize input based on type."""
        if value is None:
            return ValidationResult(
                is_valid=True,
                sanitized_value=None,
                original_value=None,
                issues=[],
                severity=ValidationSeverity.INFO,
                input_type=input_type
            )

        original_value = value
        issues = []
        severity = ValidationSeverity.INFO

        # Get validation rule
        rule = custom_rules or self.validation_rules.get(input_type, self.validation_rules[InputType.PLAIN_TEXT])

        # Convert to string if needed
        if not isinstance(value, str):
            if input_type == InputType.JSON:
                try:
                    value = json.dumps(value)
                except (TypeError, ValueError):
                    return ValidationResult(
                        is_valid=False,
                        sanitized_value=original_value,
                        original_value=original_value,
                        issues=["Invalid JSON data"],
                        severity=ValidationSeverity.ERROR,
                        input_type=input_type
                    )
            else:
                value = str(value)

        # Basic preprocessing
        if rule.strip_whitespace:
            value = value.strip()

        if rule.normalize_unicode:
            import unicodedata
            value = unicodedata.normalize('NFKC', value)

        if rule.case_insensitive and input_type in [InputType.EMAIL]:
            value = value.lower()

        # Length validation
        if rule.max_length and len(value) > rule.max_length:
            issues.append(f"Input exceeds maximum length of {rule.max_length} characters")
            severity = ValidationSeverity.ERROR

        if rule.min_length and len(value) < rule.min_length:
            issues.append(f"Input is shorter than minimum length of {rule.min_length} characters")
            severity = ValidationSeverity.ERROR

        # Pattern validation
        if rule.pattern and not re.match(rule.pattern, value):
            issues.append(f"Input does not match required pattern")
            severity = ValidationSeverity.ERROR

        # Character validation
        if rule.forbidden_chars:
            if re.search(rule.forbidden_chars, value):
                issues.append("Input contains forbidden characters")
                severity = ValidationSeverity.ERROR
                # Remove forbidden characters
                value = re.sub(rule.forbidden_chars, '', value)

        if rule.allowed_chars:
            if not re.match(f'^[{rule.allowed_chars}]*$', value):
                issues.append("Input contains disallowed characters")
                severity = ValidationSeverity.WARNING

        # Security checks
        security_issues = self._perform_security_checks(value, input_type)
        if security_issues:
            issues.extend(security_issues)
            severity = ValidationSeverity.CRITICAL

        # Type-specific validation
        type_validation_result = self._perform_type_specific_validation(value, input_type)
        if not type_validation_result[0]:
            issues.extend(type_validation_result[1])
            severity = max(severity, ValidationSeverity.ERROR, key=lambda x: x.value)

        # Sanitization
        sanitized_value = self._sanitize_value(value, rule, input_type)

        # Final validation
        is_valid = severity not in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]

        return ValidationResult(
            is_valid=is_valid,
            sanitized_value=sanitized_value,
            original_value=original_value,
            issues=issues,
            severity=severity,
            input_type=input_type
        )

    def _perform_security_checks(self, value: str, input_type: InputType) -> List[str]:
        """Perform security checks for XSS and SQL injection."""
        issues = []

        # XSS detection
        if input_type in [InputType.HTML, InputType.PLAIN_TEXT, InputType.URL]:
            for pattern in self.xss_patterns:
                if pattern.search(value):
                    issues.append("Potential XSS attack detected")
                    logger.warning(
                        f"XSS attempt detected",
                        extra={
                            "input_type": input_type.value,
                            "pattern": pattern.pattern,
                            "value_preview": value[:100]
                        }
                    )
                    break

        # SQL injection detection
        if input_type not in [InputType.HTML, InputType.URL]:
            for pattern in self.sql_injection_patterns:
                if pattern.search(value):
                    issues.append("Potential SQL injection attack detected")
                    logger.warning(
                        f"SQL injection attempt detected",
                        extra={
                            "input_type": input_type.value,
                            "pattern": pattern.pattern,
                            "value_preview": value[:100]
                        }
                    )
                    break

        # Path traversal detection
        if '../' in value or '..\\' in value:
            issues.append("Potential path traversal attack detected")

        # Command injection detection
        command_patterns = [r';\s*rm\s+', r';\s*cat\s+', r'&&\s*', r'\|\|\s*', r'`.*`', r'\$\(.*\)']
        for pattern_str in command_patterns:
            if re.search(pattern_str, value, re.IGNORECASE):
                issues.append("Potential command injection detected")
                break

        return issues

    def _perform_type_specific_validation(self, value: str, input_type: InputType) -> Tuple[bool, List[str]]:
        """Perform validation specific to input type."""
        issues = []

        if input_type == InputType.EMAIL:
            if '@' not in value:
                issues.append("Email must contain @ symbol")
            elif value.count('@') > 1:
                issues.append("Email contains multiple @ symbols")

        elif input_type == InputType.URL:
            if not (value.startswith('http://') or value.startswith('https://')):
                issues.append("URL must start with http:// or https://")

        elif input_type == InputType.IP_ADDRESS:
            if not self._is_valid_ip(value):
                issues.append("Invalid IP address format")

        elif input_type == InputType.JSON:
            try:
                json.loads(value)
            except json.JSONDecodeError as e:
                issues.append(f"Invalid JSON: {str(e)}")

        elif input_type == InputType.LINKEDIN_URL:
            if 'linkedin.com/in/' not in value.lower():
                issues.append("Must be a valid LinkedIn profile URL")

        return len(issues) == 0, issues

    def _is_valid_ip(self, ip: str) -> bool:
        """Validate IP address (IPv4 or IPv6)."""
        import ipaddress
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

    def _sanitize_value(self, value: str, rule: ValidationRule, input_type: InputType) -> str:
        """Sanitize the input value."""
        if rule.sanitize_html:
            # Use bleach to sanitize HTML
            value = bleach.clean(
                value,
                tags=self.allowed_tags,
                attributes=self.allowed_attributes,
                strip=True
            )

        if input_type == InputType.HTML:
            # Additional HTML sanitization
            value = html.escape(value, quote=False)

        elif input_type == InputType.URL:
            # URL encoding for safety
            value = urllib.parse.quote(value, safe=':/?#[]@!$&\'()*+,;=')

        elif input_type == InputType.FILENAME:
            # Remove or replace dangerous filename characters
            value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value)
            value = value.strip('. ')  # Remove leading/trailing dots and spaces

        elif input_type == InputType.PLAIN_TEXT:
            # Basic XSS prevention
            value = html.escape(value)

        return value

    def validate_form_data(self, form_data: Dict[str, Any], field_types: Dict[str, InputType]) -> Dict[str, ValidationResult]:
        """Validate multiple form fields."""
        results = {}

        for field_name, field_value in form_data.items():
            input_type = field_types.get(field_name, InputType.PLAIN_TEXT)
            results[field_name] = self.validate_input(field_value, input_type)

        return results

    def get_sanitized_form_data(self, form_data: Dict[str, Any], field_types: Dict[str, InputType]) -> Dict[str, Any]:
        """Get sanitized form data with only valid fields."""
        results = self.validate_form_data(form_data, field_types)
        sanitized_data = {}

        for field_name, validation_result in results.items():
            if validation_result.is_valid:
                sanitized_data[field_name] = validation_result.sanitized_value
            else:
                logger.warning(
                    f"Field validation failed: {field_name}",
                    extra={
                        "field": field_name,
                        "issues": validation_result.issues,
                        "severity": validation_result.severity.value
                    }
                )

        return sanitized_data

    def validate_json_api_input(self, json_data: Dict[str, Any], schema: Dict[str, InputType]) -> Tuple[bool, Dict[str, ValidationResult]]:
        """Validate JSON API input against schema."""
        results = self.validate_form_data(json_data, schema)

        # Check if all validations passed
        all_valid = all(result.is_valid for result in results.values())

        return all_valid, results

    def create_validation_middleware_response(self, validation_results: Dict[str, ValidationResult]) -> Optional[Dict[str, Any]]:
        """Create error response for validation middleware."""
        errors = {}
        has_errors = False

        for field_name, result in validation_results.items():
            if not result.is_valid:
                errors[field_name] = {
                    "issues": result.issues,
                    "severity": result.severity.value
                }
                has_errors = True

        if has_errors:
            return {
                "error": "Input validation failed",
                "validation_errors": errors,
                "message": "Please correct the highlighted fields and try again."
            }

        return None

    def get_validation_stats(self) -> Dict[str, Any]:
        """Get validation service statistics."""
        return {
            "supported_types": [input_type.value for input_type in InputType],
            "xss_patterns_count": len(self.xss_patterns),
            "sql_injection_patterns_count": len(self.sql_injection_patterns),
            "validation_rules_count": len(self.validation_rules)
        }


# Global instance
input_validation_service = InputValidationService()


def validate_input(value: Any, input_type: InputType) -> ValidationResult:
    """Convenience function for input validation."""
    return input_validation_service.validate_input(value, input_type)


def sanitize_form_data(form_data: Dict[str, Any], field_types: Dict[str, InputType]) -> Dict[str, Any]:
    """Convenience function for form data sanitization."""
    return input_validation_service.get_sanitized_form_data(form_data, field_types)