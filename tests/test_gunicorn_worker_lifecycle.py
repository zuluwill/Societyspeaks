"""Contracts for gunicorn worker recycle / PostHog shutdown (Render /health)."""

import inspect
from pathlib import Path

import gunicorn_config


def test_preload_app_stays_off():
    assert gunicorn_config.preload_app is False


def test_max_requests_recycle_stays_enabled_with_jitter():
    """Recycle bounds per-worker memory; jitter avoids lockstep SIGKILLs."""
    assert gunicorn_config.max_requests == 1000
    assert gunicorn_config.max_requests_jitter >= 300


def test_worker_exit_bounds_posthog_shutdown_with_gevent_timeout():
    src = inspect.getsource(gunicorn_config.worker_exit)
    assert "shutdown_server_posthog" in src
    assert "GeventTimeout" in src
    assert gunicorn_config._WORKER_EXIT_BUDGET_SECONDS <= 5.0


def test_render_web_keeps_profiling_off():
    src = Path("render.yaml").read_text(encoding="utf-8")
    assert 'SENTRY_PROFILES_SAMPLE_RATE' in src
    assert 'SENTRY_CONTINUOUS_PROFILING' in src
    assert 'value: "0"' in src.split("SENTRY_PROFILES_SAMPLE_RATE", 1)[1][:200]
    assert 'value: "false"' in src.split("SENTRY_CONTINUOUS_PROFILING", 1)[1][:200]
