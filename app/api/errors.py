"""
Standardized API Error Responses

Provides consistent JSON error format for partner API integration.
All API errors return: {"error": "code", "message": "human readable message"}
"""
from flask import jsonify, current_app
from flask_babel import gettext as _
from werkzeug.exceptions import HTTPException


# Werkzeug default descriptions that pass through `abort(code)` with no custom
# message. We translate the common ones so partner API consumers get localized
# responses regardless of which Werkzeug version is installed.
_WERKZEUG_DEFAULT_DESCRIPTIONS = {
    "The browser (or proxy) sent a request that this server could not understand.":
        lambda: _("The browser (or proxy) sent a request that this server could not understand."),
    "The server could not verify that you are authorized to access the URL requested.":
        lambda: _("The server could not verify that you are authorized to access the URL requested."),
    "You don't have the permission to access the requested resource.":
        lambda: _("You don't have the permission to access the requested resource."),
    "The requested URL was not found on the server.":
        lambda: _("The requested URL was not found on the server."),
    "The method is not allowed for the requested URL.":
        lambda: _("The method is not allowed for the requested URL."),
    "The server encountered an internal error and was unable to complete your request.":
        lambda: _("The server encountered an internal error and was unable to complete your request."),
}


def _localize_description(description) -> str:
    """Translate a Werkzeug/abort description if we recognize it; else pass through.

    `abort(code, "English")` produces descriptions that aren't msgids in our
    catalog. We only localize the narrow, known set of Werkzeug defaults — any
    custom description set by the caller stays verbatim.
    """
    if description is None:
        return ""
    text = str(description)
    mapped = _WERKZEUG_DEFAULT_DESCRIPTIONS.get(text)
    if mapped is not None:
        return mapped()
    return text


def _retry_after_seconds(e, default: int = 60) -> int:
    """Extract Retry-After seconds from a 429 exception; clamp to 1-3600."""
    raw = getattr(e, 'retry_after', None)
    if raw is not None and str(raw).strip() != '':
        try:
            secs = int(float(raw))
            return max(1, min(3600, secs))
        except (ValueError, TypeError):
            pass
    return max(1, min(3600, default))


def api_error(code: str, message: str, status_code: int = 400):
    """
    Create a standardized API error response.

    Args:
        code: Machine-readable error code (e.g., 'invalid_url', 'no_discussion')
        message: Human-readable error message
        status_code: HTTP status code (default 400)

    Returns:
        Flask Response with status_code set (return this directly from a view).

    Example:
        return api_error('invalid_url', 'The provided URL is not valid.', 400)
    """
    response = jsonify({
        'error': code,
        'message': message
    })
    response.status_code = status_code
    return response


# Canonical translated message per HTTP status code — used by
# handle_http_exception when a less-common exception (e.g. 402, 405, 503) is
# raised without a custom description.
_HTTP_MESSAGE_BY_STATUS = {
    400: lambda: _("Bad request"),
    401: lambda: _("Authentication required."),
    402: lambda: _("Payment required."),
    403: lambda: _("Access denied."),
    404: lambda: _("Resource not found"),
    405: lambda: _("The method used is not allowed for this resource."),
    406: lambda: _("Not acceptable."),
    408: lambda: _("Request timeout."),
    409: lambda: _("Conflict with the current state of the resource."),
    410: lambda: _("This resource is no longer available."),
    411: lambda: _("Length required."),
    413: lambda: _("Payload too large."),
    414: lambda: _("URI too long."),
    415: lambda: _("Unsupported media type."),
    422: lambda: _("Unprocessable entity."),
    429: lambda: _("Too many requests. Please try again later."),
    500: lambda: _("An internal error occurred. Please try again later."),
    501: lambda: _("Not implemented."),
    502: lambda: _("Bad gateway."),
    503: lambda: _("Service temporarily unavailable."),
    504: lambda: _("Gateway timeout."),
}


def register_error_handlers(blueprint):
    """
    Register error handlers for the API blueprint.
    Ensures all errors return JSON, not HTML.
    """

    @blueprint.errorhandler(400)
    def bad_request(e):
        # Prefer our canonical translated string; fall back to e.description only
        # if the caller set a custom English description via abort(400, "msg").
        message = _localize_description(e.description) if getattr(e, 'description', None) else _('Bad request')
        return api_error('bad_request', message, 400)

    @blueprint.errorhandler(401)
    def unauthorized(e):
        return api_error('unauthorized', _('Authentication required.'), 401)

    @blueprint.errorhandler(403)
    def forbidden(e):
        return api_error('forbidden', _('Access denied.'), 403)

    @blueprint.errorhandler(404)
    def not_found(e):
        message = _localize_description(e.description) if getattr(e, 'description', None) else _('Resource not found')
        return api_error('not_found', message, 404)

    @blueprint.errorhandler(429)
    def rate_limited(e):
        retry_after = _retry_after_seconds(e, 60)
        response = api_error(
            'rate_limited',
            _('Too many requests. Please retry in %(retry_after)s seconds.', retry_after=retry_after),
            429
        )
        response.headers['Retry-After'] = str(retry_after)
        return response

    @blueprint.errorhandler(500)
    def internal_error(e):
        current_app.logger.error(f'API Internal Error: {e}')
        return api_error(
            'internal_error',
            _('An internal error occurred. Please try again later.'),
            500
        )

    @blueprint.errorhandler(HTTPException)
    def handle_http_exception(e):
        """Handle any other HTTP exceptions with JSON response.

        Prefer our canonical translated message for the status code; fall back
        to a localized description only for unknown status codes.
        """
        canonical = _HTTP_MESSAGE_BY_STATUS.get(e.code)
        if canonical is not None:
            message = canonical()
        else:
            message = _localize_description(e.description) if e.description else str(e)
        return api_error(
            e.name.lower().replace(' ', '_'),
            message,
            e.code,
        )


# Common error codes for documentation
ERROR_CODES = {
    'invalid_url': 'The provided URL is not valid or could not be parsed.',
    'missing_url': 'The url parameter is required.',
    'no_discussion': 'No discussion found for this article URL.',
    'discussion_not_found': 'The requested discussion does not exist.',
    'discussion_unavailable': 'This discussion is no longer available.',
    'discussion_closed': 'This discussion is closed and no longer accepting votes.',
    'bad_request': 'The request was malformed or missing required parameters.',
    'unauthorized': 'Authentication is required to access this resource.',
    'forbidden': 'You do not have permission to access this resource.',
    'rate_limited': 'Too many requests. Please wait before retrying.',
    'internal_error': 'An internal server error occurred.',
}
