"""
Tests for the refinement endpoint (Block C — retention lever).

Covers:
  - empty refinement → flash + redirect, no DB change
  - first-time refinement → custom_prompt set to "Refinement: <note>"
  - subsequent refinement → appended with separator, both notes preserved
  - over-long input → truncated to MAX_NOTE_CHARS
  - other user can't refine someone else's briefing
"""
from app.models import User
from app.models.briefing import Briefing


def _seed_user(db, username='alice', email='alice@example.com'):
    u = User(username=username, email=email, password='hashed', email_verified=True)
    db.session.add(u)
    db.session.flush()
    return u


def _seed_briefing(db, user, custom_prompt=None):
    b = Briefing(
        owner_type='user', owner_id=user.id,
        name='My Brief',
        cadence='daily', timezone='UTC', preferred_send_hour=7,
        mode='auto_send', visibility='private',
        custom_prompt=custom_prompt,
        status='active',
    )
    db.session.add(b)
    db.session.flush()
    return b


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_refine_empty_input_flashes_and_redirects(app, db):
    with app.app_context():
        user = _seed_user(db)
        briefing = _seed_briefing(db, user)
        db.session.commit()
        user_id, briefing_id = user.id, briefing.id

    client = app.test_client()
    _login(client, user_id)

    resp = client.post(
        f'/briefings/{briefing_id}/refine',
        data={'refinement': '   ', 'csrf_token': 'test'},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert f'/briefings/{briefing_id}' in resp.headers['Location']

    with app.app_context():
        b = db.session.get(Briefing, briefing_id)
        assert (b.custom_prompt or '') == ''


def test_refine_first_time_sets_prompt(app, db):
    with app.app_context():
        user = _seed_user(db, username='bob', email='bob@example.com')
        briefing = _seed_briefing(db, user)
        db.session.commit()
        user_id, briefing_id = user.id, briefing.id

    client = app.test_client()
    _login(client, user_id)

    resp = client.post(
        f'/briefings/{briefing_id}/refine',
        data={'refinement': 'more AI policy, less crypto', 'csrf_token': 'test'},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        b = db.session.get(Briefing, briefing_id)
        assert 'more AI policy, less crypto' in b.custom_prompt
        assert b.custom_prompt.startswith('Refinement:')


def test_refine_appends_to_existing_prompt(app, db):
    with app.app_context():
        user = _seed_user(db, username='carol', email='carol@example.com')
        briefing = _seed_briefing(db, user, custom_prompt='Focus on tech.')
        db.session.commit()
        user_id, briefing_id = user.id, briefing.id

    client = app.test_client()
    _login(client, user_id)

    resp = client.post(
        f'/briefings/{briefing_id}/refine',
        data={'refinement': 'also include climate stories', 'csrf_token': 'test'},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        b = db.session.get(Briefing, briefing_id)
        # Original preserved, new appended after separator.
        assert b.custom_prompt.startswith('Focus on tech.')
        assert 'also include climate stories' in b.custom_prompt
        assert '\n\nRefinement:' in b.custom_prompt


def test_refine_truncates_oversize_note(app, db):
    with app.app_context():
        user = _seed_user(db, username='dave', email='dave@example.com')
        briefing = _seed_briefing(db, user)
        db.session.commit()
        user_id, briefing_id = user.id, briefing.id

    client = app.test_client()
    _login(client, user_id)

    huge_note = 'X' * 1000  # MAX_NOTE_CHARS is 500
    resp = client.post(
        f'/briefings/{briefing_id}/refine',
        data={'refinement': huge_note, 'csrf_token': 'test'},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        b = db.session.get(Briefing, briefing_id)
        # Truncated: the appendage portion can't exceed 500 chars.
        appended = b.custom_prompt.split('Refinement: ', 1)[1]
        assert len(appended) <= 500


def test_refine_blocked_for_non_owner(app, db):
    with app.app_context():
        owner = _seed_user(db, username='owner', email='owner@example.com')
        attacker = _seed_user(db, username='intruder', email='intruder@example.com')
        briefing = _seed_briefing(db, owner)
        db.session.commit()
        attacker_id, briefing_id = attacker.id, briefing.id

    client = app.test_client()
    _login(client, attacker_id)

    resp = client.post(
        f'/briefings/{briefing_id}/refine',
        data={'refinement': 'evil intent', 'csrf_token': 'test'},
        follow_redirects=False,
    )
    # Permission check returns a redirect, not the refinement.
    assert resp.status_code in (302, 403)

    with app.app_context():
        b = db.session.get(Briefing, briefing_id)
        assert b.custom_prompt is None or 'evil intent' not in b.custom_prompt
