"""Tests for the shared LLM transient-error classifier + logging helper.

Guards Sentry PYTHON-FLASK-H8/H9: a transient provider condition (rate-limit,
timeout, 5xx overload) must be recognised across every LLM call site so it logs
at WARNING and degrades gracefully, never a hard ERROR / paged exception.
"""

import logging

import pytest

from app.lib.llm_transient_errors import (
    describe_transient_llm_error,
    is_connection_error,
    is_overloaded_error,
    is_rate_limit_error,
    is_timeout_error,
    is_transient_llm_error,
    log_llm_error,
)


def _named(type_name: str, message: str) -> Exception:
    """Build an exception whose class name mimics a provider SDK error class.

    A fresh class per call — mutating one shared class's __name__ would leak the
    last-set name across all parametrized cases.
    """
    cls = type(type_name, (Exception,), {})
    return cls(message)


OVERLOAD_529 = (
    "Error code: 529 - {'type': 'error', 'error': "
    "{'type': 'overloaded_error', 'message': 'Overloaded'}}"
)


@pytest.mark.parametrize("error, expected", [
    (Exception("Error code: 429 - rate limit exceeded"), True),
    (Exception("You have exceeded your quota"), True),
    (Exception("Too Many Requests"), True),
    (_named("RateLimitError", "slow down"), True),
    (Exception("connection reset"), False),
    (Exception(OVERLOAD_529), False),
])
def test_is_rate_limit_error(error, expected):
    assert is_rate_limit_error(error) is expected


@pytest.mark.parametrize("error, expected", [
    (Exception("Request timed out"), True),
    (_named("APITimeoutError", "deadline exceeded"), True),
    (_named("ReadTimeout", ""), True),
    (Exception("bad request"), False),
])
def test_is_timeout_error(error, expected):
    assert is_timeout_error(error) is expected


@pytest.mark.parametrize("error, expected", [
    (Exception(OVERLOAD_529), True),
    (Exception("Error code: 529 - Overloaded"), True),
    (_named("OverloadedError", "Overloaded"), True),
    (_named("InternalServerError", "Internal server error"), True),
    (Exception("503 Service Unavailable"), True),
    (Exception("invalid_request_error: bad field"), False),
    (Exception("could not parse JSON"), False),
])
def test_is_overloaded_error(error, expected):
    assert is_overloaded_error(error) is expected


def test_is_connection_error():
    assert is_connection_error(_named("APIConnectionError", "failed to connect")) is True
    assert is_connection_error(Exception("connection reset by peer")) is True
    assert is_connection_error(Exception("invalid_request_error")) is False


def test_is_transient_llm_error_covers_all_classes():
    assert is_transient_llm_error(Exception("429 rate limit")) is True
    assert is_transient_llm_error(Exception("timed out")) is True
    assert is_transient_llm_error(Exception(OVERLOAD_529)) is True
    assert is_transient_llm_error(_named("APIConnectionError", "reset")) is True
    assert is_transient_llm_error(ValueError("invalid JSON from LLM")) is False


def test_describe_prefers_most_specific_label():
    assert describe_transient_llm_error(Exception("429 rate limit")) == "rate-limited/quota-limited"
    assert describe_transient_llm_error(Exception("request timed out")) == "timed out"
    assert describe_transient_llm_error(Exception(OVERLOAD_529)) == "overloaded (5xx)"
    assert describe_transient_llm_error(_named("APIConnectionError", "x")) == "connection error"
    assert describe_transient_llm_error(ValueError("bad")) == "transient"

    # Type-name alone is enough for SDK OverloadedError even with a sparse message.
    assert is_overloaded_error(_named("OverloadedError", "")) is True
    assert is_overloaded_error(_named("InternalServerError", "")) is True


def test_log_llm_error_warns_on_transient(caplog):
    logger = logging.getLogger("test.llm.transient")
    with caplog.at_level(logging.WARNING, logger="test.llm.transient"):
        is_transient = log_llm_error(logger, Exception(OVERLOAD_529), context="Seed gen failed")
    assert is_transient is True
    assert caplog.records and caplog.records[-1].levelno == logging.WARNING
    assert "overloaded" in caplog.records[-1].message.lower()


def test_log_llm_error_errors_on_permanent(caplog):
    logger = logging.getLogger("test.llm.permanent")
    with caplog.at_level(logging.WARNING, logger="test.llm.permanent"):
        is_transient = log_llm_error(
            logger, ValueError("invalid JSON from LLM"), context="Seed gen failed"
        )
    assert is_transient is False
    assert caplog.records and caplog.records[-1].levelno == logging.ERROR
