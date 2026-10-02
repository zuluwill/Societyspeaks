"""Platform LLM client for product features that run on Society Speaks' own key.

One place for model choice, timeouts, retries, structured output and usage
logging. Every call writes an ``LLMUsage`` row, which is what the cost of a
consultation is measured from.

Callers ask for JSON that matches a schema and get a dict back, or an
``LLMError``. They are expected to degrade when it is raised (hold for a
human, fall back to a template): this module never invents a result.
"""
import json
import logging
import os
import time
from typing import Optional

import anthropic
from flask import current_app

from app import db
from app.lib.llm_transient_errors import log_llm_error
from app.models import LLMUsage

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'claude-opus-5-5'
# Re-runs a request the safety classifiers decline on Anthropic's recommended
# substitute, inside the same call.
_FALLBACK_BETA = 'server-side-fallback-2026-07-01'
# One call is bounded at twice this (the request and one retry). Job timeouts
# in ``app.consultations.jobs`` are set from that bound.
_REQUEST_TIMEOUT_SECONDS = 120.0
_MAX_RETRIES = 1


class LLMError(Exception):
    """The model could not produce a usable answer."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def platform_llm_available() -> bool:
    return bool(os.environ.get('ANTHROPIC_API_KEY'))


def _model() -> str:
    return current_app.config.get('PLATFORM_LLM_MODEL') or DEFAULT_MODEL


def _record_usage(*, purpose, model, response, started, succeeded, consultation_id) -> None:
    usage = getattr(response, 'usage', None)
    try:
        db.session.add(LLMUsage(
            purpose=purpose,
            provider='anthropic',
            model=getattr(response, 'model', None) or model,
            input_tokens=int(getattr(usage, 'input_tokens', 0) or 0),
            output_tokens=int(getattr(usage, 'output_tokens', 0) or 0),
            duration_ms=int((time.monotonic() - started) * 1000),
            succeeded=succeeded,
            consultation_id=consultation_id,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.warning('Could not record LLM usage for %s', purpose, exc_info=True)


def complete_json(
    *,
    purpose: str,
    system: str,
    prompt: str,
    schema: dict,
    effort: str = 'medium',
    max_tokens: int = 16000,
    consultation_id: Optional[int] = None,
) -> dict:
    """Ask the model for JSON matching ``schema``; return it parsed.

    Raises ``LLMError`` when no key is configured, the provider fails after
    the SDK's own retries, the request is declined, or the output is cut off.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise LLMError('No platform LLM key is configured.')

    model = _model()
    client = anthropic.Anthropic(api_key=api_key, timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=_MAX_RETRIES)
    started = time.monotonic()
    response = None
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{'role': 'user', 'content': prompt}],
            output_config={
                'effort': effort,
                'format': {'type': 'json_schema', 'schema': schema},
            },
            extra_headers={'anthropic-beta': _FALLBACK_BETA},
            extra_body={'fallbacks': 'default'},
        )
    except anthropic.RateLimitError as exc:
        log_llm_error(logger, exc, context=f'{purpose}: rate limited')
        raise LLMError('The model is rate limited.', retryable=True) from exc
    except anthropic.APIConnectionError as exc:
        log_llm_error(logger, exc, context=f'{purpose}: connection failed')
        raise LLMError('Could not reach the model.', retryable=True) from exc
    except anthropic.APIStatusError as exc:
        log_llm_error(logger, exc, context=f'{purpose}: API error')
        raise LLMError(f'The model returned an error ({exc.status_code}).', retryable=exc.status_code >= 500) from exc
    finally:
        if response is None:
            _record_usage(
                purpose=purpose, model=model, response=None, started=started,
                succeeded=False, consultation_id=consultation_id,
            )

    stop_reason = getattr(response, 'stop_reason', None)
    text = next((block.text for block in response.content if block.type == 'text'), None)
    succeeded = stop_reason == 'end_turn' and bool(text)
    _record_usage(
        purpose=purpose, model=model, response=response, started=started,
        succeeded=succeeded, consultation_id=consultation_id,
    )

    if stop_reason == 'refusal':
        raise LLMError('The model declined this request.')
    if stop_reason == 'max_tokens':
        raise LLMError('The model ran out of room before finishing.')
    if not text:
        raise LLMError('The model returned no text.')
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise LLMError('The model returned invalid JSON.') from exc
    if not isinstance(data, dict):
        raise LLMError('The model returned JSON of the wrong shape.')
    return data
