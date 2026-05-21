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
    assert b'Name your society' in resp.data
    assert b'id="society-name"' in resp.data


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


def test_hub_shows_first_time_explainer_for_new_visitor(app, client, db):
    """A visitor with no game history sees the explainer panel."""
    with app.app_context():
        db.create_all()
    client.set_cookie('ss_voter_client_id', 'x' * 64)
    resp = client.get('/play/')
    assert resp.status_code == 200
    assert b'New to Tradeoffs?' in resp.data
    assert b'Five minutes. Five choices.' in resp.data


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
