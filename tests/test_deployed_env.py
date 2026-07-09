"""Tests for deployed-production environment detection."""

import pytest

from app.lib.deployed_env import is_deployed_production


@pytest.fixture(autouse=True)
def _clear_deploy_flags(monkeypatch):
    monkeypatch.delenv('DEPLOYED_PRODUCTION', raising=False)
    monkeypatch.delenv('REPLIT_DEPLOYMENT', raising=False)
    monkeypatch.delenv('FLASK_ENV', raising=False)
    monkeypatch.delenv('ALLOW_EMAIL_IN_NON_PROD', raising=False)


def test_not_deployed_by_default():
    assert is_deployed_production() is False


def test_flask_env_production_is_not_enough(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')
    assert is_deployed_production() is False


def test_deployed_production_flag(monkeypatch):
    monkeypatch.setenv('DEPLOYED_PRODUCTION', '1')
    assert is_deployed_production() is True


def test_legacy_replit_deployment_flag(monkeypatch):
    monkeypatch.setenv('REPLIT_DEPLOYMENT', '1')
    assert is_deployed_production() is True


def test_email_gate_uses_deployed_helper(monkeypatch):
    from app.resend_client import _email_sending_allowed_for_environment

    assert _email_sending_allowed_for_environment() is False

    monkeypatch.setenv('DEPLOYED_PRODUCTION', '1')
    assert _email_sending_allowed_for_environment() is True


def test_email_gate_allow_override(monkeypatch):
    from app.resend_client import _email_sending_allowed_for_environment

    monkeypatch.setenv('ALLOW_EMAIL_IN_NON_PROD', '1')
    assert _email_sending_allowed_for_environment() is True


def test_scheduler_production_gate(monkeypatch):
    from app.scheduler import _is_production_environment

    assert _is_production_environment() is False
    monkeypatch.setenv('DEPLOYED_PRODUCTION', '1')
    assert _is_production_environment() is True
