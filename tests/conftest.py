"""
Pytest configuration and shared fixtures.
"""

import pytest
import os
import sys

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def app():
    """Create application for testing."""
    from app import create_app

    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

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
