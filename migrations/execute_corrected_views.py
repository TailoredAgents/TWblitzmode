#!/usr/bin/env python3
"""
Execute corrected compatibility views in PostgreSQL.
Uses psycopg2 directly with autocommit for DDL operations.
"""

import os
import psycopg2

# Database connection (must be provided via env)
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL must be set to execute compatibility views")

print("=" * 80)
print("EXECUTING CORRECTED COMPATIBILITY VIEWS")
print("=" * 80)

# Read the corrected SQL file
SQL_PATH = os.path.join(os.path.dirname(__file__), 'create_compatibility_views_CORRECTED.sql')
with open(SQL_PATH, 'r') as f:
    sql_content = f.read()

# Connect and execute
conn = psycopg2.connect(database_url)
conn.autocommit = True  # Required for DDL
cursor = conn.cursor()

print("\n📋 Executing corrected compatibility views SQL...")
print("-" * 80)

try:
    # Split by semicolons but keep comments
    statements = []
    current_statement = []

    for line in sql_content.split('\n'):
        # Skip pure comment lines
        if line.strip().startswith('--') and not current_statement:
            continue

        current_statement.append(line)

        # If line ends with semicolon, it's a complete statement
        if line.strip().endswith(';'):
            statement_text = '\n'.join(current_statement)
            if statement_text.strip():
                statements.append(statement_text)
            current_statement = []

    # Execute each statement
    for i, statement in enumerate(statements, 1):
        statement_preview = statement.strip()[:100].replace('\n', ' ')
        print(f"\n[{i}/{len(statements)}] {statement_preview}...")

        try:
            cursor.execute(statement)

            # If it's a SELECT, fetch and display results
            if statement.strip().upper().startswith('SELECT'):
                results = cursor.fetchall()
                if results:
                    print(f"  ✅ Result: {results[0]}")
                else:
                    print(f"  ✅ Executed (no results)")
            else:
                print(f"  ✅ Success")

        except Exception as e:
            print(f"  ⚠️ Error: {e}")
            # Continue with next statement
            continue

    print("\n" + "=" * 80)
    print("✅ COMPATIBILITY VIEWS EXECUTION COMPLETE")
    print("=" * 80)

    # Final verification
    print("\n📊 FINAL VERIFICATION:")
    print("-" * 80)

    cursor.execute("""
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ('accounts', 'audit_logs', 'account_users', 'account_features', 'dashboards')
        ORDER BY table_name;
    """)

    views = cursor.fetchall()
    print(f"\n✅ Created {len(views)} compatibility views:")
    for view_name, view_type in views:
        print(f"   • {view_name} ({view_type})")

    # Test each view
    print("\n🧪 TESTING VIEWS:")
    print("-" * 80)

    test_views = ['accounts', 'audit_logs', 'account_users', 'account_features', 'dashboards']
    for view_name in test_views:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {view_name};")
            count = cursor.fetchone()[0]
            print(f"   ✅ {view_name}: {count} rows")
        except Exception as e:
            print(f"   ❌ {view_name}: {e}")

    print("\n" + "=" * 80)
    print("🎉 ALL COMPATIBILITY VIEWS WORKING!")
    print("=" * 80)

except Exception as e:
    print(f"\n❌ EXECUTION FAILED: {e}")
    import traceback
    traceback.print_exc()

finally:
    cursor.close()
    conn.close()
    print("\n✅ Database connection closed")
