from flask import Flask
from flask_migrate import Migrate
from config import Config
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize database and migration
    db.init_app(app)
    migrate.init_app(app, db)

    # Import models here, after db and migrate have been initialized
    from app import models

    # Register the routes
    from app.routes import init_routes
    init_routes(app)

    return app
