from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_talisman import Talisman
from config import Config, config_dict
from datetime import timedelta
import os
import json
import time
import logging
from logging.config import dictConfig
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from flask_session import Session
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Hardened CSP without unsafe-inline and unsafe-eval
csp = {
    'default-src': ["'self'", "https:", "data:", "blob:"],
    'img-src': ["'self'", "data:", "https:", "blob:"],
    'connect-src': ["'self'", "https:", "wss:", "https://cdn.jsdelivr.net"],
    'font-src': ["'self'", "data:", "https:"],
    'frame-src': ["'self'", "https:"],
    'style-src': [
        "'self'",
        "https://cdn.jsdelivr.net",
        "https://cdnjs.cloudflare.com"
    ],
    'script-src': [
        "'self'",
        "https://cdn.jsdelivr.net",
        "https://cdnjs.cloudflare.com",
        "https://www.googletagmanager.com",
        "https://cdn-cookieyes.com",
        "https://pol.is"
    ],
    'object-src': ["'none'"],
    'base-uri': ["'self'"],
    'form-action': ["'self'"]
}




db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
sess = Session()
cache = Cache()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000 per hour"]
)


def try_connect_db(app, retries=3):
    for attempt in range(retries):
        try:
            with app.app_context():
                db.engine.connect()
                return True
        except Exception as e:
            app.logger.error(f"Database connection attempt {attempt + 1} failed: {e}")
            time.sleep(1)
    return False


def create_app():

    # Check for production environment and initialize Sentry only in production
    if os.getenv("FLASK_ENV") == "production":
        sentry_sdk.init(
            dsn=os.getenv("SENTRY_DSN"),
            integrations=[FlaskIntegration()],
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
            _experiments={
                "continuous_profiling_auto_start": True,
            },
        )


    
    app = Flask(__name__, 
        static_url_path='',
        static_folder='static')

    dictConfig(Config.LOGGING_CONFIG)

    app.config.from_object(Config)

    # Load cities data once during app startup and cache it
    json_path = os.path.join(app.root_path, 'static', 'data', 'cities_by_country.json')
    try:
        with open(json_path, 'r') as f:
            app.config['CITIES_BY_COUNTRY'] = json.load(f)
    except FileNotFoundError:
        app.logger.error(f"Could not find cities_by_country.json at {json_path}")
        app.config['CITIES_BY_COUNTRY'] = {}  # Fallback to empty dict if file not found
    except json.JSONDecodeError as e:
        app.logger.error(f"Error decoding JSON file: {str(e)}")
        app.config['CITIES_BY_COUNTRY'] = {}


    

    # Add these lines near the top of create_app
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['STATIC_FOLDER'] = 'static'

    # Add correct MIME types
    app.config['MIME_TYPES'] = {
        '.js': 'application/javascript',
        '.css': 'text/css',
        '.html': 'text/html',
        '.json': 'application/json',
    }

    # Determine environment
    env = os.getenv('FLASK_ENV', 'development')
    app.config.from_object(config_dict[env])

    # Initialize Talisman with simplified CSP
    Talisman(
        app,
        force_https=env == 'production',
        session_cookie_secure=env == 'production',
        content_security_policy=csp,
        content_security_policy_nonce_in=None  # Disable nonces
    )

    # Initialize extensions with better session handling
    try:
        if hasattr(Config, 'SESSION_REDIS') and Config.SESSION_REDIS:
            try:
                # Test connection again right before initialization
                Config.SESSION_REDIS.ping()
                app.config['SESSION_REDIS'] = Config.SESSION_REDIS
            except Exception as e:
                app.logger.warning(f"Redis connection test failed: {e}, falling back to filesystem")
                app.config['SESSION_TYPE'] = 'filesystem'
        
        sess.init_app(app)
    except Exception as e:
        app.logger.error(f"Session initialization error: {e}")
        app.config['SESSION_TYPE'] = 'filesystem'
        sess.init_app(app)

    # Initialize cache with Redis URL instead of client to avoid connection issues
    try:
        redis_url = os.getenv('REDIS_URL')
        if redis_url and redis_url.strip():
            try:
                # Use CACHE_REDIS_URL which is more reliable than CACHE_REDIS_CLIENT
                cache.init_app(app, config={
                    'CACHE_TYPE': 'RedisCache',
                    'CACHE_REDIS_URL': redis_url,  # Use URL instead of client
                    'CACHE_DEFAULT_TIMEOUT': 300,
                    'CACHE_THRESHOLD': 500,
                    'CACHE_KEY_PREFIX': 'flask_cache_',
                    'CACHE_OPTIONS': {
                        'socket_timeout': 5,
                        'socket_connect_timeout': 5
                    }
                })
                app.logger.info("Cache initialized with Redis URL")
            except Exception as e:
                app.logger.warning(f"Redis cache initialization failed: {e}, falling back to simple cache")
                cache.init_app(app, config={'CACHE_TYPE': 'SimpleCache'})
        else:
            # Fallback to simple cache if no Redis available
            app.logger.warning("No REDIS_URL available, using simple cache")
            cache.init_app(app, config={'CACHE_TYPE': 'SimpleCache'})
    except Exception as e:
        app.logger.error(f"Cache initialization error: {e}")
        cache.init_app(app, config={'CACHE_TYPE': 'SimpleCache'})

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = "info"
    app.jinja_env.globals.update(current_user=current_user)
    
    # Initialize rate limiter with improved Redis handling
    try:
        redis_url = app.config.get('RATELIMIT_STORAGE_URL')
        
        # In production, try to get Redis URL from environment if config fallback occurred
        if env == 'production':
            # If config fallback occurred, check environment variable directly
            if not redis_url or redis_url.startswith('memory://'):
                env_redis_url = os.getenv('REDIS_URL')
                if env_redis_url and env_redis_url.strip():
                    redis_url = env_redis_url.strip()
                    app.logger.info("Using REDIS_URL from environment variable for rate limiting")
                else:
                    # In production, we need Redis for security, but allow graceful degradation with warning
                    app.logger.error("CRITICAL: Redis-backed rate limiting is strongly recommended in production.")
                    app.logger.error("REDIS_URL environment variable is not set or empty.")
                    app.logger.error("Falling back to memory-based rate limiting - this is not recommended for production.")
                    # Don't raise an exception, but allow memory fallback with strong warning
            
            # Test Redis connectivity in production if we have a URL
            if redis_url and not redis_url.startswith('memory://'):
                try:
                    import redis
                    r = redis.from_url(redis_url)
                    r.ping()
                    # Set both config keys to ensure compatibility across Flask-Limiter versions
                    app.config['RATELIMIT_STORAGE_URI'] = redis_url
                    app.config['RATELIMIT_STORAGE_URL'] = redis_url
                    app.logger.info("Rate limiter configured with Redis (production)")
                except Exception as redis_error:
                    app.logger.error(f"Redis connection failed in production: {redis_error}")
                    app.logger.error("Falling back to memory-based rate limiting - this is not ideal for production.")
                    # Don't raise exception, allow graceful degradation
                    app.config['RATELIMIT_STORAGE_URL'] = 'memory://'
        
        # Development mode - allow memory fallback but warn
        elif redis_url and not redis_url.startswith('memory://'):
            try:
                import redis
                r = redis.from_url(redis_url)
                r.ping()
                app.config['RATELIMIT_STORAGE_URI'] = redis_url
                app.config['RATELIMIT_STORAGE_URL'] = redis_url
                app.logger.info("Rate limiter configured with Redis (development)")
            except Exception as redis_error:
                app.logger.warning(f"Redis connection failed in development: {redis_error}, using memory storage")
                app.config['RATELIMIT_STORAGE_URL'] = 'memory://'
        else:
            app.logger.warning("Rate limiter using memory storage - development mode only")
        
        limiter.init_app(app)
        
        # Verify the limiter is actually using Redis (not memory) - informational only
        try:
            storage_type = str(type(limiter.storage))
            final_redis_url = app.config.get('RATELIMIT_STORAGE_URL', '')
            if final_redis_url and not final_redis_url.startswith('memory://'):
                if 'memory' in storage_type.lower() or 'dict' in storage_type.lower():
                    app.logger.warning(f"Rate limiter using memory storage despite Redis config. Storage type: {storage_type}")
                    if env == 'production':
                        app.logger.error("This is not recommended for production - rate limits won't be shared across instances")
                else:
                    app.logger.info(f"Rate limiter storage verified: {storage_type}")
            else:
                app.logger.info(f"Rate limiter using memory storage: {storage_type}")
        except Exception as storage_check_error:
            app.logger.warning(f"Could not verify rate limiter storage type: {storage_check_error}")
        
    except Exception as e:
        app.logger.error(f"Rate limiter initialization failed: {e}")
        # Always initialize limiter to prevent startup failure
        limiter.init_app(app)
        if env == 'production':
            app.logger.error("Rate limiter initialized with memory fallback in production - not ideal for scaling")

    # Database check
    
    # Replace current database check with:
    if not try_connect_db(app):
        raise RuntimeError("Could not establish database connection")
        


    # Security settings
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(days=7)
    )

    # Sentry in production only
    if env == 'production' and app.config.get('SENTRY_DSN'):
        sentry_sdk.init(
            dsn=app.config['SENTRY_DSN'],
            integrations=[FlaskIntegration()],
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0
        )

    # User loader
    from app.models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from app.routes import init_routes
    init_routes(app)

    from app.auth.routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")

    from app.profiles.routes import profiles_bp
    app.register_blueprint(profiles_bp, url_prefix="/profiles")

    from app.discussions.routes import discussions_bp
    app.register_blueprint(discussions_bp, url_prefix='/discussions')
    
    # Register statements blueprint (Phase 1 - Native Statement System)
    from app.discussions.statements import statements_bp
    app.register_blueprint(statements_bp)
    
    # Register moderation blueprint (Phase 2.3 - Moderation Queue)
    from app.discussions.moderation import moderation_bp
    app.register_blueprint(moderation_bp)
    
    # Register consensus blueprint (Phase 3 - Consensus Clustering)
    from app.discussions.consensus import consensus_bp
    app.register_blueprint(consensus_bp)

    from app.settings.routes import settings_bp
    app.register_blueprint(settings_bp, url_prefix='/settings')
    
    # Register API keys blueprint (Phase 4.1 - User LLM API Keys)
    from app.settings.api_keys import api_keys_bp
    app.register_blueprint(api_keys_bp)

    from app.help import help_bp
    app.register_blueprint(help_bp, url_prefix='/help')

    from app.admin import admin_bp
    print("Registering admin blueprint...")  # Debug statement
    app.register_blueprint(admin_bp, url_prefix='/admin')
    print("Admin blueprint registered")  # Debug statement
    # Add this line to print all registered routes
    print("All registered routes:")
    print(app.url_map)


    from app.commands import init_commands
    init_commands(app)


    # Error handler for 403 Forbidden
    @app.errorhandler(403)
    def forbidden(e):
        app.logger.warning(f"403 Forbidden: {e}")
        return render_template('errors/403.html', error_code=403, error_message="You don't have permission to access this resource."), 403

    # Error handler for 404 Not Found
    @app.errorhandler(404)
    def page_not_found(e):
        app.logger.warning(f"404 Page Not Found: {e}")
        return render_template('errors/404.html', error_code=404, error_message="The page you're looking for doesn't exist."), 404

    # Error handler for 500 Internal Server Error
    @app.errorhandler(500)
    def internal_server_error(e):
        app.logger.error(f"500 Internal Server Error: {e}")
        return render_template('errors/500.html', error_code=500, error_message="An internal server error occurred. Please try again later."), 500

    # Catch-all error handler for unhandled exceptions
    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.error(f"Unhandled Exception: {e}", exc_info=True)  # Logs full stack trace
        return render_template('errors/general_error.html', error_code=500, error_message="An unexpected error occurred."), 500

    # Error handler for 400 Bad Request
    @app.errorhandler(400)
    def bad_request(e):
        app.logger.warning(f"400 Bad Request: {e}")
        return render_template('errors/400.html', error_code=400, 
               error_message="The server couldn't understand your request."), 400

    # Error handler for 401 Unauthorized
    @app.errorhandler(401)
    def unauthorized(e):
        app.logger.warning(f"401 Unauthorized: {e}")
        return render_template('errors/401.html', error_code=401, 
               error_message="Authentication is required to access this resource."), 401

    # Error handler for 405 Method Not Allowed
    @app.errorhandler(405)
    def method_not_allowed(e):
        app.logger.warning(f"405 Method Not Allowed: {e}")
        return render_template('errors/405.html', error_code=405, 
               error_message="The method used is not allowed for this resource."), 405

    # Error handler for 429 Too Many Requests
    @app.errorhandler(429)
    def too_many_requests(e):
        app.logger.warning(f"429 Too Many Requests: {e}")
        return render_template('errors/429.html', error_code=429, 
               error_message="Too many requests. Please try again later."), 429

    # Initialize and start background scheduler (Phase 3.3)
    # Only runs in production, not during migrations or tests
    if not app.config.get('TESTING') and not app.config.get('SQLALCHEMY_MIGRATE'):
        from app.scheduler import init_scheduler, start_scheduler
        try:
            init_scheduler(app)
            start_scheduler()
            app.logger.info("Background scheduler started successfully")
        except Exception as e:
            app.logger.error(f"Failed to start scheduler: {e}")


    return app