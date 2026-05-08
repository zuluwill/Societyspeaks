"""Tests for shared DB connectivity classification and HTTP error behaviour."""

import json

import pytest
from sqlalchemy.exc import DisconnectionError, OperationalError

from app import request_wants_json_errors
from app.lib.db_transient_errors import (
    HTTP_RETRY_AFTER_DB_UNAVAILABLE_SEC,
    is_transient_db_connectivity_error,
)


@pytest.fixture
def client(app):
    return app.test_client()


def _op_with_message(msg: str) -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(msg))


@pytest.mark.parametrize(
    "message",
    (
        "connection timed out",
        "SSL connection has been closed",
        "server closed the connection unexpectedly",
        "could not connect to server: Network is unreachable",
        "connection reset by peer",
    ),
)
def test_transient_classification_positive(message):
    assert is_transient_db_connectivity_error(_op_with_message(message))
    assert is_transient_db_connectivity_error(Exception(message))


@pytest.mark.parametrize(
    "message",
    (
        "password authentication failed for user \"app\"",
        "FATAL:  database \"wrongdb\" does not exist",
        "syntax error at or near \"FOO\"",
    ),
)
def test_transient_classification_negative(message):
    assert not is_transient_db_connectivity_error(_op_with_message(message))


def test_disconnection_error_union():
    exc = DisconnectionError("SELECT 1", {}, Exception("connection was closed"))
    assert is_transient_db_connectivity_error(exc)


def test_request_wants_json_errors_embed_header(app):
    with app.test_request_context("/", headers=[("X-Embed-Request", "1")]):
        from flask import request as rq

        assert request_wants_json_errors(rq) is True


def test_request_wants_json_errors_api_path(app):
    with app.test_request_context("/api/discussions/by-article-url"):
        from flask import request as rq

        assert request_wants_json_errors(rq) is True


def test_app_level_transient_db_error_returns_json_for_api_path(app, client):
    """Non-blueprint routes under /api/ still get JSON 503 from the app handler."""

    @app.route("/api/__db_transient_test__")
    def _boom():
        raise _op_with_message("connection timed out")

    resp = client.get("/api/__db_transient_test__")
    assert resp.status_code == 503
    assert resp.is_json
    payload = resp.get_json()
    assert payload["error"] == "service_unavailable"
    assert resp.headers.get("Retry-After") == str(HTTP_RETRY_AFTER_DB_UNAVAILABLE_SEC)


def test_app_level_non_transient_db_error_json_for_api_path(app, client):
    @app.route("/api/__db_perm_test__")
    def _boom():
        raise _op_with_message('password authentication failed for user "x"')

    resp = client.get("/api/__db_perm_test__")
    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json()["error"] == "internal_error"


def test_api_blueprint_db_handler_returns_json(app, client):
    """Blueprints using register_error_handlers get JSON for SQLAlchemy outages."""
    from flask import Blueprint
    from sqlalchemy.exc import OperationalError

    from app.api.errors import register_error_handlers

    bp = Blueprint("db_err_isolation", __name__)

    @bp.route("/boom")
    def _boom():
        raise OperationalError("SELECT 1", {}, Exception("connection timed out"))

    register_error_handlers(bp)
    app.register_blueprint(bp, url_prefix="/api/db-err-test")

    resp = client.get("/api/db-err-test/boom")
    assert resp.status_code == 503
    data = json.loads(resp.data)
    assert data["error"] == "service_unavailable"
    assert resp.headers.get("Retry-After") == str(HTTP_RETRY_AFTER_DB_UNAVAILABLE_SEC)


def test_with_db_retry_catches_disconnection_error(app):
    """with_db_retry must retry DisconnectionError (not a DBAPIError subclass).

    DisconnectionError is a direct SQLAlchemyError subclass, completely outside
    the OperationalError / DBAPIError hierarchy.  If the catch clause omits it,
    a DisconnectionError raised mid-request escapes without retry.
    """
    from app.db_retry import with_db_retry

    call_count = {"n": 0}

    with app.app_context():
        @with_db_retry(max_attempts=2, delay=0)
        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise DisconnectionError("connection was closed")
            return "ok"

        result = flaky()

    assert result == "ok"
    assert call_count["n"] == 2, "Expected exactly one retry after DisconnectionError"
