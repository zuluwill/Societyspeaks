"""Tests for E1 stance card context (brief end-cap)."""

from datetime import date, timedelta

from app import db
from app.models import DailyQuestion
from app.brief.stance_card import build_stance_card_context, build_stance_email_handoff


def test_stance_context_none_without_published_question(db):
    from datetime import date
    DailyQuestion.query.filter_by(
        question_date=date.today(),
        status='published',
    ).delete()
    db.session.commit()
    assert build_stance_card_context(brief_date=date.today()) is None


def test_stance_context_none_for_historical_brief(app):
    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=1,
            question_text='Should councils fund resilience programmes?',
            status='published',
            source_type='discussion',
        )
        db.session.add(q)
        db.session.commit()
        assert build_stance_card_context(brief_date=date(2020, 1, 1)) is None


def test_stance_context_brief_sourced_subline(app):
    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=188,
            question_text='Should governments act on this underreported crisis?',
            status='published',
            source_type='brief',
            source_brief_item_id=42,
            coverage_frame_json={
                'brief_date': '2026-07-15',
                'dominant_frame': 'right',
                'is_underreported': False,
                'coverage_imbalance': 0.8,
            },
        )
        db.session.add(q)
        db.session.commit()

        ctx = build_stance_card_context(brief_date=date.today())
        assert ctx is not None
        assert ctx['is_brief_sourced'] is True
        assert 'press leaned' in ctx['subline'].lower()
        assert ctx['sourcing_brief_url'] == '/brief/2026-07-15'


def test_stance_context_underreported_subline(app):
    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=2,
            question_text='Should media cover this more?',
            status='published',
            source_type='brief',
            source_brief_item_id=7,
            coverage_frame_json={
                'brief_date': '2026-07-14',
                'is_underreported': True,
            },
        )
        db.session.add(q)
        db.session.commit()

        ctx = build_stance_card_context(brief_date=date.today())
        assert 'barely covered' in ctx['subline'].lower()


def test_stance_context_generic_when_not_brief_sourced(app):
    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=3,
            question_text='Should taxes rise?',
            status='published',
            source_type='discussion',
        )
        db.session.add(q)
        db.session.commit()

        ctx = build_stance_card_context(brief_date=date.today())
        assert ctx['is_brief_sourced'] is False
        assert ctx['subline'] == 'Where do you stand?'


def test_stance_email_handoff_url(app):
    with app.app_context():
        db.create_all()
        today = date.today()
        q = DailyQuestion(
            question_date=today,
            question_number=4,
            question_text='Test question?',
            status='published',
            source_type='discussion',
        )
        db.session.add(q)
        db.session.commit()

        handoff = build_stance_email_handoff(
            brief_date=today,
            base_url='https://societyspeaks.io',
        )
        assert handoff is not None
        assert handoff['stance_url'] == (
            f'https://societyspeaks.io/brief/{today.isoformat()}'
            f'?src=brief_stance#stance'
        )
        assert handoff['tradeoffs_url'] == (
            'https://societyspeaks.io/play/daily?src=brief_tradeoffs'
        )
        assert handoff['subline'] == 'Where do you stand?'
        assert 'vote_agree_url' not in handoff


def test_morning_wave_brief_gets_todays_wired_question(app):
    """
    Morning local-hour sends deliver yesterday's brief edition.

    Brief D wires the question for D+1; on day D+1 that companion is published
    and must appear in email/web stance (regression: brief_date == today gate
    hid E1 from morning cohorts entirely).
    """
    with app.app_context():
        db.create_all()
        today = date.today()
        yesterday = today - timedelta(days=1)
        DailyQuestion.query.filter(
            DailyQuestion.question_date.in_([today, yesterday])
        ).delete(synchronize_session=False)
        db.session.add(DailyQuestion(
            question_date=today,
            question_number=17,
            question_text='Morning-wave companion stance?',
            status='published',
            source_type='brief',
            source_brief_item_id=1500,
            coverage_frame_json={
                'brief_date': yesterday.isoformat(),
                'dominant_frame': 'center',
                'is_underreported': False,
            },
        ))
        db.session.commit()

        ctx = build_stance_card_context(brief_date=yesterday)
        assert ctx is not None
        assert ctx['question'].question_number == 17
        assert ctx['is_brief_sourced'] is True

        handoff = build_stance_email_handoff(
            brief_date=yesterday,
            base_url='https://societyspeaks.io',
        )
        assert handoff is not None
        assert handoff['question'].question_number == 17
        assert (
            handoff['stance_url']
            == f'https://societyspeaks.io/brief/{yesterday.isoformat()}?src=brief_stance#stance'
        )
        assert handoff['tradeoffs_url'].endswith('?src=brief_tradeoffs')
        assert 'press leaned' in handoff['subline'].lower()


def test_morning_wave_rejects_miswired_frame(app):
    """Companion for yesterday's brief must point at that brief, not another."""
    with app.app_context():
        db.create_all()
        today = date.today()
        yesterday = today - timedelta(days=1)
        DailyQuestion.query.filter(
            DailyQuestion.question_date.in_([today, yesterday])
        ).delete(synchronize_session=False)
        db.session.add(DailyQuestion(
            question_date=today,
            question_number=18,
            question_text='Miswired frame should not attach?',
            status='published',
            source_type='brief',
            source_brief_item_id=99,
            coverage_frame_json={
                'brief_date': (yesterday - timedelta(days=1)).isoformat(),
            },
        ))
        db.session.commit()

        assert build_stance_card_context(brief_date=yesterday) is None
        assert build_stance_email_handoff(
            brief_date=yesterday,
            base_url='https://societyspeaks.io',
        ) is None


def test_stance_email_handoff_does_not_touch_vote_identity(app, monkeypatch):
    """
    Scheduler email renders must not call _has_user_voted / current_user.

    Regression for production Sentry PYTHON-FLASK-H7 / H6: brief sends failed
    with AttributeError: 'NoneType' object has no attribute 'is_authenticated'.
    """
    def _boom(*_args, **_kwargs):
        raise AssertionError('_has_user_voted must not run during email handoff')

    monkeypatch.setattr('app.brief.stance_card._has_user_voted', _boom)

    with app.app_context():
        db.create_all()
        today = date.today()
        db.session.add(DailyQuestion(
            question_date=today,
            question_number=5,
            question_text='Scheduler-safe stance handoff?',
            status='published',
            source_type='discussion',
        ))
        db.session.commit()

        handoff = build_stance_email_handoff(
            brief_date=today,
            base_url='https://societyspeaks.io',
        )
        assert handoff is not None
        assert handoff['question'].question_number == 5
        assert handoff['stance_url'].endswith('#stance')


def test_has_user_voted_returns_false_without_request_context(app, monkeypatch):
    from app.brief.stance_card import _has_user_voted

    monkeypatch.setattr('app.brief.stance_card.has_request_context', lambda: False)

    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=6,
            question_text='Vote helper without request?',
            status='published',
            source_type='discussion',
        )
        db.session.add(q)
        db.session.commit()
        assert _has_user_voted(q) is False


def test_stance_email_handoff_includes_one_click_urls(app):
    from app.models import DailyBriefSubscriber

    with app.app_context():
        db.create_all()
        today = date.today()
        q = DailyQuestion(
            question_date=today,
            question_number=8,
            question_text='One-click from the brief?',
            status='published',
            source_type='discussion',
        )
        sub = DailyBriefSubscriber(email='brief-voter@example.com', status='active')
        db.session.add_all([q, sub])
        db.session.commit()

        handoff = build_stance_email_handoff(
            brief_date=today,
            base_url='https://societyspeaks.io',
            subscriber=sub,
        )
        assert handoff is not None
        assert handoff['vote_agree_url'].startswith(
            'https://societyspeaks.io/daily/v/'
        )
        assert handoff['vote_agree_url'].endswith('?source=brief_email')
        assert '/agree' in handoff['vote_agree_url']
        assert '/disagree' in handoff['vote_disagree_url']
        assert '/unsure' in handoff['vote_unsure_url']


def test_stance_email_handoff_first_timer_hint(app):
    from app.models import DailyBriefSubscriber

    with app.app_context():
        db.create_all()
        today = date.today()
        q = DailyQuestion(
            question_date=today,
            question_number=9,
            question_text='First brief stance?',
            status='published',
            source_type='discussion',
        )
        first_timer = DailyBriefSubscriber(
            email='first@example.com',
            status='active',
            total_briefs_received=0,
        )
        veteran = DailyBriefSubscriber(
            email='vet@example.com',
            status='active',
            total_briefs_received=3,
        )
        db.session.add_all([q, first_timer, veteran])
        db.session.commit()

        first = build_stance_email_handoff(
            brief_date=today,
            base_url='https://societyspeaks.io',
            subscriber=first_timer,
        )
        repeat = build_stance_email_handoff(
            brief_date=today,
            base_url='https://societyspeaks.io',
            subscriber=veteran,
        )
        assert first['show_first_timer_hint'] is True
        assert repeat['show_first_timer_hint'] is False


def test_daily_brief_email_teaser_above_fold(app):
    """Gmail clips long briefs — stance/tradeoffs must be announced before stories."""
    from types import SimpleNamespace

    from flask import render_template

    from app.brief.sections import SECTIONS, TOPIC_DISPLAY_LABELS, TOPIC_DISPLAY_COLORS

    with app.app_context():
        yesterday = date.today() - timedelta(days=1)
        # Empty story list: still must show the teaser (independent of TOC).
        brief = SimpleNamespace(
            title='Test Brief',
            date=yesterday,
            brief_type='daily',
            reading_time=7,
            intro_text='Intro',
            items=[],
            is_sectioned=False,
            lead_item=None,
        )
        handoff = {
            'question': SimpleNamespace(
                question_text='Should the teaser appear above the fold?',
                question_number=1,
            ),
            'subline': 'Where do you stand?',
            'show_early_signal': False,
            'vote_pcts': None,
            'show_first_timer_hint': True,
            'stance_url': (
                f'https://societyspeaks.io/brief/{yesterday.isoformat()}'
                f'?src=brief_stance#stance'
            ),
            'tradeoffs_url': 'https://societyspeaks.io/play/daily?src=brief_tradeoffs',
            'vote_agree_url': 'https://societyspeaks.io/daily/v/tok/agree?source=brief_email',
            'vote_disagree_url': 'https://societyspeaks.io/daily/v/tok/disagree?source=brief_email',
            'vote_unsure_url': 'https://societyspeaks.io/daily/v/tok/unsure?source=brief_email',
        }
        html = render_template(
            'emails/daily_brief.html',
            brief=brief,
            sorted_items=[],
            subscriber=SimpleNamespace(email='t@example.com', id=1),
            magic_link_url='https://societyspeaks.io/brief/m/x',
            unsubscribe_url='https://societyspeaks.io/u',
            preferences_url='https://societyspeaks.io/p',
            base_url='https://societyspeaks.io',
            personal_briefs_cta_url='https://societyspeaks.io/start',
            SECTIONS=SECTIONS,
            TOPIC_DISPLAY_LABELS=TOPIC_DISPLAY_LABELS,
            TOPIC_DISPLAY_COLORS=TOPIC_DISPLAY_COLORS,
            stance_handoff=handoff,
        )
        top_idx = html.find("Today's question")
        agree_idx = html.find('source=brief_email')
        stories_idx = html.find('Stories') if 'Stories' in html else html.find('mobile-headline')
        bottom_tradeoffs = html.find('brief_tradeoffs')
        assert top_idx > 0
        assert agree_idx > 0
        assert 'Agree' in html
        assert 'Disagree' in html
        assert 'one quick question' in html
        assert 'Your turn' not in html
        assert 'Also today' not in html
        assert bottom_tradeoffs > top_idx


def test_stance_ajax_vote_stays_on_brief_json(client, db):
    from datetime import date

    today = date.today()
    q = DailyQuestion(
        question_date=today,
        question_number=50,
        question_text='Should we test inline brief voting?',
        status='published',
        source_type='discussion',
    )
    db.session.add(q)
    db.session.commit()

    response = client.post(
        '/daily/vote',
        data={
            'ajax': '1',
            'vote': 'agree',
            'participation_source': 'brief_stance',
            'context_expanded': '1',
        },
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert f'/daily/{today.isoformat()}' in payload['results_url']


def test_resolver_dispatches_by_type_without_false_warning(app, db, caplog):
    """A valid brief token must resolve to the 'brief' channel and log no WARNING.

    Regression: trying the question verifier first emitted a spurious
    'Token type mismatch' WARNING on the happy path of every brief vote.
    """
    import logging

    from app.models import DailyBriefSubscriber, DailyQuestionSubscriber
    from app.daily.vote_tokens import resolve_one_click_vote_token

    with app.app_context():
        db.create_all()
        q = DailyQuestion(
            question_date=date.today(),
            question_number=61,
            question_text='Does dispatch-by-type avoid log noise?',
            status='published',
            source_type='discussion',
        )
        brief_sub = DailyBriefSubscriber(email='resolver-brief@example.com', status='active')
        q_sub = DailyQuestionSubscriber(email='resolver-q@example.com', is_active=True)
        db.session.add_all([q, brief_sub, q_sub])
        db.session.commit()

        brief_token = brief_sub.generate_vote_token(q.id)
        q_token = q_sub.generate_vote_token(q.id)

        with caplog.at_level(logging.WARNING):
            sub, qid, err, channel = resolve_one_click_vote_token(brief_token)
            assert (channel, err, qid) == ('brief', None, q.id)
            assert sub.id == brief_sub.id

            sub, qid, err, channel = resolve_one_click_vote_token(q_token)
            assert (channel, err) == ('question', None)
            assert sub.id == q_sub.id

        assert not [r for r in caplog.records if r.levelno >= logging.WARNING], \
            [r.getMessage() for r in caplog.records]


def test_brief_and_question_vote_tokens_are_salt_isolated(app, db):
    """Salt namespacing: neither list can verify the other's token."""
    from app.models import DailyBriefSubscriber, DailyQuestionSubscriber

    with app.app_context():
        db.create_all()
        brief_sub = DailyBriefSubscriber(email='salt-brief@example.com', status='active')
        q_sub = DailyQuestionSubscriber(email='salt-q@example.com', is_active=True)
        db.session.add_all([brief_sub, q_sub])
        db.session.commit()

        brief_token = brief_sub.generate_vote_token(99)
        q_token = q_sub.generate_vote_token(99)

        # Brief token rejected by the question verifier (and vice versa) at the
        # signature layer — before any type check — because the salts differ.
        assert DailyQuestionSubscriber.verify_vote_token(brief_token)[2] == 'invalid'
        assert DailyBriefSubscriber.verify_vote_token(q_token)[2] == 'invalid'


def test_brief_subscriber_one_click_vote(client, db, app):
    from unittest.mock import MagicMock, patch

    from app.models import DailyBriefSubscriber, DailyQuestionResponse

    today = date.today()
    q = DailyQuestion(
        question_date=today,
        question_number=51,
        question_text='Should brief readers vote in-email?',
        status='published',
        source_type='discussion',
    )
    sub = DailyBriefSubscriber(email='oneclick-brief@example.com', status='active')
    db.session.add_all([q, sub])
    db.session.commit()

    token = sub.generate_vote_token(q.id)
    mock_ph = MagicMock()
    mock_ph.project_api_key = 'phk_test'

    with patch('app.daily.vote_analytics._posthog', mock_ph):
        confirm = client.get(f'/daily/v/{token}/agree?source=brief_email')
    assert confirm.status_code == 200

    viewed = [c.kwargs['event'] for c in mock_ph.capture.call_args_list]
    assert 'email_vote_confirm_viewed' in viewed

    with client.session_transaction() as sess:
        assert sess.get('brief_subscriber_id') == sub.id
        assert 'daily_subscriber_id' not in sess

    with patch('app.daily.vote_analytics._posthog', mock_ph):
        vote = client.post(
            f'/daily/v/{token}/agree?source=brief_email',
            data={},
            follow_redirects=False,
        )
    assert vote.status_code == 302
    assert today.isoformat() in vote.location

    confirmed = [c.kwargs['event'] for c in mock_ph.capture.call_args_list if c.kwargs['event'] == 'email_vote_confirmed']
    assert confirmed

    response = DailyQuestionResponse.query.filter_by(daily_question_id=q.id).one()
    assert response.vote == 1
    assert response.voted_via_email is True
