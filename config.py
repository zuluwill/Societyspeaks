import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from redis.exceptions import ConnectionError, TimeoutError
from dotenv import load_dotenv
from datetime import timedelta
import os
import logging

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')

    # At start of Config class
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("DATABASE_URL environment variable not set")

    # Add near start of Config class
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)


    # Enhanced Database Connection Settings
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 5,  # Reduced pool size
        'max_overflow': 10,  # Reduced max overflow
        'pool_timeout': 30,
        'connect_args': {
            'connect_timeout': 10,
            'keepalives': 1,
            'keepalives_idle': 60,  # Increased idle time
            'keepalives_interval': 10,
            'keepalives_count': 5
        }
    }
    
    
    # Add to Config class
    LOGGING_CONFIG = {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
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
    SESSION_USE_SIGNER = True  # Adds a layer of security to session cookies
    PERMANENT_SESSION_LIFETIME = timedelta(hours=3)
    # Redis URL will be handled in connection logic below
    SESSION_REDIS_RETRY_ON_TIMEOUT = True
    SESSION_REDIS_RETRY_NUMBER = 5  # Increased retry attempts
    LOG_TO_STDOUT = os.getenv('LOG_TO_STDOUT', 'False').lower() == 'true'

    # Add session directory for filesystem fallback
    SESSION_FILE_DIR = './flask_session'
    
    # Use Redis for session management with connection pooling and better error handling
    redis_url = os.getenv('REDIS_URL')
    if redis_url:
        try:
            # Validate and clean up Redis URL
            redis_url = redis_url.strip()
            if not redis_url.startswith(('redis://', 'rediss://')):
                logging.warning(f"Invalid Redis URL format: {redis_url}, falling back to filesystem sessions")
                raise ValueError("Invalid Redis URL format")
            
            # Configure Redis connection pool with more conservative parameters
            redis_pool = redis.ConnectionPool.from_url(
                redis_url,
                max_connections=20,  # Further reduced to prevent connection issues
                socket_timeout=10.0,  # Reduced timeout for quicker fallback
                socket_connect_timeout=5.0,  # Reduced connect timeout
                socket_keepalive=True,
                # Remove socket_keepalive_options to prevent "Invalid argument" errors
                health_check_interval=60,  # Less frequent health checks to reduce load
                retry_on_timeout=True
            )
            
            # Configure Redis client with simpler retry mechanism
            SESSION_REDIS = redis.Redis(
                connection_pool=redis_pool,
                retry=Retry(ExponentialBackoff(0.1), 3),  # Simpler backoff, fewer retries
                retry_on_error=[TimeoutError, ConnectionError],  # Retry on these errors
                socket_timeout=10.0,
                socket_connect_timeout=5.0
            )
            
            # Test connection with timeout
            SESSION_REDIS.ping()  # Will raise an exception if connection fails
            logging.info("Redis connection established successfully")
            # Set Redis URL for rate limiting
            REDIS_URL = redis_url
            RATELIMIT_STORAGE_URL = redis_url  # Use validated Redis URL
        except Exception as e:
            logging.warning(f"Failed to connect to Redis ({redis_url}): {e}, falling back to filesystem sessions")
            SESSION_TYPE = 'filesystem'  # Fallback to filesystem sessions
            SESSION_REDIS = None
            REDIS_URL = None
            RATELIMIT_STORAGE_URL = 'memory://'  # Use memory fallback for rate limiting
    else:
        logging.info("No REDIS_URL provided, using filesystem sessions")
        SESSION_TYPE = 'filesystem'  # Explicitly set filesystem sessions
        SESSION_REDIS = None
        REDIS_URL = None
        RATELIMIT_STORAGE_URL = 'memory://'  # Use memory fallback for rate limiting

    # Mail Configuration
    MAIL_SERVER = 'smtp.googlemail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.getenv('EMAIL_USER')
    MAIL_PASSWORD = os.getenv('EMAIL_PASS')
    MAIL_DEFAULT_SENDER = os.getenv('EMAIL_USER')
    LOOPS_API_KEY = os.getenv('LOOPS_API_KEY')

    # Admin Configuration
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@example.com')
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')

    # Admin Security Settings
    ADMIN_LOGIN_ATTEMPTS = int(os.getenv('ADMIN_LOGIN_ATTEMPTS', '3'))  # Max failed login attempts
    ADMIN_LOGIN_TIMEOUT = int(os.getenv('ADMIN_LOGIN_TIMEOUT', '1800'))  # Timeout in seconds (30 minutes)

    # Admin Features Control
    ADMIN_CAN_CREATE_USERS = os.getenv('ADMIN_CAN_CREATE_USERS', 'False').lower() == 'true'
    ADMIN_CAN_DELETE_USERS = os.getenv('ADMIN_CAN_DELETE_USERS', 'False').lower() == 'true'
    ADMIN_CAN_EDIT_PROFILES = os.getenv('ADMIN_CAN_EDIT_PROFILES', 'False').lower() == 'true'
    ADMIN_CAN_DELETE_DISCUSSIONS = os.getenv('ADMIN_CAN_DELETE_DISCUSSIONS', 'False').lower() == 'true'
    
    # Webhook Security Configuration - temporarily optional in production
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
    if not WEBHOOK_SECRET and os.getenv('FLASK_ENV') == 'production':
        # Temporarily allow missing WEBHOOK_SECRET in production with warning
        logging.warning("WEBHOOK_SECRET environment variable not set in production - this is a temporary fallback. Please set it ASAP for security.")
        WEBHOOK_SECRET = None  # Will be handled gracefully by webhook verification code
    elif not WEBHOOK_SECRET:
        WEBHOOK_SECRET = 'dev-webhook-secret-change-in-production'  # Development only
    
    # Rate Limiting Configuration - set after Redis validation above
    # Will be updated based on actual Redis availability
    RATELIMIT_STORAGE_URL = 'memory://'  # Default fallback
    RATELIMIT_DEFAULT = "1000 per hour"  # Default rate limit
    
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
    PREFERRED_URL_SCHEME = 'https'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=60)  # Shorter session timeout for production
    SENTRY_DSN = os.getenv('SENTRY_DSN')
    CACHE_DEFAULT_TIMEOUT = 300  # 5 minutes
    ADMIN_LOGIN_ATTEMPTS = int(os.getenv('ADMIN_LOGIN_ATTEMPTS', '3'))
    ADMIN_LOGIN_TIMEOUT = int(os.getenv('ADMIN_LOGIN_TIMEOUT', '1800'))



# Dictionary to easily access configurations
config_dict = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
}