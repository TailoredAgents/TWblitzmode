import logging
from typing import Optional

from scripts.utils.postgres import (
    DEFAULT_TEST_DSN,
    ensure_database_exists,
    resolve_required_dsn,
    run_all_migrations,
)

logger = logging.getLogger(__name__)


def _resolve_dsn() -> str:
    """
    Resolve the database connection string for schema management.

    Preference order:
        1. DATABASE_URL
        2. TEST_DATABASE_URL
        3. DEFAULT_TEST_DSN (local developer default)
    """
    return resolve_required_dsn("DATABASE_URL", "TEST_DATABASE_URL", default=DEFAULT_TEST_DSN)


def ensure_schema() -> bool:
    """
    Ensure the PostgreSQL schema required by the legacy introducers API exists.

    Returns True when migrations succeed, False when a fatal error is encountered.
    """
    try:
        dsn = _resolve_dsn()
        logger.info("Ensuring PostgreSQL schema using DSN: %s", dsn)
        ensure_database_exists(dsn)
        run_all_migrations(dsn)
        logger.info("PostgreSQL schema verified successfully.")
        return True
    except Exception as exc:  # pragma: no cover - safety net for startup
        logger.error("Failed to ensure PostgreSQL schema: %s", exc, exc_info=True)
        return False


def normalize_linkedin_url(url: str) -> str:
    """
    Normalize LinkedIn URLs for consistent storage and deduplication.
    """
    if not url:
        return ""

    clean_url = url.strip().lower()

    # Remove query parameters and fragments
    clean_url = clean_url.split("?")[0].split("#")[0]

    # Remove trailing slashes
    clean_url = clean_url.rstrip("/")

    if "linkedin.com" not in clean_url:
        return ""

    # Ensure https protocol
    if clean_url.startswith("linkedin.com"):
        clean_url = f"https://{clean_url}"
    elif clean_url.startswith("www.linkedin.com"):
        clean_url = f"https://{clean_url}"
    elif clean_url.startswith("http://"):
        clean_url = clean_url.replace("http://", "https://")
    elif not clean_url.startswith("https://"):
        clean_url = f"https://{clean_url}"

    clean_url = clean_url.replace("www.linkedin.com", "linkedin.com")
    clean_url = clean_url.replace("http://linkedin.com", "https://linkedin.com")

    import re

    patterns = [
        r"https://linkedin\.com/in/([^/?]+)",
        r"https://linkedin\.com/profile/view\?id=([^&]+)",
        r"https://linkedin\.com/pub/[^/]+/[^/]+/[^/]+/([^/?]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, clean_url)
        if match:
            slug = re.sub(r"[^a-z0-9\-]", "", match.group(1))
            if slug:
                return f"https://linkedin.com/in/{slug}"

    return clean_url


def extract_linkedin_username(url: str) -> str:
    """Extract LinkedIn username from a profile URL."""
    import re

    normalized = normalize_linkedin_url(url)
    match = re.search(r"/in/([^/?]+)", normalized)
    return match.group(1) if match else ""

