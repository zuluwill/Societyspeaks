"""
Partner API Blueprint

Provides REST API endpoints for partner embed integration:
- Lookup by article URL
- Snapshot (participation counts)
- Create discussion (server-to-server, X-API-Key authenticated)
- PATCH / append statements management

All endpoints:
- Return JSON with standardized error format
- CORS open to all origins (embeds need cross-origin access); write routes are
  server-to-server only (enforced in handlers via Origin block + X-API-Key)
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
    # All routes on this blueprint are either:
    #   (a) public GETs (lookup, snapshot, oembed) — no auth needed, no CSRF needed
    #   (b) server-to-server writes authenticated by X-API-Key — CSRF is redundant and
    #       would break any CMS calling these routes without a browser session.
    #   (c) embed flag POST — cross-origin, no session; origin-checked in the handler.
    # Blueprint-level exempt is the single authoritative policy (no per-route duplication).
    from app import csrf
    csrf.exempt(partner_bp)

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
                "methods": ['GET', 'POST', 'PATCH', 'OPTIONS'],
                "allow_headers": [
                    'Content-Type',
                    'X-Requested-With',
                    'X-Partner-Ref',
                    'X-API-Key',
                    'Idempotency-Key',
                ],
                "max_age": 86400,
            }
        },
        supports_credentials=False,
    )

    app.logger.info("Partner API initialized")


# Export for external use
__all__ = ['init_api', 'partner_bp']
