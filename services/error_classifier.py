"""
Error Classification Service - Bulletproof error handling and provider health tracking
"""

import re
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from core.settings import settings
from api.database import get_db

logger = logging.getLogger(__name__)

class ErrorClassifier:
    """Classify and handle provider errors with automatic cooldowns and retries"""
    
    # Error code taxonomy
    ERROR_CODES = {
        # Content/Data Errors
        'empty_results': {
            'description': 'Provider returned 0 mutuals',
            'action': 'Try other provider if available, else finish gracefully',
            'retry': True,
            'cooldown_hours': 0
        },
        'privacy_blocked': {
            'description': 'Connections hidden or profile private',
            'action': 'Show privacy message to user, stop processing',
            'retry': False,
            'cooldown_hours': 0
        },
        'invalid_url': {
            'description': 'Bad or vanity-only LinkedIn URL',
            'action': 'Ask for UI-generated connections_of_url',
            'retry': False,
            'cooldown_hours': 0
        },
        
        # Authentication/Session Errors
        'session_invalid': {
            'description': 'LinkedIn cookies expired or invalid',
            'action': 'Prompt re-connect to PhantomBuster extension',
            'retry': False,
            'cooldown_hours': 6
        },
        'captcha_required': {
            'description': 'LinkedIn detected automation, showing captcha',
            'action': 'Automatic 24h backoff, do not retry',
            'retry': False,
            'cooldown_hours': 24
        },
        
        # Rate Limiting
        'rate_limited': {
            'description': 'Provider throttling requests',
            'action': 'Backoff 1-3h, retry once after cooldown',
            'retry': True,
            'cooldown_hours': 2
        },
        'daily_limit_reached': {
            'description': 'LinkedIn daily action limit reached',
            'action': 'Wait until next day, do not retry today',
            'retry': False,
            'cooldown_hours': 12
        },
        
        # Technical Errors
        'api_error': {
            'description': 'Provider API returned error status',
            'action': 'Retry once after short delay',
            'retry': True,
            'cooldown_hours': 1
        },
        'configuration_missing': {
            'description': 'Provider credentials missing or incomplete',
            'action': 'Surface configuration guidance to administrators and skip automation until resolved',
            'retry': False,
            'cooldown_hours': 0
        },
        'network_timeout': {
            'description': 'Network connection timeout',
            'action': 'Retry once after delay',
            'retry': True,
            'cooldown_hours': 0.5
        },
        'unknown_error': {
            'description': 'Unclassified error occurred',
            'action': 'Log for analysis, retry once',
            'retry': True,
            'cooldown_hours': 1
        }
    }
    
    def classify_error(self, error_message: str, provider: str, status_code: int = None) -> Tuple[str, str]:
        """
        Classify error message into error code and user-friendly message
        
        Returns:
            Tuple of (error_code, user_message)
        """
        if not error_message:
            return 'unknown_error', 'An unknown error occurred'
        
        error_lower = error_message.lower()
        
        # Authentication/Session patterns
        if any(pattern in error_lower for pattern in [
            'session expired', 'invalid session', 'authentication failed',
            'login required', 'unauthorized', 'invalid credentials'
        ]):
            return 'session_invalid', 'LinkedIn session expired. Please reconnect your account.'
        
        # Captcha patterns
        if any(pattern in error_lower for pattern in [
            'captcha', 'security check', 'suspicious activity',
            'verify you are human', 'blocked for automation'
        ]):
            return 'captcha_required', 'LinkedIn security check triggered. Waiting 24h before retry.'
        
        # Rate limiting patterns
        if any(pattern in error_lower for pattern in [
            'rate limit', 'too many requests', 'throttled',
            'slow down', 'request limit exceeded'
        ]):
            return 'rate_limited', 'Request rate limit hit. Will retry in 2 hours.'
        
        # Daily limits
        if any(pattern in error_lower for pattern in [
            'daily limit', 'weekly limit', 'monthly limit',
            'reached your limit', 'limit exceeded today'
        ]):
            return 'daily_limit_reached', 'Daily LinkedIn limit reached. Will retry tomorrow.'
        
        # Privacy/Content patterns
        if any(pattern in error_lower for pattern in [
            'connections not visible', 'private profile', 'access denied',
            'profile not found', 'connections hidden'
        ]):
            return 'privacy_blocked', 'Profile connections are private or hidden.'
        
        # URL validation patterns
        if any(pattern in error_lower for pattern in [
            'invalid url', 'profile not found', 'vanity url',
            'url format error', 'linkedin.com/in/ required'
        ]):
            return 'invalid_url', 'LinkedIn URL format invalid. Please provide a valid profile URL.'
        
        # Empty results patterns  
        if any(pattern in error_lower for pattern in [
            'no results', 'empty dataset', '0 connections found',
            'no mutual connections', 'no data returned'
        ]):
            return 'empty_results', 'No mutual connections found for this profile.'
        
        # API/Technical errors
        if status_code and status_code >= 500:
            return 'api_error', f'{provider} service temporarily unavailable. Will retry shortly.'
        
        if any(pattern in error_lower for pattern in [
            'timeout', 'connection refused', 'network error',
            'dns error', 'connection timeout'
        ]):
            return 'network_timeout', 'Network connection timeout. Will retry shortly.'
        
        # HTTP status code mapping
        if status_code:
            if status_code == 401:
                return 'session_invalid', 'Authentication required. Please reconnect your account.'
            elif status_code == 403:
                return 'privacy_blocked', 'Access denied to this profile or resource.'
            elif status_code == 404:
                return 'invalid_url', 'Profile not found. Please check the LinkedIn URL.'
            elif status_code == 429:
                return 'rate_limited', 'Rate limit exceeded. Will retry in 2 hours.'
        
        # Default fallback
        return 'unknown_error', f'Unexpected error: {error_message[:100]}'
    
    def record_provider_error(self, provider: str, error_code: str, error_message: str, 
                            phantom_id: str = None, tenant_id: int = None) -> Dict:
        """
        Record provider error and apply cooldown if necessary
        
        Returns:
            Dict with cooldown info and retry recommendations
        """
        # Don't record database/application errors as provider health issues
        if error_code in ('0', 'database_error') or error_message in ('0', None) or any(
            db_error in str(error_message) for db_error in [
                'Database upsert failed', 'upsert returned no ID', 'RuntimeError',
                'constraint', 'duplicate key', 'relation does not exist'
            ]
        ):
            logger.info(f"Skipping provider health record for database/app error: {error_code} - {error_message}")
            return {
                'error_code': error_code,
                'description': 'Database or application error (not provider issue)',
                'action': 'Check application logs and database connectivity',
                'can_retry': True,
                'cooldown_until': None,
                'cooldown_hours': 0
            }
        
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            error_info = self.ERROR_CODES.get(error_code, self.ERROR_CODES['unknown_error'])
            cooldown_hours = error_info['cooldown_hours']
            
            # Calculate cooldown expiry
            cooldown_until = None
            if cooldown_hours > 0:
                cooldown_until = (datetime.now() + timedelta(hours=cooldown_hours)).isoformat()
            
            # Detect database type for proper syntax
            is_postgresql = (hasattr(conn, 'info') and 'postgresql' in str(type(conn)).lower()) or \
                           'Psycopg2Compat' in str(type(conn)) or \
                           hasattr(conn, '_conn') and hasattr(conn._conn, 'info')
            
            if is_postgresql:
                # PostgreSQL syntax with tenant_id for proper multi-tenant support
                cursor.execute('''
                    INSERT INTO provider_health (
                        tenant_id, provider, error_type, error_count, cooldown_until, last_error_at, updated_at
                    ) VALUES (%s, %s, %s, 1, %s, %s, %s)
                    ON CONFLICT(tenant_id, provider, error_type) DO UPDATE SET
                        error_count = provider_health.error_count + 1,
                        cooldown_until = EXCLUDED.cooldown_until,
                        last_error_at = EXCLUDED.last_error_at,
                        updated_at = EXCLUDED.updated_at
                ''', (
                    tenant_id, provider, error_code,
                    cooldown_until, datetime.now().isoformat(), datetime.now().isoformat()
                ))
            else:
                # SQLite syntax
                cursor.execute('''
                    INSERT OR REPLACE INTO provider_health (
                        tenant_id, provider, error_type, error_count, cooldown_until, last_error_at, updated_at
                    ) VALUES (?, ?, ?, 
                        COALESCE((SELECT error_count FROM provider_health WHERE tenant_id = ? AND provider = ? AND error_type = ?), 0) + 1,
                        ?, ?, ?)
                ''', (
                    tenant_id, provider, error_code, tenant_id, provider, error_code,
                    cooldown_until, datetime.now().isoformat(), datetime.now().isoformat()
                ))
            
            conn.commit()
            conn.close()
            
            logger.warning(f"Provider {provider} error: {error_code} - {error_message}")
            if cooldown_until:
                logger.info(f"Provider {provider} cooled down until {cooldown_until}")
            
            return {
                'error_code': error_code,
                'description': error_info['description'],
                'action': error_info['action'],
                'can_retry': error_info['retry'],
                'cooldown_until': cooldown_until,
                'cooldown_hours': cooldown_hours
            }
            
        except Exception as e:
            logger.error(f"Error recording provider error: {e}")
            return {
                'error_code': 'unknown_error',
                'description': 'Failed to record error',
                'can_retry': True,
                'cooldown_until': None
            }
    
    def record_provider_success(self, provider: str, phantom_id: str = None, tenant_id: int = None):
        """Record successful provider operation and reset error counts"""
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Detect database type for proper syntax
            is_postgresql = (hasattr(conn, 'info') and 'postgresql' in str(type(conn)).lower()) or \
                           'Psycopg2Compat' in str(type(conn)) or \
                           hasattr(conn, '_conn') and hasattr(conn._conn, 'info')
            
            param_placeholder = '%s' if is_postgresql else '?'
            
            # Reset error count for this provider/error_type combination
            cursor.execute(f'''
                UPDATE provider_health 
                SET error_count = 0, cooldown_until = NULL, updated_at = {param_placeholder}
                WHERE tenant_id = {param_placeholder} AND provider = {param_placeholder}
            ''', (datetime.now().isoformat(), tenant_id, provider))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Provider {provider} success recorded")
            
        except Exception as e:
            logger.error(f"Error recording provider success: {e}")
    
    def is_provider_healthy(self, provider: str, phantom_id: str = None, tenant_id: int = None) -> Dict:
        """
        Check if provider is healthy and available for use
        
        Returns:
            Dict with health status and availability info
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Detect database type for proper syntax
            is_postgresql = (hasattr(conn, 'info') and 'postgresql' in str(type(conn)).lower()) or \
                           'Psycopg2Compat' in str(type(conn)) or \
                           hasattr(conn, '_conn') and hasattr(conn._conn, 'info')
            
            param_placeholder = '%s' if is_postgresql else '?'
            
            cursor.execute(f'''
                SELECT error_count, cooldown_until, error_type
                FROM provider_health
                WHERE tenant_id = {param_placeholder} AND provider = {param_placeholder}
                ORDER BY updated_at DESC
                LIMIT 1
            ''', (tenant_id, provider))
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                # No health record = assume healthy
                return {
                    'is_healthy': True,
                    'status': 'healthy',
                    'can_use': True,
                    'cooldown_remaining': 0
                }
            
            error_count, cooldown_until, error_type = row
            
            # Check if cooldown expired
            cooldown_active = False
            cooldown_remaining = 0
            if cooldown_until:
                cooldown_dt = datetime.fromisoformat(cooldown_until)
                if datetime.now() < cooldown_dt:
                    cooldown_active = True
                    cooldown_remaining = (cooldown_dt - datetime.now()).total_seconds()
            
            # Determine status based on error count
            status = 'healthy'
            if error_count >= 3:
                status = 'unhealthy'
            elif error_count >= 1:
                status = 'degraded'
            
            return {
                'is_healthy': status == 'healthy',
                'status': status,
                'can_use': not cooldown_active and status != 'unhealthy',
                'error_count': error_count,
                'cooldown_remaining': cooldown_remaining,
                'last_error_code': error_type,
                'last_error_message': f"Provider {provider} has {error_count} errors"
            }
            
        except Exception as e:
            logger.error(f"Error checking provider health: {e}")
            return {
                'is_healthy': True,  # Assume healthy on error
                'status': 'unknown',
                'can_use': True,
                'cooldown_remaining': 0
            }
    
    def generate_user_message(self, error_code: str, provider: str) -> str:
        """Generate user-friendly error message with actionable suggestions"""
        error_info = self.ERROR_CODES.get(error_code, self.ERROR_CODES['unknown_error'])
        
        base_message = error_info['description']
        action = error_info['action']
        
        # Add provider-specific context
        provider_name = 'PhantomBuster' if provider == 'phantombuster' else 'Apify'
        
        if error_code == 'session_invalid':
            return f"🔐 LinkedIn session expired. Please reconnect your {provider_name} account in settings."
        elif error_code == 'captcha_required':
            return f"🛡️ LinkedIn security check detected. Taking a 24-hour break for safety."
        elif error_code == 'rate_limited':
            return f"⏳ Hit LinkedIn rate limits. Will retry automatically in 2 hours."
        elif error_code == 'privacy_blocked':
            return f"🔒 This profile's connections are private. Try using the 'Connections of' URL instead."
        elif error_code == 'empty_results':
            return f"📭 No mutual connections found. This person might be outside your network."
        elif error_code == 'invalid_url':
            return f"🔗 Invalid LinkedIn URL. Please provide a direct profile link (linkedin.com/in/username)."
        elif error_code == 'daily_limit_reached':
            return f"📊 Daily LinkedIn activity limit reached. Will resume tomorrow automatically."
        else:
            return f"⚠️ {base_message}. Our system will retry automatically."

# Global classifier instance
error_classifier = ErrorClassifier()
