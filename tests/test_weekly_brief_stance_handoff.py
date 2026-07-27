"""Weekly brief email includes a week-scoped participation handoff."""

from datetime import date, timedelta
from unittest.mock import patch

from app.models import DailyBrief, DailyBriefSubscriber, DailyQuestion


def _weekly_brief(db, week_end):
    b = DailyBrief(
        date=week_end,
        brief_type='weekly',
        status='published',
        title='Weekly',
        week_start_date=week_end - timedelta(days=6),
        week_end_date=week_end,
    )
    db.session.add(b)
    db.session.flush()
    return b


def _subscriber(db):
    s = DailyBriefSubscriber(email='reader@example.com', status='active', cadence='weekly')
    s.generate_magic_token()
    s.ensure_unsubscribe_token()
    db.session.add(s)
    db.session.flush()
    return s


def _question(db, qdate, number):
    q = DailyQuestion(
        question_date=qdate,
        question_number=number,
        question_text='Should we ship the weekly stance CTA?',
        status='published',
        source_type='discussion',
    )
    db.session.add(q)
    db.session.flush()
    return q


def test_weekly_brief_email_includes_stance_handoff(db, app):
    week_end = date(2026, 7, 26)
    brief = _weekly_brief(db, week_end)
    sub = _subscriber(db)
    _question(db, week_end - timedelta(days=2), 9001)
    db.session.commit()

    from app.brief.email_client import ResendClient

    client = ResendClient()
    with app.app_context():
        with patch.object(client, '_get_sorted_brief_items', return_value=[]):
            html = client._render_email(sub, brief, sorted_items=[])

    assert 'weekly_brief_stance' in html
    assert 'Should we ship the weekly stance CTA?' in html
    assert f'/brief/weekly/{week_end.isoformat()}' in html
    assert '/daily/v/' in html
    assert 'source=weekly_brief_email' in html


# --------------------------------------------------------------------------
# Kicker copy
#
# The stance card is shared with the daily brief, whose header reads
# "Daily Question #N" (web) and "Today's question" (email). Both misread on a
# weekly edition covering 20–26 Jul, so the weekly context supplies its own.
# --------------------------------------------------------------------------

from datetime import date, timedelta


def test_weekly_email_kicker_replaces_todays_question(db, app):
    from app.brief.stance_card import build_weekly_stance_email_handoff
    from app.models import DailyQuestion

    week_end = date(2026, 7, 26)
    week_start = week_end - timedelta(days=6)
    db.session.add(DailyQuestion(
        question_text='Should the weekly kicker read correctly?',
        question_date=week_end - timedelta(days=1),
        question_number=901, status='published',
    ))
    db.session.commit()

    with app.app_context():
        handoff = build_weekly_stance_email_handoff(
            week_start=week_start, week_end=week_end, week_end_date=week_end,
            base_url='https://societyspeaks.io',
        )

    assert handoff is not None
    assert handoff['kicker'] == "This week's question"


def test_weekly_web_card_kicker_replaces_daily_question_number(db, app):
    from app.brief.stance_card import build_weekly_stance_card_context
    from app.models import DailyQuestion

    week_end = date(2026, 7, 26)
    week_start = week_end - timedelta(days=6)
    db.session.add(DailyQuestion(
        question_text='Should the weekly kicker read correctly?',
        question_date=week_end - timedelta(days=1),
        question_number=902, status='published',
    ))
    db.session.commit()

    with app.test_request_context('/brief/weekly/2026-07-26'):
        ctx = build_weekly_stance_card_context(
            week_start=week_start, week_end=week_end,
        )

    assert ctx is not None
    assert ctx['kicker'] == "This week's question"


def test_daily_stance_card_keeps_its_own_kicker(db, app):
    """The daily context must not gain a kicker — its template default stands."""
    from app.brief.stance_card import build_stance_email_handoff
    from app.models import DailyQuestion

    today = date.today()
    db.session.add(DailyQuestion(
        question_text='Daily question copy unchanged?',
        question_date=today, question_number=903, status='published',
    ))
    db.session.commit()

    with app.app_context():
        handoff = build_stance_email_handoff(
            brief_date=today, base_url='https://societyspeaks.io',
        )

    if handoff is not None:
        assert 'kicker' not in handoff
