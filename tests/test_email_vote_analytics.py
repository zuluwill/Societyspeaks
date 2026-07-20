"""Tests for email one-click vote analytics instrumentation."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.daily.vote_analytics import (
    participation_source_for_email_vote,
    track_email_vote_confirm_viewed,
    track_email_vote_confirmed,
)
from app.lib.posthog_utils import request_is_prefetch
from app.models import DailyBriefSubscriber, DailyQuestion


def _seed_question_and_brief_subscriber(number, email):
    q = DailyQuestion(
        question_date=date.today(),
        question_number=number,
        question_text='Prefetch gate?',
        status='published',
        source_type='discussion',
    )
    sub = DailyBriefSubscriber(email=email, status='active')
    db.session.add_all([q, sub])
    db.session.commit()
    return q, sub


def test_participation_source_mapping():
    assert participation_source_for_email_vote('brief_email', 'brief') == 'brief_stance_email'
    assert participation_source_for_email_vote('', 'brief') == 'brief_stance_email'
    assert participation_source_for_email_vote('weekly_digest', 'question') == 'weekly_digest_email'
    assert participation_source_for_email_vote('', 'question') == 'daily_question_email'


def test_track_confirm_viewed_fires_event(app, db):
    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=70,
            question_text='Track confirm view?',
            status='published',
            source_type='discussion',
        )
        sub = DailyBriefSubscriber(email='analytics-brief@example.com', status='active')
        db.session.add_all([q, sub])
        db.session.commit()

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            track_email_vote_confirm_viewed(
                subscriber=sub,
                question=q,
                vote_choice='agree',
                voter_channel='brief',
                source='brief_email',
            )

        mock_ph.capture.assert_called_once()
        assert mock_ph.capture.call_args.kwargs['event'] == 'email_vote_confirm_viewed'
        props = mock_ph.capture.call_args.kwargs['properties']
        assert props['participation_source'] == 'brief_stance_email'
        assert props['voter_channel'] == 'brief'


def test_track_confirmed_fires_both_events(app, db):
    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=71,
            question_text='Track confirmed vote?',
            status='published',
            source_type='discussion',
        )
        sub = DailyBriefSubscriber(email='confirmed-brief@example.com', status='active')
        db.session.add_all([q, sub])
        db.session.commit()

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            track_email_vote_confirmed(
                subscriber=sub,
                question=q,
                vote_choice='disagree',
                voter_channel='brief',
                source='brief_email',
            )

        events = [c.kwargs['event'] for c in mock_ph.capture.call_args_list]
        assert 'email_vote_confirmed' in events
        assert 'daily_question_participated' in events
        confirmed = mock_ph.capture.call_args_list[0].kwargs['properties']
        assert confirmed['confirmation_step'] == 'confirmed'
        assert confirmed['participation_source'] == 'brief_stance_email'


@pytest.mark.parametrize('headers', [
    {'Sec-Purpose': 'prefetch'},
    {'Sec-Purpose': 'prefetch;prerender'},
    {'Sec-Purpose': 'prerender'},
    {'Purpose': 'prefetch'},
    {'X-Purpose': 'prefetch'},
    {'X-Purpose': 'preview'},
    {'X-Moz': 'prefetch'},
])
def test_request_is_prefetch_true_for_prefetch_signals(app, headers):
    with app.test_request_context('/daily/v/tok/agree', headers=headers):
        assert request_is_prefetch() is True


def test_request_is_prefetch_false_for_human_get(app):
    with app.test_request_context('/daily/v/tok/agree', headers={'User-Agent': 'Mozilla/5.0 (iPhone)'}):
        assert request_is_prefetch() is False


def test_request_is_prefetch_false_outside_request_context(app):
    with app.app_context():
        assert request_is_prefetch() is False


def test_confirm_viewed_skipped_on_prefetch(app, db):
    with app.app_context():
        db.create_all()
        q, sub = _seed_question_and_brief_subscriber(72, 'prefetch-gate@example.com')

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            with app.test_request_context(headers={'Purpose': 'prefetch'}):
                track_email_vote_confirm_viewed(
                    subscriber=sub,
                    question=q,
                    vote_choice='agree',
                    voter_channel='brief',
                    source='brief_email',
                )

        mock_ph.capture.assert_not_called()


def test_confirm_viewed_skipped_for_scripted_client(app, db):
    with app.app_context():
        db.create_all()
        q, sub = _seed_question_and_brief_subscriber(73, 'scripted-gate@example.com')

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            with app.test_request_context(headers={'User-Agent': 'python-requests/2.31.0'}):
                track_email_vote_confirm_viewed(
                    subscriber=sub,
                    question=q,
                    vote_choice='agree',
                    voter_channel='brief',
                    source='brief_email',
                )

        mock_ph.capture.assert_not_called()


def test_confirm_viewed_fires_for_human_get(app, db):
    with app.app_context():
        db.create_all()
        q, sub = _seed_question_and_brief_subscriber(74, 'human-gate@example.com')

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            with app.test_request_context(headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)'}):
                track_email_vote_confirm_viewed(
                    subscriber=sub,
                    question=q,
                    vote_choice='agree',
                    voter_channel='brief',
                    source='brief_email',
                )

        mock_ph.capture.assert_called_once()
        assert mock_ph.capture.call_args.kwargs['event'] == 'email_vote_confirm_viewed'


def test_prefetch_get_renders_confirm_but_records_no_event(client, db, app):
    """End-to-end: a prefetch GET still serves the confirm page (human flow
    intact) but emits no confirm_viewed; a real browser GET emits it."""
    q, sub = _seed_question_and_brief_subscriber(75, 'e2e-prefetch@example.com')
    token = sub.generate_vote_token(q.id)

    def _confirm_viewed_events(mock_ph):
        return [c for c in mock_ph.capture.call_args_list
                if c.kwargs.get('event') == 'email_vote_confirm_viewed']

    mock_ph = MagicMock()
    mock_ph.project_api_key = 'phk_test'
    with patch('app.daily.vote_analytics._posthog', mock_ph):
        prefetch = client.get(
            f'/daily/v/{token}/agree?source=brief_email',
            headers={'Purpose': 'prefetch'},
        )
        assert prefetch.status_code == 200          # page still renders for the prefetcher
        assert _confirm_viewed_events(mock_ph) == []

        mock_ph.reset_mock()
        mock_ph.project_api_key = 'phk_test'
        human = client.get(
            f'/daily/v/{token}/agree?source=brief_email',
            headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)'},
        )
        assert human.status_code == 200
        assert len(_confirm_viewed_events(mock_ph)) == 1
