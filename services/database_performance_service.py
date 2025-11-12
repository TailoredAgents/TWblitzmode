#!/usr/bin/env python3
"""
Database Performance Service
Monitors and maintains database performance through index analysis and optimization
"""

import asyncio
import logging
import os
import psutil
import asyncpg
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

logger = logging.getLogger(__name__)

@dataclass
class IndexUsageStats:
    """Database index usage statistics"""
    table_name: str
    index_name: str
    index_size: int
    scans: int
    tuples_read: int
    tuples_fetched: int
    usage_ratio: float
    last_used: Optional[datetime]

@dataclass
class TableStats:
    """Database table statistics"""
    table_name: str
    row_count: int
    table_size: int
    index_size: int
    total_size: int
    seq_scans: int
    seq_tup_read: int
    idx_scans: int
    idx_tup_fetch: int
    n_tup_ins: int
    n_tup_upd: int
    n_tup_del: int
    last_vacuum: Optional[datetime]
    last_autovacuum: Optional[datetime]
    last_analyze: Optional[datetime]

@dataclass
class QueryPerformance:
    """Slow query performance data"""
    query: str
    calls: int
    total_time: float
    mean_time: float
    min_time: float
    max_time: float
    rows: int

class DatabasePerformanceService:
    """
    Database performance monitoring and optimization service
    """

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.pool = None

        # Performance thresholds
        self.slow_query_threshold = 1000  # milliseconds
        self.unused_index_threshold = 0.01  # 1% usage
        self.large_table_threshold = 100000  # rows
        self.bloat_threshold = 0.2  # 20% bloat

    async def initialize(self):
        """Initialize database connection pool"""
        try:
            if not self.database_url:
                raise RuntimeError("DATABASE_URL is not configured for DatabasePerformanceService")
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=2,
                max_size=10,
                command_timeout=60
            )
            logger.info("✅ Database performance service initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize database performance service: {e}")
            raise

    async def get_index_usage_stats(self) -> List[IndexUsageStats]:
        """Get detailed index usage statistics"""
        if not self.pool:
            await self.initialize()

        async with self.pool.acquire() as conn:
            query = """
                SELECT
                    s.schemaname,
                    s.relname as tablename,
                    s.indexrelname as indexname,
                    pg_size_pretty(pg_relation_size(s.indexrelid)) as index_size,
                    pg_relation_size(s.indexrelid) as index_size_bytes,
                    s.idx_scan,
                    s.idx_tup_read,
                    s.idx_tup_fetch,
                    CASE
                        WHEN s.idx_scan = 0 THEN 0
                        ELSE ROUND((s.idx_tup_fetch::numeric / NULLIF(s.idx_tup_read, 0)::numeric) * 100, 2)
                    END as usage_ratio
                FROM pg_stat_user_indexes s
                WHERE s.schemaname = 'public'
                ORDER BY s.idx_scan DESC, pg_relation_size(s.indexrelid) DESC;
            """

            rows = await conn.fetch(query)
            stats = []

            for row in rows:
                stats.append(IndexUsageStats(
                    table_name=row['tablename'],
                    index_name=row['indexname'],
                    index_size=row['index_size_bytes'],
                    scans=row['idx_scan'] or 0,
                    tuples_read=row['idx_tup_read'] or 0,
                    tuples_fetched=row['idx_tup_fetch'] or 0,
                    usage_ratio=float(row['usage_ratio'] or 0),
                    last_used=None  # PostgreSQL doesn't track last used time
                ))

            return stats

    async def get_table_stats(self) -> List[TableStats]:
        """Get comprehensive table statistics"""
        if not self.pool:
            await self.initialize()

        async with self.pool.acquire() as conn:
            query = """
                SELECT
                    t.schemaname,
                    t.relname as tablename,
                    c.reltuples::bigint as row_count,
                    pg_total_relation_size(c.oid) as total_size,
                    pg_relation_size(c.oid) as table_size,
                    pg_indexes_size(c.oid) as index_size,
                    t.seq_scan,
                    t.seq_tup_read,
                    t.idx_scan,
                    t.idx_tup_fetch,
                    t.n_tup_ins,
                    t.n_tup_upd,
                    t.n_tup_del,
                    t.last_vacuum,
                    t.last_autovacuum,
                    t.last_analyze
                FROM pg_stat_user_tables t
                JOIN pg_class c ON t.relname = c.relname
                WHERE t.schemaname = 'public'
                ORDER BY pg_total_relation_size(c.oid) DESC;
            """

            rows = await conn.fetch(query)
            stats = []

            for row in rows:
                stats.append(TableStats(
                    table_name=row['tablename'],
                    row_count=row['row_count'] or 0,
                    table_size=row['table_size'] or 0,
                    index_size=row['index_size'] or 0,
                    total_size=row['total_size'] or 0,
                    seq_scans=row['seq_scan'] or 0,
                    seq_tup_read=row['seq_tup_read'] or 0,
                    idx_scans=row['idx_scan'] or 0,
                    idx_tup_fetch=row['idx_tup_fetch'] or 0,
                    n_tup_ins=row['n_tup_ins'] or 0,
                    n_tup_upd=row['n_tup_upd'] or 0,
                    n_tup_del=row['n_tup_del'] or 0,
                    last_vacuum=row['last_vacuum'],
                    last_autovacuum=row['last_autovacuum'],
                    last_analyze=row['last_analyze']
                ))

            return stats

    async def get_slow_queries(self, limit: int = 20) -> List[QueryPerformance]:
        """Get slow query statistics (requires pg_stat_statements extension)"""
        if not self.pool:
            await self.initialize()

        async with self.pool.acquire() as conn:
            try:
                # Check if pg_stat_statements is available
                extension_check = await conn.fetchval(
                    "SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'"
                )

                if not extension_check:
                    logger.warning("pg_stat_statements extension not available - slow query analysis disabled")
                    return []

                query = """
                    SELECT
                        query,
                        calls,
                        total_exec_time as total_time,
                        mean_exec_time as mean_time,
                        min_exec_time as min_time,
                        max_exec_time as max_time,
                        rows
                    FROM pg_stat_statements
                    WHERE query NOT LIKE '%pg_stat_statements%'
                        AND query NOT LIKE '%information_schema%'
                        AND mean_exec_time > %s
                    ORDER BY mean_exec_time DESC
                    LIMIT %s;
                """

                rows = await conn.fetch(query, self.slow_query_threshold, limit)
                queries = []

                for row in rows:
                    queries.append(QueryPerformance(
                        query=row['query'][:500] + '...' if len(row['query']) > 500 else row['query'],
                        calls=row['calls'],
                        total_time=float(row['total_time']),
                        mean_time=float(row['mean_time']),
                        min_time=float(row['min_time']),
                        max_time=float(row['max_time']),
                        rows=row['rows']
                    ))

                return queries

            except Exception as e:
                logger.error(f"Failed to get slow queries: {e}")
                return []

    async def identify_unused_indexes(self) -> List[IndexUsageStats]:
        """Identify potentially unused indexes"""
        index_stats = await self.get_index_usage_stats()

        unused_indexes = []
        for stat in index_stats:
            # Skip primary keys and unique constraints
            if stat.index_name.endswith('_pkey') or 'unique' in stat.index_name.lower():
                continue

            # Consider index unused if very low scan count relative to table size
            if stat.scans < 10 and stat.usage_ratio < self.unused_index_threshold:
                unused_indexes.append(stat)

        return unused_indexes

    async def identify_missing_indexes(self) -> List[Dict[str, Any]]:
        """Identify potential missing indexes based on sequential scans"""
        table_stats = await self.get_table_stats()

        missing_indexes = []
        for stat in table_stats:
            # Large tables with high sequential scan ratios may need indexes
            if (stat.row_count > self.large_table_threshold and
                stat.seq_scans > 0 and
                stat.idx_scans > 0):

                seq_scan_ratio = stat.seq_scans / (stat.seq_scans + stat.idx_scans)

                if seq_scan_ratio > 0.3:  # More than 30% sequential scans
                    missing_indexes.append({
                        'table_name': stat.table_name,
                        'row_count': stat.row_count,
                        'seq_scans': stat.seq_scans,
                        'idx_scans': stat.idx_scans,
                        'seq_scan_ratio': round(seq_scan_ratio * 100, 2),
                        'recommendation': f'Consider adding indexes to {stat.table_name} to reduce sequential scans'
                    })

        return missing_indexes

    async def check_table_bloat(self) -> List[Dict[str, Any]]:
        """Check for table and index bloat"""
        if not self.pool:
            await self.initialize()

        async with self.pool.acquire() as conn:
            query = """
                SELECT
                    schemaname,
                    tablename,
                    ROUND(CASE
                        WHEN otta=0 OR sml.relpages=0 OR sml.relpages=otta THEN 0.0
                        ELSE sml.relpages/otta::numeric
                    END,1) AS tbloat,
                    CASE
                        WHEN relpages < otta THEN 0
                        ELSE relpages::bigint - otta
                    END AS wastedpages,
                    CASE
                        WHEN relpages < otta THEN 0
                        ELSE bs*(sml.relpages-otta)::bigint
                    END AS wastedbytes,
                    pg_size_pretty(CASE
                        WHEN relpages < otta THEN 0
                        ELSE bs*(sml.relpages-otta)::bigint
                    END) AS wasted_size
                FROM (
                    SELECT
                        schemaname, tablename, cc.reltuples, cc.relpages, bs,
                        CEIL((cc.reltuples*((datahdr+ma-
                            (CASE WHEN datahdr%ma=0 THEN ma ELSE datahdr%ma END))+nullhdr2+4))/(bs-20::float)) AS otta
                    FROM (
                        SELECT
                            ma,bs,schemaname,tablename,
                            (datawidth+(hdr+ma-(case when hdr%ma=0 THEN ma ELSE hdr%ma END)))::numeric AS datahdr,
                            (maxfracsum*(nullhdr+ma-(case when nullhdr%ma=0 THEN ma ELSE nullhdr%ma END))) AS nullhdr2
                        FROM (
                            SELECT
                                schemaname, tablename, hdr, ma, bs,
                                SUM((1-null_frac)*avg_width) AS datawidth,
                                MAX(null_frac) AS maxfracsum,
                                hdr+(
                                    SELECT 1+count(*)/8
                                    FROM pg_stats s2
                                    WHERE null_frac<>0 AND s2.schemaname = s.schemaname AND s2.tablename = s.tablename
                                ) AS nullhdr
                            FROM pg_stats s, (
                                SELECT
                                    (SELECT current_setting('block_size')::numeric) AS bs,
                                    CASE WHEN substring(SPLIT_PART(v, ' ', 2) FROM '#"[0-9]+.[0-9]+#"%' for '#')
                                        IN ('8.0','8.1','8.2') THEN 27 ELSE 23 END AS hdr,
                                    CASE WHEN v ~ 'mingw32' OR v ~ '64-bit|x86_64|ppc64|ia64|amd64' THEN 8 ELSE 4 END AS ma
                                FROM (SELECT version() AS v) AS foo
                            ) AS constants
                            WHERE schemaname='public'
                            GROUP BY schemaname, tablename, hdr, ma, bs
                        ) AS foo
                    ) AS rs
                    JOIN pg_class cc ON cc.relname = rs.tablename
                    JOIN pg_namespace nn ON cc.relnamespace = nn.oid AND nn.nspname = rs.schemaname AND nn.nspname <> 'information_schema'
                ) AS sml
                WHERE sml.relpages - otta > 0
                ORDER BY wastedbytes DESC;
            """

            try:
                rows = await conn.fetch(query)
                bloated_tables = []

                for row in rows:
                    bloat_ratio = float(row['tbloat']) if row['tbloat'] else 0
                    if bloat_ratio > (1 + self.bloat_threshold):  # More than 20% bloat
                        bloated_tables.append({
                            'table_name': row['tablename'],
                            'bloat_ratio': bloat_ratio,
                            'wasted_pages': row['wastedpages'],
                            'wasted_bytes': row['wastedbytes'],
                            'wasted_size': row['wasted_size'],
                            'recommendation': f'Consider VACUUM FULL or pg_repack for {row["tablename"]}'
                        })

                return bloated_tables

            except Exception as e:
                logger.error(f"Failed to check table bloat: {e}")
                return []

    async def optimize_database(self, auto_fix: bool = False) -> Dict[str, Any]:
        """Perform database optimization analysis and optionally apply fixes"""
        optimization_report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'index_analysis': {},
            'table_analysis': {},
            'query_analysis': {},
            'recommendations': [],
            'auto_fixes_applied': []
        }

        try:
            # Analyze indexes
            logger.info("🔍 Analyzing index usage...")
            index_stats = await self.get_index_usage_stats()
            unused_indexes = await self.identify_unused_indexes()
            missing_indexes = await self.identify_missing_indexes()

            optimization_report['index_analysis'] = {
                'total_indexes': len(index_stats),
                'unused_indexes': len(unused_indexes),
                'missing_indexes_suggestions': len(missing_indexes),
                'unused_index_details': [
                    {
                        'table': idx.table_name,
                        'index': idx.index_name,
                        'size_mb': round(idx.index_size / (1024 * 1024), 2),
                        'scans': idx.scans,
                        'usage_ratio': idx.usage_ratio
                    } for idx in unused_indexes
                ],
                'missing_index_suggestions': missing_indexes
            }

            # Analyze tables
            logger.info("📊 Analyzing table statistics...")
            table_stats = await self.get_table_stats()
            bloated_tables = await self.check_table_bloat()

            optimization_report['table_analysis'] = {
                'total_tables': len(table_stats),
                'bloated_tables': len(bloated_tables),
                'large_tables': len([t for t in table_stats if t.row_count > self.large_table_threshold]),
                'table_details': [
                    {
                        'table': stat.table_name,
                        'rows': stat.row_count,
                        'size_mb': round(stat.total_size / (1024 * 1024), 2),
                        'index_size_mb': round(stat.index_size / (1024 * 1024), 2),
                        'seq_scans': stat.seq_scans,
                        'idx_scans': stat.idx_scans
                    } for stat in table_stats[:10]  # Top 10 tables
                ],
                'bloat_details': bloated_tables
            }

            # Analyze queries
            logger.info("🐌 Analyzing slow queries...")
            slow_queries = await self.get_slow_queries()

            optimization_report['query_analysis'] = {
                'slow_queries_count': len(slow_queries),
                'slow_query_details': [
                    {
                        'query_preview': q.query[:100] + '...',
                        'calls': q.calls,
                        'mean_time_ms': round(q.mean_time, 2),
                        'total_time_ms': round(q.total_time, 2)
                    } for q in slow_queries[:10]
                ]
            }

            # Generate recommendations
            recommendations = []

            # Index recommendations
            if unused_indexes:
                recommendations.append(f"Consider dropping {len(unused_indexes)} unused indexes to save space")

            if missing_indexes:
                recommendations.append(f"Consider adding indexes to {len(missing_indexes)} tables with high sequential scan ratios")

            # Table recommendations
            if bloated_tables:
                recommendations.append(f"Consider running VACUUM on {len(bloated_tables)} bloated tables")

            tables_needing_analyze = [t for t in table_stats if not t.last_analyze or
                                    t.last_analyze < datetime.now(timezone.utc) - timedelta(days=7)]
            if tables_needing_analyze:
                recommendations.append(f"Run ANALYZE on {len(tables_needing_analyze)} tables with outdated statistics")

            # Query recommendations
            if slow_queries:
                recommendations.append(f"Optimize {len(slow_queries)} slow queries identified")

            optimization_report['recommendations'] = recommendations

            # Auto-fix if requested
            if auto_fix:
                logger.info("🔧 Applying automatic optimizations...")
                auto_fixes = await self._apply_auto_fixes(tables_needing_analyze)
                optimization_report['auto_fixes_applied'] = auto_fixes

            logger.info(f"✅ Database optimization analysis complete: {len(recommendations)} recommendations")
            return optimization_report

        except Exception as e:
            logger.error(f"❌ Database optimization analysis failed: {e}")
            optimization_report['error'] = str(e)
            return optimization_report

    async def _apply_auto_fixes(self, tables_needing_analyze: List[TableStats]) -> List[str]:
        """Apply safe automatic optimizations"""
        if not self.pool:
            await self.initialize()

        auto_fixes = []

        async with self.pool.acquire() as conn:
            # Run ANALYZE on tables with outdated statistics
            for table in tables_needing_analyze[:5]:  # Limit to 5 tables
                try:
                    await conn.execute(f"ANALYZE {table.table_name}")
                    auto_fixes.append(f"Ran ANALYZE on {table.table_name}")
                    logger.info(f"✅ Analyzed table: {table.table_name}")
                except Exception as e:
                    logger.error(f"❌ Failed to analyze {table.table_name}: {e}")

        return auto_fixes

    async def get_performance_dashboard_data(self) -> Dict[str, Any]:
        """Get data for performance monitoring dashboard"""
        try:
            # Get basic metrics
            index_stats = await self.get_index_usage_stats()
            table_stats = await self.get_table_stats()
            slow_queries = await self.get_slow_queries(10)

            # Calculate summary metrics
            total_db_size = sum(t.total_size for t in table_stats)
            total_index_size = sum(t.index_size for t in table_stats)
            total_table_size = sum(t.table_size for t in table_stats)

            # Get system metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            return {
                'database_metrics': {
                    'total_size_mb': round(total_db_size / (1024 * 1024), 2),
                    'table_size_mb': round(total_table_size / (1024 * 1024), 2),
                    'index_size_mb': round(total_index_size / (1024 * 1024), 2),
                    'total_tables': len(table_stats),
                    'total_indexes': len(index_stats),
                },
                'performance_metrics': {
                    'slow_queries_count': len(slow_queries),
                    'average_query_time': round(sum(q.mean_time for q in slow_queries) / len(slow_queries), 2) if slow_queries else 0,
                    'total_index_scans': sum(idx.scans for idx in index_stats),
                    'total_sequential_scans': sum(t.seq_scans for t in table_stats),
                },
                'system_metrics': {
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'disk_percent': disk.percent,
                    'available_memory_gb': round(memory.available / (1024**3), 2),
                    'free_disk_gb': round(disk.free / (1024**3), 2),
                },
                'top_tables': [
                    {
                        'name': t.table_name,
                        'rows': t.row_count,
                        'size_mb': round(t.total_size / (1024 * 1024), 2),
                        'seq_scans': t.seq_scans,
                        'idx_scans': t.idx_scans
                    } for t in sorted(table_stats, key=lambda x: x.total_size, reverse=True)[:10]
                ],
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"❌ Failed to get performance dashboard data: {e}")
            return {'error': str(e), 'timestamp': datetime.now(timezone.utc).isoformat()}

    async def close(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()

# Global instance
db_performance = DatabasePerformanceService()
