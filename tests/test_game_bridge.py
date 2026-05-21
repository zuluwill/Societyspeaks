"""Tests for Play → Society Speaks outcome bridge (plan §1.3)."""

from uuid import uuid4

import pytest

from app.game.services.bridge_service import find_ss_bridge
from app.game.services.daily_service import utc_game_date
from app.models.daily_question import DailyQuestion
from app.models.discussions import Discussion


@pytest.fixture
def economy_discussion_id(app, db):
    with app.app_context():
        d = Discussion(
            title='Should we raise taxes to fund public services?',
            description='A debate on fiscal trade-offs and public spending.',
            keywords='taxation, economy, fiscal',
            slug=f'raise-taxes-{uuid4().hex[:8]}',
            topic='Economy',
            has_native_statements=True,
            partner_env='live',
            participant_count=42,
        )
        db.session.add(d)
        db.session.commit()
        return d.id


@pytest.fixture
def economy_daily_id(app, db, economy_discussion_id):
    with app.app_context():
        q = DailyQuestion(
            question_date=utc_game_date(),
            question_number=9999,
            question_text='Is borrowing to fund hospitals the right call?',
            topic_category='Economy & Healthcare',
            status='published',
            source_discussion_id=economy_discussion_id,
        )
        db.session.add(q)
        db.session.commit()
        return q.id


def test_bridge_prefers_daily_question_over_discussion(app, economy_daily_id, economy_discussion_id):
    with app.app_context():
        bridge = find_ss_bridge('debt-inherited')
    assert bridge is not None
    assert bridge['bridge_type'] == 'daily_question'
    assert bridge['target_id'] == economy_daily_id


def test_bridge_falls_back_to_discussion_when_no_daily(app, economy_discussion_id):
    with app.app_context():
        bridge = find_ss_bridge('tax-cuts-public-services')
    assert bridge is not None
    assert bridge['bridge_type'] == 'discussion'
    assert bridge['target_id'] == economy_discussion_id


def test_bridge_returns_none_without_topic_tags(app, db):
    with app.app_context():
        from app.game.services import bridge_service

        scenario = bridge_service.load_scenario('debt-inherited')
        scenario = {**scenario, 'topic_tags': []}
        original = bridge_service.load_scenario
        bridge_service.load_scenario = lambda _slug: scenario
        try:
            assert bridge_service.find_ss_bridge('debt-inherited') is None
        finally:
            bridge_service.load_scenario = original


def test_outcome_page_renders_bridge(app, client, db, monkeypatch):
    from app.lib.vote_identity import fingerprint_from_client_id

    from app.game.engine.scenario import load_scenario
    from app.game.services.run_service import apply_run_choice, get_or_start_slice_run

    monkeypatch.setattr(
        'app.game.routes.find_ss_bridge',
        lambda _slug: {
            'bridge_type': 'daily_question',
            'title': 'Is borrowing to fund hospitals the right call?',
            'subtitle': 'Economy',
            'url': '/daily/2026-01-01',
            'target_id': 1,
        },
    )

    client_id = 'b' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        run = get_or_start_slice_run(user_id=None, session_fingerprint=fp)
        scenario = load_scenario(run.scenario_slug)
        for turn in scenario['turns']:
            apply_run_choice(run, turn['choices'][0]['id'])
            run = db.session.get(type(run), run.id)
        run_uuid = run.uuid

    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    body = resp.data.lower()
    assert b'take this further' in body
    assert b'join the conversation' in body
    assert b'id="ss-bridge-link"' in body
