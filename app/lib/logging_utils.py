"""Request-scoped logging helpers.

RequestIdFilter injects the current request's ID (from flask.g) into every
LogRecord so formatters can include it without each call site having to pass
it explicitly. Outside a request context (scheduler jobs, startup hooks,
worker processes) the field is populated with "-" so the formatter never
raises a KeyError.
"""

import logging
import uuid

from flask import g, has_request_context


class RequestIdFilter(logging.Filter):
    """Populate record.request_id from flask.g, or '-' outside request context."""

    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, 'request_id', '-') or '-'
        else:
            record.request_id = '-'
        return True


def new_request_id() -> str:
    """Short, URL-safe correlation ID. 12 hex chars is plenty at our request volume."""
    return uuid.uuid4().hex[:12]
