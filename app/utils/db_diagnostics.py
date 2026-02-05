from collections import Counter
import re
import time

from flask import current_app, g, has_request_context, request
from sqlalchemy import event
from sqlalchemy.engine import Engine

_ENGINE_LISTENER_ATTACHED = False


def _normalize_sql(statement: str) -> str:
    return re.sub(r"\s+", " ", statement).strip()


def init_n_plus_one_guard(app, enabled=None):
    """
    Lightweight N+1 detector for development.

    Logs warning if the same SQL statement is executed repeatedly in a request.
    """
    if enabled is None:
        enabled = app.config.get("NPLUS1_GUARD_ENABLED")
        if enabled is None:
            enabled = app.config.get("ENV", "").lower() != "production"
    if not enabled:
        return

    threshold = app.config.get("NPLUS1_QUERY_THRESHOLD", 5)
    total_threshold = app.config.get("NPLUS1_QUERY_TOTAL_THRESHOLD", 40)
    max_statements = app.config.get("NPLUS1_QUERY_MAX_STATEMENTS", 3)

    @app.before_request
    def _init_query_counter():
        g._query_counter = Counter()
        g._query_total = 0
        g._query_start_time = time.monotonic()

    @app.teardown_request
    def _log_suspected_nplus1(error=None):
        if not has_request_context():
            return
        counter = getattr(g, "_query_counter", None)
        total = getattr(g, "_query_total", 0)
        if not counter or total < total_threshold:
            return
        repeats = [(sql, count) for sql, count in counter.items() if count >= threshold]
        if not repeats:
            return
        repeats.sort(key=lambda item: item[1], reverse=True)
        duration_ms = int((time.monotonic() - getattr(g, "_query_start_time", time.monotonic())) * 1000)
        top = repeats[:max_statements]
        top_snippets = " | ".join(f"{count}x {sql[:180]}" for sql, count in top)
        current_app.logger.warning(
            "Potential N+1 query pattern detected (total=%s, repeated=%s, ms=%s, path=%s): %s",
            total,
            len(repeats),
            duration_ms,
            request.path,
            top_snippets,
        )

    global _ENGINE_LISTENER_ATTACHED
    if _ENGINE_LISTENER_ATTACHED:
        return

    @event.listens_for(Engine, "before_cursor_execute")
    def _count_query_calls(conn, cursor, statement, parameters, context, executemany):
        if not has_request_context():
            return
        if not statement:
            return
        g._query_total = getattr(g, "_query_total", 0) + 1
        counter = getattr(g, "_query_counter", None)
        if counter is None:
            counter = Counter()
            g._query_counter = counter
        counter[_normalize_sql(statement)] += 1

    _ENGINE_LISTENER_ATTACHED = True
