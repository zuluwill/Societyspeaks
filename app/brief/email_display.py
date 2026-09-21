"""Receive-day labels for Daily Brief emails.

Morning sends (and UK evening sends before the 18:00 UTC publish) deliver
yesterday's edition. ``brief.date`` stays the edition date so permalinks,
stance-card links, magic links, and the web archive keep working. Email
copy uses the subscriber's local calendar day so a Wednesday inbox does
not say Tuesday.
"""

from datetime import date, datetime
from typing import Optional

import pytz

from app.lib.time import utcnow_naive


def subscriber_local_date(subscriber, now: Optional[datetime] = None) -> date:
    """Subscriber's local calendar date at ``now`` (naive UTC, matching send guards)."""
    tz = subscriber.resolve_timezone() if hasattr(subscriber, 'resolve_timezone') else pytz.utc
    ref = now or utcnow_naive()
    return ref.replace(tzinfo=pytz.utc).astimezone(tz).date()


def brief_email_display_date(brief, subscriber=None, now: Optional[datetime] = None):
    """Date shown in the email header/subject — the day the reader receives it.

    Weekly editions keep their week-end date. Daily editions use the
    subscriber's local day. Without a subscriber, fall back to the edition date.
    """
    edition = getattr(brief, 'date', None)
    if getattr(brief, 'brief_type', 'daily') == 'weekly':
        return edition
    if subscriber is None or edition is None:
        return edition
    return subscriber_local_date(subscriber, now=now)


def brief_email_display_title(brief, display_date: Optional[date]) -> str:
    """Rewrite the leading weekday/date on a daily title to ``display_date``.

    Stored titles stay edition-dated (web, OG, archive). Only the emailed
    subject/header is remapped. Unrecognised title shapes are left alone.
    """
    title = getattr(brief, 'title', None) or 'Daily Brief'
    edition = getattr(brief, 'date', None)
    if (
        not edition
        or not display_date
        or edition == display_date
        or getattr(brief, 'brief_type', 'daily') == 'weekly'
    ):
        return title

    old_abs = f"{edition.strftime('%A')} {edition.day} {edition.strftime('%b')}"
    new_abs = f"{display_date.strftime('%A')} {display_date.day} {display_date.strftime('%b')}"
    if title.startswith(old_abs):
        return new_abs + title[len(old_abs):]

    old_poss = f"{edition.strftime('%A')}'s Brief"
    new_poss = f"{display_date.strftime('%A')}'s Brief"
    if title.startswith(old_poss):
        return new_poss + title[len(old_poss):]

    return title
