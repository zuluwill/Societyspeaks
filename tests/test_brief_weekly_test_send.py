"""Regression: single-brief sends must resolve the edition the caller asked for.

A weekly brief shares its ``date`` with that day's daily edition (the weekly is
generated on Saturday, when a Saturday daily also exists). ``send_brief_to_subscriber``
used to resolve by date alone with the model default ``brief_type='daily'``, so
test-sending a weekly brief silently delivered the daily one — the reason the
weekly email had never actually been seen.
"""

from datetime import date
from unittest.mock import patch

from app.models import DailyBrief, DailyBriefSubscriber


def _brief(db, d, *, brief_type, status='published'):
    b = DailyBrief(
        date=d, brief_type=brief_type, status=status,
        title=f"{brief_type} {d}",
    )
    db.session.add(b)
    db.session.flush()
    return b


def _subscriber(db, email='admin@societyspeaks.io'):
    s = DailyBriefSubscriber(
        email=email, status='active', timezone='UTC', preferred_send_hour=18,
    )
    s.generate_magic_token()
    s.ensure_unsubscribe_token()
    db.session.add(s)
    db.session.commit()
    return s


def _sent_brief(mock_send):
    """The DailyBrief passed to ResendClient.send_brief."""
    assert mock_send.called, "send_brief was never called"
    return mock_send.call_args[0][1]


# --------------------------------------------------------------------------
# The bug: same date, two editions
# --------------------------------------------------------------------------

def test_weekly_send_delivers_weekly_not_daily_for_same_date(db):
    """Both editions exist for one date — asking for weekly must get weekly."""
    d = date(2026, 7, 26)
    _brief(db, d, brief_type='daily')
    weekly = _brief(db, d, brief_type='weekly')
    _subscriber(db)
    db.session.commit()

    from app.brief.email_client import send_brief_to_subscriber

    with patch('app.brief.email_client.ResendClient.send_brief', return_value=True) as m:
        assert send_brief_to_subscriber(
            'admin@societyspeaks.io', d.isoformat(), 'weekly'
        ) is True

    assert _sent_brief(m).id == weekly.id
    assert _sent_brief(m).brief_type == 'weekly'


def test_daily_send_is_unaffected_by_a_weekly_on_the_same_date(db):
    d = date(2026, 7, 26)
    daily = _brief(db, d, brief_type='daily')
    _brief(db, d, brief_type='weekly')
    _subscriber(db)
    db.session.commit()

    from app.brief.email_client import send_brief_to_subscriber

    with patch('app.brief.email_client.ResendClient.send_brief', return_value=True) as m:
        assert send_brief_to_subscriber('admin@societyspeaks.io', d.isoformat()) is True

    assert _sent_brief(m).id == daily.id


def test_default_brief_type_stays_daily_for_existing_callers(db):
    """Callers that omit brief_type keep the previous behaviour."""
    d = date(2026, 7, 26)
    daily = _brief(db, d, brief_type='daily')
    _subscriber(db)
    db.session.commit()

    from app.brief.email_client import send_brief_to_subscriber

    with patch('app.brief.email_client.ResendClient.send_brief', return_value=True) as m:
        send_brief_to_subscriber('admin@societyspeaks.io', d.isoformat())

    assert _sent_brief(m).brief_type == 'daily'


# --------------------------------------------------------------------------
# Latest-edition path (no explicit date)
# --------------------------------------------------------------------------

def test_latest_weekly_is_type_scoped(db):
    """A newer daily must not shadow the latest weekly."""
    weekly = _brief(db, date(2026, 7, 19), brief_type='weekly')
    _brief(db, date(2026, 7, 26), brief_type='daily')
    _subscriber(db)
    db.session.commit()

    from app.brief.email_client import send_brief_to_subscriber

    with patch('app.brief.email_client.ResendClient.send_brief', return_value=True) as m:
        send_brief_to_subscriber('admin@societyspeaks.io', None, 'weekly')

    assert _sent_brief(m).id == weekly.id


# --------------------------------------------------------------------------
# allow_unpublished — testing a draft is the point of a test send
# --------------------------------------------------------------------------

def test_ready_edition_is_not_sent_without_allow_unpublished(db):
    d = date(2026, 7, 26)
    _brief(db, d, brief_type='weekly', status='ready')
    _subscriber(db)
    db.session.commit()

    from app.brief.email_client import send_brief_to_subscriber

    with patch('app.brief.email_client.ResendClient.send_brief', return_value=True) as m:
        assert send_brief_to_subscriber(
            'admin@societyspeaks.io', d.isoformat(), 'weekly'
        ) is False
    assert not m.called


def test_ready_edition_is_sent_with_allow_unpublished(db):
    d = date(2026, 7, 26)
    ready = _brief(db, d, brief_type='weekly', status='ready')
    _subscriber(db)
    db.session.commit()

    from app.brief.email_client import send_brief_to_subscriber

    with patch('app.brief.email_client.ResendClient.send_brief', return_value=True) as m:
        assert send_brief_to_subscriber(
            'admin@societyspeaks.io', d.isoformat(), 'weekly', allow_unpublished=True
        ) is True

    assert _sent_brief(m).id == ready.id


def test_allow_unpublished_finds_latest_ready_when_nothing_published(db):
    ready = _brief(db, date(2026, 7, 26), brief_type='weekly', status='ready')
    _subscriber(db)
    db.session.commit()

    from app.brief.email_client import send_brief_to_subscriber

    with patch('app.brief.email_client.ResendClient.send_brief', return_value=True) as m:
        send_brief_to_subscriber(
            'admin@societyspeaks.io', None, 'weekly', allow_unpublished=True
        )

    assert _sent_brief(m).id == ready.id


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------

def test_invalid_brief_type_is_rejected(db):
    _subscriber(db)
    db.session.commit()

    from app.brief.email_client import send_brief_to_subscriber

    with patch('app.brief.email_client.ResendClient.send_brief', return_value=True) as m:
        assert send_brief_to_subscriber(
            'admin@societyspeaks.io', None, 'fortnightly'
        ) is False
    assert not m.called


def test_missing_weekly_does_not_fall_back_to_daily(db):
    """No weekly for the date → fail, never silently substitute the daily."""
    d = date(2026, 7, 26)
    _brief(db, d, brief_type='daily')
    _subscriber(db)
    db.session.commit()

    from app.brief.email_client import send_brief_to_subscriber

    with patch('app.brief.email_client.ResendClient.send_brief', return_value=True) as m:
        assert send_brief_to_subscriber(
            'admin@societyspeaks.io', d.isoformat(), 'weekly'
        ) is False
    assert not m.called
