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
        assert handoff['stance_url_top'] == (
            f'https://societyspeaks.io/brief/{today.isoformat()}'
            f'?src=brief_stance_top#stance'
        )
        assert handoff['tradeoffs_url'] == (
            'https://societyspeaks.io/play/daily?src=brief_tradeoffs'
        )
        assert handoff['tradeoffs_url_top'] == (
            'https://societyspeaks.io/play/daily?src=brief_tradeoffs_top'
        )


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
        assert 'brief_stance_top' in handoff['stance_url_top']
        assert handoff['tradeoffs_url'].endswith('?src=brief_tradeoffs')
        assert handoff['tradeoffs_url_top'].endswith('?src=brief_tradeoffs_top')


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
            'stance_url': (
                f'https://societyspeaks.io/brief/{yesterday.isoformat()}'
                f'?src=brief_stance#stance'
            ),
            'stance_url_top': (
                f'https://societyspeaks.io/brief/{yesterday.isoformat()}'
                f'?src=brief_stance_top#stance'
            ),
            'tradeoffs_url': 'https://societyspeaks.io/play/daily?src=brief_tradeoffs',
            'tradeoffs_url_top': 'https://societyspeaks.io/play/daily?src=brief_tradeoffs_top',
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
        top_idx = html.find('Also today')
        top_src = html.find('brief_stance_top')
        bottom_idx = html.find('Your turn')
        assert top_idx > 0
        assert top_src > 0
        assert bottom_idx > top_idx
        assert "Take today's stance" in html
        # Tradeoffs attribution is split by placement, like stance: the above-fold
        # teaser is measurable separately from the footer payoff.
        top_tradeoffs = html.find('brief_tradeoffs_top')
        bottom_tradeoffs = html.find('src=brief_tradeoffs"')
        assert 0 < top_tradeoffs < bottom_idx  # teaser tradeoffs is above the fold
        assert bottom_tradeoffs > bottom_idx   # footer tradeoffs follows "Your turn"


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
