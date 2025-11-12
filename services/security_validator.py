"""
Security Validator - Phase 13: Multi-Tenant Security Hardening

Ensures strict organization-scoped isolation and prevents data leakage between
different organizations using the VouchLink platform. Critical for enterprise
security and compliance requirements.
"""

import logging
import hashlib
import re
from typing import Dict, Any, Optional, List, Set, Tuple
from datetime import datetime, timedelta, timezone
from enum import Enum
import json

logger = logging.getLogger(__name__)

class SecurityLevel(Enum):
    """Security levels for different operations"""
    PUBLIC = "public"
    ORGANIZATION = "organization"
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"

class AccessType(Enum):
    """Types of access operations"""
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    APPROVE = "approve"
    ADMIN = "admin"

class SecurityValidationError(Exception):
    """Raised when security validation fails"""
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.context = context or {}

class SecurityValidator:
    """
    Validates multi-tenant security and ensures organization-scoped isolation

    This validator ensures that:
    - Users can only access data from their organization
    - Workflows cannot leak data between organizations
    - API requests are properly scoped and authorized
    - Cross-tenant data access is prevented
    """

    def __init__(self):
        self.organization_access_cache: Dict[str, Set[int]] = {}
        self.user_permissions_cache: Dict[str, Dict[str, Any]] = {}
        self.security_violations: List[Dict[str, Any]] = []

    def validate_organization_access(
        self,
        user_id: int,
        user_organization_id: int,
        requested_organization_id: int,
        operation: str = "access"
    ) -> bool:
        """
        Validate that a user can access resources from the requested organization

        Args:
            user_id: ID of the user making the request
            user_organization_id: Organization ID of the user
            requested_organization_id: Organization ID being accessed
            operation: Type of operation being performed

        Returns:
            True if access is allowed, False otherwise

        Raises:
            SecurityValidationError: If access is denied
        """
        # Basic tenant isolation: users can only access their own organization
        if user_organization_id != requested_organization_id:
            violation = {
                'type': 'cross_tenant_access_attempt',
                'user_id': user_id,
                'user_organization': user_organization_id,
                'requested_organization': requested_organization_id,
                'operation': operation,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'severity': 'HIGH'
            }
            self.security_violations.append(violation)

            logger.warning(f"Security violation: User {user_id} from org {user_organization_id} "
                         f"attempted to access org {requested_organization_id} for {operation}")

            raise SecurityValidationError(
                f"Access denied: User cannot access resources from organization {requested_organization_id}",
                context=violation
            )

        return True

    def validate_conversation_access(
        self,
        user_id: int,
        user_organization_id: int,
        conversation_metadata: Dict[str, Any]
    ) -> bool:
        """
        Validate access to a specific conversation
        """
        conversation_org_id = conversation_metadata.get('organization_id')

        if not conversation_org_id:
            raise SecurityValidationError(
                "Conversation missing organization ID - security validation failed",
                context={'conversation_id': conversation_metadata.get('id'), 'user_id': user_id}
            )

        return self.validate_organization_access(
            user_id, user_organization_id, conversation_org_id, "conversation_access"
        )

    def validate_workflow_access(
        self,
        user_id: int,
        user_organization_id: int,
        workflow_metadata: Dict[str, Any]
    ) -> bool:
        """
        Validate access to a specific workflow
        """
        workflow_org_id = workflow_metadata.get('organization_id')

        if not workflow_org_id:
            raise SecurityValidationError(
                "Workflow missing organization ID - security validation failed",
                context={'workflow_id': workflow_metadata.get('id'), 'user_id': user_id}
            )

        return self.validate_organization_access(
            user_id, user_organization_id, workflow_org_id, "workflow_access"
        )

    def validate_prospect_access(
        self,
        user_id: int,
        user_organization_id: int,
        prospect_metadata: Dict[str, Any]
    ) -> bool:
        """
        Validate access to prospect data (especially sensitive for multi-tenant)
        """
        prospect_org_id = prospect_metadata.get('organization_id')

        if not prospect_org_id:
            raise SecurityValidationError(
                "Prospect missing organization ID - security validation failed",
                context={'prospect_id': prospect_metadata.get('id'), 'user_id': user_id}
            )

        return self.validate_organization_access(
            user_id, user_organization_id, prospect_org_id, "prospect_access"
        )

    def sanitize_metadata_for_organization(
        self,
        metadata: Dict[str, Any],
        target_organization_id: int
    ) -> Dict[str, Any]:
        """
        Remove sensitive information that shouldn't be shared across organizations
        """
        sanitized = metadata.copy()

        # Remove cross-organizational references
        cross_org_keys = [
            'external_organization_id',
            'shared_prospect_data',
            'cross_tenant_context',
            'global_user_data'
        ]

        for key in cross_org_keys:
            if key in sanitized:
                del sanitized[key]

        # Ensure organization_id is set correctly
        sanitized['organization_id'] = target_organization_id

        # Remove any PII that might leak between organizations
        pii_patterns = [
            r'email',
            r'phone',
            r'address',
            r'linkedin_profile',
            r'personal_'
        ]

        for key in list(sanitized.keys()):
            for pattern in pii_patterns:
                if re.search(pattern, key, re.IGNORECASE):
                    # Only remove if it's not from the target organization
                    if sanitized.get(f"{key}_organization_id", target_organization_id) != target_organization_id:
                        logger.debug(f"Sanitizing cross-org PII field: {key}")
                        del sanitized[key]
                        break

        return sanitized

    def validate_api_request_scope(
        self,
        request_data: Dict[str, Any],
        user_organization_id: int
    ) -> Dict[str, Any]:
        """
        Validate and sanitize API request data to ensure proper organizational scoping
        """
        if 'organization_id' not in request_data:
            request_data['organization_id'] = user_organization_id
        elif request_data['organization_id'] != user_organization_id:
            raise SecurityValidationError(
                f"Request organization_id {request_data['organization_id']} does not match user organization {user_organization_id}",
                context={'request_data': request_data}
            )

        # Sanitize metadata if present
        if 'metadata' in request_data and isinstance(request_data['metadata'], dict):
            request_data['metadata'] = self.sanitize_metadata_for_organization(
                request_data['metadata'], user_organization_id
            )

        return request_data

    def create_security_context(
        self,
        user_id: int,
        organization_id: int,
        user_role: str = "user",
        additional_permissions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Create a security context for validating operations
        """
        context = {
            'user_id': user_id,
            'organization_id': organization_id,
            'user_role': user_role,
            'permissions': additional_permissions or [],
            'created_at': datetime.now(timezone.utc).isoformat(),
            'session_token': self._generate_session_token(user_id, organization_id)
        }

        # Cache for performance
        cache_key = f"{user_id}:{organization_id}"
        self.user_permissions_cache[cache_key] = context

        return context

    def validate_cross_service_communication(
        self,
        source_service: str,
        target_service: str,
        message_data: Dict[str, Any],
        organization_id: int
    ) -> bool:
        """
        Validate that cross-service communication maintains organizational boundaries
        """
        # Ensure organization_id is preserved in cross-service calls
        if 'organization_id' not in message_data:
            raise SecurityValidationError(
                f"Cross-service message from {source_service} to {target_service} missing organization_id",
                context={
                    'source_service': source_service,
                    'target_service': target_service,
                    'message_keys': list(message_data.keys())
                }
            )

        if message_data['organization_id'] != organization_id:
            raise SecurityValidationError(
                f"Organization ID mismatch in cross-service communication: expected {organization_id}, got {message_data['organization_id']}",
                context={
                    'source_service': source_service,
                    'target_service': target_service,
                    'expected_org': organization_id,
                    'actual_org': message_data['organization_id']
                }
            )

        return True

    def audit_data_access(
        self,
        user_id: int,
        organization_id: int,
        resource_type: str,
        resource_id: str,
        operation: AccessType
    ) -> Dict[str, Any]:
        """
        Create audit log entry for data access
        """
        audit_entry = {
            'user_id': user_id,
            'organization_id': organization_id,
            'resource_type': resource_type,
            'resource_id': resource_id,
            'operation': operation.value,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'audit_id': self._generate_audit_id(user_id, resource_type, resource_id)
        }

        logger.info(f"Data access audit: User {user_id} performed {operation.value} on {resource_type}:{resource_id}")
        return audit_entry

    def get_security_violations(
        self,
        organization_id: Optional[int] = None,
        severity: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get security violations with optional filtering
        """
        violations = self.security_violations

        if organization_id:
            violations = [v for v in violations if v.get('user_organization') == organization_id or v.get('requested_organization') == organization_id]

        if severity:
            violations = [v for v in violations if v.get('severity') == severity]

        return violations

    def clear_security_violations(self, organization_id: Optional[int] = None):
        """
        Clear security violations (for testing or administrative purposes)
        """
        if organization_id:
            self.security_violations = [
                v for v in self.security_violations
                if v.get('user_organization') != organization_id and v.get('requested_organization') != organization_id
            ]
        else:
            self.security_violations.clear()

        logger.info(f"Security violations cleared for organization {organization_id if organization_id else 'all'}")

    def _generate_session_token(self, user_id: int, organization_id: int) -> str:
        """Generate a session token for security context"""
        data = f"{user_id}:{organization_id}:{datetime.now(timezone.utc).isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    def _generate_audit_id(self, user_id: int, resource_type: str, resource_id: str) -> str:
        """Generate a unique audit ID"""
        data = f"{user_id}:{resource_type}:{resource_id}:{datetime.now(timezone.utc).isoformat()}"
        return hashlib.md5(data.encode()).hexdigest()

    def validate_message_content_security(self, content: str, organization_id: int) -> bool:
        """
        Validate that message content doesn't contain cross-organizational sensitive data
        """
        # Check for patterns that might indicate data leakage
        suspicious_patterns = [
            r'organization[_\s]+(\d+)',  # org_123, organization 456
            r'tenant[_\s]+(\d+)',        # tenant_789
            r'company[_\s]+id[_\s]*:?[_\s]*(\d+)',  # company_id: 123
            r'user[_\s]+(\d+)@',         # user_123@
        ]

        for pattern in suspicious_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                if isinstance(match, str) and match.isdigit():
                    referenced_org = int(match)
                    if referenced_org != organization_id:
                        logger.warning(f"Potential cross-org data reference in message: org {referenced_org} referenced in org {organization_id} content")
                        return False

        return True

# Global security validator instance
global_security_validator: Optional[SecurityValidator] = None

def get_global_security_validator() -> SecurityValidator:
    """Get or create the global security validator instance"""
    global global_security_validator

    if global_security_validator is None:
        global_security_validator = SecurityValidator()
        logger.info("Global security validator initialized")

    return global_security_validator

def validate_organization_access(user_id: int, user_org_id: int, requested_org_id: int) -> bool:
    """Convenience function for organization access validation"""
    validator = get_global_security_validator()
    return validator.validate_organization_access(user_id, user_org_id, requested_org_id)

def create_secure_context(user_id: int, organization_id: int, user_role: str = "user") -> Dict[str, Any]:
    """Convenience function for creating secure context"""
    validator = get_global_security_validator()
    return validator.create_security_context(user_id, organization_id, user_role)

def sanitize_cross_org_data(data: Dict[str, Any], target_org_id: int) -> Dict[str, Any]:
    """Convenience function for sanitizing cross-organizational data"""
    validator = get_global_security_validator()
    return validator.sanitize_metadata_for_organization(data, target_org_id)