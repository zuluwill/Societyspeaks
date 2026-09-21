"""Receive-day labels on Daily Brief emails.

Morning (and pre-publish evening) sends deliver yesterday's edition. The
stored date/title and every permalink stay on that edition; only the emailed
weekday/subject should match the day the subscriber gets the mail.
"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.brief.email_display import (
    brief_email_display_date,
    brief_email_display_title,
    subscriber_local_date,
)
from app.brief.email_client import ResendClient
from app.models import DailyBrief, DailyBriefSubscriber, db


TUESDAY = date(2026, 7, 14)
WEDNESDAY = date(2026, 7, 15)


def _bare_client() -> ResendClient:
    client = ResendClient.__new__(ResendClient)
    client._disabled = True
    client.api_key = 'test'
    client.from_email = 'Brief <brief@test.io>'
    client._from_email_addr = 'brief@test.io'
    client.reply_to = 'reply@test.io'
    client.rate_limiter = MagicMock()
    client.last_send_error = None
    return client


def _brief(db, d, *, title=None, brief_type='daily'):
    b = DailyBrief(
        date=d,
        brief_type=brief_type,
        status='published',
        title=title or f"{d.strftime('%A')} {d.day} {d.strftime('%b')} Brief: Climate, Tech",
    )
    db.session.add(b)
    db.session.flush()
    return b


def _sub(db, *, tz='Europe/London', email='reader@t.test'):
    s = DailyBriefSubscriber(
        email=email,
        status='active',
        timezone=tz,
        magic_token='magic-display',
        unsubscribe_token='unsub-display',
    )
    db.session.add(s)
    db.session.flush()
    return s


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def test_local_date_uses_subscriber_timezone():
    sub = SimpleNamespace(resolve_timezone=lambda: __import__('pytz').timezone('America/New_York'))
    # 04:00 UTC Wednesday = 00:00 EDT Wednesday
    assert subscriber_local_date(sub, now=datetime(2026, 7, 15, 4, 0)) == WEDNESDAY
    # 03:59 UTC Wednesday = 23:59 EDT Tuesday
    assert subscriber_local_date(sub, now=datetime(2026, 7, 15, 3, 59)) == TUESDAY


def test_display_date_is_receive_day_for_yesterdays_edition():
    brief = SimpleNamespace(date=TUESDAY, brief_type='daily')
    sub = SimpleNamespace(
        resolve_timezone=lambda: __import__('pytz').timezone('Europe/London'),
    )
    # Wednesday 08:00 BST — typical morning send of Tuesday's edition
    shown = brief_email_display_date(brief, sub, now=datetime(2026, 7, 15, 7, 0))
    assert shown == WEDNESDAY


def test_display_date_stays_edition_day_on_same_local_day():
    brief = SimpleNamespace(date=TUESDAY, brief_type='daily')
    sub = SimpleNamespace(
        resolve_timezone=lambda: __import__('pytz').timezone('Europe/London'),
    )
    # Tuesday 20:00 BST — evening send after publish
    shown = brief_email_display_date(brief, sub, now=datetime(2026, 7, 14, 19, 0))
    assert shown == TUESDAY


def test_weekly_display_date_stays_edition_date():
    brief = SimpleNamespace(date=TUESDAY, brief_type='weekly')
    sub = SimpleNamespace(
        resolve_timezone=lambda: __import__('pytz').timezone('Europe/London'),
    )
    shown = brief_email_display_date(brief, sub, now=datetime(2026, 7, 15, 7, 0))
    assert shown == TUESDAY


def test_title_rewrites_absolute_day_label():
    brief = SimpleNamespace(
        date=TUESDAY,
        brief_type='daily',
        title='Tuesday 14 Jul Brief: Climate, Tech',
    )
    assert (
        brief_email_display_title(brief, WEDNESDAY)
        == 'Wednesday 15 Jul Brief: Climate, Tech'
    )


def test_title_rewrites_possessive_day_label():
    brief = SimpleNamespace(
        date=TUESDAY,
        brief_type='daily',
        title="Tuesday's Brief: Climate, Tech",
    )
    assert brief_email_display_title(brief, WEDNESDAY) == "Wednesday's Brief: Climate, Tech"


def test_title_leaves_unrecognised_shape_alone():
    brief = SimpleNamespace(
        date=TUESDAY,
        brief_type='daily',
        title='The stories that matter today',
    )
    assert brief_email_display_title(brief, WEDNESDAY) == 'The stories that matter today'


def test_title_unchanged_when_receive_day_matches_edition():
    brief = SimpleNamespace(
        date=TUESDAY,
        brief_type='daily',
        title='Tuesday 14 Jul Brief: Climate, Tech',
    )
    assert brief_email_display_title(brief, TUESDAY) == brief.title


# --------------------------------------------------------------------------
# rendered email — labels move, links do not
# --------------------------------------------------------------------------

def test_rendered_email_says_receive_day_and_keeps_edition_links(app, db):
    with app.app_context():
        brief = _brief(db, TUESDAY)
        sub = _sub(db)
        db.session.commit()

        client = _bare_client()
        with patch('app.brief.email_display.utcnow_naive', return_value=datetime(2026, 7, 15, 7, 0)):
            html = client._render_email(sub, brief, sorted_items=[])
            text = client._render_brief_text(
                brief=brief,
                magic_link_url=f'https://societyspeaks.io/brief/m/{sub.magic_token}?d={TUESDAY.isoformat()}',
                unsubscribe_url='https://societyspeaks.io/u',
                preferences_url='https://societyspeaks.io/p',
                sorted_items=[],
                web_brief_url=f'https://societyspeaks.io/brief/{TUESDAY.isoformat()}',
                display_date=WEDNESDAY,
                display_title=brief_email_display_title(brief, WEDNESDAY),
            )

        assert 'Wednesday, 15 July 2026' in html
        assert 'Tuesday, 14 July 2026' not in html
        assert 'Wednesday 15 Jul Brief: Climate, Tech' in html
        assert f'/brief/m/{sub.magic_token}?d={TUESDAY.isoformat()}' in html
        assert f'/brief/{TUESDAY.isoformat()}' in html
        assert f'/brief/{WEDNESDAY.isoformat()}' not in html
        assert '/brief/today' not in html

        assert 'Wednesday 15 Jul Brief: Climate, Tech' in text
        assert 'Date: Wednesday, July 15, 2026' in text
        assert f'View on web: https://societyspeaks.io/brief/{TUESDAY.isoformat()}' in text


def test_send_brief_subject_uses_receive_day(app, db):
    with app.app_context():
        brief = _brief(db, TUESDAY)
        sub = _sub(db)
        db.session.commit()

        client = _bare_client()
        captured = {}

        def _capture(email_data, idempotency_key=None):
            captured['email_data'] = email_data
            return True

        with patch('app.brief.email_display.utcnow_naive', return_value=datetime(2026, 7, 15, 7, 0)), \
             patch.object(client, '_send_with_retry', side_effect=_capture), \
             patch.object(client, '_from_for_brief', return_value=client.from_email):
            assert client.send_brief(sub, brief) is True

        assert captured['email_data']['subject'] == 'Wednesday 15 Jul Brief: Climate, Tech'
        html = captured['email_data']['html']
        text = captured['email_data']['text']
        assert 'Wednesday, 15 July 2026' in html
        # Click-tracking wrap hides raw permalinks in HTML; the text part
        # and the unwrapped renderer keep the edition date.
        assert f'/brief/{TUESDAY.isoformat()}' in text
        assert f'/brief/{WEDNESDAY.isoformat()}' not in html
        assert f'/brief/{WEDNESDAY.isoformat()}' not in text


def test_fallback_html_uses_receive_day_but_keeps_edition_permalink(app, db):
    with app.app_context():
        brief = _brief(db, TUESDAY)
        db.session.commit()
        client = _bare_client()
        html = client._fallback_html(
            brief,
            magic_link_url=f'https://societyspeaks.io/brief/m/x?d={TUESDAY.isoformat()}',
            unsubscribe_url='https://societyspeaks.io/u',
            display_date=WEDNESDAY,
            display_title='Wednesday 15 Jul Brief: Climate, Tech',
        )
        assert 'Wednesday, July 15, 2026' in html
        assert 'Wednesday 15 Jul Brief: Climate, Tech' in html
        assert f'/brief/{TUESDAY.isoformat()}' in html
        assert f'/brief/{WEDNESDAY.isoformat()}' not in html
