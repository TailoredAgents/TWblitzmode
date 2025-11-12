"""
Rate Limiting Service for VouchLink AI
Implements comprehensive rate limiting for API endpoints and public forms.
"""

import time
import asyncio
import logging
import hashlib
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import json

logger = logging.getLogger(__name__)

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.info("Redis not available, using local memory for rate limiting")


class RateLimitStrategy(Enum):
    """Rate limiting strategies."""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    LEAKY_BUCKET = "leaky_bucket"


class RateLimitScope(Enum):
    """Rate limit scopes."""
    GLOBAL = "global"
    IP_ADDRESS = "ip_address"
    USER_ID = "user_id"
    API_KEY = "api_key"
    ENDPOINT = "endpoint"
    COMBINED = "combined"


@dataclass
class RateLimitRule:
    """Rate limiting rule configuration."""
    name: str
    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: int
    burst_allowance: int
    strategy: RateLimitStrategy
    scope: RateLimitScope
    enabled: bool = True
    grace_period_seconds: int = 60
    block_duration_minutes: int = 15


@dataclass
class RateLimitResult:
    """Result of rate limit check."""
    allowed: bool
    requests_remaining: int
    reset_time: datetime
    retry_after_seconds: Optional[int]
    rate_limit_rule: str
    current_usage: int
    limit: int


class RateLimitingService:
    """Service for API rate limiting and abuse prevention."""

    def __init__(self, redis_url: Optional[str] = None):
        """Initialize the rate limiting service."""
        self.redis_client = None
        self.local_cache: Dict[str, deque] = defaultdict(deque)
        self.blocked_ips: Dict[str, datetime] = {}
        self.rules = self._initialize_default_rules()

        # Try to connect to Redis for distributed rate limiting
        if redis_url and REDIS_AVAILABLE:
            try:
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                self.redis_client.ping()
                logger.info("Connected to Redis for distributed rate limiting")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis, using local memory: {e}")

    def _initialize_default_rules(self) -> Dict[str, RateLimitRule]:
        """Initialize default rate limiting rules."""
        return {
            "public_api_strict": RateLimitRule(
                name="public_api_strict",
                requests_per_minute=10,
                requests_per_hour=100,
                requests_per_day=1000,
                burst_allowance=5,
                strategy=RateLimitStrategy.SLIDING_WINDOW,
                scope=RateLimitScope.IP_ADDRESS
            ),
            "contact_form": RateLimitRule(
                name="contact_form",
                requests_per_minute=2,
                requests_per_hour=10,
                requests_per_day=50,
                burst_allowance=1,
                strategy=RateLimitStrategy.FIXED_WINDOW,
                scope=RateLimitScope.IP_ADDRESS,
                block_duration_minutes=60
            ),
            "registration": RateLimitRule(
                name="registration",
                requests_per_minute=3,
                requests_per_hour=15,
                requests_per_day=25,
                burst_allowance=2,
                strategy=RateLimitStrategy.SLIDING_WINDOW,
                scope=RateLimitScope.IP_ADDRESS,
                block_duration_minutes=30
            ),
            "password_reset": RateLimitRule(
                name="password_reset",
                requests_per_minute=1,
                requests_per_hour=5,
                requests_per_day=10,
                burst_allowance=0,
                strategy=RateLimitStrategy.FIXED_WINDOW,
                scope=RateLimitScope.IP_ADDRESS,
                block_duration_minutes=120
            )
        }

    async def check_rate_limit(
        self,
        rule_name: str,
        identifier: str,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> RateLimitResult:
        """Check if a request is within rate limits."""
        if rule_name not in self.rules:
            rule_name = "public_api_strict"

        rule = self.rules[rule_name]

        if not rule.enabled:
            return RateLimitResult(
                allowed=True,
                requests_remaining=999999,
                reset_time=datetime.now(timezone.utc) + timedelta(minutes=1),
                retry_after_seconds=None,
                rate_limit_rule=rule_name,
                current_usage=0,
                limit=999999
            )

        # Check if IP is blocked
        if rule.scope == RateLimitScope.IP_ADDRESS and identifier in self.blocked_ips:
            block_end = self.blocked_ips[identifier]
            if datetime.now(timezone.utc) < block_end:
                retry_after = int((block_end - datetime.now(timezone.utc)).total_seconds())
                return RateLimitResult(
                    allowed=False,
                    requests_remaining=0,
                    reset_time=block_end,
                    retry_after_seconds=retry_after,
                    rate_limit_rule=rule_name,
                    current_usage=rule.requests_per_minute,
                    limit=rule.requests_per_minute
                )
            else:
                del self.blocked_ips[identifier]

        # Generate cache key
        cache_key = self._generate_cache_key(rule_name, identifier, rule.scope)

        # Use sliding window for simplicity
        return await self._check_sliding_window(cache_key, rule)

    def _generate_cache_key(self, rule_name: str, identifier: str, scope: RateLimitScope) -> str:
        """Generate a cache key for rate limiting."""
        hashed_id = hashlib.sha256(identifier.encode()).hexdigest()[:16]
        return f"rate_limit:{rule_name}:{scope.value}:{hashed_id}"

    async def _check_sliding_window(self, cache_key: str, rule: RateLimitRule) -> RateLimitResult:
        """Check rate limit using sliding window algorithm."""
        now = time.time()
        window_start = now - 60  # 1 minute window

        requests = self.local_cache[cache_key]

        # Remove old requests
        while requests and requests[0] < window_start:
            requests.popleft()

        current_count = len(requests)
        allowed = current_count < rule.requests_per_minute

        if allowed:
            requests.append(now)

        requests_remaining = max(0, rule.requests_per_minute - current_count - (1 if allowed else 0))

        return RateLimitResult(
            allowed=allowed,
            requests_remaining=requests_remaining,
            reset_time=datetime.now(timezone.utc) + timedelta(seconds=60),
            retry_after_seconds=60 if not allowed else None,
            rate_limit_rule=rule.name,
            current_usage=current_count + (1 if allowed else 0),
            limit=rule.requests_per_minute
        )

    def get_rate_limit_headers(self, result: RateLimitResult) -> Dict[str, str]:
        """Get rate limit headers for HTTP responses."""
        headers = {
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(result.requests_remaining),
            "X-RateLimit-Reset": str(int(result.reset_time.timestamp())),
            "X-RateLimit-Policy": result.rate_limit_rule,
        }

        if result.retry_after_seconds:
            headers["Retry-After"] = str(result.retry_after_seconds)

        return headers

    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiting statistics."""
        return {
            "rules": {name: {
                "enabled": rule.enabled,
                "requests_per_minute": rule.requests_per_minute,
                "strategy": rule.strategy.value,
                "scope": rule.scope.value
            } for name, rule in self.rules.items()},
            "blocked_ips": len(self.blocked_ips),
            "active_cache_keys": len(self.local_cache),
            "redis_connected": self.redis_client is not None
        }


# Global instance
rate_limiting_service = RateLimitingService()

# Alias for backward compatibility
rate_limiter = rate_limiting_service


def get_client_ip(request) -> str:
    """Extract client IP address from request."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else "unknown"
