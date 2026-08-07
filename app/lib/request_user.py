"""Safe access to flask_login's ``current_user`` outside request contexts."""

from __future__ import annotations


def current_user_is_authenticated() -> bool:
    """Return whether the request has a logged-in user.

    Outside a request context (scheduler, service-layer tests without
    ``test_request_context``, CI without pytest-flask), flask_login's
    ``current_user`` LocalProxy resolves to ``None`` and
    ``.is_authenticated`` raises ``AttributeError``. Treat that as anonymous.
    """
    try:
        from flask import has_request_context

        if not has_request_context():
            return False
        from flask_login import current_user

        return bool(current_user.is_authenticated)
    except (AttributeError, RuntimeError):
        return False
