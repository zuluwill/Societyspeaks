from datetime import datetime
from app.lib.time import utcnow_naive


def _create_admin_user(db):
    from app.models import User
    admin = User(
        username='admin-preview',
        email='admin-preview@example.com',
        is_admin=True,
    )
    admin.set_password('AdminPass123!')
    db.session.add(admin)
    db.session.commit()
    return admin


def _create_partner(db):
    from app.models import Partner, PartnerMember
    partner = Partner(
        name='Preview Partner',
        slug='preview-partner',
        contact_email='owner-preview@example.com',
        status='active',
        billing_status='inactive',
        tier='free',
        password_hash='placeholder',
    )
    partner.set_password('OwnerPass123!')
    db.session.add(partner)
    db.session.flush()
    owner = PartnerMember(
        partner_id=partner.id,
        email=partner.contact_email,
        full_name='Owner Preview',
        role='owner',
        status='active',
        accepted_at=utcnow_naive(),
        password_hash=partner.password_hash,
    )
    db.session.add(owner)
    db.session.commit()
    return partner


def _login_admin(client, admin_user):
    with client.session_transaction() as flask_session:
        flask_session['_user_id'] = str(admin_user.id)
        flask_session['_fresh'] = True


def test_preview_start_and_stop_logs_audit_events(app, db):
    from app.models import AdminAuditEvent
    admin = _create_admin_user(db)
    partner = _create_partner(db)
    client = app.test_client()
    _login_admin(client, admin)

    start_resp = client.post(f'/admin/partners/{partner.id}/preview', follow_redirects=False)
    assert start_resp.status_code == 302
    assert '/for-publishers/portal/dashboard' in start_resp.location

    start_event = AdminAuditEvent.query.filter_by(action='partner_preview_started', target_id=partner.id).first()
    assert start_event is not None
    assert start_event.admin_user_id == admin.id

    stop_resp = client.post('/admin/partners/preview/stop', follow_redirects=False)
    assert stop_resp.status_code == 302
    assert '/admin/partners' in stop_resp.location
    stop_event = AdminAuditEvent.query.filter_by(action='partner_preview_stopped', target_id=partner.id).first()
    assert stop_event is not None


def test_preview_mode_blocks_partner_writes(app, db):
    from app.models import AdminAuditEvent, PartnerApiKey
    admin = _create_admin_user(db)
    partner = _create_partner(db)
    client = app.test_client()
    _login_admin(client, admin)
    client.post(f'/admin/partners/{partner.id}/preview', follow_redirects=False)

    before_count = PartnerApiKey.query.filter_by(partner_id=partner.id).count()
    resp = client.post('/for-publishers/portal/keys/create', data={'env': 'test'}, follow_redirects=False)
    assert resp.status_code == 302
    assert '/for-publishers/portal/dashboard' in resp.location
    after_count = PartnerApiKey.query.filter_by(partner_id=partner.id).count()
    assert after_count == before_count

    blocked_event = AdminAuditEvent.query.filter_by(
        action='partner_preview_write_blocked',
        target_id=partner.id
    ).first()
    assert blocked_event is not None
