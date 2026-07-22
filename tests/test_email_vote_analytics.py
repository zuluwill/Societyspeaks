"""Tests for email one-click vote analytics instrumentation."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.daily.vote_analytics import (
    participation_source_for_email_vote,
    resolve_daily_participation_distinct_id,
    resolve_email_vote_distinct_id,
    track_email_vote_confirm_viewed,
    track_email_vote_confirmed,
    track_daily_question_participated,
)
from app.lib.posthog_utils import email_subscriber_distinct_id, request_is_prefetch
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


def test_resolve_daily_participation_prefers_subscriber_email(app, db):
    from app.lib.posthog_utils import email_subscriber_distinct_id

    with app.app_context():
        db.create_all()
        sub = DailyBriefSubscriber(email='batch-track@example.com', status='active')
        db.session.add(sub)
        db.session.commit()
        expected = email_subscriber_distinct_id(sub.email)

        with app.test_request_context('/'):
            from flask import session

            session['brief_subscriber_id'] = sub.id
            assert resolve_daily_participation_distinct_id() == expected
            assert resolve_daily_participation_distinct_id(subscriber=sub) == expected


def test_track_daily_question_participated_fires(app, db):
    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=76,
            question_text='Track web vote?',
            status='published',
            source_type='discussion',
        )
        db.session.add(q)
        db.session.commit()

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            with app.test_request_context('/', headers={'User-Agent': 'Mozilla/5.0 (iPhone)'}):
                track_daily_question_participated(
                    question=q,
                    vote='agree',
                    participation_source='daily_web',
                )

        mock_ph.capture.assert_called_once()
        assert mock_ph.capture.call_args.kwargs['event'] == 'daily_question_participated'
        props = mock_ph.capture.call_args.kwargs['properties']
        assert props['participation_source'] == 'daily_web'
        assert props['is_authenticated'] is False


def test_weekly_batch_vote_emits_participation_event(client, db, app):
    from datetime import date
    from unittest.mock import MagicMock, patch

    from app.models import DailyQuestion, DailyQuestionSubscriber

    today = date.today()
    q = DailyQuestion(
        question_date=today,
        question_number=77,
        question_text='Weekly batch tracked?',
        status='published',
        source_type='discussion',
    )
    sub = DailyQuestionSubscriber(email='weekly-batch@example.com', is_active=True)
    db.session.add_all([q, sub])
    db.session.commit()

    mock_ph = MagicMock()
    mock_ph.project_api_key = 'phk_test'

    with client.session_transaction() as sess:
        sess['daily_subscriber_id'] = sub.id

    with patch('app.daily.vote_analytics._posthog', mock_ph):
        response = client.post(
            '/daily/weekly/vote',
            json={'question_id': q.id, 'vote': 'agree'},
            headers={'Content-Type': 'application/json'},
        )

    assert response.status_code == 200
    events = [c.kwargs['event'] for c in mock_ph.capture.call_args_list]
    assert 'daily_question_participated' in events
    participated = [
        c.kwargs for c in mock_ph.capture.call_args_list
        if c.kwargs.get('event') == 'daily_question_participated'
    ][0]
    assert participated['properties']['participation_source'] == 'weekly_batch'
    assert participated['properties']['voted_via_email'] is True


def test_weekly_batch_vote_persists_audit_distinct_id(client, db, app):
    """The stored audit id must equal the distinct_id the event fired under."""
    from app.models import DailyQuestion, DailyQuestionResponse, DailyQuestionSubscriber

    today = date.today()
    q = DailyQuestion(
        question_date=today,
        question_number=78,
        question_text='Audit id persisted on batch vote?',
        status='published',
        source_type='discussion',
    )
    sub = DailyQuestionSubscriber(email='batch-audit@example.com', is_active=True)
    db.session.add_all([q, sub])
    db.session.commit()

    mock_ph = MagicMock()
    mock_ph.project_api_key = 'phk_test'

    with client.session_transaction() as sess:
        sess['daily_subscriber_id'] = sub.id

    with patch('app.daily.vote_analytics._posthog', mock_ph):
        response = client.post(
            '/daily/weekly/vote',
            json={'question_id': q.id, 'vote': 'agree'},
            headers={'Content-Type': 'application/json'},
        )

    assert response.status_code == 200
    row = DailyQuestionResponse.query.filter_by(daily_question_id=q.id).one()
    assert row.posthog_distinct_id  # populated, not NULL
    event_distinct_id = [
        c.kwargs['distinct_id'] for c in mock_ph.capture.call_args_list
        if c.kwargs.get('event') == 'daily_question_participated'
    ][0]
    assert row.posthog_distinct_id == event_distinct_id  # no drift


def test_web_vote_persists_audit_distinct_id(client, db, app):
    """Anonymous web vote also mirrors its analytics id onto the response row."""
    from app.models import DailyQuestion, DailyQuestionResponse

    q = DailyQuestion(
        question_date=date.today(),
        question_number=79,
        question_text='Audit id persisted on web vote?',
        status='published',
        source_type='discussion',
    )
    db.session.add(q)
    db.session.commit()

    mock_ph = MagicMock()
    mock_ph.project_api_key = 'phk_test'

    with patch('app.daily.vote_analytics._posthog', mock_ph):
        response = client.post(
            '/daily/vote',
            data={'vote': 'agree', 'ajax': '1'},
        )

    assert response.status_code == 200
    row = DailyQuestionResponse.query.filter_by(daily_question_id=q.id).one()
    event_calls = [
        c.kwargs['distinct_id'] for c in mock_ph.capture.call_args_list
        if c.kwargs.get('event') == 'daily_question_participated'
    ]
    assert event_calls, 'expected a participation event to fire'
    assert row.posthog_distinct_id  # populated, not NULL
    assert row.posthog_distinct_id == event_calls[0]  # no drift


def test_track_confirmed_does_not_re_alias(app, db):
    """Alias fires once on confirm-viewed GET; confirmed POST must not repeat it."""
    import posthog
    from datetime import date

    from app.models import DailyBriefSubscriber, DailyQuestion

    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=81,
            question_text='No re-alias on confirmed?',
            status='published',
            source_type='discussion',
        )
        sub = DailyBriefSubscriber(email='no-realias@example.com', status='active')
        db.session.add_all([q, sub])
        db.session.commit()

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            with patch(
                'app.daily.vote_analytics.stitch_email_subscriber_posthog_identity',
            ) as stitch_mock:
                with app.test_request_context('/', headers={'User-Agent': 'Mozilla/5.0 (iPhone)'}):
                    track_email_vote_confirmed(
                        subscriber=sub,
                        question=q,
                        vote_choice='agree',
                        voter_channel='brief',
                        source='brief_email',
                    )

        stitch_mock.assert_not_called()


def test_email_vote_audit_id_matches_event(client, db, app):
    """Email vote stores the same distinct_id the confirmed event fires under."""
    from app.lib.posthog_utils import email_subscriber_distinct_id
    from app.models import DailyBriefSubscriber, DailyQuestion, DailyQuestionResponse

    today = date.today()
    q = DailyQuestion(
        question_date=today,
        question_number=82,
        question_text='Audit id on email vote?',
        status='published',
        source_type='discussion',
    )
    sub = DailyBriefSubscriber(email='email-audit@example.com', status='active')
    db.session.add_all([q, sub])
    db.session.commit()
    token = sub.generate_vote_token(q.id)
    expected_id = email_subscriber_distinct_id(sub.email)

    mock_ph = MagicMock()
    mock_ph.project_api_key = 'phk_test'

    with patch('app.daily.vote_analytics._posthog', mock_ph):
        client.get(f'/daily/v/{token}/agree?source=brief_email')
        client.post(
            f'/daily/v/{token}/agree?source=brief_email',
            data={'confidence_level': 'high', 'reason': 'Because it matters.'},
        )

    row = DailyQuestionResponse.query.filter_by(daily_question_id=q.id).one()
    assert row.posthog_distinct_id == expected_id
    assert row.confidence_level == 'high'
    confirmed = [
        c.kwargs['distinct_id'] for c in mock_ph.capture.call_args_list
        if c.kwargs.get('event') == 'email_vote_confirmed'
    ]
    assert confirmed
    assert row.posthog_distinct_id == confirmed[0]


def test_confirm_vote_template_single_confidence_source():
    """Structural guard: chips are the sole confidence source; reason form mirrors."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    confirm = (root / 'app/templates/daily/confirm_vote.html').read_text()
    chips = (root / 'app/templates/daily/_confidence_chips.html').read_text()

    assert 'data-confidence-mirror' in confirm
    assert confirm.count('name="confidence_level"') == 1  # mirror only in reason form
    assert 'data-confidence-input' in chips
    assert 'data-confidence-mirror' in chips
    assert 'reasonSelect' not in chips


def test_subscriber_distinct_id_matches_scoreboard_hash():
    """§10c SQL hash must match app/lib/posthog_utils.email_subscriber_distinct_id."""
    import hashlib

    samples = [
        'Person@Example.com',
        '  person@example.com ',
        'tab@example.com\t',
        'newline@example.com\n',
    ]
    for email in samples:
        normalized = str(email).strip().lower()
        expected = 'subscriber:' + hashlib.sha256(normalized.encode()).hexdigest()[:32]
        assert email_subscriber_distinct_id(email) == expected


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
    from app.lib.posthog_utils import email_subscriber_distinct_id

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
        expected_id = email_subscriber_distinct_id(sub.email)

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
        confirmed = mock_ph.capture.call_args_list[0].kwargs
        assert confirmed['distinct_id'] == expected_id
        assert confirmed['properties']['confirmation_step'] == 'confirmed'
        assert confirmed['properties']['participation_source'] == 'brief_stance_email'
        assert confirmed['properties']['question_text'] == 'Track confirmed vote?'
        mock_ph.identify.assert_called()
        assert mock_ph.identify.call_args.kwargs['properties']['brief_subscriber_id'] == sub.id
        participated = mock_ph.capture.call_args_list[1].kwargs
        assert participated['distinct_id'] == expected_id


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


def test_question_analytics_properties_includes_text_and_metadata(app, db):
    from app.daily.vote_analytics import question_analytics_properties
    from app.models import DailyQuestion

    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=99,
            question_text='Should cities ban cars from centres?',
            status='published',
            source_type='discussion',
            topic_category='transport',
            contestability_score=0.72,
            editorial_contest_rating=4,
        )
        db.session.add(q)
        db.session.commit()
        props = question_analytics_properties(q)
        assert props['question_text'] == q.question_text
        assert props['topic_category'] == 'transport'
        assert props['contestability_score'] == 0.72
        assert props['editorial_contest_rating'] == 4


def test_track_email_vote_confirmed_uses_insert_id_without_stamping_mirror(app, db):
    """Live POST enqueues best-effort; reconciler owns mirrored_at."""
    from app.models import DailyQuestionResponse

    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=100,
            question_text='Mirror stamp?',
            status='published',
            source_type='discussion',
        )
        sub = DailyBriefSubscriber(email='mirror-stamp@example.com', status='active')
        db.session.add_all([q, sub])
        db.session.commit()

        response = DailyQuestionResponse(
            daily_question_id=q.id,
            session_fingerprint='fp-mirror',
            vote=1,
            voted_via_email=True,
            posthog_distinct_id=resolve_email_vote_distinct_id(sub),
        )
        db.session.add(response)
        db.session.commit()

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            with patch('app.lib.posthog_utils._drain_posthog_client') as drain:
                track_email_vote_confirmed(
                    subscriber=sub,
                    question=q,
                    vote_choice='agree',
                    voter_channel='brief',
                    source='brief_email',
                    response_id=response.id,
                )
                drain.assert_not_called()

        confirmed = mock_ph.capture.call_args_list[0].kwargs
        assert confirmed['properties']['$insert_id'] == f'dqr:{response.id}:email_vote_confirmed'
        db.session.refresh(response)
        assert response.posthog_confirmed_mirrored_at is None


def test_reconcile_unmirrored_email_votes_stamps_mirror(app, db):
    from app.daily.vote_analytics import reconcile_unmirrored_email_votes_to_posthog
    from app.models import DailyQuestionResponse

    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=102,
            question_text='Reconcile me?',
            status='published',
            source_type='discussion',
        )
        sub = DailyBriefSubscriber(email='reconcile@example.com', status='active')
        db.session.add_all([q, sub])
        db.session.commit()

        response = DailyQuestionResponse(
            daily_question_id=q.id,
            session_fingerprint='fp-reconcile',
            vote=1,
            voted_via_email=True,
            posthog_distinct_id=resolve_email_vote_distinct_id(sub),
        )
        db.session.add(response)
        db.session.commit()

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            with patch('app.lib.posthog_utils._drain_posthog_client'):
                with patch('app.lib.posthog_utils.shutdown_server_posthog'):
                    stats = reconcile_unmirrored_email_votes_to_posthog(limit=10)

        assert stats['mirrored'] == 1
        db.session.refresh(response)
        assert response.posthog_confirmed_mirrored_at is not None


def test_mirror_email_vote_confirmed_to_posthog_is_idempotent(app, db):
    from app.daily.vote_analytics import mirror_email_vote_confirmed_to_posthog
    from app.models import DailyQuestionResponse

    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=101,
            question_text='Backfill once?',
            status='published',
            source_type='discussion',
        )
        sub = DailyBriefSubscriber(email='backfill@example.com', status='active')
        db.session.add_all([q, sub])
        db.session.commit()

        response = DailyQuestionResponse(
            daily_question_id=q.id,
            session_fingerprint='fp-backfill',
            vote=-1,
            voted_via_email=True,
            posthog_distinct_id=resolve_email_vote_distinct_id(sub),
        )
        db.session.add(response)
        db.session.commit()

        mock_ph = MagicMock()
        mock_ph.project_api_key = 'phk_test'

        with patch('app.daily.vote_analytics._posthog', mock_ph):
            with patch('app.lib.posthog_utils._drain_posthog_client'):
                assert mirror_email_vote_confirmed_to_posthog(response, subscriber=sub) is True
                assert mirror_email_vote_confirmed_to_posthog(response, subscriber=sub) is False

        assert mock_ph.capture.call_count == 1
