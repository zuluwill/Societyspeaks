"""Notification lists must not load a Discussion row per item.

Sentry PYTHON-FLASK-JJ on ``auth.notifications``: the template needs
``notification.discussion.slug`` for permalinks, and each access issued
its own full Discussion SELECT. Batch the slug with selectinload.
"""

from sqlalchemy import event

from app.models import Discussion, Notification, User, generate_slug


def _create_user(db, username, email):
    user = User(username=username, email=email, password='hashed-password')
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _notifications_for_user(db, user, count=6):
    rows = []
    for i in range(count):
        discussion = Discussion(
            title=f'Notified discussion {i}',
            slug=generate_slug(f'Notified discussion {i} {user.id}'),
            creator_id=user.id,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.flush()
        note = Notification(
            user_id=user.id,
            discussion_id=discussion.id,
            type='new_response',
            title=f'New activity {i}',
            message=f'Someone replied on discussion {i}.',
            is_read=False,
        )
        db.session.add(note)
        rows.append((discussion, note))
    db.session.commit()
    return rows


def _count_discussion_selects(db, callback):
    seen = []

    def _record(conn, cursor, statement, params, context, executemany):
        sql = statement.lower()
        if 'from discussion' in sql and 'select' in sql:
            seen.append(statement)

    event.listen(db.engine, 'before_cursor_execute', _record)
    try:
        return callback(), seen
    finally:
        event.remove(db.engine, 'before_cursor_execute', _record)


def test_query_for_user_loads_slugs_in_one_query(db):
    user = _create_user(db, 'notify_unit', 'notify_unit@example.com')
    rows = _notifications_for_user(db, user, count=6)
    db.session.expire_all()

    def _access():
        notes = Notification.query_for_user(user.id).all()
        return [note.discussion.slug for note in notes]

    slugs, seen = _count_discussion_selects(db, _access)
    assert slugs == [row[0].slug for row in rows]
    assert len(seen) == 1
    assert 'in (' in seen[0].lower() or 'in(' in seen[0].lower()


def test_plain_notification_list_also_batches_discussions(db):
    """lazy='selectin' is the safety net if a caller skips query_for_user."""
    user = _create_user(db, 'notify_plain', 'notify_plain@example.com')
    _notifications_for_user(db, user, count=6)
    db.session.expire_all()

    def _access():
        notes = Notification.query.filter_by(user_id=user.id).all()
        return [note.discussion.slug for note in notes]

    slugs, seen = _count_discussion_selects(db, _access)
    assert len(slugs) == 6
    assert len(seen) == 1


def test_notifications_page_does_not_n_plus_one_discussions(client, db):
    user = _create_user(db, 'notify_reader', 'notify_reader@example.com')
    rows = _notifications_for_user(db, user, count=6)
    _login(client, user.id)

    response, seen = _count_discussion_selects(
        db, lambda: client.get('/auth/dashboard/notifications')
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'New activity 0' in body
    assert rows[0][0].slug in body
    assert '6 notification' in body
    assert '6 unread' in body
    assert len(seen) == 1


def test_notifications_page_paginates_without_n_plus_one(client, db):
    user = _create_user(db, 'notify_page', 'notify_page@example.com')
    _notifications_for_user(db, user, count=21)
    _login(client, user.id)

    first, first_seen = _count_discussion_selects(
        db, lambda: client.get('/auth/dashboard/notifications')
    )
    second, second_seen = _count_discussion_selects(
        db, lambda: client.get('/auth/dashboard/notifications?page=2')
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert 'Next' in first.get_data(as_text=True)
    assert len(first_seen) == 1
    assert len(second_seen) == 1


def test_dashboard_recent_notifications_batch_discussion_slugs(client, db):
    user = _create_user(db, 'dash_notify', 'dash_notify@example.com')
    rows = _notifications_for_user(db, user, count=5)
    db.session.expire_all()

    def _access():
        notes = Notification.query_for_user(user.id).order_by(
            Notification.created_at.desc(),
            Notification.id.desc(),
        ).limit(5).all()
        return [note.discussion.slug for note in notes]

    slugs, seen = _count_discussion_selects(db, _access)
    assert slugs
    assert rows[0][0].slug in slugs
    assert len(seen) == 1

    _login(client, user.id)
    response = client.get('/auth/dashboard')
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'New activity 0' in body
    assert 'View all' in body


def test_mark_one_and_all_notifications_read(client, db):
    user = _create_user(db, 'notify_read', 'notify_read@example.com')
    rows = _notifications_for_user(db, user, count=3)
    _login(client, user.id)

    first_id = rows[0][1].id
    resp = client.post(f'/auth/dashboard/notifications/{first_id}/read', follow_redirects=False)
    assert resp.status_code in (302, 303)

    remaining = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    assert remaining == 2

    resp = client.post('/auth/dashboard/notifications/read-all', follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert Notification.unread_count_for_user(user.id) == 0
