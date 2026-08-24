"""Unit tests for Sentry environment / release helpers."""

import logging
from pathlib import Path

from app.lib.llm_transient_errors import sentry_should_drop_transient_llm
from app.lib.sentry_config import (
    is_expected_process_lifecycle_log,
    is_gunicorn_worker_stall_log,
    resolve_sentry_app_role,
    resolve_sentry_continuous_profiling,
    resolve_sentry_environment,
    resolve_sentry_profiles_sample_rate,
    resolve_sentry_release,
    resolve_sentry_traces_sample_rate,
    sentry_should_drop_lifecycle_event,
    sentry_should_keep_worker_stall_event,
)


def test_sentry_environment_defaults_to_production(monkeypatch):
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    assert resolve_sentry_environment() == "production"


def test_sentry_environment_respects_explicit_value(monkeypatch):
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    assert resolve_sentry_environment() == "staging"


def test_sentry_environment_blank_falls_back(monkeypatch):
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "   ")
    assert resolve_sentry_environment() == "production"


def test_sentry_release_prefers_explicit_over_render(monkeypatch):
    monkeypatch.setenv("SENTRY_RELEASE", "v1.2.3")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "deadbeef")
    assert resolve_sentry_release() == "v1.2.3"


def test_sentry_release_falls_back_to_render_git_commit(monkeypatch):
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "deadbeef")
    assert resolve_sentry_release() == "deadbeef"


def test_sentry_release_none_when_unset(monkeypatch):
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    assert resolve_sentry_release() is None


def test_sentry_app_role_defaults_to_legacy(monkeypatch):
    monkeypatch.delenv("APP_ROLE", raising=False)
    assert resolve_sentry_app_role() == "legacy"


def test_sentry_app_role_uses_app_role(monkeypatch):
    monkeypatch.setenv("APP_ROLE", "scheduler")
    assert resolve_sentry_app_role() == "scheduler"


def test_traces_sample_rate_defaults_to_ten_percent(monkeypatch):
    monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)
    assert resolve_sentry_traces_sample_rate() == 0.1


def test_profiles_sample_rate_defaults_to_off(monkeypatch):
    monkeypatch.delenv("SENTRY_PROFILES_SAMPLE_RATE", raising=False)
    assert resolve_sentry_profiles_sample_rate() == 0.0


def test_sample_rates_clamp_and_reject_garbage(monkeypatch):
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "2")
    assert resolve_sentry_traces_sample_rate() == 1.0
    monkeypatch.setenv("SENTRY_PROFILES_SAMPLE_RATE", "-1")
    assert resolve_sentry_profiles_sample_rate() == 0.0
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "nope")
    assert resolve_sentry_traces_sample_rate() == 0.1


def test_continuous_profiling_default_off(monkeypatch):
    monkeypatch.delenv("SENTRY_CONTINUOUS_PROFILING", raising=False)
    assert resolve_sentry_continuous_profiling() is False
    monkeypatch.setenv("SENTRY_CONTINUOUS_PROFILING", "false")
    assert resolve_sentry_continuous_profiling() is False
    monkeypatch.setenv("SENTRY_CONTINUOUS_PROFILING", "1")
    assert resolve_sentry_continuous_profiling() is True


def _error_record(name, message):
    return logging.LogRecord(
        name=name,
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_lifecycle_filter_drops_sigkill_and_generic_oom_text():
    rec = _error_record(
        "gunicorn.error",
        "Worker (pid:2928) was sent SIGKILL! Perhaps out of memory?",
    )
    assert sentry_should_drop_lifecycle_event({}, {"log_record": rec}) is True
    rec = _error_record("gunicorn.error", "Worker (pid:1) was sent SIGTERM")
    assert sentry_should_drop_lifecycle_event({}, {"log_record": rec}) is True
    rec = _error_record(
        "gunicorn.error",
        "Greenlet appears to be blocked (hub)",
    )
    assert is_expected_process_lifecycle_log(rec.getMessage()) is True


def test_lifecycle_filter_does_not_drop_worker_timeout_or_generic_timeouts():
    stall = "worker_abort [2928]: WORKER TIMEOUT — dumping thread + greenlet stacks"
    assert is_gunicorn_worker_stall_log(stall) is True
    assert is_expected_process_lifecycle_log(stall) is False
    rec = _error_record("gunicorn.error", stall)
    assert sentry_should_drop_lifecycle_event({}, {"log_record": rec}) is False
    assert sentry_should_keep_worker_stall_event({}, {"log_record": rec}) is True

    for msg in (
        "Request timeout",
        "LLM request timed out",
        "timeout",
        "Read timed out",
    ):
        assert is_expected_process_lifecycle_log(msg) is False
        assert is_gunicorn_worker_stall_log(msg) is False
        rec = _error_record("app.lib.foo", msg)
        assert sentry_should_drop_lifecycle_event({}, {"log_record": rec}) is False
        assert sentry_should_keep_worker_stall_event({}, {"log_record": rec}) is False


def test_llm_filter_does_not_swallow_gunicorn_worker_timeout():
    """is_timeout_error matches substring 'timeout'; gunicorn stalls must still page."""
    stall = "worker_abort [2928]: WORKER TIMEOUT — dumping thread + greenlet stacks"
    rec = _error_record("gunicorn.error", stall)
    assert sentry_should_drop_transient_llm({}, {"log_record": rec}) is False
    event = {"logentry": {"message": stall}}
    assert sentry_should_keep_worker_stall_event(event, {}) is True
    assert sentry_should_drop_transient_llm(
        {"exception": {"values": [{"type": "Exception", "value": stall}]}},
        {},
    ) is False


def test_llm_filter_still_drops_provider_timeout_logs():
    rec = _error_record("openai._base_client", "Request timed out.")
    assert sentry_should_drop_transient_llm({}, {"log_record": rec}) is True


def test_before_send_keeps_worker_stall_before_llm_timeout_filter():
    src = Path("app/__init__.py").read_text(encoding="utf-8")
    keep = src.index("if sentry_should_keep_worker_stall_event")
    llm = src.index("if sentry_should_drop_transient_llm")
    life = src.index("if sentry_should_drop_lifecycle_event")
    assert keep < llm < life
    assert "continuous_profiling_auto_start" in src
    assert "resolve_sentry_continuous_profiling()" in src
    assert "resolve_sentry_profiles_sample_rate()" in src

