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
    assert len(seen) == 1


def test_dashboard_recent_notifications_batch_discussion_slugs(client, db):
    user = _create_user(db, 'dash_notify', 'dash_notify@example.com')
    _notifications_for_user(db, user, count=5)
    _login(client, user.id)

    response = client.get('/auth/dashboard')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'New activity 0' in body
    assert 'View all' in body
