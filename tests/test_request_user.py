"""request_user helpers must not explode outside a request context."""

from app.lib.request_user import current_user_is_authenticated


def test_current_user_is_authenticated_false_with_no_app():
    # No Flask app/request at all (scheduler-style call sites).
    assert current_user_is_authenticated() is False


def test_current_user_is_authenticated_false_for_anonymous_request(app):
    with app.test_request_context('/'):
        assert current_user_is_authenticated() is False
