from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from config import Config
import os

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize database and login manager
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = "info"

    # Ensure the PostgreSQL server is running
    with app.app_context():
        try:
            db.engine.connect()
        except Exception as e:
            print(f"Database connection error: {e}")
            os.system('pg_ctl start -D /workspace/postgres')

    # Import models here after initializing `db` and `login_manager`
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

    from app.commands import init_commands
    init_commands(app)

    return app
