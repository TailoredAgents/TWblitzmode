"""
Credential Migration Service - Corporate Schema Migration
Migrates legacy user_integrations and tenant_settings to new corporate schema
with enhanced encryption and organization-level integration sets.

This service handles the migration from per-user integrations to per-organization
integration sets with proper encryption and audit logging.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from .cookie_vault_service import CookieVaultService, VaultItemType
from .audit_logging_service import audit_logger, AuditEventType, AuditSeverity

logger = logging.getLogger(__name__)

@dataclass
class LegacyIntegration:
    """Legacy integration record from user_integrations or tenant_settings"""
    tenant_id: int
    user_id: Optional[int]  # None for tenant-level settings
    provider: str
    key_value: str
    is_encrypted: bool
    source_table: str  # 'user_integrations' or 'tenant_settings'

@dataclass
class MigrationResult:
    """Result of credential migration process"""
    total_processed: int
    migrated_to_vault: int
    migrated_to_integration_sets: int
    already_migrated: int
    failed_migrations: int
    errors: List[str]

class CredentialMigrationService:
    """Service for migrating credentials to corporate schema"""

    # Mapping of legacy provider names to new integration set fields
    PROVIDER_MAPPING = {
        'apify': 'apify_token_encrypted',
        'apify_token': 'apify_token_encrypted',
        'phantombuster': 'phantombuster_key_encrypted',
        'phantombuster_key': 'phantombuster_key_encrypted',
        'cufinder': 'cufinder_key_encrypted',
        'cufinder_api_key': 'cufinder_key_encrypted',
        'clearbit': 'clearbit_key_encrypted',
        'clearbit_api_key': 'clearbit_key_encrypted',
        'apollo': 'apollo_key_encrypted',
        'apollo_api_key': 'apollo_key_encrypted',
        'sendgrid': 'sendgrid_key_encrypted',
        'sendgrid_api_key': 'sendgrid_key_encrypted',
        'openai_api_key': 'feature_flags',  # Special handling for OpenAI
        'linkedin_li_at': 'vault',  # Migrate to cookie vault
        'linkedin_jsessionid': 'vault',  # Migrate to cookie vault
        'smtp_host': 'smtp_config_encrypted',
        'smtp_port': 'smtp_config_encrypted',
        'smtp_username': 'smtp_config_encrypted',
        'smtp_password': 'smtp_config_encrypted',
    }

    def __init__(self):
        self.vault_service = CookieVaultService()

    async def migrate_organization_credentials(self, organization_id: int) -> MigrationResult:
        """Migrate all credentials for an organization to the new corporate schema"""

        result = MigrationResult(
            total_processed=0,
            migrated_to_vault=0,
            migrated_to_integration_sets=0,
            already_migrated=0,
            failed_migrations=0,
            errors=[]
        )

        try:
            # Get legacy credentials
            legacy_credentials = await self._get_legacy_credentials(organization_id)
            result.total_processed = len(legacy_credentials)

            if not legacy_credentials:
                logger.info(f"No legacy credentials found for organization {organization_id}")
                return result

            # Check if integration_sets already exists for this organization
            integration_set = await self._get_or_create_integration_set(organization_id)

            # Process each credential
            for credential in legacy_credentials:
                try:
                    if credential.provider in ['linkedin_li_at', 'linkedin_jsessionid']:
                        # Migrate LinkedIn cookies to vault
                        await self._migrate_to_vault(credential, organization_id, result)
                    elif credential.provider.startswith('smtp_'):
                        # Aggregate SMTP settings
                        await self._migrate_smtp_settings(credential, organization_id, result)
                    else:
                        # Migrate to integration_sets
                        await self._migrate_to_integration_set(credential, organization_id, result)

                except Exception as e:
                    error_msg = f"Failed to migrate {credential.provider} for org {organization_id}: {str(e)}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)
                    result.failed_migrations += 1

            # Log audit event
            await audit_logger.log_event(
                organization_id=organization_id,
                actor_type="system",
                action="credential_migration",
                target_type="integration_set",
                target_id=integration_set['id'],
                payload={
                    "migrated_count": result.migrated_to_integration_sets + result.migrated_to_vault,
                    "total_processed": result.total_processed,
                    "errors": len(result.errors)
                },
                severity=AuditSeverity.INFO
            )

            logger.info(f"Migration completed for organization {organization_id}: {result}")
            return result

        except Exception as e:
            error_msg = f"Migration failed for organization {organization_id}: {str(e)}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            result.failed_migrations = result.total_processed
            return result

    async def _get_legacy_credentials(self, organization_id: int) -> List[LegacyIntegration]:
        """Get all legacy credentials for an organization"""

        credentials = []

        try:
            from ..api.db_core import get_conn, query

            with get_conn() as conn:
                # Get user integrations (using tenant_id as organization_id)
                user_integrations = query(conn, """
                    SELECT tenant_id, user_id, provider, key, encrypted
                    FROM user_integrations
                    WHERE tenant_id = ?
                """, (organization_id,))

                for row in user_integrations:
                    credentials.append(LegacyIntegration(
                        tenant_id=row['tenant_id'],
                        user_id=row['user_id'],
                        provider=row['provider'],
                        key_value=row['key'],
                        is_encrypted=bool(row['encrypted']),
                        source_table='user_integrations'
                    ))

                # Get tenant settings (using tenant_id as organization_id)
                tenant_settings = query(conn, """
                    SELECT tenant_id, setting_key, setting_value, encrypted
                    FROM tenant_settings
                    WHERE tenant_id = ?
                """, (organization_id,))

                for row in tenant_settings:
                    credentials.append(LegacyIntegration(
                        tenant_id=row['tenant_id'],
                        user_id=None,
                        provider=row['setting_key'],
                        key_value=row['setting_value'],
                        is_encrypted=bool(row['encrypted']),
                        source_table='tenant_settings'
                    ))

            logger.info(f"Found {len(credentials)} legacy credentials for organization {organization_id}")
            return credentials

        except Exception as e:
            logger.error(f"Failed to get legacy credentials for organization {organization_id}: {e}")
            return []

    async def _get_or_create_integration_set(self, organization_id: int) -> Dict[str, Any]:
        """Get existing integration set or create new one"""

        try:
            from ..api.db_core import get_conn, query, execute

            with get_conn() as conn:
                # Check if integration_sets table exists and has data for this org
                existing = query(conn, """
                    SELECT id, organization_id, feature_flags, quota_config, workflow_settings
                    FROM integration_sets
                    WHERE organization_id = ?
                """, (organization_id,))

                if existing:
                    return dict(existing[0])

                # Create new integration set
                integration_set_id = execute(conn, """
                    INSERT INTO integration_sets (
                        organization_id,
                        feature_flags,
                        quota_config,
                        workflow_settings,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (
                    organization_id,
                    json.dumps({"email_quota": 20, "auto_approval": False}),
                    json.dumps({"email_quota": 20, "prospects_per_day": 50}),
                    json.dumps({"schedule_window_start": "08:00", "schedule_window_end": "18:00"})
                ))

                return {
                    'id': integration_set_id,
                    'organization_id': organization_id,
                    'feature_flags': {"email_quota": 20, "auto_approval": False},
                    'quota_config': {"email_quota": 20, "prospects_per_day": 50},
                    'workflow_settings': {"schedule_window_start": "08:00", "schedule_window_end": "18:00"}
                }

        except Exception as e:
            logger.error(f"Failed to get/create integration set for organization {organization_id}: {e}")
            raise

    async def _migrate_to_vault(self, credential: LegacyIntegration, organization_id: int, result: MigrationResult):
        """Migrate LinkedIn cookies to cookie vault"""

        try:
            # Decrypt if encrypted
            key_value = credential.key_value
            if credential.is_encrypted:
                from ..api.security import dec
                key_value = dec(key_value)

            # Create vault item
            vault_data = {
                credential.provider: key_value,
                "created_from": "legacy_migration",
                "original_user_id": credential.user_id
            }

            # Determine team member ID (for now, use user_id as team_member_id)
            team_member_id = str(credential.user_id) if credential.user_id else "1"

            # Store in vault
            vault_item_id, encryption_key_id = await self.vault_service.encrypt_data(
                data=vault_data,
                tenant_id=str(organization_id),
                user_id=team_member_id,
                item_type=VaultItemType.LINKEDIN_COOKIE
            )

            # Store vault reference in cookie_jars table
            from ..api.db_core import get_conn, execute

            with get_conn() as conn:
                execute(conn, """
                    INSERT INTO cookie_jars (
                        organization_id, team_member_id, encrypted_cookies,
                        checksum, status, expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'active',
                        datetime('now', '+30 days'),
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (
                    organization_id,
                    int(team_member_id),
                    vault_item_id,
                    encryption_key_id[:64]  # Use first 64 chars as checksum
                ))

            result.migrated_to_vault += 1
            logger.info(f"Migrated {credential.provider} to vault for organization {organization_id}")

        except Exception as e:
            logger.error(f"Failed to migrate {credential.provider} to vault: {e}")
            raise

    async def _migrate_to_integration_set(self, credential: LegacyIntegration, organization_id: int, result: MigrationResult):
        """Migrate API keys to integration_sets table"""

        try:
            # Get field name mapping
            field_name = self.PROVIDER_MAPPING.get(credential.provider)
            if not field_name:
                logger.warning(f"No mapping found for provider: {credential.provider}")
                return

            # Decrypt if encrypted
            key_value = credential.key_value
            if credential.is_encrypted:
                from ..api.security import dec
                key_value = dec(key_value)

            # Re-encrypt with new encryption
            from ..api.security import enc
            encrypted_value = enc(key_value)

            # Update integration_sets
            from ..api.db_core import get_conn, execute

            with get_conn() as conn:
                # Dynamic SQL to update the specific field
                sql = f"""
                    UPDATE integration_sets
                    SET {field_name} = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = ?
                """
                execute(conn, sql, (encrypted_value, organization_id))

            result.migrated_to_integration_sets += 1
            logger.info(f"Migrated {credential.provider} to integration_sets for organization {organization_id}")

        except Exception as e:
            logger.error(f"Failed to migrate {credential.provider} to integration_sets: {e}")
            raise

    async def _migrate_smtp_settings(self, credential: LegacyIntegration, organization_id: int, result: MigrationResult):
        """Aggregate SMTP settings into single encrypted JSON field"""

        try:
            # Get all SMTP-related settings for this organization
            from ..api.db_core import get_conn, query, execute

            with get_conn() as conn:
                # Get current SMTP config if exists
                current_config = query(conn, """
                    SELECT smtp_config_encrypted FROM integration_sets
                    WHERE organization_id = ?
                """, (organization_id,))

                smtp_config = {}
                if current_config and current_config[0]['smtp_config_encrypted']:
                    try:
                        from ..api.security import dec
                        smtp_config = json.loads(dec(current_config[0]['smtp_config_encrypted']))
                    except:
                        smtp_config = {}

                # Add this setting to config
                setting_key = credential.provider.replace('smtp_', '')
                key_value = credential.key_value

                if credential.is_encrypted:
                    from ..api.security import dec
                    key_value = dec(key_value)

                smtp_config[setting_key] = key_value

                # Encrypt and store updated config
                from ..api.security import enc
                encrypted_config = enc(json.dumps(smtp_config))

                execute(conn, """
                    UPDATE integration_sets
                    SET smtp_config_encrypted = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = ?
                """, (encrypted_config, organization_id))

            result.migrated_to_integration_sets += 1
            logger.info(f"Migrated SMTP setting {credential.provider} for organization {organization_id}")

        except Exception as e:
            logger.error(f"Failed to migrate SMTP setting {credential.provider}: {e}")
            raise

    async def cleanup_legacy_credentials(self, organization_id: int, dry_run: bool = True) -> Dict[str, Any]:
        """Clean up legacy credential tables after successful migration"""

        cleanup_result = {
            "dry_run": dry_run,
            "user_integrations_deleted": 0,
            "tenant_settings_deleted": 0,
            "errors": []
        }

        try:
            from ..api.db_core import get_conn, execute, query

            if not dry_run:
                with get_conn() as conn:
                    # Delete user integrations
                    user_integrations_count = query(conn,
                        "SELECT COUNT(*) as count FROM user_integrations WHERE tenant_id = ?",
                        (organization_id,))[0]['count']

                    execute(conn, "DELETE FROM user_integrations WHERE tenant_id = ?", (organization_id,))
                    cleanup_result["user_integrations_deleted"] = user_integrations_count

                    # Delete tenant settings (keeping non-credential settings)
                    credential_keys = list(self.PROVIDER_MAPPING.keys())
                    placeholders = ','.join('?' * len(credential_keys))

                    tenant_settings_count = query(conn,
                        f"SELECT COUNT(*) as count FROM tenant_settings WHERE tenant_id = ? AND setting_key IN ({placeholders})",
                        [organization_id] + credential_keys)[0]['count']

                    execute(conn,
                        f"DELETE FROM tenant_settings WHERE tenant_id = ? AND setting_key IN ({placeholders})",
                        [organization_id] + credential_keys)

                    cleanup_result["tenant_settings_deleted"] = tenant_settings_count

                logger.info(f"Cleaned up legacy credentials for organization {organization_id}: {cleanup_result}")
            else:
                logger.info(f"Dry run: Would clean up credentials for organization {organization_id}")

            return cleanup_result

        except Exception as e:
            error_msg = f"Failed to cleanup legacy credentials for organization {organization_id}: {str(e)}"
            logger.error(error_msg)
            cleanup_result["errors"].append(error_msg)
            return cleanup_result

    async def migrate_all_organizations(self) -> Dict[str, Any]:
        """Migrate credentials for all organizations"""

        overall_result = {
            "organizations_processed": 0,
            "total_credentials_migrated": 0,
            "organizations_with_errors": 0,
            "detailed_results": []
        }

        try:
            from ..api.db_core import get_conn, query

            # Get all organization IDs (using tenant IDs as organization IDs)
            with get_conn() as conn:
                organizations = query(conn, "SELECT DISTINCT id FROM tenants ORDER BY id")

            for org_row in organizations:
                org_id = org_row['id']

                try:
                    logger.info(f"Starting migration for organization {org_id}")
                    result = await self.migrate_organization_credentials(org_id)

                    overall_result["organizations_processed"] += 1
                    overall_result["total_credentials_migrated"] += result.migrated_to_integration_sets + result.migrated_to_vault

                    if result.errors:
                        overall_result["organizations_with_errors"] += 1

                    overall_result["detailed_results"].append({
                        "organization_id": org_id,
                        "result": result
                    })

                except Exception as e:
                    logger.error(f"Failed to migrate organization {org_id}: {e}")
                    overall_result["organizations_with_errors"] += 1
                    overall_result["detailed_results"].append({
                        "organization_id": org_id,
                        "error": str(e)
                    })

            logger.info(f"Completed migration for all organizations: {overall_result}")
            return overall_result

        except Exception as e:
            logger.error(f"Failed to migrate all organizations: {e}")
            overall_result["error"] = str(e)
            return overall_result

# Global service instance
credential_migration_service = CredentialMigrationService()