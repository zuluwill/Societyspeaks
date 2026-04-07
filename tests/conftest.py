"""
Pytest configuration and shared fixtures.
"""

import pytest
import os
import sys
from unittest.mock import MagicMock
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set DATABASE_URL before Config class is imported (it validates at class-definition time)
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

# Mock deployment-specific modules that are not available in the test environment
# (replit.object_storage is only available on Replit's platform)
_replit_mock = MagicMock()
sys.modules.setdefault('replit', _replit_mock)
sys.modules.setdefault('replit.object_storage', _replit_mock)
sys.modules.setdefault('replit.object_storage.errors', _replit_mock)


# SQLite compatibility for tests that use in-memory DB:
# map PostgreSQL JSONB columns to JSON so metadata.create_all() can run.
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_element, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def app():
    """Create application for testing."""
    from config import Config

    # Override Config attributes AND environment variables BEFORE create_app() so
    # the app is built with SQLite-compatible settings and in-memory rate limiting.
    # FLASK_ENV must be non-production to stop __init__.py from overriding
    # RATELIMIT_STORAGE_URL with the real Redis URL from the environment.
    _orig_uri = Config.SQLALCHEMY_DATABASE_URI
    _orig_engine = Config.SQLALCHEMY_ENGINE_OPTIONS
    _orig_ratelimit = Config.RATELIMIT_STORAGE_URL
    _orig_flask_env = os.environ.get('FLASK_ENV')
    Config.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    Config.SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}
    Config.RATELIMIT_STORAGE_URL = 'memory://'
    os.environ['FLASK_ENV'] = 'development'

    try:
        from app import create_app, cache
        app = create_app()
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        # Flask-Caching's SimpleCache is a module-level singleton whose internal
        # storage is NOT reset when init_app() is called with a new app instance.
        # Explicitly clear it so cached snapshots/lookups from a prior test do not
        # bleed into the next one.
        with app.app_context():
            cache.clear()
    finally:
        # Always restore Config and environment, even if create_app() raises
        Config.SQLALCHEMY_DATABASE_URI = _orig_uri
        Config.SQLALCHEMY_ENGINE_OPTIONS = _orig_engine
        Config.RATELIMIT_STORAGE_URL = _orig_ratelimit
        if _orig_flask_env is None:
            os.environ.pop('FLASK_ENV', None)
        else:
            os.environ['FLASK_ENV'] = _orig_flask_env

    return app


@pytest.fixture
def app_context(app):
    """Application context for testing."""
    with app.app_context():
        yield


@pytest.fixture
def db(app, app_context):
    """Database for testing."""
    from app import db as _db

    _db.create_all()
    yield _db
    _db.drop_all()


class MockArticle:
    """Mock article for testing geographic extraction."""
    def __init__(self, geographic_scope=None, geographic_countries=None, source=None):
        self.geographic_scope = geographic_scope
        self.geographic_countries = geographic_countries
        self.source = source


class MockSource:
    """Mock source for testing."""
    def __init__(self, country=None):
        self.country = country


class MockTopicArticle:
    """Mock topic article wrapper for testing."""
    def __init__(self, article):
        self.article = article
