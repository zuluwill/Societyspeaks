"""
Safe deletion of Daily Brief / Daily Question email-list subscribers.

``email_event`` rows reference subscribers for analytics drill-down. Deleting a
subscriber without clearing those FKs causes IntegrityError on Postgres/SQLite.
Application code unlinks events before delete; the DB migration adds
ON DELETE SET NULL as defense in depth for any code path that omits the unlink.
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Sequence, Union

from app import db
from app.models import DailyBriefSubscriber, DailyQuestionSubscriber
from app.models.email import EmailEvent

logger = logging.getLogger(__name__)


class InvalidSubscriberIds(ValueError):
    """Raised when admin bulk-delete receives non-numeric or non-positive ids."""


def parse_subscriber_ids(raw_ids: Iterable[Union[str, int]]) -> List[int]:
    """
    Parse, validate, and dedupe subscriber ids from admin form posts.

    Raises:
        InvalidSubscriberIds: empty after strip, non-integer, or <= 0.
    """
    seen: set[int] = set()
    out: List[int] = []
    for raw in raw_ids:
        if raw is None:
            continue
        if isinstance(raw, int):
            value = raw
        else:
            text = str(raw).strip()
            if not text:
                continue
            try:
                value = int(text, 10)
            except ValueError as exc:
                raise InvalidSubscriberIds(f'Invalid subscriber id: {raw!r}') from exc
        if value <= 0:
            raise InvalidSubscriberIds(f'Invalid subscriber id: {raw!r}')
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def unlink_email_events_for_brief_subscribers(subscriber_ids: Sequence[int]) -> int:
    """Null ``brief_subscriber_id`` on analytics rows; returns rows updated."""
    if not subscriber_ids:
        return 0
    count = EmailEvent.query.filter(
        EmailEvent.brief_subscriber_id.in_(subscriber_ids)
    ).update({'brief_subscriber_id': None}, synchronize_session=False)
    if count:
        logger.info(
            'Unlinked %s email_event row(s) from brief subscriber id(s) %s',
            count,
            list(subscriber_ids),
        )
    return count


def unlink_email_events_for_question_subscribers(subscriber_ids: Sequence[int]) -> int:
    """Null ``question_subscriber_id`` on analytics rows; returns rows updated."""
    if not subscriber_ids:
        return 0
    count = EmailEvent.query.filter(
        EmailEvent.question_subscriber_id.in_(subscriber_ids)
    ).update({'question_subscriber_id': None}, synchronize_session=False)
    if count:
        logger.info(
            'Unlinked %s email_event row(s) from question subscriber id(s) %s',
            count,
            list(subscriber_ids),
        )
    return count


def delete_brief_subscriber(subscriber_id: int) -> bool:
    """
    Unlink email analytics and delete one Daily Brief subscriber.

    Returns:
        True if a row was deleted, False if id not found.
    """
    subscriber = db.session.get(DailyBriefSubscriber, subscriber_id)
    if subscriber is None:
        return False
    unlink_email_events_for_brief_subscribers([subscriber_id])
    db.session.delete(subscriber)
    return True


def delete_brief_subscribers_bulk(subscriber_ids: Sequence[int]) -> int:
    """Unlink analytics and bulk-delete Daily Brief subscribers. Returns delete count."""
    ids = list(subscriber_ids)
    if not ids:
        return 0
    unlink_email_events_for_brief_subscribers(ids)
    return DailyBriefSubscriber.query.filter(
        DailyBriefSubscriber.id.in_(ids)
    ).delete(synchronize_session=False)


def delete_question_subscriber(subscriber_id: int) -> bool:
    """
    Unlink email analytics and delete one Daily Question subscriber.

    Returns:
        True if a row was deleted, False if id not found.
    """
    subscriber = db.session.get(DailyQuestionSubscriber, subscriber_id)
    if subscriber is None:
        return False
    unlink_email_events_for_question_subscribers([subscriber_id])
    db.session.delete(subscriber)
    return True


def delete_question_subscribers_bulk(subscriber_ids: Sequence[int]) -> int:
    """Unlink analytics and bulk-delete Daily Question subscribers. Returns delete count."""
    ids = list(subscriber_ids)
    if not ids:
        return 0
    unlink_email_events_for_question_subscribers(ids)
    return DailyQuestionSubscriber.query.filter(
        DailyQuestionSubscriber.id.in_(ids)
    ).delete(synchronize_session=False)
