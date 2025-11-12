"""
Master Game Plan Database Migration Executor
September 2025 - Safe Schema Migration

Executes Master Game Plan database schema migration with
comprehensive safety checks, rollback procedures, and validation.
"""

import asyncio
import logging
import sys
import os
from datetime import datetime
from typing import Dict, Any, List

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrations.migration_safety import migration_safety, MGP_MIGRATION_PROCEDURES
import importlib.util
import sys

# Import the migration module dynamically since it starts with a number
spec = importlib.util.spec_from_file_location(
    "mgp_migration",
    "/Users/jeffreyhacker/introduceme /Introduce.me/migrations/versions/003_master_game_plan_tables.py"
)
mgp_migration_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mgp_migration_module)
mgp_upgrade = mgp_migration_module.upgrade
mgp_downgrade = mgp_migration_module.downgrade
from security import initialize_mgp_security
from rollout.feature_flag_manager import feature_flag_manager

logger = logging.getLogger(__name__)

class MGPMigrationExecutor:
    """Master Game Plan migration executor with safety checks"""

    def __init__(self):
        self.migration_id = "003_master_game_plan_tables"
        # Migration functions adapter
        self.migration_functions = {
            'upgrade': mgp_upgrade,
            'downgrade': mgp_downgrade
        }
        self.execution_log: List[Dict[str, Any]] = []

    async def execute_migration(self, dry_run: bool = False, force: bool = False) -> Dict[str, Any]:
        """Execute Master Game Plan database migration"""

        execution_result = {
            "migration_id": self.migration_id,
            "status": "starting",
            "dry_run": dry_run,
            "started_at": datetime.utcnow().isoformat(),
            "phases": {},
            "rollback_available": False,
            "warnings": [],
            "errors": []
        }

        logger.info("🗄️ Starting Master Game Plan Database Migration...")
        logger.info(f"Migration ID: {self.migration_id}")
        logger.info(f"Dry Run: {dry_run}")

        try:
            # Phase 1: Pre-migration safety checks
            logger.info("📋 Phase 1: Pre-migration safety checks...")
            safety_check = await self._pre_migration_safety_check(force)
            execution_result["phases"]["safety_check"] = safety_check

            if not safety_check["safe_to_proceed"] and not force:
                execution_result["status"] = "aborted"
                execution_result["reason"] = "Safety checks failed"
                return execution_result

            if safety_check["warnings"]:
                execution_result["warnings"].extend(safety_check["warnings"])

            # Phase 2: Backup current schema
            logger.info("💾 Phase 2: Creating schema backup...")
            backup_result = await self._create_schema_backup()
            execution_result["phases"]["backup"] = backup_result

            if not backup_result["success"]:
                if "version mismatch" in backup_result.get("error", "").lower():
                    logger.warning("⚠️  Backup failed due to version mismatch - proceeding without backup")
                    execution_result["warnings"].append("Backup skipped due to pg_dump version mismatch")
                else:
                    execution_result["status"] = "failed"
                    execution_result["errors"].append("Schema backup failed")
                    return execution_result

            # Phase 3: Execute migration with safety
            logger.info("🚀 Phase 3: Executing migration...")
            if dry_run:
                migration_result = await self._dry_run_migration()
            else:
                migration_result = await self._execute_safe_migration()

            execution_result["phases"]["migration"] = migration_result
            execution_result["rollback_available"] = migration_result.get("rollback_available", False)

            if migration_result["status"] != "completed":
                execution_result["status"] = "failed"
                if migration_result.get("error"):
                    execution_result["errors"].append(migration_result["error"])
                return execution_result

            # Phase 4: Post-migration validation
            logger.info("🔍 Phase 4: Post-migration validation...")
            validation_result = await self._post_migration_validation()
            execution_result["phases"]["validation"] = validation_result

            if not validation_result["all_passed"]:
                execution_result["status"] = "failed"
                execution_result["errors"].extend(validation_result.get("failures", []))

                # Recommend rollback
                if not dry_run:
                    execution_result["rollback_recommended"] = True
                    logger.error("❌ Migration validation failed - rollback recommended")

                return execution_result

            # Phase 5: Initialize Master Game Plan components
            if not dry_run:
                logger.info("🔧 Phase 5: Initializing Master Game Plan components...")
                init_result = await self._initialize_mgp_components()
                execution_result["phases"]["initialization"] = init_result

                if not init_result["success"]:
                    execution_result["warnings"].append("Component initialization had issues")

            # Success!
            execution_result["status"] = "completed"
            execution_result["completed_at"] = datetime.utcnow().isoformat()

            if dry_run:
                logger.info("✅ Dry run completed successfully - no changes made")
            else:
                logger.info("✅ Master Game Plan migration completed successfully!")

            return execution_result

        except Exception as e:
            execution_result["status"] = "failed"
            execution_result["error"] = str(e)
            execution_result["completed_at"] = datetime.utcnow().isoformat()

            logger.error(f"❌ Migration execution failed: {e}")
            return execution_result

    async def _pre_migration_safety_check(self, force: bool = False) -> Dict[str, Any]:
        """Comprehensive pre-migration safety check"""

        safety_check = {
            "safe_to_proceed": True,
            "checks": {},
            "warnings": [],
            "errors": []
        }

        try:
            # Check 1: Database connectivity and permissions
            logger.info("🔌 Checking database connectivity...")
            db_check = await self._check_database_connectivity()
            safety_check["checks"]["database"] = db_check

            if not db_check["connected"]:
                safety_check["safe_to_proceed"] = False
                safety_check["errors"].append("Cannot connect to database")

            if not db_check.get("has_create_permissions", False):
                safety_check["safe_to_proceed"] = False
                safety_check["errors"].append("Insufficient database permissions")

            # Check 2: Existing schema conflicts
            logger.info("🔍 Checking for schema conflicts...")
            schema_check = await self._check_schema_conflicts()
            safety_check["checks"]["schema"] = schema_check

            if schema_check["conflicts"]:
                if force:
                    safety_check["warnings"].append(f"Schema conflicts detected but proceeding due to --force: {schema_check['conflicts']}")
                else:
                    safety_check["safe_to_proceed"] = False
                    safety_check["errors"].append(f"Schema conflicts detected: {schema_check['conflicts']}")

            # Check 3: Disk space availability
            logger.info("💽 Checking disk space...")
            disk_check = await self._check_disk_space()
            safety_check["checks"]["disk_space"] = disk_check

            if disk_check["available_gb"] < 1.0:  # Require at least 1GB free
                safety_check["safe_to_proceed"] = False
                safety_check["errors"].append(f"Insufficient disk space: {disk_check['available_gb']:.2f}GB available")

            # Check 4: Current system load
            logger.info("📊 Checking system load...")
            load_check = await self._check_system_load()
            safety_check["checks"]["system_load"] = load_check

            if load_check["cpu_usage"] > 90 or load_check["memory_usage"] > 90:
                safety_check["warnings"].append("High system load detected - migration may be slow")

            # Check 5: Backup verification
            logger.info("🔄 Checking backup capabilities...")
            backup_check = await self._check_backup_capabilities()
            safety_check["checks"]["backup"] = backup_check

            if not backup_check["can_backup"]:
                safety_check["warnings"].append("Backup capabilities limited - proceed with caution")

            logger.info(f"Safety check result: {'PASS' if safety_check['safe_to_proceed'] else 'FAIL'}")

            return safety_check

        except Exception as e:
            logger.error(f"Safety check failed: {e}")
            return {
                "safe_to_proceed": False,
                "error": str(e)
            }

    async def _check_database_connectivity(self) -> Dict[str, Any]:
        """Check database connectivity and permissions"""

        try:
            import asyncpg
            conn = await asyncpg.connect(migration_safety.database_url)

            # Test basic connectivity
            result = await conn.fetchval("SELECT 1")
            connected = result == 1

            # Check permissions
            try:
                await conn.execute("CREATE TABLE IF NOT EXISTS mgp_migration_test (id SERIAL)")
                await conn.execute("DROP TABLE IF EXISTS mgp_migration_test")
                has_create_permissions = True
            except Exception:
                has_create_permissions = False

            await conn.close()

            return {
                "connected": connected,
                "has_create_permissions": has_create_permissions
            }

        except Exception as e:
            logger.error(f"Database connectivity check failed: {e}")
            return {
                "connected": False,
                "error": str(e)
            }

    async def _check_schema_conflicts(self) -> Dict[str, Any]:
        """Check for existing schema conflicts"""

        try:
            import asyncpg
            conn = await asyncpg.connect(migration_safety.database_url)

            conflicts = []

            # Check for existing MGP tables
            mgp_tables = [
                'companies', 'executives', 'connections',
                'connector_rankings', 'company_settings', 'automation_jobs'
            ]

            for table in mgp_tables:
                exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = $1
                    )
                """, table)

                if exists:
                    conflicts.append(f"Table '{table}' already exists")

            await conn.close()

            return {
                "conflicts": conflicts,
                "safe_to_proceed": len(conflicts) == 0
            }

        except Exception as e:
            logger.error(f"Schema conflict check failed: {e}")
            return {
                "conflicts": [f"Unable to check schema conflicts: {e}"],
                "safe_to_proceed": False
            }

    async def _check_disk_space(self) -> Dict[str, Any]:
        """Check available disk space"""

        try:
            import shutil
            total, used, free = shutil.disk_usage("/")

            return {
                "total_gb": total / (1024**3),
                "used_gb": used / (1024**3),
                "available_gb": free / (1024**3),
                "usage_percent": (used / total) * 100
            }

        except Exception as e:
            logger.error(f"Disk space check failed: {e}")
            return {
                "available_gb": 0,
                "error": str(e)
            }

    async def _check_system_load(self) -> Dict[str, Any]:
        """Check current system load"""

        try:
            import psutil

            return {
                "cpu_usage": psutil.cpu_percent(interval=1),
                "memory_usage": psutil.virtual_memory().percent,
                "load_average": os.getloadavg()[0] if hasattr(os, 'getloadavg') else 0
            }

        except Exception as e:
            logger.error(f"System load check failed: {e}")
            return {
                "cpu_usage": 0,
                "memory_usage": 0,
                "error": str(e)
            }

    async def _check_backup_capabilities(self) -> Dict[str, Any]:
        """Check backup capabilities"""

        try:
            # Check if pg_dump is available
            import subprocess
            result = subprocess.run(['which', 'pg_dump'],
                                  capture_output=True, text=True)

            pg_dump_available = result.returncode == 0

            return {
                "can_backup": pg_dump_available,
                "pg_dump_available": pg_dump_available
            }

        except Exception as e:
            return {
                "can_backup": False,
                "error": str(e)
            }

    async def _create_schema_backup(self) -> Dict[str, Any]:
        """Create schema backup before migration"""

        try:
            backup_file = f"mgp_migration_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"

            # Create schema dump using pg_dump
            import subprocess
            import urllib.parse

            # Parse database URL
            db_url = migration_safety.database_url
            parsed = urllib.parse.urlparse(db_url)

            env = os.environ.copy()
            env['PGPASSWORD'] = parsed.password

            cmd = [
                'pg_dump',
                '-h', parsed.hostname,
                '-p', str(parsed.port or 5432),
                '-U', parsed.username,
                '-d', parsed.path[1:],  # Remove leading /
                '--schema-only',
                '-f', backup_file
            ]

            result = subprocess.run(cmd, env=env, capture_output=True, text=True)

            if result.returncode == 0:
                logger.info(f"✅ Schema backup created: {backup_file}")
                return {
                    "success": True,
                    "backup_file": backup_file,
                    "size_mb": os.path.getsize(backup_file) / (1024*1024) if os.path.exists(backup_file) else 0
                }
            else:
                logger.error(f"Schema backup failed: {result.stderr}")
                return {
                    "success": False,
                    "error": result.stderr
                }

        except Exception as e:
            logger.error(f"Schema backup failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _dry_run_migration(self) -> Dict[str, Any]:
        """Perform dry run of migration"""

        logger.info("🧪 Performing migration dry run...")

        try:
            # For dry run, we'll analyze the migration tables that will be created
            tables_to_create = [
                "companies", "executives", "connections",
                "connector_rankings", "company_settings", "automation_jobs"
            ]

            sql_analysis = {
                "total_statements": len(tables_to_create) * 2,  # CREATE TABLE + indexes
                "create_table_count": len(tables_to_create),
                "create_index_count": len(tables_to_create) * 3,  # Approximate indexes per table
                "alter_table_count": 0,
                "estimated_duration_minutes": len(tables_to_create) * 0.2
            }

            return {
                "status": "completed",
                "dry_run": True,
                "sql_analysis": sql_analysis,
                "rollback_available": True,
                "warnings": []
            }

        except Exception as e:
            logger.error(f"Dry run failed: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

    async def _execute_safe_migration(self) -> Dict[str, Any]:
        """Execute migration with safety procedures"""

        try:
            from alembic.config import Config
            from alembic import command
            import tempfile
            import os

            logger.info("🚀 Executing Master Game Plan migration...")

            # Use Alembic to run the migration
            # Create temporary alembic.ini if it doesn't exist
            alembic_ini_path = "/Users/jeffreyhacker/introduceme /Introduce.me/alembic.ini"
            if not os.path.exists(alembic_ini_path):
                # Create a basic alembic.ini
                with open(alembic_ini_path, 'w') as f:
                    f.write("""[alembic]
script_location = migrations
sqlalchemy.url = postgresql://vouchlink_user:G0cKKzLekD8EYygLMkymwoKlU3wdBqhk@dpg-d2f3ne2li9vc73bf5gg0-a.oregon-postgres.render.com/vouchlink

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
""")

            # Configure Alembic
            alembic_cfg = Config(alembic_ini_path)
            alembic_cfg.set_main_option("script_location", "/Users/jeffreyhacker/introduceme /Introduce.me/migrations")

            # Run migration to specific revision
            command.upgrade(alembic_cfg, self.migration_id)

            logger.info("✅ Migration executed successfully")

            return {
                "status": "completed",
                "rollback_available": True,
                "tables_created": [
                    "companies", "executives", "connections",
                    "connector_rankings", "company_settings", "automation_jobs"
                ]
            }

        except Exception as e:
            logger.error(f"Safe migration execution failed: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

    async def _post_migration_validation(self) -> Dict[str, Any]:
        """Comprehensive post-migration validation"""

        validation_result = {
            "all_passed": True,
            "validations": [],
            "failures": []
        }

        try:
            import asyncpg
            conn = await asyncpg.connect(migration_safety.database_url)

            # Validate 1: All MGP tables exist
            mgp_tables = ['companies', 'executives', 'connections', 'connector_rankings', 'company_settings', 'automation_jobs']

            for table in mgp_tables:
                exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = $1
                    )
                """, table)

                if exists:
                    validation_result["validations"].append(f"✅ Table {table} exists")
                else:
                    validation_result["all_passed"] = False
                    validation_result["failures"].append(f"❌ Table {table} missing")

            # Validate 2: Check table structures
            for table in mgp_tables:
                try:
                    columns = await conn.fetch("""
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_name = $1
                        ORDER BY ordinal_position
                    """, table)

                    if columns:
                        validation_result["validations"].append(f"✅ Table {table} has {len(columns)} columns")
                    else:
                        validation_result["all_passed"] = False
                        validation_result["failures"].append(f"❌ Table {table} has no columns")

                except Exception as e:
                    validation_result["all_passed"] = False
                    validation_result["failures"].append(f"❌ Cannot validate {table}: {e}")

            # Validate 3: Check indexes
            indexes = await conn.fetch("""
                SELECT indexname, tablename
                FROM pg_indexes
                WHERE tablename = ANY($1)
            """, mgp_tables)

            if indexes:
                validation_result["validations"].append(f"✅ Created {len(indexes)} indexes")
            else:
                validation_result["failures"].append("⚠️ No indexes created")

            # Validate 4: Check foreign key constraints
            fk_constraints = await conn.fetch("""
                SELECT constraint_name, table_name
                FROM information_schema.table_constraints
                WHERE constraint_type = 'FOREIGN KEY'
                AND table_name = ANY($1)
            """, mgp_tables)

            validation_result["validations"].append(f"✅ Created {len(fk_constraints)} foreign key constraints")

            await conn.close()

            if validation_result["all_passed"]:
                logger.info("✅ All post-migration validations passed")
            else:
                logger.error(f"❌ {len(validation_result['failures'])} validation failures")

            return validation_result

        except Exception as e:
            logger.error(f"Post-migration validation failed: {e}")
            return {
                "all_passed": False,
                "error": str(e),
                "failures": [f"Validation error: {e}"]
            }

    async def _initialize_mgp_components(self) -> Dict[str, Any]:
        """Initialize Master Game Plan components after migration"""

        init_result = {
            "success": True,
            "components": {},
            "warnings": [],
            "errors": []
        }

        try:
            # Initialize feature flag manager
            logger.info("🏗️ Initializing feature flag manager...")
            try:
                await feature_flag_manager.initialize()
                init_result["components"]["feature_flags"] = "initialized"
            except Exception as e:
                init_result["warnings"].append(f"Feature flag initialization failed: {e}")
                init_result["components"]["feature_flags"] = "failed"

            # Initialize security system
            logger.info("🔒 Initializing security system...")
            try:
                security_init = await initialize_mgp_security()
                if security_init.get("status") == "completed":
                    init_result["components"]["security"] = "initialized"
                else:
                    init_result["warnings"].append("Security initialization had warnings")
                    init_result["components"]["security"] = "partial"
            except Exception as e:
                init_result["warnings"].append(f"Security initialization failed: {e}")
                init_result["components"]["security"] = "failed"

            # Create initial data if needed
            logger.info("📝 Creating initial data...")
            try:
                await self._create_initial_data()
                init_result["components"]["initial_data"] = "created"
            except Exception as e:
                init_result["warnings"].append(f"Initial data creation failed: {e}")
                init_result["components"]["initial_data"] = "failed"

            if init_result["warnings"]:
                init_result["success"] = False

            return init_result

        except Exception as e:
            logger.error(f"Component initialization failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _create_initial_data(self):
        """Create initial data for Master Game Plan"""

        try:
            import asyncpg
            conn = await asyncpg.connect(migration_safety.database_url)

            # Create default company settings
            await conn.execute("""
                INSERT INTO company_settings (setting_key, setting_value, description)
                VALUES
                    ('default_target_titles', '["CEO", "CTO", "VP Sales", "VP Marketing"]', 'Default target executive titles'),
                    ('max_executives_per_company', '5', 'Maximum executives to find per company'),
                    ('automation_timeout_minutes', '60', 'Automation timeout in minutes')
                ON CONFLICT (setting_key) DO NOTHING
            """)

            logger.info("✅ Created initial company settings")

            await conn.close()

        except Exception as e:
            logger.error(f"Failed to create initial data: {e}")
            raise

    async def rollback_migration(self) -> Dict[str, Any]:
        """Rollback Master Game Plan migration"""

        logger.critical("🔄 INITIATING MIGRATION ROLLBACK...")

        try:
            result = await migration_safety.rollback_migration(self.migration_id)

            if result["status"] == "completed":
                logger.info("✅ Migration rollback completed successfully")
            else:
                logger.error(f"❌ Migration rollback failed: {result.get('error', 'Unknown error')}")

            return result

        except Exception as e:
            logger.critical(f"❌ ROLLBACK FAILED: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

# Main execution function
async def main():
    """Main migration execution"""

    import argparse

    parser = argparse.ArgumentParser(description='Execute Master Game Plan database migration')
    parser.add_argument('--dry-run', action='store_true', help='Perform dry run without making changes')
    parser.add_argument('--force', action='store_true', help='Force migration despite warnings')
    parser.add_argument('--rollback', action='store_true', help='Rollback the migration')
    parser.add_argument('--status', action='store_true', help='Show migration status')

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    executor = MGPMigrationExecutor()

    try:
        if args.rollback:
            result = await executor.rollback_migration()
        elif args.status:
            # Show migration status
            print("Migration status check not implemented yet")
            return
        else:
            result = await executor.execute_migration(dry_run=args.dry_run, force=args.force)

        # Print results
        print("\n" + "="*80)
        print("MASTER GAME PLAN MIGRATION RESULT")
        print("="*80)
        print(f"Status: {result['status'].upper()}")

        if result.get('started_at'):
            print(f"Started: {result['started_at']}")
        if result.get('completed_at'):
            print(f"Completed: {result['completed_at']}")

        if result.get('warnings'):
            print(f"\nWarnings ({len(result['warnings'])}):")
            for warning in result['warnings']:
                print(f"  ⚠️  {warning}")

        if result.get('errors'):
            print(f"\nErrors ({len(result['errors'])}):")
            for error in result['errors']:
                print(f"  ❌ {error}")

        if result['status'] == 'completed':
            print("\n✅ Migration completed successfully!")
            if not args.dry_run:
                print("\n🎯 Master Game Plan is now ready for rollout!")
        elif result['status'] == 'failed':
            print("\n❌ Migration failed!")
            if result.get('rollback_recommended'):
                print("🔄 Consider running rollback: python -m migrations.execute_mgp_migration --rollback")

        print("="*80)

    except KeyboardInterrupt:
        print("\n⚠️ Migration interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())