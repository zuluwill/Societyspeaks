"""Admin user delete must keep audit events and still remove the account."""


def test_admin_delete_user_detaches_analytics_and_email_events(app, db, client):
    from app.models import AnalyticsEvent, EmailEvent, User

    admin = User(username='deleter', email='deleter@example.com', password='hashed', is_admin=True)
    target = User(username='spamtarget', email='spamtarget@example.com', password='hashed')
    db.session.add_all([admin, target])
    db.session.flush()
    db.session.add(AnalyticsEvent(event_name='user_signed_up', user_id=target.id))
    db.session.add(EmailEvent(
        recipient_email=target.email,
        email_category='auth',
        event_type='sent',
        user_id=target.id,
    ))
    db.session.commit()
    target_id = target.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['_fresh'] = True

    resp = client.post(f'/admin/users/{target_id}/delete', follow_redirects=False)
    assert resp.status_code == 302
    assert db.session.get(User, target_id) is None
    assert AnalyticsEvent.query.filter_by(user_id=target_id).count() == 0
    assert AnalyticsEvent.query.filter_by(event_name='user_signed_up').count() == 1
    assert EmailEvent.query.filter_by(recipient_email='spamtarget@example.com').one().user_id is None
