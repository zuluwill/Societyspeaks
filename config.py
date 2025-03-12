import redis
from dotenv import load_dotenv
from datetime import timedelta
import os

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
        'pool_size': 10,
        'max_overflow': 20,
        'pool_timeout': 30,
        'connect_args': {
            'connect_timeout': 10,
            'keepalives': 1,
            'keepalives_idle': 30,
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

    # Use Redis for session management with connection pooling and better error handling
    if os.getenv('REDIS_URL'):
        try:
            # Configure Redis with more resilient settings
            redis_pool = redis.ConnectionPool.from_url(
                os.getenv('REDIS_URL'),
                max_connections=100,
                socket_timeout=5.0,  # 5 second socket timeout
                socket_connect_timeout=5.0,  # 5 second connect timeout
                socket_keepalive=True,
                health_check_interval=15,  # Check connection health every 15 seconds
                retry_on_timeout=True
            )
            SESSION_REDIS = redis.Redis(connection_pool=redis_pool)
            
            # Test connection before assigning
            SESSION_REDIS.ping()  # Will raise an exception if connection fails
        except Exception as e:
            print(f"Failed to connect to Redis: {e}")
            SESSION_TYPE = 'filesystem'  # Fallback to filesystem sessions

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