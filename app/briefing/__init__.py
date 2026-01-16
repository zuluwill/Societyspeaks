"""
Briefing System Module (v2)

Multi-tenant briefing system for custom briefs.
Allows users/orgs to create personalized briefs with custom sources and schedules.
"""

from flask import Blueprint

briefing_bp = Blueprint('briefing', __name__, url_prefix='/briefings')

from app.briefing import routes
