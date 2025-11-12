"""
Database Migration Safety System
September 2025 - Master Game Plan Infrastructure

Provides safe migration procedures with rollback capabilities,
validation checkpoints, and conflict resolution for Master Game Plan.
"""

import asyncio
import logging
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import asyncpg
import os

logger = logging.getLogger(__name__)

@dataclass
class MigrationCheckpoint:
    """Migration validation checkpoint"""
    checkpoint_id: str
    migration_id: str
    table_name: str
    record_count: int
    schema_hash: str
    data_hash: str
    created_at: datetime
    validation_status: str  # passed, failed, pending

@dataclass
class MigrationRollback:
    """Migration rollback procedure"""
    migration_id: str
    rollback_sql: List[str]
    validation_queries: List[str]
    dependencies: List[str]
    created_at: datetime

class MigrationSafetyManager:
    """Manages safe database migrations with rollback capabilities"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.checkpoints: List[MigrationCheckpoint] = []
        self.rollback_procedures: Dict[str, MigrationRollback] = {}
        self.migration_log: List[Dict[str, Any]] = []

    async def create_safety_infrastructure(self):
        """Create tables for migration safety tracking"""

        safety_tables_sql = """
        -- Migration checkpoints table
        CREATE TABLE IF NOT EXISTS migration_checkpoints (
            id SERIAL PRIMARY KEY,
            checkpoint_id VARCHAR(255) UNIQUE NOT NULL,
            migration_id VARCHAR(255) NOT NULL,
            table_name VARCHAR(255) NOT NULL,
            record_count INTEGER NOT NULL,
            schema_hash VARCHAR(64) NOT NULL,
            data_hash VARCHAR(64) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            validation_status VARCHAR(50) DEFAULT 'pending'
        );

        -- Migration rollback procedures table
        CREATE TABLE IF NOT EXISTS migration_rollbacks (
            id SERIAL PRIMARY KEY,
            migration_id VARCHAR(255) UNIQUE NOT NULL,
            rollback_sql JSONB NOT NULL,
            validation_queries JSONB NOT NULL,
            dependencies JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Migration execution log
        CREATE TABLE IF NOT EXISTS migration_execution_log (
            id SERIAL PRIMARY KEY,
            migration_id VARCHAR(255) NOT NULL,
            operation VARCHAR(100) NOT NULL,
            status VARCHAR(50) NOT NULL,
            duration_ms INTEGER,
            error_message TEXT,
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_migration_checkpoints_migration_id
            ON migration_checkpoints(migration_id);
        CREATE INDEX IF NOT EXISTS idx_migration_rollbacks_migration_id
            ON migration_rollbacks(migration_id);
        CREATE INDEX IF NOT EXISTS idx_migration_log_migration_id
            ON migration_execution_log(migration_id);
        """

        try:
            conn = await asyncpg.connect(self.database_url)
            await conn.execute(safety_tables_sql)
            await conn.close()
            logger.info("✅ Migration safety infrastructure created")
        except Exception as e:
            logger.error(f"❌ Failed to create safety infrastructure: {e}")
            raise

    async def create_pre_migration_checkpoint(
        self,
        migration_id: str,
        tables_to_check: List[str]
    ) -> List[MigrationCheckpoint]:
        """Create checkpoints before migration execution"""

        checkpoints = []
        conn = await asyncpg.connect(self.database_url)

        try:
            for table_name in tables_to_check:
                # Get record count
                count_result = await conn.fetchval(f"SELECT COUNT(*) FROM {table_name}")
                record_count = count_result if count_result else 0

                # Get schema hash
                schema_query = """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = $1
                ORDER BY ordinal_position
                """
                schema_info = await conn.fetch(schema_query, table_name)
                schema_hash = hashlib.sha256(str(schema_info).encode()).hexdigest()

                # Get data hash (sample for large tables)
                if record_count > 10000:
                    data_query = f"SELECT * FROM {table_name} ORDER BY id LIMIT 1000"
                else:
                    data_query = f"SELECT * FROM {table_name} ORDER BY id"

                try:
                    data_sample = await conn.fetch(data_query)
                    data_hash = hashlib.sha256(str(data_sample).encode()).hexdigest()
                except Exception:
                    data_hash = "no_data"

                # Create checkpoint
                checkpoint_id = f"{migration_id}_{table_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                checkpoint = MigrationCheckpoint(
                    checkpoint_id=checkpoint_id,
                    migration_id=migration_id,
                    table_name=table_name,
                    record_count=record_count,
                    schema_hash=schema_hash,
                    data_hash=data_hash,
                    created_at=datetime.now(),
                    validation_status="passed"
                )

                # Store checkpoint
                await conn.execute("""
                    INSERT INTO migration_checkpoints
                    (checkpoint_id, migration_id, table_name, record_count,
                     schema_hash, data_hash, created_at, validation_status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, checkpoint.checkpoint_id, checkpoint.migration_id,
                    checkpoint.table_name, checkpoint.record_count,
                    checkpoint.schema_hash, checkpoint.data_hash,
                    checkpoint.created_at, checkpoint.validation_status)

                checkpoints.append(checkpoint)
                logger.info(f"✅ Created checkpoint for {table_name}: {record_count} records")

        finally:
            await conn.close()

        return checkpoints

    async def execute_safe_migration(
        self,
        migration_id: str,
        migration_sql: List[str],
        rollback_sql: List[str],
        validation_queries: List[str],
        affected_tables: List[str]
    ) -> Dict[str, Any]:
        """Execute migration with safety checks and rollback capability"""

        start_time = datetime.now()
        execution_log = {
            "migration_id": migration_id,
            "status": "started",
            "steps": [],
            "checkpoints": [],
            "rollback_available": False
        }

        try:
            # Step 1: Create pre-migration checkpoints
            logger.info(f"🔍 Creating pre-migration checkpoints for {migration_id}")
            checkpoints = await self.create_pre_migration_checkpoint(migration_id, affected_tables)
            execution_log["checkpoints"] = [asdict(cp) for cp in checkpoints]

            # Step 2: Store rollback procedure
            logger.info(f"💾 Storing rollback procedure for {migration_id}")
            await self.store_rollback_procedure(migration_id, rollback_sql, validation_queries)
            execution_log["rollback_available"] = True

            # Step 3: Execute migration in transaction
            logger.info(f"🚀 Executing migration {migration_id}")
            conn = await asyncpg.connect(self.database_url)

            async with conn.transaction():
                for i, sql_statement in enumerate(migration_sql):
                    step_start = datetime.now()
                    try:
                        await conn.execute(sql_statement)
                        step_duration = (datetime.now() - step_start).total_seconds() * 1000
                        execution_log["steps"].append({
                            "step": i + 1,
                            "sql": sql_statement[:100] + "..." if len(sql_statement) > 100 else sql_statement,
                            "status": "success",
                            "duration_ms": step_duration
                        })
                        logger.info(f"✅ Migration step {i + 1} completed in {step_duration:.0f}ms")
                    except Exception as e:
                        step_duration = (datetime.now() - step_start).total_seconds() * 1000
                        execution_log["steps"].append({
                            "step": i + 1,
                            "sql": sql_statement[:100] + "..." if len(sql_statement) > 100 else sql_statement,
                            "status": "failed",
                            "duration_ms": step_duration,
                            "error": str(e)
                        })
                        raise e

            await conn.close()

            # Step 4: Post-migration validation
            logger.info(f"🔍 Running post-migration validation for {migration_id}")
            validation_results = await self.validate_migration(migration_id, validation_queries)
            execution_log["validation"] = validation_results

            if not validation_results["all_passed"]:
                raise Exception(f"Migration validation failed: {validation_results['failures']}")

            # Step 5: Log successful execution
            total_duration = (datetime.now() - start_time).total_seconds() * 1000
            execution_log["status"] = "completed"
            execution_log["duration_ms"] = total_duration

            await self.log_migration_execution(migration_id, "execute", "success", total_duration)
            logger.info(f"✅ Migration {migration_id} completed successfully in {total_duration:.0f}ms")

            return execution_log

        except Exception as e:
            total_duration = (datetime.now() - start_time).total_seconds() * 1000
            execution_log["status"] = "failed"
            execution_log["error"] = str(e)
            execution_log["duration_ms"] = total_duration

            await self.log_migration_execution(migration_id, "execute", "failed", total_duration, str(e))
            logger.error(f"❌ Migration {migration_id} failed: {e}")

            # Offer rollback option
            execution_log["rollback_recommended"] = True
            return execution_log

    async def rollback_migration(self, migration_id: str) -> Dict[str, Any]:
        """Rollback a migration using stored rollback procedure"""

        start_time = datetime.now()
        rollback_log = {
            "migration_id": migration_id,
            "status": "started",
            "steps": []
        }

        try:
            # Get rollback procedure
            conn = await asyncpg.connect(self.database_url)
            rollback_data = await conn.fetchrow(
                "SELECT rollback_sql, validation_queries FROM migration_rollbacks WHERE migration_id = $1",
                migration_id
            )

            if not rollback_data:
                raise Exception(f"No rollback procedure found for migration {migration_id}")

            rollback_sql = rollback_data['rollback_sql']
            validation_queries = rollback_data['validation_queries']

            # Execute rollback in transaction
            logger.info(f"🔄 Rolling back migration {migration_id}")
            async with conn.transaction():
                for i, sql_statement in enumerate(rollback_sql):
                    step_start = datetime.now()
                    try:
                        await conn.execute(sql_statement)
                        step_duration = (datetime.now() - step_start).total_seconds() * 1000
                        rollback_log["steps"].append({
                            "step": i + 1,
                            "sql": sql_statement[:100] + "..." if len(sql_statement) > 100 else sql_statement,
                            "status": "success",
                            "duration_ms": step_duration
                        })
                        logger.info(f"✅ Rollback step {i + 1} completed")
                    except Exception as e:
                        step_duration = (datetime.now() - step_start).total_seconds() * 1000
                        rollback_log["steps"].append({
                            "step": i + 1,
                            "sql": sql_statement[:100] + "..." if len(sql_statement) > 100 else sql_statement,
                            "status": "failed",
                            "duration_ms": step_duration,
                            "error": str(e)
                        })
                        raise e

            await conn.close()

            # Validate rollback
            validation_results = await self.validate_migration(f"{migration_id}_rollback", validation_queries)
            rollback_log["validation"] = validation_results

            total_duration = (datetime.now() - start_time).total_seconds() * 1000
            rollback_log["status"] = "completed"
            rollback_log["duration_ms"] = total_duration

            await self.log_migration_execution(migration_id, "rollback", "success", total_duration)
            logger.info(f"✅ Rollback {migration_id} completed successfully")

            return rollback_log

        except Exception as e:
            total_duration = (datetime.now() - start_time).total_seconds() * 1000
            rollback_log["status"] = "failed"
            rollback_log["error"] = str(e)
            rollback_log["duration_ms"] = total_duration

            await self.log_migration_execution(migration_id, "rollback", "failed", total_duration, str(e))
            logger.error(f"❌ Rollback {migration_id} failed: {e}")
            return rollback_log

    async def store_rollback_procedure(
        self,
        migration_id: str,
        rollback_sql: List[str],
        validation_queries: List[str]
    ):
        """Store rollback procedure for a migration"""

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute("""
                INSERT INTO migration_rollbacks
                (migration_id, rollback_sql, validation_queries, dependencies)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (migration_id) DO UPDATE SET
                rollback_sql = EXCLUDED.rollback_sql,
                validation_queries = EXCLUDED.validation_queries,
                dependencies = EXCLUDED.dependencies
            """, migration_id, json.dumps(rollback_sql),
                json.dumps(validation_queries), json.dumps([]))
        finally:
            await conn.close()

    async def validate_migration(
        self,
        migration_id: str,
        validation_queries: List[str]
    ) -> Dict[str, Any]:
        """Validate migration results"""

        validation_results = {
            "migration_id": migration_id,
            "all_passed": True,
            "validations": [],
            "failures": []
        }

        conn = await asyncpg.connect(self.database_url)
        try:
            for i, query in enumerate(validation_queries):
                try:
                    result = await conn.fetch(query)
                    validation_results["validations"].append({
                        "validation": i + 1,
                        "query": query[:100] + "..." if len(query) > 100 else query,
                        "status": "passed",
                        "result_count": len(result)
                    })
                except Exception as e:
                    validation_results["all_passed"] = False
                    validation_results["failures"].append({
                        "validation": i + 1,
                        "query": query[:100] + "..." if len(query) > 100 else query,
                        "error": str(e)
                    })
        finally:
            await conn.close()

        return validation_results

    async def log_migration_execution(
        self,
        migration_id: str,
        operation: str,
        status: str,
        duration_ms: float,
        error_message: Optional[str] = None
    ):
        """Log migration execution details"""

        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute("""
                INSERT INTO migration_execution_log
                (migration_id, operation, status, duration_ms, error_message)
                VALUES ($1, $2, $3, $4, $5)
            """, migration_id, operation, status, duration_ms, error_message)
        finally:
            await conn.close()

# Master Game Plan specific migration procedures
MGP_MIGRATION_PROCEDURES = {
    "003_master_game_plan_tables": {
        "migration_sql": [
            # This would contain the actual SQL from 003_master_game_plan_tables.py
            # For brevity, showing the concept
        ],
        "rollback_sql": [
            "DROP TABLE IF EXISTS automation_jobs CASCADE;",
            "DROP TABLE IF EXISTS company_settings CASCADE;",
            "DROP TABLE IF EXISTS connector_rankings CASCADE;",
            "DROP TABLE IF EXISTS connections CASCADE;",
            "DROP TABLE IF EXISTS executives CASCADE;",
            "DROP TABLE IF EXISTS companies CASCADE;"
        ],
        "validation_queries": [
            "SELECT COUNT(*) FROM companies;",
            "SELECT COUNT(*) FROM executives;",
            "SELECT COUNT(*) FROM connections;",
            "SELECT COUNT(*) FROM connector_rankings;",
            "SELECT COUNT(*) FROM company_settings;",
            "SELECT COUNT(*) FROM automation_jobs;"
        ],
        "affected_tables": [
            "companies", "executives", "connections",
            "connector_rankings", "company_settings", "automation_jobs"
        ]
    }
}

# Global migration safety manager
migration_safety = MigrationSafetyManager(
    os.getenv("DATABASE_URL", "postgresql://localhost/VouchLink-AIVouchLink AI")
)