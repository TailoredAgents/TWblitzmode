"""
API Response Sanitization Service for VouchLink AI
Implements comprehensive sanitization of API responses to prevent data leakage.
"""

import json
import logging
import re
import hashlib
from typing import Dict, List, Optional, Any, Set, Union
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone

from core.roles import normalize_role

logger = logging.getLogger(__name__)


class SanitizationLevel(Enum):
    """Sanitization levels."""
    NONE = "none"
    BASIC = "basic"
    MODERATE = "moderate"
    STRICT = "strict"
    PARANOID = "paranoid"


class DataClassification(Enum):
    """Data classification levels."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass
class SanitizationRule:
    """Configuration for field sanitization."""
    field_name: str
    action: str  # "remove", "mask", "hash", "redact", "truncate"
    classification: DataClassification
    mask_pattern: Optional[str] = None
    truncate_length: Optional[int] = None
    preserve_format: bool = False


class ResponseSanitizationService:
    """Service for sanitizing API responses to prevent sensitive data exposure."""

    def __init__(self):
        """Initialize the response sanitization service."""
        self.sensitive_fields = self._initialize_sensitive_fields()
        self.sanitization_rules = self._initialize_sanitization_rules()
        self.pii_patterns = self._initialize_pii_patterns()

    def _initialize_sensitive_fields(self) -> Set[str]:
        """Initialize list of sensitive field names."""
        return {
            # Authentication & Security
            "password", "password_hash", "secret", "secret_key", "private_key",
            "api_key", "token", "refresh_token", "access_token", "jwt", "session_key",
            "salt", "hash", "signature", "csrf_token", "api_secret",

            # Personal Information
            "ssn", "social_security_number", "tax_id", "passport_number",
            "driver_license", "credit_card", "bank_account", "routing_number",
            "raw_key", "encryption_key", "private_data",

            # LinkedIn Specific
            "li_at", "jsessionid", "cookie", "sessionCookie", "raw_cookie",
            "linkedin_cookie", "browser_cookie", "authentication_cookie",

            # Database Internal
            "id", "internal_id", "db_id", "row_id", "uuid", "guid",
            "created_by", "updated_by", "deleted_by", "internal_notes",

            # System Internal
            "config", "configuration", "settings", "environment",
            "debug_info", "stack_trace", "error_details", "system_path",
            "file_path", "absolute_path", "server_info"
        }

    def _initialize_sanitization_rules(self) -> Dict[str, SanitizationRule]:
        """Initialize sanitization rules for different field types."""
        return {
            # Authentication fields - remove completely
            "password": SanitizationRule("password", "remove", DataClassification.RESTRICTED),
            "password_hash": SanitizationRule("password_hash", "remove", DataClassification.RESTRICTED),
            "secret": SanitizationRule("secret", "remove", DataClassification.RESTRICTED),
            "api_key": SanitizationRule("api_key", "mask", DataClassification.RESTRICTED, "*" * 12),
            "token": SanitizationRule("token", "mask", DataClassification.RESTRICTED, "*" * 16),

            # PII fields - mask or redact
            "email": SanitizationRule("email", "mask", DataClassification.CONFIDENTIAL,
                                    mask_pattern=r'^(.{1,2}).*(@.*)$', preserve_format=True),
            "phone": SanitizationRule("phone", "mask", DataClassification.CONFIDENTIAL,
                                    mask_pattern=r'^(.{3}).*(.{2})$', preserve_format=True),
            "ssn": SanitizationRule("ssn", "mask", DataClassification.RESTRICTED, "***-**-****"),

            # LinkedIn cookies - remove completely
            "li_at": SanitizationRule("li_at", "remove", DataClassification.RESTRICTED),
            "jsessionid": SanitizationRule("jsessionid", "remove", DataClassification.RESTRICTED),
            "raw_cookie": SanitizationRule("raw_cookie", "remove", DataClassification.RESTRICTED),

            # IDs - hash for anonymization
            "user_id": SanitizationRule("user_id", "hash", DataClassification.INTERNAL),
            "internal_id": SanitizationRule("internal_id", "remove", DataClassification.INTERNAL),

            # Registration keys - mask but keep format
            "key": SanitizationRule("key", "mask", DataClassification.CONFIDENTIAL,
                                  mask_pattern=r'^(.{4}).*(.{4})$', preserve_format=True),
            "raw_key": SanitizationRule("raw_key", "remove", DataClassification.RESTRICTED),

            # Error information - truncate
            "error": SanitizationRule("error", "truncate", DataClassification.INTERNAL, truncate_length=100),
            "stack_trace": SanitizationRule("stack_trace", "remove", DataClassification.INTERNAL),
        }

    def _initialize_pii_patterns(self) -> List[re.Pattern]:
        """Initialize patterns for detecting PII in text."""
        return [
            re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),  # Email
            re.compile(r'\b\d{3}-?\d{2}-?\d{4}\b'),  # SSN
            re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),  # Credit card
            re.compile(r'\b\d{3}-?\d{3}-?\d{4}\b'),  # Phone
            re.compile(r'\b[A-HJ-NP-TV-Z]{3,}-[A-HJ-NP-TV-Z0-9]{8,}\b'),  # Registration keys
        ]

    def sanitize_response(
        self,
        data: Any,
        sanitization_level: SanitizationLevel = SanitizationLevel.MODERATE,
        user_role: Optional[str] = None,
        preserve_structure: bool = True
    ) -> Any:
        """Sanitize API response data based on sanitization level."""
        if data is None:
            return None

        # Admin users get less sanitization (roles normalized for consistency)
        normalized_role = normalize_role(user_role)
        if normalized_role == "admin" and sanitization_level != SanitizationLevel.PARANOID:
            sanitization_level = SanitizationLevel.BASIC

        return self._sanitize_recursive(data, sanitization_level, preserve_structure)

    def _sanitize_recursive(
        self,
        data: Any,
        level: SanitizationLevel,
        preserve_structure: bool,
        path: str = ""
    ) -> Any:
        """Recursively sanitize data structure."""
        if isinstance(data, dict):
            return self._sanitize_dict(data, level, preserve_structure, path)
        elif isinstance(data, list):
            return self._sanitize_list(data, level, preserve_structure, path)
        elif isinstance(data, str):
            return self._sanitize_string(data, level, path)
        else:
            return data

    def _sanitize_dict(
        self,
        data: Dict[str, Any],
        level: SanitizationLevel,
        preserve_structure: bool,
        path: str
    ) -> Dict[str, Any]:
        """Sanitize dictionary data."""
        sanitized = {}

        for key, value in data.items():
            current_path = f"{path}.{key}" if path else key

            # Check if field should be sanitized
            sanitization_action = self._get_sanitization_action(key, level)

            if sanitization_action == "remove":
                # Skip this field entirely
                if preserve_structure:
                    sanitized[key] = "[REDACTED]"
                continue

            elif sanitization_action == "mask":
                sanitized[key] = self._mask_value(key, value)

            elif sanitization_action == "hash":
                sanitized[key] = self._hash_value(value)

            elif sanitization_action == "redact":
                sanitized[key] = "[REDACTED]"

            elif sanitization_action == "truncate":
                sanitized[key] = self._truncate_value(key, value)

            else:
                # Recursively sanitize nested structures
                sanitized[key] = self._sanitize_recursive(value, level, preserve_structure, current_path)

        return sanitized

    def _sanitize_list(
        self,
        data: List[Any],
        level: SanitizationLevel,
        preserve_structure: bool,
        path: str
    ) -> List[Any]:
        """Sanitize list data."""
        return [
            self._sanitize_recursive(item, level, preserve_structure, f"{path}[{i}]")
            for i, item in enumerate(data)
        ]

    def _sanitize_string(self, data: str, level: SanitizationLevel, path: str) -> str:
        """Sanitize string data for PII patterns."""
        if level in [SanitizationLevel.NONE, SanitizationLevel.BASIC]:
            return data

        # Check for PII patterns in string content
        sanitized = data
        for pattern in self.pii_patterns:
            if pattern.search(sanitized):
                if level == SanitizationLevel.PARANOID:
                    sanitized = pattern.sub("[PII_REDACTED]", sanitized)
                else:
                    # Partial masking
                    sanitized = pattern.sub(lambda m: self._mask_match(m.group()), sanitized)

        return sanitized

    def _get_sanitization_action(self, field_name: str, level: SanitizationLevel) -> str:
        """Determine sanitization action for a field."""
        field_lower = field_name.lower()

        # Check exact match in rules
        if field_lower in self.sanitization_rules:
            rule = self.sanitization_rules[field_lower]

            # Adjust action based on sanitization level
            if level == SanitizationLevel.NONE:
                return "none"
            elif level == SanitizationLevel.BASIC:
                if rule.classification == DataClassification.RESTRICTED:
                    return rule.action
                return "none"
            elif level == SanitizationLevel.MODERATE:
                if rule.classification in [DataClassification.RESTRICTED, DataClassification.CONFIDENTIAL]:
                    return rule.action
                return "none"
            elif level in [SanitizationLevel.STRICT, SanitizationLevel.PARANOID]:
                return rule.action

        # Check if field name contains sensitive keywords
        for sensitive_field in self.sensitive_fields:
            if sensitive_field in field_lower:
                if level in [SanitizationLevel.STRICT, SanitizationLevel.PARANOID]:
                    return "remove"
                elif level == SanitizationLevel.MODERATE:
                    return "mask"

        return "none"

    def _mask_value(self, field_name: str, value: Any) -> str:
        """Mask a value based on field type."""
        if value is None:
            return None

        value_str = str(value)
        field_lower = field_name.lower()

        if field_lower in self.sanitization_rules:
            rule = self.sanitization_rules[field_lower]
            if rule.mask_pattern:
                if rule.preserve_format:
                    return self._apply_mask_pattern(value_str, rule.mask_pattern)
                else:
                    return rule.mask_pattern

        # Default masking
        if len(value_str) <= 4:
            return "*" * len(value_str)
        elif len(value_str) <= 8:
            return value_str[:1] + "*" * (len(value_str) - 2) + value_str[-1:]
        else:
            return value_str[:2] + "*" * (len(value_str) - 4) + value_str[-2:]

    def _apply_mask_pattern(self, value: str, pattern: str) -> str:
        """Apply regex-based mask pattern."""
        try:
            # For email masking: keep first 1-2 chars and domain
            if "@" in value and pattern == r'^(.{1,2}).*(@.*)$':
                match = re.match(r'^(.{1,2}).*(@.*)$', value)
                if match:
                    return match.group(1) + "***" + match.group(2)

            # For phone masking: keep first 3 and last 2
            elif pattern == r'^(.{3}).*(.{2})$':
                match = re.match(r'^(.{3}).*(.{2})$', value)
                if match:
                    return match.group(1) + "***" + match.group(2)

            # For key masking: keep first 4 and last 4
            elif pattern == r'^(.{4}).*(.{4})$':
                match = re.match(r'^(.{4}).*(.{4})$', value)
                if match:
                    return match.group(1) + "***" + match.group(2)

        except re.error:
            pass

        # Fallback to simple masking
        return self._mask_value("default", value)

    def _hash_value(self, value: Any) -> str:
        """Hash a value for anonymization."""
        if value is None:
            return None

        value_str = str(value)
        return hashlib.sha256(value_str.encode()).hexdigest()[:12]

    def _truncate_value(self, field_name: str, value: Any) -> str:
        """Truncate a value to specified length."""
        if value is None:
            return None

        value_str = str(value)
        field_lower = field_name.lower()

        if field_lower in self.sanitization_rules:
            rule = self.sanitization_rules[field_lower]
            if rule.truncate_length and len(value_str) > rule.truncate_length:
                return value_str[:rule.truncate_length] + "..."

        return value_str

    def _mask_match(self, match: str) -> str:
        """Mask a regex match with partial visibility."""
        if len(match) <= 4:
            return "*" * len(match)
        else:
            return match[:2] + "*" * (len(match) - 4) + match[-2:]

    def sanitize_error_response(
        self,
        error_data: Dict[str, Any],
        include_details: bool = False
    ) -> Dict[str, Any]:
        """Sanitize error responses to prevent information disclosure."""
        sanitized = {
            "error": "An error occurred",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Only include safe error information
        if "message" in error_data:
            # Sanitize error message
            message = str(error_data["message"])

            # Remove file paths
            message = re.sub(r'[a-zA-Z]:\\[^\\]+(?:\\[^\\]+)*', '[PATH_REDACTED]', message)
            message = re.sub(r'/[^/\s]+(?:/[^/\s]+)*', '[PATH_REDACTED]', message)

            # Remove stack traces
            if "Traceback" in message or "File \"" in message:
                message = "Internal server error"

            sanitized["message"] = message

        if include_details and "error_code" in error_data:
            sanitized["error_code"] = error_data["error_code"]

        return sanitized

    def add_security_headers(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add security-related metadata to response."""
        if isinstance(response_data, dict):
            response_data["_security"] = {
                "data_sanitized": True,
                "sanitization_timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "1.0"
            }

        return response_data

    def get_sanitization_stats(self) -> Dict[str, Any]:
        """Get sanitization service statistics."""
        return {
            "sensitive_fields_count": len(self.sensitive_fields),
            "sanitization_rules_count": len(self.sanitization_rules),
            "pii_patterns_count": len(self.pii_patterns),
            "supported_levels": [level.value for level in SanitizationLevel],
            "data_classifications": [cls.value for cls in DataClassification]
        }

    def validate_response_safety(self, data: Any) -> tuple[bool, list[str]]:
        """Validate that response data doesn't contain obvious sensitive information."""
        issues = []

        def check_recursive(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    current_path = f"{path}.{key}" if path else key

                    # Check field names
                    if key.lower() in self.sensitive_fields:
                        issues.append(f"Sensitive field detected: {current_path}")

                    check_recursive(value, current_path)

            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    check_recursive(item, f"{path}[{i}]")

            elif isinstance(obj, str):
                # Check for PII patterns
                for pattern in self.pii_patterns:
                    if pattern.search(obj):
                        issues.append(f"PII pattern detected in: {path}")
                        break

        check_recursive(data)
        return len(issues) == 0, issues


# Global instance
response_sanitization_service = ResponseSanitizationService()


def sanitize_response(
    data: Any,
    level: SanitizationLevel = SanitizationLevel.MODERATE,
    user_role: Optional[str] = None
) -> Any:
    """Convenience function to sanitize response data."""
    return response_sanitization_service.sanitize_response(data, level, user_role)


def sanitize_error(error_data: Dict[str, Any], include_details: bool = False) -> Dict[str, Any]:
    """Convenience function to sanitize error responses."""
    return response_sanitization_service.sanitize_error_response(error_data, include_details)
