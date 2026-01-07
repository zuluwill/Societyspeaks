"""
Daily Brief Module

Automated daily news briefing with coverage analysis and sense-making tools.
"""

from flask import Blueprint

brief_bp = Blueprint('brief', __name__)

from app.brief import routes
