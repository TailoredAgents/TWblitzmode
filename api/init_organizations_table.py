#!/usr/bin/env python3
"""
Database Initialization Script: Create Organizations Table
This script creates the missing organizations table and seeds it with default data.
"""

import os
import sys
from pathlib import Path

# Add the api directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent))

from scripts.utils.postgres import postgres_connection, resolve_required_dsn


def init_organizations_table():
    """Create the organizations table if it doesn't exist."""

    dsn = resolve_required_dsn("DATABASE_URL", "TEST_DATABASE_URL")

    print(f"Connecting to database...")

    with postgres_connection(dsn) as conn:
        with conn.cursor() as cur:
            # Create the organizations table
            print("Creating organizations table...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS organizations (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    slug VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tenant_id)
                )
            """)

            # Create index for performance
            print("Creating index on tenant_id...")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_organizations_tenant_id
                ON organizations(tenant_id)
            """)

            # Insert default organization for tenant 1 (Tallwave)
            print("Inserting default organization...")
            cur.execute("""
                INSERT INTO organizations (tenant_id, name, slug, created_at, updated_at)
                VALUES (1, 'Tallwave', 'tallwave', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (tenant_id) DO NOTHING
            """)

            conn.commit()

            # Verify the table was created and data inserted
            print("\nVerifying organizations table:")
            cur.execute("SELECT * FROM organizations")
            rows = cur.fetchall()

            if rows:
                print(f"✅ Found {len(rows)} organization(s):")
                for row in rows:
                    print(f"   ID: {row[0]}, Tenant: {row[1]}, Name: {row[2]}, Slug: {row[3]}")
            else:
                print("❌ No organizations found after insert")

            # List all tables to confirm
            print("\nAll tables in database:")
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
            tables = cur.fetchall()
            for table in tables:
                mark = "✅" if table[0] == "organizations" else "  "
                print(f"{mark} {table[0]}")

    print("\n✅ Organizations table initialized successfully!")


if __name__ == "__main__":
    try:
        init_organizations_table()
    except Exception as e:
        print(f"\n❌ Error initializing organizations table: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
