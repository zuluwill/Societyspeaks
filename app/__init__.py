from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect
from config import Config, config_dict
from datetime import timedelta
from werkzeug.exceptions import HTTPException
import os
import json
import time
import logging
from logging.config import dictConfig
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from flask_session import Session
import posthog
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Hardened CSP without unsafe-inline and unsafe-eval
csp = {
    'default-src': ["'self'", "https:", "data:", "blob:"],
    'img-src': ["'self'", "data:", "https:", "blob:"],
    'connect-src': ["'self'", "https:", "wss:", "https://cdn.jsdelivr.net", "https://*.posthog.com", "https://us.i.posthog.com", "https://eu.i.posthog.com"],
    'font-src': ["'self'", "data:", "https:"],
    'frame-src': ["'self'", "https:"],
    'style-src': [
        "'self'",
        "'unsafe-inline'",
        "https://cdn.jsdelivr.net",
        "https://cdnjs.cloudflare.com",
        "https://cdn-cookieyes.com"
    ],
    'script-src': [
        "'self'",
        "'unsafe-inline'",
        "https://cdn.jsdelivr.net",
        "https://cdnjs.cloudflare.com",
        "https://www.googletagmanager.com",
        "https://cdn-cookieyes.com",
        "https://pol.is",
        "https://*.posthog.com",
        "https://us-assets.i.posthog.com",
        "https://eu-assets.i.posthog.com"
    ],
    'object-src': ["'none'"],
    'base-uri': ["'self'"],
    'form-action': ["'self'", "https://checkout.stripe.com", "https://billing.stripe.com"]
}




db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
sess = Session()
cache = Cache()
csrf = CSRFProtect()
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
        def _sentry_before_send(event, hint):
            """Drop known-harmless or expected errors (shutdown, migration heads)."""
            def drop_if(msg, *phrases):
                if not msg:
                    return False
                return any(p in msg for p in phrases)

            if "log_record" in hint:
                record = hint["log_record"]
                msg = (record.getMessage() or "") if hasattr(record, "getMessage") else str(record.msg or "")
                if drop_if(msg, "cannot schedule new futures after shutdown", "multiple head revisions"):
                    return None
            exc_info = hint.get("exc_info")
            if exc_info:
                exc_msg = str(exc_info[1] or "")
                if exc_info[0] is RuntimeError and drop_if(exc_msg, "cannot schedule new futures after shutdown"):
                    return None
                if drop_if(exc_msg, "multiple head revisions"):
                    return None
            # Event may have exception in payload (e.g. from logging integration)
            for exc in (event.get("exception") or {}).get("values") or []:
                val = exc.get("value") or ""
                if exc.get("type") == "RuntimeError" and drop_if(val, "cannot schedule new futures after shutdown"):
                    return None
                if drop_if(val, "multiple head revisions"):
                    return None
            return event

        sentry_sdk.init(
            dsn=os.getenv("SENTRY_DSN"),
            integrations=[FlaskIntegration()],
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
            before_send=_sentry_before_send,
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


    # Static file configuration
    # Set cache age for static files (1 hour) to reduce file I/O and improve resilience
    # This helps prevent OSError [Errno 5] I/O errors during high load
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600  # 1 hour in seconds
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
    
    # Configure PostHog for both server-side and frontend analytics
    posthog_api_key = os.getenv("POSTHOG_API_KEY")
    posthog_host = os.getenv("POSTHOG_HOST", "https://eu.i.posthog.com")
    app.config['POSTHOG_API_KEY'] = posthog_api_key
    app.config['POSTHOG_HOST'] = posthog_host
    if posthog_api_key:
        posthog.project_api_key = posthog_api_key
        posthog.host = posthog_host
        posthog.debug = env != "production"
        
        # Register atexit handler to flush PostHog events on shutdown
        import atexit
        def flush_posthog():
            try:
                posthog.flush()
                posthog.shutdown()
            except Exception:
                pass
        atexit.register(flush_posthog)

    # Initialize Talisman with simplified CSP
    # Note: force_https=False because Replit's proxy handles HTTPS termination
    # The proxy receives HTTPS requests and forwards them as HTTP internally
    Talisman(
        app,
        force_https=False,  # Replit proxy handles HTTPS
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
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = "info"
    app.jinja_env.globals.update(current_user=current_user)
    
    import re
    from markupsafe import Markup, escape
    
    def render_markdown_links(text):
        """Convert markdown links [text](url) to HTML <a> tags and **bold** to <strong>."""
        if not text:
            return ''
        text = str(escape(text))
        
        def safe_link_replace(match):
            link_text = match.group(1)
            url = match.group(2)
            if url.startswith(('http://', 'https://', '/')):
                return f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:underline">{link_text}</a>'
            return link_text
        
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', safe_link_replace, text)
        text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
        return Markup(text)
    
    def strip_markdown(text):
        """Strip markdown formatting for plain text display (safe for truncation)."""
        from app.utils.text_processing import strip_markdown as strip_markdown_func
        return strip_markdown_func(text)
    
    def convert_markdown(text):
        """Convert markdown to HTML."""
        if not text:
            return ''
        import markdown as md
        return Markup(md.markdown(text, extensions=['extra', 'nl2br']))
    
    app.jinja_env.filters['render_markdown'] = render_markdown_links
    app.jinja_env.filters['strip_markdown'] = strip_markdown
    app.jinja_env.filters['markdown'] = convert_markdown
    
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

    # Note: Sentry already initialized at top of create_app() for production

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
    app.logger.debug("Registering admin blueprint...")
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.logger.debug("Admin blueprint registered")
    
    # Register trending topics blueprint (News-to-Deliberation Compiler)
    from app.trending import trending_bp
    app.register_blueprint(trending_bp)
    app.logger.debug("Trending topics blueprint registered")
    
    # Register daily question blueprint (Daily Civic Question)
    from app.daily import daily_bp
    app.register_blueprint(daily_bp)
    app.logger.debug("Daily question blueprint registered")

    # Register daily brief blueprints (Evening Sense-Making Brief)
    from app.brief import brief_bp
    app.register_blueprint(brief_bp)
    app.logger.debug("Daily brief blueprint registered")

    from app.brief.admin import brief_admin_bp
    app.register_blueprint(brief_admin_bp)
    app.logger.debug("Daily brief admin blueprint registered")

    # Register news transparency blueprint
    from app.news import news_bp
    app.register_blueprint(news_bp)
    app.logger.debug("News transparency blueprint registered")

    # Register sources blueprint (Source Profiles)
    from app.sources import sources_bp
    app.register_blueprint(sources_bp, url_prefix='/sources')
    app.logger.debug("Sources blueprint registered")

    # Register briefing blueprint (Multi-tenant Briefing System v2)
    from app.briefing import briefing_bp
    app.register_blueprint(briefing_bp)
    app.logger.debug("Briefing blueprint registered")

    # Register billing blueprint (Stripe subscriptions)
    from app.billing import billing_bp
    app.register_blueprint(billing_bp)
    app.logger.debug("Billing blueprint registered")

    app.logger.debug("All registered routes:")
    app.logger.debug(app.url_map)


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
        # Log at debug level to avoid log pollution from bots/crawlers
        app.logger.debug(f"404 Page Not Found: {e}")
        return render_template('errors/404.html', error_code=404, error_message="The page you're looking for doesn't exist."), 404

    # Error handler for 500 Internal Server Error
    @app.errorhandler(500)
    def internal_server_error(e):
        app.logger.error(f"500 Internal Server Error: {e}")
        return render_template('errors/500.html', error_code=500, error_message="An internal server error occurred. Please try again later."), 500

    # Catch-all error handler for unhandled exceptions
    @app.errorhandler(Exception)
    def handle_exception(e):
        # Let HTTP exceptions (like 404, 403, etc.) be handled by their specific handlers
        if isinstance(e, HTTPException):
            return e
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

    # Health check endpoint - must respond immediately for deployment health checks
    @app.route('/health')
    def health_check():
        """Simple health check endpoint that responds immediately."""
        return {'status': 'healthy'}, 200

    # Initialize and start background scheduler (Phase 3.3)
    # Only runs in production, not during migrations or tests
    # IMPORTANT: Scheduler startup is deferred to avoid blocking gunicorn port binding
    if not app.config.get('TESTING') and not app.config.get('SQLALCHEMY_MIGRATE'):
        import threading
        from app.scheduler import init_scheduler, start_scheduler
        
        def _deferred_scheduler_start():
            """Start scheduler after a short delay to allow gunicorn to bind port first."""
            import time
            time.sleep(5)  # Wait 5 seconds for gunicorn to be fully ready
            try:
                init_scheduler(app)
                start_scheduler()
                app.logger.info("Background scheduler started successfully (deferred)")
            except Exception as e:
                app.logger.error(f"Failed to start scheduler: {e}")
        
        # Start scheduler in background thread to avoid blocking
        scheduler_thread = threading.Thread(target=_deferred_scheduler_start, daemon=True)
        scheduler_thread.start()
        app.logger.info("Scheduler startup deferred to background thread")


    return app