from app.models import User


def _create_user(db, username, email, verified=False):
    user = User(
        username=username,
        email=email,
        password='hashed-password',
        email_verified=verified,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_resend_verification_authenticated_ignores_posted_email(app, db, monkeypatch):
    with app.app_context():
        actor = _create_user(db, 'actor_user', 'actor@example.com', verified=False)
        victim = _create_user(db, 'victim_user', 'victim@example.com', verified=False)
        db.session.commit()
        actor_id = actor.id
        victim_email = victim.email

    sent_to = []

    def _fake_send_verification_email(user, verification_url):  # noqa: ARG001
        sent_to.append(user.email)

    monkeypatch.setattr('app.auth.routes.send_verification_email', _fake_send_verification_email)
    monkeypatch.setattr(User, 'get_email_verification_token', lambda self: 'test-token')

    client = app.test_client()
    _login(client, actor_id)
    response = client.post(
        '/auth/resend-verification',
        data={'email': victim_email},
        headers={'Referer': 'http://localhost/platform'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'] == 'http://localhost/platform'
    assert sent_to == ['actor@example.com']


def test_resend_verification_unauthenticated_uses_posted_email(app, db, monkeypatch):
    with app.app_context():
        target = _create_user(db, 'target_user', 'target@example.com', verified=False)
        db.session.commit()
        target_email = target.email

    sent_to = []

    def _fake_send_verification_email(user, verification_url):  # noqa: ARG001
        sent_to.append(user.email)

    monkeypatch.setattr('app.auth.routes.send_verification_email', _fake_send_verification_email)
    monkeypatch.setattr(User, 'get_email_verification_token', lambda self: 'test-token')

    client = app.test_client()
    response = client.post(
        '/auth/resend-verification',
        data={'email': target_email},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/auth/login')
    assert sent_to == ['target@example.com']
