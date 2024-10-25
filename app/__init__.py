from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config
import os

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize database
    db.init_app(app)
    migrate.init_app(app, db)

    # Ensure the PostgreSQL server is running
    with app.app_context():
        try:
            # Check connection
            db.engine.connect()
        except Exception as e:
            print(f"Database connection error: {e}")
            # Start PostgreSQL if needed
            os.system('pg_ctl start -D /workspace/postgres')

    # Register blueprints
    from app.routes import init_routes
    init_routes(app)

    from app.commands import init_commands
    init_commands(app)

    return app