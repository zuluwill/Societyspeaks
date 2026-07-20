"""Admin visibility for brief subscriber delivery health."""

from app.models import DailyBriefSubscriber, User


def _seed_admin(db):
    user = User(
        username='brief_admin',
        email='brief-admin@example.com',
        password='hashed',
        email_verified=True,
        is_admin=True,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_subscribers_at_risk_filter(app, db, client):
    with app.app_context():
        admin = _seed_admin(db)
        healthy = DailyBriefSubscriber(email='healthy@example.com', status='active', magic_token='m1')
        at_risk = DailyBriefSubscriber(
            email='risky@example.com',
            status='active',
            magic_token='m2',
            send_failure_count=2,
        )
        bounced = DailyBriefSubscriber(
            email='dead@example.com',
            status='bounced',
            magic_token='m3',
            send_failure_count=3,
        )
        db.session.add_all([healthy, at_risk, bounced])
        db.session.commit()

        _login(client, admin.id)
        resp = client.get('/admin/brief/subscribers?delivery=at_risk')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'risky@example.com' in body
        assert 'healthy@example.com' not in body
        assert 'dead@example.com' not in body


def test_clear_send_failures_resets_counter(app, db, client):
    with app.app_context():
        admin = _seed_admin(db)
        sub = DailyBriefSubscriber(
            email='recover@example.com',
            status='active',
            magic_token='m4',
            send_failure_count=2,
        )
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id

        _login(client, admin.id)
        resp = client.post(f'/admin/brief/subscribers/{sub_id}/clear-send-failures', follow_redirects=False)
        assert resp.status_code in (302, 303)

        refreshed = db.session.get(DailyBriefSubscriber, sub_id)
        assert refreshed.send_failure_count == 0
