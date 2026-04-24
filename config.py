import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from redis.exceptions import ConnectionError, TimeoutError
from cachelib.file import FileSystemCache
from dotenv import load_dotenv
from datetime import timedelta
import json
import os
import logging

load_dotenv()


def _env_int(name, default):
    """Parse an integer env var safely, logging and falling back on bad input."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        logging.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _env_optional_file_mode(name):
    """Parse optional file mode from env, accepting octal-style values."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return None
    raw = str(raw).strip()
    try:
        return int(raw, 8) if raw.startswith("0") else int(raw)
    except (TypeError, ValueError):
        logging.warning("Invalid %s=%r; ignoring custom file mode", name, raw)
        return None


def _build_session_cache():
    """Build the cachelib filesystem cache used for non-Redis session fallback."""
    session_dir = os.path.abspath(os.getenv('SESSION_FILE_DIR', './flask_session'))
    threshold = _env_int('SESSION_FILE_THRESHOLD', 500)
    mode = _env_optional_file_mode('SESSION_FILE_MODE')
    return FileSystemCache(cache_dir=session_dir, threshold=threshold, mode=mode)

_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')

    # Flask-Babel: absolute path so catalogs resolve regardless of process CWD
    BABEL_TRANSLATION_DIRECTORIES = os.path.join(_CONFIG_DIR, 'translations')
    
    # Application base URL (APP_BASE_URL takes priority, falls back to BASE_URL env var)
    APP_BASE_URL = os.getenv('APP_BASE_URL') or os.getenv('BASE_URL', 'https://societyspeaks.io')
    BASE_URL = APP_BASE_URL

    # Partner Embed Configuration
    # Comma-separated list of allowed partner origins for CORS and frame-ancestors
    # Example: PARTNER_ORIGINS=https://www.theguardian.com,https://observer.com,https://staging.theguardian.com
    _partner_origins_str = os.getenv('PARTNER_ORIGINS', '')
    PARTNER_ORIGINS = [o.strip() for o in _partner_origins_str.split(',') if o.strip()]

    # Feature flag to enable/disable embed functionality
    EMBED_ENABLED = os.getenv('EMBED_ENABLED', 'true').lower() == 'true'

    # Background Claude Haiku translation for dynamic content (app/lib/translation_worker.py).
    # Ingested news → discussions (DiscussionSourceArticle) can dominate token use; tune with allowlist / skip flags.
    # Default off (cost); set MACHINE_TRANSLATION_ENABLED=true to re-enable.
    MACHINE_TRANSLATION_ENABLED = os.getenv('MACHINE_TRANSLATION_ENABLED', 'false').lower() == 'true'
    _mt_lang_codes = os.getenv('MACHINE_TRANSLATION_LANGUAGE_CODES', '').strip()
    MACHINE_TRANSLATION_LANGUAGE_CODES = [
        x.strip().lower()[:10] for x in _mt_lang_codes.split(',') if x.strip()
    ] or None  # None = all supported non-English locales
    MACHINE_TRANSLATION_SKIP_NEWS_SOURCED_DISCUSSIONS = (
        os.getenv('MACHINE_TRANSLATION_SKIP_NEWS_SOURCED_DISCUSSIONS', 'false').lower() == 'true'
    )

    # Optional: comma-separated list of partner refs that are disabled (embed and API return 403/unavailable)
    # Example: DISABLED_PARTNER_REFS=bad-actor,revoked-partner
    # Also: Partner.embed_disabled (DB) per slug — no redeploy required; see Admin → Partners.
    _disabled_refs = os.getenv('DISABLED_PARTNER_REFS', '')
    DISABLED_PARTNER_REFS = [r.strip().lower() for r in _disabled_refs.split(',') if r.strip()]

    # Optional: discussion ID to show "See example embed" on the partner hub (e.g. DEMO_DISCUSSION_ID=123)
    _demo_id = os.getenv('DEMO_DISCUSSION_ID', '').strip()
    DEMO_DISCUSSION_ID = int(_demo_id) if _demo_id.isdigit() else None

    # Guided "big questions" flagship programmes (progress UI, recap, daily-question boost).
    # GUIDED_JOURNEY_PROGRAMME_SLUGS (comma-separated) overrides all per-country keys when set.
    GUIDED_JOURNEY_PROGRAMME_SLUG    = (os.getenv('GUIDED_JOURNEY_PROGRAMME_SLUG')    or 'humanity-big-questions').strip().lower()
    GUIDED_JOURNEY_PROGRAMME_SLUGS   = os.getenv('GUIDED_JOURNEY_PROGRAMME_SLUGS', '').strip()
    GUIDED_JOURNEY_UK_PROGRAMME_SLUG = (os.getenv('GUIDED_JOURNEY_UK_PROGRAMME_SLUG') or 'humanity-big-questions-uk').strip().lower()
    GUIDED_JOURNEY_US_PROGRAMME_SLUG = (os.getenv('GUIDED_JOURNEY_US_PROGRAMME_SLUG') or 'humanity-big-questions-us').strip().lower()
    GUIDED_JOURNEY_NL_PROGRAMME_SLUG = (os.getenv('GUIDED_JOURNEY_NL_PROGRAMME_SLUG') or 'humanity-big-questions-nl').strip().lower()
    GUIDED_JOURNEY_IE_PROGRAMME_SLUG = (os.getenv('GUIDED_JOURNEY_IE_PROGRAMME_SLUG') or 'humanity-big-questions-ie').strip().lower()
    GUIDED_JOURNEY_DE_PROGRAMME_SLUG = (os.getenv('GUIDED_JOURNEY_DE_PROGRAMME_SLUG') or 'humanity-big-questions-de').strip().lower()
    GUIDED_JOURNEY_FR_PROGRAMME_SLUG = (os.getenv('GUIDED_JOURNEY_FR_PROGRAMME_SLUG') or 'humanity-big-questions-fr').strip().lower()
    GUIDED_JOURNEY_CA_PROGRAMME_SLUG = (os.getenv('GUIDED_JOURNEY_CA_PROGRAMME_SLUG') or 'humanity-big-questions-ca').strip().lower()
    GUIDED_JOURNEY_SG_PROGRAMME_SLUG = (os.getenv('GUIDED_JOURNEY_SG_PROGRAMME_SLUG') or 'humanity-big-questions-sg').strip().lower()
    GUIDED_JOURNEY_JP_PROGRAMME_SLUG = (os.getenv('GUIDED_JOURNEY_JP_PROGRAMME_SLUG') or 'humanity-big-questions-jp').strip().lower()
    GUIDED_JOURNEY_CN_PROGRAMME_SLUG = (os.getenv('GUIDED_JOURNEY_CN_PROGRAMME_SLUG') or 'humanity-big-questions-cn').strip().lower()

    # Legacy config-key fallback for partner API auth (JSON object: {"key": "partner-slug"}).
    # Best practice is DB-backed portal-issued keys; this fallback is disabled by default.
    # Enable only during migration windows, then remove legacy keys.
    _partner_keys_str = os.getenv('PARTNER_API_KEYS', '{}')
    try:
        PARTNER_API_KEYS = json.loads(_partner_keys_str) if isinstance(_partner_keys_str, str) else _partner_keys_str
    except (ValueError, TypeError):
        PARTNER_API_KEYS = {}
    ALLOW_LEGACY_PARTNER_API_KEYS = os.getenv('ALLOW_LEGACY_PARTNER_API_KEYS', 'false').lower() == 'true'

    # Secret for hashing partner API keys (defaults to SECRET_KEY if not set)
    # WARNING: If SECRET_KEY rotates, all partner API keys become invalid unless PARTNER_KEY_SECRET is set separately
    PARTNER_KEY_SECRET = os.getenv('PARTNER_KEY_SECRET', SECRET_KEY)
    if not os.getenv('PARTNER_KEY_SECRET') and os.getenv('FLASK_ENV') == 'production':
        logging.warning(
            "PARTNER_KEY_SECRET not set - falling back to SECRET_KEY. "
            "Set PARTNER_KEY_SECRET explicitly to avoid invalidating partner API keys when SECRET_KEY rotates."
        )

    # Partner billing – per-tier Stripe Price IDs (GBP monthly recurring)
    PARTNER_STRIPE_PRICE_ID = (os.getenv('PARTNER_STRIPE_PRICE_ID') or '').strip() or None  # legacy fallback
    PARTNER_STRIPE_PRICES = {
        'starter':      (os.getenv('PARTNER_STRIPE_PRICE_STARTER') or '').strip() or None,       # £49/mo
        'professional': (os.getenv('PARTNER_STRIPE_PRICE_PROFESSIONAL') or '').strip() or None,  # £249/mo
        # Enterprise is "contact us" / manual invoicing — no self-serve checkout
    }

    # Discussion limits per tier (per calendar month)
    PARTNER_TIER_LIMITS = {
        'free':         25,    # test only
        'starter':      100,
        'professional': 500,
        'enterprise':   None,  # unlimited
    }
    PARTNER_INVITE_EXPIRY_DAYS = int(os.getenv('PARTNER_INVITE_EXPIRY_DAYS', '7'))

    # At start of Config class
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("DATABASE_URL environment variable not set")

    # Add near start of Config class
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)


    # Stripe billing configuration
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
    STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')
    DONATION_MIN_AMOUNT_PENCE = int(os.getenv('DONATION_MIN_AMOUNT_PENCE', '100'))  # GBP 1.00 minimum

    # Enhanced Database Connection Settings (configurable for scaling)
    # When using Neon's PgBouncer pooler ("-pooler" in DATABASE_URL hostname), SQLAlchemy's
    # own pool sits in front of PgBouncer, so smaller sizes are appropriate — the pooler
    # handles multiplexing to the real database.
    _using_pooler = '-pooler' in (os.getenv('DATABASE_URL') or '')
    _default_pool_size = '5' if _using_pooler else '10'
    _default_max_overflow = '10' if _using_pooler else '20'

    DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', _default_pool_size))
    DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', _default_max_overflow))
    DB_POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', '30'))  # Seconds to wait for connection
    DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', '300'))  # Recycle connections after N seconds

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    _connect_args = {
        'connect_timeout': 10,
        'keepalives': 1,
        'keepalives_idle': 30,   # was 60 — fire sooner so Neon drops are caught faster
        'keepalives_interval': 10,
        'keepalives_count': 3,   # was 5 — fail faster on a dead link
    }

    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,  # Verify connections before use (prevents stale connection errors)
        'pool_recycle': DB_POOL_RECYCLE,
        'pool_size': DB_POOL_SIZE,
        'max_overflow': DB_MAX_OVERFLOW,
        'pool_timeout': DB_POOL_TIMEOUT,
        'connect_args': _connect_args,
    }
    
    
    # Add to Config class
    LOGGING_CONFIG = {
        'version': 1,
        'disable_existing_loggers': False,
        'filters': {
            'request_id': {
                '()': 'app.lib.logging_utils.RequestIdFilter',
            },
        },
        'formatters': {
            'default': {
                'format': '%(asctime)s [%(levelname)s] [rid=%(request_id)s] %(name)s: %(message)s',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'filters': ['request_id'],
                'formatter': 'default',
            },
        },
        'root': {
            'handlers': ['console'],
            'level': 'INFO',
        }
    }

    # Add to Config class 
    DB_RETRY_ATTEMPTS = 3
    DB_RETRY_DELAY = 1  # seconds

    # Use Redis for session management
    SESSION_TYPE = 'redis'
    SESSION_PERMANENT = True
    # Server-side sessions do not need signed session IDs; the random SID length
    # provides the relevant entropy and avoids deprecated Flask-Session config.
    SESSION_ID_LENGTH = _env_int('SESSION_ID_LENGTH', 32)
    # 24 hours keeps users logged in across a normal day without forcing
    # frequent re-authentication; adjust upward for "remember me" style UX.
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_REDIS_RETRY_ON_TIMEOUT = True
    SESSION_REDIS_RETRY_NUMBER = 3
    LOG_TO_STDOUT = os.getenv('LOG_TO_STDOUT', 'False').lower() == 'true'

    # CacheLib-backed filesystem fallback used when Redis is unavailable in
    # non-production. This replaces the deprecated SESSION_FILE_* settings.
    SESSION_CACHELIB = _build_session_cache()

    _redis_url = os.getenv('REDIS_URL')
    _is_production = os.getenv('FLASK_ENV') == 'production'

    # Hard-fail in production if Redis is not configured.
    # Redis is required for sessions, distributed rate limiting, distributed
    # locks, and the briefing job queue.  A filesystem/memory fallback is
    # acceptable in development but would silently degrade all of those
    # subsystems in production.
    if not _redis_url and _is_production:
        raise RuntimeError(
            "REDIS_URL is not set. Redis is required in production for sessions, "
            "rate limiting, distributed locks, and the job queue. "
            "Set REDIS_URL in Replit secrets (use a rediss:// TLS URL from Upstash or similar)."
        )

    if _redis_url:
        _redis_url = _redis_url.strip()
        try:
            if not _redis_url.startswith(('redis://', 'rediss://')):
                raise ValueError(f"Invalid Redis URL scheme: {_redis_url}")

            # Warn loudly if unencrypted Redis is used in production.
            # Managed HA providers (Upstash, Redis Cloud) always provide rediss://.
            if _is_production and _redis_url.startswith('redis://'):
                logging.warning(
                    "REDIS_URL uses unencrypted redis:// in production. "
                    "Switch to rediss:// (TLS) — all managed HA providers support it."
                )

            # Pool sizing for gevent workers:
            # Each gunicorn worker runs up to worker_connections=1000 greenlets.
            # Redis ops complete in ~1-3 ms, so sustained concurrency against the
            # pool is low, but spikes during traffic bursts can exhaust a small pool
            # and cause greenlets to wait for a connection.  100 connections per
            # worker is a safe upper bound without over-subscribing the Redis server.
            redis_pool = redis.ConnectionPool.from_url(
                _redis_url,
                max_connections=int(os.getenv('REDIS_MAX_CONNECTIONS', '100')),
                # Fail fast: 3 s to establish, 3 s per operation.
                # The Retry wrapper below handles transient failures.
                socket_connect_timeout=2.0,
                socket_timeout=3.0,
                socket_keepalive=True,
                # Re-validate idle connections every 30 s so stale sockets from
                # a Redis failover are detected and replaced quickly.
                health_check_interval=30,
                retry_on_timeout=True,
            )

            SESSION_REDIS = redis.Redis(
                connection_pool=redis_pool,
                # Exponential backoff capped at 500 ms; 3 attempts covers a
                # transient network blip or HA failover without hanging for long.
                retry=Retry(ExponentialBackoff(cap=0.5, base=0.05), 3),
                retry_on_error=[TimeoutError, ConnectionError],
            )

            SESSION_REDIS.ping()
            logging.info("Redis connection established successfully")
            REDIS_URL = _redis_url
            RATELIMIT_STORAGE_URL = _redis_url
            RATELIMIT_STORAGE_URI = RATELIMIT_STORAGE_URL
        except Exception as e:
            if _is_production:
                # Re-raise: a production process must not silently degrade.
                raise RuntimeError(
                    f"Failed to connect to Redis at startup ({e}). "
                    "Resolve the Redis connectivity issue before deploying."
                ) from e
            logging.warning(
                f"Failed to connect to Redis ({e}), falling back to cachelib filesystem sessions. "
                "This is acceptable in development but must not happen in production."
            )
            SESSION_TYPE = 'cachelib'
            SESSION_REDIS = None
            REDIS_URL = None
            RATELIMIT_STORAGE_URL = 'memory://'
            RATELIMIT_STORAGE_URI = RATELIMIT_STORAGE_URL
    else:
        logging.info("No REDIS_URL provided, using cachelib filesystem sessions (development mode)")
        SESSION_TYPE = 'cachelib'
        SESSION_REDIS = None
        REDIS_URL = None
        RATELIMIT_STORAGE_URL = 'memory://'
        RATELIMIT_STORAGE_URI = RATELIMIT_STORAGE_URL

    # ===========================================================================
    # EMAIL CONFIGURATION
    # ===========================================================================
    
    # Resend API (Primary email provider - used for all transactional emails)
    RESEND_API_KEY = os.getenv('RESEND_API_KEY')
    RESEND_FROM_EMAIL = os.getenv('RESEND_FROM_EMAIL', 'Society Speaks <hello@societyspeaks.io>')
    RESEND_DAILY_FROM_EMAIL = os.getenv('RESEND_DAILY_FROM_EMAIL', 'Daily Questions <daily@societyspeaks.io>')
    # Optional: align auth-email From with link domain (see ResendEmailClient).
    RESEND_TRANSACTIONAL_FROM_EMAIL = os.getenv('RESEND_TRANSACTIONAL_FROM_EMAIL')
    RESEND_REPLY_TO = os.getenv('RESEND_REPLY_TO')
    
    # Validate Resend API key in production
    if not RESEND_API_KEY and os.getenv('FLASK_ENV') == 'production':
        logging.warning("RESEND_API_KEY not set in production - email sending will fail")

    # If false, ignore Resend `email.clicked` webhooks (use first-party click routes only
    # or Resend domain click tracking off). Default true for backward compatibility.
    EMAIL_ANALYTICS_RECORD_RESEND_WEBHOOK_CLICKS = (
        os.getenv("EMAIL_ANALYTICS_RECORD_RESEND_WEBHOOK_CLICKS", "true").lower() == "true"
    )

    # Legacy SMTP Configuration (kept for backwards compatibility, not actively used)
    MAIL_SERVER = 'smtp.googlemail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.getenv('EMAIL_USER')
    MAIL_PASSWORD = os.getenv('EMAIL_PASS')
    MAIL_DEFAULT_SENDER = os.getenv('EMAIL_USER')

    # Admin Configuration
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@example.com')
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')

    # ===========================================================================
    # SOCIAL MEDIA CONFIGURATION
    # ===========================================================================
    
    # Bluesky (AT Protocol) - for automatic posting
    BLUESKY_HANDLE = os.getenv('BLUESKY_HANDLE', 'societyspeaks.bsky.social')
    BLUESKY_APP_PASSWORD = os.getenv('BLUESKY_APP_PASSWORD')
    
    # X/Twitter API - for automatic posting
    # Get these from https://developer.x.com/portal
    X_API_KEY = os.getenv('X_API_KEY')  # Consumer API key
    X_API_SECRET = os.getenv('X_API_SECRET')  # Consumer API secret
    X_ACCESS_TOKEN = os.getenv('X_ACCESS_TOKEN')  # Access token for @societyspeaksio
    X_ACCESS_TOKEN_SECRET = os.getenv('X_ACCESS_TOKEN_SECRET')  # Access token secret
    
    # Validate X credentials in production (optional - posts will be skipped if not set)
    if os.getenv('FLASK_ENV') == 'production':
        if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET]):
            logging.info("X API credentials not fully configured - X posting will be skipped")

    # Admin Security Settings
    ADMIN_LOGIN_ATTEMPTS = int(os.getenv('ADMIN_LOGIN_ATTEMPTS', '3'))  # Max failed login attempts
    ADMIN_LOGIN_TIMEOUT = int(os.getenv('ADMIN_LOGIN_TIMEOUT', '1800'))  # Timeout in seconds (30 minutes)
    
    # Spam Detection Patterns
    SPAM_PATTERNS = [
        'bitcoin', 'btc', 'binance', 'crypto', 'telegra.ph',
        '📍', '📌', '🔑', '📫', '📪', '📬', '📭', '📮', '📯',
        '📜', '📃', '📄', '📑', '📊', '📈', '📉', '📋', '📎',
        '📏', '📐', '🔍', '🔎', '🔏', '🔐', '🔒', '🔓', '🔔', '🔕'
    ]

    # Admin Features Control
    ADMIN_CAN_CREATE_USERS = os.getenv('ADMIN_CAN_CREATE_USERS', 'False').lower() == 'true'
    ADMIN_CAN_DELETE_USERS = os.getenv('ADMIN_CAN_DELETE_USERS', 'False').lower() == 'true'
    ADMIN_CAN_EDIT_PROFILES = os.getenv('ADMIN_CAN_EDIT_PROFILES', 'False').lower() == 'true'
    ADMIN_CAN_DELETE_DISCUSSIONS = os.getenv('ADMIN_CAN_DELETE_DISCUSSIONS', 'False').lower() == 'true'
    
    # Webhook Security Configuration
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
    
    # RATELIMIT_STORAGE_URL is set in the Redis block above (to the Redis URL
    # on success, or 'memory://' on failure/absence). Do not reassign it here.
    RATELIMIT_DEFAULT = "1000 per hour"
    # Ops alert threshold for automated integrity repair job.
    # 0 means alert on any repaired row.
    INTEGRITY_REPAIR_ALERT_THRESHOLD = int(os.getenv('INTEGRITY_REPAIR_ALERT_THRESHOLD', '0'))
    # Counter drift alert threshold based on total absolute drift across statements.
    # 0 means alert on any detected drift before reconciliation.
    COUNTER_DRIFT_ALERT_THRESHOLD = int(os.getenv('COUNTER_DRIFT_ALERT_THRESHOLD', '0'))

    # Discussion scale guardrails and pagination defaults.
    DISCUSSION_STATEMENTS_PER_PAGE = int(os.getenv('DISCUSSION_STATEMENTS_PER_PAGE', '20'))
    EMBED_STATEMENTS_PER_PAGE = int(os.getenv('EMBED_STATEMENTS_PER_PAGE', '25'))
    MAX_STATEMENTS_PER_DISCUSSION = int(os.getenv('MAX_STATEMENTS_PER_DISCUSSION', '5000'))
    # AgglomerativeClustering is O(n²) on participants. At n=5000 participants
    # the linkage matrix is ~200 MB and takes seconds; at n=50k it OOMs.
    # These defaults are conservative upper bounds for a single synchronous run.
    # Raise them only after profiling on your actual cluster hardware.
    MAX_CONSENSUS_FULL_MATRIX_VOTES = int(os.getenv('MAX_CONSENSUS_FULL_MATRIX_VOTES', '100000'))
    MAX_CONSENSUS_FULL_MATRIX_STATEMENTS = int(os.getenv('MAX_CONSENSUS_FULL_MATRIX_STATEMENTS', '2000'))
    MAX_SYNC_ANALYTICS_PARTICIPANTS = int(os.getenv('MAX_SYNC_ANALYTICS_PARTICIPANTS', '5000'))

    # Phase 3 worker separation controls.
    # Default off in scheduler so heavy consensus compute only runs in dedicated workers.
    CONSENSUS_QUEUE_PROCESS_IN_SCHEDULER = os.getenv('CONSENSUS_QUEUE_PROCESS_IN_SCHEDULER', 'false').lower() == 'true'
    CONSENSUS_ALLOW_IN_PROCESS_EXECUTION = os.getenv('CONSENSUS_ALLOW_IN_PROCESS_EXECUTION', 'false').lower() == 'true'
    CONSENSUS_WORKER_IDLE_SLEEP_SECONDS = float(os.getenv('CONSENSUS_WORKER_IDLE_SLEEP_SECONDS', '2.0'))
    CONSENSUS_WORKER_ACTIVE_SLEEP_SECONDS = float(os.getenv('CONSENSUS_WORKER_ACTIVE_SLEEP_SECONDS', '0.2'))
    CONSENSUS_WORKER_METRICS_INTERVAL_SECONDS = int(os.getenv('CONSENSUS_WORKER_METRICS_INTERVAL_SECONDS', '30'))

    # Async programme export queue controls.
    EXPORT_QUEUE_PROCESS_IN_SCHEDULER = os.getenv('EXPORT_QUEUE_PROCESS_IN_SCHEDULER', 'false').lower() == 'true'
    EXPORT_DOWNLOAD_TOKEN_MAX_AGE_SECONDS = int(os.getenv('EXPORT_DOWNLOAD_TOKEN_MAX_AGE_SECONDS', '3600'))
    
class DevelopmentConfig(Config):
    FLASK_ENV = 'development'
    DEBUG = True
    SQLALCHEMY_ECHO = True
    ADMIN_LOGIN_ATTEMPTS = 1000  # Essentially unlimited attempts in development
    ADMIN_LOGIN_TIMEOUT = 86400  # 24 hours timeout in development

class ProductionConfig(Config):
    FLASK_ENV = 'production'
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    PREFERRED_URL_SCHEME = 'https'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    # Lax (not Strict) is required because partners redirect back from Stripe Checkout
    # and need their session cookie sent on the redirect. Strict would drop the session.
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)  # Keep users logged in for a week — 60 min caused excessive re-auth friction
    SENTRY_DSN = os.getenv('SENTRY_DSN')
    CACHE_DEFAULT_TIMEOUT = 300  # 5 minutes
    ADMIN_LOGIN_ATTEMPTS = int(os.getenv('ADMIN_LOGIN_ATTEMPTS', '3'))
    ADMIN_LOGIN_TIMEOUT = int(os.getenv('ADMIN_LOGIN_TIMEOUT', '1800'))



# Dictionary to easily access configurations
config_dict = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
}