"""Tests for the v1-launch additions: Quick Run, streak, login merge, naming UI."""

from datetime import datetime, timedelta, timezone

import pytest

from app.game.engine.scenario import load_scenario
from app.game.services.daily_service import scheduled_scenario_slug
from app.game.services.identity_service import (
    compute_daily_streak,
    merge_anonymous_game_runs,
)
from app.game.services.quick_run_service import (
    is_quick_run_slug,
    quick_run_entry,
    quick_run_pool,
)
from app.game.services.run_service import (
    apply_run_choice,
    get_or_start_daily_run,
    start_quick_run,
)
from app.lib.vote_identity import fingerprint_from_client_id
from app.models.game import GameRun


def _play_to_completion(db, run):
    scenario = load_scenario(run.scenario_slug)
    for turn in scenario['turns']:
        result = apply_run_choice(run, turn['choices'][0]['id'])
        run = db.session.get(GameRun, run.id)
        if result['game_complete']:
            break
    return run


# ---------- Quick Run pool ----------

def test_quick_run_pool_excludes_today(app, db):
    with app.app_context():
        db.create_all()
        today_slug = scheduled_scenario_slug()
        pool = quick_run_pool()
        slugs = {e['scenario_slug'] for e in pool}
        assert today_slug not in slugs
        assert len(pool) >= 1
        for entry in pool:
            assert entry['title']
            assert entry['total_turns'] == 5


def test_is_quick_run_slug_validates():
    assert is_quick_run_slug('debt-inherited')
    assert is_quick_run_slug('housing-squeeze')
    assert not is_quick_run_slug('nonexistent-scenario')
    assert not is_quick_run_slug('')


def test_quick_run_entry_returns_metadata():
    entry = quick_run_entry('debt-inherited')
    assert entry is not None
    assert entry['scenario_slug'] == 'debt-inherited'
    assert entry['total_turns'] == 5


# ---------- Quick Run lifecycle ----------

def test_start_quick_run_creates_quick_mode_run(app, db):
    with app.app_context():
        db.create_all()
        run = start_quick_run(
            scenario_slug='debt-inherited',
            user_id=None,
            session_fingerprint=fingerprint_from_client_id('q' * 64),
        )
        assert run.mode == 'quick'
        assert run.status == 'in_progress'
        assert run.scenario_slug == 'debt-inherited'


def test_quick_run_completion_doesnt_count_toward_streak(app, db):
    """Plan §3.2 — Quick Runs explicitly do not credit the daily streak."""
    fp = fingerprint_from_client_id('w' * 64)
    with app.app_context():
        db.create_all()
        run = start_quick_run(
            scenario_slug='housing-squeeze',
            user_id=None,
            session_fingerprint=fp,
        )
        _play_to_completion(db, run)
        streak = compute_daily_streak(user_id=None, session_fingerprint=fp)
        assert streak['current'] == 0


def test_quick_run_page_loads(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'r' * 64)
    resp = client.get('/play/run/debt-inherited')
    assert resp.status_code == 200
    assert b'game-app' in resp.data
    assert b'game-choice' in resp.data


def test_quick_run_404s_unknown_scenario(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 's' * 64)
    resp = client.get('/play/run/not-a-real-scenario')
    assert resp.status_code == 404


def test_quick_run_always_fresh(app, client, db):
    """Two visits to /play/run/<slug> create two distinct runs (no resume gate)."""
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'f' * 64)
    resp1 = client.get('/play/run/housing-squeeze')
    resp2 = client.get('/play/run/housing-squeeze')
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    # Different game-app data-run-uuid attrs
    uuid1 = _extract_run_uuid(resp1.data)
    uuid2 = _extract_run_uuid(resp2.data)
    assert uuid1 and uuid2
    assert uuid1 != uuid2


def _extract_run_uuid(body: bytes) -> str:
    """Pull data-run-uuid attribute from rendered turn.html for assertion."""
    needle = b'data-run-uuid="'
    start = body.find(needle)
    if start < 0:
        return ''
    start += len(needle)
    end = body.find(b'"', start)
    return body[start:end].decode('utf-8') if end > start else ''


# ---------- Streak tracking ----------

def test_streak_zero_for_no_runs(app, db):
    fp = fingerprint_from_client_id('z' * 64)
    with app.app_context():
        db.create_all()
        streak = compute_daily_streak(user_id=None, session_fingerprint=fp)
        assert streak['current'] == 0
        assert streak['longest'] == 0
        assert streak['last_played_date'] is None


def test_streak_one_after_today(app, db):
    fp = fingerprint_from_client_id('1' * 64)
    with app.app_context():
        db.create_all()
        run = get_or_start_daily_run(
            scenario_slug=scheduled_scenario_slug(),
            user_id=None,
            session_fingerprint=fp,
        )
        _play_to_completion(db, run)
        streak = compute_daily_streak(user_id=None, session_fingerprint=fp)
        assert streak['current'] == 1
        assert streak['longest'] == 1


def test_streak_increments_on_consecutive_days(app, db):
    """A completed daily yesterday + one today = streak of 2."""
    fp = fingerprint_from_client_id('2' * 64)
    with app.app_context():
        db.create_all()
        # Yesterday's daily — manually set started_at back a day.
        yesterday_run = get_or_start_daily_run(
            scenario_slug='debt-inherited',
            user_id=None,
            session_fingerprint=fp,
        )
        yesterday = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        yesterday_run.started_at = yesterday
        db.session.commit()
        yesterday_run = _play_to_completion(db, yesterday_run)
        yesterday_run.started_at = yesterday  # play_to_completion does not touch started_at
        db.session.commit()

        # Today's daily.
        today_run = get_or_start_daily_run(
            scenario_slug='housing-squeeze',
            user_id=None,
            session_fingerprint=fp,
        )
        _play_to_completion(db, today_run)

        streak = compute_daily_streak(user_id=None, session_fingerprint=fp)
        assert streak['current'] == 2
        assert streak['longest'] == 2


def test_streak_breaks_on_gap(app, db):
    """A run from 3 days ago + nothing since today = no current streak."""
    fp = fingerprint_from_client_id('3' * 64)
    with app.app_context():
        db.create_all()
        run = get_or_start_daily_run(
            scenario_slug='debt-inherited',
            user_id=None,
            session_fingerprint=fp,
        )
        run.started_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
        db.session.commit()
        _play_to_completion(db, run)

        streak = compute_daily_streak(user_id=None, session_fingerprint=fp)
        assert streak['current'] == 0
        assert streak['longest'] == 1  # one historic day still counts as the longest


# ---------- Login merge ----------

def test_login_merge_claims_orphaned_runs(app, db):
    """A user signing in claims any GameRun rows on their browser fingerprints."""
    from app.models import User

    fp_a = fingerprint_from_client_id('a' * 64)
    fp_b = fingerprint_from_client_id('b' * 64)

    with app.app_context():
        db.create_all()
        user = User(email='merge-test@example.com', username='mergetest')
        user.set_password('test-password-123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        # Two anonymous runs across two fingerprints (same browser, cookie rotation).
        r1 = start_quick_run(scenario_slug='debt-inherited', user_id=None, session_fingerprint=fp_a)
        r2 = start_quick_run(scenario_slug='housing-squeeze', user_id=None, session_fingerprint=fp_b)
        assert r1.user_id is None and r2.user_id is None

        merged = merge_anonymous_game_runs(user_id, [fp_a, fp_b])
        assert merged == 2

        r1_after = db.session.get(GameRun, r1.id)
        r2_after = db.session.get(GameRun, r2.id)
        assert r1_after.user_id == user_id
        assert r2_after.user_id == user_id


def test_login_merge_is_idempotent(app, db):
    """Re-running the merge with the same fingerprints is a no-op."""
    from app.models import User

    fp = fingerprint_from_client_id('m' * 64)
    with app.app_context():
        db.create_all()
        user = User(email='idem@example.com', username='idem')
        user.set_password('test-password-123')
        db.session.add(user)
        db.session.commit()

        start_quick_run(scenario_slug='debt-inherited', user_id=None, session_fingerprint=fp)
        first = merge_anonymous_game_runs(user.id, [fp])
        second = merge_anonymous_game_runs(user.id, [fp])
        assert first == 1
        assert second == 0


def test_logged_in_run_records_fingerprint_for_login_logout_bounce(app, db):
    """A logged-in run should also store the fingerprint so logout doesn't reset same-day replay."""
    from app.models import User

    fp = fingerprint_from_client_id('5' * 64)
    with app.app_context():
        db.create_all()
        user = User(email='bounce@example.com', username='bouncer')
        user.set_password('test-password-123')
        db.session.add(user)
        db.session.commit()

        run = get_or_start_daily_run(
            scenario_slug=scheduled_scenario_slug(),
            user_id=user.id,
            session_fingerprint=fp,
        )
        # Both identities recorded so a logout doesn't lose the run.
        assert run.user_id == user.id
        assert run.session_fingerprint == fp


def test_same_day_replay_blocked_across_login_logout(app, db):
    """Logged-in user plays today, logs out, visits anonymously — same-day check still triggers."""
    from app.game.engine.scenario import load_scenario
    from app.game.services.daily_service import scheduled_scenario_slug
    from app.game.services.run_service import apply_run_choice, get_or_start_daily_run
    from app.lib.vote_identity import fingerprint_from_client_id
    from app.models import User
    from app.models.game import GameRun

    fp = fingerprint_from_client_id('8' * 64)

    with app.app_context():
        db.create_all()
        user = User(email='bypass@example.com', username='bypass')
        user.set_password('test-password-123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        slug = scheduled_scenario_slug()
        # Play as logged-in (with fingerprint also recorded).
        run = get_or_start_daily_run(
            scenario_slug=slug,
            user_id=user_id,
            session_fingerprint=fp,
        )
        scenario = load_scenario(slug)
        for turn in scenario['turns']:
            result = apply_run_choice(run, turn['choices'][0]['id'])
            run = db.session.get(GameRun, run.id)
            if result['game_complete']:
                break
        completed_uuid = run.uuid

        # Now simulate a logged-out same-browser visit: user_id=None, same fingerprint.
        # Should NOT create a fresh run; should return the existing completed one.
        rerun = get_or_start_daily_run(
            scenario_slug=slug,
            user_id=None,
            session_fingerprint=fp,
        )
        assert rerun.uuid == completed_uuid
        assert rerun.status == 'completed'


def test_sitemap_includes_play_routes(app, client, db):
    """SEO: /play and /play/editorial-principles are crawlable per the sitemap."""
    with app.app_context():
        db.create_all()
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert '/play</loc>' in body
    assert '/play/editorial-principles</loc>' in body


def test_sitemap_omits_play_routes_when_game_disabled(app, client, db):
    with app.app_context():
        db.create_all()
        app.config['GAME_ENABLED'] = False
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert '/play</loc>' not in body
    assert '/play/editorial-principles</loc>' not in body


def test_player_has_game_history_matches_either_identity(app, db):
    """Hub explainer stays hidden after logout when only fingerprint matches."""
    from app.game.services.identity_service import player_has_game_history
    from app.lib.vote_identity import fingerprint_from_client_id

    fp = fingerprint_from_client_id('c' * 64)
    with app.app_context():
        db.create_all()
        start_quick_run(
            scenario_slug='debt-inherited',
            user_id=None,
            session_fingerprint=fp,
        )
        assert player_has_game_history(user_id=999, session_fingerprint=fp) is True
        assert player_has_game_history(user_id=999, session_fingerprint='wrong') is False


def test_footer_links_to_tradeoffs(app, client, db):
    """Footer discovery: Tradeoffs is listed alongside Daily Question and Daily Brief."""
    with app.app_context():
        db.create_all()
    resp = client.get('/')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    # Footer has all three daily-habit products
    assert body.count('Tradeoffs') >= 1
    assert 'Daily Brief' in body
    # The footer specifically — find the </footer> close tag and confirm Tradeoffs appears before it
    footer_end = body.rfind('</footer>')
    footer_start = body.rfind('<footer', 0, footer_end)
    footer = body[footer_start:footer_end] if footer_start != -1 else body
    assert 'Tradeoffs' in footer


def test_login_merge_ignores_other_users_runs(app, db):
    """Already-owned runs aren't reassigned to a different user."""
    from app.models import User

    fp = fingerprint_from_client_id('o' * 64)
    with app.app_context():
        db.create_all()
        owner = User(email='owner@example.com', username='owner')
        owner.set_password('test-password-123')
        intruder = User(email='intruder@example.com', username='intruder')
        intruder.set_password('test-password-123')
        db.session.add_all([owner, intruder])
        db.session.commit()

        run = start_quick_run(
            scenario_slug='debt-inherited',
            user_id=owner.id,
            session_fingerprint=fp,
        )
        merged = merge_anonymous_game_runs(intruder.id, [fp])
        assert merged == 0

        run_after = db.session.get(GameRun, run.id)
        assert run_after.user_id == owner.id


# ---------- Hub UI ----------

def test_hub_renders_quick_run_pool(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'h' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b'Quick Run' in resp.data
    # At least one quick run link
    assert b'/play/run/' in resp.data


def test_hub_renders_society_name_input_when_no_active_run(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'n' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b'Your society' in resp.data
    assert b'id="society-name"' in resp.data


def test_hub_prefills_a_suggested_society_name(app, client, db):
    """The name input ships with a non-empty, non-placeholder suggestion so the
    only required action is "Play"."""
    import re

    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'q' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    body = resp.data.decode()
    match = re.search(r'id="society-name"[^>]*\bvalue="([^"]+)"', body)
    assert match, 'society-name input should carry a pre-filled value'
    assert match.group(1).strip(), 'pre-filled society name must not be blank'
    # The roll-another affordance ships its candidate pool inline for offline reuse.
    assert b'id="society-reroll"' in resp.data
    assert b'data-suggestions=' in resp.data
    # name_source starts as "suggested" until the player types.
    assert b'id="name-source"' in resp.data
    assert b'value="suggested"' in resp.data


def test_hub_renders_signin_cta_for_anonymous(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'g' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b'Sign up free' in resp.data
    assert b'Sign in' in resp.data


def test_society_name_param_persists_through_to_run(app, client, db):
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'p' * 64)
    resp = client.get('/play/daily?name=Atlas%20Republic')
    assert resp.status_code == 200
    assert b'Atlas Republic' in resp.data


def test_quick_run_carries_society_name(app, client, db):
    """A name passed to the Quick Run route ends up on the rendered run."""
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'k' * 64)
    resp = client.get('/play/run/debt-inherited?name=Riverlands')
    assert resp.status_code == 200
    assert b'Riverlands' in resp.data


def test_turn_screen_marks_quick_runs(app, client, db):
    """The turn screen header tells the player they're in Quick Run mode."""
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'j' * 64)
    resp = client.get('/play/run/housing-squeeze')
    assert resp.status_code == 200
    assert b'Quick Run' in resp.data


def test_hub_quick_run_links_carry_name_via_data_attr(app, client, db):
    """The hub exposes a base href on Quick Run cards so JS can append ?name=."""
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'i' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b'data-quick-run-base' in resp.data


def test_hub_signin_offers_magic_link_with_play_next(app, client, db):
    """Hub sign-in CTA routes to magic-link request, not password login,
    and pre-fills next=/play/ so users land back on the hub after signing in."""
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'm' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    body = resp.data
    # Magic-link CTA wording present
    assert b'Email me a sign-in link' in body
    assert b'Already have an account?' in body
    # Link targets the magic-link request with next=/play/
    assert b'/auth/login/magic-link?next=%2Fplay%2F' in body or b'/auth/login/magic-link?next=/play/' in body
    # Sign-up CTA preserves the destination
    assert b'/auth/register?next=' in body
    # The bare password "Sign in" button is gone from the hub
    sign_in_section_start = body.find(b'game-hub-signin')
    assert sign_in_section_start > 0
    sign_in_section_end = body.find(b'</section>', sign_in_section_start)
    sign_in_block = body[sign_in_section_start:sign_in_section_end]
    assert b'/auth/login"' not in sign_in_block and b'/auth/login?' not in sign_in_block


def test_outcome_signin_offers_magic_link_with_outcome_next_for_owner(app, client, db):
    """Run owner signing in from their outcome returns to that outcome page."""
    run_uuid = _play_to_completion_via_route(app, db, client, 'n' * 64)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    body = resp.data
    assert b'Email me a sign-in link' in body
    assert b'Already have an account?' in body
    encoded_next = f'/auth/login/magic-link?next=%2Fplay%2Foutcome%2F{run_uuid}'.encode()
    plain_next = f'/auth/login/magic-link?next=/play/outcome/{run_uuid}'.encode()
    assert encoded_next in body or plain_next in body
    reg_encoded = f'/auth/register?next=%2Fplay%2Foutcome%2F{run_uuid}'.encode()
    reg_plain = f'/auth/register?next=/play/outcome/{run_uuid}'.encode()
    assert reg_encoded in body or reg_plain in body


def test_outcome_signin_returns_hub_for_shared_link_viewer(app, client, db):
    """A visitor reading someone else's shared outcome lands on /play/ after sign-in."""
    run_uuid = _play_to_completion_via_route(app, db, client, 'a' * 64)
    client.set_cookie('ss_voter_client_id', 'b' * 64)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    body = resp.data
    assert b'/auth/login/magic-link?next=%2Fplay%2F' in body or b'/auth/login/magic-link?next=/play/' in body
    assert f'/auth/login/magic-link?next=%2Fplay%2Foutcome%2F{run_uuid}'.encode() not in body
    assert f'/auth/login/magic-link?next=/play/outcome/{run_uuid}'.encode() not in body


def _play_to_completion_via_route(app, db, client, client_id):
    """Helper — play today's daily through the test client, return outcome UUID."""
    from app.game.engine.scenario import load_scenario
    from app.game.services.daily_service import scheduled_scenario_slug
    from app.lib.vote_identity import fingerprint_from_client_id

    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        db.create_all()
        run = get_or_start_daily_run(
            scenario_slug=scheduled_scenario_slug(),
            user_id=None,
            session_fingerprint=fp,
        )
        scenario = load_scenario(run.scenario_slug)
        for turn in scenario['turns']:
            result = apply_run_choice(run, turn['choices'][0]['id'])
            run = db.session.get(GameRun, run.id)
            if result['game_complete']:
                break
        run_uuid = run.uuid
    client.set_cookie('ss_voter_client_id', client_id)
    return run_uuid


def test_hub_shows_first_time_explainer_for_new_visitor(app, client, db):
    """A visitor with no game history sees the explainer panel."""
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'x' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b'New to Tradeoffs?' in resp.data
    assert b"You're in charge. Every decision costs something." in resp.data


def test_hub_hides_explainer_after_first_play(app, client, db):
    """Once a player has played once, the explainer disappears."""
    from app.game.engine.scenario import load_scenario
    from app.game.services.daily_service import scheduled_scenario_slug
    from app.lib.vote_identity import fingerprint_from_client_id

    client_id = 'y' * 64
    fp = fingerprint_from_client_id(client_id)

    with app.app_context():
        db.create_all()
        run = get_or_start_daily_run(
            scenario_slug=scheduled_scenario_slug(),
            user_id=None,
            session_fingerprint=fp,
        )
        scenario = load_scenario(run.scenario_slug)
        for turn in scenario['turns']:
            result = apply_run_choice(run, turn['choices'][0]['id'])
            run = db.session.get(GameRun, run.id)
            if result['game_complete']:
                break

    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b'New to Tradeoffs?' not in resp.data


def test_hub_hides_explainer_after_quick_run_only(app, client, db):
    """Quick Run-only players are not treated as first-time visitors."""
    with app.app_context():
        db.create_all()
        run = start_quick_run(
            scenario_slug='debt-inherited',
            user_id=None,
            session_fingerprint=fingerprint_from_client_id('z' * 64),
        )
        _play_to_completion(db, run)

    client.set_cookie('ss_voter_client_id', 'z' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b'New to Tradeoffs?' not in resp.data


# ---------- Society-name suggestions ----------

def test_name_generator_produces_distinct_nonempty_names():
    import random

    from app.game.services.society_name_service import generate_society_names

    names = generate_society_names(12, rng=random.Random(42))
    assert len(names) == 12
    assert len(set(names)) == 12, 'suggestions within a batch must be unique'
    for name in names:
        assert name.strip(), 'a suggestion must never be blank'
        assert len(name) <= 48, 'must fit the input maxlength'


def test_name_generator_is_deterministic_with_seed():
    import random

    from app.game.services.society_name_service import generate_society_names

    first = generate_society_names(8, rng=random.Random(7))
    second = generate_society_names(8, rng=random.Random(7))
    assert first == second


def test_name_generator_accepts_string_seed_for_stability():
    """The hub seeds by visitor+date so a reload doesn't shuffle the pre-fill."""
    from app.game.services.society_name_service import generate_society_names

    a1 = generate_society_names(12, seed='visitor-x|2026-06-01')
    a2 = generate_society_names(12, seed='visitor-x|2026-06-01')
    assert a1 == a2, 'same seed must yield the same suggestions'

    b = generate_society_names(12, seed='visitor-y|2026-06-01')
    c = generate_society_names(12, seed='visitor-x|2026-06-02')
    # Different visitor (same day) and same visitor (different day) should
    # not lock to the same first suggestion — variety is the point.
    assert a1[0] != b[0] or a1[0] != c[0]


def test_hub_prefill_is_stable_across_reloads(app, client, db):
    """Same visitor + same UTC day → the same pre-filled suggestion on reload."""
    import re

    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'r' * 64)
    pattern = re.compile(r'id="society-name"[^>]*\bvalue="([^"]+)"')

    first = pattern.search(client.get('/play/').data.decode())
    second = pattern.search(client.get('/play/').data.decode())
    assert first and second
    assert first.group(1) == second.group(1), (
        'reloading the hub must not shuffle the pre-filled society name'
    )


def test_name_source_helper_maps_to_analytics_flag():
    from app.game.routes import _name_was_custom

    assert _name_was_custom('custom') is True
    assert _name_was_custom('suggested') is False
    assert _name_was_custom(None) is None
    assert _name_was_custom('garbage') is None


def _captured_started_events(monkeypatch):
    """Patch analytics so we can inspect game_run_started properties."""
    events = []

    def _capture(run, event, properties=None):
        events.append((event, properties or {}))

    monkeypatch.setattr(
        'app.game.services.run_service.track_game_event', _capture
    )
    return events


def test_suggested_name_is_not_counted_as_custom(app, db, monkeypatch):
    """A player who accepts/rolls our suggestion is not flagged has_custom_name,
    even though the stored name differs from the default."""
    events = _captured_started_events(monkeypatch)
    with app.app_context():
        db.create_all()
        start_quick_run(
            scenario_slug='debt-inherited',
            user_id=None,
            session_fingerprint=fingerprint_from_client_id('s' * 64),
            society_name='The Halcyon Republic',
            name_was_custom=False,
        )
    started = [p for (e, p) in events if e == 'game_run_started']
    assert started and started[0]['has_custom_name'] is False


def test_typed_name_is_counted_as_custom(app, db, monkeypatch):
    events = _captured_started_events(monkeypatch)
    with app.app_context():
        db.create_all()
        get_or_start_daily_run(
            scenario_slug=scheduled_scenario_slug(),
            user_id=None,
            session_fingerprint=fingerprint_from_client_id('t' * 64),
            society_name='My Own Republic',
            name_was_custom=True,
        )
    started = [p for (e, p) in events if e == 'game_run_started']
    assert started and started[0]['has_custom_name'] is True


def test_missing_flag_falls_back_to_legacy_string_compare(app, db, monkeypatch):
    """Callers that don't pass the hint keep the old behaviour: a name that
    differs from the default counts as custom."""
    events = _captured_started_events(monkeypatch)
    with app.app_context():
        db.create_all()
        start_quick_run(
            scenario_slug='debt-inherited',
            user_id=None,
            session_fingerprint=fingerprint_from_client_id('u' * 64),
            society_name='Riverlands',
        )
    started = [p for (e, p) in events if e == 'game_run_started']
    assert started and started[0]['has_custom_name'] is True


def test_homepage_renders_tradeoffs_card(app, client, db):
    """The Three Ways section now includes the Tradeoffs card."""
    with app.app_context():
        db.create_all()
    resp = client.get('/')
    assert resp.status_code == 200
    body = resp.data
    assert b'Three daily ways to engage' in body
    # All three product names appear in the lineup
    assert b'The Daily Question' in body
    assert b'The Daily Brief' in body
    assert b'Tradeoffs' in body
    # The card links to /play
    assert b'/play' in body


def test_editorial_principles_renders_magazine_layout(app, client, db):
    """The 'How it works' page is now magazine-grade — title, deck, principles list, footer CTA."""
    with app.app_context():
        db.create_all()
    resp = client.get('/play/editorial-principles')
    assert resp.status_code == 200
    body = resp.data
    # Magazine structure
    assert b'game-editorial-eyebrow' in body
    assert b'game-editorial-title' in body
    assert b'game-editorial-deck' in body
    assert b'game-editorial-principles' in body
    # Content checks — the north-star quote, the ten principles, the publish gate, the contact
    assert b'never grades the reflection' in body
    assert b'What Tradeoffs is' in body
    assert b'What Tradeoffs is not' in body
    assert b'What the validator catches' in body
    assert b'Who writes the scenarios' in body
    assert b'When we get it wrong' in body
    assert b'info@societyspeaks.io' in body
    # Footer CTA back to play
    assert b'Play today' in body


def test_editorial_principles_uses_wider_main(app, client, db):
    """Editorial layout overrides the default narrow shell."""
    with app.app_context():
        db.create_all()
    resp = client.get('/play/editorial-principles')
    assert resp.status_code == 200
    assert b'max-w-2xl' in resp.data


def test_privacy_policy_contains_play_section(app, client, db):
    """Privacy policy §1.4 covers Society Play (Tradeoffs) game data."""
    with app.app_context():
        db.create_all()
    resp = client.get('/privacy-policy')
    assert resp.status_code == 200
    body = resp.data
    assert b'1.4 Society Play' in body
    assert b'Tradeoffs' in body
    # Data categories called out
    assert b'Choice log' in body
    assert b'Society state' in body
    assert b'Session fingerprint' in body
    # Retention windows
    assert b'24 months' in body
    assert b'30 days' in body
    # Rights — anonymous + logged-in paths
    assert b'Delete your account' in body
    assert b'ss_voter_client_id' in body
    # Honesty about share-link semantics
    assert b'unguessable but not encrypted' in body


def test_homepage_tradeoffs_card_falls_back_without_play_meta(app, client, db, monkeypatch):
    """Homepage stays alive even if the game meta loader raises."""
    import app.routes as main_routes
    monkeypatch.setattr(
        'app.game.services.daily_service.daily_meta',
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('boom')),
    )
    with app.app_context():
        db.create_all()
    resp = client.get('/')
    assert resp.status_code == 200
    # Generic fallback copy appears when play_meta is None
    assert b'A new crisis. Five choices.' in resp.data


def test_build_share_text_contains_identity_stats_and_url(app):
    from app.game.services.share_text_service import build_share_text

    with app.app_context():
        text = build_share_text(
            society_name='Riverlands',
            headline='Everyone trusted you. The country ran out of money.',
            governance_label='Short-Term Fixer',
            scenario_title='Debt inherited',
            visible_stats={'prosperity': 41, 'trust': 72, 'fairness': 58, 'stability': 63},
            trait_chips=['High-trust', 'Debt-heavy'],
            streak_current=3,
            contradiction_summary='You chose growth twice. Fairness never recovered.',
            share_url='https://societyspeaks.io/play/outcome/abc-123',
            challenge_url='https://societyspeaks.io/play/challenge/xyz',
        )
    assert 'Riverlands' in text
    assert 'Everyone trusted you' in text
    assert 'Short-Term Fixer' in text
    assert '72 🤝' in text
    assert 'Challenge a friend' in text
    assert 'https://societyspeaks.io/play/challenge/xyz' in text


def test_outcome_page_renders_share_results_block(app, client, db):
    from app.game.engine.scenario import load_scenario
    from app.game.services.run_service import apply_run_choice, get_or_start_slice_run
    from app.lib.vote_identity import fingerprint_from_client_id

    client_id = 's' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        db.create_all()
        run = get_or_start_slice_run(user_id=None, session_fingerprint=fp)
        scenario = load_scenario(run.scenario_slug)
        for turn in scenario['turns']:
            result = apply_run_choice(run, turn['choices'][0]['id'])
            run = db.session.get(type(run), run.id)
            if result['game_complete']:
                break
        run_uuid = run.uuid

    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get(f'/play/outcome/{run_uuid}')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'Share your results' in body
    assert 'Share results' in body
    assert 'game-share-preview' in body
    assert 'game-share-payload' in body
    assert 'What kind of leader would you be?' in body
    assert f'/play/outcome/{run_uuid}' in body
    assert 'outcome.js?v=6' in body
    assert '/play/challenge/' in body


def test_friend_challenge_reveals_creator_headline(app, client, db):
    from app.game.engine.scenario import load_scenario
    from app.game.services.challenge_service import get_or_create_challenge
    from app.game.services.run_service import apply_run_choice, get_or_start_slice_run
    from app.lib.vote_identity import fingerprint_from_client_id

    creator_id = 'c1' * 32
    friend_id = 'f1' * 32
    creator_fp = fingerprint_from_client_id(creator_id)
    friend_fp = fingerprint_from_client_id(friend_id)

    with app.app_context():
        db.create_all()
        creator_run = get_or_start_slice_run(user_id=None, session_fingerprint=creator_fp)
        scenario = load_scenario(creator_run.scenario_slug)
        for turn in scenario['turns']:
            result = apply_run_choice(creator_run, turn['choices'][0]['id'])
            creator_run = db.session.get(type(creator_run), creator_run.id)
            if result['game_complete']:
                break
        challenge = get_or_create_challenge(creator_run)
        assert challenge is not None
        token = challenge.token
        creator_headline = creator_run.outcome.headline
        slug = creator_run.scenario_slug

        friend_run = get_or_start_slice_run(user_id=None, session_fingerprint=friend_fp)
        assert friend_run.scenario_slug == slug
        for turn in scenario['turns']:
            result = apply_run_choice(friend_run, turn['choices'][1]['id'] if len(turn['choices']) > 1 else turn['choices'][0]['id'])
            friend_run = db.session.get(type(friend_run), friend_run.id)
            if result['game_complete']:
                break
        friend_uuid = friend_run.uuid

    client.set_cookie('ss_voter_client_id', friend_id)
    with client.session_transaction() as sess:
        sess['pending_game_challenge'] = token
    resp = client.get(f'/play/outcome/{friend_uuid}')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'Same scenario · different path' in body
    assert creator_headline in body


def test_challenge_anonymous_creator_localises_to_someone(app, db):
    """A default-name creator stores a sentinel, not literal 'Someone' — so the
    label renders in the viewer's locale, not the creator's."""
    from app.game.engine.scenario import load_scenario
    from app.game.services.challenge_service import (
        _ANONYMOUS_CREATOR_TOKEN,
        challenge_reveal_for_run,
        get_or_create_challenge,
    )
    from app.game.services.run_service import apply_run_choice, get_or_start_slice_run

    fp = fingerprint_from_client_id('a' * 64)
    with app.app_context():
        db.create_all()

        # Creator with default society name.
        creator = get_or_start_slice_run(user_id=None, session_fingerprint=fp)
        # society_name comes out as the default
        scenario = load_scenario(creator.scenario_slug)
        for turn in scenario['turns']:
            r = apply_run_choice(creator, turn['choices'][0]['id'])
            creator = db.session.get(GameRun, creator.id)
            if r['game_complete']:
                break
        challenge = get_or_create_challenge(creator)
        # Sentinel stored in DB — viewer's gettext renders the localised label.
        assert challenge.creator_display_name == _ANONYMOUS_CREATOR_TOKEN

        # A friend playing the challenge gets the localised label on reveal.
        friend_fp = fingerprint_from_client_id('b' * 64)
        friend = get_or_start_slice_run(user_id=None, session_fingerprint=friend_fp)
        for turn in load_scenario(friend.scenario_slug)['turns']:
            r = apply_run_choice(friend, turn['choices'][0]['id'])
            friend = db.session.get(GameRun, friend.id)
            if r['game_complete']:
                break

        reveal = challenge_reveal_for_run(
            completed_run=friend,
            pending_token=challenge.token,
        )
        assert reveal is not None
        # Default English locale resolves to "Someone".
        assert reveal['display_name'] == 'Someone'


def test_challenge_named_creator_preserves_society_name(app, db):
    """A creator who named their society stores the literal name (no localisation)."""
    from app.game.engine.scenario import load_scenario
    from app.game.services.challenge_service import (
        challenge_reveal_for_run,
        get_or_create_challenge,
    )
    from app.game.services.run_service import (
        apply_run_choice,
        get_or_start_daily_run,
    )
    from app.game.services.daily_service import scheduled_scenario_slug

    fp = fingerprint_from_client_id('c' * 64)
    with app.app_context():
        db.create_all()
        creator = get_or_start_daily_run(
            scenario_slug=scheduled_scenario_slug(),
            user_id=None,
            session_fingerprint=fp,
            society_name='Atlas Republic',
        )
        for turn in load_scenario(creator.scenario_slug)['turns']:
            r = apply_run_choice(creator, turn['choices'][0]['id'])
            creator = db.session.get(GameRun, creator.id)
            if r['game_complete']:
                break
        challenge = get_or_create_challenge(creator)
        assert challenge.creator_display_name == 'Atlas Republic'

        friend_fp = fingerprint_from_client_id('d' * 64)
        friend = get_or_start_daily_run(
            scenario_slug=creator.scenario_slug,
            user_id=None,
            session_fingerprint=friend_fp,
        )
        for turn in load_scenario(friend.scenario_slug)['turns']:
            r = apply_run_choice(friend, turn['choices'][0]['id'])
            friend = db.session.get(GameRun, friend.id)
            if r['game_complete']:
                break

        reveal = challenge_reveal_for_run(
            completed_run=friend,
            pending_token=challenge.token,
        )
        assert reveal['display_name'] == 'Atlas Republic'


def test_challenge_link_redirects_to_play(app, client, db):
    from app.game.services.challenge_service import get_or_create_challenge
    from app.game.services.run_service import apply_run_choice, get_or_start_slice_run
    from app.lib.vote_identity import fingerprint_from_client_id

    client_id = 'z' * 64
    fp = fingerprint_from_client_id(client_id)
    with app.app_context():
        db.create_all()
        from app.game.engine.scenario import load_scenario

        run = get_or_start_slice_run(user_id=None, session_fingerprint=fp)
        scenario = load_scenario(run.scenario_slug)
        for turn in scenario['turns']:
            result = apply_run_choice(run, turn['choices'][0]['id'])
            run = db.session.get(type(run), run.id)
            if result['game_complete']:
                break
        challenge = get_or_create_challenge(run)
        token = challenge.token

    client.set_cookie('ss_voter_client_id', client_id)
    resp = client.get(f'/play/challenge/{token}', follow_redirects=False)
    assert resp.status_code == 302
    assert '/play/daily/' in resp.headers['Location'] or '/play/run/' in resp.headers['Location']
    with client.session_transaction() as sess:
        assert sess.get('pending_game_challenge') == token
