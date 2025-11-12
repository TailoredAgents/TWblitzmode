"""
PII Redaction Service for VouchLink AI
Implements comprehensive data protection policies for chat transcripts and user data.
"""

import re
import hashlib
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PIIType(Enum):
    """Types of PII that can be detected and redacted."""
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    URL = "url"
    API_KEY = "api_key"
    JWT_TOKEN = "jwt_token"
    PASSWORD = "password"
    LINKEDIN_URL = "linkedin_url"
    NAME = "name"
    ADDRESS = "address"


@dataclass
class PIIDetection:
    """Represents a detected PII instance."""
    pii_type: PIIType
    original_text: str
    start_pos: int
    end_pos: int
    redacted_text: str
    confidence: float


class PIIRedactionService:
    """Service for detecting and redacting PII from text content."""

    def __init__(self):
        """Initialize the PII redaction service with detection patterns."""
        self.patterns = self._initialize_patterns()
        self.redaction_policies = self._initialize_redaction_policies()

    def _initialize_patterns(self) -> Dict[PIIType, re.Pattern]:
        """Initialize regex patterns for PII detection."""
        return {
            PIIType.EMAIL: re.compile(
                r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                re.IGNORECASE
            ),
            PIIType.PHONE: re.compile(
                r'(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b'
            ),
            PIIType.SSN: re.compile(
                r'\b(?:\d{3}-?\d{2}-?\d{4}|\d{9})\b'
            ),
            PIIType.CREDIT_CARD: re.compile(
                r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3[0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b'
            ),
            PIIType.IP_ADDRESS: re.compile(
                r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
            ),
            PIIType.URL: re.compile(
                r'https?://(?:[-\w.])+(?:[:\d]+)?(?:/(?:[\w/_.])*(?:\?(?:[\w&=%.])*)?(?:#(?:[\w.])*)?)?',
                re.IGNORECASE
            ),
            PIIType.API_KEY: re.compile(
                r'\b(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*["\']?([A-Za-z0-9_-]{20,})["\']?',
                re.IGNORECASE
            ),
            PIIType.JWT_TOKEN: re.compile(
                r'\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*\b'
            ),
            PIIType.PASSWORD: re.compile(
                r'\b(?:password|pwd|pass)\s*[:=]\s*["\']?([^\s"\']{6,})["\']?',
                re.IGNORECASE
            ),
            PIIType.LINKEDIN_URL: re.compile(
                r'https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?',
                re.IGNORECASE
            ),
        }

    def _initialize_redaction_policies(self) -> Dict[PIIType, str]:
        """Initialize redaction replacement patterns for each PII type."""
        return {
            PIIType.EMAIL: "[EMAIL_REDACTED]",
            PIIType.PHONE: "[PHONE_REDACTED]",
            PIIType.SSN: "[SSN_REDACTED]",
            PIIType.CREDIT_CARD: "[CARD_REDACTED]",
            PIIType.IP_ADDRESS: "[IP_REDACTED]",
            PIIType.URL: "[URL_REDACTED]",
            PIIType.API_KEY: "[API_KEY_REDACTED]",
            PIIType.JWT_TOKEN: "[TOKEN_REDACTED]",
            PIIType.PASSWORD: "[PASSWORD_REDACTED]",
            PIIType.LINKEDIN_URL: "[LINKEDIN_PROFILE_REDACTED]",
            PIIType.NAME: "[NAME_REDACTED]",
            PIIType.ADDRESS: "[ADDRESS_REDACTED]",
        }

    def detect_pii(self, text: str) -> List[PIIDetection]:
        """Detect PII instances in the given text."""
        detections = []

        for pii_type, pattern in self.patterns.items():
            matches = pattern.finditer(text)
            for match in matches:
                detection = PIIDetection(
                    pii_type=pii_type,
                    original_text=match.group(0),
                    start_pos=match.start(),
                    end_pos=match.end(),
                    redacted_text=self.redaction_policies[pii_type],
                    confidence=self._calculate_confidence(pii_type, match.group(0))
                )
                detections.append(detection)

        # Sort detections by position (reverse order for replacement)
        detections.sort(key=lambda d: d.start_pos, reverse=True)
        return detections

    def _calculate_confidence(self, pii_type: PIIType, text: str) -> float:
        """Calculate confidence score for PII detection."""
        # Basic confidence calculation - can be enhanced with ML models
        confidence_scores = {
            PIIType.EMAIL: 0.95 if '@' in text and '.' in text else 0.7,
            PIIType.PHONE: 0.9,
            PIIType.SSN: 0.85,
            PIIType.CREDIT_CARD: 0.9,
            PIIType.IP_ADDRESS: 0.8,
            PIIType.URL: 0.95,
            PIIType.API_KEY: 0.9,
            PIIType.JWT_TOKEN: 0.95,
            PIIType.PASSWORD: 0.8,
            PIIType.LINKEDIN_URL: 0.95,
        }
        return confidence_scores.get(pii_type, 0.5)

    def redact_text(self, text: str, min_confidence: float = 0.7) -> Tuple[str, List[PIIDetection]]:
        """Redact PII from text based on confidence threshold."""
        detections = self.detect_pii(text)
        high_confidence_detections = [
            d for d in detections if d.confidence >= min_confidence
        ]

        redacted_text = text
        for detection in high_confidence_detections:
            redacted_text = (
                redacted_text[:detection.start_pos] +
                detection.redacted_text +
                redacted_text[detection.end_pos:]
            )

        return redacted_text, high_confidence_detections

    def redact_chat_message(self, message: str, preserve_context: bool = True) -> Dict[str, Any]:
        """Redact PII from a chat message while preserving conversational context."""
        original_message = message
        redacted_message, detections = self.redact_text(message)

        # Create redaction summary for audit logs
        redaction_summary = {
            "original_length": len(original_message),
            "redacted_length": len(redacted_message),
            "pii_types_found": list(set(d.pii_type.value for d in detections)),
            "redaction_count": len(detections),
            "redacted_message": redacted_message,
        }

        # Add hash of original for verification without storing PII
        redaction_summary["original_hash"] = hashlib.sha256(
            original_message.encode('utf-8')
        ).hexdigest()

        # Log redaction event for audit
        if detections:
            logger.info(
                f"PII redacted from chat message",
                extra={
                    "redaction_count": len(detections),
                    "pii_types": [d.pii_type.value for d in detections],
                    "message_hash": redaction_summary["original_hash"]
                }
            )

        return redaction_summary

    def redact_user_data(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact PII from user data structures."""
        redacted_data = {}

        for key, value in user_data.items():
            if isinstance(value, str):
                redacted_value, _ = self.redact_text(value)
                redacted_data[key] = redacted_value
            elif isinstance(value, dict):
                redacted_data[key] = self.redact_user_data(value)
            elif isinstance(value, list):
                redacted_data[key] = [
                    self.redact_user_data(item) if isinstance(item, dict)
                    else self.redact_text(item)[0] if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                redacted_data[key] = value

        return redacted_data

    def create_audit_trail(self, original_data: Any, redacted_data: Any, context: str) -> Dict[str, Any]:
        """Create an audit trail for redaction operations."""
        audit_entry = {
            "timestamp": logger.name,  # Will be filled by logging system
            "context": context,
            "original_hash": hashlib.sha256(str(original_data).encode()).hexdigest(),
            "redacted_hash": hashlib.sha256(str(redacted_data).encode()).hexdigest(),
            "redaction_applied": original_data != redacted_data,
        }

        return audit_entry


# Global instance
pii_redaction_service = PIIRedactionService()


def redact_chat_content(content: str) -> str:
    """Convenience function to redact PII from chat content."""
    result = pii_redaction_service.redact_chat_message(content)
    return result["redacted_message"]


def redact_api_response(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to redact PII from API responses."""
    return pii_redaction_service.redact_user_data(response_data)