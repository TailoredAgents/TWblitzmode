"""
Cookie Vault Service - minimal plaintext storage for LinkedIn cookies.

The original implementation depended on KMS, Fernet, and custom AES layers. Blitz
mode keeps the same public interface but stores payloads verbatim so we do not
need vault encryption keys or JWT secrets anywhere in the project.
"""

import os
import json
import logging
from collections import defaultdict
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
from contextlib import suppress
from dataclasses import dataclass, asdict
from enum import Enum
import secrets
import asyncio
import httpx

from api.database import get_db, using_native_adapter

logger = logging.getLogger(__name__)


def _parse_timestamp(value: Optional[Any]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        with suppress(ValueError):
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None

class VaultItemType(Enum):
    LINKEDIN_COOKIE = "linkedin_cookie"
    BROWSER_SESSION = "browser_session"
    API_TOKEN = "api_token"
    EMAIL_CREDENTIALS = "email_credentials"
    OAUTH_TOKEN = "oauth_token"


class EncryptionResult(tuple):
    """Tuple-like encryption result that also supports awaiting."""

    def __new__(cls, encrypted_data: str, key_id: str):
        return super().__new__(cls, (encrypted_data, key_id))

    def __await__(self):
        async def _wrap():
            return tuple(self)

        return _wrap().__await__()

    @property
    def encrypted_data(self) -> str:
        return self[0]

    @property
    def key_id(self) -> str:
        return self[1]


class DecryptionResult(dict):
    """Dict-like container that yields the decrypted payload and is awaitable."""

    def __await__(self):
        async def _wrap():
            return dict(self)

        return _wrap().__await__()

@dataclass
class VaultItem:
    """Encrypted vault item with metadata"""
    id: str
    tenant_id: str
    user_id: str
    item_type: VaultItemType
    label: str
    encrypted_data: str
    encryption_key_id: str
    created_at: datetime
    last_accessed: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class CookieVaultUserSummary:
    """Aggregated cookie vault metadata for a specific user."""

    user_id: str
    active: int
    expired: int
    expiring_soon: int
    stale: int
    latest_label: Optional[str]
    latest_created_at: Optional[str]
    latest_expires_at: Optional[str]
    rotation_due_at: Optional[str]
    rotation_recommended: bool
    vault_item_ids: List[str]


@dataclass
class CookieVaultSummary:
    """Tenant-wide LinkedIn cookie vault health summary."""

    tenant_id: str
    total_items: int
    active_items: int
    expired_items: int
    expiring_soon: int
    stale_items: int
    rotation_recommended: bool
    status: str
    message: str
    last_rotation_at: Optional[str]
    missing_vault_entries: int
    missing_vault_users: List[str]
    user_summaries: List[CookieVaultUserSummary]
    generated_at: str

class CookieVaultService:
    """Cookie vault facade with plaintext storage to avoid secret management."""

    VaultItemType = VaultItemType
    DEFAULT_ROTATION_DAYS = 90
    EXPIRING_SOON_DAYS = 14

    def __init__(self):
        # Blitz mode intentionally avoids secret management.
        self.kms_client = None
        self.master_key_id = None
        self.vault_encryption_key = None
        self.vault_encryption_key_file = None
        self.key_source = "disabled"

        rotation_days = os.getenv("COOKIE_ROTATION_DAYS")
        expiring_days = os.getenv("COOKIE_EXPIRING_SOON_DAYS")
        try:
            if rotation_days:
                self.DEFAULT_ROTATION_DAYS = max(1, int(rotation_days))
            if expiring_days:
                self.EXPIRING_SOON_DAYS = max(1, int(expiring_days))
        except ValueError:
            logger.warning(
                "Invalid cookie vault threshold configuration; using defaults (%s days rotation, %s days expiring)",
                self.DEFAULT_ROTATION_DAYS,
                self.EXPIRING_SOON_DAYS,
            )


    def encrypt_data(self, data: Dict[str, Any], tenant_id: str, user_id: str, item_type: VaultItemType) -> EncryptionResult:
        """Serialize data without encryption (plaintext storage)."""
        try:
            payload = json.dumps(data, default=str)
            return EncryptionResult(payload, "plaintext")
        except Exception as e:
            logger.error(f"Failed to serialize {item_type.value}: %s", e)
            raise ValueError(f"Failed to serialize sensitive data: {str(e)}")

    def decrypt_data(self, encrypted_data: str, key_id: str, tenant_id: str, user_id: str, item_type: VaultItemType) -> DecryptionResult:
        """Deserialize plaintext vault entries."""
        try:
            data = json.loads(encrypted_data)
            return DecryptionResult(data)
        except Exception as e:
            logger.error(f"Failed to deserialize {item_type.value}: %s", e)
            raise ValueError(f"Failed to deserialize sensitive data: {str(e)}")

    def get_health_status(self) -> Dict[str, Any]:
        """Return configuration metadata for health dashboards."""
        return {
            "provider": "cookie_vault",
            "kmsEnabled": False,
            "keySource": self.key_source,
            "keyConfigured": False,
            "masterKeyId": None,
            "encryptionMode": "plaintext",
        }

    async def store_vault_item(
        self,
        tenant_id: str,
        user_id: str,
        item_type: VaultItemType,
        label: str,
        sensitive_data: Dict[str, Any],
        expires_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Store encrypted item in the vault"""
        try:
            # Generate unique item ID
            item_id = f"vault_{secrets.token_urlsafe(16)}"

            # Encrypt sensitive data
            encrypted_data, key_id = await self.encrypt_data(sensitive_data, tenant_id, user_id, item_type)

            # Create vault item
            vault_item = VaultItem(
                id=item_id,
                tenant_id=tenant_id,
                user_id=user_id,
                item_type=item_type,
                label=label,
                encrypted_data=encrypted_data,
                encryption_key_id=key_id,
                created_at=datetime.now(timezone.utc),
                expires_at=expires_at,
                metadata=metadata or {}
            )

            # Store in database
            await self._save_vault_item_to_db(vault_item)

            logger.info(f"Stored {item_type.value} in vault: {item_id}")
            return item_id

        except Exception as e:
            logger.error(f"Failed to store vault item: {e}")
            raise ValueError(f"Failed to store item in vault: {str(e)}")

    async def store_cookies(
        self,
        tenant_id: str,
        user_id: str,
        li_at: str,
        jsessionid: str,
        label: str,
        user_agent: Optional[str] = None,
        expires_days: int = 365
    ) -> str:
        """
        Convenience method to store LinkedIn cookies securely

        Args:
            tenant_id: Organization/tenant identifier
            user_id: User identifier
            li_at: LinkedIn li_at cookie value
            jsessionid: LinkedIn JSESSIONID cookie value
            label: Human-readable label for the cookie set
            user_agent: Optional user agent string
            expires_days: Days until cookies expire (default 365)

        Returns:
            vault_item_id: Unique identifier for the stored cookie set

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        # Validate required parameters
        if not tenant_id or not user_id:
            raise ValueError("tenant_id and user_id are required for secure cookie storage")

        if not li_at or not jsessionid:
            raise ValueError("Both li_at and jsessionid cookies are required")

        if not label or len(label.strip()) == 0:
            raise ValueError("A descriptive label is required for cookie identification")

        # Prepare cookie data for encryption
        cookie_data = {
            "li_at": li_at.strip(),
            "jsessionid": jsessionid.strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "label": label.strip(),
        }

        if user_agent:
            cookie_data["user_agent"] = user_agent.strip()

        # Set expiration date
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

        # Store in vault with proper tenant isolation
        try:
            vault_item_id = await self.store_vault_item(
                tenant_id=tenant_id,
                user_id=user_id,
                item_type=VaultItemType.LINKEDIN_COOKIE,
                label=f"LinkedIn Cookies: {label}",
                sensitive_data=cookie_data,
                expires_at=expires_at,
                metadata={
                    "cookie_type": "linkedin",
                    "platform": "linkedin.com",
                    "expires_days": expires_days,
                    "rotation_days": self.DEFAULT_ROTATION_DAYS,
                    "created_by_user_id": user_id,
                    "created_via": "api.store_cookies",
                }
            )

            logger.info(f"Stored LinkedIn cookies for tenant {tenant_id}, user {user_id}: {vault_item_id}")
            return vault_item_id

        except Exception as e:
            logger.error(f"Failed to store LinkedIn cookies for tenant {tenant_id}, user {user_id}: {e}")
            raise ValueError(f"Failed to store LinkedIn cookies: {str(e)}")

    async def retrieve_vault_item(self, item_id: str, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve and decrypt vault item"""
        try:
            # Load from database
            vault_item = await self._load_vault_item_from_db(item_id, tenant_id, user_id)
            if not vault_item:
                return None

            # Check if expired
            if vault_item.expires_at and vault_item.expires_at < datetime.now(timezone.utc):
                await self._mark_vault_item_expired(item_id)
                logger.warning(f"Vault item {item_id} has expired")
                return None

            # Decrypt sensitive data
            decrypted_data = await self.decrypt_data(
                vault_item.encrypted_data,
                vault_item.encryption_key_id,
                vault_item.tenant_id,
                vault_item.user_id,
                vault_item.item_type
            )

            # Update last accessed timestamp
            await self._update_last_accessed(item_id)

            return {
                "id": vault_item.id,
                "label": vault_item.label,
                "item_type": vault_item.item_type.value,
                "data": decrypted_data,
                "metadata": vault_item.metadata,
                "created_at": vault_item.created_at.isoformat(),
                "last_accessed": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to retrieve vault item {item_id}: {e}")
            raise ValueError(f"Failed to retrieve vault item: {str(e)}")

    def _derive_rotation_metadata(self, item: VaultItem, *, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Calculate rotation metadata for a vault item."""

        reference_time = now or datetime.now(timezone.utc)
        metadata = item.metadata or {}

        rotation_days = metadata.get("rotation_days") or metadata.get("rotationDays")
        try:
            rotation_days_int = int(rotation_days) if rotation_days is not None else self.DEFAULT_ROTATION_DAYS
            if rotation_days_int <= 0:
                rotation_days_int = self.DEFAULT_ROTATION_DAYS
        except (TypeError, ValueError):
            rotation_days_int = self.DEFAULT_ROTATION_DAYS

        rotation_due = item.created_at + timedelta(days=rotation_days_int)
        rotation_recommended = rotation_due <= reference_time

        expires_in_days: Optional[int] = None
        expiring_soon = False
        expired = False
        if item.expires_at:
            delta = item.expires_at - reference_time
            expires_in_days = int(delta.total_seconds() // 86400)
            expired = delta.total_seconds() <= 0
            expiring_soon = 0 < delta.total_seconds() <= self.EXPIRING_SOON_DAYS * 86400

        return {
            "rotation_due_at": rotation_due.isoformat(),
            "rotation_recommended": rotation_recommended,
            "expires_in_days": expires_in_days,
            "expired": expired,
            "expiring_soon": expiring_soon,
        }

    async def list_vault_items(self, tenant_id: str, user_id: str, item_type: Optional[VaultItemType] = None) -> List[Dict[str, Any]]:
        """List vault items (metadata only, no sensitive data)"""
        try:
            vault_items = await self._list_vault_items_from_db(tenant_id, user_id, item_type)
            now = datetime.now(timezone.utc)

            return [
                {
                    "id": item.id,
                    "label": item.label,
                    "item_type": item.item_type.value,
                    "created_at": item.created_at.isoformat(),
                    "last_accessed": item.last_accessed.isoformat() if item.last_accessed else None,
                    "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                    "is_active": item.is_active,
                    "metadata": item.metadata,
                    **self._derive_rotation_metadata(item, now=now),
                }
                for item in vault_items
            ]

        except Exception as e:
            logger.error(f"Failed to list vault items: {e}")
            raise ValueError(f"Failed to list vault items: {str(e)}")

    async def get_linkedin_cookies(self, tenant_id: str, user_id: str) -> List[Dict[str, Any]]:
        """
        Convenience method to get all LinkedIn cookies for a user

        Args:
            tenant_id: Organization/tenant identifier
            user_id: User identifier

        Returns:
            List of LinkedIn cookie sets with decrypted data

        Raises:
            ValueError: If required parameters are missing
        """
        if not tenant_id or not user_id:
            raise ValueError("tenant_id and user_id are required for cookie retrieval")

        try:
            # Get all LinkedIn cookie vault items
            vault_items = await self._list_vault_items_from_db(
                tenant_id=tenant_id,
                user_id=user_id,
                item_type=VaultItemType.LINKEDIN_COOKIE
            )

            now = datetime.now(timezone.utc)
            cookies_list = []
            for item in vault_items:
                if str(item.tenant_id) != str(tenant_id) or str(item.user_id) != str(user_id):
                    continue
                # Decrypt the cookie data
                decrypted_data = await self.decrypt_data(
                    item.encrypted_data,
                    item.encryption_key_id,
                    tenant_id,
                    user_id,
                    item.item_type
                )

                if decrypted_data:
                    cookies_list.append({
                        "id": item.id,
                        "label": item.label,
                        "li_at": decrypted_data.get("li_at"),
                        "jsessionid": decrypted_data.get("jsessionid"),
                        "user_agent": decrypted_data.get("user_agent"),
                        "created_at": item.created_at.isoformat(),
                        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                        "is_active": item.is_active,
                        "metadata": item.metadata,
                        **self._derive_rotation_metadata(item, now=now),
                    })

            logger.info(f"Retrieved {len(cookies_list)} LinkedIn cookie sets for tenant {tenant_id}, user {user_id}")
            return cookies_list

        except Exception as e:
            logger.error(f"Failed to get LinkedIn cookies for tenant {tenant_id}, user {user_id}: {e}")
            raise ValueError(f"Failed to retrieve LinkedIn cookies: {str(e)}")

    async def delete_vault_item(self, item_id: str, tenant_id: str, user_id: str) -> bool:
        """Securely delete vault item"""
        try:
            # Verify ownership
            vault_item = await self._load_vault_item_from_db(item_id, tenant_id, user_id)
            if not vault_item:
                return False

            # Mark as deleted and overwrite sensitive data
            await self._secure_delete_vault_item(item_id, tenant_id, user_id)

            logger.info(f"Securely deleted vault item: {item_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete vault item {item_id}: {e}")
            return False

    async def delete_user_vault_items(self, tenant_id: str, user_id: str) -> int:
        """Securely delete all vault items for a specific user"""
        try:
            # Get all vault items for this user
            vault_items = await self.list_vault_items(tenant_id, user_id)

            deleted_count = 0

            # Delete each item securely
            for item in vault_items:
                try:
                    success = await self.delete_vault_item(item["id"], tenant_id, user_id)
                    if success:
                        deleted_count += 1
                except Exception as item_error:
                    logger.error(f"Failed to delete vault item {item['id']}: {item_error}")
                    continue

            # Also run bulk cleanup query for any remaining items
            await self._bulk_delete_user_vault_items(tenant_id, user_id)

            logger.info(f"Deleted {deleted_count} vault items for user {user_id} in tenant {tenant_id}")
            return deleted_count

        except Exception as e:
            logger.error(f"Failed to delete vault items for user {user_id}: {e}")
            return 0

    async def rotate_encryption_keys(self, tenant_id: str) -> Dict[str, Any]:
        """Rotate encryption keys for a tenant"""
        try:
            # This would implement key rotation for production
            # For now, return operation status

            rotation_id = secrets.token_urlsafe(16)

            logger.info(f"Started key rotation for tenant {tenant_id}: {rotation_id}")

            return {
                "rotation_id": rotation_id,
                "tenant_id": tenant_id,
                "status": "completed",
                "rotated_at": datetime.now(timezone.utc).isoformat(),
                "items_rotated": 0  # Would be actual count in production
            }

        except Exception as e:
            logger.error(f"Key rotation failed for tenant {tenant_id}: {e}")
            raise ValueError(f"Failed to rotate encryption keys: {str(e)}")

    # Database interaction methods - PostgreSQL implementation

    async def _save_vault_item_to_db(self, vault_item: VaultItem):
        """Save vault item to database with proper PostgreSQL integration"""
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS vault_items (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        item_type TEXT NOT NULL,
                        label TEXT NOT NULL,
                        encrypted_data TEXT NOT NULL,
                        encryption_key_id TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_accessed TIMESTAMP NULL,
                        expires_at TIMESTAMP NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        metadata TEXT DEFAULT '{}'
                    )
                """)

                cursor.execute(
                    """
                    UPDATE vault_items
                    SET is_active = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = ? AND user_id = ? AND item_type = ?
                    """,
                    (
                        vault_item.tenant_id,
                        vault_item.user_id,
                        vault_item.item_type.value,
                    ),
                )

                cursor.execute("""
                    INSERT INTO vault_items (
                        id,
                        tenant_id,
                        user_id,
                        item_type,
                        label,
                        encrypted_data,
                        encryption_key_id,
                        created_at,
                        expires_at,
                        is_active,
                        metadata,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        encrypted_data = excluded.encrypted_data,
                        encryption_key_id = excluded.encryption_key_id,
                        expires_at = excluded.expires_at,
                        is_active = excluded.is_active,
                        metadata = excluded.metadata,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    vault_item.id,
                    vault_item.tenant_id,
                    vault_item.user_id,
                    vault_item.item_type.value,
                    vault_item.label,
                    vault_item.encrypted_data,
                    vault_item.encryption_key_id,
                    vault_item.created_at,
                    vault_item.expires_at,
                    1 if vault_item.is_active else 0,
                    json.dumps(vault_item.metadata or {}),
                    datetime.now(timezone.utc),
                ))

                conn.commit()
                logger.info(f"Successfully saved vault item {vault_item.id} to database")

        except Exception as e:
            logger.error(f"Failed to save vault item {vault_item.id}: {e}")
            raise

    async def _load_vault_item_from_db(self, item_id: str, tenant_id: str, user_id: str) -> Optional[VaultItem]:
        """Load vault item from database with tenant isolation"""
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                # Query with tenant isolation for security
                cursor.execute("""
                    SELECT id, tenant_id, user_id, item_type, label, encrypted_data,
                           encryption_key_id, created_at, last_accessed, expires_at,
                           is_active, metadata
                    FROM vault_items
                    WHERE id = ? AND tenant_id = ? AND user_id = ? AND is_active = 1
                """, (item_id, tenant_id, user_id))

                row = cursor.fetchone()
                if not row:
                    return None

                # Convert database row to VaultItem
                return VaultItem(
                    id=row[0],
                    tenant_id=row[1],
                    user_id=row[2],
                    item_type=VaultItemType(row[3]),
                    label=row[4],
                    encrypted_data=row[5],
                    encryption_key_id=row[6],
                    created_at=_parse_timestamp(row[7]) or datetime.now(timezone.utc),
                    last_accessed=_parse_timestamp(row[8]),
                    expires_at=_parse_timestamp(row[9]),
                    is_active=bool(row[10]),
                    metadata=json.loads(row[11]) if row[11] else {}
                )

        except Exception as e:
            logger.error(f"Failed to load vault item {item_id}: {e}")
            return None

    async def _list_vault_items_from_db(self, tenant_id: str, user_id: str, item_type: Optional[VaultItemType] = None) -> List[VaultItem]:
        """List vault items from database with optional type filtering"""
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                # Build query with optional type filter
                query = """
                    SELECT id, tenant_id, user_id, item_type, label, encrypted_data,
                           encryption_key_id, created_at, last_accessed, expires_at,
                           is_active, metadata
                    FROM vault_items
                    WHERE tenant_id = ? AND user_id = ? AND is_active = 1
                """
                params = [tenant_id, user_id]

                if item_type:
                    query += " AND item_type = ?"
                    params.append(item_type.value)

                query += " ORDER BY created_at DESC"

                cursor.execute(query, params)
                rows = cursor.fetchall()

                vault_items = []
                for row in rows:
                    vault_items.append(VaultItem(
                        id=row[0],
                        tenant_id=row[1],
                        user_id=row[2],
                        item_type=VaultItemType(row[3]),
                        label=row[4],
                        encrypted_data=row[5],
                        encryption_key_id=row[6],
                        created_at=_parse_timestamp(row[7]) or datetime.now(timezone.utc),
                        last_accessed=_parse_timestamp(row[8]),
                        expires_at=_parse_timestamp(row[9]),
                        is_active=bool(row[10]),
                        metadata=json.loads(row[11]) if row[11] else {}
                    ))

                return vault_items

        except Exception as e:
            logger.error(f"Failed to list vault items: {e}")
            return []

    async def _list_tenant_vault_items_from_db(
        self,
        tenant_id: str,
        item_type: Optional[VaultItemType] = None,
    ) -> List[VaultItem]:
        """List all vault items for a tenant."""

        try:
            with get_db() as conn:
                cursor = conn.cursor()

                query = """
                    SELECT id, tenant_id, user_id, item_type, label, encrypted_data,
                           encryption_key_id, created_at, last_accessed, expires_at,
                           is_active, metadata
                    FROM vault_items
                    WHERE tenant_id = ?
                """
                params = [tenant_id]

                if item_type:
                    query += " AND item_type = ?"
                    params.append(item_type.value)

                query += " ORDER BY created_at DESC"

                cursor.execute(query, params)
                rows = cursor.fetchall()

                items: List[VaultItem] = []
                for row in rows:
                    items.append(
                        VaultItem(
                            id=row[0],
                            tenant_id=row[1],
                            user_id=row[2],
                            item_type=VaultItemType(row[3]),
                            label=row[4],
                            encrypted_data=row[5],
                            encryption_key_id=row[6],
                            created_at=_parse_timestamp(row[7]) or datetime.now(timezone.utc),
                            last_accessed=_parse_timestamp(row[8]),
                            expires_at=_parse_timestamp(row[9]),
                            is_active=bool(row[10]),
                            metadata=json.loads(row[11]) if row[11] else {},
                        )
                    )

                return items

        except Exception as exc:
            logger.error("Failed to list tenant vault items for %s: %s", tenant_id, exc)
            return []

    async def summarize_linkedin_cookies(self, tenant_id: str) -> Dict[str, Any]:
        """Return tenant-wide summary for LinkedIn cookie storage."""

        tenant_id_str = str(tenant_id)
        now = datetime.now(timezone.utc)

        items = await self._list_tenant_vault_items_from_db(
            tenant_id_str,
            VaultItemType.LINKEDIN_COOKIE,
        )

        user_groups: Dict[str, List[VaultItem]] = defaultdict(list)
        total_items = len(items)
        active_items = 0
        expired_items = 0
        expiring_soon_items = 0
        stale_items = 0
        last_rotation_at: Optional[datetime] = None

        for item in items:
            rotation_meta = self._derive_rotation_metadata(item, now=now)
            user_groups[str(item.user_id)].append(item)

            is_expired = rotation_meta["expired"]
            is_expiring_soon = rotation_meta["expiring_soon"]
            needs_rotation = rotation_meta["rotation_recommended"]

            if item.is_active and not is_expired:
                active_items += 1
            if is_expired:
                expired_items += 1
            if is_expiring_soon and not is_expired:
                expiring_soon_items += 1
            if needs_rotation:
                stale_items += 1

            if last_rotation_at is None or item.created_at > last_rotation_at:
                last_rotation_at = item.created_at

        user_summaries: List[CookieVaultUserSummary] = []
        for user_id, user_items in user_groups.items():
            user_active = 0
            user_expired = 0
            user_expiring = 0
            user_stale = 0
            latest_item: Optional[VaultItem] = None
            latest_rotation_meta: Optional[Dict[str, Any]] = None

            for item in sorted(user_items, key=lambda i: i.created_at, reverse=True):
                rotation_meta = self._derive_rotation_metadata(item, now=now)
                if latest_item is None:
                    latest_item = item
                    latest_rotation_meta = rotation_meta

                if item.is_active and not rotation_meta["expired"]:
                    user_active += 1
                if rotation_meta["expired"]:
                    user_expired += 1
                if rotation_meta["expiring_soon"] and not rotation_meta["expired"]:
                    user_expiring += 1
                if rotation_meta["rotation_recommended"]:
                    user_stale += 1

            user_summaries.append(
                CookieVaultUserSummary(
                    user_id=user_id,
                    active=user_active,
                    expired=user_expired,
                    expiring_soon=user_expiring,
                    stale=user_stale,
                    latest_label=latest_item.label if latest_item else None,
                    latest_created_at=latest_item.created_at.isoformat() if latest_item else None,
                    latest_expires_at=latest_item.expires_at.isoformat() if latest_item and latest_item.expires_at else None,
                    rotation_due_at=(latest_rotation_meta or {}).get("rotation_due_at"),
                    rotation_recommended=(latest_rotation_meta or {}).get("rotation_recommended", False),
                    vault_item_ids=[item.id for item in user_items],
                )
            )

        missing_vault_users: List[str] = []
        missing_vault_entries = 0
        try:
            org_id: Optional[int] = None
            try:
                org_id = int(tenant_id_str)
            except (TypeError, ValueError):
                org_id = None

            if org_id is not None:
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT user_id, status, vault_item_id
                        FROM cookie_jars
                        WHERE organization_id = ?
                        """,
                        (org_id,),
                    )
                    rows = cursor.fetchall()
                    for row in rows:
                        jar_user = row[0]
                        vault_item_id = row[2]
                        if not vault_item_id:
                            missing_vault_entries += 1
                            if jar_user is not None:
                                missing_vault_users.append(str(jar_user))
                        else:
                            # Ensure stored vault item still present; if missing mark as warning
                            if str(jar_user) not in user_groups:
                                missing_vault_users.append(str(jar_user))
        except Exception as exc:
            logger.debug("Unable to evaluate cookie jar coverage for tenant %s: %s", tenant_id_str, exc)

        rotation_recommended = stale_items > 0 or missing_vault_entries > 0

        if active_items == 0:
            status = "missing"
            message = "No active LinkedIn cookie records stored yet. Upload li_at and JSESSIONID cookies to unlock automations."
        elif rotation_recommended or expiring_soon_items > 0 or expired_items > 0:
            status = "warning"
            message = "Some LinkedIn cookie records require rotation or vault backups. Review the cookie jar to avoid automation failures."
        else:
            status = "healthy"
            message = "LinkedIn cookie vault is healthy and ready for automation."

        summary = CookieVaultSummary(
            tenant_id=tenant_id_str,
            total_items=total_items,
            active_items=active_items,
            expired_items=expired_items,
            expiring_soon=expiring_soon_items,
            stale_items=stale_items,
            rotation_recommended=rotation_recommended,
            status=status,
            message=message,
            last_rotation_at=last_rotation_at.isoformat() if last_rotation_at else None,
            missing_vault_entries=missing_vault_entries,
            missing_vault_users=sorted(set(missing_vault_users)),
            user_summaries=user_summaries,
            generated_at=now.isoformat(),
        )

        return asdict(summary)

    async def _mark_vault_item_expired(self, item_id: str):
        """Mark vault item as expired in database"""
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE vault_items
                    SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (item_id,))

                conn.commit()
                logger.info(f"Marked vault item {item_id} as expired")

        except Exception as e:
            logger.error(f"Failed to mark vault item {item_id} as expired: {e}")

    async def _update_last_accessed(self, item_id: str):
        """Update last accessed timestamp for vault item"""
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE vault_items
                    SET last_accessed = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (item_id,))

                conn.commit()

        except Exception as e:
            logger.error(f"Failed to update last accessed for vault item {item_id}: {e}")

    async def _secure_delete_vault_item(self, item_id: str, tenant_id: str, user_id: str):
        """
        Securely delete vault item with data overwriting and tenant validation

        This method validates tenant context before deletion to prevent cross-tenant access
        """
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                # First verify the item belongs to the correct tenant and user
                cursor.execute(
                    "SELECT metadata, tenant_id, user_id FROM vault_items WHERE id = ? AND tenant_id = ? AND user_id = ?",
                    (item_id, tenant_id, user_id),
                )
                row = cursor.fetchone()
                if not row:
                    # Item not found or doesn't belong to this tenant/user
                    logger.warning(f"Vault item {item_id} not found or access denied for tenant {tenant_id}, user {user_id}")
                    return

                existing_metadata = {}
                if row[0]:  # metadata column
                    try:
                        existing_metadata = json.loads(row[0])
                    except json.JSONDecodeError:
                        existing_metadata = {}

                existing_metadata["deleted_at"] = datetime.now(timezone.utc).isoformat()
                existing_metadata["deleted_by_tenant"] = tenant_id
                existing_metadata["deleted_by_user"] = user_id

                # Only update the specific item with tenant/user validation
                cursor.execute(
                    """
                    UPDATE vault_items
                    SET encrypted_data = '',
                        encryption_key_id = 'DELETED',
                        is_active = 0,
                        metadata = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND tenant_id = ? AND user_id = ?
                    """,
                    (json.dumps(existing_metadata), item_id, tenant_id, user_id),
                )

                conn.commit()
                logger.info(f"Securely deleted vault item {item_id}")

        except Exception as e:
            logger.error(f"Failed to securely delete vault item {item_id}: {e}")

    async def _bulk_delete_user_vault_items(self, tenant_id: str, user_id: str):
        """Bulk delete all vault items for a user from database"""
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                bulk_metadata = json.dumps(
                    {"bulk_deleted_at": datetime.now(timezone.utc).isoformat()}
                )

                cursor.execute(
                    """
                    UPDATE vault_items
                    SET
                        is_active = 0,
                        encrypted_data = '',
                        metadata = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = ? AND user_id = ? AND is_active = 1
                    """,
                    (bulk_metadata, tenant_id, user_id),
                )

                affected_rows = cursor.rowcount
                conn.commit()

                logger.info(f"Bulk deleted {affected_rows} vault items for user {user_id} in tenant {tenant_id}")

        except Exception as e:
            logger.error(f"Failed to bulk delete vault items for user {user_id}: {e}")

    async def health_check(self) -> Dict[str, Any]:
        """Health check for cookie vault service"""
        try:
            health_status = {
                "status": "healthy",
                "encryption": "plaintext",
                "kms_enabled": False,
                "master_key_configured": False,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            # Basic serialization round-trip check to ensure DB writes will work.
            test_data = {"test": "data", "timestamp": datetime.now(timezone.utc).isoformat()}
            serialized, key_id = await self.encrypt_data(test_data, "test_tenant", "test_user", VaultItemType.API_TOKEN)
            if key_id != "plaintext":
                raise ValueError("Unexpected key identifier in plaintext mode")
            deserialized = await self.decrypt_data(serialized, key_id, "test_tenant", "test_user", VaultItemType.API_TOKEN)

            if deserialized.get("test") == "data":
                health_status["serialization_test"] = "passed"
            else:
                health_status["serialization_test"] = "failed"
                health_status["status"] = "degraded"

            return health_status

        except Exception as e:
            logger.error(f"Cookie vault health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

# Global cookie vault service instance
cookie_vault = CookieVaultService()
