"""Platform LLM client: request shape, usage logging, and failure handling."""
import json
from types import SimpleNamespace

import anthropic
import pytest

from app.lib import llm_client
from app.lib.llm_client import LLMError, complete_json
from app.models import LLMUsage

SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok'], 'additionalProperties': False}


def _response(text='{"ok": true}', stop_reason='end_turn'):
    return SimpleNamespace(
        content=[SimpleNamespace(type='thinking', thinking=''), SimpleNamespace(type='text', text=text)],
        stop_reason=stop_reason,
        model='claude-opus-5-5',
        usage=SimpleNamespace(input_tokens=120, output_tokens=40),
    )


@pytest.fixture
def fake_client(monkeypatch):
    calls = []
    outcome = {'value': _response()}

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if isinstance(outcome['value'], Exception):
                raise outcome['value']
            return outcome['value']

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(llm_client.anthropic, 'Anthropic', _Client)
    return calls, outcome


def _ask():
    return complete_json(purpose='test.purpose', system='sys', prompt='hello', schema=SCHEMA, effort='low')


def test_request_uses_structured_output_effort_and_refusal_fallback(db, fake_client):
    calls, _outcome = fake_client

    assert _ask() == {'ok': True}

    request = calls[0]
    assert request['model'] == 'claude-opus-5-5'
    assert request['output_config'] == {'effort': 'low', 'format': {'type': 'json_schema', 'schema': SCHEMA}}
    assert request['extra_body'] == {'fallbacks': 'default'}
    assert request['extra_headers'] == {'anthropic-beta': 'server-side-fallback-2026-07-01'}
    for removed in ('temperature', 'top_p', 'thinking'):
        assert removed not in request, f'{removed} is rejected by this model'
    usage = LLMUsage.query.one()
    assert (usage.purpose, usage.input_tokens, usage.output_tokens, usage.succeeded) == ('test.purpose', 120, 40, True)


def test_model_can_be_overridden_by_config(app, db, fake_client):
    calls, _outcome = fake_client
    app.config['PLATFORM_LLM_MODEL'] = 'claude-sonnet-5-5'

    _ask()

    assert calls[0]['model'] == 'claude-sonnet-5-5'


@pytest.mark.parametrize('stop_reason, text', [
    ('refusal', ''),
    ('max_tokens', '{"ok": tr'),
    ('end_turn', 'not json'),
    ('end_turn', '[1, 2]'),
])
def test_unusable_answers_raise_and_are_logged_as_failures(db, fake_client, stop_reason, text):
    _calls, outcome = fake_client
    outcome['value'] = _response(text=text, stop_reason=stop_reason)

    with pytest.raises(LLMError):
        _ask()

    assert LLMUsage.query.count() == 1


def _status_error(cls, status):
    response = SimpleNamespace(status_code=status, headers={}, request=SimpleNamespace())
    error = cls.__new__(cls)
    Exception.__init__(error, 'boom')
    error.status_code = status
    error.response = response
    error.message = 'boom'
    return error


def test_outages_are_retryable_and_bad_requests_are_not(db, fake_client):
    _calls, outcome = fake_client

    outcome['value'] = _status_error(anthropic.RateLimitError, 429)
    with pytest.raises(LLMError) as rate_limited:
        _ask()
    outcome['value'] = _status_error(anthropic.InternalServerError, 529)
    with pytest.raises(LLMError) as overloaded:
        _ask()
    outcome['value'] = _status_error(anthropic.BadRequestError, 400)
    with pytest.raises(LLMError) as bad_request:
        _ask()

    assert rate_limited.value.retryable and overloaded.value.retryable
    assert not bad_request.value.retryable
    assert [usage.succeeded for usage in LLMUsage.query.all()] == [False, False, False]


def test_no_key_fails_without_calling_anyone(db, monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setattr(llm_client.anthropic, 'Anthropic', lambda **kwargs: pytest.fail('no client without a key'))

    with pytest.raises(LLMError) as error:
        _ask()

    assert not error.value.retryable
