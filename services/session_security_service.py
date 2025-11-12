"""
Session Security Service for VouchLink AI
Implements comprehensive session management and security hardening.
"""

import json
import logging
import secrets
import time
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

try:
    import jwt  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    jwt = None  # type: ignore
    logging.getLogger(__name__).warning(
        "PyJWT is not installed; session token utilities will be unavailable."
    )

try:
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover - optional dependency
    Fernet = None  # type: ignore
    logging.getLogger(__name__).warning(
        "cryptography is not installed; session encryption will be disabled."
    )

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session states."""
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUSPICIOUS = "suspicious"


@dataclass
class SessionInfo:
    """Session information."""
    session_id: str
    user_id: int
    tenant_id: str
    created_at: datetime
    last_activity: datetime
    expires_at: datetime
    ip_address: str
    user_agent: str
    device_fingerprint: str
    state: SessionState
    csrf_token: str
    refresh_token: Optional[str] = None
    metadata: Dict[str, Any] = None


@dataclass
class SecurityPolicy:
    """Session security policy configuration."""
    session_timeout_minutes: int = 480  # 8 hours
    idle_timeout_minutes: int = 60  # 1 hour
    max_sessions_per_user: int = 5
    require_device_fingerprinting: bool = True
    enable_csrf_protection: bool = True
    secure_cookie_flags: bool = True
    same_site_strict: bool = True
    rotate_session_on_auth: bool = True
    detect_session_hijacking: bool = True
    ip_change_detection: bool = True
    user_agent_validation: bool = True


class SessionSecurityService:
    """Service for secure session management."""

    def __init__(self, secret_key: str, policy: Optional[SecurityPolicy] = None):
        """Initialize the session security service."""
        self.secret_key = secret_key
        self.policy = policy or SecurityPolicy()
        self.active_sessions: Dict[str, SessionInfo] = {}
        self.user_sessions: Dict[int, List[str]] = {}
        self.revoked_tokens: set = set()

        # Initialize encryption for sensitive session data when cryptography is available
        if secret_key and Fernet is not None:
            self.fernet = Fernet(Fernet.generate_key())
        else:
            self.fernet = None

    def create_session(
        self,
        user_id: int,
        tenant_id: str,
        ip_address: str,
        user_agent: str,
        device_fingerprint: Optional[str] = None
    ) -> SessionInfo:
        """Create a new secure session."""
        # Generate session ID
        session_id = self._generate_session_id()

        # Generate CSRF token
        csrf_token = self._generate_csrf_token()

        # Calculate expiration times
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=self.policy.session_timeout_minutes)

        # Create device fingerprint if not provided
        if not device_fingerprint and self.policy.require_device_fingerprinting:
            device_fingerprint = self._generate_device_fingerprint(user_agent, ip_address)

        # Check session limits
        self._enforce_session_limits(user_id)

        # Create session info
        session_info = SessionInfo(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=now,
            last_activity=now,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint or "",
            state=SessionState.ACTIVE,
            csrf_token=csrf_token,
            metadata={}
        )

        # Store session
        self.active_sessions[session_id] = session_info

        # Track user sessions
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = []
        self.user_sessions[user_id].append(session_id)

        logger.info(
            f"Session created",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "ip_address": ip_address,
                "expires_at": expires_at.isoformat()
            }
        )

        return session_info

    def validate_session(
        self,
        session_id: str,
        ip_address: str,
        user_agent: str
    ) -> Tuple[bool, Optional[SessionInfo], List[str]]:
        """Validate a session and return validation result."""
        warnings = []

        # Check if session exists
        if session_id not in self.active_sessions:
            return False, None, ["Session not found"]

        session = self.active_sessions[session_id]

        # Check session state
        if session.state != SessionState.ACTIVE:
            return False, session, [f"Session is {session.state.value}"]

        # Check expiration
        now = datetime.now(timezone.utc)
        if now > session.expires_at:
            session.state = SessionState.EXPIRED
            return False, session, ["Session expired"]

        # Check idle timeout
        idle_time = now - session.last_activity
        if idle_time.total_seconds() > (self.policy.idle_timeout_minutes * 60):
            session.state = SessionState.EXPIRED
            return False, session, ["Session idle timeout"]

        # Security checks
        security_issues = self._perform_security_checks(session, ip_address, user_agent)
        if security_issues:
            if "critical" in str(security_issues).lower():
                session.state = SessionState.SUSPICIOUS
                return False, session, security_issues
            else:
                warnings.extend(security_issues)

        # Update last activity
        session.last_activity = now

        return True, session, warnings

    def _perform_security_checks(
        self,
        session: SessionInfo,
        current_ip: str,
        current_user_agent: str
    ) -> List[str]:
        """Perform security checks on the session."""
        issues = []

        # IP address change detection
        if self.policy.ip_change_detection and session.ip_address != current_ip:
            issues.append("IP address changed - possible session hijacking")
            logger.warning(
                f"IP address change detected",
                extra={
                    "session_id": session.session_id,
                    "user_id": session.user_id,
                    "original_ip": session.ip_address,
                    "current_ip": current_ip
                }
            )

        # User agent validation
        if self.policy.user_agent_validation:
            if not self._is_user_agent_similar(session.user_agent, current_user_agent):
                issues.append("User agent mismatch - possible session hijacking")
                logger.warning(
                    f"User agent change detected",
                    extra={
                        "session_id": session.session_id,
                        "user_id": session.user_id,
                        "original_ua": session.user_agent[:100],
                        "current_ua": current_user_agent[:100]
                    }
                )

        # Device fingerprint check
        if self.policy.require_device_fingerprinting and session.device_fingerprint:
            current_fingerprint = self._generate_device_fingerprint(current_user_agent, current_ip)
            if current_fingerprint != session.device_fingerprint:
                issues.append("Device fingerprint mismatch")

        return issues

    def refresh_session(self, session_id: str) -> Optional[SessionInfo]:
        """Refresh a session's expiration time."""
        if session_id not in self.active_sessions:
            return None

        session = self.active_sessions[session_id]

        if session.state != SessionState.ACTIVE:
            return None

        # Extend expiration
        session.expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.policy.session_timeout_minutes)
        session.last_activity = datetime.now(timezone.utc)

        logger.info(
            f"Session refreshed",
            extra={
                "session_id": session_id,
                "user_id": session.user_id,
                "new_expires_at": session.expires_at.isoformat()
            }
        )

        return session

    def revoke_session(self, session_id: str, reason: str = "Manual revocation") -> bool:
        """Revoke a specific session."""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]
        session.state = SessionState.REVOKED

        # Remove from user sessions
        if session.user_id in self.user_sessions:
            self.user_sessions[session.user_id] = [
                sid for sid in self.user_sessions[session.user_id] if sid != session_id
            ]

        # Add to revoked tokens if it's a JWT
        self.revoked_tokens.add(session_id)

        logger.info(
            f"Session revoked",
            extra={
                "session_id": session_id,
                "user_id": session.user_id,
                "reason": reason
            }
        )

        return True

    def revoke_all_user_sessions(self, user_id: int, except_session: Optional[str] = None) -> int:
        """Revoke all sessions for a user except optionally one."""
        if user_id not in self.user_sessions:
            return 0

        sessions_to_revoke = self.user_sessions[user_id][:]
        if except_session:
            sessions_to_revoke = [sid for sid in sessions_to_revoke if sid != except_session]

        revoked_count = 0
        for session_id in sessions_to_revoke:
            if self.revoke_session(session_id, "Bulk revocation"):
                revoked_count += 1

        return revoked_count

    def cleanup_expired_sessions(self) -> int:
        """Clean up expired and revoked sessions."""
        now = datetime.now(timezone.utc)
        expired_sessions = []

        for session_id, session in self.active_sessions.items():
            if (session.state in [SessionState.EXPIRED, SessionState.REVOKED] or
                now > session.expires_at):
                expired_sessions.append(session_id)

        # Remove expired sessions
        for session_id in expired_sessions:
            session = self.active_sessions.pop(session_id, None)
            if session and session.user_id in self.user_sessions:
                self.user_sessions[session.user_id] = [
                    sid for sid in self.user_sessions[session.user_id] if sid != session_id
                ]

        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")

        return len(expired_sessions)

    def get_session_security_headers(self, session: SessionInfo) -> Dict[str, str]:
        """Get security headers for session responses."""
        headers = {}

        if self.policy.secure_cookie_flags:
            headers["Set-Cookie"] = f"session_id={session.session_id}; " \
                                   f"HttpOnly; Secure; " \
                                   f"SameSite={'Strict' if self.policy.same_site_strict else 'Lax'}; " \
                                   f"Max-Age={self.policy.session_timeout_minutes * 60}"

        if self.policy.enable_csrf_protection:
            headers["X-CSRF-Token"] = session.csrf_token

        # Security headers
        headers.update({
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Referrer-Policy": "strict-origin-when-cross-origin"
        })

        return headers

    def validate_csrf_token(self, session_id: str, provided_token: str) -> bool:
        """Validate CSRF token for the session."""
        if not self.policy.enable_csrf_protection:
            return True

        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]
        return secrets.compare_digest(session.csrf_token, provided_token)

    def generate_jwt_token(self, session: SessionInfo, expires_minutes: int = 15) -> str:
        """Generate a JWT token for the session."""
        if jwt is None:
            raise RuntimeError("PyJWT is not installed; cannot generate JWT tokens.")

        payload = {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "tenant_id": session.tenant_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + (expires_minutes * 60),
            "device_fingerprint": session.device_fingerprint
        }

        return jwt.encode(payload, self.secret_key, algorithm="HS256")

    def validate_jwt_token(self, token: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Validate a JWT token."""
        if jwt is None:
            raise RuntimeError("PyJWT is not installed; cannot validate JWT tokens.")

        try:
            # Check if token is revoked
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"], options={"verify_exp": False})
            session_id = payload.get("session_id")

            if session_id in self.revoked_tokens:
                return False, None

            # Verify expiration
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])

            # Additional session validation
            if session_id in self.active_sessions:
                session = self.active_sessions[session_id]
                if session.state != SessionState.ACTIVE:
                    return False, None

            return True, payload

        except jwt.ExpiredSignatureError:
            return False, None
        except jwt.InvalidTokenError:
            return False, None

    def _generate_session_id(self) -> str:
        """Generate a cryptographically secure session ID."""
        return secrets.token_urlsafe(32)

    def _generate_csrf_token(self) -> str:
        """Generate a CSRF token."""
        return secrets.token_urlsafe(32)

    def _generate_device_fingerprint(self, user_agent: str, ip_address: str) -> str:
        """Generate a device fingerprint."""
        fingerprint_data = f"{user_agent}:{ip_address}:{self.secret_key}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]

    def _enforce_session_limits(self, user_id: int):
        """Enforce maximum sessions per user."""
        if user_id not in self.user_sessions:
            return

        current_sessions = self.user_sessions[user_id]

        if len(current_sessions) >= self.policy.max_sessions_per_user:
            # Remove oldest sessions
            sessions_to_remove = len(current_sessions) - self.policy.max_sessions_per_user + 1

            for _ in range(sessions_to_remove):
                if current_sessions:
                    oldest_session_id = current_sessions.pop(0)
                    self.revoke_session(oldest_session_id, "Session limit exceeded")

    def _is_user_agent_similar(self, original: str, current: str) -> bool:
        """Check if user agents are similar enough (basic version check)."""
        # Extract browser name and major version
        def extract_browser_info(ua):
            ua = ua.lower()
            if 'chrome' in ua:
                return 'chrome'
            elif 'firefox' in ua:
                return 'firefox'
            elif 'safari' in ua:
                return 'safari'
            elif 'edge' in ua:
                return 'edge'
            else:
                return 'unknown'

        return extract_browser_info(original) == extract_browser_info(current)

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        now = datetime.now(timezone.utc)
        active_count = sum(1 for s in self.active_sessions.values() if s.state == SessionState.ACTIVE)
        expired_count = sum(1 for s in self.active_sessions.values() if now > s.expires_at)

        return {
            "total_sessions": len(self.active_sessions),
            "active_sessions": active_count,
            "expired_sessions": expired_count,
            "revoked_tokens": len(self.revoked_tokens),
            "users_with_sessions": len(self.user_sessions),
            "policy": asdict(self.policy)
        }

    def export_session_for_storage(self, session: SessionInfo) -> str:
        """Export session data for secure storage."""
        if not self.fernet:
            return json.dumps(asdict(session), default=str)

        session_data = asdict(session)
        # Convert datetime objects to ISO strings
        for key, value in session_data.items():
            if isinstance(value, datetime):
                session_data[key] = value.isoformat()

        json_data = json.dumps(session_data)
        encrypted_data = self.fernet.encrypt(json_data.encode())
        return encrypted_data.decode()

    def import_session_from_storage(self, encrypted_data: str) -> Optional[SessionInfo]:
        """Import session data from secure storage."""
        try:
            if not self.fernet:
                session_data = json.loads(encrypted_data)
            else:
                decrypted_data = self.fernet.decrypt(encrypted_data.encode())
                session_data = json.loads(decrypted_data.decode())

            # Convert ISO strings back to datetime objects
            for key in ['created_at', 'last_activity', 'expires_at']:
                if key in session_data and isinstance(session_data[key], str):
                    session_data[key] = datetime.fromisoformat(session_data[key])

            # Convert state back to enum
            if 'state' in session_data:
                session_data['state'] = SessionState(session_data['state'])

            return SessionInfo(**session_data)

        except Exception as e:
            logger.error(f"Failed to import session from storage: {e}")
            return None


# Global instance (will be initialized with proper secret key)
session_security_service: Optional[SessionSecurityService] = None


def initialize_session_service(secret_key: str, policy: Optional[SecurityPolicy] = None):
    """Initialize the global session security service."""
    global session_security_service
    session_security_service = SessionSecurityService(secret_key, policy)


def get_session_service() -> SessionSecurityService:
    """Get the global session security service."""
    if session_security_service is None:
        raise RuntimeError("Session service not initialized. Call initialize_session_service() first.")
    return session_security_service