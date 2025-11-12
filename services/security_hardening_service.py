#!/usr/bin/env python3
"""
Enterprise Security Hardening Service - September 2025 Production Hardening
Comprehensive security controls, secret management, and audit logging

Features:
- Secure credential management with encryption
- Role-based access control (RBAC)
- API authentication and authorization
- Data encryption at rest and in transit
- Comprehensive audit logging
- Security monitoring and alerting
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Set
import jwt
import bcrypt

from core.roles import normalize_role

from services.database_pool_manager import get_main_db_connection
from services.error_handling_framework import handle_errors, error_context

logger = logging.getLogger(__name__)

class SecurityLevel(Enum):
    """Security classification levels"""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"

class UserRole(Enum):
    """User roles for RBAC"""
    USER = "user"
    ADMIN = "admin"

class AuditEventType(Enum):
    """Security audit event types"""
    LOGIN = "login"
    LOGOUT = "logout"
    ACCESS_GRANTED = "access_granted"
    ACCESS_DENIED = "access_denied"
    DATA_ACCESS = "data_access"
    DATA_MODIFICATION = "data_modification"
    SECRET_ACCESS = "secret_access"
    PERMISSION_CHANGE = "permission_change"
    SECURITY_VIOLATION = "security_violation"

@dataclass
class SecurityCredential:
    """Secure credential storage"""
    name: str
    encrypted_value: bytes
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    access_count: int = 0
    last_accessed: Optional[datetime] = None

@dataclass
class SecurityPolicy:
    """Security policy definition"""
    name: str
    resource_pattern: str
    required_role: UserRole
    allowed_operations: Set[str]
    conditions: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

@dataclass
class AuditLog:
    """Security audit log entry"""
    id: str
    event_type: AuditEventType
    user_id: Optional[int] = None
    organization_id: Optional[int] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    result: str = "success"
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class SecretManager:
    """Secure secret management with encryption"""

    def __init__(self, master_key: Optional[str] = None):
        self.master_key = master_key or self._generate_master_key()
        self.cipher_suite = self._create_cipher_suite()
        self.secrets_cache: Dict[str, SecurityCredential] = {}
        self._cache_ttl = 300  # 5 minutes

    def _generate_master_key(self) -> str:
        """Generate or retrieve master encryption key"""

        # Try to get from environment first
        master_key = os.getenv('VAULT_ENCRYPTION_KEY')
        if master_key:
            return master_key

        # Generate temporary key for development
        temp_key = Fernet.generate_key().decode()
        logger.warning("Generated temporary encryption key - configure VAULT_ENCRYPTION_KEY for production")
        return temp_key

    def _create_cipher_suite(self) -> Fernet:
        """Create encryption cipher suite"""

        # Derive key from master key using PBKDF2
        password = self.master_key.encode()
        salt = b'vouchlink_ai_master_game_plan_2025'  # Static salt for consistency

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )

        key = base64.urlsafe_b64encode(kdf.derive(password))
        return Fernet(key)

    async def store_secret(self,
                          name: str,
                          value: str,
                          metadata: Dict[str, Any] = None,
                          expires_in_days: Optional[int] = None) -> bool:
        """Store encrypted secret"""

        try:
            # Encrypt the secret value
            encrypted_value = self.cipher_suite.encrypt(value.encode())

            # Set expiration
            expires_at = None
            if expires_in_days:
                expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

            # Create credential
            credential = SecurityCredential(
                name=name,
                encrypted_value=encrypted_value,
                metadata=metadata or {},
                expires_at=expires_at
            )

            # Store in database
            async with get_main_db_connection() as conn:
                await conn.execute("""
                    INSERT INTO security_credentials (name, encrypted_value, metadata, created_at, expires_at)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (name) DO UPDATE SET
                        encrypted_value = EXCLUDED.encrypted_value,
                        metadata = EXCLUDED.metadata,
                        created_at = EXCLUDED.created_at,
                        expires_at = EXCLUDED.expires_at
                """, name, encrypted_value, json.dumps(metadata or {}),
                credential.created_at, expires_at)

            # Cache the credential
            self.secrets_cache[name] = credential

            logger.info(f"🔐 Stored encrypted secret: {name}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to store secret {name}: {e}")
            return False

    async def get_secret(self, name: str) -> Optional[str]:
        """Retrieve and decrypt secret"""

        try:
            # Check cache first
            if name in self.secrets_cache:
                credential = self.secrets_cache[name]

                # Check if expired
                if credential.expires_at and datetime.now(timezone.utc) > credential.expires_at:
                    await self.delete_secret(name)
                    return None

                # Update access tracking
                credential.access_count += 1
                credential.last_accessed = datetime.now(timezone.utc)

                # Decrypt and return
                decrypted_value = self.cipher_suite.decrypt(credential.encrypted_value)
                return decrypted_value.decode()

            # Load from database
            async with get_main_db_connection() as conn:
                row = await conn.fetchrow("""
                    SELECT encrypted_value, metadata, expires_at, access_count
                    FROM security_credentials
                    WHERE name = $1
                """, name)

                if not row:
                    return None

                # Check expiration
                if row['expires_at'] and datetime.now(timezone.utc) > row['expires_at']:
                    await self.delete_secret(name)
                    return None

                # Update access count
                await conn.execute("""
                    UPDATE security_credentials
                    SET access_count = access_count + 1, last_accessed = $1
                    WHERE name = $2
                """, datetime.now(timezone.utc), name)

                # Decrypt value
                decrypted_value = self.cipher_suite.decrypt(row['encrypted_value'])

                # Cache the credential
                credential = SecurityCredential(
                    name=name,
                    encrypted_value=row['encrypted_value'],
                    metadata=json.loads(row['metadata'] or '{}'),
                    access_count=row['access_count'] + 1,
                    last_accessed=datetime.now(timezone.utc)
                )
                self.secrets_cache[name] = credential

                return decrypted_value.decode()

        except Exception as e:
            logger.error(f"❌ Failed to retrieve secret {name}: {e}")
            return None

    async def delete_secret(self, name: str) -> bool:
        """Delete secret"""

        try:
            async with get_main_db_connection() as conn:
                await conn.execute("DELETE FROM security_credentials WHERE name = $1", name)

            # Remove from cache
            if name in self.secrets_cache:
                del self.secrets_cache[name]

            logger.info(f"🗑️ Deleted secret: {name}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to delete secret {name}: {e}")
            return False

    async def list_secrets(self) -> List[Dict[str, Any]]:
        """List all secrets (metadata only)"""

        try:
            async with get_main_db_connection() as conn:
                rows = await conn.fetch("""
                    SELECT name, metadata, created_at, expires_at, access_count, last_accessed
                    FROM security_credentials
                    ORDER BY created_at DESC
                """)

                return [
                    {
                        "name": row['name'],
                        "metadata": json.loads(row['metadata'] or '{}'),
                        "created_at": row['created_at'].isoformat(),
                        "expires_at": row['expires_at'].isoformat() if row['expires_at'] else None,
                        "access_count": row['access_count'],
                        "last_accessed": row['last_accessed'].isoformat() if row['last_accessed'] else None
                    }
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"❌ Failed to list secrets: {e}")
            return []

class AccessControlManager:
    """Role-based access control (RBAC) manager"""

    def __init__(self):
        self.policies: Dict[str, SecurityPolicy] = {}
        self.role_hierarchy = {
            UserRole.USER: 1,
            UserRole.ADMIN: 2
        }

    async def create_policy(self, policy: SecurityPolicy):
        """Create security policy"""

        self.policies[policy.name] = policy

        # Store in database
        async with get_main_db_connection() as conn:
            await conn.execute("""
                INSERT INTO security_policies (name, resource_pattern, required_role, allowed_operations, conditions, enabled)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (name) DO UPDATE SET
                    resource_pattern = EXCLUDED.resource_pattern,
                    required_role = EXCLUDED.required_role,
                    allowed_operations = EXCLUDED.allowed_operations,
                    conditions = EXCLUDED.conditions,
                    enabled = EXCLUDED.enabled
            """, policy.name, policy.resource_pattern, policy.required_role.value,
            json.dumps(list(policy.allowed_operations)), json.dumps(policy.conditions), policy.enabled)

        logger.info(f"🛡️ Created security policy: {policy.name}")

    async def check_permission(self,
                             user_role: UserRole,
                             resource: str,
                             operation: str,
                             context: Dict[str, Any] = None) -> bool:
        """Check if user has permission for operation on resource"""

        context = context or {}

        # Load policies if not cached
        if not self.policies:
            await self._load_policies()

        # Check each policy
        for policy in self.policies.values():
            if not policy.enabled:
                continue

            # Check if resource matches pattern
            if not self._matches_pattern(resource, policy.resource_pattern):
                continue

            # Check if operation is allowed
            if operation not in policy.allowed_operations:
                continue

            # Check role hierarchy
            user_level = self.role_hierarchy.get(user_role, 0)
            required_level = self.role_hierarchy.get(policy.required_role, 0)

            if user_level >= required_level:
                # Check additional conditions
                if self._check_conditions(policy.conditions, context):
                    return True

        return False

    def _matches_pattern(self, resource: str, pattern: str) -> bool:
        """Check if resource matches pattern"""

        if pattern == "*":
            return True

        if pattern.endswith("*"):
            return resource.startswith(pattern[:-1])

        return resource == pattern

    def _check_conditions(self, conditions: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Check additional conditions"""

        for key, expected_value in conditions.items():
            if key not in context:
                return False

            if context[key] != expected_value:
                return False

        return True

    async def _load_policies(self):
        """Load policies from database"""

        try:
            async with get_main_db_connection() as conn:
                rows = await conn.fetch("SELECT * FROM security_policies WHERE enabled = true")

                for row in rows:
                    policy = SecurityPolicy(
                        name=row['name'],
                        resource_pattern=row['resource_pattern'],
                        required_role=UserRole(row['required_role']),
                        allowed_operations=set(json.loads(row['allowed_operations'])),
                        conditions=json.loads(row['conditions'] or '{}'),
                        enabled=row['enabled']
                    )
                    self.policies[policy.name] = policy

        except Exception as e:
            logger.error(f"❌ Failed to load security policies: {e}")

class SecurityAuditor:
    """Security audit logging and monitoring"""

    def __init__(self):
        self.audit_buffer: List[AuditLog] = []
        self.buffer_size = 100
        self._flush_task: Optional[asyncio.Task] = None

    async def log_event(self,
                       event_type: AuditEventType,
                       user_id: Optional[int] = None,
                       organization_id: Optional[int] = None,
                       resource: Optional[str] = None,
                       action: Optional[str] = None,
                       result: str = "success",
                       ip_address: Optional[str] = None,
                       user_agent: Optional[str] = None,
                       metadata: Dict[str, Any] = None):
        """Log security audit event"""

        audit_log = AuditLog(
            id=secrets.token_hex(16),
            event_type=event_type,
            user_id=user_id,
            organization_id=organization_id,
            resource=resource,
            action=action,
            result=result,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata or {}
        )

        self.audit_buffer.append(audit_log)

        # Flush buffer if full
        if len(self.audit_buffer) >= self.buffer_size:
            await self._flush_audit_logs()

    async def _flush_audit_logs(self):
        """Flush audit logs to database"""

        if not self.audit_buffer:
            return

        try:
            async with get_main_db_connection() as conn:
                # Prepare batch insert
                values = []
                for log in self.audit_buffer:
                    values.append((
                        log.id, log.event_type.value, log.user_id, log.organization_id,
                        log.resource, log.action, log.result, log.ip_address,
                        log.user_agent, json.dumps(log.metadata), log.timestamp
                    ))

                # Batch insert
                await conn.executemany("""
                    INSERT INTO security_audit_logs
                    (id, event_type, user_id, organization_id, resource, action, result,
                     ip_address, user_agent, metadata, timestamp)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """, values)

                # Clear buffer
                self.audit_buffer.clear()

        except Exception as e:
            logger.error(f"❌ Failed to flush audit logs: {e}")

    async def get_audit_logs(self,
                           user_id: Optional[int] = None,
                           organization_id: Optional[int] = None,
                           event_type: Optional[AuditEventType] = None,
                           start_time: Optional[datetime] = None,
                           end_time: Optional[datetime] = None,
                           limit: int = 100) -> List[Dict[str, Any]]:
        """Get audit logs with filtering"""

        try:
            conditions = ["1=1"]
            params = []
            param_count = 0

            if user_id:
                param_count += 1
                conditions.append(f"user_id = ${param_count}")
                params.append(user_id)

            if organization_id:
                param_count += 1
                conditions.append(f"organization_id = ${param_count}")
                params.append(organization_id)

            if event_type:
                param_count += 1
                conditions.append(f"event_type = ${param_count}")
                params.append(event_type.value)

            if start_time:
                param_count += 1
                conditions.append(f"timestamp >= ${param_count}")
                params.append(start_time)

            if end_time:
                param_count += 1
                conditions.append(f"timestamp <= ${param_count}")
                params.append(end_time)

            param_count += 1
            params.append(limit)

            query = f"""
                SELECT * FROM security_audit_logs
                WHERE {' AND '.join(conditions)}
                ORDER BY timestamp DESC
                LIMIT ${param_count}
            """

            async with get_main_db_connection() as conn:
                rows = await conn.fetch(query, *params)

                return [
                    {
                        "id": row['id'],
                        "event_type": row['event_type'],
                        "user_id": row['user_id'],
                        "organization_id": row['organization_id'],
                        "resource": row['resource'],
                        "action": row['action'],
                        "result": row['result'],
                        "ip_address": row['ip_address'],
                        "user_agent": row['user_agent'],
                        "metadata": json.loads(row['metadata'] or '{}'),
                        "timestamp": row['timestamp'].isoformat()
                    }
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"❌ Failed to get audit logs: {e}")
            return []

class JWTManager:
    """JWT token management for API authentication"""

    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = secret_key or os.getenv('JWT_SECRET_KEY', 'fallback_secret_2025')
        self.algorithm = 'HS256'
        self.default_expiry = timedelta(hours=24)

    def generate_token(self,
                      user_id: int,
                      organization_id: int,
                      email: str,
                      role: UserRole,
                      expires_in: Optional[timedelta] = None) -> str:
        """Generate JWT token"""

        expiry = expires_in or self.default_expiry

        payload = {
            'user_id': user_id,
            'organization_id': organization_id,
            'email': email,
            'role': role.value,
            'iat': datetime.now(timezone.utc),
            'exp': datetime.now(timezone.utc) + expiry
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode JWT token"""

        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("JWT token expired")
            return None

        except jwt.InvalidTokenError:
            logger.warning("Invalid JWT token")
            return None

    def refresh_token(self, token: str) -> Optional[str]:
        """Refresh JWT token if valid and not expired"""

        payload = self.verify_token(token)
        if not payload:
            return None

        # Generate new token with same payload but fresh expiry
        new_payload = {
            'user_id': payload['user_id'],
            'organization_id': payload['organization_id'],
            'email': payload['email'],
            'role': payload['role'],
            'iat': datetime.now(timezone.utc),
            'exp': datetime.now(timezone.utc) + self.default_expiry
        }

        return jwt.encode(new_payload, self.secret_key, algorithm=self.algorithm)

class SecurityHardeningService:
    """Main security hardening service"""

    def __init__(self):
        self.secret_manager = SecretManager()
        self.access_control = AccessControlManager()
        self.auditor = SecurityAuditor()
        self.jwt_manager = JWTManager()
        self._initialized = False

    async def initialize(self):
        """Initialize security service"""

        if self._initialized:
            return

        # Ensure database schema exists
        await self._ensure_security_schema()

        # Setup default security policies
        await self._setup_default_policies()

        # Start background tasks
        asyncio.create_task(self._periodic_audit_flush())

        self._initialized = True
        logger.info("🔐 Security Hardening Service initialized")

    async def _ensure_security_schema(self):
        """Ensure security database schema exists"""

        async with get_main_db_connection() as conn:
            # Security credentials table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS security_credentials (
                    name VARCHAR(255) PRIMARY KEY,
                    encrypted_value BYTEA NOT NULL,
                    metadata JSONB DEFAULT '{}',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    expires_at TIMESTAMP WITH TIME ZONE,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TIMESTAMP WITH TIME ZONE
                )
            """)

            # Security policies table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS security_policies (
                    name VARCHAR(255) PRIMARY KEY,
                    resource_pattern VARCHAR(255) NOT NULL,
                    required_role VARCHAR(50) NOT NULL,
                    allowed_operations JSONB NOT NULL,
                    conditions JSONB DEFAULT '{}',
                    enabled BOOLEAN DEFAULT true,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)

            # Security audit logs table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS security_audit_logs (
                    id VARCHAR(32) PRIMARY KEY,
                    event_type VARCHAR(50) NOT NULL,
                    user_id INTEGER,
                    organization_id INTEGER,
                    resource VARCHAR(255),
                    action VARCHAR(100),
                    result VARCHAR(20) DEFAULT 'success',
                    ip_address VARCHAR(45),
                    user_agent TEXT,
                    metadata JSONB DEFAULT '{}',
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)

            # Indexes for performance
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_security_audit_user_org
                ON security_audit_logs(user_id, organization_id, timestamp DESC)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_security_audit_event_time
                ON security_audit_logs(event_type, timestamp DESC)
            """)

    async def _setup_default_policies(self):
        """Setup default security policies"""

        # Admin policies
        admin_policy = SecurityPolicy(
            name="admin_full_access",
            resource_pattern="*",
            required_role=UserRole.ADMIN,
            allowed_operations={"create", "read", "update", "delete", "execute"}
        )
        await self.access_control.create_policy(admin_policy)

        # Workflow policies
        workflow_policy = SecurityPolicy(
            name="workflow_management",
            resource_pattern="workflow/*",
            required_role=UserRole.ADMIN,
            allowed_operations={"create", "read", "update"}
        )
        await self.access_control.create_policy(workflow_policy)

        # Data access policies
        data_policy = SecurityPolicy(
            name="data_access",
            resource_pattern="data/*",
            required_role=UserRole.USER,
            allowed_operations={"read"}
        )
        await self.access_control.create_policy(data_policy)

    async def _periodic_audit_flush(self):
        """Periodic audit log flushing"""

        while True:
            try:
                await asyncio.sleep(60)  # Flush every minute
                await self.auditor._flush_audit_logs()

            except Exception as e:
                logger.error(f"Audit flush error: {e}")

    @handle_errors(service_name="security_hardening")
    async def authenticate_request(self, token: str, required_resource: str, required_operation: str) -> Dict[str, Any]:
        """Authenticate and authorize API request"""

        # Verify JWT token
        payload = self.jwt_manager.verify_token(token)
        if not payload:
            await self.auditor.log_event(
                AuditEventType.ACCESS_DENIED,
                resource=required_resource,
                action=required_operation,
                result="invalid_token"
            )
            return {"authorized": False, "error": "Invalid or expired token"}

        # Extract user information
        user_id = payload.get('user_id')
        organization_id = payload.get('organization_id')
        role = UserRole(normalize_role(payload.get('role')))

        # Check permissions
        authorized = await self.access_control.check_permission(
            user_role=role,
            resource=required_resource,
            operation=required_operation,
            context={"organization_id": organization_id}
        )

        # Log audit event
        event_type = AuditEventType.ACCESS_GRANTED if authorized else AuditEventType.ACCESS_DENIED
        await self.auditor.log_event(
            event_type=event_type,
            user_id=user_id,
            organization_id=organization_id,
            resource=required_resource,
            action=required_operation,
            result="authorized" if authorized else "permission_denied"
        )

        if authorized:
            return {
                "authorized": True,
                "user_id": user_id,
                "organization_id": organization_id,
                "role": role.value
            }
        else:
            return {"authorized": False, "error": "Insufficient permissions"}

    async def get_security_dashboard_data(self) -> Dict[str, Any]:
        """Get security dashboard data"""

        # Recent audit events
        recent_events = await self.auditor.get_audit_logs(limit=50)

        # Security metrics
        async with get_main_db_connection() as conn:
            # Count events by type in last 24 hours
            event_counts = await conn.fetch("""
                SELECT event_type, COUNT(*) as count
                FROM security_audit_logs
                WHERE timestamp >= $1
                GROUP BY event_type
                ORDER BY count DESC
            """, datetime.now(timezone.utc) - timedelta(hours=24))

            # Failed access attempts
            failed_access = await conn.fetchval("""
                SELECT COUNT(*) FROM security_audit_logs
                WHERE event_type = 'access_denied'
                AND timestamp >= $1
            """, datetime.now(timezone.utc) - timedelta(hours=24))

            # Active secrets count
            secrets_count = await conn.fetchval("SELECT COUNT(*) FROM security_credentials")

        # Secrets list (metadata only)
        secrets_list = await self.secret_manager.list_secrets()

        return {
            "recent_events": recent_events[:20],  # Last 20 events
            "event_counts": [dict(row) for row in event_counts],
            "failed_access_attempts_24h": failed_access,
            "active_secrets_count": secrets_count,
            "secrets_list": secrets_list,
            "policies_count": len(self.access_control.policies),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# Global security service instance
security_service = SecurityHardeningService()

# Context managers and decorators for security

@asynccontextmanager
async def security_context(token: str, resource: str, operation: str):
    """Security context manager for protected operations"""

    auth_result = await security_service.authenticate_request(token, resource, operation)

    if not auth_result.get("authorized"):
        raise PermissionError(auth_result.get("error", "Access denied"))

    yield auth_result

def require_permission(resource: str, operation: str):
    """Decorator to require specific permission for function"""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract token from kwargs or request context
            token = kwargs.pop('auth_token', None)
            if not token:
                raise ValueError("Authentication token required")

            # Check permission
            async with security_context(token, resource, operation) as auth_info:
                # Add auth info to kwargs
                kwargs['auth_info'] = auth_info
                return await func(*args, **kwargs)

        return wrapper
    return decorator

# Utility functions

async def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

async def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def generate_api_key() -> str:
    """Generate secure API key"""
    return secrets.token_urlsafe(32)

def validate_input(input_data: str, max_length: int = 1000) -> str:
    """Validate and sanitize input data"""

    if not input_data:
        return ""

    # Remove potentially dangerous characters
    sanitized = input_data.replace('<', '&lt;').replace('>', '&gt;')

    # Truncate to max length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    return sanitized.strip()

async def create_secure_session(user_id: int, organization_id: int, email: str, role: UserRole) -> Dict[str, str]:
    """Create secure user session with tokens"""

    # Generate access token
    access_token = security_service.jwt_manager.generate_token(
        user_id=user_id,
        organization_id=organization_id,
        email=email,
        role=role,
        expires_in=timedelta(hours=1)
    )

    # Generate refresh token
    refresh_token = security_service.jwt_manager.generate_token(
        user_id=user_id,
        organization_id=organization_id,
        email=email,
        role=role,
        expires_in=timedelta(days=7)
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": 3600
    }
