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
