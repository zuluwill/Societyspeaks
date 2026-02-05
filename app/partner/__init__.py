"""
Partner Hub Module

Provides partner-facing pages for embedding Society Speaks on third-party sites.
Includes the partner hub landing page, embed code generator, and API documentation.
"""
from flask import Blueprint

partner_bp = Blueprint('partner', __name__, url_prefix='/for-publishers')

from app.partner import routes  # noqa: F401, E402
