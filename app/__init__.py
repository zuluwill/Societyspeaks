from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_talisman import Talisman
from config import Config, config_dict
from datetime import timedelta
import os
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from flask_session import Session
from flask_caching import Cache

# Simplified CSP that will work with inline scripts
csp = {
    'default-src': ["'self'", "'unsafe-inline'", "'unsafe-eval'", "https:", "data:", "blob:"],
    'img-src': ["'self'", "data:", "https:", "blob:"],
    'connect-src': ["'self'", "https:", "wss:"],
    'font-src': ["'self'", "data:", "https:"],
    'frame-src': ["'self'", "https:"],
    'object-src': ["'none'"]
}

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
sess = Session()
cache = Cache()

def create_app():
    app = Flask(__name__, 
        static_url_path='',
        static_folder='static')
    app.config.from_object(Config)

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

    # Initialize extensions
    if hasattr(Config, 'SESSION_REDIS') and Config.SESSION_REDIS:
        app.config['SESSION_REDIS'] = Config.SESSION_REDIS
        sess.init_app(app)

    cache.init_app(app, config={
        'CACHE_TYPE': 'redis',
        'CACHE_REDIS_URL': Config.REDIS_URL,
        'CACHE_DEFAULT_TIMEOUT': 300
    })

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = "info"
    app.jinja_env.globals.update(current_user=current_user)

    # Database check
    with app.app_context():
        try:
            db.engine.connect()
        except Exception as e:
            print(f"Database connection error: {e}")

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

    from app.settings.routes import settings_bp
    app.register_blueprint(settings_bp, url_prefix='/settings')

    from app.commands import init_commands
    init_commands(app)

    return app