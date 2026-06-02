"""Tests for participation-driving additions: world-today distribution, the
cumulative player profile, hub social proof, the first-decision preview, and the
v2 scenario→discussion bridge mappings."""

from datetime import datetime, time

import pytest

from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.game.engine.scenario import load_scenario
from app.game.services.bridge_service import _TAG_TO_DISCUSSION_TOPICS, _scenario_tags
from app.game.services.daily_results_service import world_today, world_today_share_line
from app.game.services.daily_service import utc_game_date
from app.game.services.profile_service import compute_player_profile
from app.game.services import stats_service
from app.lib.vote_identity import fingerprint_from_client_id
from app.models.game import GameRun, GameRunOutcome

_V2_SCENARIOS = [
    'pandemic-outbreak',
    'security-and-defence',
    'crime-and-justice',
    'disinformation-age',
    'trade-and-tariffs',
    'disaster-response',
    'pension-reckoning',
    'federal-fracture',
]


def _daily_with_turn0(db, *, slug, fingerprint, choice_id, when=None):
    """A completed daily run whose only logged decision is turn 1's choice."""
    started = when or datetime.combine(utc_game_date(), time(12, 0))
    run = GameRun(
        uuid=GameRun.generate_uuid(),
        scenario_slug=slug,
        mode='daily',
        session_fingerprint=fingerprint,
        society_name='Testland',
        emblem_seed=GameRun.generate_uuid(),
        state_json={},
        choice_log_json=[{'turn_index': 0, 'choice_id': choice_id}],
        delayed_queue_json=[],
        headline_log_json=[],
        turn_index=5,
        total_turns=5,
        status=GAME_RUN_STATUS_COMPLETED,
        started_at=started,
        completed_at=started,
    )
    db.session.add(run)
    db.session.commit()
    return run


def _completed_with_outcome(db, *, slug, fingerprint, ta=50.0, pf=50.0,
                            category='mixed_legacy', traits=None, when=None):
    started = when or datetime.combine(utc_game_date(), time(12, 0))
    run = GameRun(
        uuid=GameRun.generate_uuid(),
        scenario_slug=slug,
        mode='daily',
        session_fingerprint=fingerprint,
        society_name='Testland',
        emblem_seed=GameRun.generate_uuid(),
        state_json={},
        choice_log_json=[],
        delayed_queue_json=[],
        headline_log_json=[],
        turn_index=5,
        total_turns=5,
        status=GAME_RUN_STATUS_COMPLETED,
        started_at=started,
        completed_at=started,
    )
    db.session.add(run)
    db.session.flush()
    db.session.add(GameRunOutcome(
        run_id=run.id,
        headline='A nation, governed.',
        governance_label='Pragmatic survivor',
        outcome_category=category,
        axis_trust_autonomy=ta,
        axis_prosperity_fairness=pf,
        stat_finals_json={'prosperity': 50, 'trust': 50, 'fairness': 50, 'stability': 50},
        trait_chips_json=traits if traits is not None else ['Steady', 'Balanced'],
    ))
    db.session.commit()
    return run


# ---------- World today (per-turn choice distribution) ----------

def test_world_today_none_for_quick_run(app, db):
    with app.app_context():
        db.create_all()
        run = _daily_with_turn0(db, slug='pandemic-outbreak', fingerprint='a' * 64,
                                choice_id='lockdown_hard')
        run.mode = 'quick'
        db.session.commit()
        assert world_today(run) is None


def test_world_today_below_threshold_not_ready(app, db):
    with app.app_context():
        db.create_all()
        run = _daily_with_turn0(db, slug='pandemic-outbreak', fingerprint='a' * 64,
                                choice_id='lockdown_hard')
        result = world_today(run, min_n=5)
        assert result['ready'] is False
        assert result['sample_size'] == 1


def test_world_today_reports_distribution_and_marks_your_choice(app, db):
    with app.app_context():
        db.create_all()
        # 6 lockdown, 3 targeted, 1 trust (me — the minority).
        for i in range(6):
            _daily_with_turn0(db, slug='pandemic-outbreak',
                              fingerprint=f'l{i}' + 'l' * 60, choice_id='lockdown_hard')
        for i in range(3):
            _daily_with_turn0(db, slug='pandemic-outbreak',
                              fingerprint=f't{i}' + 't' * 60, choice_id='targeted_measures')
        me = _daily_with_turn0(db, slug='pandemic-outbreak', fingerprint='m' * 64,
                               choice_id='trust_the_public')

        result = world_today(me, min_n=5)
        assert result['ready'] is True
        assert result['sample_size'] == 10
        turn0 = result['turns'][0]
        pcts = {c['choice_id']: c['percent'] for c in turn0['choices']}
        assert pcts['lockdown_hard'] == 60
        assert pcts['targeted_measures'] == 30
        assert pcts['trust_the_public'] == 10
        # Sorted most-popular first.
        assert turn0['choices'][0]['choice_id'] == 'lockdown_hard'
        # My minority pick is flagged.
        mine = next(c for c in turn0['choices'] if c['is_yours'])
        assert mine['choice_id'] == 'trust_the_public'


def test_world_today_tally_is_cached_and_overlay_is_per_player(app, db, monkeypatch):
    """The distribution caches per (scenario, day); only 'is_yours' is per-run."""
    class FakeRedis:
        def __init__(self):
            self.store = {}
        def get(self, k):
            return self.store.get(k)
        def setex(self, k, ttl, v):
            self.store[k] = v

    fake = FakeRedis()
    monkeypatch.setattr('app.lib.redis_client.get_client', lambda decode_responses=True: fake)

    with app.app_context():
        db.create_all()
        for i in range(6):
            _daily_with_turn0(db, slug='pandemic-outbreak',
                              fingerprint=f'l{i}' + 'l' * 60, choice_id='lockdown_hard')
        me = _daily_with_turn0(db, slug='pandemic-outbreak', fingerprint='m' * 64,
                               choice_id='trust_the_public')

        first = world_today(me, min_n=5)
        assert first['ready'] is True and first['sample_size'] == 7
        # Something landed in the cache.
        assert any('game:world:tally' in k for k in fake.store)

        # Mutate the DB after caching — the cached tally must not move.
        for i in range(20):
            _daily_with_turn0(db, slug='pandemic-outbreak',
                              fingerprint=f'x{i}' + 'x' * 59, choice_id='targeted_measures')
        cached = world_today(me, min_n=5)
        assert cached['sample_size'] == 7  # still the stale, cached sample

        # A different player reads the same cached distribution, but the overlay
        # follows *their* pick.
        other = _daily_with_turn0(db, slug='pandemic-outbreak', fingerprint='o' * 64,
                                  choice_id='lockdown_hard')
        other_view = world_today(other, min_n=5)
        my_turn0 = {c['choice_id']: c['percent'] for c in cached['turns'][0]['choices']}
        other_turn0 = {c['choice_id']: c['percent'] for c in other_view['turns'][0]['choices']}
        assert my_turn0 == other_turn0  # same cached percentages
        assert next(c['choice_id'] for c in cached['turns'][0]['choices'] if c['is_yours']) == 'trust_the_public'
        assert next(c['choice_id'] for c in other_view['turns'][0]['choices'] if c['is_yours']) == 'lockdown_hard'


def test_world_today_share_line_only_for_minority(app, db):
    with app.app_context():
        db.create_all()
        for i in range(6):
            _daily_with_turn0(db, slug='pandemic-outbreak',
                              fingerprint=f'l{i}' + 'l' * 60, choice_id='lockdown_hard')
        for i in range(3):
            _daily_with_turn0(db, slug='pandemic-outbreak',
                              fingerprint=f't{i}' + 't' * 60, choice_id='targeted_measures')
        minority = _daily_with_turn0(db, slug='pandemic-outbreak', fingerprint='m' * 64,
                                     choice_id='trust_the_public')
        majority = _daily_with_turn0(db, slug='pandemic-outbreak', fingerprint='n' * 64,
                                     choice_id='lockdown_hard')

        line = world_today_share_line(world_today(minority, min_n=5))
        assert line and '%' in line
        # Majority pick (>=50%) doesn't brag.
        assert world_today_share_line(world_today(majority, min_n=5)) is None

    assert world_today_share_line(None) is None
    assert world_today_share_line({'ready': False}) is None


# ---------- Player profile ----------

def test_profile_none_without_identity(app, db):
    with app.app_context():
        db.create_all()
        assert compute_player_profile(user_id=None, session_fingerprint=None) is None


def test_profile_not_enough_below_minimum(app, db):
    fp = fingerprint_from_client_id('a' * 64)
    with app.app_context():
        db.create_all()
        _completed_with_outcome(db, slug='debt-inherited', fingerprint=fp)
        profile = compute_player_profile(user_id=None, session_fingerprint=fp)
        assert profile['total'] == 1
        assert profile['has_enough'] is False
        assert profile['lean'] is None


def test_profile_aggregates_leanings_and_outcomes(app, db):
    fp = fingerprint_from_client_id('b' * 64)
    with app.app_context():
        db.create_all()
        # Three runs leaning autonomy + fairness, mostly collapsing.
        for i in range(3):
            _completed_with_outcome(
                db, slug=f'debt-inherited', fingerprint=fp,
                ta=80.0, pf=80.0, category='collapse', traits=['Hard-nosed'],
            )
        profile = compute_player_profile(user_id=None, session_fingerprint=fp)
        assert profile['total'] == 3
        assert profile['has_enough'] is True
        assert profile['lean']['trust_autonomy']['direction'] == 'autonomy'
        assert profile['lean']['prosperity_fairness']['direction'] == 'fairness'
        assert profile['lean']['trust_autonomy']['strength'] == 60  # |80-50|*2
        assert profile['signature_traits'] == ['Hard-nosed']
        top = profile['outcome_breakdown'][0]
        assert top['category'] == 'collapse'
        assert top['percent'] == 100


def test_profile_scoped_to_visitor(app, db):
    mine = fingerprint_from_client_id('c' * 64)
    other = fingerprint_from_client_id('d' * 64)
    with app.app_context():
        db.create_all()
        for _i in range(3):
            _completed_with_outcome(db, slug='debt-inherited', fingerprint=mine)
        _completed_with_outcome(db, slug='debt-inherited', fingerprint=other)
        assert compute_player_profile(user_id=None, session_fingerprint=mine)['total'] == 3
        assert compute_player_profile(user_id=None, session_fingerprint=other)['total'] == 1


# ---------- Stats / social proof ----------

def test_participation_stats_hidden_below_floor(app, db):
    with app.app_context():
        db.create_all()
        stats_service._cache.update(at=0.0, value=None)
        _completed_with_outcome(db, slug='debt-inherited', fingerprint='e' * 64)
        stats = stats_service.participation_stats()
        assert stats['total'] == 1
        assert stats['today'] == 1
        assert stats['show'] is False


# ---------- Bridge mappings for v2 scenarios ----------

@pytest.mark.parametrize('slug', _V2_SCENARIOS)
def test_v2_scenario_has_at_least_one_bridgeable_tag(slug):
    scenario = load_scenario(slug)
    tags = _scenario_tags(scenario)
    assert tags, f'{slug} has no topic_tags'
    mapped = [t for t in tags if t in _TAG_TO_DISCUSSION_TOPICS]
    assert mapped, f'{slug} tags {sorted(tags)} bridge to no discussion topic'


# ---------- Routes ----------

def test_profile_route_empty_state(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'z' * 64)
    resp = client.get('/play/profile')
    assert resp.status_code == 200
    assert b'No profile yet' in resp.data


def test_profile_route_renders_tendencies(app, client, db):
    client_id = 'y' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        db.create_all()
        for _i in range(3):
            _completed_with_outcome(db, slug='debt-inherited', fingerprint=fp,
                                    ta=80.0, pf=80.0, category='collapse')
    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get('/play/profile')
    assert resp.status_code == 200
    assert b'Where you lean' in resp.data
    assert b'3 societies governed' in resp.data


def test_og_card_renders_with_and_without_world_badge():
    from types import SimpleNamespace

    from app.game.services import og_image_service

    if not og_image_service.is_available():
        pytest.skip('Pillow not available on this host')

    run = SimpleNamespace(society_name='Aurelia')
    view = {
        'headline': 'Against the odds, you held society together.',
        'governance_label': 'Pragmatic survivor',
        'scenario': {'title': 'The Inheritance'},
        'trait_chips': ['Steady', 'Bold'],
        'axis': {'trust_autonomy': 70, 'prosperity_fairness': 40},
    }
    emblem = {'accent': '#d4a853'}

    plain = og_image_service.render_outcome_png(run=run, view=view, emblem=emblem)
    badged = og_image_service.render_outcome_png(
        run=run, view=view, emblem=emblem,
        world_badge='Only 10% made the call you did: Trust the public',
    )
    for png in (plain, badged):
        assert png[:8] == b'\x89PNG\r\n\x1a\n'
        assert len(png) > 2_000
    # The badge changes the pixels, so the encoded bytes must differ.
    assert plain != badged


def test_hub_renders_social_proof_counter(app, client, db):
    """With enough plays, the hub shows the locale-formatted counter (no crash)."""
    with app.app_context():
        db.create_all()
        stats_service._cache.update(at=0.0, value=None)
        for i in range(50):  # at/above the _MIN_TOTAL_TO_SHOW floor
            _completed_with_outcome(db, slug='debt-inherited',
                                    fingerprint=f's{i}' + 's' * 58)
    client.set_cookie('ss_voter_client_id', 'h' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b'societies governed' in resp.data


def test_outcome_renders_world_distribution_when_enough(app, client, db):
    client_id = 'k' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        db.create_all()
        for i in range(34):
            _daily_with_turn0(db, slug='pandemic-outbreak',
                              fingerprint=f'w{i}' + 'w' * 58, choice_id='lockdown_hard')
        mine = _daily_with_turn0(db, slug='pandemic-outbreak', fingerprint=fp,
                                 choice_id='trust_the_public')
        # Outcome page needs an outcome row to render; attach a minimal one.
        db.session.add(GameRunOutcome(
            run_id=mine.id, headline='Held together.', governance_label='Survivor',
            outcome_category='mixed_legacy', axis_trust_autonomy=50.0,
            axis_prosperity_fairness=50.0,
            stat_finals_json={'prosperity': 50, 'trust': 50, 'fairness': 50, 'stability': 50},
            trait_chips_json=['Steady'],
        ))
        db.session.commit()
        run_uuid = mine.uuid
    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    assert b'How the world governed today' in resp.data
