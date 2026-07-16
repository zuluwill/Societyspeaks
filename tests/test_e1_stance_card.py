"""Tests for E1 stance card context (brief end-cap)."""

from datetime import date

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
        assert handoff['stance_url'] == f'https://societyspeaks.io/brief/{today.isoformat()}#stance'


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
