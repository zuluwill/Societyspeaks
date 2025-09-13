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
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    SESSION_REDIS_RETRY_ON_TIMEOUT = True
    SESSION_REDIS_RETRY_NUMBER = 5  # Increased retry attempts
    LOG_TO_STDOUT = os.getenv('LOG_TO_STDOUT', 'False').lower() == 'true'

    # Add session directory for filesystem fallback
    SESSION_FILE_DIR = './flask_session'
    
    # Use Redis for session management with connection pooling and better error handling
    if os.getenv('REDIS_URL'):
        try:
            # Configure Redis connection pool with proper parameters
            redis_pool = redis.ConnectionPool.from_url(
                os.getenv('REDIS_URL'),
                max_connections=50,  # Reduced to prevent overwhelming cloud provider
                socket_timeout=30.0,  # Increased to 30 seconds for cloud latency
                socket_connect_timeout=10.0,  # Increased connect timeout
                socket_keepalive=True,
                socket_keepalive_options={
                    1: 1,  # TCP_KEEPIDLE - start keepalive after 1 second
                    2: 10,  # TCP_KEEPINTVL - interval between keepalive probes
                    3: 5,   # TCP_KEEPCNT - failed keepalive probes before giving up
                },
                health_check_interval=30,  # Less frequent health checks for cloud
            )
            
            # Configure Redis client with proper retry mechanism
            SESSION_REDIS = redis.Redis(
                connection_pool=redis_pool,
                retry=Retry(ExponentialBackoff(0.5), 5),  # Exponential backoff starting at 0.5s, max 5 retries
                retry_on_error=[TimeoutError, ConnectionError],  # Retry on these errors
                socket_timeout=30.0,
                socket_connect_timeout=10.0
            )
            
            # Test connection before assigning
            SESSION_REDIS.ping()  # Will raise an exception if connection fails
            logging.info("Redis connection established successfully")
        except Exception as e:
            logging.warning(f"Failed to connect to Redis: {e}, falling back to filesystem sessions")
            SESSION_TYPE = 'filesystem'  # Fallback to filesystem sessions
            SESSION_REDIS = None

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