"""
Trending Topics System - News-to-Deliberation Compiler

This module handles:
- Fetching news from curated sources
- Scoring articles for civic relevance and quality
- Clustering similar articles into topics
- Generating balanced seed statements
- Admin review queue for publishing
"""

from flask import Blueprint

trending_bp = Blueprint('trending', __name__, url_prefix='/admin/trending')

from app.trending import routes
