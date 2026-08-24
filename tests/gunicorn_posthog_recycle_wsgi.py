"""Minimal WSGI app for gunicorn+gevent PostHog recycle tests.

Loaded by gunicorn's gevent worker with ``preload_app`` off, so
``monkey.patch_all()`` has already run. Mirrors ``create_app`` PostHog
setup without Flask/DB: a live async client (analytics + AI lanes) whose
OS consumer threads are what hung ``Client.join`` in PYTHON-FLASK-JD.
"""
from __future__ import annotations

import os
import sys

from app.lib.posthog_utils import (
    _gevent_is_patching_threads,
    configure_posthog_credentials,
    register_posthog_atexit,
)

_API_KEY = os.environ.get("POSTHOG_API_KEY") or "phc_gunicorn_recycle_test"
_HOST = os.environ.get("POSTHOG_HOST") or "http://127.0.0.1:1"

configure_posthog_credentials(_API_KEY, _HOST, debug=False)
register_posthog_atexit()

import posthog as ph  # noqa: E402

# Build the client at import, not on first request, so recycle always has
# live OS consumers — the hang path, not an empty worker.
ph.setup()
_client = getattr(ph, "default_client", None)
if _client is not None:
    for _lane in getattr(_client, "_lanes", None) or ():
        start = getattr(_lane, "start", None)
        if callable(start):
            start()

_consumers = 0
if _client is not None:
    for _lane in getattr(_client, "_lanes", None) or ():
        _consumers += len(getattr(_lane, "consumers", None) or ())
    if not _consumers:
        _consumers = len(getattr(_client, "consumers", None) or ())

sys.stderr.write(
    "POSTHOG_RECYCLE_PROBE sync_mode=%s consumers=%s gevent_threads=%s\n"
    % (
        getattr(ph, "sync_mode", None),
        _consumers,
        _gevent_is_patching_threads(),
    )
)
sys.stderr.flush()


def app(environ, start_response):
    path = environ.get("PATH_INFO") or "/"
    if path in ("/", "/health", "/capture"):
        try:
            ph.capture("gunicorn-recycle-test", "recycle_probe")
        except Exception:
            pass
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ok"]
    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"no"]
