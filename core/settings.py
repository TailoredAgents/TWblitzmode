from pydantic_settings import BaseSettings
from typing import Optional, List
import os

class Settings(BaseSettings):
    # Apify Configuration (optional for dev/fallback runs)
    APIFY_TOKEN: Optional[str] = None
    APIFY_ACTOR_ID: str = "saswave~linkedin-mutual-connections-parser"
    APIFY_WEBHOOK_SECRET: Optional[str] = None
    WEBHOOK_SECRET: Optional[str] = None
    PHANTOMBUSTER_WEBHOOK_SECRET: Optional[str] = None
    OUTREACH_WEBHOOK_SECRET: Optional[str] = None
    BATCH_WEBHOOK_SECRET: Optional[str] = None
    
    # LinkedIn Authentication for Apify - Choose ONE approach:
    # A) Use Apify secret store (recommended for production)
    APIFY_LI_COOKIE_SECRET_NAME: Optional[str] = None
    
    # OR B) Pass raw cookies directly (testing only)
    APIFY_LI_AT: Optional[str] = None
    APIFY_JSESSIONID: Optional[str] = None

    # PhantomBuster Configuration (fallback)
    # Make optional so the app can boot on Render even if the secret
    # isn't provided during Blueprint creation. Endpoints that require
    # it already check at runtime and return 400 if missing.
    PHANTOMBUSTER_API_KEY: Optional[str] = None
    PB_LINKEDIN_SEARCH_EXPORT_ID: Optional[str] = None           # Standard LinkedIn Search Export
    PB_LINKEDIN_CONNECTIONS_EXPORT_ID: Optional[str] = None     # LinkedIn Connections Export
    PB_PROFILE_SCRAPER_ID: str = "8456783857463914"                 # LinkedIn Profile Scraper (universal)
    PB_LINKEDIN_MESSAGE_SENDER_ID: str = "7337341487627069"  # LinkedIn Message Sender
    
    # Legacy environment variable support
    LINKEDIN_CONNECTIONS_PHANTOM_ID: Optional[str] = None
    LINKEDIN_SEARCH_PHANTOM_ID: Optional[str] = None
    LINKEDIN_SESSION_COOKIE: Optional[str] = None

    # Application Configuration
    APP_BASE_URL: str = "http://localhost:8888"
    CLIENT_NAME: str = os.getenv("CLIENT_NAME", "Tallwave")
    DEFAULT_ORGANIZATION_SLUG: str = "tallwave"
    DEFAULT_ORGANIZATION_DOMAIN: str = "tallwave.com"
    DEFAULT_POSTGRES_DSN: str = "postgresql://tallwave:tallwave@localhost:5432/tallwave_introducer"
    DATABASE_URL: str = DEFAULT_POSTGRES_DSN
    DATABASE_PATH: str = DEFAULT_POSTGRES_DSN  # legacy fallback for code still referencing DATABASE_PATH
    DATABASE_SLOW_QUERY_THRESHOLD_MS: Optional[int] = 250
    DATABASE_POOL_LOGGING_INTERVAL_SECONDS: int = 60
    DATABASE_MAINTENANCE_WINDOW: str = "sunday 03:00"
    ENVIRONMENT: str = "development"
    COMPANY_PORTAL_PRIMARY_DOMAIN: Optional[str] = None
    COMPANY_PORTAL_ALLOW_LEGACY_REGISTER: bool = False
    COMPANY_PORTAL_AUTO_NUDGE_ENABLED: bool = True
    COMPANY_PORTAL_AUTO_NUDGE_COOLDOWN_SECONDS: int = 86400
    COMPANY_PORTAL_AUTO_NUDGE_INTERVAL_MINUTES: int = 30
    COMPANY_PORTAL_SEAT_REQUEST_ALERT_EMAILS: Optional[str] = None
    COMPANY_PORTAL_DEV_REGISTRATION_ENABLED: bool = True
    COMPANY_PORTAL_DEV_MAX_SEATS: Optional[int] = None
    COMPANY_PORTAL_UNLIMITED_SEATS: bool = True
    COMPANY_PORTAL_ALLOW_BILLINGLESS_REGISTRATION: bool = True
    COMPANY_PORTAL_DEV_DB_PATH: str = "db/company_portal_dev.db"
    COMPANY_PORTAL_ALLOWED_DEV_DOMAINS: Optional[str] = None

    # Email Integration Settings
    # CUFinder Configuration
    CUFINDER_API_KEY: Optional[str] = None
    
    # SendGrid Configuration  
    SENDGRID_API_KEY: Optional[str] = None
    SENDGRID_WEBHOOK_VERIFICATION_KEY: Optional[str] = None
    SENDGRID_PASSWORD_RESET_TEMPLATE_ID: Optional[str] = None
    SENDGRID_ONBOARDING_NUDGE_TEMPLATE_ID: Optional[str] = None
    DEFAULT_FROM_EMAIL: str = "noreply@example.com"
    DEFAULT_FROM_NAME: str = "Tallwave Introducer Platform"
    SUPPORT_CONTACT_EMAIL: Optional[str] = None

    # OpenAI Configuration
    OPENAI_API_KEY: Optional[str] = None
    # Primary model lock for all AI decisions. PRIMARY_MODEL takes precedence when provided.
    PRIMARY_MODEL: str = os.environ.get("PRIMARY_MODEL", "gpt-4.1")
    OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", os.environ.get("PRIMARY_MODEL", "gpt-4.1"))
    OPENAI_AGENTS_ENABLED: bool = False
    
    # Job Configuration
    APIFY_TIMEOUT_SECONDS: int = 300  # 5 minutes
    PHANTOMBUSTER_TIMEOUT_SECONDS: int = 600  # 10 minutes
    MAX_CONCURRENT_JOBS: int = 2
    
    # Ranking Configuration
    DEFAULT_STRENGTH_SCORE: float = 0.5
    RECENCY_BOOST_30_DAYS: float = 0.4
    RECENCY_BOOST_90_DAYS: float = 0.25
    RECENCY_BOOST_365_DAYS: float = 0.1
    TRUSTED_TAG_BOOST: float = 0.3
    
    # Outreach Configuration
    OUTREACH_DAILY_LIMIT: int = 25           # Messages per day
    OUTREACH_BATCH_SIZE: int = 5             # Recipients per PhantomBuster run
    OUTREACH_RANDOM_DELAY_MIN: int = 60      # Min delay between messages (seconds)
    OUTREACH_RANDOM_DELAY_MAX: int = 180     # Max delay between messages (seconds)
    
    # Warm-up Configuration
    WARMUP_VISITOR_TOP_N: int = 3            # Top N profiles to visit
    WARMUP_DELAY_HOURS: int = 24             # Hours to wait before messaging (24-48 ideal)
    WARMUP_DAILY_LIMIT: int = 50             # Profile visits per day
    
    # Provider Health Configuration  
    PROVIDER_COOLDOWN_HOURS: int = 2         # Hours to cool down after errors
    MUTUALS_TTL_DAYS: int = 14               # Days to cache mutuals before re-scrape
    
    # Batch Processing Configuration
    BATCH_WARMUP_SIZE: int = 10              # Warm-up visits per batch
    BATCH_OUTREACH_SIZE: int = 5             # Messages per batch
    BATCH_SCRAPING_SIZE: int = 15            # Profile scrapes per batch
    BATCH_MIN_DELAY_MINUTES: int = 15        # Minimum delay between batches
    BATCH_MAX_CONCURRENT: int = 2            # Maximum concurrent batches per type
    BATCH_CLEANUP_DAYS: int = 7              # Days to keep batch records
    
    # PhantomBuster Phantom IDs for new features
    PB_PROFILE_VISITOR_ID: str = "4892"      # LinkedIn Profile Visitor phantom
    PB_LINKEDIN_MESSAGE_SENDER_ID: str = "7337341487627069"  # LinkedIn Message Sender phantom
    
    # Feature Flags & Deployment Controls
    FEATURE_FLAGS: Optional[str] = None
    ENABLE_LEGACY_INTRODUCERS: bool = False
    ENABLE_AUTOMATION_WORKFLOWS: bool = False
    LEGACY_AUTOMATION_RATE_LIMIT_PER_MINUTE: int = 10
    PLAYGROUND_MODE: bool = False
    

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = 'ignore'  # Allow extra fields from .env

settings = Settings()

# Belt and suspenders: normalize OPENAI_MODEL to PRIMARY_MODEL if provided and mismatched
try:
    if settings.PRIMARY_MODEL and settings.OPENAI_MODEL != settings.PRIMARY_MODEL:
        # Prefer PRIMARY_MODEL to avoid drift
        settings.OPENAI_MODEL = settings.PRIMARY_MODEL
except Exception:
    # Do not fail import; downstream validation will enforce in production
    pass
