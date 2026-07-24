"""Shared helpers for stable email unsubscribe links."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING
from urllib.parse import unquote

if TYPE_CHECKING:
    from app.models import DailyBriefSubscriber, DailyQuestionSubscriber


def normalize_unsubscribe_token(raw: Optional[str]) -> str:
    """Clean a token from the URL path (copy/paste noise, encoding, scanners)."""
    if not raw:
        return ''
    token = unquote(str(raw).strip())
    if token.lower() == 'none':
        return ''
    return token.rstrip('.,>;)\"\'')


def lookup_brief_subscriber_by_unsubscribe_token(
    raw_token: str,
) -> Optional['DailyBriefSubscriber']:
    from app.models import DailyBriefSubscriber

    token = normalize_unsubscribe_token(raw_token)
    if not token:
        return None
    subscriber = DailyBriefSubscriber.query.filter_by(unsubscribe_token=token).first()
    if subscriber:
        return subscriber
    return DailyBriefSubscriber.query.filter_by(magic_token=token).first()


def lookup_question_subscriber_by_unsubscribe_token(
    raw_token: str,
) -> Optional['DailyQuestionSubscriber']:
    from app.models import DailyQuestionSubscriber

    token = normalize_unsubscribe_token(raw_token)
    if not token:
        return None
    subscriber = DailyQuestionSubscriber.query.filter_by(unsubscribe_token=token).first()
    if subscriber:
        return subscriber
    return DailyQuestionSubscriber.query.filter_by(magic_token=token).first()


def build_brief_unsubscribe_url(base_url: str, subscriber: 'DailyBriefSubscriber') -> str:
    """Return a stable brief unsubscribe URL; never fall back to rotating magic_token."""
    subscriber.ensure_unsubscribe_token()
    if not subscriber.unsubscribe_token:
        raise ValueError(
            f'DailyBriefSubscriber {subscriber.id} has no unsubscribe_token after ensure'
        )
    return f"{base_url.rstrip('/')}/brief/unsubscribe/{subscriber.unsubscribe_token}"


def build_question_unsubscribe_url(base_url: str, subscriber: 'DailyQuestionSubscriber') -> str:
    """Return a stable daily-question unsubscribe URL."""
    subscriber.ensure_unsubscribe_token()
    if not subscriber.unsubscribe_token:
        raise ValueError(
            f'DailyQuestionSubscriber {subscriber.id} has no unsubscribe_token after ensure'
        )
    return f"{base_url.rstrip('/')}/daily/unsubscribe/{subscriber.unsubscribe_token}"
