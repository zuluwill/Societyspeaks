"""
News Transparency Blueprint

Provides premium news transparency features:
- Automated display of published topics from last 24 hours
- Coverage analysis showing political bias distribution
- Perspective analysis (how left/center/right outlets frame stories)
- Lazy-loaded perspectives for non-brief topics
"""

from flask import Blueprint

news_bp = Blueprint('news', __name__)

from app.news import routes
