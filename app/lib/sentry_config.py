"""Sentry SDK environment, sampling, and expected-noise filters.

Keep labels explicit and stable across hosts. Do not derive the Sentry
environment from FLASK_ENV — that value is not a deploy identity and has
produced duplicate labels (e.g. ``prod`` vs SDK default ``production``).
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

# Gunicorn/gevent lifecycle lines. These are process management, not product
# bugs. Do NOT put generic "timeout" here — a real request stall after the
# PostHog worker_exit hang is fixed should still page via worker_abort.
_LIFECYCLE_LOG_PHRASES: tuple[str, ...] = (
    "was sent SIGTERM",
    "Worker was sent SIGTERM",
    "was sent SIGKILL",
    "Perhaps out of memory?",
    "exited with code 128",
)

_GEVENT_MONITOR_MARKERS: tuple[str, ...] = (
    "appears to be blocked",
    "Blocked Stack (for thread id",
)

# Real 120s stalls. Must page. Do not add these to _LIFECYCLE_LOG_PHRASES,
# and do not let the LLM "timeout" substring filter swallow them.
_WORKER_STALL_PHRASES: tuple[str, ...] = (
    "WORKER TIMEOUT",
    "worker_abort",
)


def resolve_sentry_environment() -> str:
    """Return the Sentry environment name (never empty)."""
    value = (os.getenv("SENTRY_ENVIRONMENT") or "production").strip()
    return value or "production"


def resolve_sentry_release() -> Optional[str]:
    """Prefer explicit SENTRY_RELEASE, then Render's git commit SHA."""
    for key in ("SENTRY_RELEASE", "RENDER_GIT_COMMIT"):
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    return None


def resolve_sentry_app_role() -> str:
    """Tag events with APP_ROLE so web/scheduler/worker are distinguishable."""
    value = (os.getenv("APP_ROLE") or "legacy").strip()
    return value or "legacy"


def _bounded_sample_rate(raw: Optional[str], default: float) -> float:
    try:
        rate = float((raw or "").strip() or default)
    except ValueError:
        return default
    if rate < 0.0:
        return 0.0
    if rate > 1.0:
        return 1.0
    return rate


def resolve_sentry_traces_sample_rate() -> float:
    """Transaction tracing (spans). Default 10%; not the continuous profiler."""
    return _bounded_sample_rate(os.getenv("SENTRY_TRACES_SAMPLE_RATE"), 0.1)


def resolve_sentry_profiles_sample_rate() -> float:
    """Transaction profiles. Default 0 — extra OS threads fight gunicorn+gevent.

    Opt in with SENTRY_PROFILES_SAMPLE_RATE (0–1) if investigating a specific
    endpoint off the gevent hub (e.g. a sync worker).
    """
    return _bounded_sample_rate(os.getenv("SENTRY_PROFILES_SAMPLE_RATE"), 0.0)


def resolve_sentry_continuous_profiling() -> bool:
    """Continuous profiler starts a sleeper thread in every process.

    Default off: abort dumps from production (2026-08) showed
    ``sentry_sdk.profiler.transaction_profiler`` on every timed-out worker.
    Opt in with SENTRY_CONTINUOUS_PROFILING=1.
    """
    raw = (os.getenv("SENTRY_CONTINUOUS_PROFILING") or "").strip().lower()
    return raw in ("1", "true", "on", "yes")


def is_gunicorn_worker_stall_log(message: str) -> bool:
    """True for gunicorn abort / 120s timeout lines that must still page."""
    if not message:
        return False
    return any(phrase in message for phrase in _WORKER_STALL_PHRASES)


def is_expected_process_lifecycle_log(message: str) -> bool:
    """True for gunicorn/gevent process-management lines that must not page.

    Intentionally does **not** match ``WORKER TIMEOUT`` / ``worker_abort``.
    After PostHog shutdown no longer joins OS threads from the hub, those
    lines mean a real 120s stall and should still reach Sentry.
    """
    if not message:
        return False
    if any(phrase in message for phrase in _LIFECYCLE_LOG_PHRASES):
        return True
    if "appears to be blocked" in message and "Greenlet" in message:
        return True
    if any(marker in message for marker in _GEVENT_MONITOR_MARKERS[1:]):
        return True
    return False


def _log_record_message(hint: Mapping[str, Any]) -> str:
    record = hint.get("log_record")
    if record is None:
        return ""
    if hasattr(record, "getMessage"):
        return record.getMessage() or ""
    return str(getattr(record, "msg", "") or "")


def _event_log_message(event: Optional[Mapping[str, Any]]) -> str:
    if not event:
        return ""
    logentry = event.get("logentry") or {}
    return str(logentry.get("message") or logentry.get("formatted") or "")


def sentry_should_keep_worker_stall_event(
    event: Optional[Mapping[str, Any]],
    hint: Optional[Mapping[str, Any]] = None,
) -> bool:
    """True when before_send must keep this event (skip other drop filters).

    Gunicorn ``WORKER TIMEOUT`` / ``worker_abort`` ERROR logs contain the
    substring ``timeout``. The LLM transient filter would otherwise drop them.
    """
    hint = hint or {}
    record = hint.get("log_record")
    if record is not None and str(getattr(record, "name", "") or "").startswith(
        "gunicorn"
    ):
        if is_gunicorn_worker_stall_log(_log_record_message(hint)):
            return True
    if is_gunicorn_worker_stall_log(_log_record_message(hint)):
        return True
    if is_gunicorn_worker_stall_log(_event_log_message(event)):
        return True
    exc_info = hint.get("exc_info")
    if exc_info and len(exc_info) > 1:
        if is_gunicorn_worker_stall_log(str(exc_info[1] or "")):
            return True
    for exc in ((event or {}).get("exception") or {}).get("values") or []:
        if is_gunicorn_worker_stall_log(str(exc.get("value") or "")):
            return True
    return False


def sentry_should_drop_lifecycle_event(
    event: Optional[Mapping[str, Any]],
    hint: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Drop gunicorn/gevent lifecycle noise from before_send."""
    hint = hint or {}
    if is_expected_process_lifecycle_log(_log_record_message(hint)):
        return True
    if is_expected_process_lifecycle_log(_event_log_message(event)):
        return True
    exc_info = hint.get("exc_info") if hint else None
    if exc_info and len(exc_info) > 1:
        if is_expected_process_lifecycle_log(str(exc_info[1] or "")):
            return True
    for exc in ((event or {}).get("exception") or {}).get("values") or []:
        if is_expected_process_lifecycle_log(str(exc.get("value") or "")):
            return True
    return False
