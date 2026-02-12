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
    # Public partner APIs are intentionally cross-origin for easy self-serve embeds.
    # Do not allow X-API-Key in browser CORS preflight; key-protected writes must be
    # server-to-server (enforced in endpoint handlers).
    # Blueprint objects are module singletons; guard against re-registering
    # handlers when create_app() is called multiple times in tests.
    if not getattr(partner_bp, "_ss_error_handlers_registered", False):
        register_error_handlers(partner_bp)
        partner_bp._ss_error_handlers_registered = True

    # Register the blueprint with /api prefix
    app.register_blueprint(partner_bp, url_prefix='/api')

    # Public partner APIs are intentionally cross-origin for easy self-serve embeds.
    # Bind CORS to the app routes (not blueprint objects) so repeated app factory
    # usage in tests does not mutate an already-registered blueprint.
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": "*",
                "methods": ['GET', 'POST', 'OPTIONS'],
                "allow_headers": ['Content-Type', 'X-Requested-With', 'X-Partner-Ref', 'Idempotency-Key'],
                "max_age": 86400,
            }
        },
        supports_credentials=False,
    )

    app.logger.info("Partner API initialized with dynamic origin allowlist")


# Export for external use
__all__ = ['init_api', 'partner_bp']
