"""Resolve one-click email vote tokens for question or brief subscribers."""

from __future__ import annotations

from typing import Literal, Optional, Tuple, Union

from flask import current_app
from itsdangerous import URLSafeTimedSerializer

from app.models import DailyBriefSubscriber, DailyQuestionSubscriber

VoterChannel = Literal['question', 'brief']
SubscriberT = Union[DailyQuestionSubscriber, DailyBriefSubscriber]

# The signed ``type`` claim that identifies a brief-list token. Question-list
# tokens use ``'vote'`` (see DailyQuestionSubscriber.generate_vote_token).
_BRIEF_TOKEN_TYPE = 'brief_vote'


def _peek_token_type(token: str) -> Optional[str]:
    """
    Read the (unverified) ``type`` claim so we can dispatch to one verifier.

    ``loads_unsafe`` recovers the payload without checking the signature or the
    per-purpose salt, so it works for either token family and never raises on a
    bad/garbage token — it returns ``(False, None)``. The claim is only used to
    *pick* a verifier; the chosen verifier still checks the signature.
    """
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        _sig_ok, payload = serializer.loads_unsafe(token)
    except Exception:
        return None
    return payload.get('type') if isinstance(payload, dict) else None


def resolve_one_click_vote_token(
    token: str,
) -> Tuple[Optional[SubscriberT], Optional[int], Optional[str], Optional[VoterChannel]]:
    """
    Verify a signed vote token from either subscriber list.

    Dispatches on the token's signed ``type`` claim so verification runs exactly
    once. Trying both verifiers in sequence used to hand a valid brief token to
    the question verifier first, tripping a false ``Token type mismatch`` WARNING
    on the happy path of every brief vote.

    Returns (subscriber, question_id, error_code, channel). On any failure the
    channel is ``None`` and error_code carries the reason from the verifier that
    owns the token type.
    """
    if _peek_token_type(token) == _BRIEF_TOKEN_TYPE:
        subscriber, question_id, error = DailyBriefSubscriber.verify_vote_token(token)
        return subscriber, question_id, error, ('brief' if error is None else None)

    subscriber, question_id, error = DailyQuestionSubscriber.verify_vote_token(token)
    return subscriber, question_id, error, ('question' if error is None else None)
