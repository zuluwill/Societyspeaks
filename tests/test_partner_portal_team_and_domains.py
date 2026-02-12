from datetime import datetime, timedelta
from unittest.mock import patch


def _create_partner_with_owner(db, email='owner@example.com'):
    from app.models import Partner, PartnerMember

    partner = Partner(
        name='Team Partner',
        slug='team-partner',
        contact_email=email,
        password_hash='fakehash',
        status='active',
        billing_status='inactive',
        tier='free',
    )
    partner.set_password('ValidPass123!')
    db.session.add(partner)
    db.session.flush()

    owner = PartnerMember(
        partner_id=partner.id,
        email=email,
        full_name='Owner User',
        role='owner',
        status='active',
        accepted_at=datetime.utcnow(),
    )
    owner.set_password('ValidPass123!')
    db.session.add(owner)
    db.session.commit()
    return partner, owner


def test_is_partner_origin_allowed_rejects_inactive_domain(app, db):
    from app.models import PartnerDomain
    from app.api.utils import is_partner_origin_allowed

    partner, _ = _create_partner_with_owner(db, email='origin-owner@example.com')
    domain = PartnerDomain(
        partner_id=partner.id,
        domain='inactive.example.com',
        env='live',
        verification_method='dns_txt',
        verification_token='tok_domain',
        verified_at=datetime.utcnow(),
        is_active=False,
    )
    db.session.add(domain)
    db.session.commit()

    with app.app_context():
        assert is_partner_origin_allowed('https://inactive.example.com') is False


def test_invite_member_and_accept_invite_flow(app, db):
    from app.models import PartnerMember

    partner, owner = _create_partner_with_owner(db)
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session['partner_portal_id'] = partner.id
        flask_session['partner_member_id'] = owner.id

    with patch('app.partner.routes._send_partner_member_invite_email', return_value={'id': 'email_123'}):
        invite_response = client.post(
            '/for-publishers/portal/team/invite',
            data={'email': 'teammate@example.com', 'role': 'member', 'full_name': 'Teammate User'},
            follow_redirects=False,
        )
    assert invite_response.status_code == 302

    invited = PartnerMember.query.filter_by(email='teammate@example.com', partner_id=partner.id).first()
    assert invited is not None
    assert invited.status == 'pending'
    assert invited.invite_token

    accept_response = client.post(
        f'/for-publishers/portal/team/accept/{invited.invite_token}',
        data={'full_name': 'Teammate User', 'password': 'AnotherPass123!'},
        follow_redirects=False,
    )
    assert accept_response.status_code == 302

    db.session.refresh(invited)
    assert invited.status == 'active'
    assert invited.accepted_at is not None
    assert invited.invite_token is None


def test_disabled_member_is_forced_to_reauthenticate(app, db):
    from app.models import PartnerMember

    partner, owner = _create_partner_with_owner(db, email='owner2@example.com')
    member = PartnerMember(
        partner_id=partner.id,
        email='member2@example.com',
        full_name='Member Two',
        role='member',
        status='active',
        accepted_at=datetime.utcnow(),
    )
    member.set_password('MemberPass123!')
    db.session.add(member)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session['partner_portal_id'] = partner.id
        flask_session['partner_member_id'] = member.id

    member.status = 'disabled'
    db.session.commit()

    response = client.get('/for-publishers/portal/dashboard', follow_redirects=False)
    assert response.status_code == 302
    assert '/for-publishers/portal/login' in response.location


def test_invite_token_expiry_blocks_acceptance(app, db):
    from app.models import PartnerMember

    partner, owner = _create_partner_with_owner(db, email='owner3@example.com')
    stale_member = PartnerMember(
        partner_id=partner.id,
        email='stale-invite@example.com',
        full_name='Stale Invite',
        role='member',
        status='pending',
        invite_token='stale-token-123',
        invited_at=datetime.utcnow() - timedelta(days=10),
    )
    db.session.add(stale_member)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session['partner_portal_id'] = partner.id
        flask_session['partner_member_id'] = owner.id

    response = client.post(
        f'/for-publishers/portal/team/accept/{stale_member.invite_token}',
        data={'full_name': 'Stale Invite', 'password': 'AnotherPass123!'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert '/for-publishers/portal/login' in response.location


def test_owner_login_uses_partner_password_source(app, db):
    partner, owner = _create_partner_with_owner(db, email='owner4@example.com')
    owner.set_password('OldOwnerPass123!')
    partner.set_password('NewPartnerPass123!')
    db.session.commit()

    client = app.test_client()
    response = client.post(
        '/for-publishers/portal/login',
        data={'email': partner.contact_email, 'password': 'NewPartnerPass123!'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert '/for-publishers/portal/dashboard' in response.location
    db.session.refresh(owner)
    db.session.refresh(partner)
    assert owner.password_hash == partner.password_hash
