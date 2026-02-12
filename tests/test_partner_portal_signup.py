"""
Regression tests for partner portal signup hardening.
"""

import pytest

from app.models import Partner, PartnerMember


@pytest.fixture
def client(app, db):
    """Flask test client with database tables created."""
    return app.test_client()


class TestPartnerPortalSignup:
    def test_signup_success_creates_partner_owner_and_test_key(self, client, db):
        resp = client.post(
            '/for-publishers/portal/signup',
            data={
                'name': 'Guardian Labs',
                'email': 'new-publisher@example.com',
                'password': 'ValidPass123',
                'domain': 'guardian.example',
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert '/for-publishers/portal/dashboard' in resp.location

        partner = Partner.query.filter_by(contact_email='new-publisher@example.com').first()
        assert partner is not None
        assert partner.status == 'active'

        owner = PartnerMember.query.filter_by(partner_id=partner.id, role='owner').first()
        assert owner is not None
        assert owner.email == 'new-publisher@example.com'
        assert partner.api_keys.count() == 1

    def test_signup_with_existing_member_email_redirects_to_login(self, client, db):
        existing_partner = Partner(
            name='Existing Publisher',
            slug='existing-publisher',
            contact_email='owner-existing@example.com',
            status='active',
            billing_status='inactive',
        )
        existing_partner.set_password('OwnerPass123')
        db.session.add(existing_partner)
        db.session.flush()

        invited_member = PartnerMember(
            partner_id=existing_partner.id,
            email='invitee@example.com',
            role='member',
            status='pending',
        )
        db.session.add(invited_member)
        db.session.commit()

        resp = client.post(
            '/for-publishers/portal/signup',
            data={
                'name': 'Duplicate Signup',
                'email': 'invitee@example.com',
                'password': 'ValidPass123',
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert '/for-publishers/portal/login' in resp.location
        assert Partner.query.count() == 1
        assert Partner.query.filter_by(contact_email='invitee@example.com').first() is None
