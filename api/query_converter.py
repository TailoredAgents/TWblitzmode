"""
SQL Query converter for PostgreSQL compatibility
Automatically converts SQLite queries to PostgreSQL when needed
"""
import os
import re

from api.database import _convert_placeholders

def is_postgres() -> bool:
    """Check if we're using PostgreSQL"""
    db_url = os.getenv("DATABASE_URL", "")
    return db_url.startswith("postgres://") or db_url.startswith("postgresql://")

def convert_query(query: str) -> str:
    """Convert SQLite query to PostgreSQL if needed"""
    if not is_postgres():
        return query
    
    # Replace datetime('now') with NOW()
    query = query.replace("datetime('now')", "NOW()")
    query = query.replace("DATETIME('now')", "NOW()")
    
    # Replace CURRENT_TIMESTAMP with NOW() for consistency
    query = query.replace("CURRENT_TIMESTAMP", "NOW()")
    
    # Replace ? placeholders with %s for psycopg2
    # Count the number of ? and replace them with numbered placeholders
    if "?" in query:
        query = _convert_placeholders(query)
    
    # Handle INTEGER PRIMARY KEY -> SERIAL PRIMARY KEY
    query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    query = query.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
    
    # Remove SQLite-specific PRAGMA statements
    if query.strip().upper().startswith("PRAGMA"):
        return "-- " + query  # Comment out PRAGMA statements
    
    return query

def convert_params(params: tuple) -> tuple:
    """Convert parameters if needed (currently just passes through)"""
    return params

# For use with existing code
def execute_query(conn, query: str, params: tuple = None):
    """Execute a query with automatic conversion"""
    query = convert_query(query)
    
    if is_postgres():
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor
    else:
        return conn.execute(query, params)

def fetch_one(conn, query: str, params: tuple = None):
    """Fetch one result with automatic conversion"""
    query = convert_query(query)
    
    if is_postgres():
        import psycopg2.extras
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(query, params)
        result = cursor.fetchone()
        return dict(result) if result else None
    else:
        cursor = conn.execute(query, params)
        result = cursor.fetchone()
        return dict(result) if result else None

def fetch_all(conn, query: str, params: tuple = None):
    """Fetch all results with automatic conversion"""
    query = convert_query(query)
    
    if is_postgres():
        import psycopg2.extras
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(query, params)
        results = cursor.fetchall()
        return [dict(row) for row in results]
    else:
        cursor = conn.execute(query, params)
        results = cursor.fetchall()
        return [dict(row) for row in results]
