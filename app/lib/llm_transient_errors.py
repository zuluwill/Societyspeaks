"""Classify transient LLM provider failures (rate-limit, timeout, 5xx overload).

Single source of truth for OpenAI/Anthropic transient-error handling, mirroring
:mod:`app.lib.db_transient_errors` for the database layer.

A transient failure is a retryable server-side or network condition — the
provider SDKs already retry these with exponential backoff (``max_retries``);
when those retries are exhausted the surfaced error should be logged at
**WARNING** and the caller should degrade gracefully (fallback content, skip the
item, or return a clean 503) — never a hard **ERROR** that pages the team on a
routine provider blip. Non-transient failures (bad request, auth, JSON parse)
stay at ERROR.

Matching is by exception **type name** and case-insensitive message substring so
it works across OpenAI and Anthropic SDK versions without importing either.
Seen in production as Anthropic ``OverloadedError`` (``Error code: 529``) and
``InternalServerError`` (``Error code: 500``).
"""

from __future__ import annotations

import logging

# SDK exception class names that are always treated as transient for Sentry filtering.
TRANSIENT_LLM_EXCEPTION_TYPE_NAMES = frozenset({
    "InternalServerError",
    "OverloadedError",
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ReadTimeout",
    "Timeout",
})


def is_rate_limit_error(error: BaseException) -> bool:
    """429 / quota exhaustion — retryable after a backoff."""
    text = str(error).lower()
    return (
        "rate limit" in text
        or "too many requests" in text
        or "429" in text
        or "quota" in text
        or type(error).__name__ == "RateLimitError"
    )


def is_timeout_error(error: BaseException) -> bool:
    """Request/connection timeout — retryable."""
    text = str(error).lower()
    return (
        "timed out" in text
        or "timeout" in text
        or type(error).__name__ in ("APITimeoutError", "ReadTimeout", "ConnectTimeout", "Timeout")
    )


def is_overloaded_error(error: BaseException) -> bool:
    """Transient server-side overload / 5xx — retryable, not a hard failure."""
    text = str(error).lower()
    name = type(error).__name__
    if name in ("OverloadedError", "InternalServerError"):
        return True
    if any(
        phrase in text
        for phrase in (
            "overloaded",
            "529",
            "service unavailable",
            "internal server error",
            "bad gateway",
            "gateway timeout",
        )
    ):
        return True
    # OpenAI/Anthropic APIStatusError carries the HTTP status in the message.
    if name == "APIStatusError" and any(
        code in text for code in (" 500", " 502", " 503", " 504", " 529", "code: 5")
    ):
        return True
    return False


def is_connection_error(error: BaseException) -> bool:
    """Provider SDK / network connection drop — retryable."""
    text = str(error).lower()
    name = type(error).__name__
    return (
        name in ("APIConnectionError", "ConnectError", "ConnectionError")
        or "connection error" in text
        or "connection reset" in text
        or "connection aborted" in text
        or "network is unreachable" in text
    )


def is_transient_llm_error(error: BaseException) -> bool:
    """True for any retryable provider condition (rate-limit, timeout, 5xx, connection)."""
    return (
        is_rate_limit_error(error)
        or is_timeout_error(error)
        or is_overloaded_error(error)
        or is_connection_error(error)
    )


def describe_transient_llm_error(error: BaseException) -> str:
    """Short label for logging (checked most-specific first)."""
    if is_rate_limit_error(error):
        return "rate-limited/quota-limited"
    if is_timeout_error(error):
        return "timed out"
    if is_overloaded_error(error):
        return "overloaded (5xx)"
    if is_connection_error(error):
        return "connection error"
    return "transient"


def log_llm_error(
    logger: logging.Logger,
    error: BaseException,
    *,
    context: str,
    exc_info: bool = False,
) -> bool:
    """Log an LLM provider failure at the right level for its class.

    WARNING for a transient/retryable condition, ERROR otherwise. Does **not**
    change control flow — the caller keeps its own return/raise/continue.

    Returns ``True`` when the error was classified as transient, so callers that
    care (e.g. to return a 503 vs a 500) can branch on it without re-classifying.
    """
    if is_transient_llm_error(error):
        logger.warning(
            "%s — %s: %s", context, describe_transient_llm_error(error), error
        )
        return True
    logger.error("%s: %s", context, error, exc_info=exc_info)
    return False


def sentry_should_drop_transient_llm(event, hint) -> bool:
    """Return True when a Sentry event is a retryable provider blip (already logged).

    Safety net for call sites that still re-raise after :func:`log_llm_error`, and
    for SDK exceptions captured before our handlers run.

    Gunicorn ``WORKER TIMEOUT`` logs contain the substring ``timeout``; they are
    process stalls, not LLM blips, and must not be dropped here.
    """
    from app.lib.sentry_config import (
        is_expected_process_lifecycle_log,
        is_gunicorn_worker_stall_log,
    )

    event = event or {}
    hint = hint or {}

    exc_info = hint.get("exc_info")
    if exc_info and len(exc_info) >= 2 and exc_info[1] is not None:
        if is_gunicorn_worker_stall_log(str(exc_info[1])):
            return False
        if is_transient_llm_error(exc_info[1]):
            return True

    for exc in (event.get("exception") or {}).get("values") or []:
        typ = exc.get("type") or ""
        val = exc.get("value") or ""
        if is_gunicorn_worker_stall_log(val):
            return False
        if typ in TRANSIENT_LLM_EXCEPTION_TYPE_NAMES:
            return True
        if is_transient_llm_error(Exception(val)):
            return True

    if "log_record" in hint:
        record = hint["log_record"]
        msg = (record.getMessage() or "") if hasattr(record, "getMessage") else str(record.msg or "")
        logger_name = str(getattr(record, "name", "") or "")
        # gunicorn ERROR logs are process lifecycle, not LLM provider blips.
        if logger_name.startswith("gunicorn"):
            return False
        if is_gunicorn_worker_stall_log(msg) or is_expected_process_lifecycle_log(msg):
            return False
        if record.levelno >= logging.ERROR and is_transient_llm_error(Exception(msg)):
            return True

    return False
