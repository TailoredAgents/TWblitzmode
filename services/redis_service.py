#!/usr/bin/env python3
"""
Redis Service Integration
Provides caching and rate limiting capabilities
"""

import logging
import json
import asyncio
from typing import Any, Optional, Dict, List
from datetime import datetime, timedelta, timezone
import redis.asyncio as redis
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class RedisService:
    """
    Redis service for caching and rate limiting
    Supports both standalone and cluster configurations
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.client = None
        self.connection_pool = None
        self._is_connected = False

    async def initialize(self):
        """Initialize Redis connection with retry logic"""
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                # Create connection pool
                self.connection_pool = redis.ConnectionPool.from_url(
                    self.redis_url,
                    encoding='utf-8',
                    decode_responses=True,
                    max_connections=20,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )

                # Create Redis client
                self.client = redis.Redis(connection_pool=self.connection_pool)

                # Test connection
                await self.client.ping()
                self._is_connected = True

                logger.info(f"✅ Redis connected successfully to {self.redis_url}")
                return True

            except redis.ConnectionError as e:
                logger.warning(f"Redis connection attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2 ** attempt))
                else:
                    logger.error(f"❌ Redis connection failed after {max_retries} attempts")
                    self._is_connected = False
                    return False

            except Exception as e:
                logger.error(f"❌ Unexpected Redis initialization error: {e}")
                self._is_connected = False
                return False

    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected"""
        return self._is_connected and self.client is not None

    async def get(self, key: str) -> Optional[str]:
        """Get value from Redis"""
        if not self.is_connected:
            logger.warning("Redis not connected - cache miss")
            return None

        try:
            return await self.client.get(key)
        except Exception as e:
            logger.error(f"Redis GET error for key {key}: {e}")
            return None

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set value in Redis with optional TTL"""
        if not self.is_connected:
            logger.warning("Redis not connected - cache write skipped")
            return False

        try:
            if ttl:
                return await self.client.setex(key, ttl, value)
            else:
                return await self.client.set(key, value)
        except Exception as e:
            logger.error(f"Redis SET error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete key from Redis"""
        if not self.is_connected:
            return False

        try:
            result = await self.client.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis DELETE error for key {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not self.is_connected:
            return False

        try:
            return await self.client.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis EXISTS error for key {key}: {e}")
            return False

    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment key by amount"""
        if not self.is_connected:
            return None

        try:
            return await self.client.incrby(key, amount)
        except Exception as e:
            logger.error(f"Redis INCREMENT error for key {key}: {e}")
            return None

    async def expire(self, key: str, ttl: int) -> bool:
        """Set TTL for existing key"""
        if not self.is_connected:
            return False

        try:
            return await self.client.expire(key, ttl)
        except Exception as e:
            logger.error(f"Redis EXPIRE error for key {key}: {e}")
            return False

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Get JSON value from Redis"""
        value = await self.get(key)
        if value is None:
            return None

        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for key {key}: {e}")
            return None

    async def set_json(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """Set JSON value in Redis"""
        try:
            json_str = json.dumps(value, default=str)
            return await self.set(key, json_str, ttl)
        except TypeError as e:
            logger.error(f"JSON encode error for key {key}: {e}")
            return False

    async def rate_limit_check(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """
        Check rate limit using sliding window
        Returns (is_allowed, remaining_requests)
        """
        if not self.is_connected:
            # If Redis is down, allow the request but log warning
            logger.warning(f"Redis down - allowing rate limit for {key}")
            return True, limit - 1

        try:
            # Use Lua script for atomic rate limiting
            lua_script = """
            local key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local window = tonumber(ARGV[2])
            local current_time = tonumber(ARGV[3])

            -- Remove expired entries
            redis.call('zremrangebyscore', key, 0, current_time - window)

            -- Count current requests
            local current_count = redis.call('zcard', key)

            if current_count < limit then
                -- Add current request
                redis.call('zadd', key, current_time, current_time)
                redis.call('expire', key, window)
                return {1, limit - current_count - 1}
            else
                return {0, 0}
            end
            """

            current_time = datetime.now(timezone.utc).timestamp()
            result = await self.client.eval(
                lua_script, 1, key, limit, window, current_time
            )

            is_allowed = bool(result[0])
            remaining = int(result[1])

            return is_allowed, remaining

        except Exception as e:
            logger.error(f"Rate limit check error for key {key}: {e}")
            # On error, allow the request
            return True, limit - 1

    async def cache_linkedin_url(self, company: str, url: str, ttl: int = 86400):
        """Cache LinkedIn URL for company"""
        cache_key = f"linkedin_url:{company.lower().replace(' ', '_')}"
        cached_data = {
            "url": url,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "company": company
        }
        await self.set_json(cache_key, cached_data, ttl)

    async def get_cached_linkedin_url(self, company: str) -> Optional[str]:
        """Get cached LinkedIn URL for company"""
        cache_key = f"linkedin_url:{company.lower().replace(' ', '_')}"
        cached_data = await self.get_json(cache_key)

        if cached_data and "url" in cached_data:
            return cached_data["url"]
        return None

    async def cache_email_validation(self, email: str, is_valid: bool, details: Dict[str, Any], ttl: int = 3600):
        """Cache email validation result"""
        cache_key = f"email_validation:{email}"
        cached_data = {
            "is_valid": is_valid,
            "details": details,
            "validated_at": datetime.now(timezone.utc).isoformat()
        }
        await self.set_json(cache_key, cached_data, ttl)

    async def get_cached_email_validation(self, email: str) -> Optional[Dict[str, Any]]:
        """Get cached email validation result"""
        cache_key = f"email_validation:{email}"
        return await self.get_json(cache_key)

    async def cleanup_expired_keys(self, pattern: str = "*") -> int:
        """Clean up expired keys matching pattern"""
        if not self.is_connected:
            return 0

        try:
            # Note: In production, use SCAN instead of KEYS for large datasets
            keys = await self.client.keys(pattern)
            expired_count = 0

            for key in keys:
                ttl = await self.client.ttl(key)
                if ttl == -2:  # Key doesn't exist (expired)
                    expired_count += 1

            return expired_count

        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            return 0

    async def get_health_status(self) -> Dict[str, Any]:
        """Get Redis health status"""
        if not self.is_connected:
            return {
                "status": "disconnected",
                "connected": False,
                "error": "Not connected to Redis"
            }

        try:
            # Get Redis info
            info = await self.client.info()

            return {
                "status": "healthy",
                "connected": True,
                "redis_version": info.get("redis_version", "unknown"),
                "used_memory": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "uptime_in_seconds": info.get("uptime_in_seconds", 0)
            }

        except Exception as e:
            return {
                "status": "error",
                "connected": False,
                "error": str(e)
            }

    async def close(self):
        """Close Redis connection"""
        if self.client:
            await self.client.close()
        if self.connection_pool:
            await self.connection_pool.disconnect()

        self._is_connected = False
        logger.info("Redis connection closed")

# Global Redis instance
redis_service = RedisService()