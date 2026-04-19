"""Moderation queue access: owner and site admin (aligned with discussion templates)."""

from app.models import Discussion, User, generate_slug


def _create_user(db, username, email, *, is_admin=False):
    user = User(username=username, email=email, password='hashed-password')
    if is_admin:
        user.is_admin = True
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_moderation_queue_allows_owner(app, db):
    with app.app_context():
        owner = _create_user(db, 'modowner1', 'modowner1@example.com')
        discussion = Discussion(
            title='Mod perm owner',
            slug=generate_slug('Mod perm owner'),
            creator_id=owner.id,
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.commit()
        did, slug = discussion.id, discussion.slug

    client = app.test_client()
    _login(client, owner.id)
    resp = client.get(f'/discussions/{did}/moderation', follow_redirects=False)
    assert resp.status_code == 200


def test_moderation_queue_allows_site_admin_not_owner(app, db):
    with app.app_context():
        owner = _create_user(db, 'modowner2', 'modowner2@example.com')
        admin = _create_user(db, 'modadmin1', 'modadmin1@example.com', is_admin=True)
        discussion = Discussion(
            title='Mod perm admin',
            slug=generate_slug('Mod perm admin'),
            creator_id=owner.id,
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.commit()
        did = discussion.id

    client = app.test_client()
    _login(client, admin.id)
    resp = client.get(f'/discussions/{did}/moderation', follow_redirects=False)
    assert resp.status_code == 200


def test_moderation_queue_denies_non_owner_non_admin(app, db):
    with app.app_context():
        owner = _create_user(db, 'modowner3', 'modowner3@example.com')
        stranger = _create_user(db, 'modstranger', 'modstranger@example.com')
        discussion = Discussion(
            title='Mod perm stranger',
            slug=generate_slug('Mod perm stranger'),
            creator_id=owner.id,
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.commit()
        did, slug = discussion.id, discussion.slug

    client = app.test_client()
    _login(client, stranger.id)
    resp = client.get(f'/discussions/{did}/moderation', follow_redirects=False)
    assert resp.status_code == 302
    assert f'/discussions/{did}/{slug}' in resp.headers.get('Location', '')


def test_moderation_summary_api_allows_admin(app, db):
    with app.app_context():
        owner = _create_user(db, 'modowner4', 'modowner4@example.com')
        admin = _create_user(db, 'modadmin2', 'modadmin2@example.com', is_admin=True)
        discussion = Discussion(
            title='Mod API admin',
            slug=generate_slug('Mod API admin'),
            creator_id=owner.id,
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.commit()
        did = discussion.id

    client = app.test_client()
    _login(client, admin.id)
    resp = client.get(f'/api/discussions/{did}/moderation/summary')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'pending_flags' in data
