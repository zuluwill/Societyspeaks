from unittest.mock import MagicMock, patch


def _create_partner(db, email='partner@example.com'):
    from app.models import Partner

    partner = Partner(
        name='Partner Co',
        slug='partner-co',
        contact_email=email,
        password_hash='fakehash',
        status='active',
        billing_status='inactive',
        tier='free',
    )
    db.session.add(partner)
    db.session.commit()
    return partner


class _FakeCheckoutSession:
    def __init__(self, customer, subscription=None, metadata=None):
        self.customer = customer
        self.subscription = subscription
        self.metadata = metadata or {}

    def get(self, key, default=None):
        return self.metadata if key == 'metadata' else default


def test_portal_billing_success_does_not_bind_mismatched_customer(app, db):
    partner = _create_partner(db)
    client = app.test_client()

    with client.session_transaction() as flask_session:
        flask_session['partner_portal_id'] = partner.id

    fake_checkout = _FakeCheckoutSession(
        customer='cus_other',
        subscription=None,
        metadata={'partner_id': str(partner.id), 'purpose': 'partner_subscription'},
    )
    fake_stripe = MagicMock()
    fake_stripe.checkout.Session.retrieve.return_value = fake_checkout

    with patch('app.partner.routes.get_stripe', return_value=fake_stripe):
        response = client.get('/for-publishers/portal/billing/success?session_id=cs_test_mismatch')

    assert response.status_code == 302

    db.session.refresh(partner)
    assert partner.stripe_customer_id is None


def test_handle_partner_subscription_terminal_status_clears_subscription_id(app, db):
    from app.billing.routes import _handle_partner_subscription

    partner = _create_partner(db, email='partner2@example.com')
    partner.stripe_customer_id = 'cus_123'
    partner.stripe_subscription_id = 'sub_old'
    partner.billing_status = 'active'
    partner.tier = 'professional'
    db.session.commit()

    fake_stripe = MagicMock()
    fake_stripe.Subscription.retrieve.return_value = {
        'id': 'sub_old',
        'customer': 'cus_123',
        'status': 'canceled',
        'metadata': {
            'partner_id': str(partner.id),
            'partner_tier': 'professional',
            'purpose': 'partner_subscription',
        },
    }

    with app.app_context():
        with patch('app.billing.routes.get_stripe', return_value=fake_stripe):
            _handle_partner_subscription({'id': 'sub_old', 'customer': 'cus_123'})

    db.session.refresh(partner)
    assert partner.billing_status == 'inactive'
    assert partner.tier == 'free'
    assert partner.stripe_subscription_id is None


def test_partner_checkout_completed_webhook_syncs_partner_state(app, db):
    from app.billing.routes import _handle_partner_checkout_completed

    partner = _create_partner(db, email='partner3@example.com')

    fake_stripe = MagicMock()
    fake_stripe.Subscription.retrieve.return_value = {
        'id': 'sub_new',
        'customer': 'cus_new',
        'status': 'active',
        'metadata': {
            'partner_id': str(partner.id),
            'partner_tier': 'starter',
            'purpose': 'partner_subscription',
        },
    }

    checkout_data = {
        'id': 'cs_test_complete',
        'customer': 'cus_new',
        'subscription': 'sub_new',
        'metadata': {
            'partner_id': str(partner.id),
            'partner_tier': 'starter',
            'purpose': 'partner_subscription',
        },
    }

    with app.app_context():
        with patch('app.billing.routes.get_stripe', return_value=fake_stripe):
            _handle_partner_checkout_completed(checkout_data)

    db.session.refresh(partner)
    assert partner.stripe_customer_id == 'cus_new'
    assert partner.stripe_subscription_id == 'sub_new'
    assert partner.billing_status == 'active'
    assert partner.tier == 'starter'
