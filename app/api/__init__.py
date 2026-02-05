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


def init_api(app):
    """
    Initialize the Partner API blueprint with CORS and error handlers.

    Args:
        app: Flask application instance
    """
    # Get partner origins from config
    origins = app.config.get('PARTNER_ORIGINS', [])

    # Handle case where config is a comma-separated string
    if isinstance(origins, str):
        origins = [o.strip() for o in origins.split(',') if o.strip()]

    # If no origins configured, use empty list (no CORS allowed)
    # In development, you might want to add localhost origins
    if not origins and app.config.get('ENV') == 'development':
        origins = ['http://localhost:3000', 'http://127.0.0.1:3000']

    # Configure CORS for the partner API blueprint
    # This allows cross-origin requests from partner sites
    CORS(
        partner_bp,
        origins=origins,
        methods=['GET', 'POST', 'OPTIONS'],
        allow_headers=['Content-Type', 'X-Requested-With', 'X-Partner-Ref'],
        max_age=86400,  # Cache preflight for 24 hours
        supports_credentials=False  # No cookies needed for API
    )

    # Register standardized error handlers
    register_error_handlers(partner_bp)

    # Register the blueprint with /api prefix
    app.register_blueprint(partner_bp, url_prefix='/api')

    app.logger.info(f"Partner API initialized with {len(origins)} allowed origins")


# Export for external use
__all__ = ['init_api', 'partner_bp']
