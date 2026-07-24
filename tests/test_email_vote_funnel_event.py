"""Tests for server-side email vote funnel event persistence."""

from datetime import date
from unittest.mock import MagicMock, patch

from app import db
from app.models import DailyBriefSubscriber, DailyQuestion, DailyQuestionResponse, EmailVoteFunnelEvent


def _seed():
    q = DailyQuestion(
        question_date=date.today(),
        question_number=901,
        question_text='Device funnel test?',
        status='published',
        source_type='discussion',
    )
    sub = DailyBriefSubscriber(email='funnel-device@example.com', status='active')
    db.session.add_all([q, sub])
    db.session.commit()
    return q, sub


def test_confirm_view_persists_funnel_event(client, db, app):
    q, sub = _seed()
    token = sub.generate_vote_token(q.id)
    ua = (
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
    )

    with patch('app.daily.vote_analytics._posthog', MagicMock(project_api_key='phk_test')):
        resp = client.get(
            f'/daily/v/{token}/agree?source=brief_email',
            headers={'User-Agent': ua},
        )
    assert resp.status_code == 200

    row = EmailVoteFunnelEvent.query.filter_by(
        daily_question_id=q.id,
        step=EmailVoteFunnelEvent.STEP_CONFIRM_VIEW,
    ).one()
    assert row.device_class == 'mobile'
    assert row.brief_subscriber_id == sub.id
    assert row.participation_source == 'brief_stance_email'


def test_vote_confirmed_persists_funnel_event(client, db, app):
    q, sub = _seed()
    token = sub.generate_vote_token(q.id)
    ua = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )

    with patch('app.daily.vote_analytics._posthog', MagicMock(project_api_key='phk_test')):
        client.get(f'/daily/v/{token}/agree?source=brief_email', headers={'User-Agent': ua})
        vote = client.post(
            f'/daily/v/{token}/agree?source=brief_email',
            data={},
            headers={'User-Agent': ua},
            follow_redirects=False,
        )
    assert vote.status_code == 302

    response = DailyQuestionResponse.query.filter_by(daily_question_id=q.id).one()
    row = EmailVoteFunnelEvent.query.filter_by(
        daily_question_id=q.id,
        step=EmailVoteFunnelEvent.STEP_VOTE_CONFIRMED,
    ).one()
    assert row.device_class == 'desktop'
    assert row.response_id == response.id


def test_bot_user_agent_not_persisted(client, db, app):
    q, sub = _seed()
    token = sub.generate_vote_token(q.id)

    with patch('app.daily.vote_analytics._posthog', MagicMock(project_api_key='phk_test')):
        resp = client.get(
            f'/daily/v/{token}/agree?source=brief_email',
            headers={'User-Agent': 'python-requests/2.32.4'},
        )
    assert resp.status_code == 200
    assert EmailVoteFunnelEvent.query.count() == 0
