from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect
from config import Config, config_dict
from datetime import timedelta
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
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
talisman = Talisman()


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
            """Drop known-harmless or expected errors (shutdown, migration heads, scanners, transient).
            PendingRollbackError: dropped after fixing scheduler session cleanup; may also drop
            non-scheduler occurrences (acceptable to reduce noise; fix session handling if seen elsewhere).
            """
            def drop_if(msg, *phrases):
                if not msg:
                    return False
                return any(p in msg for p in phrases)

            msg = ""
            if "log_record" in hint:
                record = hint["log_record"]
                msg = (record.getMessage() or "") if hasattr(record, "getMessage") else str(record.msg or "")
                if drop_if(msg, "cannot schedule new futures after shutdown", "multiple head revisions"):
                    return None
                if drop_if(msg, "Failed to generate audio for item"):
                    return None
                if "Error fetching asset" in msg and (".php" in msg or "filemanager" in msg.lower() or "server/php" in msg.lower()):
                    return None
            exc_info = hint.get("exc_info")
            if exc_info:
                exc_msg = str(exc_info[1] or "")
                exc_type = exc_info[0]
                if exc_type is RuntimeError and drop_if(exc_msg, "cannot schedule new futures after shutdown"):
                    return None
                if drop_if(exc_msg, "multiple head revisions"):
                    return None
                if exc_type is OSError and drop_if(exc_msg, "errno 5", "input/output error"):
                    return None
                if "PendingRollbackError" in (getattr(exc_type, "__name__", "") or ""):
                    return None
            # Event may have exception in payload (e.g. from logging integration)
            for exc in (event.get("exception") or {}).get("values") or []:
                val = exc.get("value") or ""
                typ = exc.get("type") or ""
                if typ == "RuntimeError" and drop_if(val, "cannot schedule new futures after shutdown"):
                    return None
                if drop_if(val, "multiple head revisions"):
                    return None
                if typ == "OSError" and drop_if(val, "errno 5", "input/output error"):
                    return None
                if "PendingRollbackError" in typ:
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

    # Trust X-Forwarded-For / Proto from exactly one reverse proxy.
    # Keep forwarded host trust opt-in to reduce host header spoofing risk.
    trust_proxy_host = os.getenv("TRUST_PROXY_HOST_HEADER", "false").lower() == "true"
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1 if trust_proxy_host else 0,
    )

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
    talisman.init_app(
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
                Config.SESSION_REDIS.ping()
                app.config['SESSION_REDIS'] = Config.SESSION_REDIS
            except Exception as e:
                app.logger.warning(f"Redis session ping failed ({type(e).__name__}): {e}, falling back to filesystem")
                app.config['SESSION_TYPE'] = 'filesystem'
        
        sess.init_app(app)
    except Exception as e:
        app.logger.error(f"Session initialization error: {e}")
        app.config['SESSION_TYPE'] = 'filesystem'
        sess.init_app(app)

    # Initialize cache — set config on app.config so flask-caching reads it reliably
    try:
        redis_url = os.getenv('REDIS_URL')
        if redis_url and redis_url.strip():
            try:
                app.config['CACHE_TYPE'] = 'RedisCache'
                app.config['CACHE_REDIS_URL'] = redis_url
                app.config['CACHE_DEFAULT_TIMEOUT'] = 300
                app.config['CACHE_THRESHOLD'] = 500
                app.config['CACHE_KEY_PREFIX'] = 'flask_cache_'
                app.config['CACHE_OPTIONS'] = {
                    'socket_timeout': 3,
                    'socket_connect_timeout': 3
                }
                cache.init_app(app)
                app.logger.info("Cache initialized with Redis successfully")
            except Exception as e:
                app.logger.warning(f"Redis cache initialization failed: {e}, falling back to simple cache")
                app.config['CACHE_TYPE'] = 'SimpleCache'
                cache.init_app(app)
        else:
            app.logger.warning("No REDIS_URL available, using simple cache")
            app.config['CACHE_TYPE'] = 'SimpleCache'
            cache.init_app(app)
    except Exception as e:
        app.logger.error(f"Cache initialization error: {e}")
        app.config['CACHE_TYPE'] = 'SimpleCache'
        cache.init_app(app)

    # Verify Redis-backed cache in production when REDIS_URL is set
    if os.getenv("FLASK_ENV") == "production" and os.getenv('REDIS_URL'):
        if app.config.get('CACHE_TYPE') != 'RedisCache':
            app.logger.error("CRITICAL: Cache is not using Redis in production despite REDIS_URL being set.")

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'  # type: ignore[assignment]
    login_manager.login_message_category = "info"
    app.jinja_env.globals.update(current_user=current_user)

    from app.lib.bot_protection import generate_form_token
    app.jinja_env.globals['bot_form_token'] = generate_form_token

    from app.utils.db_diagnostics import init_n_plus_one_guard
    init_n_plus_one_guard(app)
    
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
    
    def strip_so_what(text):
        """Remove leading 'So what?' (and variants) from Why It Matters text for display."""
        if not text or not isinstance(text, str):
            return text or ''
        stripped = re.sub(r'^\s*So\s+what\s*[?:\-]\s*', '', text, flags=re.IGNORECASE, count=1)
        return stripped.strip() if stripped != text else text

    app.jinja_env.filters['render_markdown'] = render_markdown_links
    app.jinja_env.filters['strip_markdown'] = strip_markdown
    app.jinja_env.filters['markdown'] = convert_markdown
    app.jinja_env.filters['strip_so_what'] = strip_so_what
    
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
                    r = redis.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
                    r.ping()
                    app.config['RATELIMIT_STORAGE_URI'] = redis_url
                    app.config['RATELIMIT_STORAGE_URL'] = redis_url
                    app.logger.info("Rate limiter configured with Redis (production)")
                except Exception as redis_error:
                    app.logger.error(f"Redis connection failed in production: {redis_error}")
                    app.logger.error("Falling back to memory-based rate limiting - this is not ideal for production.")
                    app.config['RATELIMIT_STORAGE_URL'] = 'memory://'
        
        # Development mode - allow memory fallback but warn
        elif redis_url and not redis_url.startswith('memory://'):
            try:
                import redis
                r = redis.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
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

    # Register Partner API blueprint (embed integration)
    from app.api import init_api
    init_api(app)
    app.logger.debug("Partner API blueprint registered")

    # Register Partner Hub blueprint (publisher-facing pages)
    from app.partner import partner_bp
    app.register_blueprint(partner_bp)
    app.logger.debug("Partner hub blueprint registered")

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
        try:
            raw = getattr(e, 'retry_after', 60) or 60
            retry_after = max(1, min(3600, int(float(raw))))
        except (ValueError, TypeError):
            retry_after = 60
        # Return JSON for API/embed requests so clients get Retry-After and consistent format
        if request.is_json or request.headers.get('X-Embed-Request'):
            from flask import jsonify
            resp = jsonify({'error': 'rate_limited', 'message': f'Too many requests. Please retry in {retry_after} seconds.'})
            resp.status_code = 429
            resp.headers['Retry-After'] = str(retry_after)
            return resp
        response = render_template('errors/429.html', error_code=429,
               error_message="Too many requests. Please try again later.")
        from flask import make_response
        r = make_response(response, 429)
        r.headers['Retry-After'] = str(retry_after)
        return r

    _is_deployed = os.environ.get('REPLIT_DEPLOYMENT') == '1'
    _skip_scheduler = app.config.get('TESTING') or os.environ.get('SQLALCHEMY_MIGRATE')
    _scheduler_lock_key = 'scheduler_lock'
    _scheduler_heartbeat_key = 'scheduler:last_heartbeat_at'
    _scheduler_state = {
        'enabled': bool(_is_deployed and not _skip_scheduler),
        'running': False,
        'lock_acquired': False,
        'last_heartbeat_at': None,
        'last_error': None,
    }
    app.config['SCHEDULER_RUNTIME'] = _scheduler_state

    # Health check endpoint - must respond immediately for deployment health checks
    @app.route('/health')
    def health_check():
        """Health check endpoint with cross-worker scheduler visibility."""
        scheduler_snapshot = {
            'enabled': _scheduler_state.get('enabled', False),
            'running': _scheduler_state.get('running', False),
            'lock_acquired': _scheduler_state.get('lock_acquired', False),
            'last_heartbeat_at': _scheduler_state.get('last_heartbeat_at'),
            'owner_pid': None,
            'lock_ttl_seconds': None,
            'source': 'local_memory',
        }
        if _is_deployed:
            redis_url = os.getenv('REDIS_URL')
            if redis_url:
                try:
                    import redis as redis_lib
                    health_redis = redis_lib.from_url(redis_url, socket_timeout=1, socket_connect_timeout=1)
                    owner_pid = health_redis.get(_scheduler_lock_key)
                    lock_ttl = health_redis.ttl(_scheduler_lock_key)
                    shared_heartbeat = health_redis.get(_scheduler_heartbeat_key)

                    has_owner = bool(owner_pid) and (lock_ttl is None or lock_ttl > 0)
                    scheduler_snapshot['running'] = has_owner
                    scheduler_snapshot['lock_acquired'] = has_owner
                    scheduler_snapshot['owner_pid'] = owner_pid
                    scheduler_snapshot['lock_ttl_seconds'] = lock_ttl
                    scheduler_snapshot['last_heartbeat_at'] = (
                        int(shared_heartbeat) if shared_heartbeat and str(shared_heartbeat).isdigit() else shared_heartbeat
                    )
                    scheduler_snapshot['source'] = 'redis'
                except Exception as health_error:
                    scheduler_snapshot['source'] = f"local_memory (redis_error: {type(health_error).__name__})"
        return {'status': 'healthy', 'scheduler': scheduler_snapshot}, 200
    
    if _is_deployed and not _skip_scheduler:
        import threading
        
        _SCHEDULER_LOCK_KEY = _scheduler_lock_key
        _SCHEDULER_LOCK_TTL = 120
        _SCHEDULER_HEARTBEAT_SECONDS = 20
        _SCHEDULER_RETRY_DELAY_SECONDS = 15
        _SCHEDULER_MAX_LOCK_ATTEMPTS = 8

        def _update_shared_scheduler_heartbeat(redis_client):
            """Publish scheduler heartbeat in Redis so /health is worker-agnostic."""
            try:
                heartbeat_value = int(time.time())
                heartbeat_ttl = max(_SCHEDULER_LOCK_TTL * 2, 180)
                redis_client.setex(_scheduler_heartbeat_key, heartbeat_ttl, str(heartbeat_value))
                _scheduler_state['last_heartbeat_at'] = heartbeat_value
            except Exception as heartbeat_update_error:
                app.logger.debug(f"Could not update shared scheduler heartbeat: {heartbeat_update_error}")

        def _release_scheduler_lock(redis_client, owner_pid):
            """Release scheduler lock only if owned by this process."""
            try:
                release_script = """
                if redis.call('get', KEYS[1]) == ARGV[1] then
                    return redis.call('del', KEYS[1])
                else
                    return 0
                end
                """
                redis_client.eval(release_script, 1, _SCHEDULER_LOCK_KEY, str(owner_pid))
            except Exception as release_error:
                app.logger.warning(f"Failed to release scheduler lock: {release_error}")

        def _acquire_scheduler_lock(redis_client, owner_pid, attempts=_SCHEDULER_MAX_LOCK_ATTEMPTS):
            """Try to acquire scheduler lock with bounded retries and jitter."""
            acquired = False
            for attempt in range(1, attempts + 1):
                try:
                    redis_client.ping()
                    acquired = redis_client.set(_SCHEDULER_LOCK_KEY, str(owner_pid), nx=True, ex=_SCHEDULER_LOCK_TTL)
                    if acquired:
                        app.logger.info(f"Scheduler lock acquired on attempt {attempt} (pid={owner_pid})")
                        _scheduler_state['lock_acquired'] = True
                        _update_shared_scheduler_heartbeat(redis_client)
                        return True
                    existing = redis_client.get(_SCHEDULER_LOCK_KEY)
                    existing_ttl = redis_client.ttl(_SCHEDULER_LOCK_KEY)
                    app.logger.info(
                        f"Scheduler lock held by pid={existing}, ttl={existing_ttl}s, "
                        f"retrying ({attempt}/{attempts})..."
                    )
                except Exception as acquire_error:
                    app.logger.warning(f"Redis error during lock attempt {attempt}: {acquire_error}")

                if attempt < attempts:
                    # Small jitter helps avoid lock-step retries across workers.
                    sleep_seconds = _SCHEDULER_RETRY_DELAY_SECONDS + (attempt % 3)
                    time.sleep(sleep_seconds)

            _scheduler_state['lock_acquired'] = False
            return False

        def _run_scheduler_cycle():
            """Acquire lock, run scheduler, and maintain lock heartbeat until loss/failure."""
            pid = os.getpid()
            redis_url = os.getenv('REDIS_URL')
            _scheduler_state['running'] = False

            if not redis_url:
                _scheduler_state['last_error'] = "REDIS_URL missing for scheduler lock"
                app.logger.error("REDIS_URL is required for scheduler lock in deployed environment; scheduler start aborted")
                return False

            try:
                import redis as redis_lib
                redis_client = redis_lib.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
            except Exception as connect_error:
                _scheduler_state['last_error'] = f"Redis connect failed: {connect_error}"
                app.logger.error(f"Could not connect to Redis for scheduler lock: {connect_error}")
                return False

            if not _acquire_scheduler_lock(redis_client, pid):
                _scheduler_state['last_error'] = "Unable to acquire scheduler lock"
                app.logger.error(f"Failed to acquire scheduler lock after retries (pid={pid})")
                return False

            try:
                from app.scheduler import init_scheduler, start_scheduler
                init_scheduler(app)
                start_scheduler()
                _scheduler_state['running'] = True
                _scheduler_state['last_error'] = None
                app.logger.info(f"Background scheduler started (pid={pid})")
            except Exception as start_error:
                _scheduler_state['running'] = False
                _scheduler_state['lock_acquired'] = False
                _scheduler_state['last_error'] = f"Scheduler start failed: {start_error}"
                app.logger.error(f"Failed to start scheduler: {start_error}")
                _release_scheduler_lock(redis_client, pid)
                return False

            renew_script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
            else
                return nil
            end
            """

            consecutive_failures = 0
            while True:
                time.sleep(_SCHEDULER_HEARTBEAT_SECONDS)
                try:
                    result = redis_client.eval(renew_script, 1, _SCHEDULER_LOCK_KEY, str(pid), str(_SCHEDULER_LOCK_TTL))
                    if result is None:
                        app.logger.warning(f"Scheduler lock lost by pid={pid}, attempting re-acquire...")
                        _scheduler_state['lock_acquired'] = False
                        reacquired = _acquire_scheduler_lock(redis_client, pid, attempts=3)
                        if reacquired:
                            consecutive_failures = 0
                            continue

                        app.logger.error(f"Scheduler lock taken by another worker; shutting down scheduler (pid={pid})")
                        try:
                            from app.scheduler import shutdown_scheduler
                            shutdown_scheduler(wait=False)
                        except Exception as shutdown_error:
                            app.logger.warning(f"Failed to shutdown scheduler after lock loss: {shutdown_error}")
                        _scheduler_state['running'] = False
                        _scheduler_state['lock_acquired'] = False
                        return False

                    _scheduler_state['last_heartbeat_at'] = int(time.time())
                    _scheduler_state['lock_acquired'] = True
                    _update_shared_scheduler_heartbeat(redis_client)
                    consecutive_failures = 0
                except Exception as heartbeat_error:
                    consecutive_failures += 1
                    _scheduler_state['last_error'] = f"Heartbeat error: {heartbeat_error}"
                    app.logger.warning(f"Heartbeat error ({consecutive_failures}/5): {heartbeat_error}")
                    if consecutive_failures >= 5:
                        app.logger.error(f"Heartbeat failed repeatedly; shutting down scheduler (pid={pid})")
                        try:
                            from app.scheduler import shutdown_scheduler
                            shutdown_scheduler(wait=False)
                        except Exception:
                            pass
                        _release_scheduler_lock(redis_client, pid)
                        _scheduler_state['running'] = False
                        _scheduler_state['lock_acquired'] = False
                        return False
                    try:
                        import redis as redis_lib
                        redis_client = redis_lib.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
                    except Exception:
                        pass

        def _scheduler_supervisor():
            """Continuously supervise scheduler startup/recovery in deployed production."""
            time.sleep(15)  # Allow app to bind port before attempting scheduler work.
            while True:
                try:
                    _run_scheduler_cycle()
                except Exception as supervisor_error:
                    _scheduler_state['running'] = False
                    _scheduler_state['lock_acquired'] = False
                    _scheduler_state['last_error'] = f"Supervisor error: {supervisor_error}"
                    app.logger.error(f"Scheduler supervisor error: {supervisor_error}", exc_info=True)

                # Self-heal: retry after a short delay if scheduler cycle exits.
                time.sleep(_SCHEDULER_RETRY_DELAY_SECONDS)

        scheduler_thread = threading.Thread(target=_scheduler_supervisor, daemon=True)
        scheduler_thread.start()
        app.logger.info("Scheduler startup deferred to background thread")
    elif not _skip_scheduler:
        app.logger.info("Scheduler disabled in development (only runs in production deployments)")


    return app