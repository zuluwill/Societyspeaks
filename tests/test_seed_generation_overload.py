"""Regression test: a 529 overload in the seed path degrades, not pages.

Sentry PYTHON-FLASK-H8/H9: an Anthropic 529 ``OverloadedError`` was logged at
ERROR ("Seed generation failed"), raising a noisy alert for a transient,
retryable server condition. It must log at WARNING and return an empty result so
the caller falls through to the next provider / deterministic fallback seeds.

Classifier unit tests live in test_llm_transient_errors.py (the shared home).
"""

import logging

from app.trending import seed_generator as sg


class _FakeOverloadedError(Exception):
    """Mimics anthropic.OverloadedError: str() carries the 529 payload."""


_FakeOverloadedError.__name__ = "OverloadedError"

_OVERLOAD_MSG = (
    "Error code: 529 - {'type': 'error', 'error': "
    "{'type': 'overloaded_error', 'message': 'Overloaded'}}"
)


def test_anthropic_overload_logs_warning_not_error(monkeypatch, caplog):
    """A 529 during an Anthropic seed call → WARNING + empty result, never ERROR."""
    class _Boom:
        class messages:
            @staticmethod
            def create(**_kwargs):
                raise _FakeOverloadedError(_OVERLOAD_MSG)

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda **_kwargs: _Boom())

    with caplog.at_level(logging.WARNING, logger="app.trending.seed_generator"):
        result = sg._generate_with_anthropic(
            topic=None,
            title="Should councils fund resilience programmes?",
            excerpt=None,
            source_name=None,
            count=5,
            api_key="sk-test",
        )

    assert result == []  # degraded gracefully
    assert any(
        rec.levelno == logging.WARNING and "overloaded" in rec.message.lower()
        for rec in caplog.records
    ), "expected a transient WARNING for the 529 overload"
    assert not any(
        rec.levelno >= logging.ERROR for rec in caplog.records
    ), "a transient 529 must not be logged at ERROR"
