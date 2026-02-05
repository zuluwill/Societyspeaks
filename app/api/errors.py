"""
Standardized API Error Responses

Provides consistent JSON error format for partner API integration.
All API errors return: {"error": "code", "message": "human readable message"}
"""
from flask import jsonify, current_app
from werkzeug.exceptions import HTTPException


def api_error(code: str, message: str, status_code: int = 400):
    """
    Create a standardized API error response.

    Args:
        code: Machine-readable error code (e.g., 'invalid_url', 'no_discussion')
        message: Human-readable error message
        status_code: HTTP status code (default 400)

    Returns:
        Tuple of (response, status_code) for Flask

    Example:
        return api_error('invalid_url', 'The provided URL is not valid.', 400)
    """
    response = jsonify({
        'error': code,
        'message': message
    })
    response.status_code = status_code
    return response


def register_error_handlers(blueprint):
    """
    Register error handlers for the API blueprint.
    Ensures all errors return JSON, not HTML.
    """

    @blueprint.errorhandler(400)
    def bad_request(e):
        message = str(e.description) if hasattr(e, 'description') else 'Bad request'
        return api_error('bad_request', message, 400)

    @blueprint.errorhandler(401)
    def unauthorized(e):
        return api_error('unauthorized', 'Authentication required.', 401)

    @blueprint.errorhandler(403)
    def forbidden(e):
        return api_error('forbidden', 'Access denied.', 403)

    @blueprint.errorhandler(404)
    def not_found(e):
        message = str(e.description) if hasattr(e, 'description') else 'Resource not found'
        return api_error('not_found', message, 404)

    @blueprint.errorhandler(429)
    def rate_limited(e):
        return api_error(
            'rate_limited',
            'Too many requests. Please retry in 60 seconds.',
            429
        )

    @blueprint.errorhandler(500)
    def internal_error(e):
        current_app.logger.error(f'API Internal Error: {e}')
        return api_error(
            'internal_error',
            'An internal error occurred. Please try again later.',
            500
        )

    @blueprint.errorhandler(HTTPException)
    def handle_http_exception(e):
        """Handle any other HTTP exceptions with JSON response."""
        return api_error(
            e.name.lower().replace(' ', '_'),
            e.description or str(e),
            e.code
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
