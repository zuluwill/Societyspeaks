"""
Partner API Blueprint

Provides REST API endpoints for partner embed integration:
- Lookup by article URL
- Snapshot (participation counts)
- (Phase 2) Create discussion

All endpoints:
- Return JSON with standardized error format
- Use CORS allowlist for partner origins
- Apply rate limiting
- Support caching where appropriate
"""
from flask import Blueprint
from flask_cors import CORS

from app.api.errors import register_error_handlers
from app.api.partner import partner_bp
from app.api.utils import is_partner_origin_allowed


def init_api(app):
    """
    Initialize the Partner API blueprint with CORS and error handlers.

    Args:
        app: Flask application instance
    """
    def _origin_checker(origin):
        if app.config.get('ENV') == 'development' and origin in ['http://localhost:3000', 'http://127.0.0.1:3000']:
            return True
        return is_partner_origin_allowed(origin)

    # Configure CORS for the partner API blueprint
    CORS(
        partner_bp,
        origins=_origin_checker,
        methods=['GET', 'POST', 'OPTIONS'],
        allow_headers=['Content-Type', 'X-Requested-With', 'X-Partner-Ref', 'X-API-Key'],
        max_age=86400,
        supports_credentials=False
    )

    # Register standardized error handlers
    register_error_handlers(partner_bp)

    # Register the blueprint with /api prefix
    app.register_blueprint(partner_bp, url_prefix='/api')

    app.logger.info("Partner API initialized with dynamic origin allowlist")


# Export for external use
__all__ = ['init_api', 'partner_bp']
