"""Unit tests for Sentry environment / release helpers."""

from app.lib.sentry_config import (
    resolve_sentry_app_role,
    resolve_sentry_environment,
    resolve_sentry_release,
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
